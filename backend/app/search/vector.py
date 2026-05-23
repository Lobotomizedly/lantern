"""
Vector search using pgvector for semantic similarity search.

This module provides vector-based semantic search over Items, Claims, Events,
and Narratives using PostgreSQL's pgvector extension with cosine similarity.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class SearchableType(str, Enum):
    """Types of entities that can be searched."""

    ITEM = "item"
    CLAIM = "claim"
    EVENT = "event"
    NARRATIVE = "narrative"


@dataclass
class VectorSearchResult:
    """A single result from vector search."""

    id: UUID
    entity_type: SearchableType
    score: float  # Cosine similarity score (higher is better)
    title: Optional[str] = None
    content: Optional[str] = None
    source_id: Optional[UUID] = None
    source_name: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    reliability_tier: Optional[str] = None
    url: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorSearchConfig(BaseModel):
    """Configuration for vector search."""

    embedding_dimensions: int = 1536
    default_limit: int = 20
    max_limit: int = 100
    similarity_threshold: float = 0.0  # Minimum similarity score


class VectorSearch:
    """
    Vector search engine using pgvector.

    Performs semantic similarity search over embeddings stored in PostgreSQL
    using the pgvector extension with cosine similarity.
    """

    def __init__(
        self,
        pool: Optional[asyncpg.Pool] = None,
        config: Optional[VectorSearchConfig] = None,
    ):
        """
        Initialize vector search.

        Args:
            pool: asyncpg connection pool. If None, will create one.
            config: Vector search configuration.
        """
        self._pool = pool
        self._external_pool = pool is not None
        self.config = config or VectorSearchConfig(
            embedding_dimensions=settings.embedding_dimensions
        )

    async def initialize(self) -> None:
        """Initialize the connection pool if not provided externally."""
        if self._pool is None:
            # Extract connection params from SQLAlchemy URL
            db_url = settings.database_url
            # Convert asyncpg URL format
            dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=settings.database_pool_size,
            )
            logger.info("Vector search connection pool initialized")

    async def close(self) -> None:
        """Close the connection pool if we created it."""
        if self._pool and not self._external_pool:
            await self._pool.close()
            self._pool = None
            logger.info("Vector search connection pool closed")

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not initialized."""
        if self._pool is None:
            raise RuntimeError("Vector search not initialized. Call initialize() first.")
        return self._pool

    async def search(
        self,
        query_embedding: list[float],
        entity_types: Optional[list[SearchableType]] = None,
        subject_ids: Optional[list[UUID]] = None,
        source_ids: Optional[list[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        reliability_tiers: Optional[list[str]] = None,
        limit: int = 20,
        offset: int = 0,
        similarity_threshold: Optional[float] = None,
    ) -> list[VectorSearchResult]:
        """
        Search for similar items using vector embeddings.

        Args:
            query_embedding: The query vector (must match embedding_dimensions).
            entity_types: Filter by entity types. Default: all types.
            subject_ids: Filter by subject IDs.
            source_ids: Filter by source IDs.
            date_from: Filter by published date (from).
            date_to: Filter by published date (to).
            reliability_tiers: Filter by reliability tiers (e.g., ["T1", "T2"]).
            limit: Maximum number of results.
            offset: Offset for pagination.
            similarity_threshold: Minimum similarity score (0-1).

        Returns:
            List of search results ordered by similarity (highest first).
        """
        if len(query_embedding) != self.config.embedding_dimensions:
            raise ValueError(
                f"Query embedding must have {self.config.embedding_dimensions} dimensions, "
                f"got {len(query_embedding)}"
            )

        limit = min(limit, self.config.max_limit)
        threshold = similarity_threshold or self.config.similarity_threshold
        entity_types = entity_types or list(SearchableType)

        results: list[VectorSearchResult] = []

        # Search each entity type
        for entity_type in entity_types:
            type_results = await self._search_entity_type(
                query_embedding=query_embedding,
                entity_type=entity_type,
                subject_ids=subject_ids,
                source_ids=source_ids,
                date_from=date_from,
                date_to=date_to,
                reliability_tiers=reliability_tiers,
                limit=limit,
                similarity_threshold=threshold,
            )
            results.extend(type_results)

        # Sort by similarity score and apply pagination
        results.sort(key=lambda r: r.score, reverse=True)
        return results[offset : offset + limit]

    async def _search_entity_type(
        self,
        query_embedding: list[float],
        entity_type: SearchableType,
        subject_ids: Optional[list[UUID]] = None,
        source_ids: Optional[list[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        reliability_tiers: Optional[list[str]] = None,
        limit: int = 20,
        similarity_threshold: float = 0.0,
    ) -> list[VectorSearchResult]:
        """Search a specific entity type."""

        # Build query based on entity type
        if entity_type == SearchableType.ITEM:
            return await self._search_items(
                query_embedding, subject_ids, source_ids, date_from, date_to,
                reliability_tiers, limit, similarity_threshold
            )
        elif entity_type == SearchableType.CLAIM:
            return await self._search_claims(
                query_embedding, subject_ids, source_ids, date_from, date_to,
                reliability_tiers, limit, similarity_threshold
            )
        elif entity_type == SearchableType.EVENT:
            return await self._search_events(
                query_embedding, subject_ids, date_from, date_to,
                limit, similarity_threshold
            )
        elif entity_type == SearchableType.NARRATIVE:
            return await self._search_narratives(
                query_embedding, subject_ids, date_from, date_to,
                limit, similarity_threshold
            )
        else:
            logger.warning(f"Unknown entity type: {entity_type}")
            return []

    async def _search_items(
        self,
        query_embedding: list[float],
        subject_ids: Optional[list[UUID]],
        source_ids: Optional[list[UUID]],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        reliability_tiers: Optional[list[str]],
        limit: int,
        similarity_threshold: float,
    ) -> list[VectorSearchResult]:
        """Search items table."""

        # Build the query with filters
        query_parts = ["""
            SELECT
                i.id,
                i.title,
                i.content,
                i.source_id,
                s.name as source_name,
                i.author,
                i.published_at,
                s.reliability_tier,
                i.url,
                1 - (i.embedding <=> $1::vector) as similarity
            FROM items i
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE i.embedding IS NOT NULL
        """]

        params: list[Any] = [query_embedding]
        param_idx = 2

        if subject_ids:
            query_parts.append(f"AND i.subject_id = ANY(${param_idx}::uuid[])")
            params.append(subject_ids)
            param_idx += 1

        if source_ids:
            query_parts.append(f"AND i.source_id = ANY(${param_idx}::uuid[])")
            params.append(source_ids)
            param_idx += 1

        if date_from:
            query_parts.append(f"AND i.published_at >= ${param_idx}")
            params.append(date_from)
            param_idx += 1

        if date_to:
            query_parts.append(f"AND i.published_at <= ${param_idx}")
            params.append(date_to)
            param_idx += 1

        if reliability_tiers:
            query_parts.append(f"AND s.reliability_tier = ANY(${param_idx}::text[])")
            params.append(reliability_tiers)
            param_idx += 1

        query_parts.append(f"AND 1 - (i.embedding <=> $1::vector) >= ${param_idx}")
        params.append(similarity_threshold)
        param_idx += 1

        query_parts.append("ORDER BY i.embedding <=> $1::vector")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)

        query = "\n".join(query_parts)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            VectorSearchResult(
                id=row["id"],
                entity_type=SearchableType.ITEM,
                score=float(row["similarity"]),
                title=row["title"],
                content=row["content"][:500] if row["content"] else None,
                source_id=row["source_id"],
                source_name=row["source_name"],
                author=row["author"],
                published_at=row["published_at"],
                reliability_tier=row["reliability_tier"],
                url=row["url"],
            )
            for row in rows
        ]

    async def _search_claims(
        self,
        query_embedding: list[float],
        subject_ids: Optional[list[UUID]],
        source_ids: Optional[list[UUID]],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        reliability_tiers: Optional[list[str]],
        limit: int,
        similarity_threshold: float,
    ) -> list[VectorSearchResult]:
        """Search claims table."""

        query_parts = ["""
            SELECT
                c.id,
                c.text as content,
                c.assessment,
                c.confidence,
                i.id as item_id,
                i.source_id,
                s.name as source_name,
                i.author,
                i.published_at,
                s.reliability_tier,
                i.url,
                1 - (c.embedding <=> $1::vector) as similarity
            FROM claims c
            LEFT JOIN items i ON c.item_id = i.id
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE c.embedding IS NOT NULL
        """]

        params: list[Any] = [query_embedding]
        param_idx = 2

        if subject_ids:
            query_parts.append(f"AND c.subject_id = ANY(${param_idx}::uuid[])")
            params.append(subject_ids)
            param_idx += 1

        if source_ids:
            query_parts.append(f"AND i.source_id = ANY(${param_idx}::uuid[])")
            params.append(source_ids)
            param_idx += 1

        if date_from:
            query_parts.append(f"AND i.published_at >= ${param_idx}")
            params.append(date_from)
            param_idx += 1

        if date_to:
            query_parts.append(f"AND i.published_at <= ${param_idx}")
            params.append(date_to)
            param_idx += 1

        if reliability_tiers:
            query_parts.append(f"AND s.reliability_tier = ANY(${param_idx}::text[])")
            params.append(reliability_tiers)
            param_idx += 1

        query_parts.append(f"AND 1 - (c.embedding <=> $1::vector) >= ${param_idx}")
        params.append(similarity_threshold)
        param_idx += 1

        query_parts.append("ORDER BY c.embedding <=> $1::vector")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)

        query = "\n".join(query_parts)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            VectorSearchResult(
                id=row["id"],
                entity_type=SearchableType.CLAIM,
                score=float(row["similarity"]),
                content=row["content"],
                source_id=row["source_id"],
                source_name=row["source_name"],
                author=row["author"],
                published_at=row["published_at"],
                reliability_tier=row["reliability_tier"],
                url=row["url"],
                metadata={
                    "assessment": row["assessment"],
                    "confidence": row["confidence"],
                    "item_id": str(row["item_id"]) if row["item_id"] else None,
                },
            )
            for row in rows
        ]

    async def _search_events(
        self,
        query_embedding: list[float],
        subject_ids: Optional[list[UUID]],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        limit: int,
        similarity_threshold: float,
    ) -> list[VectorSearchResult]:
        """Search events table."""

        query_parts = ["""
            SELECT
                e.id,
                e.title,
                e.description as content,
                e.event_date,
                e.location,
                e.event_type,
                1 - (e.embedding <=> $1::vector) as similarity
            FROM events e
            WHERE e.embedding IS NOT NULL
        """]

        params: list[Any] = [query_embedding]
        param_idx = 2

        if subject_ids:
            query_parts.append(f"AND e.subject_id = ANY(${param_idx}::uuid[])")
            params.append(subject_ids)
            param_idx += 1

        if date_from:
            query_parts.append(f"AND e.event_date >= ${param_idx}")
            params.append(date_from)
            param_idx += 1

        if date_to:
            query_parts.append(f"AND e.event_date <= ${param_idx}")
            params.append(date_to)
            param_idx += 1

        query_parts.append(f"AND 1 - (e.embedding <=> $1::vector) >= ${param_idx}")
        params.append(similarity_threshold)
        param_idx += 1

        query_parts.append("ORDER BY e.embedding <=> $1::vector")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)

        query = "\n".join(query_parts)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            VectorSearchResult(
                id=row["id"],
                entity_type=SearchableType.EVENT,
                score=float(row["similarity"]),
                title=row["title"],
                content=row["content"],
                published_at=row["event_date"],
                metadata={
                    "location": row["location"],
                    "event_type": row["event_type"],
                },
            )
            for row in rows
        ]

    async def _search_narratives(
        self,
        query_embedding: list[float],
        subject_ids: Optional[list[UUID]],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        limit: int,
        similarity_threshold: float,
    ) -> list[VectorSearchResult]:
        """Search narratives table."""

        query_parts = ["""
            SELECT
                n.id,
                n.title,
                n.description as content,
                n.status,
                n.created_at,
                n.updated_at,
                1 - (n.embedding <=> $1::vector) as similarity
            FROM narratives n
            WHERE n.embedding IS NOT NULL
        """]

        params: list[Any] = [query_embedding]
        param_idx = 2

        if subject_ids:
            query_parts.append(f"AND n.subject_id = ANY(${param_idx}::uuid[])")
            params.append(subject_ids)
            param_idx += 1

        if date_from:
            query_parts.append(f"AND n.created_at >= ${param_idx}")
            params.append(date_from)
            param_idx += 1

        if date_to:
            query_parts.append(f"AND n.created_at <= ${param_idx}")
            params.append(date_to)
            param_idx += 1

        query_parts.append(f"AND 1 - (n.embedding <=> $1::vector) >= ${param_idx}")
        params.append(similarity_threshold)
        param_idx += 1

        query_parts.append("ORDER BY n.embedding <=> $1::vector")
        query_parts.append(f"LIMIT ${param_idx}")
        params.append(limit)

        query = "\n".join(query_parts)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            VectorSearchResult(
                id=row["id"],
                entity_type=SearchableType.NARRATIVE,
                score=float(row["similarity"]),
                title=row["title"],
                content=row["content"],
                published_at=row["created_at"],
                metadata={
                    "status": row["status"],
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                },
            )
            for row in rows
        ]

    async def get_embedding_by_id(
        self,
        entity_id: UUID,
        entity_type: SearchableType,
    ) -> Optional[list[float]]:
        """
        Retrieve an embedding by entity ID.

        Args:
            entity_id: The entity's UUID.
            entity_type: The type of entity.

        Returns:
            The embedding vector or None if not found.
        """
        table_map = {
            SearchableType.ITEM: "items",
            SearchableType.CLAIM: "claims",
            SearchableType.EVENT: "events",
            SearchableType.NARRATIVE: "narratives",
        }

        table = table_map.get(entity_type)
        if not table:
            return None

        query = f"SELECT embedding FROM {table} WHERE id = $1"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, entity_id)

        if row and row["embedding"]:
            # pgvector returns a string representation, parse it
            embedding_str = row["embedding"]
            if isinstance(embedding_str, str):
                # Parse "[0.1, 0.2, ...]" format
                values = embedding_str.strip("[]").split(",")
                return [float(v.strip()) for v in values]
            return list(row["embedding"])

        return None

    async def find_similar(
        self,
        entity_id: UUID,
        entity_type: SearchableType,
        limit: int = 10,
        exclude_self: bool = True,
    ) -> list[VectorSearchResult]:
        """
        Find similar entities to a given entity.

        Args:
            entity_id: The reference entity's UUID.
            entity_type: The type of entity.
            limit: Maximum number of results.
            exclude_self: Whether to exclude the reference entity from results.

        Returns:
            List of similar entities.
        """
        embedding = await self.get_embedding_by_id(entity_id, entity_type)
        if not embedding:
            return []

        results = await self.search(
            query_embedding=embedding,
            entity_types=[entity_type],
            limit=limit + (1 if exclude_self else 0),
        )

        if exclude_self:
            results = [r for r in results if r.id != entity_id][:limit]

        return results
