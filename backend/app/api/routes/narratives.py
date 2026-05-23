"""
Narrative Endpoints
Handles narrative tracking, lifecycle, and analysis operations.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination, VerifiedSubjectAccess
from app.models.orm import Narrative, NarrativeLifecycle, NarrativeAmplifier, Claim, Subject
from app.models.schemas.narratives import (
    NarrativeResponse,
    NarrativeListResponse,
    NarrativeDetailResponse,
    NarrativeLifecycleResponse,
    AmplifierResponse,
    ClaimResponse,
    NarrativeMetrics,
)

router = APIRouter()


@router.get(
    "",
    response_model=NarrativeListResponse,
    summary="List narratives",
    description="Retrieve a paginated list of narratives with optional filtering.",
)
async def list_narratives(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    subject_id: Annotated[UUID | None, Query(description="Filter by subject")] = None,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Filter by lifecycle status (emerging, growing, peak, declining, dormant)",
        ),
    ] = None,
    min_velocity: Annotated[
        float | None, Query(ge=0, description="Minimum velocity score")
    ] = None,
    min_documents: Annotated[
        int | None, Query(ge=0, description="Minimum document count")
    ] = None,
    search: Annotated[str | None, Query(description="Search in narrative name/description")] = None,
) -> NarrativeListResponse:
    """
    List narratives with filtering options:
    - **subject_id**: Filter by specific subject
    - **status**: Filter by lifecycle status
    - **min_velocity**: Filter by minimum velocity score
    - **min_documents**: Filter by minimum document count
    - **search**: Search in narrative name and description
    """
    # Build base query
    query = select(Narrative).where(Narrative.is_active == True)

    # Filter by subject or organization access
    if subject_id:
        query = query.where(Narrative.subject_id == subject_id)
    else:
        # Filter to user's organization subjects
        subquery = select(Subject.id).where(
            Subject.organization_id == current_user.organization_id
        )
        query = query.where(Narrative.subject_id.in_(subquery))

    # Apply status filter
    if status_filter:
        query = query.where(Narrative.lifecycle_status == status_filter)

    # Apply velocity filter
    if min_velocity is not None:
        query = query.where(Narrative.velocity_score >= min_velocity)

    # Apply document count filter
    if min_documents is not None:
        query = query.where(Narrative.document_count >= min_documents)

    # Apply search filter
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Narrative.name.ilike(search_filter))
            | (Narrative.description.ilike(search_filter))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination and ordering
    query = (
        query.options(selectinload(Narrative.subject))
        .order_by(Narrative.velocity_score.desc(), Narrative.updated_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    narratives = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return NarrativeListResponse(
        items=[
            NarrativeResponse(
                id=n.id,
                name=n.name,
                description=n.description,
                subject_id=n.subject_id,
                subject_name=n.subject.name if n.subject else None,
                lifecycle_status=n.lifecycle_status,
                velocity_score=n.velocity_score,
                document_count=n.document_count,
                first_seen_at=n.first_seen_at,
                last_seen_at=n.last_seen_at,
                peak_at=n.peak_at,
                created_at=n.created_at,
                updated_at=n.updated_at,
            )
            for n in narratives
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{narrative_id}",
    response_model=NarrativeDetailResponse,
    summary="Get narrative detail",
    description="Retrieve detailed information about a specific narrative.",
)
async def get_narrative(
    narrative_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    include_lifecycle: Annotated[
        bool, Query(description="Include lifecycle history")
    ] = True,
    include_amplifiers: Annotated[
        bool, Query(description="Include top amplifiers")
    ] = True,
    include_claims: Annotated[
        bool, Query(description="Include associated claims")
    ] = True,
    amplifier_limit: Annotated[
        int, Query(ge=1, le=50, description="Max amplifiers to return")
    ] = 10,
    claim_limit: Annotated[
        int, Query(ge=1, le=50, description="Max claims to return")
    ] = 10,
) -> NarrativeDetailResponse:
    """
    Get detailed narrative information including:
    - **Lifecycle history**: Track how the narrative evolved over time
    - **Top amplifiers**: Accounts/sources driving the narrative
    - **Associated claims**: Specific claims within the narrative
    - **Metrics**: Velocity, reach, sentiment distribution
    """
    # Fetch narrative with relationships
    query = (
        select(Narrative)
        .options(
            selectinload(Narrative.subject),
            selectinload(Narrative.lifecycle_events),
            selectinload(Narrative.amplifiers),
            selectinload(Narrative.claims),
        )
        .where(Narrative.id == narrative_id)
    )

    result = await db.execute(query)
    narrative = result.scalar_one_or_none()

    if not narrative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Narrative with id '{narrative_id}' not found",
        )

    # Verify access via subject organization
    if narrative.subject and narrative.subject.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this narrative",
        )

    # Build lifecycle response
    lifecycle: list[NarrativeLifecycleResponse] = []
    if include_lifecycle and narrative.lifecycle_events:
        lifecycle = [
            NarrativeLifecycleResponse(
                id=event.id,
                narrative_id=event.narrative_id,
                status=event.status,
                velocity_score=event.velocity_score,
                document_count=event.document_count,
                recorded_at=event.recorded_at,
                notes=event.notes,
            )
            for event in sorted(
                narrative.lifecycle_events, key=lambda x: x.recorded_at
            )
        ]

    # Build amplifiers response
    amplifiers: list[AmplifierResponse] = []
    if include_amplifiers and narrative.amplifiers:
        sorted_amplifiers = sorted(
            narrative.amplifiers, key=lambda x: x.influence_score, reverse=True
        )[:amplifier_limit]
        amplifiers = [
            AmplifierResponse(
                id=amp.id,
                narrative_id=amp.narrative_id,
                platform=amp.platform,
                account_id=amp.account_id,
                account_name=amp.account_name,
                account_type=amp.account_type,
                influence_score=amp.influence_score,
                post_count=amp.post_count,
                total_reach=amp.total_reach,
                first_posted_at=amp.first_posted_at,
                last_posted_at=amp.last_posted_at,
                is_coordinated=amp.is_coordinated,
            )
            for amp in sorted_amplifiers
        ]

    # Build claims response
    claims: list[ClaimResponse] = []
    if include_claims and narrative.claims:
        sorted_claims = sorted(
            narrative.claims, key=lambda x: x.frequency, reverse=True
        )[:claim_limit]
        claims = [
            ClaimResponse(
                id=claim.id,
                narrative_id=claim.narrative_id,
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                verification_status=claim.verification_status,
                frequency=claim.frequency,
                first_seen_at=claim.first_seen_at,
                last_seen_at=claim.last_seen_at,
                source_count=claim.source_count,
            )
            for claim in sorted_claims
        ]

    # Calculate metrics
    metrics = _calculate_narrative_metrics(narrative)

    return NarrativeDetailResponse(
        id=narrative.id,
        name=narrative.name,
        description=narrative.description,
        subject_id=narrative.subject_id,
        subject_name=narrative.subject.name if narrative.subject else None,
        lifecycle_status=narrative.lifecycle_status,
        velocity_score=narrative.velocity_score,
        document_count=narrative.document_count,
        first_seen_at=narrative.first_seen_at,
        last_seen_at=narrative.last_seen_at,
        peak_at=narrative.peak_at,
        created_at=narrative.created_at,
        updated_at=narrative.updated_at,
        lifecycle=lifecycle,
        amplifiers=amplifiers,
        claims=claims,
        metrics=metrics,
    )


def _calculate_narrative_metrics(narrative: Narrative) -> NarrativeMetrics:
    """Calculate aggregate metrics for a narrative."""
    # In production, these would be computed from actual data
    # Here we provide placeholder calculations

    sentiment_distribution = {
        "positive": 0.0,
        "negative": 0.0,
        "neutral": 0.0,
    }

    # Calculate from amplifiers if available
    total_reach = sum(
        amp.total_reach for amp in narrative.amplifiers if amp.total_reach
    )
    coordinated_count = sum(
        1 for amp in narrative.amplifiers if amp.is_coordinated
    )

    # Calculate claim verification stats
    verified_claims = sum(
        1 for claim in narrative.claims if claim.verification_status == "verified"
    )
    disputed_claims = sum(
        1 for claim in narrative.claims if claim.verification_status == "disputed"
    )

    return NarrativeMetrics(
        total_reach=total_reach,
        unique_sources=len(set(amp.account_id for amp in narrative.amplifiers)),
        platform_distribution=_get_platform_distribution(narrative.amplifiers),
        sentiment_distribution=sentiment_distribution,
        coordinated_amplifier_count=coordinated_count,
        verified_claim_count=verified_claims,
        disputed_claim_count=disputed_claims,
        average_velocity_7d=narrative.velocity_score,  # Simplified
        peak_velocity=narrative.velocity_score * 1.5 if narrative.velocity_score else 0,
    )


def _get_platform_distribution(amplifiers: list) -> dict[str, int]:
    """Calculate distribution of amplifiers across platforms."""
    distribution: dict[str, int] = {}
    for amp in amplifiers:
        platform = amp.platform or "unknown"
        distribution[platform] = distribution.get(platform, 0) + 1
    return distribution
