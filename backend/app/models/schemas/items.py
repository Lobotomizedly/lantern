"""
Item-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.models.schemas.common import BaseSchema


# =============================================================================
# Item Schemas
# =============================================================================


class ItemBase(BaseSchema):
    """Base schema for Item (content item)."""

    source_id: UUID = Field(
        ...,
        description="ID of the source this item came from",
    )
    raw_ref: str = Field(
        ...,
        max_length=2048,
        description="Original URL or reference to the content",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Title of the content",
    )
    normalized_text: str = Field(
        ...,
        description="Cleaned and normalized text content",
    )
    raw_text: Optional[str] = Field(
        default=None,
        description="Original raw text before normalization",
    )
    sentiment: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Sentiment score (-1 to 1)",
    )
    salience: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Salience/importance score (0 to 1)",
    )
    published_at: Optional[datetime] = Field(
        default=None,
        description="When the content was originally published",
    )
    author: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Author of the content",
    )
    language: str = Field(
        default="en",
        max_length=10,
        description="Language code",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class ItemCreate(ItemBase):
    """Schema for creating an Item."""

    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding (1536 dimensions)",
    )
    entity_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of entities mentioned in this item",
    )


class ItemUpdate(BaseSchema):
    """Schema for updating an Item."""

    title: Optional[str] = Field(
        default=None,
        max_length=500,
    )
    normalized_text: Optional[str] = None
    sentiment: Optional[float] = Field(
        default=None,
        ge=-1.0,
        le=1.0,
    )
    salience: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    embedding: Optional[list[float]] = None
    metadata: Optional[dict[str, Any]] = None


class ItemRead(ItemBase):
    """Schema for reading an Item."""

    id: UUID = Field(..., description="Unique identifier")
    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding (excluded by default for performance)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
