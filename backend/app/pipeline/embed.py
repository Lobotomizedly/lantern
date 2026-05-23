"""
Embed Stage

Generates embeddings for content items:
- Uses OpenAI text-embedding-3-small model
- Batch processing for efficiency
- Caches embeddings by dedup_hash
"""

import asyncio
from typing import Any, Optional
from uuid import UUID

import numpy as np
import redis.asyncio as redis
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    RetryableError,
    NonRetryableError,
)


class EmbeddingCache:
    """
    Cache for embeddings keyed by content dedup hash.

    Stores embeddings in Redis with TTL for memory management.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        prefix: str = "lantern:embedding:",
        ttl: int = 86400 * 7,  # 7 days
    ):
        self.redis = redis_client
        self.prefix = prefix
        self.ttl = ttl

    async def get(self, dedup_hash: str) -> Optional[list[float]]:
        """
        Get cached embedding by dedup hash.

        Args:
            dedup_hash: Content dedup hash

        Returns:
            Embedding vector or None if not cached
        """
        key = f"{self.prefix}{dedup_hash}"
        data = await self.redis.get(key)

        if data:
            # Parse comma-separated floats
            return [float(x) for x in data.decode().split(",")]

        return None

    async def set(self, dedup_hash: str, embedding: list[float]) -> None:
        """
        Cache embedding by dedup hash.

        Args:
            dedup_hash: Content dedup hash
            embedding: Embedding vector
        """
        key = f"{self.prefix}{dedup_hash}"
        # Store as comma-separated string for compactness
        value = ",".join(str(x) for x in embedding)
        await self.redis.setex(key, self.ttl, value)

    async def get_many(
        self, dedup_hashes: list[str]
    ) -> dict[str, Optional[list[float]]]:
        """
        Get multiple cached embeddings.

        Args:
            dedup_hashes: List of content dedup hashes

        Returns:
            Dict mapping hash to embedding (None if not cached)
        """
        if not dedup_hashes:
            return {}

        keys = [f"{self.prefix}{h}" for h in dedup_hashes]
        values = await self.redis.mget(keys)

        result = {}
        for hash_val, data in zip(dedup_hashes, values):
            if data:
                result[hash_val] = [float(x) for x in data.decode().split(",")]
            else:
                result[hash_val] = None

        return result


class OpenAIEmbedder:
    """
    Generates embeddings using OpenAI's API.

    Handles batching, rate limiting, and retries.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        max_batch_size: int = 100,
        max_tokens_per_batch: int = 8000,
    ):
        """
        Initialize embedder.

        Args:
            api_key: OpenAI API key
            model: Embedding model name
            dimensions: Output embedding dimensions
            max_batch_size: Maximum texts per API call
            max_tokens_per_batch: Approximate token limit per batch
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions
        self.max_batch_size = max_batch_size
        self.max_tokens_per_batch = max_tokens_per_batch

    async def embed_single(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = await self.embed_batch([text])
        return embeddings[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Split into smaller batches if needed
        batches = self._create_batches(texts)
        all_embeddings: list[list[float]] = []

        for batch in batches:
            embeddings = await self._embed_batch_with_retry(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def _create_batches(self, texts: list[str]) -> list[list[str]]:
        """
        Split texts into batches respecting size limits.

        Args:
            texts: All texts to batch

        Returns:
            List of text batches
        """
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_tokens = 0

        for text in texts:
            # Rough token estimation (4 chars per token)
            estimated_tokens = len(text) // 4

            if (
                len(current_batch) >= self.max_batch_size
                or current_tokens + estimated_tokens > self.max_tokens_per_batch
            ):
                if current_batch:
                    batches.append(current_batch)
                current_batch = [text]
                current_tokens = estimated_tokens
            else:
                current_batch.append(text)
                current_tokens += estimated_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    async def _embed_batch_with_retry(
        self,
        texts: list[str],
        max_retries: int = 3,
    ) -> list[list[float]]:
        """
        Embed a batch with retry logic.

        Args:
            texts: Texts to embed
            max_retries: Maximum retry attempts

        Returns:
            Embedding vectors
        """
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self.dimensions,
                )

                # Sort by index to maintain order
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return [item.embedding for item in sorted_data]

            except RateLimitError as e:
                last_error = e
                # Exponential backoff
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)

            except APIConnectionError as e:
                last_error = e
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)

            except APIError as e:
                # Non-retryable API errors
                raise NonRetryableError(
                    f"OpenAI API error: {e}",
                    "embed",
                )

        raise RetryableError(
            f"Failed to embed after {max_retries} attempts: {last_error}",
            "embed",
        )


class EmbedStage(PipelineStage):
    """
    Pipeline stage for generating embeddings.

    Generates embeddings using OpenAI's text-embedding-3-small model
    with caching by dedup_hash for efficiency.
    """

    stage_name = "embed"
    next_stage = "entity"

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)

        # Initialize OpenAI embedder
        api_key = self.config.get("openai_api_key")
        if not api_key and settings.openai_api_key:
            api_key = settings.openai_api_key.get_secret_value()

        if not api_key:
            raise ValueError("OpenAI API key required for embedding stage")

        self.embedder = OpenAIEmbedder(
            api_key=api_key,
            model=self.config.get("embedding_model", settings.openai_embedding_model),
            dimensions=self.config.get("embedding_dimensions", settings.embedding_dimensions),
            max_batch_size=self.config.get("batch_size", 100),
        )

        # Initialize cache
        self.cache = EmbeddingCache(
            redis_client=redis_client,
            ttl=self.config.get("cache_ttl", 86400 * 7),
        )

        # Chunking configuration
        self.max_text_length = self.config.get("max_text_length", 8000)
        self.chunk_overlap = self.config.get("chunk_overlap", 200)

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Generate embedding for item content.

        Args:
            context: Pipeline context with clean_text

        Returns:
            Updated context with embedding
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for embedding",
                self.stage_name,
                context.item_id,
            )

        # Check cache first
        if context.dedup_hash:
            cached = await self.cache.get(context.dedup_hash)
            if cached:
                self.logger.debug(f"Using cached embedding for item {context.item_id}")
                context.embedding = cached
                context.embedding_model = self.embedder.model
                return context

        # Generate embedding
        try:
            # Truncate or chunk text if too long
            text_for_embedding = self._prepare_text(context.clean_text)

            embedding = await self.embedder.embed_single(text_for_embedding)

            context.embedding = embedding
            context.embedding_model = self.embedder.model

            # Cache the embedding
            if context.dedup_hash:
                await self.cache.set(context.dedup_hash, embedding)

            # Store embedding in database
            await self._store_embedding(context)

            self.logger.info(
                f"Generated embedding for item {context.item_id} "
                f"(dims={len(embedding)})"
            )

        except RetryableError:
            raise
        except NonRetryableError:
            raise
        except Exception as e:
            raise RetryableError(
                f"Embedding generation failed: {e}",
                self.stage_name,
                context.item_id,
            )

        return context

    def _prepare_text(self, text: str) -> str:
        """
        Prepare text for embedding (truncate or create summary embedding).

        Args:
            text: Full text content

        Returns:
            Text suitable for embedding
        """
        if len(text) <= self.max_text_length:
            return text

        # For long texts, use beginning + end strategy
        # This captures both intro context and conclusions
        half_length = self.max_text_length // 2
        beginning = text[:half_length]
        end = text[-half_length:]

        return f"{beginning}\n\n[...]\n\n{end}"

    async def _store_embedding(self, context: PipelineContext) -> None:
        """
        Store embedding in the database.

        Args:
            context: Pipeline context with embedding
        """
        if not context.embedding:
            return

        try:
            # Update item with embedding
            # Using raw SQL for pgvector compatibility
            query = text("""
                UPDATE items
                SET embedding = :embedding,
                    embedding_model = :model,
                    updated_at = NOW()
                WHERE id = :item_id
            """)

            await self.db.execute(
                query,
                {
                    "item_id": str(context.item_id),
                    "embedding": context.embedding,
                    "model": context.embedding_model,
                },
            )
            await self.db.commit()

        except Exception as e:
            self.logger.error(f"Failed to store embedding: {e}")
            # Don't fail the whole pipeline for storage errors
            await self.db.rollback()

    async def process_batch(
        self, contexts: list[PipelineContext]
    ) -> list[PipelineContext]:
        """
        Process multiple items in a batch for efficiency.

        Args:
            contexts: List of pipeline contexts

        Returns:
            List of updated contexts
        """
        if not contexts:
            return []

        # Separate cached from uncached
        uncached_contexts: list[PipelineContext] = []
        cached_results: dict[UUID, list[float]] = {}

        # Check cache for all items
        dedup_hashes = [c.dedup_hash for c in contexts if c.dedup_hash]
        if dedup_hashes:
            cached = await self.cache.get_many(dedup_hashes)

            for ctx in contexts:
                if ctx.dedup_hash and cached.get(ctx.dedup_hash):
                    cached_results[ctx.item_id] = cached[ctx.dedup_hash]
                else:
                    uncached_contexts.append(ctx)
        else:
            uncached_contexts = contexts

        # Generate embeddings for uncached items
        if uncached_contexts:
            texts = [
                self._prepare_text(ctx.clean_text or "")
                for ctx in uncached_contexts
            ]

            try:
                embeddings = await self.embedder.embed_batch(texts)

                for ctx, embedding in zip(uncached_contexts, embeddings):
                    ctx.embedding = embedding
                    ctx.embedding_model = self.embedder.model

                    # Cache the embedding
                    if ctx.dedup_hash:
                        await self.cache.set(ctx.dedup_hash, embedding)

            except Exception as e:
                self.logger.error(f"Batch embedding failed: {e}")
                raise

        # Update all contexts with cached results
        for ctx in contexts:
            if ctx.item_id in cached_results:
                ctx.embedding = cached_results[ctx.item_id]
                ctx.embedding_model = self.embedder.model

        # Store all embeddings
        for ctx in contexts:
            if ctx.embedding:
                await self._store_embedding(ctx)

        return contexts
