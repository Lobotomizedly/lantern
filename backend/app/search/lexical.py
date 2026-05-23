"""
Lexical search using OpenSearch for BM25 full-text search.

This module provides full-text search capabilities using OpenSearch's
BM25 ranking algorithm with support for field boosting and exact matching.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from opensearchpy import AsyncOpenSearch, NotFoundError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class IndexName(str, Enum):
    """OpenSearch index names."""

    ITEMS = "lantern_items"
    CLAIMS = "lantern_claims"
    EVENTS = "lantern_events"
    NARRATIVES = "lantern_narratives"
    ENTITIES = "lantern_entities"


@dataclass
class LexicalSearchResult:
    """A single result from lexical search."""

    id: UUID
    index: IndexName
    score: float  # BM25 score
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


class LexicalSearchConfig(BaseModel):
    """Configuration for lexical search."""

    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_scheme: str = "https"
    opensearch_user: str = "admin"
    opensearch_password: str = "admin"
    verify_certs: bool = False
    default_limit: int = 20
    max_limit: int = 100
    highlight_fragment_size: int = 150
    highlight_number_of_fragments: int = 3


class FieldBoosts(BaseModel):
    """Field boost weights for BM25 search."""

    title: float = 3.0
    content: float = 1.0
    entity_names: float = 2.5
    author: float = 1.5
    source_name: float = 2.0
    quote: float = 2.0


class LexicalSearch:
    """
    Lexical search engine using OpenSearch.

    Performs BM25 full-text search with field boosting, exact matching,
    and highlighting support.
    """

    def __init__(
        self,
        client: Optional[AsyncOpenSearch] = None,
        config: Optional[LexicalSearchConfig] = None,
        boosts: Optional[FieldBoosts] = None,
    ):
        """
        Initialize lexical search.

        Args:
            client: OpenSearch async client. If None, will create one.
            config: Lexical search configuration.
            boosts: Field boost weights.
        """
        self._client = client
        self._external_client = client is not None
        self.config = config or LexicalSearchConfig()
        self.boosts = boosts or FieldBoosts()

    async def initialize(self) -> None:
        """Initialize the OpenSearch client if not provided externally."""
        if self._client is None:
            self._client = AsyncOpenSearch(
                hosts=[{
                    "host": self.config.opensearch_host,
                    "port": self.config.opensearch_port,
                }],
                http_auth=(self.config.opensearch_user, self.config.opensearch_password),
                use_ssl=self.config.opensearch_scheme == "https",
                verify_certs=self.config.verify_certs,
                ssl_show_warn=False,
            )
            logger.info("OpenSearch client initialized")

    async def close(self) -> None:
        """Close the OpenSearch client if we created it."""
        if self._client and not self._external_client:
            await self._client.close()
            self._client = None
            logger.info("OpenSearch client closed")

    @property
    def client(self) -> AsyncOpenSearch:
        """Get the OpenSearch client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("Lexical search not initialized. Call initialize() first.")
        return self._client

    async def search(
        self,
        query: str,
        indices: Optional[list[IndexName]] = None,
        subject_ids: Optional[list[UUID]] = None,
        source_ids: Optional[list[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        reliability_tiers: Optional[list[str]] = None,
        entity_ids: Optional[list[UUID]] = None,
        exact_match_fields: Optional[dict[str, str]] = None,
        limit: int = 20,
        offset: int = 0,
        include_highlights: bool = True,
    ) -> list[LexicalSearchResult]:
        """
        Perform BM25 full-text search.

        Args:
            query: The search query text.
            indices: Indices to search. Default: all indices.
            subject_ids: Filter by subject IDs.
            source_ids: Filter by source IDs.
            date_from: Filter by published date (from).
            date_to: Filter by published date (to).
            reliability_tiers: Filter by reliability tiers.
            entity_ids: Filter by related entity IDs.
            exact_match_fields: Fields requiring exact match (e.g., {"author": "John Doe"}).
            limit: Maximum number of results.
            offset: Offset for pagination.
            include_highlights: Whether to include search highlights.

        Returns:
            List of search results ordered by BM25 score.
        """
        limit = min(limit, self.config.max_limit)
        indices = indices or list(IndexName)
        index_names = [idx.value for idx in indices]

        # Build the query
        must_clauses: list[dict[str, Any]] = []
        filter_clauses: list[dict[str, Any]] = []

        # Main multi-match query with field boosting
        if query:
            must_clauses.append({
                "multi_match": {
                    "query": query,
                    "fields": [
                        f"title^{self.boosts.title}",
                        f"content^{self.boosts.content}",
                        f"entity_names^{self.boosts.entity_names}",
                        f"author^{self.boosts.author}",
                        f"source_name^{self.boosts.source_name}",
                        f"quote^{self.boosts.quote}",
                    ],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                    "operator": "or",
                    "minimum_should_match": "30%",
                }
            })

        # Exact match filters
        if exact_match_fields:
            for field_name, value in exact_match_fields.items():
                filter_clauses.append({
                    "term": {f"{field_name}.keyword": value}
                })

        # Subject filter
        if subject_ids:
            filter_clauses.append({
                "terms": {"subject_id": [str(sid) for sid in subject_ids]}
            })

        # Source filter
        if source_ids:
            filter_clauses.append({
                "terms": {"source_id": [str(sid) for sid in source_ids]}
            })

        # Date range filter
        if date_from or date_to:
            date_range: dict[str, Any] = {}
            if date_from:
                date_range["gte"] = date_from.isoformat()
            if date_to:
                date_range["lte"] = date_to.isoformat()
            filter_clauses.append({
                "range": {"published_at": date_range}
            })

        # Reliability tier filter
        if reliability_tiers:
            filter_clauses.append({
                "terms": {"reliability_tier": reliability_tiers}
            })

        # Entity filter
        if entity_ids:
            filter_clauses.append({
                "terms": {"entity_ids": [str(eid) for eid in entity_ids]}
            })

        # Build the full query
        bool_query: dict[str, Any] = {}
        if must_clauses:
            bool_query["must"] = must_clauses
        if filter_clauses:
            bool_query["filter"] = filter_clauses

        # If no must clauses, match all
        if not must_clauses:
            bool_query["must"] = [{"match_all": {}}]

        search_body: dict[str, Any] = {
            "query": {"bool": bool_query},
            "from": offset,
            "size": limit,
            "track_total_hits": True,
        }

        # Add highlighting
        if include_highlights:
            search_body["highlight"] = {
                "fields": {
                    "title": {},
                    "content": {
                        "fragment_size": self.config.highlight_fragment_size,
                        "number_of_fragments": self.config.highlight_number_of_fragments,
                    },
                    "quote": {},
                },
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            }

        try:
            response = await self.client.search(
                index=",".join(index_names),
                body=search_body,
            )
        except NotFoundError:
            logger.warning(f"Indices not found: {index_names}")
            return []

        return self._parse_response(response)

    async def search_exact_quote(
        self,
        quote: str,
        indices: Optional[list[IndexName]] = None,
        limit: int = 10,
    ) -> list[LexicalSearchResult]:
        """
        Search for an exact quote.

        Args:
            quote: The exact quote to search for.
            indices: Indices to search.
            limit: Maximum number of results.

        Returns:
            List of results containing the exact quote.
        """
        indices = indices or list(IndexName)
        index_names = [idx.value for idx in indices]

        search_body = {
            "query": {
                "bool": {
                    "should": [
                        {"match_phrase": {"content": quote}},
                        {"match_phrase": {"quote": quote}},
                        {"match_phrase": {"title": quote}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": limit,
        }

        try:
            response = await self.client.search(
                index=",".join(index_names),
                body=search_body,
            )
        except NotFoundError:
            return []

        return self._parse_response(response)

    async def search_by_entity_name(
        self,
        name: str,
        indices: Optional[list[IndexName]] = None,
        limit: int = 20,
    ) -> list[LexicalSearchResult]:
        """
        Search for content mentioning an entity by name.

        Args:
            name: The entity name to search for.
            indices: Indices to search.
            limit: Maximum number of results.

        Returns:
            List of results mentioning the entity.
        """
        indices = indices or list(IndexName)
        index_names = [idx.value for idx in indices]

        search_body = {
            "query": {
                "bool": {
                    "should": [
                        # Exact match on entity names (highest priority)
                        {
                            "term": {
                                "entity_names.keyword": {
                                    "value": name,
                                    "boost": 5.0,
                                }
                            }
                        },
                        # Phrase match on entity names
                        {
                            "match_phrase": {
                                "entity_names": {
                                    "query": name,
                                    "boost": 3.0,
                                }
                            }
                        },
                        # Phrase match in content
                        {
                            "match_phrase": {
                                "content": {
                                    "query": name,
                                    "boost": 1.5,
                                }
                            }
                        },
                        # Phrase match in title
                        {
                            "match_phrase": {
                                "title": {
                                    "query": name,
                                    "boost": 2.0,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": limit,
        }

        try:
            response = await self.client.search(
                index=",".join(index_names),
                body=search_body,
            )
        except NotFoundError:
            return []

        return self._parse_response(response)

    async def index_document(
        self,
        index: IndexName,
        doc_id: UUID,
        document: dict[str, Any],
        refresh: bool = False,
    ) -> bool:
        """
        Index a single document.

        Args:
            index: The index to add the document to.
            doc_id: The document ID.
            document: The document data.
            refresh: Whether to refresh the index immediately.

        Returns:
            True if successful.
        """
        try:
            await self.client.index(
                index=index.value,
                id=str(doc_id),
                body=document,
                refresh=refresh,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to index document {doc_id}: {e}")
            return False

    async def bulk_index(
        self,
        index: IndexName,
        documents: list[tuple[UUID, dict[str, Any]]],
        refresh: bool = False,
    ) -> tuple[int, int]:
        """
        Bulk index multiple documents.

        Args:
            index: The index to add documents to.
            documents: List of (doc_id, document) tuples.
            refresh: Whether to refresh the index after.

        Returns:
            Tuple of (success_count, error_count).
        """
        if not documents:
            return 0, 0

        actions = []
        for doc_id, doc in documents:
            actions.append({"index": {"_index": index.value, "_id": str(doc_id)}})
            actions.append(doc)

        try:
            response = await self.client.bulk(body=actions, refresh=refresh)
            errors = response.get("errors", False)
            items = response.get("items", [])

            success_count = sum(1 for item in items if "error" not in item.get("index", {}))
            error_count = len(items) - success_count

            if errors:
                for item in items:
                    if "error" in item.get("index", {}):
                        logger.error(f"Bulk index error: {item['index']['error']}")

            return success_count, error_count
        except Exception as e:
            logger.error(f"Bulk index failed: {e}")
            return 0, len(documents)

    async def delete_document(
        self,
        index: IndexName,
        doc_id: UUID,
        refresh: bool = False,
    ) -> bool:
        """
        Delete a document from the index.

        Args:
            index: The index containing the document.
            doc_id: The document ID to delete.
            refresh: Whether to refresh the index immediately.

        Returns:
            True if successful.
        """
        try:
            await self.client.delete(
                index=index.value,
                id=str(doc_id),
                refresh=refresh,
            )
            return True
        except NotFoundError:
            logger.warning(f"Document not found for deletion: {doc_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False

    async def update_document(
        self,
        index: IndexName,
        doc_id: UUID,
        updates: dict[str, Any],
        refresh: bool = False,
    ) -> bool:
        """
        Update a document in the index.

        Args:
            index: The index containing the document.
            doc_id: The document ID to update.
            updates: The fields to update.
            refresh: Whether to refresh the index immediately.

        Returns:
            True if successful.
        """
        try:
            await self.client.update(
                index=index.value,
                id=str(doc_id),
                body={"doc": updates},
                refresh=refresh,
            )
            return True
        except NotFoundError:
            logger.warning(f"Document not found for update: {doc_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to update document {doc_id}: {e}")
            return False

    def _parse_response(self, response: dict[str, Any]) -> list[LexicalSearchResult]:
        """Parse OpenSearch response into result objects."""
        results = []
        hits = response.get("hits", {}).get("hits", [])

        for hit in hits:
            source = hit.get("_source", {})
            highlights = hit.get("highlight", {})

            # Parse published_at if present
            published_at = None
            if source.get("published_at"):
                try:
                    published_at = datetime.fromisoformat(
                        source["published_at"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            # Determine index from _index field
            index_value = hit.get("_index", "")
            try:
                index = IndexName(index_value)
            except ValueError:
                # Try to match by prefix
                index = IndexName.ITEMS
                for idx in IndexName:
                    if index_value.startswith(idx.value):
                        index = idx
                        break

            results.append(
                LexicalSearchResult(
                    id=UUID(hit["_id"]),
                    index=index,
                    score=float(hit.get("_score", 0)),
                    title=source.get("title"),
                    content=source.get("content", source.get("text"))[:500] if source.get("content") or source.get("text") else None,
                    source_id=UUID(source["source_id"]) if source.get("source_id") else None,
                    source_name=source.get("source_name"),
                    author=source.get("author"),
                    published_at=published_at,
                    reliability_tier=source.get("reliability_tier"),
                    url=source.get("url"),
                    highlights=highlights,
                    metadata={
                        k: v for k, v in source.items()
                        if k not in {
                            "title", "content", "text", "source_id", "source_name",
                            "author", "published_at", "reliability_tier", "url"
                        }
                    },
                )
            )

        return results

    async def get_document_count(self, index: IndexName) -> int:
        """Get the total document count in an index."""
        try:
            response = await self.client.count(index=index.value)
            return response.get("count", 0)
        except NotFoundError:
            return 0

    async def index_exists(self, index: IndexName) -> bool:
        """Check if an index exists."""
        return await self.client.indices.exists(index=index.value)
