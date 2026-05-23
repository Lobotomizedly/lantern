"""
Events Endpoints
Handles listing and retrieval of detected events and happenings.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import Event, Entity
from app.models.schemas import (
    EventRead,
    EntitySummary,
    EventListResponse,
    EventDetailResponse,
)

router = APIRouter()


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "",
    response_model=EventListResponse,
    summary="List events",
    description="Retrieve a paginated list of detected events with optional filters.",
)
async def list_events(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    event_type: Annotated[
        str | None, Query(description="Filter by event type/category")
    ] = None,
    occurred_after: Annotated[
        datetime | None, Query(description="Filter events that occurred after this date")
    ] = None,
    occurred_before: Annotated[
        datetime | None, Query(description="Filter events that occurred before this date")
    ] = None,
    location: Annotated[
        str | None, Query(description="Filter by location (partial match)")
    ] = None,
    min_confidence: Annotated[
        float | None, Query(ge=0.0, le=1.0, description="Minimum confidence score")
    ] = None,
    entity_id: Annotated[
        UUID | None, Query(description="Filter events involving a specific entity")
    ] = None,
    search: Annotated[
        str | None, Query(description="Search in title and description")
    ] = None,
) -> EventListResponse:
    """
    List detected events with filtering options:
    - **event_type**: Filter by event type/category
    - **occurred_after/occurred_before**: Filter by date range
    - **location**: Filter by location (partial match)
    - **min_confidence**: Filter by minimum confidence score
    - **entity_id**: Filter events involving a specific entity
    - **search**: Full-text search in title and description
    """
    # Build base query
    query = select(Event)

    # Apply filters
    if event_type:
        query = query.where(Event.event_type == event_type)

    if occurred_after:
        query = query.where(Event.occurred_at >= occurred_after)

    if occurred_before:
        query = query.where(Event.occurred_at <= occurred_before)

    if location:
        query = query.where(Event.location.ilike(f"%{location}%"))

    if min_confidence is not None:
        query = query.where(Event.confidence >= min_confidence)

    if entity_id:
        # Filter events that involve a specific entity
        query = query.join(Event.entities).where(Entity.id == entity_id)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Event.title.ilike(search_filter))
            | (Event.description.ilike(search_filter))
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Calculate pagination metadata
    total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0

    # Apply pagination and ordering (most recent first)
    query = (
        query.options(selectinload(Event.entities))
        .order_by(Event.occurred_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    events = result.scalars().unique().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return EventListResponse(
        items=[EventRead.model_validate(event) for event in events],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
        has_next=pagination.page < total_pages,
        has_prev=pagination.page > 1,
    )


@router.get(
    "/{event_id}",
    response_model=EventDetailResponse,
    summary="Get event details",
    description="Retrieve detailed information about a specific event.",
)
async def get_event(
    event_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> EventDetailResponse:
    """
    Get detailed event information including:
    - Full event details and metadata
    - List of involved entities with their roles
    - Count of evidence items
    """
    query = (
        select(Event)
        .options(selectinload(Event.entities))
        .where(Event.id == event_id)
    )

    result = await db.execute(query)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        )

    # Build entity summaries
    involved_entities = []
    if event.entities:
        for entity in event.entities:
            involved_entities.append(
                EntitySummary(
                    id=entity.id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    role=None,  # Role would come from the association table
                )
            )

    # Build response
    event_data = EventRead.model_validate(event)

    return EventDetailResponse(
        **event_data.model_dump(),
        involved_entities=involved_entities,
        evidence_item_count=len(event.evidence_item_ids) if event.evidence_item_ids else 0,
    )
