"""
Hybrid search combining vector and lexical search.

This module implements hybrid search using Reciprocal Rank Fusion (RRF)
to merge results from vector (semantic) and lexical (BM25) search.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from app.search.vector import VectorSearch, VectorSearchResult, SearchableType
from app.search.lexical import LexicalSearch, LexicalSearchResult, IndexName
from app.search.filters import SearchFilters

logger = logging.getLogger(__name__)


# Mapping between vector entity types and OpenSearch indices
ENTITY_TYPE_TO_INDEX = {
    SearchableType.ITEM: IndexName.ITEMS,
    SearchableType.CLAIM: IndexName.CLAIMS,
    SearchableType.EVENT: IndexName.EVENTS,
    SearchableType.NARRATIVE: IndexName.NARRATIVES,
}

INDEX_TO_ENTITY_TYPE = {v: k for k, v in ENTITY_TYPE_TO_INDEX.items()}


@dataclass
class HybridSearchResult:
    """A single result from hybrid search."""

    id: UUID
    entity_type: SearchableType
    hybrid_score: float  # Combined RRF score
    vector_score: Optional[float] = None  # Original cosine similarity
    lexical_score: Optional[float] = None  # Original BM25 score
    vector_rank: Optional[int] = None  # Rank in vector results
    lexical_rank: Optional[int] = None  # Rank in lexical results
    title: Optional[str] = None
    content: Optional[str] = None
    source_id: Optional[UUID] = None
    source_name: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    reliability_tier: Optional[str] = None
    url: Optional[str] = None
    highlights: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class RRFConfig(BaseModel):
    """Configuration for Reciprocal Rank Fusion."""

    # RRF constant k (higher = more weight to lower-ranked results)
    k: int = 60

    # Weight for vector search results (0-1)
    vector_weight: float = 0.5

    # Weight for lexical search results (0-1)
    lexical_weight: float = 0.5

    # Number of results to fetch from each search method
    fetch_limit: int = 100


class HybridSearchConfig(BaseModel):
    """Configuration for hybrid search."""

    rrf: RRFConfig = RRFConfig()
    default_limit: int = 20
    max_limit: int = 100


class HybridSearch:
    """
    Hybrid search engine combining vector and lexical search.

    Uses Reciprocal Rank Fusion (RRF) to merge results from semantic
    vector search and BM25 lexical search for optimal retrieval.
    """

    def __init__(
        self,
        vector_search: VectorSearch,
        lexical_search: LexicalSearch,
        config: Optional[HybridSearchConfig] = None,
    ):
        """
        Initialize hybrid search.

        Args:
            vector_search: Vector search engine instance.
            lexical_search: Lexical search engine instance.
            config: Hybrid search configuration.
        """
        self.vector_search = vector_search
        self.lexical_search = lexical_search
        self.config = config or HybridSearchConfig()

    async def search(
        self,
        query: str,
        query_embedding: list[float],
        entity_types: Optional[list[SearchableType]] = None,
        filters: Optional[SearchFilters] = None,
        rrf_config: Optional[RRFConfig] = None,
        limit: int = 20,
        offset: int = 0,
        include_highlights: bool = True,
    ) -> list[HybridSearchResult]:
        """
        Perform hybrid search combining vector and lexical results.

        Args:
            query: The natural language search query.
            query_embedding: The embedding vector for the query.
            entity_types: Types of entities to search.
            filters: Search filters to apply.
            rrf_config: Custom RRF configuration (overrides default).
            limit: Maximum number of results.
            offset: Offset for pagination.
            include_highlights: Whether to include search highlights.

        Returns:
            List of hybrid search results ordered by RRF score.
        """
        limit = min(limit, self.config.max_limit)
        rrf = rrf_config or self.config.rrf
        entity_types = entity_types or list(SearchableType)
        filters = filters or SearchFilters()

        # Convert entity types to indices
        indices = [ENTITY_TYPE_TO_INDEX[et] for et in entity_types]

        # Execute both searches in parallel
        import asyncio

        vector_task = self.vector_search.search(
            query_embedding=query_embedding,
            entity_types=entity_types,
            subject_ids=filters.subject_ids,
            source_ids=filters.source_ids,
            date_from=filters.date_from,
            date_to=filters.date_to,
            reliability_tiers=filters.reliability_tiers,
            limit=rrf.fetch_limit,
        )

        lexical_task = self.lexical_search.search(
            query=query,
            indices=indices,
            subject_ids=filters.subject_ids,
            source_ids=filters.source_ids,
            date_from=filters.date_from,
            date_to=filters.date_to,
            reliability_tiers=filters.reliability_tiers,
            entity_ids=filters.entity_ids,
            limit=rrf.fetch_limit,
            include_highlights=include_highlights,
        )

        vector_results, lexical_results = await asyncio.gather(
            vector_task, lexical_task
        )

        # Merge results using RRF
        merged = self._merge_with_rrf(
            vector_results=vector_results,
            lexical_results=lexical_results,
            rrf_config=rrf,
        )

        # Apply pagination
        return merged[offset : offset + limit]

    async def search_vector_only(
        self,
        query_embedding: list[float],
        entity_types: Optional[list[SearchableType]] = None,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[HybridSearchResult]:
        """
        Perform vector-only search (pure semantic search).

        Args:
            query_embedding: The embedding vector for the query.
            entity_types: Types of entities to search.
            filters: Search filters to apply.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of results as HybridSearchResult for consistent API.
        """
        filters = filters or SearchFilters()

        results = await self.vector_search.search(
            query_embedding=query_embedding,
            entity_types=entity_types,
            subject_ids=filters.subject_ids,
            source_ids=filters.source_ids,
            date_from=filters.date_from,
            date_to=filters.date_to,
            reliability_tiers=filters.reliability_tiers,
            limit=limit,
            offset=offset,
        )

        return [
            HybridSearchResult(
                id=r.id,
                entity_type=r.entity_type,
                hybrid_score=r.score,
                vector_score=r.score,
                vector_rank=i + 1,
                title=r.title,
                content=r.content,
                source_id=r.source_id,
                source_name=r.source_name,
                author=r.author,
                published_at=r.published_at,
                reliability_tier=r.reliability_tier,
                url=r.url,
                metadata=r.metadata,
            )
            for i, r in enumerate(results)
        ]

    async def search_lexical_only(
        self,
        query: str,
        entity_types: Optional[list[SearchableType]] = None,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
        include_highlights: bool = True,
    ) -> list[HybridSearchResult]:
        """
        Perform lexical-only search (pure BM25 search).

        Args:
            query: The search query text.
            entity_types: Types of entities to search.
            filters: Search filters to apply.
            limit: Maximum number of results.
            offset: Offset for pagination.
            include_highlights: Whether to include search highlights.

        Returns:
            List of results as HybridSearchResult for consistent API.
        """
        entity_types = entity_types or list(SearchableType)
        filters = filters or SearchFilters()
        indices = [ENTITY_TYPE_TO_INDEX[et] for et in entity_types]

        results = await self.lexical_search.search(
            query=query,
            indices=indices,
            subject_ids=filters.subject_ids,
            source_ids=filters.source_ids,
            date_from=filters.date_from,
            date_to=filters.date_to,
            reliability_tiers=filters.reliability_tiers,
            entity_ids=filters.entity_ids,
            limit=limit,
            offset=offset,
            include_highlights=include_highlights,
        )

        return [
            HybridSearchResult(
                id=r.id,
                entity_type=INDEX_TO_ENTITY_TYPE.get(r.index, SearchableType.ITEM),
                hybrid_score=r.score,
                lexical_score=r.score,
                lexical_rank=i + 1,
                title=r.title,
                content=r.content,
                source_id=r.source_id,
                source_name=r.source_name,
                author=r.author,
                published_at=r.published_at,
                reliability_tier=r.reliability_tier,
                url=r.url,
                highlights=r.highlights,
                metadata=r.metadata,
            )
            for i, r in enumerate(results)
        ]

    def _merge_with_rrf(
        self,
        vector_results: list[VectorSearchResult],
        lexical_results: list[LexicalSearchResult],
        rrf_config: RRFConfig,
    ) -> list[HybridSearchResult]:
        """
        Merge results using Reciprocal Rank Fusion.

        RRF Score = sum(weight_i / (k + rank_i)) for each result source

        Args:
            vector_results: Results from vector search.
            lexical_results: Results from lexical search.
            rrf_config: RRF configuration.

        Returns:
            Merged and sorted results.
        """
        k = rrf_config.k

        # Build a map of results by ID
        result_map: dict[UUID, dict[str, Any]] = {}

        # Process vector results
        for rank, vr in enumerate(vector_results, start=1):
            result_map[vr.id] = {
                "id": vr.id,
                "entity_type": vr.entity_type,
                "vector_score": vr.score,
                "vector_rank": rank,
                "title": vr.title,
                "content": vr.content,
                "source_id": vr.source_id,
                "source_name": vr.source_name,
                "author": vr.author,
                "published_at": vr.published_at,
                "reliability_tier": vr.reliability_tier,
                "url": vr.url,
                "metadata": vr.metadata,
                "highlights": {},
            }

        # Process lexical results
        for rank, lr in enumerate(lexical_results, start=1):
            if lr.id in result_map:
                # Update existing entry
                result_map[lr.id]["lexical_score"] = lr.score
                result_map[lr.id]["lexical_rank"] = rank
                result_map[lr.id]["highlights"] = lr.highlights
                # Prefer lexical metadata if richer
                if not result_map[lr.id]["title"] and lr.title:
                    result_map[lr.id]["title"] = lr.title
            else:
                # New entry from lexical search
                entity_type = INDEX_TO_ENTITY_TYPE.get(lr.index, SearchableType.ITEM)
                result_map[lr.id] = {
                    "id": lr.id,
                    "entity_type": entity_type,
                    "lexical_score": lr.score,
                    "lexical_rank": rank,
                    "title": lr.title,
                    "content": lr.content,
                    "source_id": lr.source_id,
                    "source_name": lr.source_name,
                    "author": lr.author,
                    "published_at": lr.published_at,
                    "reliability_tier": lr.reliability_tier,
                    "url": lr.url,
                    "metadata": lr.metadata,
                    "highlights": lr.highlights,
                }

        # Calculate RRF scores
        results: list[HybridSearchResult] = []
        for data in result_map.values():
            rrf_score = 0.0

            # Vector contribution
            if data.get("vector_rank") is not None:
                rrf_score += rrf_config.vector_weight / (k + data["vector_rank"])

            # Lexical contribution
            if data.get("lexical_rank") is not None:
                rrf_score += rrf_config.lexical_weight / (k + data["lexical_rank"])

            results.append(
                HybridSearchResult(
                    id=data["id"],
                    entity_type=data["entity_type"],
                    hybrid_score=rrf_score,
                    vector_score=data.get("vector_score"),
                    lexical_score=data.get("lexical_score"),
                    vector_rank=data.get("vector_rank"),
                    lexical_rank=data.get("lexical_rank"),
                    title=data.get("title"),
                    content=data.get("content"),
                    source_id=data.get("source_id"),
                    source_name=data.get("source_name"),
                    author=data.get("author"),
                    published_at=data.get("published_at"),
                    reliability_tier=data.get("reliability_tier"),
                    url=data.get("url"),
                    highlights=data.get("highlights", {}),
                    metadata=data.get("metadata", {}),
                )
            )

        # Sort by RRF score (descending)
        results.sort(key=lambda r: r.hybrid_score, reverse=True)

        return results

    async def search_with_weights(
        self,
        query: str,
        query_embedding: list[float],
        vector_weight: float = 0.5,
        lexical_weight: float = 0.5,
        entity_types: Optional[list[SearchableType]] = None,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[HybridSearchResult]:
        """
        Perform hybrid search with custom weights.

        Convenience method for quickly adjusting the vector/lexical balance.

        Args:
            query: The natural language search query.
            query_embedding: The embedding vector for the query.
            vector_weight: Weight for vector search (0-1).
            lexical_weight: Weight for lexical search (0-1).
            entity_types: Types of entities to search.
            filters: Search filters to apply.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of hybrid search results.
        """
        # Normalize weights
        total = vector_weight + lexical_weight
        if total > 0:
            vector_weight = vector_weight / total
            lexical_weight = lexical_weight / total

        rrf_config = RRFConfig(
            vector_weight=vector_weight,
            lexical_weight=lexical_weight,
        )

        return await self.search(
            query=query,
            query_embedding=query_embedding,
            entity_types=entity_types,
            filters=filters,
            rrf_config=rrf_config,
            limit=limit,
            offset=offset,
        )

    async def explain_scores(
        self,
        result: HybridSearchResult,
    ) -> dict[str, Any]:
        """
        Explain how a result's hybrid score was calculated.

        Args:
            result: The hybrid search result to explain.

        Returns:
            Dictionary with score breakdown.
        """
        rrf = self.config.rrf
        k = rrf.k

        explanation = {
            "result_id": str(result.id),
            "entity_type": result.entity_type.value,
            "hybrid_score": result.hybrid_score,
            "rrf_k": k,
            "components": [],
        }

        if result.vector_rank is not None:
            vector_contribution = rrf.vector_weight / (k + result.vector_rank)
            explanation["components"].append({
                "source": "vector",
                "rank": result.vector_rank,
                "original_score": result.vector_score,
                "weight": rrf.vector_weight,
                "contribution": vector_contribution,
                "formula": f"{rrf.vector_weight} / ({k} + {result.vector_rank}) = {vector_contribution:.6f}",
            })

        if result.lexical_rank is not None:
            lexical_contribution = rrf.lexical_weight / (k + result.lexical_rank)
            explanation["components"].append({
                "source": "lexical",
                "rank": result.lexical_rank,
                "original_score": result.lexical_score,
                "weight": rrf.lexical_weight,
                "contribution": lexical_contribution,
                "formula": f"{rrf.lexical_weight} / ({k} + {result.lexical_rank}) = {lexical_contribution:.6f}",
            })

        return explanation
