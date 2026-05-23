"""
Review Queue Endpoints
Handles human-in-the-loop review workflow for artifacts and flags.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination, AnalystUser
from app.models.orm import Review, Artifact, SentinelFlag, Subject
from app.models.schemas.reviews import (
    ReviewResponse,
    ReviewDetailResponse,
    ReviewListResponse,
    ReviewApproveRequest,
    ReviewRejectRequest,
    ReviewStatus,
    ReviewType,
    ReviewDecision,
)

router = APIRouter()


@router.get(
    "",
    response_model=ReviewListResponse,
    summary="List pending reviews",
    description="Retrieve a paginated list of items pending review.",
)
async def list_reviews(
    db: DatabaseSession,
    current_user: AnalystUser,
    pagination: Pagination,
    response: Response,
    review_type: Annotated[
        str | None, Query(description="Filter by type (artifact, flag)")
    ] = None,
    priority: Annotated[
        str | None, Query(description="Filter by priority (low, medium, high, urgent)")
    ] = None,
    subject_id: Annotated[UUID | None, Query(description="Filter by subject")] = None,
    assigned_to_me: Annotated[
        bool, Query(description="Only show reviews assigned to current user")
    ] = False,
    include_completed: Annotated[
        bool, Query(description="Include completed reviews")
    ] = False,
) -> ReviewListResponse:
    """
    List reviews pending human approval:
    - **review_type**: Filter by artifact or flag reviews
    - **priority**: Filter by priority level
    - **subject_id**: Filter by associated subject
    - **assigned_to_me**: Only show assigned reviews
    - **include_completed**: Include already reviewed items
    """
    # Build query
    query = select(Review).where(
        Review.organization_id == current_user.organization_id
    )

    # Filter by status
    if not include_completed:
        query = query.where(Review.status == "pending")

    # Apply filters
    if review_type:
        query = query.where(Review.review_type == review_type)

    if priority:
        query = query.where(Review.priority == priority)

    if subject_id:
        query = query.where(Review.subject_id == subject_id)

    if assigned_to_me:
        query = query.where(Review.assigned_to_id == current_user.id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination and ordering (prioritize urgent items)
    priority_order = func.case(
        (Review.priority == "urgent", 1),
        (Review.priority == "high", 2),
        (Review.priority == "medium", 3),
        (Review.priority == "low", 4),
        else_=5,
    )

    query = (
        query.options(
            selectinload(Review.subject),
            selectinload(Review.assigned_to),
        )
        .order_by(priority_order, Review.created_at.asc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    reviews = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return ReviewListResponse(
        items=[
            ReviewResponse(
                id=review.id,
                review_type=review.review_type,
                title=review.title,
                description=review.description,
                status=review.status,
                priority=review.priority,
                subject_id=review.subject_id,
                subject_name=review.subject.name if review.subject else None,
                artifact_id=review.artifact_id,
                flag_id=review.flag_id,
                assigned_to_id=review.assigned_to_id,
                assigned_to_name=(
                    review.assigned_to.name if review.assigned_to else None
                ),
                created_at=review.created_at,
                due_at=review.due_at,
            )
            for review in reviews
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        pending_count=total if not include_completed else None,
    )


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse,
    summary="Get review details",
    description="Retrieve detailed information about a specific review.",
)
async def get_review(
    review_id: UUID,
    db: DatabaseSession,
    current_user: AnalystUser,
) -> ReviewDetailResponse:
    """
    Get review details including:
    - **content**: The artifact or flag content to review
    - **context**: Related information for decision making
    - **history**: Previous review decisions if any
    """
    query = (
        select(Review)
        .options(
            selectinload(Review.subject),
            selectinload(Review.artifact),
            selectinload(Review.flag),
            selectinload(Review.assigned_to),
            selectinload(Review.reviewed_by),
        )
        .where(Review.id == review_id)
    )

    result = await db.execute(query)
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review with id '{review_id}' not found",
        )

    # Verify access
    if (
        review.organization_id != current_user.organization_id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this review",
        )

    # Build content based on review type
    content = _build_review_content(review)

    # Build context
    context = await _build_review_context(db, review)

    return ReviewDetailResponse(
        id=review.id,
        review_type=review.review_type,
        title=review.title,
        description=review.description,
        status=review.status,
        priority=review.priority,
        subject_id=review.subject_id,
        subject_name=review.subject.name if review.subject else None,
        artifact_id=review.artifact_id,
        flag_id=review.flag_id,
        assigned_to_id=review.assigned_to_id,
        assigned_to_name=review.assigned_to.name if review.assigned_to else None,
        created_at=review.created_at,
        due_at=review.due_at,
        content=content,
        context=context,
        decision=review.decision,
        feedback=review.feedback,
        reviewed_by_id=review.reviewed_by_id,
        reviewed_by_name=review.reviewed_by.name if review.reviewed_by else None,
        reviewed_at=review.reviewed_at,
    )


@router.post(
    "/{review_id}/approve",
    response_model=ReviewResponse,
    summary="Approve review item",
    description="Approve an artifact or flag with optional feedback.",
)
async def approve_review(
    review_id: UUID,
    request: ReviewApproveRequest,
    db: DatabaseSession,
    current_user: AnalystUser,
) -> ReviewResponse:
    """
    Approve a pending review:
    - **feedback**: Optional approval notes
    - **modifications**: Optional modifications to apply
    """
    review = await db.get(Review, review_id)

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review with id '{review_id}' not found",
        )

    # Verify access
    if (
        review.organization_id != current_user.organization_id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this review",
        )

    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review has already been {review.status}",
        )

    # Update review
    review.status = "approved"
    review.decision = "approved"
    review.feedback = request.feedback
    review.reviewed_by_id = current_user.id
    review.reviewed_at = datetime.utcnow()
    review.updated_at = datetime.utcnow()

    # Apply approval effects
    await _apply_approval(db, review, request.modifications)

    await db.flush()
    await db.refresh(review, ["subject"])

    return ReviewResponse(
        id=review.id,
        review_type=review.review_type,
        title=review.title,
        description=review.description,
        status=review.status,
        priority=review.priority,
        subject_id=review.subject_id,
        subject_name=review.subject.name if review.subject else None,
        artifact_id=review.artifact_id,
        flag_id=review.flag_id,
        assigned_to_id=review.assigned_to_id,
        created_at=review.created_at,
        due_at=review.due_at,
    )


@router.post(
    "/{review_id}/reject",
    response_model=ReviewResponse,
    summary="Reject review item",
    description="Reject an artifact or flag with required feedback.",
)
async def reject_review(
    review_id: UUID,
    request: ReviewRejectRequest,
    db: DatabaseSession,
    current_user: AnalystUser,
) -> ReviewResponse:
    """
    Reject a pending review:
    - **feedback**: Required rejection reason/feedback
    - **request_revision**: Request regeneration with feedback
    """
    review = await db.get(Review, review_id)

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review with id '{review_id}' not found",
        )

    # Verify access
    if (
        review.organization_id != current_user.organization_id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this review",
        )

    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review has already been {review.status}",
        )

    # Update review
    review.status = "rejected"
    review.decision = "rejected"
    review.feedback = request.feedback
    review.reviewed_by_id = current_user.id
    review.reviewed_at = datetime.utcnow()
    review.updated_at = datetime.utcnow()

    # Apply rejection effects
    await _apply_rejection(db, review, request.request_revision)

    await db.flush()
    await db.refresh(review, ["subject"])

    return ReviewResponse(
        id=review.id,
        review_type=review.review_type,
        title=review.title,
        description=review.description,
        status=review.status,
        priority=review.priority,
        subject_id=review.subject_id,
        subject_name=review.subject.name if review.subject else None,
        artifact_id=review.artifact_id,
        flag_id=review.flag_id,
        assigned_to_id=review.assigned_to_id,
        created_at=review.created_at,
        due_at=review.due_at,
    )


def _build_review_content(review: Review) -> dict:
    """Build content dict for review detail."""
    if review.review_type == "artifact" and review.artifact:
        return {
            "type": "artifact",
            "artifact_type": review.artifact.artifact_type,
            "title": review.artifact.title,
            "content": review.artifact.content,
            "parameters": review.artifact.parameters,
        }
    elif review.review_type == "flag" and review.flag:
        return {
            "type": "flag",
            "flag_type": review.flag.flag_type,
            "severity": review.flag.severity,
            "message": review.flag.message,
            "evidence": review.flag.evidence,
            "recommended_action": review.flag.recommended_action,
        }

    return {"type": "unknown", "message": "Content not available"}


async def _build_review_context(db: DatabaseSession, review: Review) -> dict:
    """Build context information for review decision making."""
    context = {
        "subject": None,
        "related_reviews": [],
        "recent_activity": [],
    }

    if review.subject:
        context["subject"] = {
            "id": str(review.subject.id),
            "name": review.subject.name,
            "description": review.subject.description,
        }

    # Get related reviews
    related_query = (
        select(Review)
        .where(
            Review.subject_id == review.subject_id,
            Review.id != review.id,
        )
        .order_by(Review.created_at.desc())
        .limit(5)
    )
    related_result = await db.execute(related_query)
    related = related_result.scalars().all()

    context["related_reviews"] = [
        {
            "id": str(r.id),
            "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in related
    ]

    return context


async def _apply_approval(
    db: DatabaseSession,
    review: Review,
    modifications: dict | None,
) -> None:
    """Apply effects of approval to the reviewed item."""
    if review.review_type == "artifact" and review.artifact_id:
        artifact = await db.get(Artifact, review.artifact_id)
        if artifact:
            artifact.status = "published"
            artifact.published_at = datetime.utcnow()
            if modifications:
                # Apply any modifications
                if modifications.get("title"):
                    artifact.title = modifications["title"]
            artifact.updated_at = datetime.utcnow()

    elif review.review_type == "flag" and review.flag_id:
        flag = await db.get(SentinelFlag, review.flag_id)
        if flag:
            flag.is_acknowledged = True
            flag.acknowledged_by_id = review.reviewed_by_id
            flag.acknowledged_at = datetime.utcnow()
            flag.updated_at = datetime.utcnow()


async def _apply_rejection(
    db: DatabaseSession,
    review: Review,
    request_revision: bool,
) -> None:
    """Apply effects of rejection to the reviewed item."""
    if review.review_type == "artifact" and review.artifact_id:
        artifact = await db.get(Artifact, review.artifact_id)
        if artifact:
            if request_revision:
                artifact.status = "revision_requested"
                artifact.revision_feedback = review.feedback
            else:
                artifact.status = "rejected"
            artifact.updated_at = datetime.utcnow()

    elif review.review_type == "flag" and review.flag_id:
        flag = await db.get(SentinelFlag, review.flag_id)
        if flag:
            flag.is_dismissed = True
            flag.dismissed_reason = review.feedback
            flag.updated_at = datetime.utcnow()
