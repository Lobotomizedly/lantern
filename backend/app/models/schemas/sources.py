"""
Source-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.models.schemas.common import BaseSchema, SourceType, ReliabilityTier


# =============================================================================
# Source Schemas
# =============================================================================


class SourceBase(BaseSchema):
    """Base schema for Source."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the source",
    )
    source_type: SourceType = Field(
        ...,
        description="Type of source",
    )
    url: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="Base URL of the source",
    )
    reliability_tier: ReliabilityTier = Field(
        default=ReliabilityTier.TIER_3,
        description="Reliability tier (1-4, 1 being highest)",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Description of the source",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the source is active",
    )
    fetch_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration for fetching from this source",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class SourceCreate(SourceBase):
    """Schema for creating a Source."""

    pass


class SourceUpdate(BaseSchema):
    """Schema for updating a Source."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    source_type: Optional[SourceType] = None
    url: Optional[str] = Field(
        default=None,
        max_length=2048,
    )
    reliability_tier: Optional[ReliabilityTier] = None
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
    )
    is_active: Optional[bool] = None
    fetch_config: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class SourceRead(SourceBase):
    """Schema for reading a Source."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
