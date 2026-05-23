"""
Temporal Workflow Definitions

Durable workflows for agent execution with retry, checkpointing,
and scheduling support.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

# Activity input/output types
@dataclass
class SentinelActivityInput:
    """Input for Sentinel agent activity."""
    subject_id: str
    lookback_days: int = 30
    sensitivity: float = 1.5


@dataclass
class SentinelActivityOutput:
    """Output from Sentinel agent activity."""
    success: bool
    items_reviewed: int
    flags_emitted: int
    error_message: Optional[str] = None


@dataclass
class NarrativeTrackerActivityInput:
    """Input for Narrative Tracker agent activity."""
    narrative_id: str
    subject_id: Optional[str] = None
    velocity_threshold: float = 2.0


@dataclass
class NarrativeTrackerActivityOutput:
    """Output from Narrative Tracker agent activity."""
    success: bool
    lifecycle_stage: str
    prevalence_score: float
    lifecycle_changed: bool
    spike_detected: bool
    error_message: Optional[str] = None


@dataclass
class InvestigatorActivityInput:
    """Input for Investigator agent activity."""
    question: str
    search_web: bool = False
    max_leads: int = 10
    context: Optional[Dict[str, Any]] = None


@dataclass
class InvestigatorActivityOutput:
    """Output from Investigator agent activity."""
    success: bool
    evidence_count: int
    confidence: float
    summary: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class SynthesizerActivityInput:
    """Input for Synthesizer agent activity."""
    artifact_type: str
    topic: str
    scope: Optional[Dict[str, Any]] = None
    tonal_variants: Optional[List[str]] = None
    min_citations: int = 5


@dataclass
class SynthesizerActivityOutput:
    """Output from Synthesizer agent activity."""
    success: bool
    artifact_id: Optional[str] = None
    citation_count: int = 0
    citation_coverage: float = 0.0
    variant_ids: Optional[List[str]] = None
    error_message: Optional[str] = None


@dataclass
class GraphCuratorActivityInput:
    """Input for Graph Curator agent activity."""
    similarity_threshold: float = 0.85
    stale_days: int = 90
    batch_size: int = 100


@dataclass
class GraphCuratorActivityOutput:
    """Output from Graph Curator agent activity."""
    success: bool
    entities_processed: int
    merges_executed: int
    stale_links_pruned: int
    error_message: Optional[str] = None


# Activities
@activity.defn
async def run_sentinel_agent(input: SentinelActivityInput) -> SentinelActivityOutput:
    """Activity that runs the Sentinel agent."""
    from .sentinel import SentinelAgent, SentinelConfig
    from .base import AgentBudget
    import anthropic

    try:
        config = SentinelConfig(
            agent_type="sentinel",
            goal=f"Monitor Subject {input.subject_id} for today's changes",
            subject_id=input.subject_id,
            lookback_days=input.lookback_days,
            sensitivity=input.sensitivity,
            budget=AgentBudget(
                max_tokens=50000,
                max_cost=5.0,
                max_wallclock=1800,
            ),
        )

        client = anthropic.AsyncAnthropic()
        agent = SentinelAgent(config=config, client=client)

        # Send heartbeats during execution
        async def heartbeat_task():
            while True:
                await asyncio.sleep(30)
                activity.heartbeat()

        heartbeat = asyncio.create_task(heartbeat_task())

        try:
            output = await agent.run()
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

        return SentinelActivityOutput(
            success=output.success,
            items_reviewed=output.items_reviewed,
            flags_emitted=len(output.flags),
            error_message=output.error_message,
        )

    except Exception as e:
        return SentinelActivityOutput(
            success=False,
            items_reviewed=0,
            flags_emitted=0,
            error_message=str(e),
        )


@activity.defn
async def run_narrative_tracker_agent(
    input: NarrativeTrackerActivityInput,
) -> NarrativeTrackerActivityOutput:
    """Activity that runs the Narrative Tracker agent."""
    from .narrative_tracker import NarrativeTrackerAgent, NarrativeTrackerConfig
    from .base import AgentBudget
    import anthropic

    try:
        config = NarrativeTrackerConfig(
            agent_type="narrative_tracker",
            goal=f"Track Narrative {input.narrative_id}",
            narrative_id=input.narrative_id,
            subject_id=input.subject_id,
            velocity_threshold=input.velocity_threshold,
            budget=AgentBudget(
                max_tokens=30000,
                max_cost=3.0,
                max_wallclock=1200,
            ),
        )

        client = anthropic.AsyncAnthropic()
        agent = NarrativeTrackerAgent(config=config, client=client)

        output = await agent.run()

        return NarrativeTrackerActivityOutput(
            success=output.success,
            lifecycle_stage=output.lifecycle_stage.value,
            prevalence_score=output.prevalence_score,
            lifecycle_changed=output.lifecycle_changed,
            spike_detected=output.spike_detected,
            error_message=output.error_message,
        )

    except Exception as e:
        return NarrativeTrackerActivityOutput(
            success=False,
            lifecycle_stage="unknown",
            prevalence_score=0.0,
            lifecycle_changed=False,
            spike_detected=False,
            error_message=str(e),
        )


@activity.defn
async def run_investigator_agent(
    input: InvestigatorActivityInput,
) -> InvestigatorActivityOutput:
    """Activity that runs the Investigator agent."""
    from .investigator import InvestigatorAgent, InvestigatorConfig
    from .base import AgentBudget
    import anthropic

    try:
        config = InvestigatorConfig(
            agent_type="investigator",
            goal=f"Investigate: {input.question}",
            question=input.question,
            search_web=input.search_web,
            max_leads=input.max_leads,
            context=input.context or {},
            budget=AgentBudget(
                max_tokens=80000,
                max_cost=8.0,
                max_wallclock=2400,
            ),
        )

        client = anthropic.AsyncAnthropic()
        agent = InvestigatorAgent(config=config, client=client)

        # Heartbeat for long-running investigations
        async def heartbeat_task():
            while True:
                await asyncio.sleep(30)
                activity.heartbeat()

        heartbeat = asyncio.create_task(heartbeat_task())

        try:
            output = await agent.run()
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

        summary = None
        if output.investigation_trail:
            summary = output.investigation_trail.summary

        return InvestigatorActivityOutput(
            success=output.success,
            evidence_count=output.evidence_count,
            confidence=output.confidence,
            summary=summary,
            error_message=output.error_message,
        )

    except Exception as e:
        return InvestigatorActivityOutput(
            success=False,
            evidence_count=0,
            confidence=0.0,
            error_message=str(e),
        )


@activity.defn
async def run_synthesizer_agent(
    input: SynthesizerActivityInput,
) -> SynthesizerActivityOutput:
    """Activity that runs the Synthesizer agent."""
    from .synthesizer import SynthesizerAgent, SynthesizerConfig, ArtifactType, TonalVariant
    from .base import AgentBudget
    import anthropic

    try:
        # Parse artifact type and tonal variants
        artifact_type = ArtifactType(input.artifact_type)
        tonal_variants = [TonalVariant(t) for t in (input.tonal_variants or ["neutral"])]

        config = SynthesizerConfig(
            agent_type="synthesizer",
            goal=f"Synthesize {input.artifact_type}: {input.topic}",
            artifact_type=artifact_type,
            topic=input.topic,
            scope=input.scope or {},
            tonal_variants=tonal_variants,
            min_citations=input.min_citations,
            budget=AgentBudget(
                max_tokens=60000,
                max_cost=6.0,
                max_wallclock=1800,
            ),
        )

        client = anthropic.AsyncAnthropic()
        agent = SynthesizerAgent(config=config, client=client)

        output = await agent.run()

        artifact_id = None
        if output.primary_artifact:
            artifact_id = output.primary_artifact.id

        variant_ids = []
        for variant in output.tonal_variants.values():
            variant_ids.append(variant.id)

        return SynthesizerActivityOutput(
            success=output.success,
            artifact_id=artifact_id,
            citation_count=output.citation_count,
            citation_coverage=output.citation_coverage,
            variant_ids=variant_ids if variant_ids else None,
            error_message=output.error_message,
        )

    except Exception as e:
        return SynthesizerActivityOutput(
            success=False,
            error_message=str(e),
        )


@activity.defn
async def run_graph_curator_agent(
    input: GraphCuratorActivityInput,
) -> GraphCuratorActivityOutput:
    """Activity that runs the Graph Curator agent."""
    from .graph_curator import GraphCuratorAgent, GraphCuratorConfig
    from .base import AgentBudget
    import anthropic

    try:
        config = GraphCuratorConfig(
            agent_type="graph_curator",
            goal="Curate and maintain knowledge graph quality",
            similarity_threshold=input.similarity_threshold,
            stale_days=input.stale_days,
            batch_size=input.batch_size,
            budget=AgentBudget(
                max_tokens=100000,
                max_cost=10.0,
                max_wallclock=3600,
            ),
        )

        client = anthropic.AsyncAnthropic()
        agent = GraphCuratorAgent(config=config, client=client)

        output = await agent.run()

        return GraphCuratorActivityOutput(
            success=output.success,
            entities_processed=output.entities_processed,
            merges_executed=output.merges_executed,
            stale_links_pruned=output.stale_links_pruned,
            error_message=output.error_message,
        )

    except Exception as e:
        return GraphCuratorActivityOutput(
            success=False,
            entities_processed=0,
            merges_executed=0,
            stale_links_pruned=0,
            error_message=str(e),
        )


@activity.defn
async def get_subjects_for_sentinel() -> List[str]:
    """Get list of subject IDs that need Sentinel runs."""
    # In production, this would query the database
    # For now, return empty list
    return []


@activity.defn
async def get_active_narratives() -> List[Dict[str, Any]]:
    """Get list of active narratives that need tracking."""
    # In production, this would query the database
    return []


@activity.defn
async def notify_on_failure(
    workflow_type: str,
    entity_id: str,
    error_message: str,
) -> None:
    """Send notification on workflow failure."""
    # In production, this would send alerts via email/Slack/etc.
    pass


# Workflows
@workflow.defn
class DailySentinelWorkflow:
    """
    Daily workflow that runs Sentinel agents for all subjects.

    Runs after the daily collection sweep to review new items.
    """

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """Execute the daily sentinel sweep."""
        results = {
            "started_at": workflow.now().isoformat(),
            "subjects_processed": 0,
            "total_items_reviewed": 0,
            "total_flags_emitted": 0,
            "failures": [],
        }

        # Get subjects to process
        subject_ids = await workflow.execute_activity(
            get_subjects_for_sentinel,
            start_to_close_timeout=timedelta(minutes=5),
        )

        # Run sentinel for each subject
        for subject_id in subject_ids:
            try:
                output = await workflow.execute_activity(
                    run_sentinel_agent,
                    SentinelActivityInput(subject_id=subject_id),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(minutes=5),
                        maximum_attempts=3,
                    ),
                )

                if output.success:
                    results["subjects_processed"] += 1
                    results["total_items_reviewed"] += output.items_reviewed
                    results["total_flags_emitted"] += output.flags_emitted
                else:
                    results["failures"].append({
                        "subject_id": subject_id,
                        "error": output.error_message,
                    })

            except Exception as e:
                results["failures"].append({
                    "subject_id": subject_id,
                    "error": str(e),
                })

                # Notify on failure
                await workflow.execute_activity(
                    notify_on_failure,
                    args=["sentinel", subject_id, str(e)],
                    start_to_close_timeout=timedelta(minutes=1),
                )

        results["completed_at"] = workflow.now().isoformat()
        return results


@workflow.defn
class NarrativeTrackerWorkflow:
    """
    Workflow that tracks narratives on a schedule.

    Can be triggered periodically or on-demand.
    """

    @workflow.run
    async def run(
        self,
        narrative_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute narrative tracking."""
        results = {
            "started_at": workflow.now().isoformat(),
            "narratives_processed": 0,
            "lifecycle_changes": 0,
            "spikes_detected": 0,
            "failures": [],
        }

        if narrative_id:
            # Track specific narrative
            narratives = [{"id": narrative_id}]
        else:
            # Get all active narratives
            narratives = await workflow.execute_activity(
                get_active_narratives,
                start_to_close_timeout=timedelta(minutes=5),
            )

        for narrative in narratives:
            try:
                output = await workflow.execute_activity(
                    run_narrative_tracker_agent,
                    NarrativeTrackerActivityInput(
                        narrative_id=narrative["id"],
                        subject_id=narrative.get("subject_id"),
                    ),
                    start_to_close_timeout=timedelta(minutes=20),
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                    ),
                )

                if output.success:
                    results["narratives_processed"] += 1
                    if output.lifecycle_changed:
                        results["lifecycle_changes"] += 1
                    if output.spike_detected:
                        results["spikes_detected"] += 1
                else:
                    results["failures"].append({
                        "narrative_id": narrative["id"],
                        "error": output.error_message,
                    })

            except Exception as e:
                results["failures"].append({
                    "narrative_id": narrative["id"],
                    "error": str(e),
                })

        results["completed_at"] = workflow.now().isoformat()
        return results


@workflow.defn
class InvestigatorWorkflow:
    """
    Workflow for running an investigation.

    Supports long-running investigations with checkpointing.
    """

    @workflow.run
    async def run(
        self,
        question: str,
        search_web: bool = False,
        max_leads: int = 10,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an investigation."""
        results = {
            "started_at": workflow.now().isoformat(),
            "question": question,
            "success": False,
            "evidence_count": 0,
            "confidence": 0.0,
            "summary": None,
            "error": None,
        }

        try:
            output = await workflow.execute_activity(
                run_investigator_agent,
                InvestigatorActivityInput(
                    question=question,
                    search_web=search_web,
                    max_leads=max_leads,
                    context=context,
                ),
                start_to_close_timeout=timedelta(minutes=45),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=30),
                    maximum_interval=timedelta(minutes=10),
                    maximum_attempts=2,
                ),
            )

            results["success"] = output.success
            results["evidence_count"] = output.evidence_count
            results["confidence"] = output.confidence
            results["summary"] = output.summary
            results["error"] = output.error_message

        except Exception as e:
            results["error"] = str(e)

            # Notify on failure
            await workflow.execute_activity(
                notify_on_failure,
                args=["investigator", question[:50], str(e)],
                start_to_close_timeout=timedelta(minutes=1),
            )

        results["completed_at"] = workflow.now().isoformat()
        return results


@workflow.defn
class SynthesizerWorkflow:
    """
    Workflow for synthesizing artifacts.

    Produces reports, memos, timelines, and other artifacts.
    """

    @workflow.run
    async def run(
        self,
        artifact_type: str,
        topic: str,
        scope: Optional[Dict[str, Any]] = None,
        tonal_variants: Optional[List[str]] = None,
        min_citations: int = 5,
    ) -> Dict[str, Any]:
        """Execute artifact synthesis."""
        results = {
            "started_at": workflow.now().isoformat(),
            "artifact_type": artifact_type,
            "topic": topic,
            "success": False,
            "artifact_id": None,
            "citation_count": 0,
            "citation_coverage": 0.0,
            "variant_ids": [],
            "error": None,
        }

        try:
            output = await workflow.execute_activity(
                run_synthesizer_agent,
                SynthesizerActivityInput(
                    artifact_type=artifact_type,
                    topic=topic,
                    scope=scope,
                    tonal_variants=tonal_variants,
                    min_citations=min_citations,
                ),
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(
                    maximum_attempts=2,
                ),
            )

            results["success"] = output.success
            results["artifact_id"] = output.artifact_id
            results["citation_count"] = output.citation_count
            results["citation_coverage"] = output.citation_coverage
            results["variant_ids"] = output.variant_ids or []
            results["error"] = output.error_message

        except Exception as e:
            results["error"] = str(e)

        results["completed_at"] = workflow.now().isoformat()
        return results


@workflow.defn
class GraphCuratorWorkflow:
    """
    Workflow for graph curation tasks.

    Runs periodically to maintain graph quality.
    """

    @workflow.run
    async def run(
        self,
        similarity_threshold: float = 0.85,
        stale_days: int = 90,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """Execute graph curation."""
        results = {
            "started_at": workflow.now().isoformat(),
            "success": False,
            "entities_processed": 0,
            "merges_executed": 0,
            "stale_links_pruned": 0,
            "error": None,
        }

        try:
            output = await workflow.execute_activity(
                run_graph_curator_agent,
                GraphCuratorActivityInput(
                    similarity_threshold=similarity_threshold,
                    stale_days=stale_days,
                    batch_size=batch_size,
                ),
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=2,
                ),
            )

            results["success"] = output.success
            results["entities_processed"] = output.entities_processed
            results["merges_executed"] = output.merges_executed
            results["stale_links_pruned"] = output.stale_links_pruned
            results["error"] = output.error_message

        except Exception as e:
            results["error"] = str(e)

            await workflow.execute_activity(
                notify_on_failure,
                args=["graph_curator", "global", str(e)],
                start_to_close_timeout=timedelta(minutes=1),
            )

        results["completed_at"] = workflow.now().isoformat()
        return results


# Worker setup helper
def get_workflow_classes() -> List[type]:
    """Get all workflow classes for worker registration."""
    return [
        DailySentinelWorkflow,
        NarrativeTrackerWorkflow,
        InvestigatorWorkflow,
        SynthesizerWorkflow,
        GraphCuratorWorkflow,
    ]


def get_activity_functions() -> List:
    """Get all activity functions for worker registration."""
    return [
        run_sentinel_agent,
        run_narrative_tracker_agent,
        run_investigator_agent,
        run_synthesizer_agent,
        run_graph_curator_agent,
        get_subjects_for_sentinel,
        get_active_narratives,
        notify_on_failure,
    ]
