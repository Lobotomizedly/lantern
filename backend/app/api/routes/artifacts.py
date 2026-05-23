"""
Artifact Endpoints
Handles artifact generation, listing, and retrieval (reports, memos, timelines, newsletters).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import Artifact, Subject
from app.models.schemas.artifacts import (
    ArtifactCreateRequest,
    ArtifactResponse,
    ArtifactDetailResponse,
    ArtifactListResponse,
    ArtifactType,
    ArtifactStatus,
    ArtifactContent,
)

router = APIRouter()


@router.post(
    "",
    response_model=ArtifactResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an artifact",
    description="Request generation of a report, memo, timeline, or newsletter.",
)
async def create_artifact(
    request: ArtifactCreateRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> ArtifactResponse:
    """
    Request artifact generation:
    - **artifact_type**: Type of artifact (report, memo, timeline, newsletter)
    - **subject_id**: Subject to generate artifact for
    - **title**: Custom title for the artifact
    - **parameters**: Type-specific generation parameters
    - **schedule**: Optional recurring schedule

    Artifact types:
    - **report**: Comprehensive analysis report
    - **memo**: Executive summary memo
    - **timeline**: Visual timeline of events
    - **newsletter**: Stakeholder newsletter
    """
    # Validate subject access
    if request.subject_id:
        subject = await db.get(Subject, request.subject_id)
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject with id '{request.subject_id}' not found",
            )
        if (
            subject.organization_id != current_user.organization_id
            and current_user.role != "admin"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this subject",
            )

    # Validate artifact type parameters
    _validate_artifact_parameters(request.artifact_type, request.parameters)

    # Create artifact record
    artifact = Artifact(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        subject_id=request.subject_id,
        artifact_type=request.artifact_type,
        title=request.title or _generate_default_title(request.artifact_type, subject),
        description=request.description,
        parameters=request.parameters or {},
        schedule=request.schedule,
        status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(artifact)
    await db.flush()

    # Queue for generation
    artifact.status = "queued"
    artifact.queued_at = datetime.utcnow()

    # In production, this would trigger an async job
    # For immediate simple artifacts, we might generate synchronously
    if request.artifact_type == "memo" and not request.parameters.get("detailed"):
        artifact.status = "generating"
        artifact.started_at = datetime.utcnow()

    await db.flush()

    return ArtifactResponse(
        id=artifact.id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        description=artifact.description,
        status=artifact.status,
        subject_id=artifact.subject_id,
        created_at=artifact.created_at,
        queued_at=artifact.queued_at,
        started_at=artifact.started_at,
        completed_at=artifact.completed_at,
        estimated_completion_seconds=_estimate_generation_time(request),
    )


@router.get(
    "",
    response_model=ArtifactListResponse,
    summary="List artifacts",
    description="Retrieve a paginated list of artifacts.",
)
async def list_artifacts(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    artifact_type: Annotated[
        str | None, Query(description="Filter by artifact type")
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by status"),
    ] = None,
    subject_id: Annotated[UUID | None, Query(description="Filter by subject")] = None,
    created_by_me: Annotated[
        bool, Query(description="Only show artifacts created by current user")
    ] = False,
) -> ArtifactListResponse:
    """
    List artifacts with filtering:
    - **artifact_type**: Filter by type (report, memo, timeline, newsletter)
    - **status**: Filter by status (pending, queued, generating, completed, failed)
    - **subject_id**: Filter by associated subject
    - **created_by_me**: Only show user's own artifacts
    """
    # Build query
    query = select(Artifact).where(
        Artifact.organization_id == current_user.organization_id
    )

    # Apply filters
    if artifact_type:
        query = query.where(Artifact.artifact_type == artifact_type)

    if status_filter:
        query = query.where(Artifact.status == status_filter)

    if subject_id:
        query = query.where(Artifact.subject_id == subject_id)

    if created_by_me:
        query = query.where(Artifact.user_id == current_user.id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination and ordering
    query = (
        query.options(selectinload(Artifact.subject))
        .order_by(Artifact.created_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    artifacts = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return ArtifactListResponse(
        items=[
            ArtifactResponse(
                id=artifact.id,
                artifact_type=artifact.artifact_type,
                title=artifact.title,
                description=artifact.description,
                status=artifact.status,
                subject_id=artifact.subject_id,
                subject_name=artifact.subject.name if artifact.subject else None,
                created_at=artifact.created_at,
                queued_at=artifact.queued_at,
                started_at=artifact.started_at,
                completed_at=artifact.completed_at,
            )
            for artifact in artifacts
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{artifact_id}",
    response_model=ArtifactDetailResponse,
    summary="Get artifact content",
    description="Retrieve an artifact with its full content.",
)
async def get_artifact(
    artifact_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    include_metadata: Annotated[
        bool, Query(description="Include generation metadata")
    ] = True,
) -> ArtifactDetailResponse:
    """
    Get artifact details and content:
    - **content**: Full artifact content (HTML, markdown, or structured data)
    - **metadata**: Generation metadata and parameters
    - **export_urls**: URLs for various export formats
    """
    query = (
        select(Artifact)
        .options(selectinload(Artifact.subject))
        .where(Artifact.id == artifact_id)
    )

    result = await db.execute(query)
    artifact = result.scalar_one_or_none()

    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact with id '{artifact_id}' not found",
        )

    # Verify access
    if (
        artifact.organization_id != current_user.organization_id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this artifact",
        )

    # Build content response
    content = None
    if artifact.status == "completed" and artifact.content:
        content = ArtifactContent(
            format=artifact.content.get("format", "html"),
            body=artifact.content.get("body", ""),
            sections=artifact.content.get("sections"),
            data=artifact.content.get("data"),
        )

    # Build export URLs
    export_urls = None
    if artifact.status == "completed":
        base_url = f"/api/v1/artifacts/{artifact_id}/export"
        export_urls = {
            "pdf": f"{base_url}?format=pdf",
            "html": f"{base_url}?format=html",
            "markdown": f"{base_url}?format=md",
            "docx": f"{base_url}?format=docx",
        }

    # Build metadata
    metadata = None
    if include_metadata:
        metadata = {
            "parameters": artifact.parameters,
            "generation_time_seconds": (
                (artifact.completed_at - artifact.started_at).total_seconds()
                if artifact.completed_at and artifact.started_at
                else None
            ),
            "token_count": artifact.token_count,
            "version": artifact.version,
            "schedule": artifact.schedule,
        }

    return ArtifactDetailResponse(
        id=artifact.id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        description=artifact.description,
        status=artifact.status,
        subject_id=artifact.subject_id,
        subject_name=artifact.subject.name if artifact.subject else None,
        created_at=artifact.created_at,
        queued_at=artifact.queued_at,
        started_at=artifact.started_at,
        completed_at=artifact.completed_at,
        content=content,
        export_urls=export_urls,
        metadata=metadata,
        error=artifact.error,
    )


def _validate_artifact_parameters(artifact_type: str, parameters: dict | None) -> None:
    """Validate parameters for artifact type."""
    if not parameters:
        return

    valid_params = {
        "report": [
            "date_range",
            "include_narratives",
            "include_entities",
            "include_timeline",
            "include_recommendations",
            "format",
            "length",
        ],
        "memo": [
            "date_range",
            "audience",
            "focus_areas",
            "max_length",
            "detailed",
        ],
        "timeline": [
            "date_range",
            "granularity",
            "include_narratives",
            "include_documents",
            "format",
        ],
        "newsletter": [
            "date_range",
            "sections",
            "tone",
            "audience",
            "include_charts",
        ],
    }

    allowed = valid_params.get(artifact_type, [])
    invalid = [k for k in parameters.keys() if k not in allowed]

    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid parameters for {artifact_type}: {', '.join(invalid)}",
        )


def _generate_default_title(artifact_type: str, subject: Subject | None) -> str:
    """Generate a default title for an artifact."""
    subject_name = subject.name if subject else "General"
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    titles = {
        "report": f"{subject_name} Analysis Report - {date_str}",
        "memo": f"{subject_name} Executive Summary - {date_str}",
        "timeline": f"{subject_name} Timeline - {date_str}",
        "newsletter": f"{subject_name} Newsletter - {date_str}",
    }

    return titles.get(artifact_type, f"{artifact_type.title()} - {date_str}")


def _estimate_generation_time(request: ArtifactCreateRequest) -> int:
    """Estimate generation time in seconds."""
    base_times = {
        "report": 120,
        "memo": 30,
        "timeline": 45,
        "newsletter": 90,
    }

    base = base_times.get(request.artifact_type, 60)

    # Adjust based on parameters
    if request.parameters:
        if request.parameters.get("detailed"):
            base *= 2
        if request.parameters.get("include_narratives"):
            base += 30
        if request.parameters.get("include_charts"):
            base += 45

    return base
