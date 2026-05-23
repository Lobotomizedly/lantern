"""
Entity-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.models.schemas.common import BaseSchema, EntityType


# =============================================================================
# Entity Schemas
# =============================================================================


class EntityBase(BaseSchema):
    """Base schema for Entity."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Primary name of the entity",
    )
    entity_type: EntityType = Field(
        ...,
        description="Type of entity",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names for the entity",
    )
    external_ids: dict[str, str] = Field(
        default_factory=dict,
        description="External identifiers (e.g., wikidata_id, linkedin_url)",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Description of the entity",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EntityCreate(EntityBase):
    """Schema for creating an Entity."""

    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding (1536 dimensions)",
    )


class EntityUpdate(BaseSchema):
    """Schema for updating an Entity."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    entity_type: Optional[EntityType] = None
    aliases: Optional[list[str]] = None
    external_ids: Optional[dict[str, str]] = None
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
    )
    metadata: Optional[dict[str, Any]] = None
    embedding: Optional[list[float]] = None


class EntityRead(EntityBase):
    """Schema for reading an Entity."""

    id: UUID = Field(..., description="Unique identifier")
    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding (excluded by default for performance)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
