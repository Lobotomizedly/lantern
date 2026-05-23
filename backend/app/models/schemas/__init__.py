"""
Pydantic schemas for API request/response validation.

This package contains all Pydantic schemas used for data validation,
serialization, and API documentation in the Lantern platform.

All schemas are re-exported here for backward compatibility.
"""

# Common schemas and enums
from app.models.schemas.common import (
    # Enums
    SubjectType,
    EntityType,
    SourceType,
    ReliabilityTier,
    ClaimStance,
    ClaimPolarity,
    NarrativeLifecycle,
    ArtifactType,
    ArtifactStatus,
    AgentRunStatus,
    AgentStepType,
    ReviewStatus,
    ReviewType,
    SentinelFlagSeverity,
    # Base schemas
    BaseSchema,
    TimestampMixin,
    # Pagination
    PaginationParams,
    PaginatedResponse,
    # Watchlist
    WatchlistSource,
    WatchlistConfig,
    AlertThresholds,
    # Citation
    Citation,
)

# Subject schemas
from app.models.schemas.subjects import (
    SubjectBase,
    SubjectCreate,
    SubjectUpdate,
    SubjectRead,
    SubjectResponse,
    SubjectListResponse,
    SubjectDetailResponse,
    SubjectDigestResponse,
    SubjectConfig,
    SubjectConfigCreate,
    SubjectConfigUpdate,
    SubjectMetrics,
    SentinelFlagResponse,
)

# Entity schemas
from app.models.schemas.entities import (
    EntityBase,
    EntityCreate,
    EntityUpdate,
    EntityRead,
)

# Source schemas
from app.models.schemas.sources import (
    SourceBase,
    SourceCreate,
    SourceUpdate,
    SourceRead,
)

# Item schemas
from app.models.schemas.items import (
    ItemBase,
    ItemCreate,
    ItemUpdate,
    ItemRead,
)

# Claim schemas
from app.models.schemas.claims import (
    ClaimBase,
    ClaimCreate,
    ClaimUpdate,
    ClaimRead,
)

# Event schemas
from app.models.schemas.events import (
    EventBase,
    EventCreate,
    EventUpdate,
    EventRead,
    EntitySummary,
    EventListResponse,
    EventDetailResponse,
)

# Narrative schemas
from app.models.schemas.narratives import (
    AmplifierInfo,
    AmplifierResponse,
    NarrativeAmplifier,
    ClaimResponse,
    NarrativeClaim,
    NarrativeLifecycleResponse,
    NarrativeLifecycleHistory,
    NarrativeMetrics,
    NarrativeBase,
    NarrativeCreate,
    NarrativeUpdate,
    NarrativeRead,
    NarrativeResponse,
    NarrativeListResponse,
    NarrativeDetailResponse,
    NarrativeDetail,
)

# Search schemas
from app.models.schemas.search import (
    DateRange,
    SearchFilters,
    SearchRequest,
    SearchResultItem,
    SearchResult,
    SearchFacets,
    SearchResponse,
)

# Timeline schemas
from app.models.schemas.timeline import (
    TimelineFilters,
    TimelineRequest,
    TimelineEvent,
    TimelineEventResponse,
    TimelineAggregation,
    TimelineResponse,
)

# Agent schemas
from app.models.schemas.agents import (
    InvestigateRequest,
    AgentCostSummary,
    AgentTrace,
    AgentTraceResponse,
    AgentRunResponse,
    AgentRunListResponse,
    AgentRunDetailResponse,
    AgentRunDetail,
    AgentRunBase,
    AgentRunCreate,
    AgentRunUpdate,
    AgentRunRead,
    AgentStepBase,
    AgentStepCreate,
    AgentStepRead,
)

# Artifact schemas
from app.models.schemas.artifacts import (
    ArtifactContent,
    ArtifactRequest,
    ArtifactCreateRequest,
    ArtifactCreate,
    ArtifactResponse,
    ArtifactListResponse,
    ArtifactDetailResponse,
    ArtifactBase,
    ArtifactUpdate,
    ArtifactRead,
)

# Review schemas
from app.models.schemas.reviews import (
    ReviewDecision,
    ReviewItem,
    ReviewContext,
    ReviewApproveRequest,
    ReviewRejectRequest,
    ReviewResponse,
    ReviewListResponse,
    ReviewDetailResponse,
)


__all__ = [
    # Enums
    "SubjectType",
    "EntityType",
    "SourceType",
    "ReliabilityTier",
    "ClaimStance",
    "ClaimPolarity",
    "NarrativeLifecycle",
    "ArtifactType",
    "ArtifactStatus",
    "AgentRunStatus",
    "AgentStepType",
    "ReviewStatus",
    "ReviewType",
    "SentinelFlagSeverity",
    # Base
    "BaseSchema",
    "TimestampMixin",
    "PaginationParams",
    "PaginatedResponse",
    "WatchlistSource",
    "WatchlistConfig",
    "AlertThresholds",
    "Citation",
    # Subject
    "SubjectBase",
    "SubjectCreate",
    "SubjectUpdate",
    "SubjectRead",
    "SubjectResponse",
    "SubjectListResponse",
    "SubjectDetailResponse",
    "SubjectDigestResponse",
    "SubjectConfig",
    "SubjectConfigCreate",
    "SubjectConfigUpdate",
    "SubjectMetrics",
    "SentinelFlagResponse",
    # Entity
    "EntityBase",
    "EntityCreate",
    "EntityUpdate",
    "EntityRead",
    # Source
    "SourceBase",
    "SourceCreate",
    "SourceUpdate",
    "SourceRead",
    # Item
    "ItemBase",
    "ItemCreate",
    "ItemUpdate",
    "ItemRead",
    # Claim
    "ClaimBase",
    "ClaimCreate",
    "ClaimUpdate",
    "ClaimRead",
    # Event
    "EventBase",
    "EventCreate",
    "EventUpdate",
    "EventRead",
    "EntitySummary",
    "EventListResponse",
    "EventDetailResponse",
    # Narrative
    "AmplifierInfo",
    "AmplifierResponse",
    "NarrativeAmplifier",
    "ClaimResponse",
    "NarrativeClaim",
    "NarrativeLifecycleResponse",
    "NarrativeLifecycleHistory",
    "NarrativeMetrics",
    "NarrativeBase",
    "NarrativeCreate",
    "NarrativeUpdate",
    "NarrativeRead",
    "NarrativeResponse",
    "NarrativeListResponse",
    "NarrativeDetailResponse",
    "NarrativeDetail",
    # Search
    "DateRange",
    "SearchFilters",
    "SearchRequest",
    "SearchResultItem",
    "SearchResult",
    "SearchFacets",
    "SearchResponse",
    # Timeline
    "TimelineFilters",
    "TimelineRequest",
    "TimelineEvent",
    "TimelineEventResponse",
    "TimelineAggregation",
    "TimelineResponse",
    # Agent
    "InvestigateRequest",
    "AgentCostSummary",
    "AgentTrace",
    "AgentTraceResponse",
    "AgentRunResponse",
    "AgentRunListResponse",
    "AgentRunDetailResponse",
    "AgentRunDetail",
    "AgentRunBase",
    "AgentRunCreate",
    "AgentRunUpdate",
    "AgentRunRead",
    "AgentStepBase",
    "AgentStepCreate",
    "AgentStepRead",
    # Artifact
    "ArtifactContent",
    "ArtifactRequest",
    "ArtifactCreateRequest",
    "ArtifactCreate",
    "ArtifactResponse",
    "ArtifactListResponse",
    "ArtifactDetailResponse",
    "ArtifactBase",
    "ArtifactUpdate",
    "ArtifactRead",
    # Review
    "ReviewDecision",
    "ReviewItem",
    "ReviewContext",
    "ReviewApproveRequest",
    "ReviewRejectRequest",
    "ReviewResponse",
    "ReviewListResponse",
    "ReviewDetailResponse",
]
