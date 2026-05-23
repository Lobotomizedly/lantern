"""
Agent Endpoints
Handles Investigator agent spawning, monitoring, and trace retrieval.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import AgentRun, AgentTrace, Subject
from app.models.schemas.agents import (
    InvestigateRequest,
    AgentRunResponse,
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentTraceResponse,
    AgentRunStatus,
    AgentCostSummary,
)

router = APIRouter()


@router.post(
    "/investigate",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Spawn an Investigator agent",
    description="Start an AI-powered investigation on a topic or narrative.",
)
async def spawn_investigator(
    request: InvestigateRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> AgentRunResponse:
    """
    Spawn an Investigator agent to analyze:
    - **query**: The investigation question or topic
    - **subject_id**: Optional subject context
    - **depth**: Investigation depth (shallow, medium, deep)
    - **focus_areas**: Specific areas to investigate
    - **max_iterations**: Maximum agent iterations
    - **include_sources**: Whether to include source verification

    The agent runs asynchronously. Use GET /agents/runs/{id} to check status.
    """
    # Validate subject access if provided
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

    # Check rate limits / quotas
    recent_runs = await db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.user_id == current_user.id,
            AgentRun.created_at >= datetime.utcnow() - __import__("datetime").timedelta(hours=1),
        )
    )
    run_count = recent_runs.scalar() or 0

    # Rate limit: 10 runs per hour
    if run_count >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 10 agent runs per hour.",
            headers={"Retry-After": "3600"},
        )

    # Create agent run record
    agent_run = AgentRun(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        subject_id=request.subject_id,
        agent_type="investigator",
        query=request.query,
        config={
            "depth": request.depth or "medium",
            "focus_areas": request.focus_areas or [],
            "max_iterations": request.max_iterations or 10,
            "include_sources": request.include_sources if request.include_sources is not None else True,
        },
        status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(agent_run)
    await db.flush()

    # In production, this would queue the job to a task runner (e.g., Celery)
    # For now, we just create the record and mark it as queued
    agent_run.status = "queued"
    agent_run.queued_at = datetime.utcnow()
    await db.flush()

    return AgentRunResponse(
        id=agent_run.id,
        agent_type=agent_run.agent_type,
        query=agent_run.query,
        status=agent_run.status,
        subject_id=agent_run.subject_id,
        created_at=agent_run.created_at,
        queued_at=agent_run.queued_at,
        started_at=agent_run.started_at,
        completed_at=agent_run.completed_at,
        estimated_completion_seconds=_estimate_completion_time(request),
    )


@router.get(
    "/runs",
    response_model=AgentRunListResponse,
    summary="List agent runs",
    description="Retrieve a paginated list of agent runs.",
)
async def list_agent_runs(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Filter by status (pending, queued, running, completed, failed, cancelled)",
        ),
    ] = None,
    agent_type: Annotated[
        str | None, Query(description="Filter by agent type")
    ] = None,
    subject_id: Annotated[UUID | None, Query(description="Filter by subject")] = None,
) -> AgentRunListResponse:
    """
    List agent runs with filtering:
    - **status**: Filter by run status
    - **agent_type**: Filter by agent type
    - **subject_id**: Filter by associated subject
    """
    # Build query
    query = select(AgentRun).where(
        AgentRun.organization_id == current_user.organization_id
    )

    # Apply filters
    if status_filter:
        query = query.where(AgentRun.status == status_filter)

    if agent_type:
        query = query.where(AgentRun.agent_type == agent_type)

    if subject_id:
        query = query.where(AgentRun.subject_id == subject_id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination and ordering
    query = (
        query.options(selectinload(AgentRun.subject))
        .order_by(AgentRun.created_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    runs = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return AgentRunListResponse(
        items=[
            AgentRunResponse(
                id=run.id,
                agent_type=run.agent_type,
                query=run.query,
                status=run.status,
                subject_id=run.subject_id,
                subject_name=run.subject.name if run.subject else None,
                created_at=run.created_at,
                queued_at=run.queued_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
            )
            for run in runs
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunDetailResponse,
    summary="Get agent run details",
    description="Retrieve detailed information about a specific agent run.",
)
async def get_agent_run(
    run_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    include_trace: Annotated[
        bool, Query(description="Include execution trace")
    ] = True,
    trace_limit: Annotated[
        int, Query(ge=1, le=100, description="Max trace entries")
    ] = 50,
) -> AgentRunDetailResponse:
    """
    Get agent run details including:
    - **Status**: Current run status and progress
    - **Cost**: Token usage and cost breakdown
    - **Trace**: Execution trace with tool calls and reasoning
    - **Output**: Final investigation output (if completed)
    """
    query = (
        select(AgentRun)
        .options(
            selectinload(AgentRun.subject),
            selectinload(AgentRun.traces),
        )
        .where(AgentRun.id == run_id)
    )

    result = await db.execute(query)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run with id '{run_id}' not found",
        )

    # Verify access
    if (
        run.organization_id != current_user.organization_id
        and current_user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this agent run",
        )

    # Build trace response
    traces: list[AgentTraceResponse] = []
    if include_trace and run.traces:
        sorted_traces = sorted(run.traces, key=lambda x: x.sequence_number)[
            :trace_limit
        ]
        traces = [
            AgentTraceResponse(
                id=trace.id,
                sequence_number=trace.sequence_number,
                trace_type=trace.trace_type,
                content=trace.content,
                tool_name=trace.tool_name,
                tool_input=trace.tool_input,
                tool_output=trace.tool_output,
                tokens_used=trace.tokens_used,
                duration_ms=trace.duration_ms,
                created_at=trace.created_at,
            )
            for trace in sorted_traces
        ]

    # Calculate cost summary
    cost_summary = _calculate_cost_summary(run)

    # Calculate progress
    progress = _calculate_progress(run)

    return AgentRunDetailResponse(
        id=run.id,
        agent_type=run.agent_type,
        query=run.query,
        status=run.status,
        subject_id=run.subject_id,
        subject_name=run.subject.name if run.subject else None,
        config=run.config,
        created_at=run.created_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        output=run.output,
        error=run.error,
        cost=cost_summary,
        progress=progress,
        traces=traces,
    )


def _estimate_completion_time(request: InvestigateRequest) -> int:
    """Estimate completion time in seconds based on request parameters."""
    base_time = 30  # Base 30 seconds

    depth_multiplier = {
        "shallow": 1,
        "medium": 2,
        "deep": 4,
    }

    multiplier = depth_multiplier.get(request.depth or "medium", 2)
    iterations = request.max_iterations or 10

    return base_time * multiplier + (iterations * 5)


def _calculate_cost_summary(run: AgentRun) -> AgentCostSummary:
    """Calculate cost summary from agent run traces."""
    total_input_tokens = 0
    total_output_tokens = 0
    total_tool_calls = 0

    if run.traces:
        for trace in run.traces:
            if trace.tokens_used:
                # Assume tokens_used is a dict with input/output
                if isinstance(trace.tokens_used, dict):
                    total_input_tokens += trace.tokens_used.get("input", 0)
                    total_output_tokens += trace.tokens_used.get("output", 0)
                else:
                    total_output_tokens += trace.tokens_used

            if trace.trace_type == "tool_call":
                total_tool_calls += 1

    # Calculate cost (example rates)
    input_cost = (total_input_tokens / 1000) * 0.003  # $0.003 per 1K input tokens
    output_cost = (total_output_tokens / 1000) * 0.015  # $0.015 per 1K output tokens

    return AgentCostSummary(
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        total_tokens=total_input_tokens + total_output_tokens,
        tool_calls=total_tool_calls,
        estimated_cost_usd=round(input_cost + output_cost, 4),
    )


def _calculate_progress(run: AgentRun) -> dict:
    """Calculate progress information for the agent run."""
    if run.status == "completed":
        return {"percentage": 100, "current_step": "Completed", "steps_completed": run.config.get("max_iterations", 10) if run.config else 10}

    if run.status == "failed":
        return {"percentage": 0, "current_step": "Failed", "error": run.error}

    if run.status in ("pending", "queued"):
        return {"percentage": 0, "current_step": "Waiting to start"}

    if run.status == "running" and run.traces:
        max_iterations = run.config.get("max_iterations", 10) if run.config else 10
        current_iteration = len([t for t in run.traces if t.trace_type == "iteration"])
        percentage = min(95, int((current_iteration / max_iterations) * 100))

        latest_trace = sorted(run.traces, key=lambda x: x.sequence_number)[-1]
        current_step = f"Iteration {current_iteration}: {latest_trace.trace_type}"

        return {
            "percentage": percentage,
            "current_step": current_step,
            "steps_completed": current_iteration,
            "total_steps": max_iterations,
        }

    return {"percentage": 0, "current_step": "Initializing"}
