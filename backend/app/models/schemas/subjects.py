"""
Subject-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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

    model_config = ConfigDict(from_attributes=True)

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

    model_config = ConfigDict(from_attributes=True)

    keywords: Optional[list[str]] = None
    entities: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    alert_thresholds: Optional[AlertThresholds] = None
    collection_schedule: Optional[str] = None
    is_active: Optional[bool] = None


class SubjectConfig(BaseModel):
    """Full subject configuration response."""

    model_config = ConfigDict(from_attributes=True)

    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    alert_thresholds: Optional[AlertThresholds] = None
    collection_schedule: Optional[str] = None
    is_active: bool = True
    last_collection_at: Optional[datetime] = None


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
    type: str = Field(default="topic", description="Type of subject")
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list, description="Alternative names")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    is_archived: bool = False
    config: Optional[SubjectConfig] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Custom validation to map subject_type to type."""
        if hasattr(obj, "subject_type"):
            # Create a dict from the object and map subject_type -> type
            # ORM uses metadata_ to avoid conflict with SQLAlchemy's metadata
            data = {
                "id": obj.id,
                "name": obj.name,
                "type": obj.subject_type if obj.subject_type else "topic",
                "description": obj.description,
                "aliases": getattr(obj, "aliases", None) or [],
                "metadata": getattr(obj, "metadata_", None) or {},
                "owner_id": obj.owner_id,
                "organization_id": obj.organization_id,
                "is_archived": obj.is_archived,
                "config": obj.config,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


class SubjectListResponse(BaseModel):
    """Paginated list of subjects."""

    model_config = ConfigDict(from_attributes=True)

    items: list[SubjectResponse]
    total: int
    page: int
    page_size: int
    has_more: bool = False


class SubjectMetrics(BaseModel):
    """Metrics for a subject."""

    model_config = ConfigDict(from_attributes=True)

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

    model_config = ConfigDict(from_attributes=True)

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
