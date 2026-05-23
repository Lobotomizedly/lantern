"""
Agent-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.schemas.common import BaseSchema, AgentRunStatus, AgentStepType


# =============================================================================
# Investigate Request
# =============================================================================


class InvestigateRequest(BaseModel):
    """Request schema for spawning an Investigator agent."""

    query: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="The investigation question or topic",
    )
    subject_id: Optional[UUID] = Field(
        default=None,
        description="Optional subject context for the investigation",
    )
    depth: Optional[str] = Field(
        default="medium",
        description="Investigation depth (shallow, medium, deep)",
    )
    focus_areas: Optional[list[str]] = Field(
        default=None,
        description="Specific areas to focus investigation on",
    )
    max_iterations: Optional[int] = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of agent iterations",
    )
    include_sources: Optional[bool] = Field(
        default=True,
        description="Whether to include source verification",
    )


# =============================================================================
# Agent Cost Summary
# =============================================================================


class AgentCostSummary(BaseModel):
    """Cost summary for an agent run."""

    input_tokens: int = Field(default=0, description="Total input tokens used")
    output_tokens: int = Field(default=0, description="Total output tokens used")
    total_tokens: int = Field(default=0, description="Total tokens used")
    tool_calls: int = Field(default=0, description="Number of tool calls made")
    estimated_cost_usd: float = Field(
        default=0.0, description="Estimated cost in USD"
    )


# =============================================================================
# Agent Trace
# =============================================================================


class AgentTrace(BaseModel):
    """Individual trace entry for an agent run."""

    id: UUID
    sequence_number: int
    trace_type: str = Field(..., description="Type of trace entry")
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[dict[str, Any]] = None
    tokens_used: Optional[int] = None
    duration_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Alias for backward compatibility
AgentTraceResponse = AgentTrace


# =============================================================================
# Agent Run Response
# =============================================================================


class AgentRunResponse(BaseModel):
    """Response schema for agent run listing."""

    id: UUID
    agent_type: str
    query: str
    status: str
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_completion_seconds: Optional[int] = None


class AgentRunListResponse(BaseModel):
    """Paginated list of agent runs."""

    items: list[AgentRunResponse]
    total: int
    page: int
    page_size: int


class AgentRunDetailResponse(AgentRunResponse):
    """Detailed agent run response with traces and cost."""

    config: Optional[dict[str, Any]] = None
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    cost: Optional[AgentCostSummary] = None
    progress: Optional[dict[str, Any]] = None
    traces: list[AgentTrace] = Field(default_factory=list)


# Alias for backward compatibility
AgentRunDetail = AgentRunDetailResponse


# =============================================================================
# Legacy Schemas (for backward compatibility)
# =============================================================================


class AgentRunBase(BaseSchema):
    """Base schema for AgentRun (tracking agent executions)."""

    agent_name: str = Field(
        ...,
        max_length=100,
        description="Name of the agent",
    )
    task_description: str = Field(
        ...,
        max_length=2000,
        description="Description of the task being performed",
    )
    status: AgentRunStatus = Field(
        default=AgentRunStatus.PENDING,
        description="Current status",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the agent",
    )
    output_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Output data from the agent",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="When the run started",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the run completed",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens used",
    )
    total_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Total cost in USD",
    )
    model_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Model used for this run",
    )
    parent_run_id: Optional[UUID] = Field(
        default=None,
        description="Parent run ID if this is a sub-run",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class AgentRunCreate(AgentRunBase):
    """Schema for creating an AgentRun."""

    pass


class AgentRunUpdate(BaseSchema):
    """Schema for updating an AgentRun."""

    status: Optional[AgentRunStatus] = None
    output_data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    total_tokens: Optional[int] = Field(
        default=None,
        ge=0,
    )
    total_cost_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
    )
    metadata: Optional[dict[str, Any]] = None


class AgentRunRead(AgentRunBase):
    """Schema for reading an AgentRun."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentStepBase(BaseSchema):
    """Base schema for AgentStep (individual step in an agent run)."""

    run_id: UUID = Field(
        ...,
        description="ID of the parent agent run",
    )
    step_number: int = Field(
        ...,
        ge=1,
        description="Step number in the sequence",
    )
    step_type: AgentStepType = Field(
        ...,
        description="Type of step",
    )
    name: str = Field(
        ...,
        max_length=200,
        description="Name of the step/tool/action",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for the step",
    )
    output_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Output data from the step",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Duration in milliseconds",
    )
    tokens_used: int = Field(
        default=0,
        ge=0,
        description="Tokens used in this step",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if the step failed",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class AgentStepCreate(AgentStepBase):
    """Schema for creating an AgentStep."""

    pass


class AgentStepRead(AgentStepBase):
    """Schema for reading an AgentStep."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
