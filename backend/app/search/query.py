"""
Query parsing and execution for the Lantern search system.

This module handles parsing natural language queries, extracting
structured filters, and executing the full hybrid retrieval pipeline.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.search.filters import (
    SearchFilters,
    parse_date_expression,
    ReliabilityTier,
    SentimentValue,
)
from app.search.vector import SearchableType
from app.search.hybrid import HybridSearch, HybridSearchResult, RRFConfig
from app.search.rerank import CrossEncoderReranker, RerankedResult

logger = logging.getLogger(__name__)


@dataclass
class ParsedQuery:
    """A parsed search query with extracted components."""

    # The cleaned query text for search
    query_text: str

    # Original query before parsing
    original_query: str

    # Extracted filters
    filters: SearchFilters = field(default_factory=SearchFilters)

    # Extracted entity types to search
    entity_types: Optional[list[SearchableType]] = None

    # Query intent (informational, navigational, etc.)
    intent: str = "informational"

    # Confidence in parsing (0-1)
    parse_confidence: float = 1.0

    # Extracted named entities from query
    mentioned_entities: list[str] = field(default_factory=list)

    # Any quoted phrases for exact matching
    exact_phrases: list[str] = field(default_factory=list)

    # Search mode override
    search_mode: Optional[str] = None  # "vector", "lexical", "hybrid"


class QueryParserConfig(BaseModel):
    """Configuration for query parsing."""

    # Whether to extract filters from query text
    extract_filters: bool = True

    # Whether to identify entity types from query
    detect_entity_types: bool = True

    # Whether to extract named entities
    extract_entities: bool = True

    # Whether to detect query intent
    detect_intent: bool = True

    # Minimum query length for full parsing
    min_query_length: int = 3


class QueryParser:
    """
    Parser for natural language search queries.

    Extracts structured filters, entity types, and other search
    parameters from free-form query text.
    """

    def __init__(self, config: Optional[QueryParserConfig] = None):
        """
        Initialize query parser.

        Args:
            config: Parser configuration.
        """
        self.config = config or QueryParserConfig()

        # Patterns for filter extraction
        self._date_patterns = [
            (r"(?:from|since|after)\s+(\d{4}-\d{2}-\d{2})", "date_from"),
            (r"(?:to|until|before)\s+(\d{4}-\d{2}-\d{2})", "date_to"),
            (r"(last\s+\d+\s+(?:day|week|month|year)s?)", "date_range"),
            (r"(past\s+(?:week|month|year))", "date_range"),
        ]

        self._reliability_pattern = re.compile(
            r"(?:tier|reliability)\s*[=:]?\s*(T[1-5])",
            re.IGNORECASE
        )

        self._sentiment_pattern = re.compile(
            r"(?:sentiment)\s*[=:]?\s*(positive|negative|neutral|mixed)",
            re.IGNORECASE
        )

        self._source_pattern = re.compile(
            r"(?:source|from)\s*[=:]?\s*[\"']([^\"']+)[\"']",
            re.IGNORECASE
        )

        self._entity_type_keywords = {
            "items": SearchableType.ITEM,
            "articles": SearchableType.ITEM,
            "documents": SearchableType.ITEM,
            "claims": SearchableType.CLAIM,
            "statements": SearchableType.CLAIM,
            "assertions": SearchableType.CLAIM,
            "events": SearchableType.EVENT,
            "occurrences": SearchableType.EVENT,
            "incidents": SearchableType.EVENT,
            "narratives": SearchableType.NARRATIVE,
            "stories": SearchableType.NARRATIVE,
            "threads": SearchableType.NARRATIVE,
        }

        self._intent_keywords = {
            "informational": ["what", "who", "when", "where", "why", "how", "explain", "describe"],
            "navigational": ["find", "locate", "show", "get", "fetch"],
            "analytical": ["analyze", "compare", "contrast", "trend", "pattern"],
            "verification": ["verify", "confirm", "check", "validate", "true", "false"],
        }

    def parse(self, query: str) -> ParsedQuery:
        """
        Parse a natural language query.

        Args:
            query: The raw query string.

        Returns:
            ParsedQuery with extracted components.
        """
        original_query = query
        query_text = query.strip()

        if len(query_text) < self.config.min_query_length:
            return ParsedQuery(
                query_text=query_text,
                original_query=original_query,
                parse_confidence=0.5,
            )

        # Extract quoted phrases first
        exact_phrases = self._extract_quoted_phrases(query_text)

        # Extract filters
        filters = SearchFilters()
        if self.config.extract_filters:
            filters, query_text = self._extract_filters(query_text)

        # Detect entity types
        entity_types = None
        if self.config.detect_entity_types:
            entity_types, query_text = self._detect_entity_types(query_text)

        # Extract named entities
        mentioned_entities = []
        if self.config.extract_entities:
            mentioned_entities = self._extract_named_entities(query_text)

        # Detect intent
        intent = "informational"
        if self.config.detect_intent:
            intent = self._detect_intent(query_text)

        # Detect search mode
        search_mode = self._detect_search_mode(query_text)

        # Clean up the query text
        query_text = self._clean_query(query_text)

        return ParsedQuery(
            query_text=query_text,
            original_query=original_query,
            filters=filters,
            entity_types=entity_types,
            intent=intent,
            mentioned_entities=mentioned_entities,
            exact_phrases=exact_phrases,
            search_mode=search_mode,
        )

    def _extract_quoted_phrases(self, query: str) -> list[str]:
        """Extract quoted phrases for exact matching."""
        # Match both single and double quotes
        pattern = r'["\']([^"\']+)["\']'
        matches = re.findall(pattern, query)
        return matches

    def _extract_filters(self, query: str) -> tuple[SearchFilters, str]:
        """Extract structured filters from query text."""
        filters = SearchFilters()
        remaining = query

        # Extract date filters
        for pattern, filter_type in self._date_patterns:
            match = re.search(pattern, remaining, re.IGNORECASE)
            if match:
                if filter_type == "date_from":
                    try:
                        filters.date_from = datetime.fromisoformat(match.group(1))
                    except ValueError:
                        pass
                elif filter_type == "date_to":
                    try:
                        filters.date_to = datetime.fromisoformat(match.group(1))
                    except ValueError:
                        pass
                elif filter_type == "date_range":
                    date_filter = parse_date_expression(match.group(1))
                    if date_filter:
                        filters.date_from = date_filter.date_from
                        filters.date_to = date_filter.date_to

                remaining = remaining[:match.start()] + remaining[match.end():]

        # Extract reliability tier
        match = self._reliability_pattern.search(remaining)
        if match:
            tier = match.group(1).upper()
            filters.reliability_tiers = [tier]
            remaining = remaining[:match.start()] + remaining[match.end():]

        # Extract sentiment
        match = self._sentiment_pattern.search(remaining)
        if match:
            sentiment = match.group(1).lower()
            filters.sentiments = [sentiment]
            remaining = remaining[:match.start()] + remaining[match.end():]

        # Extract source
        match = self._source_pattern.search(remaining)
        if match:
            source_name = match.group(1)
            filters.source_names = [source_name]
            remaining = remaining[:match.start()] + remaining[match.end():]

        return filters, remaining.strip()

    def _detect_entity_types(self, query: str) -> tuple[Optional[list[SearchableType]], str]:
        """Detect entity types from query keywords."""
        query_lower = query.lower()
        detected_types = set()
        remaining = query

        for keyword, entity_type in self._entity_type_keywords.items():
            if keyword in query_lower:
                detected_types.add(entity_type)
                # Remove the keyword from query
                pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                remaining = pattern.sub("", remaining)

        if detected_types:
            return list(detected_types), remaining.strip()
        return None, remaining

    def _extract_named_entities(self, query: str) -> list[str]:
        """Extract potential named entities from query."""
        # Simple heuristic: capitalized word sequences
        # In production, use NER model
        entities = []

        # Match capitalized sequences (potential names/organizations)
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        matches = re.findall(pattern, query)

        for match in matches:
            # Filter out common words that might be capitalized
            if match.lower() not in {"the", "a", "an", "in", "on", "at", "for", "and", "or"}:
                entities.append(match)

        return entities

    def _detect_intent(self, query: str) -> str:
        """Detect the intent of the query."""
        query_lower = query.lower()

        for intent, keywords in self._intent_keywords.items():
            for keyword in keywords:
                if keyword in query_lower:
                    return intent

        return "informational"

    def _detect_search_mode(self, query: str) -> Optional[str]:
        """Detect if query specifies a search mode."""
        query_lower = query.lower()

        if "semantic:" in query_lower or "vector:" in query_lower:
            return "vector"
        if "keyword:" in query_lower or "exact:" in query_lower:
            return "lexical"
        if "hybrid:" in query_lower:
            return "hybrid"

        return None

    def _clean_query(self, query: str) -> str:
        """Clean up query text after filter extraction."""
        # Remove mode prefixes
        query = re.sub(r'^(semantic|vector|keyword|exact|hybrid):\s*', '', query, flags=re.IGNORECASE)

        # Remove multiple spaces
        query = re.sub(r'\s+', ' ', query)

        return query.strip()


class QueryExecutorConfig(BaseModel):
    """Configuration for query execution."""

    # Default number of results
    default_limit: int = 20

    # Maximum results per query
    max_limit: int = 100

    # Whether to apply reranking
    enable_reranking: bool = True

    # Number of results to rerank
    rerank_top_n: int = 50

    # Default RRF configuration
    rrf_config: RRFConfig = Field(default_factory=RRFConfig)


@dataclass
class QueryExecutionResult:
    """Result of query execution."""

    query: ParsedQuery
    results: list[RerankedResult]
    total_count: int
    search_time_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class QueryExecutor:
    """
    Executes parsed queries through the full retrieval pipeline.

    Coordinates between vector search, lexical search, hybrid fusion,
    and reranking to produce final results.
    """

    def __init__(
        self,
        hybrid_search: HybridSearch,
        reranker: CrossEncoderReranker,
        embedding_fn: Any,  # Callable to generate embeddings
        config: Optional[QueryExecutorConfig] = None,
    ):
        """
        Initialize query executor.

        Args:
            hybrid_search: Hybrid search engine.
            reranker: Cross-encoder reranker.
            embedding_fn: Function to generate query embeddings.
            config: Executor configuration.
        """
        self.hybrid_search = hybrid_search
        self.reranker = reranker
        self.embedding_fn = embedding_fn
        self.config = config or QueryExecutorConfig()
        self.parser = QueryParser()

    async def execute(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        entity_types: Optional[list[SearchableType]] = None,
        limit: int = 20,
        offset: int = 0,
        enable_reranking: Optional[bool] = None,
    ) -> QueryExecutionResult:
        """
        Execute a search query through the full pipeline.

        Args:
            query: Natural language query.
            filters: Additional filters to apply.
            entity_types: Entity types to search.
            limit: Maximum results to return.
            offset: Offset for pagination.
            enable_reranking: Whether to apply reranking.

        Returns:
            QueryExecutionResult with final results.
        """
        import time

        start_time = time.time()

        # Parse the query
        parsed = self.parser.parse(query)

        # Merge provided filters with extracted filters
        effective_filters = parsed.filters
        if filters:
            effective_filters = effective_filters.merge(filters)

        # Determine entity types
        effective_entity_types = entity_types or parsed.entity_types

        # Determine search mode
        search_mode = parsed.search_mode or "hybrid"

        # Generate query embedding
        query_embedding = await self._get_embedding(parsed.query_text)

        # Execute search based on mode
        hybrid_results: list[HybridSearchResult]

        if search_mode == "vector":
            hybrid_results = await self.hybrid_search.search_vector_only(
                query_embedding=query_embedding,
                entity_types=effective_entity_types,
                filters=effective_filters,
                limit=self.config.rerank_top_n if enable_reranking else limit,
                offset=offset if not enable_reranking else 0,
            )
        elif search_mode == "lexical":
            hybrid_results = await self.hybrid_search.search_lexical_only(
                query=parsed.query_text,
                entity_types=effective_entity_types,
                filters=effective_filters,
                limit=self.config.rerank_top_n if enable_reranking else limit,
                offset=offset if not enable_reranking else 0,
            )
        else:  # hybrid
            hybrid_results = await self.hybrid_search.search(
                query=parsed.query_text,
                query_embedding=query_embedding,
                entity_types=effective_entity_types,
                filters=effective_filters,
                limit=self.config.rerank_top_n if enable_reranking else limit,
                offset=offset if not enable_reranking else 0,
            )

        # Apply reranking if enabled
        rerank = enable_reranking if enable_reranking is not None else self.config.enable_reranking

        if rerank and hybrid_results:
            final_results = await self.reranker.rerank(
                query=parsed.query_text,
                results=hybrid_results,
                top_n=limit,
            )
            # Apply offset after reranking
            if offset > 0:
                final_results = final_results[offset:]
        else:
            # Convert to RerankedResult format
            final_results = [
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
            ][:limit]

        elapsed_ms = (time.time() - start_time) * 1000

        return QueryExecutionResult(
            query=parsed,
            results=final_results,
            total_count=len(hybrid_results),
            search_time_ms=round(elapsed_ms, 2),
            metadata={
                "search_mode": search_mode,
                "reranking_enabled": rerank,
                "filters_applied": not effective_filters.is_empty(),
            },
        )

    async def execute_with_provenance(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Execute query and return results with full provenance.

        Returns results enriched with source, author, date, reliability,
        and URL information.

        Args:
            query: Natural language query.
            filters: Additional filters.
            limit: Maximum results.

        Returns:
            List of result dictionaries with provenance.
        """
        result = await self.execute(query, filters=filters, limit=limit)

        return [
            {
                "id": str(r.id),
                "entity_type": r.entity_type.value,
                "score": r.rerank_score,
                "title": r.title,
                "content": r.content,
                "provenance": {
                    "source_id": str(r.source_id) if r.source_id else None,
                    "source_name": r.source_name,
                    "author": r.author,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "reliability_tier": r.reliability_tier,
                    "url": r.url,
                },
                "highlights": r.highlights,
                "metadata": r.metadata,
            }
            for r in result.results
        ]

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for query text."""
        if callable(self.embedding_fn):
            # Support both sync and async embedding functions
            import asyncio
            import inspect

            if inspect.iscoroutinefunction(self.embedding_fn):
                return await self.embedding_fn(text)
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, self.embedding_fn, text)
        else:
            raise ValueError("embedding_fn must be callable")


class EmbeddingService:
    """
    Service for generating text embeddings.

    Provides a consistent interface for embedding generation
    that can be used with QueryExecutor.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
    ):
        """
        Initialize embedding service.

        Args:
            model: Embedding model name.
            dimensions: Embedding dimensions.
        """
        self.model = model
        self.dimensions = dimensions
        self._client = None

    async def initialize(self) -> None:
        """Initialize the embedding client."""
        try:
            from openai import AsyncOpenAI
            from app.core.config import settings

            api_key = settings.openai_api_key
            if api_key:
                self._client = AsyncOpenAI(api_key=api_key.get_secret_value())
                logger.info(f"Embedding service initialized with model: {self.model}")
        except ImportError:
            logger.warning("openai package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize embedding service: {e}")

    async def embed(self, text: str) -> list[float]:
        """
        Generate embedding for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        if not self._client:
            raise RuntimeError("Embedding service not initialized")

        response = await self._client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self.dimensions,
        )

        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        if not self._client:
            raise RuntimeError("Embedding service not initialized")

        response = await self._client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )

        return [item.embedding for item in response.data]
