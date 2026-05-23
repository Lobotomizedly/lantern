"""
Graph Curator Global Agent

A global agent responsible for maintaining knowledge graph quality
through entity resolution, event clustering, and link pruning.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import anthropic
from pydantic import BaseModel, Field

from .base import (
    Agent,
    AgentConfig,
    AgentMemory,
    AgentOutput,
    Flag,
    ReviewPolicy,
    StopCondition,
)
from .tools import tool_catalog


class EntityMergeCandidate(BaseModel):
    """A candidate pair of entities for merging."""
    entity_a_id: str
    entity_a_name: str
    entity_b_id: str
    entity_b_name: str
    similarity_score: float
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    merge_recommendation: str = "review"  # merge, keep_separate, review


class EventCluster(BaseModel):
    """A cluster of related events."""
    cluster_id: str
    event_ids: List[str] = Field(default_factory=list)
    representative_event: Optional[str] = None
    confidence: float = 0.0


class StaleLink(BaseModel):
    """A potentially stale graph link."""
    source_id: str
    target_id: str
    relationship_type: str
    last_evidence_date: datetime
    evidence_count: int
    prune_recommendation: bool = False


class GraphCuratorConfig(AgentConfig):
    """Configuration specific to Graph Curator agent."""
    agent_type: str = "graph_curator"
    similarity_threshold: float = Field(default=0.85, description="Threshold for entity similarity")
    stale_days: int = Field(default=90, description="Days without evidence to consider link stale")
    batch_size: int = Field(default=100, description="Entities to process per batch")
    auto_merge_threshold: float = Field(default=0.95, description="Threshold for auto-merging")


class GraphCuratorOutput(AgentOutput):
    """Output specific to Graph Curator agent."""
    entities_processed: int = 0
    merge_candidates_found: int = 0
    merges_executed: int = 0
    events_clustered: int = 0
    stale_links_pruned: int = 0


class GraphCuratorAgent(Agent[GraphCuratorOutput]):
    """
    Graph Curator global agent for knowledge graph maintenance.

    Responsibilities:
    - Resolve duplicate entities across the graph
    - Merge event clusters representing the same real-world event
    - Prune stale links without recent evidence
    - Improve entity linking quality
    """

    def __init__(
        self,
        config: GraphCuratorConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.curator_config = config

        # Register tools
        for tool_name in ["graph_query", "emit_flag"]:
            tool = tool_catalog.get(tool_name)
            if tool:
                self.register_tool(tool_name, tool)

    def get_system_prompt(self) -> str:
        return """You are a Graph Curator agent for the Lantern Narrative Intelligence Platform.

Your role is to maintain the quality and integrity of the knowledge graph by:
1. Identifying and resolving duplicate entities
2. Clustering related events that represent the same real-world occurrence
3. Pruning stale links that lack recent evidence
4. Improving entity linking accuracy

When evaluating entity duplicates, consider:
- Name variations (abbreviations, nicknames, transliterations)
- Contextual evidence (same events, relationships, mentions)
- Attribute overlap (locations, dates, roles)

For event clustering:
- Events with same participants, time, and outcome are likely duplicates
- Different reporting of the same event should be clustered
- Preserve distinct events even if related

For link pruning:
- Links without recent evidence may be outdated
- Consider the relationship type (some are inherently persistent)
- Flag for review rather than auto-prune when uncertain

Be conservative with auto-merges and auto-prunes. When uncertain, flag for human review.
"""

    async def execute(self) -> GraphCuratorOutput:
        """Execute graph curation tasks."""
        flags_emitted: List[Flag] = []
        entities_processed = 0
        merge_candidates_found = 0
        merges_executed = 0
        events_clustered = 0
        stale_links_pruned = 0

        try:
            # Step 1: Entity deduplication
            dup_result = await self._deduplicate_entities()
            entities_processed = dup_result["processed"]
            merge_candidates_found = dup_result["candidates"]
            merges_executed = dup_result["merged"]
            flags_emitted.extend(dup_result["flags"])

            # Step 2: Event clustering
            cluster_result = await self._cluster_events()
            events_clustered = cluster_result["clustered"]
            flags_emitted.extend(cluster_result["flags"])

            # Step 3: Stale link pruning
            prune_result = await self._prune_stale_links()
            stale_links_pruned = prune_result["pruned"]
            flags_emitted.extend(prune_result["flags"])

            # Step 4: Entity linking quality check
            quality_result = await self._check_linking_quality()
            flags_emitted.extend(quality_result["flags"])

            return GraphCuratorOutput(
                success=True,
                stop_condition=StopCondition.GOAL_MET,
                flags=flags_emitted,
                entities_processed=entities_processed,
                merge_candidates_found=merge_candidates_found,
                merges_executed=merges_executed,
                events_clustered=events_clustered,
                stale_links_pruned=stale_links_pruned,
                execution_summary={
                    "agent_id": self.agent_id,
                    "budget_used": {
                        "tokens": self.config.budget.tokens_used,
                        "cost": self.config.budget.cost_incurred,
                    },
                },
            )

        except Exception as e:
            return GraphCuratorOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
                flags=flags_emitted,
                entities_processed=entities_processed,
                merge_candidates_found=merge_candidates_found,
                merges_executed=merges_executed,
                events_clustered=events_clustered,
                stale_links_pruned=stale_links_pruned,
            )

    async def _deduplicate_entities(self) -> Dict[str, Any]:
        """Find and resolve duplicate entities."""
        result = {
            "processed": 0,
            "candidates": 0,
            "merged": 0,
            "flags": [],
        }

        graph_tool = self._tools.get("graph_query")
        if not graph_tool:
            return result

        # Get entities to process
        # In production, this would fetch from the graph database
        entity_batches = await self._get_entity_batches()

        for batch in entity_batches:
            # Find similar entities in batch
            candidates = await self._find_similar_entities(batch)
            result["candidates"] += len(candidates)

            for candidate in candidates:
                # Evaluate with Claude for ambiguous cases
                if candidate.similarity_score < self.curator_config.auto_merge_threshold:
                    evaluation = await self._evaluate_merge_candidate(candidate)
                    candidate.merge_recommendation = evaluation

                # Execute merges or create flags
                if candidate.merge_recommendation == "merge":
                    success = await self._execute_merge(candidate)
                    if success:
                        result["merged"] += 1
                elif candidate.merge_recommendation == "review":
                    flag = await self._create_merge_review_flag(candidate)
                    if flag:
                        result["flags"].append(flag)

            result["processed"] += len(batch)

            # Check budget
            stop_condition = self.determine_stop_condition()
            if stop_condition:
                break

        return result

    async def _get_entity_batches(self) -> List[List[Dict[str, Any]]]:
        """Get batches of entities to process."""
        graph_tool = self._tools.get("graph_query")
        if not graph_tool:
            return []

        # Query for entities that need deduplication check
        result = await graph_tool.execute(
            query_type="entity_neighbors",
            entity_type="person",  # Start with persons, most common duplicates
            limit=self.curator_config.batch_size,
        )

        if not result.success:
            return []

        entities = result.data.get("nodes", [])

        # Split into batches
        batch_size = self.curator_config.batch_size
        return [entities[i:i + batch_size] for i in range(0, len(entities), batch_size)]

    async def _find_similar_entities(
        self,
        entities: List[Dict[str, Any]],
    ) -> List[EntityMergeCandidate]:
        """Find similar entities within a batch using name similarity and attributes."""
        candidates = []

        # Build name index for efficient comparison
        name_map: Dict[str, List[Dict[str, Any]]] = {}
        for entity in entities:
            name = entity.get("name", "").lower().strip()
            normalized = self._normalize_name(name)
            if normalized:
                if normalized not in name_map:
                    name_map[normalized] = []
                name_map[normalized].append(entity)

        # Find entities with similar names
        processed_pairs: Set[Tuple[str, str]] = set()

        for normalized, group in name_map.items():
            if len(group) > 1:
                # Multiple entities with same normalized name
                for i, entity_a in enumerate(group):
                    for entity_b in group[i + 1:]:
                        pair_key = tuple(sorted([entity_a["id"], entity_b["id"]]))
                        if pair_key not in processed_pairs:
                            processed_pairs.add(pair_key)

                            similarity = self._calculate_entity_similarity(entity_a, entity_b)
                            if similarity >= self.curator_config.similarity_threshold:
                                candidates.append(EntityMergeCandidate(
                                    entity_a_id=entity_a["id"],
                                    entity_a_name=entity_a.get("name", ""),
                                    entity_b_id=entity_b["id"],
                                    entity_b_name=entity_b.get("name", ""),
                                    similarity_score=similarity,
                                    evidence=self._gather_merge_evidence(entity_a, entity_b),
                                ))

        return candidates

    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison."""
        import re
        # Remove common suffixes/prefixes
        name = re.sub(r'\b(mr|mrs|ms|dr|jr|sr|inc|llc|corp)\b\.?', '', name.lower())
        # Remove punctuation and extra spaces
        name = re.sub(r'[^\w\s]', '', name)
        name = ' '.join(name.split())
        return name

    def _calculate_entity_similarity(
        self,
        entity_a: Dict[str, Any],
        entity_b: Dict[str, Any],
    ) -> float:
        """Calculate similarity score between two entities."""
        scores = []

        # Name similarity (Levenshtein distance normalized)
        name_a = entity_a.get("name", "").lower()
        name_b = entity_b.get("name", "").lower()
        if name_a and name_b:
            name_sim = self._string_similarity(name_a, name_b)
            scores.append(("name", name_sim, 0.4))

        # Type match
        if entity_a.get("type") == entity_b.get("type"):
            scores.append(("type", 1.0, 0.2))
        else:
            scores.append(("type", 0.0, 0.2))

        # Attribute overlap
        attrs_a = set(entity_a.get("attributes", {}).keys())
        attrs_b = set(entity_b.get("attributes", {}).keys())
        if attrs_a and attrs_b:
            overlap = len(attrs_a & attrs_b) / len(attrs_a | attrs_b)
            scores.append(("attributes", overlap, 0.2))

        # Relationship overlap
        rels_a = set(entity_a.get("relationships", []))
        rels_b = set(entity_b.get("relationships", []))
        if rels_a or rels_b:
            if rels_a and rels_b:
                overlap = len(rels_a & rels_b) / len(rels_a | rels_b)
            else:
                overlap = 0.0
            scores.append(("relationships", overlap, 0.2))

        # Weighted average
        if not scores:
            return 0.0

        total_weight = sum(s[2] for s in scores)
        weighted_sum = sum(s[1] * s[2] for s in scores)
        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using Levenshtein ratio."""
        if s1 == s2:
            return 1.0
        if not s1 or not s2:
            return 0.0

        # Simple Levenshtein distance
        len1, len2 = len(s1), len(s2)
        if len1 > len2:
            s1, s2 = s2, s1
            len1, len2 = len2, len1

        distances = range(len1 + 1)
        for i2, c2 in enumerate(s2):
            new_distances = [i2 + 1]
            for i1, c1 in enumerate(s1):
                if c1 == c2:
                    new_distances.append(distances[i1])
                else:
                    new_distances.append(1 + min((distances[i1], distances[i1 + 1], new_distances[-1])))
            distances = new_distances

        distance = distances[-1]
        max_len = max(len1, len2)
        return 1.0 - (distance / max_len)

    def _gather_merge_evidence(
        self,
        entity_a: Dict[str, Any],
        entity_b: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Gather evidence for entity merge decision."""
        evidence = []

        # Name evidence
        evidence.append({
            "type": "name_comparison",
            "entity_a_name": entity_a.get("name"),
            "entity_b_name": entity_b.get("name"),
        })

        # Attribute evidence
        attrs_a = entity_a.get("attributes", {})
        attrs_b = entity_b.get("attributes", {})
        common_attrs = set(attrs_a.keys()) & set(attrs_b.keys())
        for attr in common_attrs:
            evidence.append({
                "type": "attribute_comparison",
                "attribute": attr,
                "entity_a_value": attrs_a[attr],
                "entity_b_value": attrs_b[attr],
                "match": attrs_a[attr] == attrs_b[attr],
            })

        return evidence

    async def _evaluate_merge_candidate(self, candidate: EntityMergeCandidate) -> str:
        """Use Claude to evaluate ambiguous merge candidates."""
        messages = [
            {
                "role": "user",
                "content": f"""Evaluate whether these two entities should be merged:

Entity A: {candidate.entity_a_name} (ID: {candidate.entity_a_id})
Entity B: {candidate.entity_b_name} (ID: {candidate.entity_b_id})

Similarity Score: {candidate.similarity_score:.2%}

Evidence:
{json.dumps(candidate.evidence, indent=2)}

Should these entities be merged? Respond with exactly one of:
- "merge" - if clearly the same entity
- "keep_separate" - if clearly different entities
- "review" - if uncertain and human review is needed

Respond with just the single word decision.
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=50)
            content = response.content[0].text.strip().lower()

            if "merge" in content and "keep" not in content:
                return "merge"
            elif "keep" in content or "separate" in content:
                return "keep_separate"
            else:
                return "review"

        except Exception:
            return "review"

    async def _execute_merge(self, candidate: EntityMergeCandidate) -> bool:
        """Execute an entity merge."""
        # In production, this would update the graph database
        # For now, log the action
        self.memory.add_tool_result(
            "entity_merge",
            {
                "entity_a": candidate.entity_a_id,
                "entity_b": candidate.entity_b_id,
                "status": "merged",
            },
        )
        return True

    async def _create_merge_review_flag(self, candidate: EntityMergeCandidate) -> Optional[Flag]:
        """Create a flag for human review of merge candidate."""
        emit_tool = self._tools.get("emit_flag")
        if not emit_tool:
            return None

        result = await emit_tool.execute(
            flag_type="entity_merge_review",
            severity="info",
            title=f"Entity merge review: {candidate.entity_a_name} <-> {candidate.entity_b_name}",
            description=f"Potential duplicate entities detected with {candidate.similarity_score:.0%} similarity. "
                        f"Manual review recommended.",
            evidence=candidate.evidence,
        )

        if result.success:
            return Flag(**result.data)
        return None

    async def _cluster_events(self) -> Dict[str, Any]:
        """Cluster related events."""
        result = {
            "clustered": 0,
            "flags": [],
        }

        graph_tool = self._tools.get("graph_query")
        if not graph_tool:
            return result

        # Query for recent events that may need clustering
        query_result = await graph_tool.execute(
            query_type="entity_neighbors",
            entity_type="event",
            limit=200,
        )

        if not query_result.success:
            return result

        events = query_result.data.get("nodes", [])

        # Group events by approximate time and participants
        time_groups = self._group_events_by_time(events)

        for group in time_groups.values():
            if len(group) > 1:
                # Check if events should be clustered
                clusters = await self._identify_event_clusters(group)

                for cluster in clusters:
                    if len(cluster.event_ids) > 1:
                        success = await self._merge_event_cluster(cluster)
                        if success:
                            result["clustered"] += len(cluster.event_ids) - 1

        return result

    def _group_events_by_time(
        self,
        events: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group events by approximate time (same day)."""
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for event in events:
            timestamp = event.get("timestamp", event.get("date", ""))
            if timestamp:
                # Extract date portion
                date_key = timestamp[:10] if len(timestamp) >= 10 else timestamp
                if date_key not in groups:
                    groups[date_key] = []
                groups[date_key].append(event)

        return groups

    async def _identify_event_clusters(
        self,
        events: List[Dict[str, Any]],
    ) -> List[EventCluster]:
        """Identify clusters within a group of events."""
        clusters = []

        # Simple clustering by participant overlap
        processed = set()

        for i, event_a in enumerate(events):
            if event_a["id"] in processed:
                continue

            cluster_events = [event_a]
            processed.add(event_a["id"])

            participants_a = set(event_a.get("participants", []))

            for event_b in events[i + 1:]:
                if event_b["id"] in processed:
                    continue

                participants_b = set(event_b.get("participants", []))

                # Check overlap
                if participants_a and participants_b:
                    overlap = len(participants_a & participants_b) / len(participants_a | participants_b)
                    if overlap > 0.5:
                        cluster_events.append(event_b)
                        processed.add(event_b["id"])

            if len(cluster_events) > 1:
                clusters.append(EventCluster(
                    cluster_id=f"cluster_{event_a['id']}",
                    event_ids=[e["id"] for e in cluster_events],
                    representative_event=event_a["id"],
                    confidence=0.8,
                ))

        return clusters

    async def _merge_event_cluster(self, cluster: EventCluster) -> bool:
        """Merge a cluster of events into one."""
        # In production, update the graph database
        self.memory.add_tool_result(
            "event_cluster_merge",
            {
                "cluster_id": cluster.cluster_id,
                "events_merged": cluster.event_ids,
                "representative": cluster.representative_event,
            },
        )
        return True

    async def _prune_stale_links(self) -> Dict[str, Any]:
        """Prune links without recent evidence."""
        result = {
            "pruned": 0,
            "flags": [],
        }

        graph_tool = self._tools.get("graph_query")
        if not graph_tool:
            return result

        # Query for links to evaluate
        cutoff_date = datetime.utcnow() - timedelta(days=self.curator_config.stale_days)

        query_result = await graph_tool.execute(
            query_type="entity_relationships",
            limit=500,
        )

        if not query_result.success:
            return result

        edges = query_result.data.get("edges", [])

        for edge in edges:
            last_evidence = edge.get("last_evidence_date")
            if last_evidence:
                try:
                    last_date = datetime.fromisoformat(last_evidence.replace("Z", "+00:00"))
                    if last_date < cutoff_date:
                        # Consider for pruning
                        stale_link = StaleLink(
                            source_id=edge.get("source"),
                            target_id=edge.get("target"),
                            relationship_type=edge.get("type", "unknown"),
                            last_evidence_date=last_date,
                            evidence_count=edge.get("evidence_count", 0),
                        )

                        # Evaluate if should prune
                        should_prune = self._evaluate_stale_link(stale_link)

                        if should_prune:
                            success = await self._prune_link(stale_link)
                            if success:
                                result["pruned"] += 1
                except (ValueError, TypeError):
                    continue

        return result

    def _evaluate_stale_link(self, link: StaleLink) -> bool:
        """Evaluate whether a stale link should be pruned."""
        # Persistent relationship types should not be auto-pruned
        persistent_types = {"parent_of", "sibling_of", "founded", "headquartered_in"}
        if link.relationship_type in persistent_types:
            return False

        # Low evidence count makes pruning more likely
        if link.evidence_count <= 1:
            return True

        # Default: don't auto-prune
        return False

    async def _prune_link(self, link: StaleLink) -> bool:
        """Prune a stale link from the graph."""
        # In production, update the graph database
        self.memory.add_tool_result(
            "link_prune",
            {
                "source": link.source_id,
                "target": link.target_id,
                "relationship": link.relationship_type,
            },
        )
        return True

    async def _check_linking_quality(self) -> Dict[str, Any]:
        """Check and report on entity linking quality."""
        result = {
            "flags": [],
        }

        # This would analyze linking quality metrics
        # For now, create a summary flag if issues detected

        # Example quality check: entities with very few links
        graph_tool = self._tools.get("graph_query")
        if graph_tool:
            query_result = await graph_tool.execute(
                query_type="entity_neighbors",
                limit=100,
            )

            if query_result.success:
                nodes = query_result.data.get("nodes", [])
                orphaned = [n for n in nodes if n.get("link_count", 0) == 0]

                if len(orphaned) > 10:
                    emit_tool = self._tools.get("emit_flag")
                    if emit_tool:
                        flag_result = await emit_tool.execute(
                            flag_type="graph_quality",
                            severity="info",
                            title=f"{len(orphaned)} orphaned entities detected",
                            description="Multiple entities with no links found. "
                                        "These may need manual review or additional linking.",
                            evidence=[{"entity_id": n["id"], "name": n.get("name")} for n in orphaned[:10]],
                        )
                        if flag_result.success:
                            result["flags"].append(Flag(**flag_result.data))

        return result

    def check_goal_met(self) -> bool:
        """Check if curation tasks are complete."""
        # Goal is met after processing all entity batches
        return self.memory.working_memory.get("processing_complete", False)

    def check_no_new_info(self) -> bool:
        """Check if no more data to process."""
        return self.memory.working_memory.get("no_more_data", False)
