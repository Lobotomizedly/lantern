"""
Search-related schemas for API request/response validation.
"""

from datetime import datetime, date
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas.common import BaseSchema


# =============================================================================
# Date Range
# =============================================================================


class DateRange(BaseModel):
    """Date range filter."""

    model_config = ConfigDict(from_attributes=True)

    start: Optional[date] = Field(
        default=None,
        description="Start date (inclusive)",
    )
    end: Optional[date] = Field(
        default=None,
        description="End date (inclusive)",
    )


# =============================================================================
# Search Filters
# =============================================================================


class SearchFilters(BaseModel):
    """Filters for search operations."""

    model_config = ConfigDict(from_attributes=True)

    subject_ids: Optional[list[UUID]] = Field(
        default=None,
        description="Filter by specific subjects",
    )
    source_types: Optional[list[str]] = Field(
        default=None,
        description="Filter by source types (news, social, etc.)",
    )
    date_range: Optional[DateRange] = Field(
        default=None,
        description="Filter by publication date range",
    )
    reliability_tiers: Optional[list[int]] = Field(
        default=None,
        description="Filter by source reliability tiers (1-4)",
    )
    sentiments: Optional[list[str]] = Field(
        default=None,
        description="Filter by sentiment (positive, negative, neutral)",
    )
    narrative_ids: Optional[list[UUID]] = Field(
        default=None,
        description="Filter by associated narratives",
    )
    entity_ids: Optional[list[UUID]] = Field(
        default=None,
        description="Filter by mentioned entities",
    )


# =============================================================================
# Search Request
# =============================================================================


class SearchRequest(BaseModel):
    """Request schema for search operations."""

    model_config = ConfigDict(from_attributes=True)

    query: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Search query text",
    )
    filters: Optional[SearchFilters] = Field(
        default=None,
        description="Search filters",
    )
    page: Optional[int] = Field(
        default=1,
        ge=1,
        description="Page number",
    )
    page_size: Optional[int] = Field(
        default=20,
        ge=1,
        le=100,
        description="Items per page",
    )
    sort_by: Optional[str] = Field(
        default=None,
        description="Field to sort by (date, relevance)",
    )
    sort_order: Optional[str] = Field(
        default="desc",
        description="Sort order (asc, desc)",
    )


# =============================================================================
# Search Result Item
# =============================================================================


class SearchResultItem(BaseModel):
    """Individual search result item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Document ID")
    title: Optional[str] = Field(default=None, description="Document title")
    summary: Optional[str] = Field(default=None, description="Document summary")
    content_preview: Optional[str] = Field(
        default=None, description="Content preview/snippet"
    )
    url: Optional[str] = Field(default=None, description="Original URL")
    source_name: Optional[str] = Field(default=None, description="Source name")
    source_type: Optional[str] = Field(default=None, description="Source type")
    reliability_tier: Optional[int] = Field(
        default=None, description="Source reliability tier"
    )
    published_at: Optional[datetime] = Field(
        default=None, description="Publication date"
    )
    sentiment: Optional[str] = Field(default=None, description="Sentiment label")
    sentiment_score: Optional[float] = Field(
        default=None, description="Sentiment score"
    )
    entities: list[dict[str, Any]] = Field(
        default_factory=list, description="Mentioned entities"
    )
    narratives: list[dict[str, Any]] = Field(
        default_factory=list, description="Associated narratives"
    )
    highlight: Optional[str] = Field(
        default=None, description="Highlighted text snippet"
    )
    relevance_score: float = Field(default=1.0, description="Search relevance score")


# =============================================================================
# Search Facets
# =============================================================================


class SearchFacets(BaseModel):
    """Facet counts for search filter UI."""

    model_config = ConfigDict(from_attributes=True)

    subjects: list[dict[str, Any]] = Field(
        default_factory=list, description="Subject facets"
    )
    source_types: list[dict[str, Any]] = Field(
        default_factory=list, description="Source type facets"
    )
    reliability_tiers: list[dict[str, Any]] = Field(
        default_factory=list, description="Reliability tier facets"
    )
    sentiments: list[dict[str, Any]] = Field(
        default_factory=list, description="Sentiment facets"
    )


# =============================================================================
# Search Response
# =============================================================================


class SearchResponse(BaseModel):
    """Response schema for search operations."""

    model_config = ConfigDict(from_attributes=True)

    items: list[SearchResultItem] = Field(
        default_factory=list, description="Search results"
    )
    total: int = Field(..., description="Total number of results")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    query: Optional[str] = Field(default=None, description="Original search query")
    filters: Optional[SearchFilters] = Field(
        default=None, description="Applied filters"
    )
    facets: Optional[SearchFacets] = Field(
        default=None, description="Facet counts for filtering"
    )


# =============================================================================
# Aliases for backward compatibility
# =============================================================================

SearchResult = SearchResultItem
