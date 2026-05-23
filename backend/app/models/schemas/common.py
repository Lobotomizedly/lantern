"""
Common schemas and enums shared across the API.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums
# =============================================================================


class SubjectType(str, Enum):
    """Type of subject being tracked."""

    PERSON = "person"
    ORG = "org"
    TOPIC = "topic"


class EntityType(str, Enum):
    """Type of entity extracted from content."""

    PERSON = "person"
    ORG = "org"
    PLACE = "place"
    PRODUCT = "product"


class SourceType(str, Enum):
    """Type of content source."""

    NEWS = "news"
    SOCIAL = "social"
    FILING = "filing"
    PODCAST = "podcast"
    VIDEO = "video"
    BLOG = "blog"
    PRESS_RELEASE = "press_release"


class ReliabilityTier(int, Enum):
    """Source reliability tier (1 = highest, 4 = lowest)."""

    TIER_1 = 1  # Primary sources, major publications
    TIER_2 = 2  # Secondary sources, regional publications
    TIER_3 = 3  # Blogs, opinion pieces
    TIER_4 = 4  # Social media, unverified sources


class ClaimStance(str, Enum):
    """Stance of a claim toward its subject."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ClaimPolarity(str, Enum):
    """Polarity/direction of the claim."""

    ASSERTION = "assertion"
    DENIAL = "denial"
    SPECULATION = "speculation"
    QUESTION = "question"


class NarrativeLifecycle(str, Enum):
    """Lifecycle stage of a narrative."""

    EMERGING = "emerging"
    GROWING = "growing"
    PEAKING = "peaking"
    DECLINING = "declining"
    DORMANT = "dormant"


class ArtifactType(str, Enum):
    """Type of generated artifact."""

    REPORT = "report"
    MEMO = "memo"
    TIMELINE = "timeline"
    NEWSLETTER = "newsletter"


class ArtifactStatus(str, Enum):
    """Status of artifact generation."""

    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    PENDING = "pending"
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"


class AgentRunStatus(str, Enum):
    """Status of an agent run."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentStepType(str, Enum):
    """Type of agent step."""

    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    REASONING = "reasoning"
    OUTPUT = "output"
    ITERATION = "iteration"


class ReviewStatus(str, Enum):
    """Status of a review item."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewType(str, Enum):
    """Type of item being reviewed."""

    ARTIFACT = "artifact"
    FLAG = "flag"


class SentinelFlagSeverity(str, Enum):
    """Severity level of a sentinel flag."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# Base Schemas
# =============================================================================


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
    )


class TimestampMixin(BaseModel):
    """Mixin for created_at and updated_at timestamps."""

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the record was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the record was last updated",
    )


# =============================================================================
# Pagination Schemas
# =============================================================================


class PaginationParams(BaseModel):
    """Common pagination parameters."""

    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: Optional[str] = Field(default=None, description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort order (asc/desc)")


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list[Any] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(default=0, description="Total number of pages")
    has_next: bool = Field(default=False, description="Whether there is a next page")
    has_prev: bool = Field(default=False, description="Whether there is a previous page")


# =============================================================================
# Watchlist Configuration
# =============================================================================


class WatchlistSource(BaseModel):
    """Configuration for a watchlist source."""

    source_type: SourceType = Field(
        ...,
        description="Type of source to monitor",
    )
    source_ids: list[UUID] = Field(
        default_factory=list,
        description="Specific source IDs to monitor",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this source is enabled",
    )


class WatchlistConfig(BaseModel):
    """Configuration for subject watchlist monitoring."""

    sources: list[WatchlistSource] = Field(
        default_factory=list,
        description="List of sources to monitor",
    )
    queries: list[str] = Field(
        default_factory=list,
        description="Search queries for finding relevant content",
    )
    cadence_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="How often to check for updates (in minutes)",
    )
    lookback_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="How far back to look for content (in days)",
    )
    alert_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score to trigger alerts",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Additional keywords to monitor",
    )
    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords to exclude from monitoring",
    )


# =============================================================================
# Alert Thresholds
# =============================================================================


class AlertThresholds(BaseModel):
    """Alert threshold configuration."""

    velocity_spike: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Threshold for velocity spike alerts",
    )
    sentiment_shift: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Threshold for sentiment shift alerts",
    )
    coordinated_activity: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Threshold for coordinated activity detection",
    )


# =============================================================================
# Citation
# =============================================================================


class Citation(BaseModel):
    """Citation reference in an artifact."""

    item_id: Optional[UUID] = Field(
        default=None,
        description="ID of the cited item",
    )
    claim_id: Optional[UUID] = Field(
        default=None,
        description="ID of the cited claim",
    )
    text: str = Field(
        ...,
        description="Citation text/reference",
    )
    url: Optional[str] = Field(
        default=None,
        description="URL of the cited source",
    )
