"""
Semantic search system for Lantern Narrative Intelligence Platform.

This module provides:
- Vector search using pgvector for semantic similarity
- Lexical search using OpenSearch for BM25 full-text search
- Hybrid search combining vector and lexical results with RRF
- Cross-encoder reranking for final precision
- Query parsing and filter extraction
- Index management for search indices
- High-level search client for UI and agents
"""

from app.search.vector import (
    VectorSearch,
    VectorSearchResult,
    SearchableType,
)
from app.search.lexical import (
    LexicalSearch,
    LexicalSearchResult,
    IndexName,
)
from app.search.hybrid import (
    HybridSearch,
    HybridSearchResult,
    RRFConfig,
)
from app.search.filters import (
    SearchFilters,
    SubjectFilter,
    SourceFilter,
    DateRangeFilter,
    ReliabilityTierFilter,
    SentimentFilter,
    NarrativeFilter,
    EntityFilter,
)
from app.search.rerank import (
    CrossEncoderReranker,
    RerankedResult,
)
from app.search.query import (
    QueryParser,
    ParsedQuery,
    QueryExecutor,
)
from app.search.index import (
    IndexManager,
    IndexMapping,
)
from app.search.client import (
    SearchClient,
    SearchRequest,
    SearchResponse,
    ResultType,
)

__all__ = [
    # Vector search
    "VectorSearch",
    "VectorSearchResult",
    "SearchableType",
    # Lexical search
    "LexicalSearch",
    "LexicalSearchResult",
    "IndexName",
    # Hybrid search
    "HybridSearch",
    "HybridSearchResult",
    "RRFConfig",
    # Filters
    "SearchFilters",
    "SubjectFilter",
    "SourceFilter",
    "DateRangeFilter",
    "ReliabilityTierFilter",
    "SentimentFilter",
    "NarrativeFilter",
    "EntityFilter",
    # Reranking
    "CrossEncoderReranker",
    "RerankedResult",
    # Query
    "QueryParser",
    "ParsedQuery",
    "QueryExecutor",
    # Index management
    "IndexManager",
    "IndexMapping",
    # Client
    "SearchClient",
    "SearchRequest",
    "SearchResponse",
    "ResultType",
]
