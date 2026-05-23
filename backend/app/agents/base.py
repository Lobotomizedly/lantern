"""
Base Agent Framework

Implements the core agent contract with goal-oriented execution,
budget constraints, memory management, and Temporal integration.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

import anthropic
from pydantic import BaseModel, Field


class StopCondition(str, Enum):
    """Conditions that terminate agent execution."""
    GOAL_MET = "goal_met"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_NEW_INFO = "no_new_info"
    ERROR = "error"
    MANUAL_STOP = "manual_stop"


class ReviewPolicy(str, Enum):
    """Policy for output review before publication."""
    AUTO_PUBLISH = "auto_publish"
    HUMAN_REVIEW = "human_review"
    ESCALATE_ON_FLAG = "escalate_on_flag"


class AgentState(str, Enum):
    """Current state of agent execution."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentBudget(BaseModel):
    """Budget constraints for agent execution."""
    max_tokens: int = Field(default=100000, description="Maximum tokens to consume")
    max_cost: float = Field(default=10.0, description="Maximum cost in dollars")
    max_wallclock: int = Field(default=3600, description="Maximum wall-clock time in seconds")
    max_tool_calls: int = Field(default=100, description="Maximum tool invocations")
    max_sub_agents: int = Field(default=5, description="Maximum sub-agents to spawn")
    max_recursion_depth: int = Field(default=3, description="Maximum recursion depth for sub-agents")

    # Tracking fields
    tokens_used: int = Field(default=0, description="Tokens consumed so far")
    cost_incurred: float = Field(default=0.0, description="Cost incurred so far")
    tool_calls_made: int = Field(default=0, description="Tool calls made so far")
    sub_agents_spawned: int = Field(default=0, description="Sub-agents spawned so far")
    start_time: Optional[datetime] = Field(default=None, description="Execution start time")

    def check_budget(self) -> tuple[bool, Optional[str]]:
        """Check if budget is exhausted. Returns (is_ok, violation_reason)."""
        if self.tokens_used >= self.max_tokens:
            return False, f"Token budget exhausted: {self.tokens_used}/{self.max_tokens}"
        if self.cost_incurred >= self.max_cost:
            return False, f"Cost budget exhausted: ${self.cost_incurred:.2f}/${self.max_cost:.2f}"
        if self.tool_calls_made >= self.max_tool_calls:
            return False, f"Tool call budget exhausted: {self.tool_calls_made}/{self.max_tool_calls}"
        if self.sub_agents_spawned >= self.max_sub_agents:
            return False, f"Sub-agent budget exhausted: {self.sub_agents_spawned}/{self.max_sub_agents}"
        if self.start_time:
            elapsed = (datetime.utcnow() - self.start_time).total_seconds()
            if elapsed >= self.max_wallclock:
                return False, f"Wall-clock budget exhausted: {elapsed:.0f}s/{self.max_wallclock}s"
        return True, None

    def record_usage(
        self,
        tokens: int = 0,
        cost: float = 0.0,
        tool_calls: int = 0,
        sub_agents: int = 0,
    ) -> None:
        """Record resource usage."""
        self.tokens_used += tokens
        self.cost_incurred += cost
        self.tool_calls_made += tool_calls
        self.sub_agents_spawned += sub_agents


class AgentMemory(BaseModel):
    """Agent memory with run-scoped and persistent storage."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Run-scoped memory (cleared each run)
    working_memory: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)

    # Persistent memory (maintained across runs for standing agents)
    persistent_memory: Dict[str, Any] = Field(default_factory=dict)
    checkpoints: List[Dict[str, Any]] = Field(default_factory=list)

    def add_message(self, role: str, content: str, **metadata: Any) -> None:
        """Add a message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            **metadata,
        })

    def add_tool_result(self, tool_name: str, result: Any, **metadata: Any) -> None:
        """Record a tool execution result."""
        self.tool_results.append({
            "tool": tool_name,
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
            **metadata,
        })

    def create_checkpoint(self, label: str) -> Dict[str, Any]:
        """Create a checkpoint of current state."""
        checkpoint = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat(),
            "working_memory": self.working_memory.copy(),
            "conversation_length": len(self.conversation_history),
            "tool_results_length": len(self.tool_results),
        }
        self.checkpoints.append(checkpoint)
        return checkpoint

    def restore_checkpoint(self, label: str) -> bool:
        """Restore state from a labeled checkpoint."""
        for checkpoint in reversed(self.checkpoints):
            if checkpoint["label"] == label:
                self.working_memory = checkpoint["working_memory"].copy()
                self.conversation_history = self.conversation_history[:checkpoint["conversation_length"]]
                self.tool_results = self.tool_results[:checkpoint["tool_results_length"]]
                return True
        return False

    def clear_run_memory(self) -> None:
        """Clear run-scoped memory for a new run."""
        self.run_id = str(uuid.uuid4())
        self.working_memory = {}
        self.conversation_history = []
        self.tool_results = []


class Artifact(BaseModel):
    """An output artifact produced by an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = Field(..., description="Type of artifact (report, memo, timeline, etc.)")
    title: str = Field(..., description="Title of the artifact")
    content: str = Field(..., description="Main content of the artifact")
    citations: List[Dict[str, Any]] = Field(default_factory=list, description="Source citations")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(..., description="Agent ID that created this artifact")
    review_status: str = Field(default="pending", description="Review status")


class Flag(BaseModel):
    """A flag emitted by an agent for review."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = Field(..., description="Type of flag")
    severity: str = Field(default="info", description="Severity level: info, warning, alert, critical")
    title: str = Field(..., description="Short title")
    description: str = Field(..., description="Detailed description")
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Supporting evidence")
    subject_id: Optional[str] = Field(default=None, description="Related subject ID")
    narrative_id: Optional[str] = Field(default=None, description="Related narrative ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(..., description="Agent ID that created this flag")
    acknowledged: bool = Field(default=False)


class AgentOutput(BaseModel):
    """Output from agent execution."""
    success: bool = Field(..., description="Whether the agent completed successfully")
    stop_condition: StopCondition = Field(..., description="Why the agent stopped")
    artifacts: List[Artifact] = Field(default_factory=list)
    flags: List[Flag] = Field(default_factory=list)
    structured_result: Optional[Dict[str, Any]] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    execution_summary: Dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Configuration for an agent instance."""
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: str = Field(..., description="Type of agent")
    goal: str = Field(..., description="Goal description for the agent")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    toolset: List[str] = Field(default_factory=list, description="Allowed tools")
    budget: AgentBudget = Field(default_factory=AgentBudget)
    review_policy: ReviewPolicy = Field(default=ReviewPolicy.HUMAN_REVIEW)
    model: str = Field(default="claude-sonnet-4-20250514", description="Claude model to use")
    temperature: float = Field(default=0.7, description="Model temperature")
    parent_agent_id: Optional[str] = Field(default=None, description="Parent agent if spawned")
    recursion_depth: int = Field(default=0, description="Current recursion depth")

    # Temporal integration
    workflow_id: Optional[str] = Field(default=None, description="Associated Temporal workflow ID")
    activity_heartbeat_timeout: int = Field(default=60, description="Heartbeat timeout in seconds")


T = TypeVar("T", bound=AgentOutput)


class Agent(ABC, Generic[T]):
    """
    Base agent class implementing the agent contract.

    Agents are goal-oriented, budget-constrained units of work that:
    - Execute toward a specific goal
    - Use a defined toolset
    - Maintain run-scoped and persistent memory
    - Respect budget constraints
    - Produce artifacts, flags, or structured results
    - Integrate with Temporal for durable execution
    """

    def __init__(
        self,
        config: AgentConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        self.config = config
        self.memory = memory or AgentMemory()
        self.client = client or anthropic.AsyncAnthropic()
        self.state = AgentState.PENDING
        self._tools: Dict[str, Any] = {}
        self._stop_requested = False

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def goal(self) -> str:
        return self.config.goal

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent type."""
        pass

    @abstractmethod
    async def execute(self) -> T:
        """Execute the agent's main logic."""
        pass

    @abstractmethod
    def check_goal_met(self) -> bool:
        """Check if the agent's goal has been achieved."""
        pass

    @abstractmethod
    def check_no_new_info(self) -> bool:
        """Check if the agent has exhausted available information."""
        pass

    def register_tool(self, name: str, tool: Any) -> None:
        """Register a tool for use by this agent."""
        if name in self.config.toolset or not self.config.toolset:
            self._tools[name] = tool

    async def run(self) -> T:
        """Run the agent with full lifecycle management."""
        self.state = AgentState.RUNNING
        self.config.budget.start_time = datetime.utcnow()

        try:
            # Create initial checkpoint
            self.memory.create_checkpoint("start")

            # Execute main logic
            output = await self.execute()

            # Determine final state
            self.state = AgentState.COMPLETED if output.success else AgentState.FAILED

            return output

        except Exception as e:
            self.state = AgentState.FAILED
            return self._create_error_output(str(e))

    async def call_claude(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
    ) -> anthropic.types.Message:
        """Make a call to Claude with budget tracking."""
        # Check budget before call
        is_ok, violation = self.config.budget.check_budget()
        if not is_ok:
            raise BudgetExhaustedException(violation)

        # Prepare request
        request_params = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "system": self.get_system_prompt(),
            "messages": messages,
            "temperature": self.config.temperature,
        }

        if tools:
            request_params["tools"] = tools

        # Make the call
        response = await self.client.messages.create(**request_params)

        # Track usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens = input_tokens + output_tokens

        # Estimate cost (approximate rates)
        cost = self._estimate_cost(input_tokens, output_tokens)

        self.config.budget.record_usage(tokens=total_tokens, cost=cost)

        # Store in memory
        self.memory.add_message("assistant", str(response.content))

        return response

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on model and token counts."""
        # Approximate rates per 1K tokens
        rates = {
            "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
            "claude-opus-4-20250514": {"input": 0.015, "output": 0.075},
            "claude-3-5-haiku-20241022": {"input": 0.001, "output": 0.005},
        }

        model_rates = rates.get(
            self.config.model,
            {"input": 0.003, "output": 0.015}  # Default to Sonnet rates
        )

        return (input_tokens / 1000 * model_rates["input"] +
                output_tokens / 1000 * model_rates["output"])

    def determine_stop_condition(self) -> Optional[StopCondition]:
        """Determine if and why the agent should stop."""
        if self._stop_requested:
            return StopCondition.MANUAL_STOP

        is_ok, _ = self.config.budget.check_budget()
        if not is_ok:
            return StopCondition.BUDGET_EXHAUSTED

        if self.check_goal_met():
            return StopCondition.GOAL_MET

        if self.check_no_new_info():
            return StopCondition.NO_NEW_INFO

        return None

    def request_stop(self) -> None:
        """Request the agent to stop at the next opportunity."""
        self._stop_requested = True

    def _create_error_output(self, error_message: str) -> T:
        """Create an error output object."""
        return AgentOutput(
            success=False,
            stop_condition=StopCondition.ERROR,
            error_message=error_message,
            execution_summary={
                "agent_id": self.agent_id,
                "budget_used": {
                    "tokens": self.config.budget.tokens_used,
                    "cost": self.config.budget.cost_incurred,
                    "tool_calls": self.config.budget.tool_calls_made,
                },
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize agent state for persistence."""
        return {
            "config": self.config.model_dump(),
            "memory": self.memory.model_dump(),
            "state": self.state.value,
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        client: Optional[anthropic.AsyncAnthropic] = None,
    ) -> "Agent":
        """Deserialize agent state."""
        config = AgentConfig(**data["config"])
        memory = AgentMemory(**data["memory"])
        agent = cls(config=config, memory=memory, client=client)
        agent.state = AgentState(data["state"])
        return agent


class StandingAgent(Agent[T]):
    """
    Base class for standing agents that persist across runs.

    Standing agents:
    - Run on a schedule (e.g., daily)
    - Maintain persistent memory across runs
    - Monitor and compare against baselines
    - Associated with a specific entity (Subject, Narrative, etc.)
    """

    def __init__(
        self,
        config: AgentConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.entity_id: Optional[str] = config.inputs.get("entity_id")

    async def run(self) -> T:
        """Run with persistent memory management."""
        # Load any existing persistent memory
        await self._load_persistent_memory()

        # Clear run-scoped memory while preserving persistent
        self.memory.clear_run_memory()

        # Execute the agent
        output = await super().run()

        # Save persistent memory
        await self._save_persistent_memory()

        return output

    async def _load_persistent_memory(self) -> None:
        """Load persistent memory from storage. Override in subclass."""
        pass

    async def _save_persistent_memory(self) -> None:
        """Save persistent memory to storage. Override in subclass."""
        pass


class EphemeralAgent(Agent[T]):
    """
    Base class for ephemeral agents that run once and terminate.

    Ephemeral agents:
    - Spawned on-demand for specific tasks
    - Do not persist memory after completion
    - May be spawned by standing agents or users
    """

    def __init__(
        self,
        config: AgentConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.spawned_by = config.parent_agent_id


class BudgetExhaustedException(Exception):
    """Raised when an agent's budget is exhausted."""
    pass
