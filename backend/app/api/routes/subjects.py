"""
Subject Management Endpoints
Handles CRUD operations for monitored subjects and their configurations.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import (
    DatabaseSession,
    CurrentUser,
    Pagination,
    VerifiedSubjectAccess,
    OwnerSubjectAccess,
)
from app.models.orm import Subject, SubjectConfig, SentinelFlag
from app.models.schemas.subjects import (
    SubjectCreate,
    SubjectUpdate,
    SubjectResponse,
    SubjectListResponse,
    SubjectDetailResponse,
    SubjectDigestResponse,
    SentinelFlagResponse,
)

router = APIRouter()


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new subject",
    description="Create and configure a new subject for narrative monitoring.",
)
async def create_subject(
    subject_data: SubjectCreate,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> SubjectResponse:
    """
    Create a new subject with the following configuration options:
    - **name**: Display name for the subject
    - **description**: Optional description of the subject
    - **keywords**: List of keywords to track
    - **entities**: List of entities (people, organizations, etc.) to monitor
    - **sources**: List of source configurations to pull from
    - **alert_thresholds**: Sentinel alert configuration
    """
    # Check for duplicate subject name within organization
    existing = await db.execute(
        select(Subject).where(
            Subject.name == subject_data.name,
            Subject.organization_id == current_user.organization_id,
            Subject.is_archived == False,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subject with name '{subject_data.name}' already exists",
        )

    # Create subject
    subject = Subject(
        name=subject_data.name,
        subject_type=subject_data.subject_type.value if subject_data.subject_type else "topic",
        description=subject_data.description or "",
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(subject)
    await db.flush()

    # Create subject configuration
    config = SubjectConfig(
        subject_id=subject.id,
        keywords=subject_data.config.keywords,
        entities=subject_data.config.entities,
        sources=subject_data.config.sources,
        alert_thresholds=subject_data.config.alert_thresholds.model_dump()
        if subject_data.config.alert_thresholds
        else None,
        collection_schedule=subject_data.config.collection_schedule,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(config)

    await db.flush()
    await db.refresh(subject, ["config"])

    return SubjectResponse.model_validate(subject)


@router.get(
    "",
    response_model=SubjectListResponse,
    summary="List all subjects",
    description="Retrieve a paginated list of subjects accessible to the current user.",
)
async def list_subjects(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
    search: Annotated[str | None, Query(description="Search by name or description")] = None,
) -> SubjectListResponse:
    """
    List all subjects with optional filtering:
    - **is_active**: Filter by active/inactive status
    - **search**: Search in subject name and description
    """
    # Build base query
    query = select(Subject).where(
        Subject.organization_id == current_user.organization_id,
        Subject.is_archived == False,
    )

    # Apply filters
    if is_active is not None:
        query = query.join(SubjectConfig).where(SubjectConfig.is_active == is_active)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Subject.name.ilike(search_filter))
            | (Subject.description.ilike(search_filter))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination and ordering
    query = (
        query.options(selectinload(Subject.config))
        .order_by(Subject.created_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    subjects = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return SubjectListResponse(
        items=[SubjectResponse.model_validate(s) for s in subjects],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{subject_id}",
    response_model=SubjectDetailResponse,
    summary="Get subject details",
    description="Retrieve detailed information about a specific subject.",
)
async def get_subject(
    subject_id: VerifiedSubjectAccess,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> SubjectDetailResponse:
    """
    Get detailed subject information including:
    - Configuration settings
    - Recent activity metrics
    - Narrative summary
    - Latest flags
    """
    query = (
        select(Subject)
        .options(
            selectinload(Subject.config),
            selectinload(Subject.sentinel_flags),
        )
        .where(Subject.id == subject_id)
    )

    result = await db.execute(query)
    subject = result.scalar_one_or_none()

    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with id '{subject_id}' not found",
        )

    # Calculate metrics (these would typically come from a metrics service)
    metrics = {
        "total_documents": 0,
        "total_narratives": 0,
        "active_flags": len([f for f in subject.sentinel_flags if not f.is_resolved]),
        "last_collection": subject.config.last_collection_at if subject.config else None,
    }

    return SubjectDetailResponse(
        **SubjectResponse.model_validate(subject).model_dump(),
        metrics=metrics,
        recent_flags=[
            SentinelFlagResponse.model_validate(f)
            for f in sorted(
                subject.sentinel_flags, key=lambda x: x.created_at, reverse=True
            )[:5]
        ],
    )


@router.put(
    "/{subject_id}",
    response_model=SubjectResponse,
    summary="Update subject configuration",
    description="Update an existing subject's configuration.",
)
async def update_subject(
    subject_id: OwnerSubjectAccess,
    subject_data: SubjectUpdate,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> SubjectResponse:
    """
    Update subject configuration:
    - **name**: Update display name
    - **description**: Update description
    - **config**: Update monitoring configuration
    """
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with id '{subject_id}' not found",
        )

    # Update basic fields
    if subject_data.name is not None:
        # Check for duplicate name
        existing = await db.execute(
            select(Subject).where(
                Subject.name == subject_data.name,
                Subject.organization_id == current_user.organization_id,
                Subject.id != subject_id,
                Subject.is_archived == False,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Subject with name '{subject_data.name}' already exists",
            )
        subject.name = subject_data.name

    if subject_data.description is not None:
        subject.description = subject_data.description

    subject.updated_at = datetime.utcnow()

    # Update configuration if provided
    if subject_data.config is not None:
        config = await db.execute(
            select(SubjectConfig).where(SubjectConfig.subject_id == subject_id)
        )
        config = config.scalar_one_or_none()

        if config:
            if subject_data.config.keywords is not None:
                config.keywords = subject_data.config.keywords
            if subject_data.config.entities is not None:
                config.entities = subject_data.config.entities
            if subject_data.config.sources is not None:
                config.sources = subject_data.config.sources
            if subject_data.config.alert_thresholds is not None:
                config.alert_thresholds = subject_data.config.alert_thresholds.model_dump()
            if subject_data.config.collection_schedule is not None:
                config.collection_schedule = subject_data.config.collection_schedule
            if subject_data.config.is_active is not None:
                config.is_active = subject_data.config.is_active
            config.updated_at = datetime.utcnow()

    await db.flush()
    await db.refresh(subject, ["config"])

    return SubjectResponse.model_validate(subject)


@router.delete(
    "/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive subject",
    description="Archive a subject (soft delete). The subject can be restored later.",
)
async def archive_subject(
    subject_id: OwnerSubjectAccess,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> None:
    """
    Archive a subject. This performs a soft delete:
    - The subject is marked as archived
    - Data collection stops
    - Historical data is preserved
    - The subject can be restored by an admin
    """
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with id '{subject_id}' not found",
        )

    subject.is_archived = True
    subject.archived_at = datetime.utcnow()
    subject.updated_at = datetime.utcnow()

    # Deactivate configuration
    config_result = await db.execute(
        select(SubjectConfig).where(SubjectConfig.subject_id == subject_id)
    )
    config = config_result.scalar_one_or_none()
    if config:
        config.is_active = False
        config.updated_at = datetime.utcnow()


@router.get(
    "/{subject_id}/digest",
    response_model=SubjectDigestResponse,
    summary="Get Sentinel digest",
    description="Get the latest Sentinel flags and alerts for a subject.",
)
async def get_subject_digest(
    subject_id: VerifiedSubjectAccess,
    db: DatabaseSession,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50, description="Number of flags to return")] = 10,
    include_resolved: Annotated[bool, Query(description="Include resolved flags")] = False,
) -> SubjectDigestResponse:
    """
    Get Sentinel digest containing:
    - Latest flags (velocity spikes, coordinated activity, etc.)
    - Alert severity distribution
    - Trending narratives
    - Recommended actions
    """
    # Build query for sentinel flags
    query = (
        select(SentinelFlag)
        .where(SentinelFlag.subject_id == subject_id)
        .order_by(SentinelFlag.created_at.desc())
    )

    if not include_resolved:
        query = query.where(SentinelFlag.is_resolved == False)

    query = query.limit(limit)

    result = await db.execute(query)
    flags = result.scalars().all()

    # Calculate severity distribution
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for flag in flags:
        if flag.severity in severity_counts:
            severity_counts[flag.severity] += 1

    # Get subject for summary
    subject = await db.get(Subject, subject_id)

    return SubjectDigestResponse(
        subject_id=subject_id,
        subject_name=subject.name if subject else "Unknown",
        generated_at=datetime.utcnow(),
        flags=[SentinelFlagResponse.model_validate(f) for f in flags],
        severity_distribution=severity_counts,
        total_active_flags=len([f for f in flags if not f.is_resolved]),
        summary=_generate_digest_summary(flags, severity_counts),
    )


def _generate_digest_summary(flags: list[SentinelFlag], severity_counts: dict) -> str:
    """Generate a human-readable summary of the digest."""
    if not flags:
        return "No active flags. Narrative landscape is stable."

    critical_high = severity_counts["critical"] + severity_counts["high"]
    if critical_high > 0:
        return (
            f"Attention required: {critical_high} high-priority flag(s) detected. "
            f"Review recommended for {flags[0].flag_type if flags else 'emerging patterns'}."
        )

    total = sum(severity_counts.values())
    return f"{total} flag(s) under monitoring. Latest: {flags[0].flag_type if flags else 'N/A'}."
