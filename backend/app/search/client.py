"""
High-level search client for the Lantern search system.

This module provides a unified search API for both the UI and agents,
with support for different result types and pagination.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.search.vector import VectorSearch, SearchableType
from app.search.lexical import LexicalSearch, IndexName
from app.search.hybrid import HybridSearch, RRFConfig
from app.search.filters import SearchFilters
from app.search.rerank import CrossEncoderReranker, RerankedResult
from app.search.query import QueryExecutor, QueryParser, EmbeddingService

logger = logging.getLogger(__name__)


class ResultType(str, Enum):
    """Types of search results."""

    ITEM = "item"
    CLAIM = "claim"
    EVENT = "event"
    NARRATIVE = "narrative"
    ALL = "all"


class SearchMode(str, Enum):
    """Search mode selection."""

    HYBRID = "hybrid"
    VECTOR = "vector"
    LEXICAL = "lexical"


class SortOrder(str, Enum):
    """Sort order for results."""

    RELEVANCE = "relevance"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    RELIABILITY = "reliability"


class SearchRequest(BaseModel):
    """Search request parameters."""

    # Query text
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")

    # Result types to include
    result_types: list[ResultType] = Field(
        default=[ResultType.ALL],
        description="Types of results to return"
    )

    # Search mode
    mode: SearchMode = Field(
        default=SearchMode.HYBRID,
        description="Search mode"
    )

    # Filters
    subject_ids: Optional[list[UUID]] = Field(default=None, description="Filter by subjects")
    source_ids: Optional[list[UUID]] = Field(default=None, description="Filter by sources")
    date_from: Optional[datetime] = Field(default=None, description="Filter by date (from)")
    date_to: Optional[datetime] = Field(default=None, description="Filter by date (to)")
    reliability_tiers: Optional[list[str]] = Field(default=None, description="Filter by reliability")
    entity_ids: Optional[list[UUID]] = Field(default=None, description="Filter by entities")
    narrative_ids: Optional[list[UUID]] = Field(default=None, description="Filter by narratives")

    # Pagination
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Result offset")

    # Options
    sort_by: SortOrder = Field(default=SortOrder.RELEVANCE, description="Sort order")
    include_highlights: bool = Field(default=True, description="Include search highlights")
    include_provenance: bool = Field(default=True, description="Include source provenance")
    enable_reranking: bool = Field(default=True, description="Apply cross-encoder reranking")

    # Advanced
    vector_weight: float = Field(default=0.5, ge=0, le=1, description="Vector search weight")
    lexical_weight: float = Field(default=0.5, ge=0, le=1, description="Lexical search weight")

    def to_filters(self) -> SearchFilters:
        """Convert request to SearchFilters object."""
        return SearchFilters(
            subject_ids=self.subject_ids,
            source_ids=self.source_ids,
            date_from=self.date_from,
            date_to=self.date_to,
            reliability_tiers=self.reliability_tiers,
            entity_ids=self.entity_ids,
            narrative_ids=self.narrative_ids,
        )

    def to_entity_types(self) -> Optional[list[SearchableType]]:
        """Convert result types to entity types."""
        if ResultType.ALL in self.result_types:
            return None

        type_map = {
            ResultType.ITEM: SearchableType.ITEM,
            ResultType.CLAIM: SearchableType.CLAIM,
            ResultType.EVENT: SearchableType.EVENT,
            ResultType.NARRATIVE: SearchableType.NARRATIVE,
        }

        return [type_map[rt] for rt in self.result_types if rt in type_map]


@dataclass
class SearchResultItem:
    """A single search result."""

    id: UUID
    type: ResultType
    score: float
    title: Optional[str] = None
    content: Optional[str] = None
    highlights: dict[str, list[str]] = field(default_factory=dict)

    # Provenance
    source_id: Optional[UUID] = None
    source_name: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    reliability_tier: Optional[str] = None
    url: Optional[str] = None

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResponse:
    """Search response with results and metadata."""

    # Results
    results: list[SearchResultItem]

    # Pagination
    total: int
    limit: int
    offset: int
    has_more: bool

    # Query info
    query: str
    parsed_query: str
    search_time_ms: float

    # Metadata
    filters_applied: dict[str, Any] = field(default_factory=dict)
    search_mode: str = "hybrid"
    reranking_applied: bool = False


class SearchClient:
    """
    High-level search client for Lantern.

    Provides a unified API for search operations used by both
    the web UI and agent systems.
    """

    def __init__(
        self,
        vector_search: Optional[VectorSearch] = None,
        lexical_search: Optional[LexicalSearch] = None,
        hybrid_search: Optional[HybridSearch] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        """
        Initialize search client.

        Args:
            vector_search: Vector search engine.
            lexical_search: Lexical search engine.
            hybrid_search: Hybrid search engine.
            reranker: Cross-encoder reranker.
            embedding_service: Embedding generation service.
        """
        self._vector_search = vector_search
        self._lexical_search = lexical_search
        self._hybrid_search = hybrid_search
        self._reranker = reranker
        self._embedding_service = embedding_service
        self._query_executor: Optional[QueryExecutor] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the search client and all dependencies."""
        if self._initialized:
            return

        # Initialize vector search if not provided
        if self._vector_search is None:
            self._vector_search = VectorSearch()
            await self._vector_search.initialize()

        # Initialize lexical search if not provided
        if self._lexical_search is None:
            self._lexical_search = LexicalSearch()
            await self._lexical_search.initialize()

        # Create hybrid search if not provided
        if self._hybrid_search is None:
            self._hybrid_search = HybridSearch(
                vector_search=self._vector_search,
                lexical_search=self._lexical_search,
            )

        # Initialize reranker if not provided
        if self._reranker is None:
            self._reranker = CrossEncoderReranker()
            try:
                await self._reranker.initialize()
            except Exception as e:
                logger.warning(f"Reranker initialization failed: {e}")

        # Initialize embedding service if not provided
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService()
            try:
                await self._embedding_service.initialize()
            except Exception as e:
                logger.warning(f"Embedding service initialization failed: {e}")

        # Create query executor
        if self._embedding_service and self._hybrid_search and self._reranker:
            self._query_executor = QueryExecutor(
                hybrid_search=self._hybrid_search,
                reranker=self._reranker,
                embedding_fn=self._embedding_service.embed,
            )

        self._initialized = True
        logger.info("Search client initialized")

    async def close(self) -> None:
        """Close the search client and release resources."""
        if self._vector_search:
            await self._vector_search.close()
        if self._lexical_search:
            await self._lexical_search.close()
        self._initialized = False

    async def search(self, request: SearchRequest) -> SearchResponse:
        """
        Execute a search request.

        Args:
            request: Search request parameters.

        Returns:
            SearchResponse with results and metadata.
        """
        import time

        if not self._initialized:
            await self.initialize()

        start_time = time.time()

        # Parse query
        parser = QueryParser()
        parsed = parser.parse(request.query)

        # Get filters
        filters = request.to_filters()
        if not parsed.filters.is_empty():
            filters = filters.merge(parsed.filters)

        # Get entity types
        entity_types = request.to_entity_types()
        if parsed.entity_types:
            entity_types = parsed.entity_types

        # Build RRF config
        rrf_config = RRFConfig(
            vector_weight=request.vector_weight,
            lexical_weight=request.lexical_weight,
        )

        # Execute search based on mode
        results: list[RerankedResult] = []

        if request.mode == SearchMode.HYBRID and self._query_executor:
            execution_result = await self._query_executor.execute(
                query=request.query,
                filters=filters,
                entity_types=entity_types,
                limit=request.limit,
                offset=request.offset,
                enable_reranking=request.enable_reranking,
            )
            results = execution_result.results
        elif request.mode == SearchMode.VECTOR and self._hybrid_search:
            # Vector-only search
            embedding = await self._embedding_service.embed(parsed.query_text)
            hybrid_results = await self._hybrid_search.search_vector_only(
                query_embedding=embedding,
                entity_types=entity_types,
                filters=filters,
                limit=request.limit,
                offset=request.offset,
            )
            results = self._convert_to_reranked(hybrid_results)
        elif request.mode == SearchMode.LEXICAL and self._hybrid_search:
            # Lexical-only search
            hybrid_results = await self._hybrid_search.search_lexical_only(
                query=parsed.query_text,
                entity_types=entity_types,
                filters=filters,
                limit=request.limit,
                offset=request.offset,
                include_highlights=request.include_highlights,
            )
            results = self._convert_to_reranked(hybrid_results)
        else:
            logger.error("Search not properly initialized")
            results = []

        # Convert to response format
        result_items = [
            self._to_result_item(r, request.include_provenance)
            for r in results
        ]

        # Apply sorting if not relevance (already sorted by score)
        if request.sort_by != SortOrder.RELEVANCE:
            result_items = self._apply_sort(result_items, request.sort_by)

        elapsed_ms = (time.time() - start_time) * 1000

        return SearchResponse(
            results=result_items,
            total=len(results),
            limit=request.limit,
            offset=request.offset,
            has_more=len(results) >= request.limit,
            query=request.query,
            parsed_query=parsed.query_text,
            search_time_ms=round(elapsed_ms, 2),
            filters_applied=filters.to_dict() if not filters.is_empty() else {},
            search_mode=request.mode.value,
            reranking_applied=request.enable_reranking and request.mode == SearchMode.HYBRID,
        )

    async def search_simple(
        self,
        query: str,
        limit: int = 20,
        result_types: Optional[list[ResultType]] = None,
    ) -> list[SearchResultItem]:
        """
        Simple search interface for quick queries.

        Args:
            query: Search query.
            limit: Maximum results.
            result_types: Types of results to include.

        Returns:
            List of search results.
        """
        request = SearchRequest(
            query=query,
            limit=limit,
            result_types=result_types or [ResultType.ALL],
        )
        response = await self.search(request)
        return response.results

    async def search_items(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for items only."""
        request = SearchRequest(
            query=query,
            result_types=[ResultType.ITEM],
            subject_ids=filters.subject_ids if filters else None,
            source_ids=filters.source_ids if filters else None,
            date_from=filters.date_from if filters else None,
            date_to=filters.date_to if filters else None,
            reliability_tiers=filters.reliability_tiers if filters else None,
            limit=limit,
            offset=offset,
        )
        return await self.search(request)

    async def search_claims(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for claims only."""
        request = SearchRequest(
            query=query,
            result_types=[ResultType.CLAIM],
            subject_ids=filters.subject_ids if filters else None,
            source_ids=filters.source_ids if filters else None,
            date_from=filters.date_from if filters else None,
            date_to=filters.date_to if filters else None,
            reliability_tiers=filters.reliability_tiers if filters else None,
            limit=limit,
            offset=offset,
        )
        return await self.search(request)

    async def search_events(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for events only."""
        request = SearchRequest(
            query=query,
            result_types=[ResultType.EVENT],
            subject_ids=filters.subject_ids if filters else None,
            date_from=filters.date_from if filters else None,
            date_to=filters.date_to if filters else None,
            limit=limit,
            offset=offset,
        )
        return await self.search(request)

    async def search_narratives(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search for narratives only."""
        request = SearchRequest(
            query=query,
            result_types=[ResultType.NARRATIVE],
            subject_ids=filters.subject_ids if filters else None,
            limit=limit,
            offset=offset,
        )
        return await self.search(request)

    async def find_similar(
        self,
        entity_id: UUID,
        entity_type: ResultType,
        limit: int = 10,
    ) -> list[SearchResultItem]:
        """
        Find similar entities to a given entity.

        Args:
            entity_id: The reference entity ID.
            entity_type: Type of the entity.
            limit: Maximum results.

        Returns:
            List of similar entities.
        """
        if not self._initialized:
            await self.initialize()

        if not self._vector_search:
            return []

        # Map result type to searchable type
        type_map = {
            ResultType.ITEM: SearchableType.ITEM,
            ResultType.CLAIM: SearchableType.CLAIM,
            ResultType.EVENT: SearchableType.EVENT,
            ResultType.NARRATIVE: SearchableType.NARRATIVE,
        }

        searchable_type = type_map.get(entity_type)
        if not searchable_type:
            return []

        results = await self._vector_search.find_similar(
            entity_id=entity_id,
            entity_type=searchable_type,
            limit=limit,
        )

        return [
            SearchResultItem(
                id=r.id,
                type=entity_type,
                score=r.score,
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
            for r in results
        ]

    async def search_by_entity(
        self,
        entity_name: str,
        limit: int = 20,
    ) -> list[SearchResultItem]:
        """
        Search for content mentioning an entity by name.

        Args:
            entity_name: Name of the entity.
            limit: Maximum results.

        Returns:
            List of results mentioning the entity.
        """
        if not self._initialized:
            await self.initialize()

        if not self._lexical_search:
            return []

        results = await self._lexical_search.search_by_entity_name(
            name=entity_name,
            limit=limit,
        )

        type_map = {
            IndexName.ITEMS: ResultType.ITEM,
            IndexName.CLAIMS: ResultType.CLAIM,
            IndexName.EVENTS: ResultType.EVENT,
            IndexName.NARRATIVES: ResultType.NARRATIVE,
        }

        return [
            SearchResultItem(
                id=r.id,
                type=type_map.get(r.index, ResultType.ITEM),
                score=r.score,
                title=r.title,
                content=r.content,
                highlights=r.highlights,
                source_id=r.source_id,
                source_name=r.source_name,
                author=r.author,
                published_at=r.published_at,
                reliability_tier=r.reliability_tier,
                url=r.url,
                metadata=r.metadata,
            )
            for r in results
        ]

    async def get_search_stats(self) -> dict[str, Any]:
        """Get search system statistics."""
        if not self._initialized:
            await self.initialize()

        stats = {
            "initialized": self._initialized,
            "indices": {},
        }

        if self._lexical_search:
            for index in IndexName:
                try:
                    count = await self._lexical_search.get_document_count(index)
                    stats["indices"][index.value] = {
                        "document_count": count,
                        "exists": await self._lexical_search.index_exists(index),
                    }
                except Exception as e:
                    stats["indices"][index.value] = {"error": str(e)}

        return stats

    def _convert_to_reranked(
        self,
        hybrid_results: list,
    ) -> list[RerankedResult]:
        """Convert hybrid results to reranked format."""
        from app.search.hybrid import HybridSearchResult

        return [
            RerankedResult(
                id=r.id,
                entity_type=r.entity_type,
                rerank_score=r.hybrid_score,
                original_rank=i + 1,
                new_rank=i + 1,
                hybrid_score=r.hybrid_score,
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
            for i, r in enumerate(hybrid_results)
        ]

    def _to_result_item(
        self,
        result: RerankedResult,
        include_provenance: bool,
    ) -> SearchResultItem:
        """Convert reranked result to result item."""
        type_map = {
            SearchableType.ITEM: ResultType.ITEM,
            SearchableType.CLAIM: ResultType.CLAIM,
            SearchableType.EVENT: ResultType.EVENT,
            SearchableType.NARRATIVE: ResultType.NARRATIVE,
        }

        return SearchResultItem(
            id=result.id,
            type=type_map.get(result.entity_type, ResultType.ITEM),
            score=result.rerank_score,
            title=result.title,
            content=result.content,
            highlights=result.highlights,
            source_id=result.source_id if include_provenance else None,
            source_name=result.source_name if include_provenance else None,
            author=result.author if include_provenance else None,
            published_at=result.published_at if include_provenance else None,
            reliability_tier=result.reliability_tier if include_provenance else None,
            url=result.url if include_provenance else None,
            metadata=result.metadata,
        )

    def _apply_sort(
        self,
        results: list[SearchResultItem],
        sort_by: SortOrder,
    ) -> list[SearchResultItem]:
        """Apply secondary sorting to results."""
        if sort_by == SortOrder.DATE_DESC:
            return sorted(
                results,
                key=lambda r: r.published_at or datetime.min,
                reverse=True,
            )
        elif sort_by == SortOrder.DATE_ASC:
            return sorted(
                results,
                key=lambda r: r.published_at or datetime.max,
            )
        elif sort_by == SortOrder.RELIABILITY:
            tier_order = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
            return sorted(
                results,
                key=lambda r: tier_order.get(r.reliability_tier or "T5", 5),
            )
        return results


# Convenience function for creating a configured search client
async def create_search_client(
    db_pool: Any = None,
) -> SearchClient:
    """
    Create and initialize a search client.

    Args:
        db_pool: Optional asyncpg connection pool.

    Returns:
        Initialized SearchClient.
    """
    vector_search = VectorSearch(pool=db_pool)
    lexical_search = LexicalSearch()
    reranker = CrossEncoderReranker()
    embedding_service = EmbeddingService()

    client = SearchClient(
        vector_search=vector_search,
        lexical_search=lexical_search,
        reranker=reranker,
        embedding_service=embedding_service,
    )

    await client.initialize()
    return client
