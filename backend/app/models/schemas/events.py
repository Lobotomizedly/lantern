"""
Event-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas.common import BaseSchema


# =============================================================================
# Event Schemas
# =============================================================================


class EventBase(BaseSchema):
    """Base schema for Event (detected event/happening)."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Title of the event",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Description of the event",
    )
    occurred_at: datetime = Field(
        ...,
        description="When the event occurred",
    )
    location: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Location of the event",
    )
    location_geo: Optional[dict[str, float]] = Field(
        default=None,
        description="Geographic coordinates (lat, lon)",
    )
    evidence_item_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of items that provide evidence for this event",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for this event detection",
    )
    event_type: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Type/category of event",
    )
    entity_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of entities involved in this event",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EventCreate(EventBase):
    """Schema for creating an Event."""

    pass


class EventUpdate(BaseSchema):
    """Schema for updating an Event."""

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
    )
    description: Optional[str] = Field(
        default=None,
        max_length=5000,
    )
    occurred_at: Optional[datetime] = None
    location: Optional[str] = Field(
        default=None,
        max_length=500,
    )
    location_geo: Optional[dict[str, float]] = None
    evidence_item_ids: Optional[list[UUID]] = None
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    event_type: Optional[str] = Field(
        default=None,
        max_length=100,
    )
    entity_ids: Optional[list[UUID]] = None
    metadata: Optional[dict[str, Any]] = None


class EventRead(EventBase):
    """Schema for reading an Event."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Event Response Schemas
# =============================================================================


class EntitySummary(BaseModel):
    """Summary of an entity involved in an event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Entity ID")
    name: str = Field(..., description="Entity name")
    entity_type: str = Field(..., description="Type of entity")
    role: Optional[str] = Field(default=None, description="Role in the event")


class EventListResponse(BaseModel):
    """Paginated response for events list."""

    model_config = ConfigDict(from_attributes=True)

    items: list[EventRead] = Field(default_factory=list, description="List of events")
    total: int = Field(..., description="Total number of events")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(default=0, description="Total number of pages")
    has_next: bool = Field(default=False, description="Whether there is a next page")
    has_prev: bool = Field(default=False, description="Whether there is a previous page")


class EventDetailResponse(EventRead):
    """Detailed event response with related data."""

    involved_entities: list[EntitySummary] = Field(
        default_factory=list,
        description="Entities involved in this event",
    )
    evidence_item_count: int = Field(
        default=0,
        description="Number of evidence items",
    )
