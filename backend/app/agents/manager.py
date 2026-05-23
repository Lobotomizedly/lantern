"""
Agent Manager

Manages agent lifecycle: spawning, tracking, budget enforcement,
checkpointing, and output routing.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union

import anthropic
from pydantic import BaseModel, Field

from .base import (
    Agent,
    AgentConfig,
    AgentMemory,
    AgentOutput,
    AgentBudget,
    AgentState,
    ReviewPolicy,
    StopCondition,
    BudgetExhaustedException,
)
from .sentinel import SentinelAgent, SentinelConfig
from .narrative_tracker import NarrativeTrackerAgent, NarrativeTrackerConfig
from .graph_curator import GraphCuratorAgent, GraphCuratorConfig
from .investigator import InvestigatorAgent, InvestigatorConfig
from .synthesizer import SynthesizerAgent, SynthesizerConfig


class AgentRunStatus(str, Enum):
    """Status of an agent run."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentRun(BaseModel):
    """Record of an agent run."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    agent_type: str
    parent_run_id: Optional[str] = None
    recursion_depth: int = 0

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Status
    status: AgentRunStatus = AgentRunStatus.PENDING
    stop_condition: Optional[StopCondition] = None
    error_message: Optional[str] = None

    # Budget tracking
    budget_allocated: AgentBudget = Field(default_factory=AgentBudget)
    budget_used: Dict[str, Any] = Field(default_factory=dict)

    # Results
    output_artifacts: List[str] = Field(default_factory=list)  # Artifact IDs
    output_flags: List[str] = Field(default_factory=list)  # Flag IDs
    structured_result: Optional[Dict[str, Any]] = None

    # Checkpoints
    checkpoints: List[Dict[str, Any]] = Field(default_factory=list)


class ReviewQueueItem(BaseModel):
    """An item in the review queue."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    agent_type: str
    artifact_id: Optional[str] = None
    flag_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    priority: int = 0
    status: str = "pending"  # pending, in_review, approved, rejected


class AgentManager:
    """
    Manages the lifecycle of all agents in the system.

    Responsibilities:
    - Spawn and configure agents
    - Track active runs
    - Enforce budget constraints (kill on breach)
    - Handle checkpointing and retry
    - Route outputs to review queue
    - Record runs for cost/audit
    - Cap recursive spawning depth
    """

    # Agent type registry
    AGENT_TYPES: Dict[str, Type[Agent]] = {
        "sentinel": SentinelAgent,
        "narrative_tracker": NarrativeTrackerAgent,
        "graph_curator": GraphCuratorAgent,
        "investigator": InvestigatorAgent,
        "synthesizer": SynthesizerAgent,
    }

    CONFIG_TYPES: Dict[str, Type[AgentConfig]] = {
        "sentinel": SentinelConfig,
        "narrative_tracker": NarrativeTrackerConfig,
        "graph_curator": GraphCuratorConfig,
        "investigator": InvestigatorConfig,
        "synthesizer": SynthesizerConfig,
    }

    MAX_RECURSION_DEPTH = 5

    def __init__(
        self,
        client: Optional[anthropic.AsyncAnthropic] = None,
        review_service: Any = None,
        persistence_service: Any = None,
    ):
        self.client = client or anthropic.AsyncAnthropic()
        self.review_service = review_service
        self.persistence_service = persistence_service

        # Active runs
        self._active_runs: Dict[str, AgentRun] = {}
        self._running_agents: Dict[str, Agent] = {}

        # Run history (for audit)
        self._run_history: List[AgentRun] = []

        # Review queue
        self._review_queue: List[ReviewQueueItem] = []

        # Locks
        self._spawn_lock = asyncio.Lock()

    async def spawn_agent(
        self,
        agent_type: str,
        goal: str,
        inputs: Dict[str, Any],
        budget: Optional[AgentBudget] = None,
        review_policy: ReviewPolicy = ReviewPolicy.HUMAN_REVIEW,
        parent_run_id: Optional[str] = None,
        wait_for_completion: bool = True,
    ) -> Union[AgentRun, AgentOutput]:
        """
        Spawn a new agent.

        Args:
            agent_type: Type of agent to spawn
            goal: Goal description for the agent
            inputs: Input parameters specific to agent type
            budget: Budget constraints (uses defaults if not specified)
            review_policy: How outputs should be reviewed
            parent_run_id: ID of parent run if spawned by another agent
            wait_for_completion: Whether to wait for the agent to complete

        Returns:
            AgentRun if not waiting, AgentOutput if waiting for completion
        """
        async with self._spawn_lock:
            # Determine recursion depth
            recursion_depth = 0
            if parent_run_id and parent_run_id in self._active_runs:
                parent_run = self._active_runs[parent_run_id]
                recursion_depth = parent_run.recursion_depth + 1

                # Check recursion limit
                if recursion_depth > self.MAX_RECURSION_DEPTH:
                    raise RecursionDepthExceeded(
                        f"Maximum recursion depth ({self.MAX_RECURSION_DEPTH}) exceeded"
                    )

            # Get agent class
            if agent_type not in self.AGENT_TYPES:
                raise ValueError(f"Unknown agent type: {agent_type}")

            agent_class = self.AGENT_TYPES[agent_type]
            config_class = self.CONFIG_TYPES[agent_type]

            # Build configuration
            config_data = {
                "agent_type": agent_type,
                "goal": goal,
                "review_policy": review_policy,
                "recursion_depth": recursion_depth,
                **inputs,
            }

            if parent_run_id:
                config_data["parent_agent_id"] = parent_run_id

            config = config_class(**config_data)

            # Apply budget
            if budget:
                config.budget = budget
            elif parent_run_id and parent_run_id in self._active_runs:
                # Inherit reduced budget from parent
                parent_budget = self._active_runs[parent_run_id].budget_allocated
                config.budget = self._calculate_sub_budget(parent_budget)

            # Create run record
            run = AgentRun(
                agent_id=config.agent_id,
                agent_type=agent_type,
                parent_run_id=parent_run_id,
                recursion_depth=recursion_depth,
                budget_allocated=config.budget,
            )

            self._active_runs[run.run_id] = run

            # Create agent instance
            memory = AgentMemory()
            agent = agent_class(config=config, memory=memory, client=self.client)

            self._running_agents[run.run_id] = agent

        # Execute
        if wait_for_completion:
            return await self._execute_agent(run, agent)
        else:
            # Start in background
            asyncio.create_task(self._execute_agent(run, agent))
            return run

    async def spawn_sub_agent(
        self,
        agent_type: str,
        goal: str,
        inputs: Dict[str, Any],
        budget_fraction: float = 0.25,
        wait_for_completion: bool = True,
        parent_run_id: Optional[str] = None,
    ) -> Union[AgentRun, AgentOutput]:
        """
        Spawn a sub-agent with inherited budget.

        Used by agents to delegate subtasks.
        """
        # Find parent budget
        parent_budget = None
        if parent_run_id and parent_run_id in self._active_runs:
            parent_run = self._active_runs[parent_run_id]
            parent_budget = parent_run.budget_allocated

            # Update parent's sub-agent count
            remaining_budget = AgentBudget(
                max_tokens=parent_budget.max_tokens - parent_budget.tokens_used,
                max_cost=parent_budget.max_cost - parent_budget.cost_incurred,
                max_tool_calls=parent_budget.max_tool_calls - parent_budget.tool_calls_made,
                max_sub_agents=parent_budget.max_sub_agents - 1,
            )

            # Check if parent can spawn more sub-agents
            if remaining_budget.max_sub_agents < 0:
                raise BudgetExhaustedException("Parent agent has exhausted sub-agent budget")

            # Calculate sub-agent budget
            sub_budget = AgentBudget(
                max_tokens=int(remaining_budget.max_tokens * budget_fraction),
                max_cost=remaining_budget.max_cost * budget_fraction,
                max_tool_calls=int(remaining_budget.max_tool_calls * budget_fraction),
                max_sub_agents=max(0, remaining_budget.max_sub_agents - 1),
                max_wallclock=int(remaining_budget.max_wallclock * budget_fraction),
            )
        else:
            # Default sub-agent budget
            sub_budget = AgentBudget(
                max_tokens=25000,
                max_cost=2.5,
                max_tool_calls=25,
                max_sub_agents=1,
                max_wallclock=900,
            )

        return await self.spawn_agent(
            agent_type=agent_type,
            goal=goal,
            inputs=inputs,
            budget=sub_budget,
            parent_run_id=parent_run_id,
            wait_for_completion=wait_for_completion,
        )

    async def _execute_agent(self, run: AgentRun, agent: Agent) -> AgentOutput:
        """Execute an agent with full lifecycle management."""
        run.status = AgentRunStatus.RUNNING
        run.started_at = datetime.utcnow()

        try:
            # Start budget monitor
            monitor_task = asyncio.create_task(
                self._monitor_budget(run, agent)
            )

            # Run the agent
            output = await agent.run()

            # Cancel monitor
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            # Record completion
            run.completed_at = datetime.utcnow()
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
            run.status = AgentRunStatus.COMPLETED if output.success else AgentRunStatus.FAILED
            run.stop_condition = output.stop_condition

            # Record budget usage
            run.budget_used = {
                "tokens": agent.config.budget.tokens_used,
                "cost": agent.config.budget.cost_incurred,
                "tool_calls": agent.config.budget.tool_calls_made,
                "sub_agents": agent.config.budget.sub_agents_spawned,
            }

            # Process outputs
            await self._process_outputs(run, output)

            # Archive run
            await self._archive_run(run)

            return output

        except BudgetExhaustedException as e:
            run.status = AgentRunStatus.BUDGET_EXHAUSTED
            run.error_message = str(e)
            run.completed_at = datetime.utcnow()
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()

            return AgentOutput(
                success=False,
                stop_condition=StopCondition.BUDGET_EXHAUSTED,
                error_message=str(e),
            )

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.error_message = str(e)
            run.completed_at = datetime.utcnow()
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()

            return AgentOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
            )

        finally:
            # Cleanup
            if run.run_id in self._running_agents:
                del self._running_agents[run.run_id]

    async def _monitor_budget(self, run: AgentRun, agent: Agent) -> None:
        """Monitor agent budget and kill if exceeded."""
        while True:
            await asyncio.sleep(5)  # Check every 5 seconds

            # Check budget
            is_ok, violation = agent.config.budget.check_budget()
            if not is_ok:
                # Kill the agent
                agent.request_stop()
                run.status = AgentRunStatus.BUDGET_EXHAUSTED
                run.error_message = violation
                break

    async def _process_outputs(self, run: AgentRun, output: AgentOutput) -> None:
        """Process agent outputs - route to review queue, record artifacts."""
        agent = self._running_agents.get(run.run_id)
        review_policy = agent.config.review_policy if agent else ReviewPolicy.HUMAN_REVIEW

        # Process artifacts
        for artifact in output.artifacts:
            run.output_artifacts.append(artifact.id)

            # Route based on policy
            if review_policy == ReviewPolicy.AUTO_PUBLISH:
                await self._publish_artifact(artifact)
            else:
                await self._queue_for_review(run, artifact_id=artifact.id)

        # Process flags
        for flag in output.flags:
            run.output_flags.append(flag.id)

            # Flags always go to review
            await self._queue_for_review(run, flag_id=flag.id, priority=self._flag_priority(flag))

        # Store structured result
        run.structured_result = output.structured_result

    async def _publish_artifact(self, artifact: Any) -> None:
        """Publish an artifact directly (auto-publish policy)."""
        # In production, this would update the database
        pass

    async def _queue_for_review(
        self,
        run: AgentRun,
        artifact_id: Optional[str] = None,
        flag_id: Optional[str] = None,
        priority: int = 0,
    ) -> None:
        """Add an item to the review queue."""
        item = ReviewQueueItem(
            run_id=run.run_id,
            agent_type=run.agent_type,
            artifact_id=artifact_id,
            flag_id=flag_id,
            priority=priority,
        )

        self._review_queue.append(item)

        # Sort by priority (higher first)
        self._review_queue.sort(key=lambda x: x.priority, reverse=True)

        # Persist if service available
        if self.review_service:
            await self.review_service.add_to_queue(item)

    def _flag_priority(self, flag: Any) -> int:
        """Determine priority for a flag based on severity."""
        severity_priorities = {
            "critical": 100,
            "alert": 75,
            "warning": 50,
            "info": 25,
        }
        return severity_priorities.get(flag.severity, 0)

    async def _archive_run(self, run: AgentRun) -> None:
        """Archive a completed run for audit purposes."""
        # Remove from active
        if run.run_id in self._active_runs:
            del self._active_runs[run.run_id]

        # Add to history
        self._run_history.append(run)

        # Persist if service available
        if self.persistence_service:
            await self.persistence_service.save_run(run)

    def _calculate_sub_budget(self, parent_budget: AgentBudget) -> AgentBudget:
        """Calculate budget for a sub-agent."""
        remaining_tokens = parent_budget.max_tokens - parent_budget.tokens_used
        remaining_cost = parent_budget.max_cost - parent_budget.cost_incurred
        remaining_calls = parent_budget.max_tool_calls - parent_budget.tool_calls_made

        # Sub-agents get 25% of remaining budget by default
        return AgentBudget(
            max_tokens=int(remaining_tokens * 0.25),
            max_cost=remaining_cost * 0.25,
            max_tool_calls=int(remaining_calls * 0.25),
            max_sub_agents=max(0, parent_budget.max_sub_agents - 1),
            max_wallclock=int(parent_budget.max_wallclock * 0.25),
            max_recursion_depth=parent_budget.max_recursion_depth,
        )

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running agent."""
        if run_id not in self._active_runs:
            return False

        run = self._active_runs[run_id]
        agent = self._running_agents.get(run_id)

        if agent:
            agent.request_stop()

        run.status = AgentRunStatus.CANCELLED
        run.completed_at = datetime.utcnow()
        run.duration_seconds = (run.completed_at - run.started_at).total_seconds()

        return True

    async def retry_from_checkpoint(
        self,
        run_id: str,
        checkpoint_label: str,
    ) -> Optional[AgentRun]:
        """Retry a failed run from a checkpoint."""
        # Find the original run
        original_run = None
        for run in self._run_history:
            if run.run_id == run_id:
                original_run = run
                break

        if not original_run or not original_run.checkpoints:
            return None

        # Find checkpoint
        checkpoint = None
        for cp in original_run.checkpoints:
            if cp.get("label") == checkpoint_label:
                checkpoint = cp
                break

        if not checkpoint:
            return None

        # Restore agent state and respawn
        # This would need to restore the full agent state from persistence
        # For now, we'll create a new run with similar parameters

        return await self.spawn_agent(
            agent_type=original_run.agent_type,
            goal=checkpoint.get("goal", ""),
            inputs=checkpoint.get("inputs", {}),
            budget=original_run.budget_allocated,
        )

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        """Get a run by ID."""
        if run_id in self._active_runs:
            return self._active_runs[run_id]

        for run in self._run_history:
            if run.run_id == run_id:
                return run

        return None

    def get_active_runs(self) -> List[AgentRun]:
        """Get all active runs."""
        return list(self._active_runs.values())

    def get_review_queue(self) -> List[ReviewQueueItem]:
        """Get the current review queue."""
        return self._review_queue.copy()

    async def process_review(
        self,
        item_id: str,
        approved: bool,
        reviewer_notes: Optional[str] = None,
    ) -> bool:
        """Process a review decision."""
        for item in self._review_queue:
            if item.id == item_id:
                item.status = "approved" if approved else "rejected"

                # If approved, publish
                if approved and item.artifact_id:
                    # Fetch and publish artifact
                    pass

                # Remove from queue
                self._review_queue.remove(item)
                return True

        return False

    def get_cost_summary(
        self,
        since: Optional[datetime] = None,
        agent_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get cost summary for runs."""
        runs = self._run_history
        if since:
            runs = [r for r in runs if r.started_at >= since]
        if agent_type:
            runs = [r for r in runs if r.agent_type == agent_type]

        total_cost = sum(r.budget_used.get("cost", 0) for r in runs)
        total_tokens = sum(r.budget_used.get("tokens", 0) for r in runs)
        total_duration = sum(r.duration_seconds for r in runs)

        by_type: Dict[str, Dict[str, Any]] = {}
        for run in runs:
            if run.agent_type not in by_type:
                by_type[run.agent_type] = {
                    "runs": 0,
                    "cost": 0.0,
                    "tokens": 0,
                    "duration": 0.0,
                }
            by_type[run.agent_type]["runs"] += 1
            by_type[run.agent_type]["cost"] += run.budget_used.get("cost", 0)
            by_type[run.agent_type]["tokens"] += run.budget_used.get("tokens", 0)
            by_type[run.agent_type]["duration"] += run.duration_seconds

        return {
            "total_runs": len(runs),
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "total_duration_seconds": total_duration,
            "by_agent_type": by_type,
        }


class RecursionDepthExceeded(Exception):
    """Raised when recursive agent spawning exceeds the limit."""
    pass
