"""
Dashboard Endpoints
Provides aggregated statistics and recent activity for the dashboard.
"""

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser
from app.models.orm import (
    Subject,
    Item,
    Event,
    Narrative,
    Artifact,
    AgentRun,
    Claim,
)

router = APIRouter()


# =============================================================================
# Response Schemas
# =============================================================================


class CountStats(BaseModel):
    """Count statistics for a resource."""

    total: int = Field(..., description="Total count")
    active: int = Field(default=0, description="Active count")
    new_today: int = Field(default=0, description="New items today")
    new_this_week: int = Field(default=0, description="New items this week")


class NarrativeStats(BaseModel):
    """Narrative-specific statistics."""

    total: int = Field(..., description="Total narratives")
    by_lifecycle: dict[str, int] = Field(
        default_factory=dict,
        description="Count by lifecycle stage",
    )
    avg_prevalence: float = Field(default=0.0, description="Average prevalence score")
    trending_count: int = Field(default=0, description="Number of trending narratives")


class AgentStats(BaseModel):
    """Agent run statistics."""

    total_runs: int = Field(default=0, description="Total agent runs")
    completed: int = Field(default=0, description="Completed runs")
    failed: int = Field(default=0, description="Failed runs")
    running: int = Field(default=0, description="Currently running")
    total_tokens_today: int = Field(default=0, description="Tokens used today")
    total_cost_today_usd: float = Field(default=0.0, description="Cost today in USD")


class SentimentDistribution(BaseModel):
    """Distribution of sentiment across items."""

    positive: int = Field(default=0, description="Positive sentiment items")
    neutral: int = Field(default=0, description="Neutral sentiment items")
    negative: int = Field(default=0, description="Negative sentiment items")


class DashboardStatsResponse(BaseModel):
    """Complete dashboard statistics."""

    subjects: CountStats
    items: CountStats
    events: CountStats
    narratives: NarrativeStats
    artifacts: CountStats
    agents: AgentStats
    sentiment_distribution: SentimentDistribution
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ActivityItem(BaseModel):
    """Single activity item."""

    id: str = Field(..., description="Activity ID")
    type: str = Field(..., description="Activity type")
    title: str = Field(..., description="Activity title/description")
    timestamp: datetime = Field(..., description="When the activity occurred")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class RecentActivityResponse(BaseModel):
    """Recent activity feed."""

    activities: list[ActivityItem] = Field(default_factory=list)
    total_count: int = Field(default=0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Get dashboard statistics",
    description="Retrieve aggregated statistics for the dashboard overview.",
)
async def get_dashboard_stats(
    db: DatabaseSession,
    current_user: CurrentUser,
) -> DashboardStatsResponse:
    """
    Get comprehensive dashboard statistics including:
    - Subject counts and status
    - Item ingestion metrics
    - Event detection counts
    - Narrative lifecycle distribution
    - Artifact generation stats
    - Agent run metrics
    - Sentiment distribution
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    # Subject stats
    subject_total = (await db.execute(select(func.count(Subject.id)))).scalar() or 0
    subject_active = (
        await db.execute(select(func.count(Subject.id)).where(Subject.is_active == True))
    ).scalar() or 0
    subject_new_today = (
        await db.execute(
            select(func.count(Subject.id)).where(Subject.created_at >= today_start)
        )
    ).scalar() or 0
    subject_new_week = (
        await db.execute(
            select(func.count(Subject.id)).where(Subject.created_at >= week_start)
        )
    ).scalar() or 0

    # Item stats
    item_total = (await db.execute(select(func.count(Item.id)))).scalar() or 0
    item_new_today = (
        await db.execute(
            select(func.count(Item.id)).where(Item.created_at >= today_start)
        )
    ).scalar() or 0
    item_new_week = (
        await db.execute(
            select(func.count(Item.id)).where(Item.created_at >= week_start)
        )
    ).scalar() or 0

    # Event stats
    event_total = (await db.execute(select(func.count(Event.id)))).scalar() or 0
    event_new_today = (
        await db.execute(
            select(func.count(Event.id)).where(Event.created_at >= today_start)
        )
    ).scalar() or 0
    event_new_week = (
        await db.execute(
            select(func.count(Event.id)).where(Event.created_at >= week_start)
        )
    ).scalar() or 0

    # Narrative stats
    narrative_total = (await db.execute(select(func.count(Narrative.id)))).scalar() or 0

    # Count by lifecycle
    lifecycle_counts = {}
    for lifecycle in ["emerging", "growing", "peaking", "declining", "dormant"]:
        count = (
            await db.execute(
                select(func.count(Narrative.id)).where(Narrative.lifecycle == lifecycle)
            )
        ).scalar() or 0
        lifecycle_counts[lifecycle] = count

    # Average prevalence
    avg_prevalence_result = (
        await db.execute(select(func.avg(Narrative.prevalence_score)))
    ).scalar()
    avg_prevalence = float(avg_prevalence_result) if avg_prevalence_result else 0.0

    # Trending narratives (velocity > 0.5)
    trending_count = (
        await db.execute(
            select(func.count(Narrative.id)).where(Narrative.velocity > 0.5)
        )
    ).scalar() or 0

    # Artifact stats
    artifact_total = (await db.execute(select(func.count(Artifact.id)))).scalar() or 0
    artifact_published = (
        await db.execute(
            select(func.count(Artifact.id)).where(Artifact.status == "published")
        )
    ).scalar() or 0
    artifact_new_today = (
        await db.execute(
            select(func.count(Artifact.id)).where(Artifact.created_at >= today_start)
        )
    ).scalar() or 0
    artifact_new_week = (
        await db.execute(
            select(func.count(Artifact.id)).where(Artifact.created_at >= week_start)
        )
    ).scalar() or 0

    # Agent run stats
    agent_total = (await db.execute(select(func.count(AgentRun.id)))).scalar() or 0
    agent_completed = (
        await db.execute(
            select(func.count(AgentRun.id)).where(AgentRun.status == "completed")
        )
    ).scalar() or 0
    agent_failed = (
        await db.execute(
            select(func.count(AgentRun.id)).where(AgentRun.status == "failed")
        )
    ).scalar() or 0
    agent_running = (
        await db.execute(
            select(func.count(AgentRun.id)).where(AgentRun.status == "running")
        )
    ).scalar() or 0

    # Today's token usage and cost
    tokens_today_result = (
        await db.execute(
            select(func.sum(AgentRun.total_tokens)).where(
                AgentRun.created_at >= today_start
            )
        )
    ).scalar()
    tokens_today = int(tokens_today_result) if tokens_today_result else 0

    cost_today_result = (
        await db.execute(
            select(func.sum(AgentRun.total_cost_usd)).where(
                AgentRun.created_at >= today_start
            )
        )
    ).scalar()
    cost_today = float(cost_today_result) if cost_today_result else 0.0

    # Sentiment distribution
    positive_count = (
        await db.execute(
            select(func.count(Item.id)).where(Item.sentiment > 0.2)
        )
    ).scalar() or 0
    negative_count = (
        await db.execute(
            select(func.count(Item.id)).where(Item.sentiment < -0.2)
        )
    ).scalar() or 0
    neutral_count = (
        await db.execute(
            select(func.count(Item.id)).where(
                Item.sentiment >= -0.2, Item.sentiment <= 0.2
            )
        )
    ).scalar() or 0

    return DashboardStatsResponse(
        subjects=CountStats(
            total=subject_total,
            active=subject_active,
            new_today=subject_new_today,
            new_this_week=subject_new_week,
        ),
        items=CountStats(
            total=item_total,
            active=item_total,  # All items are "active"
            new_today=item_new_today,
            new_this_week=item_new_week,
        ),
        events=CountStats(
            total=event_total,
            active=event_total,
            new_today=event_new_today,
            new_this_week=event_new_week,
        ),
        narratives=NarrativeStats(
            total=narrative_total,
            by_lifecycle=lifecycle_counts,
            avg_prevalence=round(avg_prevalence, 3),
            trending_count=trending_count,
        ),
        artifacts=CountStats(
            total=artifact_total,
            active=artifact_published,
            new_today=artifact_new_today,
            new_this_week=artifact_new_week,
        ),
        agents=AgentStats(
            total_runs=agent_total,
            completed=agent_completed,
            failed=agent_failed,
            running=agent_running,
            total_tokens_today=tokens_today,
            total_cost_today_usd=round(cost_today, 4),
        ),
        sentiment_distribution=SentimentDistribution(
            positive=positive_count,
            neutral=neutral_count,
            negative=negative_count,
        ),
        generated_at=now,
    )


@router.get(
    "/activity",
    response_model=RecentActivityResponse,
    summary="Get recent activity",
    description="Retrieve recent activity feed for the dashboard.",
)
async def get_recent_activity(
    db: DatabaseSession,
    current_user: CurrentUser,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Maximum number of activities to return")
    ] = 20,
    activity_types: Annotated[
        list[str] | None,
        Query(description="Filter by activity types (item, event, narrative, artifact, agent)"),
    ] = None,
) -> RecentActivityResponse:
    """
    Get recent activity feed including:
    - New items ingested
    - Events detected
    - Narratives updated
    - Artifacts generated
    - Agent runs completed

    Activities are sorted by most recent first.
    """
    activities: list[ActivityItem] = []
    per_type_limit = limit // 5 if activity_types is None else limit // len(activity_types) if activity_types else limit

    # Get recent items
    if activity_types is None or "item" in activity_types:
        items_query = (
            select(Item)
            .options(selectinload(Item.source))
            .order_by(Item.created_at.desc())
            .limit(per_type_limit)
        )
        items_result = await db.execute(items_query)
        for item in items_result.scalars().all():
            activities.append(
                ActivityItem(
                    id=str(item.id),
                    type="item",
                    title=item.title or "Untitled item",
                    timestamp=item.created_at,
                    metadata={
                        "source": item.source.name if item.source else None,
                        "sentiment": item.sentiment,
                        "author": item.author,
                    },
                )
            )

    # Get recent events
    if activity_types is None or "event" in activity_types:
        events_query = (
            select(Event)
            .order_by(Event.created_at.desc())
            .limit(per_type_limit)
        )
        events_result = await db.execute(events_query)
        for event in events_result.scalars().all():
            activities.append(
                ActivityItem(
                    id=str(event.id),
                    type="event",
                    title=event.title,
                    timestamp=event.created_at,
                    metadata={
                        "event_type": event.event_type,
                        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                        "location": event.location,
                        "confidence": event.confidence,
                    },
                )
            )

    # Get recent narratives
    if activity_types is None or "narrative" in activity_types:
        narratives_query = (
            select(Narrative)
            .order_by(Narrative.updated_at.desc())
            .limit(per_type_limit)
        )
        narratives_result = await db.execute(narratives_query)
        for narrative in narratives_result.scalars().all():
            activities.append(
                ActivityItem(
                    id=str(narrative.id),
                    type="narrative",
                    title=narrative.thesis[:100] + "..." if len(narrative.thesis) > 100 else narrative.thesis,
                    timestamp=narrative.updated_at,
                    metadata={
                        "lifecycle": narrative.lifecycle,
                        "prevalence": narrative.prevalence_score,
                        "velocity": narrative.velocity,
                    },
                )
            )

    # Get recent artifacts
    if activity_types is None or "artifact" in activity_types:
        artifacts_query = (
            select(Artifact)
            .order_by(Artifact.created_at.desc())
            .limit(per_type_limit)
        )
        artifacts_result = await db.execute(artifacts_query)
        for artifact in artifacts_result.scalars().all():
            activities.append(
                ActivityItem(
                    id=str(artifact.id),
                    type="artifact",
                    title=artifact.title,
                    timestamp=artifact.created_at,
                    metadata={
                        "artifact_type": artifact.artifact_type,
                        "status": artifact.status,
                    },
                )
            )

    # Get recent agent runs
    if activity_types is None or "agent" in activity_types:
        agent_runs_query = (
            select(AgentRun)
            .order_by(AgentRun.created_at.desc())
            .limit(per_type_limit)
        )
        agent_runs_result = await db.execute(agent_runs_query)
        for run in agent_runs_result.scalars().all():
            activities.append(
                ActivityItem(
                    id=str(run.id),
                    type="agent",
                    title=f"{run.agent_name}: {run.task_description[:50]}...",
                    timestamp=run.created_at,
                    metadata={
                        "agent_name": run.agent_name,
                        "status": run.status,
                        "total_tokens": run.total_tokens,
                        "duration_ms": (
                            int((run.completed_at - run.started_at).total_seconds() * 1000)
                            if run.completed_at and run.started_at
                            else None
                        ),
                    },
                )
            )

    # Sort all activities by timestamp and limit
    activities.sort(key=lambda x: x.timestamp, reverse=True)
    activities = activities[:limit]

    return RecentActivityResponse(
        activities=activities,
        total_count=len(activities),
        generated_at=datetime.utcnow(),
    )
