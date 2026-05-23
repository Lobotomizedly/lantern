"""
Deduplication Stage

Implements multi-level deduplication:
- Hash-based deduplication (URL-normalized + content shingle)
- Semantic near-duplicate detection using embedding similarity
- Collapse wire-service reprints to single Item with multiple source refs
"""

import hashlib
import re
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from uuid import UUID

import numpy as np
import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    RetryableError,
    NonRetryableError,
)


class URLNormalizer:
    """Normalizes URLs for consistent deduplication."""

    # Query parameters to strip (tracking params)
    STRIP_PARAMS = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "ref",
        "source",
        "mc_cid",
        "mc_eid",
        "_ga",
        "_gl",
    }

    @classmethod
    def normalize(cls, url: str) -> str:
        """
        Normalize URL for deduplication.

        Args:
            url: Raw URL

        Returns:
            Normalized URL
        """
        if not url:
            return ""

        # Parse URL
        parsed = urlparse(url.lower().strip())

        # Normalize scheme
        scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme

        # Normalize netloc (remove www prefix)
        netloc = parsed.netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Normalize path (remove trailing slash)
        path = parsed.path.rstrip("/") or "/"

        # Filter query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=False)
        filtered_params = {
            k: v
            for k, v in query_params.items()
            if k.lower() not in cls.STRIP_PARAMS
        }
        # Sort params for consistency
        query = urlencode(sorted(filtered_params.items()), doseq=True)

        # Reconstruct URL (without fragment)
        normalized = urlunparse((scheme, netloc, path, "", query, ""))

        return normalized


class ContentShingler:
    """
    Creates shingles (n-grams) from text for near-duplicate detection.

    Uses MinHash for efficient similarity estimation.
    """

    def __init__(
        self,
        shingle_size: int = 5,
        num_hashes: int = 128,
    ):
        """
        Initialize shingler.

        Args:
            shingle_size: Number of words per shingle
            num_hashes: Number of hash functions for MinHash
        """
        self.shingle_size = shingle_size
        self.num_hashes = num_hashes

        # Pre-generate hash coefficients for MinHash
        np.random.seed(42)
        self.hash_a = np.random.randint(1, 2**31 - 1, size=num_hashes)
        self.hash_b = np.random.randint(0, 2**31 - 1, size=num_hashes)
        self.prime = 2**31 - 1

    def create_shingles(self, text: str) -> set[str]:
        """
        Create word shingles from text.

        Args:
            text: Input text

        Returns:
            Set of shingle strings
        """
        # Normalize text
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        words = text.split()

        if len(words) < self.shingle_size:
            return {" ".join(words)}

        shingles = set()
        for i in range(len(words) - self.shingle_size + 1):
            shingle = " ".join(words[i : i + self.shingle_size])
            shingles.add(shingle)

        return shingles

    def compute_minhash(self, shingles: set[str]) -> list[int]:
        """
        Compute MinHash signature for a set of shingles.

        Args:
            shingles: Set of shingle strings

        Returns:
            MinHash signature (list of hash values)
        """
        if not shingles:
            return [0] * self.num_hashes

        # Convert shingles to hash values
        shingle_hashes = [
            int(hashlib.md5(s.encode()).hexdigest(), 16) % self.prime
            for s in shingles
        ]

        # Compute MinHash signature
        signature = []
        for i in range(self.num_hashes):
            min_hash = float("inf")
            for h in shingle_hashes:
                hash_val = (self.hash_a[i] * h + self.hash_b[i]) % self.prime
                min_hash = min(min_hash, hash_val)
            signature.append(int(min_hash))

        return signature

    def estimate_similarity(
        self, sig1: list[int], sig2: list[int]
    ) -> float:
        """
        Estimate Jaccard similarity from MinHash signatures.

        Args:
            sig1: First MinHash signature
            sig2: Second MinHash signature

        Returns:
            Estimated Jaccard similarity (0-1)
        """
        if len(sig1) != len(sig2):
            raise ValueError("Signatures must have same length")

        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)


class DedupStage(PipelineStage):
    """
    Pipeline stage for deduplication.

    Implements multi-level deduplication:
    1. URL-based exact match
    2. Content hash exact match
    3. MinHash near-duplicate detection
    4. Semantic similarity (embedding-based)
    """

    stage_name = "dedup"
    next_stage = "embed"

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)

        # Dedup configuration
        self.url_dedup_enabled = self.config.get("url_dedup_enabled", True)
        self.content_dedup_enabled = self.config.get("content_dedup_enabled", True)
        self.minhash_dedup_enabled = self.config.get("minhash_dedup_enabled", True)
        self.semantic_dedup_enabled = self.config.get("semantic_dedup_enabled", True)

        # Similarity thresholds
        self.minhash_threshold = self.config.get("minhash_threshold", 0.8)
        self.semantic_threshold = self.config.get("semantic_threshold", 0.95)

        # Redis key prefixes for dedup indices
        self.url_index_prefix = "lantern:dedup:url:"
        self.hash_index_prefix = "lantern:dedup:hash:"
        self.minhash_index_prefix = "lantern:dedup:minhash:"

        # Initialize shingler
        self.shingler = ContentShingler(
            shingle_size=self.config.get("shingle_size", 5),
            num_hashes=self.config.get("num_minhashes", 128),
        )

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Process item for deduplication.

        Args:
            context: Pipeline context with clean_text

        Returns:
            Updated context with dedup info
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for deduplication",
                self.stage_name,
                context.item_id,
            )

        # Step 1: URL-based dedup
        if self.url_dedup_enabled and context.url:
            duplicate = await self._check_url_duplicate(context)
            if duplicate:
                return self._mark_as_duplicate(context, duplicate, "url")

        # Step 2: Content hash dedup
        content_hash = self._compute_content_hash(context.clean_text)
        context.dedup_hash = content_hash

        if self.content_dedup_enabled:
            duplicate = await self._check_hash_duplicate(content_hash)
            if duplicate:
                return self._mark_as_duplicate(context, duplicate, "hash")

        # Step 3: MinHash near-duplicate detection
        if self.minhash_dedup_enabled:
            duplicate = await self._check_minhash_duplicate(context)
            if duplicate:
                return await self._handle_near_duplicate(context, duplicate)

        # Step 4: Semantic duplicate detection (deferred to after embedding)
        # This will be checked again after embed stage if enabled

        # Store dedup indices for future lookups
        await self._store_dedup_indices(context, content_hash)

        self.logger.info(f"Item {context.item_id} passed deduplication (hash={content_hash[:16]}...)")

        return context

    def _compute_content_hash(self, text: str) -> str:
        """
        Compute content hash for exact duplicate detection.

        Uses normalized text to ignore minor formatting differences.

        Args:
            text: Clean text content

        Returns:
            SHA-256 hash of normalized content
        """
        # Normalize for hashing
        normalized = text.lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"[^\w\s]", "", normalized)
        normalized = normalized.strip()

        return hashlib.sha256(normalized.encode()).hexdigest()

    async def _check_url_duplicate(
        self, context: PipelineContext
    ) -> Optional[UUID]:
        """
        Check for URL-based duplicate.

        Args:
            context: Pipeline context

        Returns:
            Item ID of duplicate or None
        """
        if not context.url:
            return None

        normalized_url = URLNormalizer.normalize(context.url)
        url_hash = hashlib.sha256(normalized_url.encode()).hexdigest()

        # Check Redis index
        existing = await self.redis.get(f"{self.url_index_prefix}{url_hash}")
        if existing:
            return UUID(existing.decode())

        return None

    async def _check_hash_duplicate(self, content_hash: str) -> Optional[UUID]:
        """
        Check for content hash duplicate.

        Args:
            content_hash: Content hash to check

        Returns:
            Item ID of duplicate or None
        """
        existing = await self.redis.get(f"{self.hash_index_prefix}{content_hash}")
        if existing:
            return UUID(existing.decode())

        return None

    async def _check_minhash_duplicate(
        self, context: PipelineContext
    ) -> Optional[tuple[UUID, float]]:
        """
        Check for near-duplicate using MinHash.

        Args:
            context: Pipeline context

        Returns:
            Tuple of (item_id, similarity) or None
        """
        # Create shingles and MinHash signature
        shingles = self.shingler.create_shingles(context.clean_text)
        signature = self.shingler.compute_minhash(shingles)

        # Use LSH bands for efficient lookup
        # Split signature into bands
        num_bands = 16
        rows_per_band = len(signature) // num_bands

        candidates: set[str] = set()

        for band_idx in range(num_bands):
            start = band_idx * rows_per_band
            end = start + rows_per_band
            band_hash = hashlib.md5(
                str(signature[start:end]).encode()
            ).hexdigest()

            band_key = f"{self.minhash_index_prefix}band:{band_idx}:{band_hash}"
            members = await self.redis.smembers(band_key)
            candidates.update(m.decode() for m in members)

        # Check actual similarity for candidates
        for candidate_id in candidates:
            if candidate_id == str(context.item_id):
                continue

            # Get candidate's signature
            sig_key = f"{self.minhash_index_prefix}sig:{candidate_id}"
            stored_sig = await self.redis.get(sig_key)

            if stored_sig:
                candidate_sig = [int(x) for x in stored_sig.decode().split(",")]
                similarity = self.shingler.estimate_similarity(signature, candidate_sig)

                if similarity >= self.minhash_threshold:
                    return (UUID(candidate_id), similarity)

        return None

    async def _handle_near_duplicate(
        self,
        context: PipelineContext,
        duplicate_info: tuple[UUID, float],
    ) -> PipelineContext:
        """
        Handle near-duplicate detection (e.g., wire service reprint).

        Creates a link between items rather than rejecting.

        Args:
            context: Pipeline context
            duplicate_info: Tuple of (original_item_id, similarity)

        Returns:
            Updated context
        """
        original_id, similarity = duplicate_info

        self.logger.info(
            f"Near-duplicate detected: {context.item_id} similar to {original_id} "
            f"(similarity={similarity:.3f})"
        )

        # Mark as duplicate but continue processing
        # This allows tracking multiple sources for the same content
        context.is_duplicate = True
        context.canonical_item_id = original_id

        # Store source reference linking this item to the original
        await self._link_duplicate_sources(context, original_id)

        return context

    async def _link_duplicate_sources(
        self, context: PipelineContext, original_id: UUID
    ) -> None:
        """
        Link duplicate item to original as an alternative source.

        Args:
            context: Pipeline context of duplicate
            original_id: ID of original item
        """
        # Store in Redis for later batch processing
        link_key = f"lantern:dedup:links:{original_id}"
        await self.redis.sadd(
            link_key,
            f"{context.item_id}:{context.source_id or 'unknown'}",
        )

        # Also store reverse lookup
        reverse_key = f"lantern:dedup:canonical:{context.item_id}"
        await self.redis.set(reverse_key, str(original_id))

    def _mark_as_duplicate(
        self,
        context: PipelineContext,
        original_id: UUID,
        method: str,
    ) -> PipelineContext:
        """
        Mark item as exact duplicate.

        Args:
            context: Pipeline context
            original_id: ID of original item
            method: Deduplication method that found duplicate

        Returns:
            Updated context
        """
        self.logger.info(
            f"Exact duplicate detected ({method}): "
            f"{context.item_id} duplicates {original_id}"
        )

        context.is_duplicate = True
        context.canonical_item_id = original_id

        return context

    async def _store_dedup_indices(
        self, context: PipelineContext, content_hash: str
    ) -> None:
        """
        Store deduplication indices for this item.

        Args:
            context: Pipeline context
            content_hash: Content hash
        """
        item_id_str = str(context.item_id)
        ttl = 86400 * 30  # 30 days

        # Store URL index
        if context.url:
            normalized_url = URLNormalizer.normalize(context.url)
            url_hash = hashlib.sha256(normalized_url.encode()).hexdigest()
            await self.redis.setex(
                f"{self.url_index_prefix}{url_hash}",
                ttl,
                item_id_str,
            )

        # Store content hash index
        await self.redis.setex(
            f"{self.hash_index_prefix}{content_hash}",
            ttl,
            item_id_str,
        )

        # Store MinHash signature and LSH bands
        if self.minhash_dedup_enabled:
            shingles = self.shingler.create_shingles(context.clean_text)
            signature = self.shingler.compute_minhash(shingles)

            # Store full signature
            sig_key = f"{self.minhash_index_prefix}sig:{item_id_str}"
            await self.redis.setex(
                sig_key,
                ttl,
                ",".join(str(x) for x in signature),
            )

            # Store LSH band hashes
            num_bands = 16
            rows_per_band = len(signature) // num_bands

            for band_idx in range(num_bands):
                start = band_idx * rows_per_band
                end = start + rows_per_band
                band_hash = hashlib.md5(
                    str(signature[start:end]).encode()
                ).hexdigest()

                band_key = f"{self.minhash_index_prefix}band:{band_idx}:{band_hash}"
                await self.redis.sadd(band_key, item_id_str)
                await self.redis.expire(band_key, ttl)

    async def check_semantic_duplicate(
        self,
        embedding: list[float],
        threshold: Optional[float] = None,
    ) -> Optional[tuple[UUID, float]]:
        """
        Check for semantic duplicate using embedding similarity.

        This is called after the embed stage generates embeddings.

        Args:
            embedding: Item embedding vector
            threshold: Similarity threshold (default: self.semantic_threshold)

        Returns:
            Tuple of (item_id, similarity) or None
        """
        if not self.semantic_dedup_enabled:
            return None

        threshold = threshold or self.semantic_threshold

        # Use pgvector for similarity search
        query = text("""
            SELECT id, embedding <=> :embedding AS distance
            FROM items
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> :embedding
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"embedding": embedding},
        )
        row = result.fetchone()

        if row:
            item_id, distance = row
            similarity = 1 - distance  # Convert distance to similarity

            if similarity >= threshold:
                return (UUID(str(item_id)), similarity)

        return None
