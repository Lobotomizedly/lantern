"""
Timeline Endpoints
Handles event timeline generation and filtering.
"""

from datetime import datetime, date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import TimelineEvent, Subject, Document, Narrative
from app.models.schemas.timeline import (
    TimelineResponse,
    TimelineEventResponse,
    TimelineFilters,
    TimelineAggregation,
)

router = APIRouter()


@router.get(
    "",
    response_model=TimelineResponse,
    summary="Get event timeline",
    description="Retrieve a chronological timeline of events with filtering.",
)
async def get_timeline(
    db: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
    subject_id: Annotated[UUID | None, Query(description="Filter by subject")] = None,
    start_date: Annotated[
        date | None, Query(description="Start date (inclusive)")
    ] = None,
    end_date: Annotated[date | None, Query(description="End date (inclusive)")] = None,
    event_types: Annotated[
        list[str] | None,
        Query(
            description="Filter by event types (document, narrative_change, flag, milestone)"
        ),
    ] = None,
    importance: Annotated[
        str | None,
        Query(description="Minimum importance level (low, medium, high, critical)"),
    ] = None,
    narrative_id: Annotated[
        UUID | None, Query(description="Filter by narrative")
    ] = None,
    aggregation: Annotated[
        str | None,
        Query(description="Aggregation period (hour, day, week, month)"),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 50,
) -> TimelineResponse:
    """
    Get event timeline with options:
    - **subject_id**: Filter events for a specific subject
    - **start_date/end_date**: Date range filter
    - **event_types**: Filter by event type
    - **importance**: Filter by importance level
    - **narrative_id**: Filter by associated narrative
    - **aggregation**: Group events by time period
    """
    # Build base query
    query = select(TimelineEvent)

    # Filter by subject or organization access
    if subject_id:
        query = query.where(TimelineEvent.subject_id == subject_id)
    else:
        # Filter to user's organization subjects
        subquery = select(Subject.id).where(
            Subject.organization_id == current_user.organization_id
        )
        query = query.where(TimelineEvent.subject_id.in_(subquery))

    # Apply date filters
    if start_date:
        start_datetime = datetime.combine(start_date, datetime.min.time())
        query = query.where(TimelineEvent.occurred_at >= start_datetime)

    if end_date:
        end_datetime = datetime.combine(end_date, datetime.max.time())
        query = query.where(TimelineEvent.occurred_at <= end_datetime)

    # Apply event type filter
    if event_types:
        query = query.where(TimelineEvent.event_type.in_(event_types))

    # Apply importance filter
    if importance:
        importance_levels = _get_importance_levels(importance)
        query = query.where(TimelineEvent.importance.in_(importance_levels))

    # Apply narrative filter
    if narrative_id:
        query = query.where(TimelineEvent.narrative_id == narrative_id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply ordering and pagination
    query = (
        query.options(
            selectinload(TimelineEvent.subject),
            selectinload(TimelineEvent.document),
            selectinload(TimelineEvent.narrative),
        )
        .order_by(TimelineEvent.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    events = result.scalars().all()

    # Build aggregation if requested
    aggregation_data = None
    if aggregation:
        aggregation_data = await _build_timeline_aggregation(
            db, current_user, subject_id, start_date, end_date, aggregation
        )

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)

    return TimelineResponse(
        events=[
            TimelineEventResponse(
                id=event.id,
                event_type=event.event_type,
                title=event.title,
                description=event.description,
                occurred_at=event.occurred_at,
                importance=event.importance,
                subject_id=event.subject_id,
                subject_name=event.subject.name if event.subject else None,
                document_id=event.document_id,
                document_title=event.document.title if event.document else None,
                narrative_id=event.narrative_id,
                narrative_name=event.narrative.name if event.narrative else None,
                metadata=event.metadata,
            )
            for event in events
        ],
        total=total,
        page=page,
        page_size=page_size,
        filters=TimelineFilters(
            subject_id=subject_id,
            start_date=start_date,
            end_date=end_date,
            event_types=event_types,
            importance=importance,
            narrative_id=narrative_id,
        ),
        aggregation=aggregation_data,
    )


def _get_importance_levels(min_importance: str) -> list[str]:
    """Get list of importance levels at or above the specified minimum."""
    levels = ["low", "medium", "high", "critical"]
    try:
        min_index = levels.index(min_importance)
        return levels[min_index:]
    except ValueError:
        return levels


async def _build_timeline_aggregation(
    db: DatabaseSession,
    current_user: CurrentUser,
    subject_id: UUID | None,
    start_date: date | None,
    end_date: date | None,
    period: str,
) -> TimelineAggregation:
    """Build aggregated timeline statistics."""
    # Determine date truncation based on period
    if period == "hour":
        trunc_func = func.date_trunc("hour", TimelineEvent.occurred_at)
    elif period == "day":
        trunc_func = func.date_trunc("day", TimelineEvent.occurred_at)
    elif period == "week":
        trunc_func = func.date_trunc("week", TimelineEvent.occurred_at)
    elif period == "month":
        trunc_func = func.date_trunc("month", TimelineEvent.occurred_at)
    else:
        trunc_func = func.date_trunc("day", TimelineEvent.occurred_at)

    # Build aggregation query
    query = select(
        trunc_func.label("period"),
        TimelineEvent.event_type,
        func.count().label("count"),
    ).group_by(trunc_func, TimelineEvent.event_type)

    # Apply filters
    if subject_id:
        query = query.where(TimelineEvent.subject_id == subject_id)
    else:
        subquery = select(Subject.id).where(
            Subject.organization_id == current_user.organization_id
        )
        query = query.where(TimelineEvent.subject_id.in_(subquery))

    if start_date:
        query = query.where(
            TimelineEvent.occurred_at >= datetime.combine(start_date, datetime.min.time())
        )

    if end_date:
        query = query.where(
            TimelineEvent.occurred_at <= datetime.combine(end_date, datetime.max.time())
        )

    query = query.order_by(trunc_func)

    result = await db.execute(query)
    rows = result.all()

    # Build aggregation buckets
    buckets: dict[str, dict[str, int]] = {}
    event_type_totals: dict[str, int] = {}

    for row in rows:
        period_key = row.period.isoformat() if row.period else "unknown"
        event_type = row.event_type or "unknown"
        count = row.count

        if period_key not in buckets:
            buckets[period_key] = {}

        buckets[period_key][event_type] = count
        event_type_totals[event_type] = event_type_totals.get(event_type, 0) + count

    return TimelineAggregation(
        period=period,
        buckets=[
            {"period": k, "counts": v, "total": sum(v.values())}
            for k, v in buckets.items()
        ],
        event_type_totals=event_type_totals,
        total_events=sum(event_type_totals.values()),
    )
