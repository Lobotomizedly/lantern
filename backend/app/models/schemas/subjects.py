"""
Subject-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.schemas.common import (
    BaseSchema,
    SubjectType,
    WatchlistConfig,
    AlertThresholds,
    SentinelFlagSeverity,
)


# =============================================================================
# Subject Configuration
# =============================================================================


class SubjectConfigCreate(BaseModel):
    """Configuration for creating a subject."""

    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords to track for this subject",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Entities to monitor",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Source configurations",
    )
    alert_thresholds: Optional[AlertThresholds] = Field(
        default=None,
        description="Alert threshold configuration",
    )
    collection_schedule: Optional[str] = Field(
        default=None,
        description="Cron-style collection schedule",
    )


class SubjectConfigUpdate(BaseModel):
    """Configuration for updating a subject."""

    keywords: Optional[list[str]] = None
    entities: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    alert_thresholds: Optional[AlertThresholds] = None
    collection_schedule: Optional[str] = None
    is_active: Optional[bool] = None


class SubjectConfig(BaseModel):
    """Full subject configuration response."""

    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    alert_thresholds: Optional[AlertThresholds] = None
    collection_schedule: Optional[str] = None
    is_active: bool = True
    last_collection_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# =============================================================================
# Subject Schemas
# =============================================================================


class SubjectBase(BaseSchema):
    """Base schema for Subject."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the subject",
    )
    subject_type: SubjectType = Field(
        default=SubjectType.TOPIC,
        description="Type of subject (person, org, topic)",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Description of the subject",
    )


class SubjectCreate(SubjectBase):
    """Schema for creating a Subject."""

    config: SubjectConfigCreate = Field(
        default_factory=SubjectConfigCreate,
        description="Subject monitoring configuration",
    )


class SubjectUpdate(BaseSchema):
    """Schema for updating a Subject."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    subject_type: Optional[SubjectType] = None
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
    )
    config: Optional[SubjectConfigUpdate] = None


class SubjectResponse(BaseSchema):
    """Schema for subject response."""

    id: UUID = Field(..., description="Unique identifier")
    name: str = Field(..., description="Name of the subject")
    description: Optional[str] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    is_archived: bool = False
    config: Optional[SubjectConfig] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SubjectListResponse(BaseModel):
    """Paginated list of subjects."""

    items: list[SubjectResponse]
    total: int
    page: int
    page_size: int


class SubjectMetrics(BaseModel):
    """Metrics for a subject."""

    total_documents: int = 0
    total_narratives: int = 0
    active_flags: int = 0
    last_collection: Optional[datetime] = None


# =============================================================================
# Sentinel Flag Schemas
# =============================================================================


class SentinelFlagResponse(BaseSchema):
    """Schema for sentinel flag response."""

    id: UUID = Field(..., description="Unique identifier")
    subject_id: UUID = Field(..., description="Associated subject ID")
    flag_type: str = Field(..., description="Type of flag")
    severity: str = Field(..., description="Severity level")
    message: str = Field(..., description="Flag message")
    evidence: Optional[dict[str, Any]] = None
    recommended_action: Optional[str] = None
    is_resolved: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SubjectDetailResponse(SubjectResponse):
    """Detailed subject response with metrics and flags."""

    metrics: SubjectMetrics = Field(default_factory=SubjectMetrics)
    recent_flags: list[SentinelFlagResponse] = Field(default_factory=list)


# =============================================================================
# Subject Digest Schemas
# =============================================================================


class SubjectDigestResponse(BaseModel):
    """Sentinel digest for a subject."""

    subject_id: UUID
    subject_name: str
    generated_at: datetime
    flags: list[SentinelFlagResponse]
    severity_distribution: dict[str, int]
    total_active_flags: int
    summary: str


# =============================================================================
# Legacy Schemas (for backward compatibility with existing code)
# =============================================================================


class SubjectRead(SubjectBase):
    """Schema for reading a Subject (legacy)."""

    id: UUID = Field(..., description="Unique identifier")
    watchlist_config: WatchlistConfig = Field(
        default_factory=WatchlistConfig,
        description="Watchlist monitoring configuration",
    )
    is_active: bool = Field(
        default=True,
        description="Whether the subject is actively monitored",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
