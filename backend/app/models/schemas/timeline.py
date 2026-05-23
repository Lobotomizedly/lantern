"""
Timeline-related schemas for API request/response validation.
"""

from datetime import datetime, date
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.schemas.common import BaseSchema


# =============================================================================
# Timeline Filters
# =============================================================================


class TimelineFilters(BaseModel):
    """Filters for timeline queries."""

    subject_id: Optional[UUID] = Field(
        default=None,
        description="Filter by subject ID",
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Start date (inclusive)",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="End date (inclusive)",
    )
    event_types: Optional[list[str]] = Field(
        default=None,
        description="Filter by event types",
    )
    importance: Optional[str] = Field(
        default=None,
        description="Minimum importance level",
    )
    narrative_id: Optional[UUID] = Field(
        default=None,
        description="Filter by narrative ID",
    )


# =============================================================================
# Timeline Request
# =============================================================================


class TimelineRequest(BaseModel):
    """Request schema for timeline operations."""

    subject_id: Optional[UUID] = Field(
        default=None,
        description="Subject to get timeline for",
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Start date (inclusive)",
    )
    end_date: Optional[date] = Field(
        default=None,
        description="End date (inclusive)",
    )
    event_types: Optional[list[str]] = Field(
        default=None,
        description="Event types to include",
    )
    importance: Optional[str] = Field(
        default=None,
        description="Minimum importance level (low, medium, high, critical)",
    )
    narrative_id: Optional[UUID] = Field(
        default=None,
        description="Filter by narrative",
    )
    aggregation: Optional[str] = Field(
        default=None,
        description="Aggregation period (hour, day, week, month)",
    )
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=50, ge=1, le=100, description="Items per page")


# =============================================================================
# Timeline Event
# =============================================================================


class TimelineEvent(BaseModel):
    """Individual timeline event."""

    id: UUID = Field(..., description="Event ID")
    event_type: str = Field(..., description="Type of event")
    title: str = Field(..., description="Event title")
    description: Optional[str] = Field(default=None, description="Event description")
    occurred_at: datetime = Field(..., description="When the event occurred")
    importance: str = Field(default="medium", description="Importance level")
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    document_id: Optional[UUID] = None
    document_title: Optional[str] = None
    narrative_id: Optional[UUID] = None
    narrative_name: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


# Alias for backward compatibility
TimelineEventResponse = TimelineEvent


# =============================================================================
# Timeline Aggregation
# =============================================================================


class TimelineAggregation(BaseModel):
    """Aggregated timeline statistics."""

    period: str = Field(..., description="Aggregation period")
    buckets: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Time-based buckets with counts",
    )
    event_type_totals: dict[str, int] = Field(
        default_factory=dict,
        description="Total counts by event type",
    )
    total_events: int = Field(default=0, description="Total number of events")


# =============================================================================
# Timeline Response
# =============================================================================


class TimelineResponse(BaseModel):
    """Response schema for timeline queries."""

    events: list[TimelineEvent] = Field(
        default_factory=list,
        description="Timeline events",
    )
    total: int = Field(..., description="Total number of events")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    filters: Optional[TimelineFilters] = Field(
        default=None,
        description="Applied filters",
    )
    aggregation: Optional[TimelineAggregation] = Field(
        default=None,
        description="Aggregation data if requested",
    )
