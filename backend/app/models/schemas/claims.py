"""
Claim-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from app.models.schemas.common import BaseSchema, ClaimStance, ClaimPolarity


# =============================================================================
# Claim Schemas
# =============================================================================


class ClaimBase(BaseSchema):
    """Base schema for Claim (extracted claim/statement)."""

    item_id: UUID = Field(
        ...,
        description="ID of the item this claim was extracted from",
    )
    subject_who: str = Field(
        ...,
        max_length=500,
        description="Who the claim is about (subject)",
    )
    predicate: str = Field(
        ...,
        max_length=500,
        description="The action or relationship",
    )
    object_what: str = Field(
        ...,
        max_length=1000,
        description="What the claim states (object)",
    )
    stance: ClaimStance = Field(
        default=ClaimStance.NEUTRAL,
        description="Stance of the claim",
    )
    polarity: ClaimPolarity = Field(
        default=ClaimPolarity.ASSERTION,
        description="Polarity of the claim",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for this claim extraction",
    )
    evidence_text: Optional[str] = Field(
        default=None,
        description="The exact text that supports this claim",
    )
    subject_entity_id: Optional[UUID] = Field(
        default=None,
        description="Linked entity ID for the subject",
    )
    object_entity_id: Optional[UUID] = Field(
        default=None,
        description="Linked entity ID for the object",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class ClaimCreate(ClaimBase):
    """Schema for creating a Claim."""

    pass


class ClaimUpdate(BaseSchema):
    """Schema for updating a Claim."""

    subject_who: Optional[str] = Field(
        default=None,
        max_length=500,
    )
    predicate: Optional[str] = Field(
        default=None,
        max_length=500,
    )
    object_what: Optional[str] = Field(
        default=None,
        max_length=1000,
    )
    stance: Optional[ClaimStance] = None
    polarity: Optional[ClaimPolarity] = None
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    subject_entity_id: Optional[UUID] = None
    object_entity_id: Optional[UUID] = None
    metadata: Optional[dict[str, Any]] = None


class ClaimRead(ClaimBase):
    """Schema for reading a Claim."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
