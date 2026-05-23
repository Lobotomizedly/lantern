"""
Narrative-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas.common import BaseSchema, NarrativeLifecycle


# =============================================================================
# Amplifier Info
# =============================================================================


class AmplifierInfo(BaseModel):
    """Information about a narrative amplifier."""

    model_config = ConfigDict(from_attributes=True)

    entity_id: Optional[UUID] = Field(
        default=None,
        description="Entity ID of the amplifier",
    )
    name: str = Field(
        ...,
        description="Name of the amplifier",
    )
    influence_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Influence score of this amplifier",
    )
    platform: Optional[str] = Field(
        default=None,
        description="Platform where amplification occurs",
    )


class AmplifierResponse(BaseModel):
    """Response schema for amplifier details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    narrative_id: UUID
    platform: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    influence_score: float = 0.0
    post_count: int = 0
    total_reach: int = 0
    first_posted_at: Optional[datetime] = None
    last_posted_at: Optional[datetime] = None
    is_coordinated: bool = False


# Alias for backward compatibility
NarrativeAmplifier = AmplifierResponse


# =============================================================================
# Claim Response
# =============================================================================


class ClaimResponse(BaseModel):
    """Response schema for claims within a narrative."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    narrative_id: UUID
    claim_text: str
    claim_type: Optional[str] = None
    verification_status: Optional[str] = None
    frequency: int = 0
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    source_count: int = 0


# Alias for backward compatibility
NarrativeClaim = ClaimResponse


# =============================================================================
# Narrative Lifecycle
# =============================================================================


class NarrativeLifecycleResponse(BaseModel):
    """Response schema for narrative lifecycle events."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    narrative_id: UUID
    status: str
    velocity_score: float = 0.0
    document_count: int = 0
    recorded_at: datetime
    notes: Optional[str] = None


# Alias for backward compatibility
NarrativeLifecycleHistory = NarrativeLifecycleResponse


# =============================================================================
# Narrative Metrics
# =============================================================================


class NarrativeMetrics(BaseModel):
    """Metrics for a narrative."""

    model_config = ConfigDict(from_attributes=True)

    total_reach: int = 0
    unique_sources: int = 0
    platform_distribution: dict[str, int] = Field(default_factory=dict)
    sentiment_distribution: dict[str, float] = Field(default_factory=dict)
    coordinated_amplifier_count: int = 0
    verified_claim_count: int = 0
    disputed_claim_count: int = 0
    average_velocity_7d: float = 0.0
    peak_velocity: float = 0.0


# =============================================================================
# Narrative Schemas
# =============================================================================


class NarrativeBase(BaseSchema):
    """Base schema for Narrative."""

    thesis: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Core thesis/claim of the narrative",
    )
    summary: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Detailed summary of the narrative",
    )
    lifecycle: NarrativeLifecycle = Field(
        default=NarrativeLifecycle.EMERGING,
        description="Current lifecycle stage",
    )
    prevalence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="How prevalent/widespread the narrative is",
    )
    velocity: float = Field(
        default=0.0,
        description="Rate of change in prevalence",
    )
    amplifiers: list[AmplifierInfo] = Field(
        default_factory=list,
        description="Entities amplifying this narrative",
    )
    supporting_claim_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of claims that support this narrative",
    )
    opposing_claim_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of claims that oppose this narrative",
    )
    related_narrative_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of related narratives",
    )
    first_seen_at: Optional[datetime] = Field(
        default=None,
        description="When the narrative was first detected",
    )
    peak_at: Optional[datetime] = Field(
        default=None,
        description="When the narrative peaked",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags/categories for the narrative",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class NarrativeResponse(BaseModel):
    """Response schema for narrative listing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    lifecycle_status: str = "emerging"
    velocity_score: float = 0.0
    document_count: int = 0
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    peak_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NarrativeListResponse(BaseModel):
    """Paginated list of narratives."""

    model_config = ConfigDict(from_attributes=True)

    items: list[NarrativeResponse]
    total: int
    page: int
    page_size: int


class NarrativeDetailResponse(NarrativeResponse):
    """Detailed narrative response with related data."""

    lifecycle: list[NarrativeLifecycleResponse] = Field(default_factory=list)
    amplifiers: list[AmplifierResponse] = Field(default_factory=list)
    claims: list[ClaimResponse] = Field(default_factory=list)
    metrics: Optional[NarrativeMetrics] = None


# Alias for backward compatibility
NarrativeDetail = NarrativeDetailResponse


# =============================================================================
# Legacy Schemas (for backward compatibility)
# =============================================================================


class NarrativeCreate(NarrativeBase):
    """Schema for creating a Narrative."""

    pass


class NarrativeUpdate(BaseSchema):
    """Schema for updating a Narrative."""

    thesis: Optional[str] = Field(
        default=None,
        min_length=10,
        max_length=2000,
    )
    summary: Optional[str] = Field(
        default=None,
        max_length=5000,
    )
    lifecycle: Optional[NarrativeLifecycle] = None
    prevalence_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    velocity: Optional[float] = None
    amplifiers: Optional[list[AmplifierInfo]] = None
    supporting_claim_ids: Optional[list[UUID]] = None
    opposing_claim_ids: Optional[list[UUID]] = None
    related_narrative_ids: Optional[list[UUID]] = None
    peak_at: Optional[datetime] = None
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


class NarrativeRead(NarrativeBase):
    """Schema for reading a Narrative."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
