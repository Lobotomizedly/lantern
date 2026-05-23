"""
Sentinel Standing Agent

A standing agent that runs daily after collection sweep for each Subject.
Monitors for changes, detects emerging narratives, and emits flags for review.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import anthropic
from pydantic import BaseModel, Field

from .base import (
    AgentConfig,
    AgentMemory,
    AgentOutput,
    Artifact,
    Flag,
    ReviewPolicy,
    StandingAgent,
    StopCondition,
)
from .tools import tool_catalog


class SentinelBaseline(BaseModel):
    """Baseline metrics for a subject, used for comparison."""
    subject_id: str
    computed_at: datetime = Field(default_factory=datetime.utcnow)

    # Volume metrics
    avg_daily_items: float = 0.0
    avg_daily_sources: float = 0.0

    # Sentiment metrics
    avg_sentiment_score: float = 0.0
    sentiment_std_dev: float = 0.0

    # Entity metrics
    known_entities: List[str] = Field(default_factory=list)
    entity_mention_rates: Dict[str, float] = Field(default_factory=dict)

    # Narrative metrics
    active_narratives: List[str] = Field(default_factory=list)
    narrative_prevalence: Dict[str, float] = Field(default_factory=dict)

    # Source metrics
    source_distribution: Dict[str, float] = Field(default_factory=dict)


class SentinelConfig(AgentConfig):
    """Configuration specific to Sentinel agent."""
    agent_type: str = "sentinel"
    subject_id: str = Field(..., description="Subject to monitor")
    lookback_days: int = Field(default=30, description="Days to compute baseline")
    sensitivity: float = Field(default=1.5, description="Threshold multiplier for alerts")


class SentinelOutput(AgentOutput):
    """Output specific to Sentinel agent."""
    items_reviewed: int = Field(default=0)
    baseline_updated: bool = Field(default=False)
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)


class SentinelAgent(StandingAgent[SentinelOutput]):
    """
    Sentinel standing agent for monitoring a Subject.

    Runs daily after collection sweep to:
    - Review the day's new items
    - Compare against baseline metrics
    - Detect anomalies and emerging trends
    - Emit flags for human review
    """

    def __init__(
        self,
        config: SentinelConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.sentinel_config = config
        self.baseline: Optional[SentinelBaseline] = None

        # Register tools
        for tool_name in ["corpus_search", "graph_query", "item_fetch", "emit_flag"]:
            tool = tool_catalog.get(tool_name)
            if tool:
                self.register_tool(tool_name, tool)

    @property
    def subject_id(self) -> str:
        return self.sentinel_config.subject_id

    def get_system_prompt(self) -> str:
        return f"""You are a Sentinel agent monitoring Subject {self.subject_id} for the Lantern Narrative Intelligence Platform.

Your role is to:
1. Review all new items collected today for this subject
2. Compare today's metrics against the established baseline
3. Identify significant changes or anomalies
4. Detect emerging narratives or sentiment shifts
5. Flag notable items or patterns for human review

You have access to the following tools:
- corpus_search: Search the document corpus semantically
- graph_query: Query the entity/event/narrative graph
- item_fetch: Retrieve full item content
- emit_flag: Emit flags for human review

When analyzing items, consider:
- Volume changes: Is there an unusual spike or drop in coverage?
- Sentiment shifts: Has the overall tone changed significantly?
- New entities: Are there new actors or organizations appearing?
- Narrative emergence: Are new storylines developing?
- Velocity spikes: Is a particular narrative spreading faster than usual?
- Source changes: Are new sources covering this subject?

Be thorough but efficient. Emit flags only for genuinely significant observations.
Include specific evidence and item references in your flags.

Current baseline metrics:
{self._format_baseline()}

Today's date: {datetime.utcnow().strftime('%Y-%m-%d')}
"""

    def _format_baseline(self) -> str:
        """Format baseline for system prompt."""
        if not self.baseline:
            return "No baseline established yet - this is the first run."

        return f"""
- Average daily items: {self.baseline.avg_daily_items:.1f}
- Average sentiment: {self.baseline.avg_sentiment_score:.2f} (std: {self.baseline.sentiment_std_dev:.2f})
- Known entities: {len(self.baseline.known_entities)}
- Active narratives: {len(self.baseline.active_narratives)}
- Baseline computed: {self.baseline.computed_at.strftime('%Y-%m-%d')}
"""

    async def execute(self) -> SentinelOutput:
        """Execute the daily sentinel review."""
        flags_emitted: List[Flag] = []
        items_reviewed = 0
        metrics_summary: Dict[str, Any] = {}

        try:
            # Load baseline from persistent memory
            await self._load_baseline()

            # Step 1: Fetch today's items
            today = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)

            corpus_tool = self._tools.get("corpus_search")
            if corpus_tool:
                search_result = await corpus_tool.execute(
                    query="*",  # All items
                    subject_id=self.subject_id,
                    date_from=yesterday.isoformat(),
                    date_to=today.isoformat(),
                    limit=100,
                )

                if search_result.success:
                    items = search_result.data.get("items", [])
                    items_reviewed = len(items)
                    self.memory.working_memory["today_items"] = items

            # Step 2: Compute today's metrics
            today_metrics = await self._compute_daily_metrics()
            metrics_summary = today_metrics

            # Step 3: Compare against baseline and detect anomalies
            if self.baseline:
                anomalies = self._detect_anomalies(today_metrics)

                # Step 4: Emit flags for significant anomalies
                emit_tool = self._tools.get("emit_flag")
                if emit_tool:
                    for anomaly in anomalies:
                        flag_result = await emit_tool.execute(**anomaly)
                        if flag_result.success:
                            flags_emitted.append(Flag(**flag_result.data))

            # Step 5: Run Claude analysis for deeper insights
            if items_reviewed > 0:
                analysis_flags = await self._run_claude_analysis()
                flags_emitted.extend(analysis_flags)

            # Step 6: Update baseline with new data
            await self._update_baseline(today_metrics)

            # Save persistent memory
            await self._save_baseline()

            return SentinelOutput(
                success=True,
                stop_condition=StopCondition.GOAL_MET,
                flags=flags_emitted,
                items_reviewed=items_reviewed,
                baseline_updated=True,
                metrics_summary=metrics_summary,
                execution_summary={
                    "agent_id": self.agent_id,
                    "subject_id": self.subject_id,
                    "items_reviewed": items_reviewed,
                    "flags_emitted": len(flags_emitted),
                    "budget_used": {
                        "tokens": self.config.budget.tokens_used,
                        "cost": self.config.budget.cost_incurred,
                    },
                },
            )

        except Exception as e:
            return SentinelOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
                flags=flags_emitted,
                items_reviewed=items_reviewed,
                metrics_summary=metrics_summary,
            )

    async def _compute_daily_metrics(self) -> Dict[str, Any]:
        """Compute metrics for today's items."""
        items = self.memory.working_memory.get("today_items", [])

        if not items:
            return {
                "item_count": 0,
                "source_count": 0,
                "avg_sentiment": 0.0,
                "entities": [],
                "narratives": [],
            }

        # Compute basic metrics
        sources = set()
        sentiments = []
        entities = set()
        narratives = set()

        for item in items:
            if "source" in item:
                sources.add(item["source"].get("id", "unknown"))
            if "sentiment" in item:
                sentiments.append(item["sentiment"])
            if "entities" in item:
                for entity in item["entities"]:
                    entities.add(entity.get("id", entity.get("name", "")))
            if "narratives" in item:
                for narrative in item["narratives"]:
                    narratives.add(narrative.get("id", ""))

        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

        return {
            "item_count": len(items),
            "source_count": len(sources),
            "avg_sentiment": avg_sentiment,
            "entities": list(entities),
            "narratives": list(narratives),
            "sources": list(sources),
        }

    def _detect_anomalies(self, today_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect anomalies by comparing today's metrics to baseline."""
        anomalies = []
        sensitivity = self.sentinel_config.sensitivity

        if not self.baseline:
            return anomalies

        # Volume spike detection
        if self.baseline.avg_daily_items > 0:
            volume_ratio = today_metrics["item_count"] / self.baseline.avg_daily_items
            if volume_ratio > sensitivity * 2:
                anomalies.append({
                    "flag_type": "velocity_spike",
                    "severity": "alert" if volume_ratio > sensitivity * 3 else "warning",
                    "title": f"Volume spike detected: {volume_ratio:.1f}x baseline",
                    "description": f"Today's item count ({today_metrics['item_count']}) "
                                   f"is {volume_ratio:.1f}x the baseline average "
                                   f"({self.baseline.avg_daily_items:.0f})",
                    "evidence": [],
                    "subject_id": self.subject_id,
                })

        # Sentiment shift detection
        if self.baseline.sentiment_std_dev > 0:
            sentiment_z = abs(
                today_metrics["avg_sentiment"] - self.baseline.avg_sentiment_score
            ) / self.baseline.sentiment_std_dev

            if sentiment_z > sensitivity:
                direction = "positive" if today_metrics["avg_sentiment"] > self.baseline.avg_sentiment_score else "negative"
                anomalies.append({
                    "flag_type": "sentiment_shift",
                    "severity": "alert" if sentiment_z > sensitivity * 2 else "warning",
                    "title": f"Significant {direction} sentiment shift",
                    "description": f"Today's average sentiment ({today_metrics['avg_sentiment']:.2f}) "
                                   f"differs from baseline ({self.baseline.avg_sentiment_score:.2f}) "
                                   f"by {sentiment_z:.1f} standard deviations",
                    "evidence": [],
                    "subject_id": self.subject_id,
                })

        # New entity detection
        new_entities = set(today_metrics.get("entities", [])) - set(self.baseline.known_entities)
        if len(new_entities) >= 3:  # Threshold for significance
            anomalies.append({
                "flag_type": "new_entity",
                "severity": "info",
                "title": f"{len(new_entities)} new entities detected",
                "description": f"New entities appearing in today's coverage: {', '.join(list(new_entities)[:10])}",
                "evidence": [],
                "subject_id": self.subject_id,
            })

        return anomalies

    async def _run_claude_analysis(self) -> List[Flag]:
        """Run Claude analysis for deeper pattern detection."""
        flags = []
        items = self.memory.working_memory.get("today_items", [])

        if len(items) < 5:
            return flags

        # Prepare items summary for analysis
        items_summary = []
        for item in items[:50]:  # Limit for token efficiency
            items_summary.append({
                "id": item.get("id"),
                "title": item.get("title", "")[:200],
                "snippet": item.get("snippet", "")[:300],
                "source": item.get("source", {}).get("name", "unknown"),
                "sentiment": item.get("sentiment"),
            })

        messages = [
            {
                "role": "user",
                "content": f"""Analyze these items collected today for Subject {self.subject_id}.

Items:
{json.dumps(items_summary, indent=2)}

Identify:
1. Any emerging narratives or themes not previously seen
2. Coordination patterns (similar messaging across sources)
3. Particularly notable or impactful items
4. Any concerning patterns

Respond with a JSON array of flags to emit. Each flag should have:
- flag_type: one of "emerging_narrative", "coordination_detected", "notable_item"
- severity: "info", "warning", "alert", or "critical"
- title: short title
- description: detailed description
- evidence: array of {{item_id, excerpt, relevance}}

If nothing significant is found, respond with an empty array: []
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=2000)

            # Parse Claude's response
            content = response.content[0].text if response.content else "[]"

            # Extract JSON from response
            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                flag_data = json.loads(json_match.group())
                emit_tool = self._tools.get("emit_flag")

                for fd in flag_data:
                    if emit_tool:
                        fd["subject_id"] = self.subject_id
                        result = await emit_tool.execute(**fd)
                        if result.success:
                            flags.append(Flag(**result.data))

        except Exception as e:
            # Log error but don't fail the whole run
            self.memory.add_message("system", f"Claude analysis error: {str(e)}")

        return flags

    async def _load_baseline(self) -> None:
        """Load baseline from persistent memory."""
        baseline_data = self.memory.persistent_memory.get("baseline")
        if baseline_data:
            self.baseline = SentinelBaseline(**baseline_data)

    async def _save_baseline(self) -> None:
        """Save baseline to persistent memory."""
        if self.baseline:
            self.memory.persistent_memory["baseline"] = self.baseline.model_dump()

    async def _update_baseline(self, today_metrics: Dict[str, Any]) -> None:
        """Update baseline with today's data using rolling average."""
        if not self.baseline:
            # Initialize baseline
            self.baseline = SentinelBaseline(
                subject_id=self.subject_id,
                avg_daily_items=float(today_metrics["item_count"]),
                avg_sentiment_score=today_metrics["avg_sentiment"],
                sentiment_std_dev=0.1,  # Initial estimate
                known_entities=today_metrics.get("entities", []),
                active_narratives=today_metrics.get("narratives", []),
            )
        else:
            # Rolling update with exponential decay
            alpha = 0.1  # Learning rate

            self.baseline.avg_daily_items = (
                (1 - alpha) * self.baseline.avg_daily_items +
                alpha * today_metrics["item_count"]
            )

            old_sentiment = self.baseline.avg_sentiment_score
            self.baseline.avg_sentiment_score = (
                (1 - alpha) * old_sentiment +
                alpha * today_metrics["avg_sentiment"]
            )

            # Update std dev estimate
            diff = abs(today_metrics["avg_sentiment"] - old_sentiment)
            self.baseline.sentiment_std_dev = (
                (1 - alpha) * self.baseline.sentiment_std_dev +
                alpha * diff
            )

            # Merge entities
            new_entities = set(self.baseline.known_entities) | set(today_metrics.get("entities", []))
            self.baseline.known_entities = list(new_entities)

            # Merge narratives
            new_narratives = set(self.baseline.active_narratives) | set(today_metrics.get("narratives", []))
            self.baseline.active_narratives = list(new_narratives)

            self.baseline.computed_at = datetime.utcnow()

    def check_goal_met(self) -> bool:
        """Check if all items have been reviewed."""
        items = self.memory.working_memory.get("today_items", [])
        reviewed = self.memory.working_memory.get("items_reviewed", 0)
        return len(items) > 0 and reviewed >= len(items)

    def check_no_new_info(self) -> bool:
        """Check if no more items to review."""
        items = self.memory.working_memory.get("today_items", [])
        return len(items) == 0

    async def _load_persistent_memory(self) -> None:
        """Load persistent memory from storage."""
        # In production, this would load from database
        pass

    async def _save_persistent_memory(self) -> None:
        """Save persistent memory to storage."""
        # In production, this would save to database
        pass
