"""
Index management for OpenSearch.

This module handles creating indices with proper mappings,
syncing data from PostgreSQL to OpenSearch, and incremental updates.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from opensearchpy import AsyncOpenSearch, NotFoundError
from pydantic import BaseModel

from app.search.lexical import IndexName, LexicalSearch

logger = logging.getLogger(__name__)


class IndexMapping(BaseModel):
    """OpenSearch index mapping configuration."""

    # Number of shards
    number_of_shards: int = 1

    # Number of replicas
    number_of_replicas: int = 1

    # Refresh interval
    refresh_interval: str = "1s"


# Index mappings for each entity type
ITEM_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "subject_id": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "source_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "title": {
                "type": "text",
                "analyzer": "content_analyzer",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "content": {"type": "text", "analyzer": "content_analyzer"},
            "author": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "url": {"type": "keyword"},
            "published_at": {"type": "date"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "reliability_tier": {"type": "keyword"},
            "entity_ids": {"type": "keyword"},
            "entity_names": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "sentiment": {"type": "keyword"},
            "sentiment_score": {"type": "float"},
            "content_type": {"type": "keyword"},
            "language": {"type": "keyword"},
        }
    },
}

CLAIM_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "subject_id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "source_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "text": {"type": "text", "analyzer": "content_analyzer"},
            "content": {"type": "text", "analyzer": "content_analyzer"},  # Alias for text
            "quote": {"type": "text", "analyzer": "content_analyzer"},
            "author": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "url": {"type": "keyword"},
            "published_at": {"type": "date"},
            "created_at": {"type": "date"},
            "reliability_tier": {"type": "keyword"},
            "assessment": {"type": "keyword"},
            "confidence": {"type": "float"},
            "entity_ids": {"type": "keyword"},
            "entity_names": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "claim_type": {"type": "keyword"},
        }
    },
}

EVENT_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "subject_id": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "content_analyzer",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "description": {"type": "text", "analyzer": "content_analyzer"},
            "content": {"type": "text", "analyzer": "content_analyzer"},  # Alias
            "event_date": {"type": "date"},
            "published_at": {"type": "date"},  # Alias for event_date
            "location": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "event_type": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "entity_ids": {"type": "keyword"},
            "entity_names": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "claim_ids": {"type": "keyword"},
            "item_ids": {"type": "keyword"},
        }
    },
}

NARRATIVE_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "subject_id": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "content_analyzer",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "description": {"type": "text", "analyzer": "content_analyzer"},
            "content": {"type": "text", "analyzer": "content_analyzer"},  # Alias
            "status": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "published_at": {"type": "date"},  # Alias for created_at
            "entity_ids": {"type": "keyword"},
            "entity_names": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "event_ids": {"type": "keyword"},
            "claim_ids": {"type": "keyword"},
            "tags": {"type": "keyword"},
        }
    },
}

ENTITY_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "subject_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "aliases": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "entity_type": {"type": "keyword"},
            "description": {"type": "text"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": False},
        }
    },
}

INDEX_MAPPINGS = {
    IndexName.ITEMS: ITEM_MAPPING,
    IndexName.CLAIMS: CLAIM_MAPPING,
    IndexName.EVENTS: EVENT_MAPPING,
    IndexName.NARRATIVES: NARRATIVE_MAPPING,
    IndexName.ENTITIES: ENTITY_MAPPING,
}


@dataclass
class SyncStats:
    """Statistics from a sync operation."""

    index: IndexName
    total_processed: int
    successful: int
    failed: int
    duration_seconds: float


class IndexManager:
    """
    Manages OpenSearch indices for the Lantern search system.

    Handles index creation, deletion, mapping updates, and data
    synchronization from PostgreSQL.
    """

    def __init__(
        self,
        lexical_search: LexicalSearch,
        db_pool: Any = None,  # asyncpg pool
    ):
        """
        Initialize index manager.

        Args:
            lexical_search: Lexical search instance with OpenSearch client.
            db_pool: asyncpg connection pool for PostgreSQL.
        """
        self.lexical_search = lexical_search
        self.db_pool = db_pool

    @property
    def client(self) -> AsyncOpenSearch:
        """Get the OpenSearch client."""
        return self.lexical_search.client

    async def create_index(
        self,
        index: IndexName,
        mapping: Optional[dict[str, Any]] = None,
        delete_if_exists: bool = False,
    ) -> bool:
        """
        Create an OpenSearch index with proper mapping.

        Args:
            index: The index to create.
            mapping: Custom mapping. If None, uses default mapping.
            delete_if_exists: Whether to delete existing index first.

        Returns:
            True if successful.
        """
        try:
            # Check if index exists
            exists = await self.client.indices.exists(index=index.value)

            if exists:
                if delete_if_exists:
                    await self.delete_index(index)
                else:
                    logger.info(f"Index {index.value} already exists")
                    return True

            # Get mapping
            index_mapping = mapping or INDEX_MAPPINGS.get(index, {})

            # Create index
            await self.client.indices.create(
                index=index.value,
                body=index_mapping,
            )

            logger.info(f"Created index: {index.value}")
            return True

        except Exception as e:
            logger.error(f"Failed to create index {index.value}: {e}")
            return False

    async def delete_index(self, index: IndexName) -> bool:
        """
        Delete an OpenSearch index.

        Args:
            index: The index to delete.

        Returns:
            True if successful.
        """
        try:
            await self.client.indices.delete(index=index.value)
            logger.info(f"Deleted index: {index.value}")
            return True
        except NotFoundError:
            logger.warning(f"Index {index.value} not found for deletion")
            return False
        except Exception as e:
            logger.error(f"Failed to delete index {index.value}: {e}")
            return False

    async def create_all_indices(self, delete_if_exists: bool = False) -> dict[IndexName, bool]:
        """
        Create all search indices.

        Args:
            delete_if_exists: Whether to delete existing indices first.

        Returns:
            Dictionary of index -> success status.
        """
        results = {}
        for index in IndexName:
            results[index] = await self.create_index(index, delete_if_exists=delete_if_exists)
        return results

    async def get_index_stats(self, index: IndexName) -> dict[str, Any]:
        """
        Get statistics for an index.

        Args:
            index: The index to get stats for.

        Returns:
            Index statistics.
        """
        try:
            stats = await self.client.indices.stats(index=index.value)
            primaries = stats["_all"]["primaries"]

            return {
                "index": index.value,
                "exists": True,
                "doc_count": primaries["docs"]["count"],
                "deleted_docs": primaries["docs"]["deleted"],
                "size_bytes": primaries["store"]["size_in_bytes"],
                "size_mb": round(primaries["store"]["size_in_bytes"] / 1024 / 1024, 2),
            }
        except NotFoundError:
            return {
                "index": index.value,
                "exists": False,
                "doc_count": 0,
            }
        except Exception as e:
            logger.error(f"Failed to get stats for {index.value}: {e}")
            return {
                "index": index.value,
                "error": str(e),
            }

    async def sync_items(
        self,
        subject_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        batch_size: int = 100,
    ) -> SyncStats:
        """
        Sync items from PostgreSQL to OpenSearch.

        Args:
            subject_id: Optional subject filter.
            since: Only sync items updated since this time.
            batch_size: Number of items per batch.

        Returns:
            Sync statistics.
        """
        import time

        start_time = time.time()
        total = 0
        successful = 0
        failed = 0

        # Build query
        query_parts = ["""
            SELECT
                i.id,
                i.subject_id,
                i.source_id,
                s.name as source_name,
                i.title,
                i.content,
                i.author,
                i.url,
                i.published_at,
                i.created_at,
                i.updated_at,
                s.reliability_tier,
                i.content_type,
                i.language,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.id::text) FROM item_entities ie JOIN entities e ON ie.entity_id = e.id WHERE ie.item_id = i.id),
                    '{}'
                ) as entity_ids,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.name) FROM item_entities ie JOIN entities e ON ie.entity_id = e.id WHERE ie.item_id = i.id),
                    '{}'
                ) as entity_names
            FROM items i
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE 1=1
        """]

        params = []
        param_idx = 1

        if subject_id:
            query_parts.append(f"AND i.subject_id = ${param_idx}")
            params.append(subject_id)
            param_idx += 1

        if since:
            query_parts.append(f"AND i.updated_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        query_parts.append("ORDER BY i.updated_at DESC")

        query = "\n".join(query_parts)

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                batch = []
                async for row in cursor:
                    doc = {
                        "id": str(row["id"]),
                        "subject_id": str(row["subject_id"]) if row["subject_id"] else None,
                        "source_id": str(row["source_id"]) if row["source_id"] else None,
                        "source_name": row["source_name"],
                        "title": row["title"],
                        "content": row["content"],
                        "author": row["author"],
                        "url": row["url"],
                        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                        "reliability_tier": row["reliability_tier"],
                        "content_type": row["content_type"],
                        "language": row["language"],
                        "entity_ids": list(row["entity_ids"]) if row["entity_ids"] else [],
                        "entity_names": list(row["entity_names"]) if row["entity_names"] else [],
                    }
                    batch.append((row["id"], doc))
                    total += 1

                    if len(batch) >= batch_size:
                        s, f = await self.lexical_search.bulk_index(IndexName.ITEMS, batch)
                        successful += s
                        failed += f
                        batch = []

                # Index remaining batch
                if batch:
                    s, f = await self.lexical_search.bulk_index(IndexName.ITEMS, batch)
                    successful += s
                    failed += f

        duration = time.time() - start_time
        logger.info(f"Synced {successful}/{total} items in {duration:.2f}s")

        return SyncStats(
            index=IndexName.ITEMS,
            total_processed=total,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration, 2),
        )

    async def sync_claims(
        self,
        subject_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        batch_size: int = 100,
    ) -> SyncStats:
        """Sync claims from PostgreSQL to OpenSearch."""
        import time

        start_time = time.time()
        total = 0
        successful = 0
        failed = 0

        query_parts = ["""
            SELECT
                c.id,
                c.subject_id,
                c.item_id,
                i.source_id,
                s.name as source_name,
                c.text,
                c.quote,
                i.author,
                i.url,
                i.published_at,
                c.created_at,
                s.reliability_tier,
                c.assessment,
                c.confidence,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.id::text) FROM claim_entities ce JOIN entities e ON ce.entity_id = e.id WHERE ce.claim_id = c.id),
                    '{}'
                ) as entity_ids,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.name) FROM claim_entities ce JOIN entities e ON ce.entity_id = e.id WHERE ce.claim_id = c.id),
                    '{}'
                ) as entity_names
            FROM claims c
            LEFT JOIN items i ON c.item_id = i.id
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE 1=1
        """]

        params = []
        param_idx = 1

        if subject_id:
            query_parts.append(f"AND c.subject_id = ${param_idx}")
            params.append(subject_id)
            param_idx += 1

        if since:
            query_parts.append(f"AND c.updated_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        query = "\n".join(query_parts)

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                batch = []
                async for row in cursor:
                    doc = {
                        "id": str(row["id"]),
                        "subject_id": str(row["subject_id"]) if row["subject_id"] else None,
                        "item_id": str(row["item_id"]) if row["item_id"] else None,
                        "source_id": str(row["source_id"]) if row["source_id"] else None,
                        "source_name": row["source_name"],
                        "text": row["text"],
                        "content": row["text"],  # Alias
                        "quote": row["quote"],
                        "author": row["author"],
                        "url": row["url"],
                        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "reliability_tier": row["reliability_tier"],
                        "assessment": row["assessment"],
                        "confidence": row["confidence"],
                        "entity_ids": list(row["entity_ids"]) if row["entity_ids"] else [],
                        "entity_names": list(row["entity_names"]) if row["entity_names"] else [],
                    }
                    batch.append((row["id"], doc))
                    total += 1

                    if len(batch) >= batch_size:
                        s, f = await self.lexical_search.bulk_index(IndexName.CLAIMS, batch)
                        successful += s
                        failed += f
                        batch = []

                if batch:
                    s, f = await self.lexical_search.bulk_index(IndexName.CLAIMS, batch)
                    successful += s
                    failed += f

        duration = time.time() - start_time
        logger.info(f"Synced {successful}/{total} claims in {duration:.2f}s")

        return SyncStats(
            index=IndexName.CLAIMS,
            total_processed=total,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration, 2),
        )

    async def sync_events(
        self,
        subject_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        batch_size: int = 100,
    ) -> SyncStats:
        """Sync events from PostgreSQL to OpenSearch."""
        import time

        start_time = time.time()
        total = 0
        successful = 0
        failed = 0

        query_parts = ["""
            SELECT
                e.id,
                e.subject_id,
                e.title,
                e.description,
                e.event_date,
                e.location,
                e.event_type,
                e.created_at,
                e.updated_at,
                COALESCE(
                    (SELECT array_agg(DISTINCT ent.id::text) FROM event_entities ee JOIN entities ent ON ee.entity_id = ent.id WHERE ee.event_id = e.id),
                    '{}'
                ) as entity_ids,
                COALESCE(
                    (SELECT array_agg(DISTINCT ent.name) FROM event_entities ee JOIN entities ent ON ee.entity_id = ent.id WHERE ee.event_id = e.id),
                    '{}'
                ) as entity_names
            FROM events e
            WHERE 1=1
        """]

        params = []
        param_idx = 1

        if subject_id:
            query_parts.append(f"AND e.subject_id = ${param_idx}")
            params.append(subject_id)
            param_idx += 1

        if since:
            query_parts.append(f"AND e.updated_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        query = "\n".join(query_parts)

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                batch = []
                async for row in cursor:
                    doc = {
                        "id": str(row["id"]),
                        "subject_id": str(row["subject_id"]) if row["subject_id"] else None,
                        "title": row["title"],
                        "description": row["description"],
                        "content": row["description"],  # Alias
                        "event_date": row["event_date"].isoformat() if row["event_date"] else None,
                        "published_at": row["event_date"].isoformat() if row["event_date"] else None,
                        "location": row["location"],
                        "event_type": row["event_type"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                        "entity_ids": list(row["entity_ids"]) if row["entity_ids"] else [],
                        "entity_names": list(row["entity_names"]) if row["entity_names"] else [],
                    }
                    batch.append((row["id"], doc))
                    total += 1

                    if len(batch) >= batch_size:
                        s, f = await self.lexical_search.bulk_index(IndexName.EVENTS, batch)
                        successful += s
                        failed += f
                        batch = []

                if batch:
                    s, f = await self.lexical_search.bulk_index(IndexName.EVENTS, batch)
                    successful += s
                    failed += f

        duration = time.time() - start_time
        logger.info(f"Synced {successful}/{total} events in {duration:.2f}s")

        return SyncStats(
            index=IndexName.EVENTS,
            total_processed=total,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration, 2),
        )

    async def sync_narratives(
        self,
        subject_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        batch_size: int = 100,
    ) -> SyncStats:
        """Sync narratives from PostgreSQL to OpenSearch."""
        import time

        start_time = time.time()
        total = 0
        successful = 0
        failed = 0

        query_parts = ["""
            SELECT
                n.id,
                n.subject_id,
                n.title,
                n.description,
                n.status,
                n.created_at,
                n.updated_at,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.id::text) FROM narrative_entities ne JOIN entities e ON ne.entity_id = e.id WHERE ne.narrative_id = n.id),
                    '{}'
                ) as entity_ids,
                COALESCE(
                    (SELECT array_agg(DISTINCT e.name) FROM narrative_entities ne JOIN entities e ON ne.entity_id = e.id WHERE ne.narrative_id = n.id),
                    '{}'
                ) as entity_names
            FROM narratives n
            WHERE 1=1
        """]

        params = []
        param_idx = 1

        if subject_id:
            query_parts.append(f"AND n.subject_id = ${param_idx}")
            params.append(subject_id)
            param_idx += 1

        if since:
            query_parts.append(f"AND n.updated_at > ${param_idx}")
            params.append(since)
            param_idx += 1

        query = "\n".join(query_parts)

        async with self.db_pool.acquire() as conn:
            async with conn.transaction():
                cursor = await conn.cursor(query, *params)

                batch = []
                async for row in cursor:
                    doc = {
                        "id": str(row["id"]),
                        "subject_id": str(row["subject_id"]) if row["subject_id"] else None,
                        "title": row["title"],
                        "description": row["description"],
                        "content": row["description"],  # Alias
                        "status": row["status"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                        "published_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "entity_ids": list(row["entity_ids"]) if row["entity_ids"] else [],
                        "entity_names": list(row["entity_names"]) if row["entity_names"] else [],
                    }
                    batch.append((row["id"], doc))
                    total += 1

                    if len(batch) >= batch_size:
                        s, f = await self.lexical_search.bulk_index(IndexName.NARRATIVES, batch)
                        successful += s
                        failed += f
                        batch = []

                if batch:
                    s, f = await self.lexical_search.bulk_index(IndexName.NARRATIVES, batch)
                    successful += s
                    failed += f

        duration = time.time() - start_time
        logger.info(f"Synced {successful}/{total} narratives in {duration:.2f}s")

        return SyncStats(
            index=IndexName.NARRATIVES,
            total_processed=total,
            successful=successful,
            failed=failed,
            duration_seconds=round(duration, 2),
        )

    async def sync_all(
        self,
        subject_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
    ) -> dict[IndexName, SyncStats]:
        """
        Sync all entity types.

        Args:
            subject_id: Optional subject filter.
            since: Only sync items updated since this time.

        Returns:
            Dictionary of index -> sync stats.
        """
        results = {}

        results[IndexName.ITEMS] = await self.sync_items(subject_id, since)
        results[IndexName.CLAIMS] = await self.sync_claims(subject_id, since)
        results[IndexName.EVENTS] = await self.sync_events(subject_id, since)
        results[IndexName.NARRATIVES] = await self.sync_narratives(subject_id, since)

        return results

    async def index_single_item(self, item_id: UUID) -> bool:
        """Index a single item (for incremental updates)."""
        query = """
            SELECT
                i.id,
                i.subject_id,
                i.source_id,
                s.name as source_name,
                i.title,
                i.content,
                i.author,
                i.url,
                i.published_at,
                i.created_at,
                i.updated_at,
                s.reliability_tier,
                i.content_type,
                i.language
            FROM items i
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE i.id = $1
        """

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, item_id)

        if not row:
            return False

        doc = {
            "id": str(row["id"]),
            "subject_id": str(row["subject_id"]) if row["subject_id"] else None,
            "source_id": str(row["source_id"]) if row["source_id"] else None,
            "source_name": row["source_name"],
            "title": row["title"],
            "content": row["content"],
            "author": row["author"],
            "url": row["url"],
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "reliability_tier": row["reliability_tier"],
            "content_type": row["content_type"],
            "language": row["language"],
        }

        return await self.lexical_search.index_document(IndexName.ITEMS, item_id, doc, refresh=True)

    async def delete_item_from_index(self, item_id: UUID) -> bool:
        """Remove an item from the search index."""
        return await self.lexical_search.delete_document(IndexName.ITEMS, item_id, refresh=True)
