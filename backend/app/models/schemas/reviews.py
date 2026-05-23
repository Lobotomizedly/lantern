"""
Review-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas.common import BaseSchema, ReviewStatus, ReviewType


# =============================================================================
# Review Decision
# =============================================================================


class ReviewDecision(BaseModel):
    """Decision made on a review item."""

    model_config = ConfigDict(from_attributes=True)

    decision: str = Field(
        ...,
        description="Decision type (approved, rejected)",
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Feedback or notes on the decision",
    )
    reviewed_by_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None


# =============================================================================
# Review Item
# =============================================================================


class ReviewItem(BaseModel):
    """Base review item information."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    review_type: str
    title: str
    description: Optional[str] = None
    status: str
    priority: str = "medium"
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    artifact_id: Optional[UUID] = None
    flag_id: Optional[UUID] = None
    assigned_to_id: Optional[UUID] = None
    assigned_to_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    due_at: Optional[datetime] = None


# =============================================================================
# Review Context
# =============================================================================


class ReviewContext(BaseModel):
    """Context information for making a review decision."""

    model_config = ConfigDict(from_attributes=True)

    subject: Optional[dict[str, Any]] = None
    related_reviews: list[dict[str, Any]] = Field(default_factory=list)
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Review Requests
# =============================================================================


class ReviewApproveRequest(BaseModel):
    """Request schema for approving a review item."""

    model_config = ConfigDict(from_attributes=True)

    feedback: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional approval notes",
    )
    modifications: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional modifications to apply",
    )


class ReviewRejectRequest(BaseModel):
    """Request schema for rejecting a review item."""

    model_config = ConfigDict(from_attributes=True)

    feedback: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Required rejection reason/feedback",
    )
    request_revision: bool = Field(
        default=False,
        description="Whether to request regeneration with feedback",
    )


# =============================================================================
# Review Response
# =============================================================================


class ReviewResponse(ReviewItem):
    """Response schema for review listing."""

    pass


class ReviewListResponse(BaseModel):
    """Paginated list of reviews."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ReviewResponse]
    total: int
    page: int
    page_size: int
    pending_count: Optional[int] = None


class ReviewDetailResponse(ReviewResponse):
    """Detailed review response with content and context."""

    content: Optional[dict[str, Any]] = None
    context: Optional[dict[str, Any]] = None
    decision: Optional[str] = None
    feedback: Optional[str] = None
    reviewed_by_id: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
