"""
Narrative Tracker Standing Agent

A standing agent that monitors individual narratives, tracking their
lifecycle, prevalence, and amplifiers.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import anthropic
from pydantic import BaseModel, Field

from .base import (
    AgentConfig,
    AgentMemory,
    AgentOutput,
    Flag,
    ReviewPolicy,
    StandingAgent,
    StopCondition,
)
from .tools import tool_catalog


class NarrativeLifecycle(str, Enum):
    """Lifecycle stages of a narrative."""
    EMERGING = "emerging"
    RISING = "rising"
    PEAK = "peak"
    DECLINING = "declining"
    DORMANT = "dormant"


class AmplifierInfo(BaseModel):
    """Information about an entity amplifying a narrative."""
    entity_id: str
    entity_name: str
    entity_type: str
    mention_count: int = 0
    reach_score: float = 0.0
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class NarrativeMetrics(BaseModel):
    """Current metrics for a narrative."""
    narrative_id: str
    computed_at: datetime = Field(default_factory=datetime.utcnow)

    # Lifecycle
    lifecycle_stage: NarrativeLifecycle = NarrativeLifecycle.EMERGING
    lifecycle_confidence: float = 0.0

    # Prevalence
    prevalence_score: float = 0.0
    raw_mention_count: int = 0
    weighted_mention_count: float = 0.0

    # Velocity
    velocity: float = 0.0  # Change rate
    acceleration: float = 0.0  # Change in velocity

    # Historical
    daily_counts: List[Dict[str, Any]] = Field(default_factory=list)
    peak_date: Optional[datetime] = None
    peak_prevalence: float = 0.0

    # Amplifiers
    amplifiers: List[AmplifierInfo] = Field(default_factory=list)
    top_sources: List[Dict[str, Any]] = Field(default_factory=list)


class NarrativeTrackerConfig(AgentConfig):
    """Configuration specific to Narrative Tracker agent."""
    agent_type: str = "narrative_tracker"
    narrative_id: str = Field(..., description="Narrative to track")
    subject_id: Optional[str] = Field(default=None, description="Associated subject")
    velocity_threshold: float = Field(default=2.0, description="Threshold for velocity spike alerts")
    amplifier_threshold: int = Field(default=3, description="Min mentions to be considered amplifier")


class NarrativeTrackerOutput(AgentOutput):
    """Output specific to Narrative Tracker agent."""
    lifecycle_stage: NarrativeLifecycle = NarrativeLifecycle.EMERGING
    prevalence_score: float = 0.0
    lifecycle_changed: bool = False
    spike_detected: bool = False
    new_amplifiers: List[str] = Field(default_factory=list)


class NarrativeTrackerAgent(StandingAgent[NarrativeTrackerOutput]):
    """
    Narrative Tracker standing agent for monitoring individual narratives.

    Runs periodically to:
    - Update narrative lifecycle (emerging -> rising -> peak -> declining -> dormant)
    - Calculate prevalence score weighted by source reach/reliability
    - Track and update amplifier list
    - Detect unexpected spikes and spawn investigators
    """

    def __init__(
        self,
        config: NarrativeTrackerConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.tracker_config = config
        self.metrics: Optional[NarrativeMetrics] = None

        # Register tools
        for tool_name in ["corpus_search", "graph_query", "emit_flag", "sub_agent_spawn"]:
            tool = tool_catalog.get(tool_name)
            if tool:
                self.register_tool(tool_name, tool)

    @property
    def narrative_id(self) -> str:
        return self.tracker_config.narrative_id

    def get_system_prompt(self) -> str:
        return f"""You are a Narrative Tracker agent monitoring Narrative {self.narrative_id} for the Lantern Narrative Intelligence Platform.

Your role is to:
1. Track the narrative's lifecycle stage (emerging, rising, peak, declining, dormant)
2. Calculate prevalence score weighted by source reach and reliability
3. Identify and track amplifiers (entities spreading the narrative)
4. Detect unexpected spikes or changes in narrative spread
5. Spawn investigators for unusual patterns

You have access to the following tools:
- corpus_search: Search for items mentioning or related to this narrative
- graph_query: Query the narrative's spread through the entity graph
- emit_flag: Emit flags for lifecycle changes or unusual patterns
- sub_agent_spawn: Spawn an investigator agent for deep analysis

Lifecycle Stage Criteria:
- EMERGING: New narrative, low prevalence, few sources
- RISING: Growing prevalence, increasing velocity, expanding source diversity
- PEAK: Maximum or near-maximum prevalence, velocity approaching zero
- DECLINING: Decreasing prevalence, negative velocity
- DORMANT: Very low prevalence, no significant activity

Consider source reliability and reach when calculating prevalence:
- Mainstream news outlets have higher reach
- Primary sources have higher reliability
- Social media has varying reach based on following

Current metrics:
{self._format_metrics()}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}
"""

    def _format_metrics(self) -> str:
        """Format current metrics for system prompt."""
        if not self.metrics:
            return "No metrics established yet - this may be a new narrative."

        return f"""
- Lifecycle: {self.metrics.lifecycle_stage.value} (confidence: {self.metrics.lifecycle_confidence:.0%})
- Prevalence Score: {self.metrics.prevalence_score:.2f}
- Raw Mentions: {self.metrics.raw_mention_count}
- Velocity: {self.metrics.velocity:+.2f}
- Top Amplifiers: {len(self.metrics.amplifiers)}
- Peak Date: {self.metrics.peak_date.strftime('%Y-%m-%d') if self.metrics.peak_date else 'Not yet reached'}
"""

    async def execute(self) -> NarrativeTrackerOutput:
        """Execute the narrative tracking update."""
        flags_emitted: List[Flag] = []
        lifecycle_changed = False
        spike_detected = False
        new_amplifiers: List[str] = []

        try:
            # Load existing metrics
            await self._load_metrics()

            # Step 1: Search for recent narrative mentions
            recent_items = await self._fetch_recent_mentions()
            self.memory.working_memory["recent_items"] = recent_items

            # Step 2: Query graph for spread patterns
            spread_data = await self._query_narrative_spread()
            self.memory.working_memory["spread_data"] = spread_data

            # Step 3: Calculate new metrics
            new_metrics = await self._calculate_metrics(recent_items, spread_data)

            # Step 4: Detect lifecycle changes
            old_lifecycle = self.metrics.lifecycle_stage if self.metrics else None
            new_lifecycle = self._determine_lifecycle(new_metrics)
            new_metrics.lifecycle_stage = new_lifecycle

            if old_lifecycle and old_lifecycle != new_lifecycle:
                lifecycle_changed = True
                flag = await self._emit_lifecycle_change_flag(old_lifecycle, new_lifecycle)
                if flag:
                    flags_emitted.append(flag)

            # Step 5: Detect velocity spikes
            if self.metrics and self.metrics.velocity > 0:
                velocity_ratio = new_metrics.velocity / max(self.metrics.velocity, 0.1)
                if velocity_ratio > self.tracker_config.velocity_threshold:
                    spike_detected = True
                    flag = await self._handle_velocity_spike(velocity_ratio)
                    if flag:
                        flags_emitted.append(flag)

            # Step 6: Update amplifier list
            old_amplifier_ids = {a.entity_id for a in (self.metrics.amplifiers if self.metrics else [])}
            new_amplifier_ids = {a.entity_id for a in new_metrics.amplifiers}
            new_amplifiers = list(new_amplifier_ids - old_amplifier_ids)

            if len(new_amplifiers) >= 5:
                flag = await self._emit_new_amplifiers_flag(new_amplifiers)
                if flag:
                    flags_emitted.append(flag)

            # Step 7: Save updated metrics
            self.metrics = new_metrics
            await self._save_metrics()

            return NarrativeTrackerOutput(
                success=True,
                stop_condition=StopCondition.GOAL_MET,
                flags=flags_emitted,
                lifecycle_stage=new_lifecycle,
                prevalence_score=new_metrics.prevalence_score,
                lifecycle_changed=lifecycle_changed,
                spike_detected=spike_detected,
                new_amplifiers=new_amplifiers,
                execution_summary={
                    "agent_id": self.agent_id,
                    "narrative_id": self.narrative_id,
                    "items_analyzed": len(recent_items),
                    "flags_emitted": len(flags_emitted),
                    "budget_used": {
                        "tokens": self.config.budget.tokens_used,
                        "cost": self.config.budget.cost_incurred,
                    },
                },
            )

        except Exception as e:
            return NarrativeTrackerOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
                flags=flags_emitted,
                lifecycle_stage=self.metrics.lifecycle_stage if self.metrics else NarrativeLifecycle.EMERGING,
                prevalence_score=self.metrics.prevalence_score if self.metrics else 0.0,
            )

    async def _fetch_recent_mentions(self) -> List[Dict[str, Any]]:
        """Fetch recent items mentioning this narrative."""
        corpus_tool = self._tools.get("corpus_search")
        if not corpus_tool:
            return []

        # Search for items in the last 24 hours
        today = datetime.utcnow()
        yesterday = today - timedelta(days=1)

        result = await corpus_tool.execute(
            query=f"narrative:{self.narrative_id}",
            date_from=yesterday.isoformat(),
            date_to=today.isoformat(),
            limit=100,
        )

        if result.success:
            return result.data.get("items", [])
        return []

    async def _query_narrative_spread(self) -> Dict[str, Any]:
        """Query the graph for narrative spread patterns."""
        graph_tool = self._tools.get("graph_query")
        if not graph_tool:
            return {}

        result = await graph_tool.execute(
            query_type="narrative_spread",
            entity_id=self.narrative_id,
            depth=3,
            limit=100,
        )

        if result.success:
            return result.data
        return {}

    async def _calculate_metrics(
        self,
        recent_items: List[Dict[str, Any]],
        spread_data: Dict[str, Any],
    ) -> NarrativeMetrics:
        """Calculate updated narrative metrics."""
        metrics = NarrativeMetrics(
            narrative_id=self.narrative_id,
            computed_at=datetime.utcnow(),
        )

        # Raw mention count
        metrics.raw_mention_count = len(recent_items)

        # Calculate weighted mentions based on source reach
        weighted_sum = 0.0
        source_counts: Dict[str, int] = {}
        entity_mentions: Dict[str, Dict[str, Any]] = {}

        for item in recent_items:
            source = item.get("source", {})
            source_id = source.get("id", "unknown")
            source_reach = source.get("reach_score", 1.0)
            source_reliability = source.get("reliability_score", 1.0)

            # Weight by reach and reliability
            weight = source_reach * source_reliability
            weighted_sum += weight

            # Track source distribution
            source_counts[source_id] = source_counts.get(source_id, 0) + 1

            # Track entity mentions (potential amplifiers)
            for entity in item.get("entities", []):
                entity_id = entity.get("id", entity.get("name", ""))
                if entity_id:
                    if entity_id not in entity_mentions:
                        entity_mentions[entity_id] = {
                            "name": entity.get("name", entity_id),
                            "type": entity.get("type", "unknown"),
                            "count": 0,
                            "reach": 0.0,
                            "first_seen": datetime.utcnow(),
                            "last_seen": datetime.utcnow(),
                        }
                    entity_mentions[entity_id]["count"] += 1
                    entity_mentions[entity_id]["reach"] += source_reach
                    entity_mentions[entity_id]["last_seen"] = datetime.utcnow()

        metrics.weighted_mention_count = weighted_sum

        # Calculate prevalence score (0-100 scale)
        # This would typically involve comparing to overall corpus volume
        max_expected_daily = 1000  # Calibrate based on corpus size
        metrics.prevalence_score = min(100.0, (weighted_sum / max_expected_daily) * 100)

        # Calculate velocity (change from previous)
        if self.metrics:
            metrics.velocity = metrics.prevalence_score - self.metrics.prevalence_score
            metrics.acceleration = metrics.velocity - self.metrics.velocity

            # Update peak tracking
            if metrics.prevalence_score > self.metrics.peak_prevalence:
                metrics.peak_prevalence = metrics.prevalence_score
                metrics.peak_date = datetime.utcnow()
            else:
                metrics.peak_prevalence = self.metrics.peak_prevalence
                metrics.peak_date = self.metrics.peak_date

            # Maintain daily count history
            metrics.daily_counts = self.metrics.daily_counts[-30:] + [{
                "date": datetime.utcnow().date().isoformat(),
                "count": metrics.raw_mention_count,
                "prevalence": metrics.prevalence_score,
            }]
        else:
            metrics.daily_counts = [{
                "date": datetime.utcnow().date().isoformat(),
                "count": metrics.raw_mention_count,
                "prevalence": metrics.prevalence_score,
            }]

        # Build amplifier list
        threshold = self.tracker_config.amplifier_threshold
        for entity_id, data in entity_mentions.items():
            if data["count"] >= threshold:
                amplifier = AmplifierInfo(
                    entity_id=entity_id,
                    entity_name=data["name"],
                    entity_type=data["type"],
                    mention_count=data["count"],
                    reach_score=data["reach"],
                    first_seen=data["first_seen"],
                    last_seen=data["last_seen"],
                )
                metrics.amplifiers.append(amplifier)

        # Sort amplifiers by reach
        metrics.amplifiers.sort(key=lambda a: a.reach_score, reverse=True)
        metrics.amplifiers = metrics.amplifiers[:50]  # Top 50

        # Top sources
        metrics.top_sources = [
            {"source_id": k, "count": v}
            for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        ]

        return metrics

    def _determine_lifecycle(self, metrics: NarrativeMetrics) -> NarrativeLifecycle:
        """Determine lifecycle stage based on metrics."""
        # Use velocity, prevalence, and historical data to determine stage

        if len(metrics.daily_counts) < 3:
            # Not enough data - assume emerging
            return NarrativeLifecycle.EMERGING

        # Recent trend (last 3 days)
        recent_counts = metrics.daily_counts[-3:]
        recent_prevalences = [d["prevalence"] for d in recent_counts]
        avg_recent = sum(recent_prevalences) / len(recent_prevalences)

        # Velocity indicators
        is_growing = metrics.velocity > 1.0
        is_declining = metrics.velocity < -1.0
        is_stable = abs(metrics.velocity) <= 1.0

        # Prevalence indicators
        is_low = avg_recent < 10
        is_moderate = 10 <= avg_recent < 40
        is_high = avg_recent >= 40

        # Determine stage
        if is_low and is_growing:
            stage = NarrativeLifecycle.EMERGING
            confidence = 0.7
        elif is_growing and (is_moderate or is_high):
            stage = NarrativeLifecycle.RISING
            confidence = 0.8
        elif is_high and is_stable:
            stage = NarrativeLifecycle.PEAK
            confidence = 0.75
        elif is_declining:
            stage = NarrativeLifecycle.DECLINING
            confidence = 0.8
        elif is_low and is_stable:
            stage = NarrativeLifecycle.DORMANT
            confidence = 0.85
        else:
            # Default to current or emerging
            stage = self.metrics.lifecycle_stage if self.metrics else NarrativeLifecycle.EMERGING
            confidence = 0.5

        metrics.lifecycle_confidence = confidence
        return stage

    async def _emit_lifecycle_change_flag(
        self,
        old_stage: NarrativeLifecycle,
        new_stage: NarrativeLifecycle,
    ) -> Optional[Flag]:
        """Emit a flag for lifecycle stage change."""
        emit_tool = self._tools.get("emit_flag")
        if not emit_tool:
            return None

        severity = "info"
        if new_stage == NarrativeLifecycle.RISING:
            severity = "warning"
        elif new_stage == NarrativeLifecycle.PEAK:
            severity = "alert"

        result = await emit_tool.execute(
            flag_type="lifecycle_change",
            severity=severity,
            title=f"Narrative lifecycle: {old_stage.value} -> {new_stage.value}",
            description=f"Narrative {self.narrative_id} has transitioned from "
                        f"{old_stage.value} to {new_stage.value} stage. "
                        f"Current prevalence: {self.metrics.prevalence_score if self.metrics else 0:.1f}",
            evidence=[],
            narrative_id=self.narrative_id,
            subject_id=self.tracker_config.subject_id,
        )

        if result.success:
            return Flag(**result.data)
        return None

    async def _handle_velocity_spike(self, velocity_ratio: float) -> Optional[Flag]:
        """Handle a velocity spike - emit flag and potentially spawn investigator."""
        emit_tool = self._tools.get("emit_flag")
        spawn_tool = self._tools.get("sub_agent_spawn")

        severity = "alert" if velocity_ratio > 3.0 else "warning"

        # Emit flag
        flag = None
        if emit_tool:
            result = await emit_tool.execute(
                flag_type="velocity_spike",
                severity=severity,
                title=f"Narrative velocity spike: {velocity_ratio:.1f}x normal",
                description=f"Narrative {self.narrative_id} is spreading {velocity_ratio:.1f}x "
                            f"faster than previous period. This may indicate coordinated "
                            f"amplification or a triggering event.",
                evidence=[],
                narrative_id=self.narrative_id,
                subject_id=self.tracker_config.subject_id,
            )
            if result.success:
                flag = Flag(**result.data)

        # Spawn investigator for significant spikes
        if velocity_ratio > 3.0 and spawn_tool:
            await spawn_tool.execute(
                agent_type="investigator",
                goal=f"Investigate the sudden spike in narrative {self.narrative_id}. "
                     f"Determine if this is due to a triggering event, coordinated amplification, "
                     f"or organic spread. Identify key drivers.",
                inputs={
                    "narrative_id": self.narrative_id,
                    "investigation_type": "velocity_spike",
                    "context": {
                        "velocity_ratio": velocity_ratio,
                        "current_prevalence": self.metrics.prevalence_score if self.metrics else 0,
                    },
                },
                budget_fraction=0.3,
            )

        return flag

    async def _emit_new_amplifiers_flag(self, new_amplifier_ids: List[str]) -> Optional[Flag]:
        """Emit a flag for significant new amplifiers."""
        emit_tool = self._tools.get("emit_flag")
        if not emit_tool:
            return None

        result = await emit_tool.execute(
            flag_type="amplifier_surge",
            severity="info",
            title=f"{len(new_amplifier_ids)} new amplifiers detected",
            description=f"Narrative {self.narrative_id} has {len(new_amplifier_ids)} new "
                        f"significant amplifiers. This may indicate expanding reach.",
            evidence=[{"entity_id": eid, "relevance": "new amplifier"} for eid in new_amplifier_ids[:10]],
            narrative_id=self.narrative_id,
            subject_id=self.tracker_config.subject_id,
        )

        if result.success:
            return Flag(**result.data)
        return None

    async def _load_metrics(self) -> None:
        """Load metrics from persistent memory."""
        metrics_data = self.memory.persistent_memory.get("metrics")
        if metrics_data:
            # Handle nested models
            if "amplifiers" in metrics_data:
                metrics_data["amplifiers"] = [
                    AmplifierInfo(**a) if isinstance(a, dict) else a
                    for a in metrics_data["amplifiers"]
                ]
            self.metrics = NarrativeMetrics(**metrics_data)

    async def _save_metrics(self) -> None:
        """Save metrics to persistent memory."""
        if self.metrics:
            self.memory.persistent_memory["metrics"] = self.metrics.model_dump()

    def check_goal_met(self) -> bool:
        """Check if metrics have been updated."""
        return self.metrics is not None and self.metrics.computed_at.date() == datetime.utcnow().date()

    def check_no_new_info(self) -> bool:
        """Check if no new data available."""
        items = self.memory.working_memory.get("recent_items", [])
        return len(items) == 0

    async def _load_persistent_memory(self) -> None:
        """Load persistent memory from storage."""
        # In production, load from database
        pass

    async def _save_persistent_memory(self) -> None:
        """Save persistent memory to storage."""
        # In production, save to database
        pass
