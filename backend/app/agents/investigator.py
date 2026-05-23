"""
Investigator Ephemeral Agent

An ephemeral agent that investigates questions by searching corpus and graph,
optionally searching the open web, and following leads iteratively.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import anthropic
from pydantic import BaseModel, Field

from .base import (
    AgentConfig,
    AgentMemory,
    AgentOutput,
    Artifact,
    EphemeralAgent,
    ReviewPolicy,
    StopCondition,
)
from .tools import tool_catalog


class EvidenceItem(BaseModel):
    """A piece of evidence found during investigation."""
    id: str
    source_type: str  # corpus, graph, web
    source_id: str  # item_id, entity_id, or URL
    content: str
    relevance_score: float = 0.0
    relevance_explanation: str = ""
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class InvestigationLead(BaseModel):
    """A lead to follow during investigation."""
    id: str
    description: str
    priority: float = 0.5
    source_evidence_id: Optional[str] = None
    explored: bool = False
    result_summary: str = ""


class InvestigationTrail(BaseModel):
    """The evidence trail from an investigation."""
    question: str
    summary: str = ""
    confidence: float = 0.0
    evidence: List[EvidenceItem] = Field(default_factory=list)
    leads_explored: List[InvestigationLead] = Field(default_factory=list)
    leads_unexplored: List[InvestigationLead] = Field(default_factory=list)
    conclusions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class InvestigatorConfig(AgentConfig):
    """Configuration specific to Investigator agent."""
    agent_type: str = "investigator"
    question: str = Field(..., description="The question to investigate")
    search_web: bool = Field(default=False, description="Whether to search open web")
    max_leads: int = Field(default=10, description="Maximum leads to follow")
    min_evidence: int = Field(default=3, description="Minimum evidence items to collect")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class InvestigatorOutput(AgentOutput):
    """Output specific to Investigator agent."""
    investigation_trail: Optional[InvestigationTrail] = None
    evidence_count: int = 0
    leads_explored: int = 0
    confidence: float = 0.0


class InvestigatorAgent(EphemeralAgent[InvestigatorOutput]):
    """
    Investigator ephemeral agent for deep research tasks.

    Given a question:
    - Searches corpus and graph for relevant information
    - Optionally searches open web for external sources
    - Follows leads iteratively until question is answered
    - Returns structured evidence trail with citations
    """

    def __init__(
        self,
        config: InvestigatorConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.investigator_config = config
        self.trail = InvestigationTrail(question=config.question)

        # Register tools
        allowed_tools = ["corpus_search", "graph_query", "item_fetch"]
        if config.search_web:
            allowed_tools.extend(["web_search", "web_fetch"])

        for tool_name in allowed_tools:
            tool = tool_catalog.get(tool_name)
            if tool:
                self.register_tool(tool_name, tool)

    @property
    def question(self) -> str:
        return self.investigator_config.question

    def get_system_prompt(self) -> str:
        context_str = ""
        if self.investigator_config.context:
            context_str = f"\nAdditional Context:\n{json.dumps(self.investigator_config.context, indent=2)}"

        web_note = ""
        if self.investigator_config.search_web:
            web_note = "\nYou may also search the open web for external sources using web_search and web_fetch."

        return f"""You are an Investigator agent for the Lantern Narrative Intelligence Platform.

Your task is to investigate the following question:
{self.question}
{context_str}

You have access to:
- corpus_search: Search the document corpus semantically
- graph_query: Query the entity/event/narrative graph
- item_fetch: Retrieve full item content{web_note}

Investigation Process:
1. Start with broad searches to understand the landscape
2. Identify key entities, events, and narratives related to the question
3. Gather specific evidence from items and graph
4. Follow leads iteratively - each piece of evidence may suggest new avenues
5. Build a coherent evidence trail with citations
6. Draw conclusions with appropriate confidence levels

Evidence Standards:
- Cite specific items with IDs for all claims
- Note the source type (corpus, graph, web) for each piece of evidence
- Rate relevance of each evidence item
- Track what remains uncertain or unexplored

When you have sufficient evidence (at least {self.investigator_config.min_evidence} items) or have exhausted leads,
provide a final summary with:
- Key findings
- Supporting evidence with citations
- Confidence level
- Remaining uncertainties

Be thorough but efficient. Stop when the question is adequately answered or no more leads exist.
"""

    async def execute(self) -> InvestigatorOutput:
        """Execute the investigation."""
        try:
            # Step 1: Initial broad search
            await self._conduct_initial_search()

            # Step 2: Generate initial leads from search results
            await self._generate_leads()

            # Step 3: Iteratively explore leads
            iteration = 0
            max_iterations = self.investigator_config.max_leads

            while iteration < max_iterations:
                # Check stop conditions
                stop_condition = self.determine_stop_condition()
                if stop_condition:
                    break

                # Get next lead to explore
                lead = self._get_next_lead()
                if not lead:
                    break

                # Explore the lead
                await self._explore_lead(lead)
                iteration += 1

                # Generate new leads from findings
                await self._generate_leads()

            # Step 4: Synthesize findings
            await self._synthesize_findings()

            return InvestigatorOutput(
                success=True,
                stop_condition=self.determine_stop_condition() or StopCondition.GOAL_MET,
                investigation_trail=self.trail,
                evidence_count=len(self.trail.evidence),
                leads_explored=len(self.trail.leads_explored),
                confidence=self.trail.confidence,
                execution_summary={
                    "agent_id": self.agent_id,
                    "question": self.question,
                    "evidence_found": len(self.trail.evidence),
                    "leads_explored": len(self.trail.leads_explored),
                    "leads_unexplored": len(self.trail.leads_unexplored),
                    "budget_used": {
                        "tokens": self.config.budget.tokens_used,
                        "cost": self.config.budget.cost_incurred,
                    },
                },
            )

        except Exception as e:
            return InvestigatorOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
                investigation_trail=self.trail,
                evidence_count=len(self.trail.evidence),
                leads_explored=len(self.trail.leads_explored),
            )

    async def _conduct_initial_search(self) -> None:
        """Conduct initial broad searches."""
        corpus_tool = self._tools.get("corpus_search")
        graph_tool = self._tools.get("graph_query")

        # Corpus search
        if corpus_tool:
            result = await corpus_tool.execute(
                query=self.question,
                limit=20,
            )

            if result.success:
                items = result.data.get("items", [])
                for item in items:
                    evidence = EvidenceItem(
                        id=f"corpus_{item.get('id', '')}",
                        source_type="corpus",
                        source_id=item.get("id", ""),
                        content=item.get("snippet", item.get("title", "")),
                        relevance_score=item.get("relevance_score", 0.5),
                        timestamp=datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None,
                        metadata={
                            "title": item.get("title"),
                            "source": item.get("source", {}).get("name"),
                        },
                    )
                    self.trail.evidence.append(evidence)

        # Graph search for entities
        if graph_tool:
            # Extract potential entity references from question
            entity_terms = await self._extract_entity_terms()

            for term in entity_terms[:5]:  # Limit to top 5
                result = await graph_tool.execute(
                    query_type="entity_neighbors",
                    entity_id=term,
                    depth=2,
                    limit=20,
                )

                if result.success:
                    nodes = result.data.get("nodes", [])
                    for node in nodes:
                        evidence = EvidenceItem(
                            id=f"graph_{node.get('id', '')}",
                            source_type="graph",
                            source_id=node.get("id", ""),
                            content=f"Entity: {node.get('name', '')} ({node.get('type', '')})",
                            relevance_score=0.6,
                            metadata=node,
                        )
                        self.trail.evidence.append(evidence)

        # Deduplicate evidence
        self._deduplicate_evidence()

    async def _extract_entity_terms(self) -> List[str]:
        """Extract potential entity terms from the question."""
        messages = [
            {
                "role": "user",
                "content": f"""Extract key entity names or terms from this question that should be searched in a knowledge graph:

Question: {self.question}

Return a JSON array of terms, most important first. Example: ["Company X", "John Smith", "Project Alpha"]
Just the JSON array, nothing else.
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=200)
            content = response.content[0].text.strip()

            # Parse JSON
            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass

        # Fallback: simple word extraction
        words = self.question.split()
        return [w for w in words if len(w) > 3 and w[0].isupper()]

    async def _generate_leads(self) -> None:
        """Generate investigation leads from current evidence."""
        if not self.trail.evidence:
            return

        # Use Claude to generate leads
        evidence_summary = "\n".join([
            f"- [{e.source_type}] {e.content[:200]}"
            for e in self.trail.evidence[:20]
        ])

        explored_summary = "\n".join([
            f"- {l.description}: {l.result_summary[:100]}"
            for l in self.trail.leads_explored[-5:]
        ]) if self.trail.leads_explored else "None yet"

        messages = [
            {
                "role": "user",
                "content": f"""Based on the investigation so far, suggest leads to explore further.

Question: {self.question}

Evidence collected:
{evidence_summary}

Leads already explored:
{explored_summary}

Suggest 3-5 new leads to explore. For each lead, provide:
1. A specific search query or entity to investigate
2. Why this might help answer the question

Return as JSON array:
[{{"description": "...", "priority": 0.0-1.0}}]

Return only unexplored angles. If the question seems answered, return an empty array.
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=500)
            content = response.content[0].text.strip()

            import re
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                leads_data = json.loads(json_match.group())

                for i, ld in enumerate(leads_data):
                    # Check if lead already exists
                    existing = any(
                        l.description.lower() == ld.get("description", "").lower()
                        for l in self.trail.leads_explored + self.trail.leads_unexplored
                    )

                    if not existing:
                        lead = InvestigationLead(
                            id=f"lead_{len(self.trail.leads_explored) + len(self.trail.leads_unexplored)}",
                            description=ld.get("description", ""),
                            priority=ld.get("priority", 0.5),
                        )
                        self.trail.leads_unexplored.append(lead)

            # Sort by priority
            self.trail.leads_unexplored.sort(key=lambda l: l.priority, reverse=True)

        except Exception:
            pass

    def _get_next_lead(self) -> Optional[InvestigationLead]:
        """Get the next lead to explore."""
        if not self.trail.leads_unexplored:
            return None

        # Get highest priority unexplored lead
        lead = self.trail.leads_unexplored.pop(0)
        return lead

    async def _explore_lead(self, lead: InvestigationLead) -> None:
        """Explore a specific lead."""
        lead.explored = True

        # Search corpus for lead
        corpus_tool = self._tools.get("corpus_search")
        if corpus_tool:
            result = await corpus_tool.execute(
                query=lead.description,
                limit=10,
            )

            if result.success:
                items = result.data.get("items", [])
                new_evidence = []

                for item in items:
                    evidence = EvidenceItem(
                        id=f"corpus_{item.get('id', '')}",
                        source_type="corpus",
                        source_id=item.get("id", ""),
                        content=item.get("snippet", item.get("title", "")),
                        relevance_score=item.get("relevance_score", 0.5),
                        metadata={
                            "title": item.get("title"),
                            "source": item.get("source", {}).get("name"),
                            "lead_id": lead.id,
                        },
                    )
                    new_evidence.append(evidence)

                lead.result_summary = f"Found {len(items)} items"

                # Add new evidence, avoiding duplicates
                existing_ids = {e.source_id for e in self.trail.evidence}
                for e in new_evidence:
                    if e.source_id not in existing_ids:
                        self.trail.evidence.append(e)
                        existing_ids.add(e.source_id)

        # Optionally fetch full content for high-relevance items
        item_tool = self._tools.get("item_fetch")
        if item_tool and lead.priority > 0.7:
            high_relevance = [
                e for e in self.trail.evidence
                if e.metadata.get("lead_id") == lead.id and e.relevance_score > 0.7
            ]

            for evidence in high_relevance[:3]:  # Limit full fetches
                result = await item_tool.execute(item_id=evidence.source_id)
                if result.success:
                    full_content = result.data.get("content", "")
                    evidence.content = full_content[:2000]  # Truncate long content

        # Search web if enabled
        if self.investigator_config.search_web:
            web_tool = self._tools.get("web_search")
            if web_tool:
                result = await web_tool.execute(
                    query=lead.description,
                    limit=5,
                )

                if result.success:
                    web_results = result.data.get("results", [])
                    for wr in web_results:
                        evidence = EvidenceItem(
                            id=f"web_{hash(wr.get('url', ''))}",
                            source_type="web",
                            source_id=wr.get("url", ""),
                            content=wr.get("snippet", wr.get("title", "")),
                            relevance_score=0.5,
                            metadata={
                                "title": wr.get("title"),
                                "url": wr.get("url"),
                                "lead_id": lead.id,
                            },
                        )
                        self.trail.evidence.append(evidence)

        self.trail.leads_explored.append(lead)

    def _deduplicate_evidence(self) -> None:
        """Remove duplicate evidence items."""
        seen_ids: Set[str] = set()
        unique_evidence = []

        for evidence in self.trail.evidence:
            if evidence.source_id not in seen_ids:
                seen_ids.add(evidence.source_id)
                unique_evidence.append(evidence)

        self.trail.evidence = unique_evidence

    async def _synthesize_findings(self) -> None:
        """Synthesize findings into conclusions."""
        if not self.trail.evidence:
            self.trail.summary = "No evidence found."
            self.trail.confidence = 0.0
            return

        # Prepare evidence for Claude
        evidence_text = "\n\n".join([
            f"[{i+1}] [{e.source_type}] {e.content[:500]}"
            for i, e in enumerate(self.trail.evidence[:30])
        ])

        messages = [
            {
                "role": "user",
                "content": f"""Synthesize the investigation findings.

Question: {self.question}

Evidence collected:
{evidence_text}

Leads explored: {len(self.trail.leads_explored)}
Leads remaining: {len(self.trail.leads_unexplored)}

Provide:
1. A summary answering the question (2-3 paragraphs)
2. Key conclusions (bullet points)
3. Remaining uncertainties
4. Confidence level (0.0-1.0)

Format as JSON:
{{
    "summary": "...",
    "conclusions": ["...", "..."],
    "uncertainties": ["...", "..."],
    "confidence": 0.X
}}
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=1500)
            content = response.content[0].text.strip()

            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                synthesis = json.loads(json_match.group())
                self.trail.summary = synthesis.get("summary", "")
                self.trail.conclusions = synthesis.get("conclusions", [])
                self.trail.uncertainties = synthesis.get("uncertainties", [])
                self.trail.confidence = synthesis.get("confidence", 0.5)

        except Exception:
            # Fallback summary
            self.trail.summary = f"Investigation found {len(self.trail.evidence)} pieces of evidence across {len(self.trail.leads_explored)} explored leads."
            self.trail.confidence = 0.5

        # Score evidence relevance
        await self._score_evidence_relevance()

    async def _score_evidence_relevance(self) -> None:
        """Score the relevance of each evidence item to the conclusion."""
        if not self.trail.summary or len(self.trail.evidence) <= 5:
            return

        # Use Claude to rate relevance
        for i in range(0, len(self.trail.evidence), 10):
            batch = self.trail.evidence[i:i+10]

            evidence_list = "\n".join([
                f"{j+1}. {e.content[:200]}"
                for j, e in enumerate(batch)
            ])

            messages = [
                {
                    "role": "user",
                    "content": f"""Rate how relevant each piece of evidence is to this conclusion:

Summary: {self.trail.summary[:500]}

Evidence:
{evidence_list}

Return JSON array of scores (0.0-1.0) for each item:
[0.8, 0.6, 0.9, ...]

Just the array, nothing else.
"""
                }
            ]

            try:
                response = await self.call_claude(messages, max_tokens=100)
                content = response.content[0].text.strip()

                import re
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    scores = json.loads(json_match.group())
                    for j, score in enumerate(scores):
                        if j < len(batch):
                            batch[j].relevance_score = float(score)

            except Exception:
                pass

    def check_goal_met(self) -> bool:
        """Check if the investigation goal is met."""
        # Goal is met if we have sufficient evidence and a conclusion
        has_min_evidence = len(self.trail.evidence) >= self.investigator_config.min_evidence
        has_conclusion = bool(self.trail.summary)
        high_confidence = self.trail.confidence >= 0.7

        return has_min_evidence and has_conclusion and high_confidence

    def check_no_new_info(self) -> bool:
        """Check if no more leads to explore."""
        return len(self.trail.leads_unexplored) == 0
