"""
Synthesizer Ephemeral Agent

An ephemeral agent that produces artifacts (reports, memos, timelines, newsletters)
with grounded assertions and citation coverage.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

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


class ArtifactType(str, Enum):
    """Types of artifacts that can be synthesized."""
    REPORT = "report"
    MEMO = "memo"
    TIMELINE = "timeline"
    NEWSLETTER = "newsletter"
    BRIEFING = "briefing"


class TonalVariant(str, Enum):
    """Tonal variants for memo generation."""
    EXECUTIVE = "executive"  # Brief, high-level, action-oriented
    ANALYTICAL = "analytical"  # Detailed, evidence-focused
    URGENT = "urgent"  # Alert-style, emphasizing immediate concerns
    NEUTRAL = "neutral"  # Balanced, objective presentation


class Citation(BaseModel):
    """A citation for a source."""
    id: str
    item_id: str
    quote: str
    context: str
    page_or_section: Optional[str] = None
    used_for: str  # What assertion this supports


class ContentSection(BaseModel):
    """A section of artifact content."""
    heading: str
    content: str
    citations: List[Citation] = Field(default_factory=list)


class SynthesizerConfig(AgentConfig):
    """Configuration specific to Synthesizer agent."""
    agent_type: str = "synthesizer"
    artifact_type: ArtifactType = Field(..., description="Type of artifact to produce")
    topic: str = Field(..., description="Topic or title for the artifact")
    scope: Dict[str, Any] = Field(default_factory=dict, description="Scope parameters")
    tonal_variants: List[TonalVariant] = Field(
        default=[TonalVariant.NEUTRAL],
        description="Tonal variants to generate (for memos)"
    )
    min_citations: int = Field(default=5, description="Minimum citations required")
    max_length: int = Field(default=5000, description="Maximum length in words")
    template: Optional[str] = Field(default=None, description="Custom template")


class SynthesizerOutput(AgentOutput):
    """Output specific to Synthesizer agent."""
    primary_artifact: Optional[Artifact] = None
    tonal_variants: Dict[str, Artifact] = Field(default_factory=dict)
    citation_count: int = 0
    citation_coverage: float = 0.0  # Percentage of assertions with citations


class SynthesizerAgent(EphemeralAgent[SynthesizerOutput]):
    """
    Synthesizer ephemeral agent for producing artifacts.

    Produces:
    - Reports: Comprehensive documents with sections and analysis
    - Memos: Shorter, targeted communications
    - Timelines: Chronological event sequences
    - Newsletters: Curated updates and summaries
    - Briefings: Executive-style quick reads

    Features:
    - Retrieval-grounded assertions
    - Self-check citation coverage
    - Multiple tonal variants for memos
    """

    def __init__(
        self,
        config: SynthesizerConfig,
        memory: Optional[AgentMemory] = None,
        client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        super().__init__(config, memory, client)
        self.synthesizer_config = config
        self.citations: List[Citation] = []
        self.source_items: Dict[str, Dict[str, Any]] = {}

        # Register tools
        for tool_name in ["corpus_search", "graph_query", "item_fetch", "draft_artifact"]:
            tool = tool_catalog.get(tool_name)
            if tool:
                self.register_tool(tool_name, tool)

    @property
    def artifact_type(self) -> ArtifactType:
        return self.synthesizer_config.artifact_type

    @property
    def topic(self) -> str:
        return self.synthesizer_config.topic

    def get_system_prompt(self) -> str:
        type_instructions = self._get_type_instructions()

        return f"""You are a Synthesizer agent for the Lantern Narrative Intelligence Platform.

Your task is to produce a {self.artifact_type.value} on the topic:
{self.topic}

{type_instructions}

Core Principles:
1. EVERY factual assertion must be grounded in retrieved evidence
2. Use citations liberally - cite specific items by ID
3. Never fabricate information - if uncertain, note the uncertainty
4. Maintain appropriate tone for the artifact type
5. Structure content logically with clear sections

Citation Format:
- Use inline citations: "Statement [item_123]"
- List full citations at the end
- Include relevant quotes from sources

You have access to:
- corpus_search: Search for relevant documents
- graph_query: Query entities, events, and relationships
- item_fetch: Get full content of specific items
- draft_artifact: Submit the final artifact

Process:
1. Search for relevant material
2. Gather supporting evidence
3. Outline the artifact structure
4. Draft content with citations
5. Self-check citation coverage
6. Submit the artifact

Minimum citations required: {self.synthesizer_config.min_citations}
Maximum length: {self.synthesizer_config.max_length} words
"""

    def _get_type_instructions(self) -> str:
        """Get specific instructions based on artifact type."""
        instructions = {
            ArtifactType.REPORT: """
Report Requirements:
- Executive summary at the beginning
- Clear section structure with headings
- Analysis and interpretation of findings
- Conclusions and recommendations
- Full citation list
""",
            ArtifactType.MEMO: """
Memo Requirements:
- Clear, concise communication
- Key points highlighted
- Action items if applicable
- Brief supporting evidence
- Professional tone
""",
            ArtifactType.TIMELINE: """
Timeline Requirements:
- Chronological ordering of events
- Clear date/time markers
- Brief description for each event
- Links between related events
- Key turning points highlighted
""",
            ArtifactType.NEWSLETTER: """
Newsletter Requirements:
- Engaging headlines
- Mix of topics and story types
- Brief summaries with links to full content
- Visual section breaks
- Curated highlights
""",
            ArtifactType.BRIEFING: """
Briefing Requirements:
- Ultra-concise format
- Key facts only
- Bullet points preferred
- Critical information first
- Decision-relevant framing
""",
        }
        return instructions.get(self.artifact_type, "")

    async def execute(self) -> SynthesizerOutput:
        """Execute artifact synthesis."""
        primary_artifact = None
        tonal_variants: Dict[str, Artifact] = {}

        try:
            # Step 1: Gather source material
            await self._gather_sources()

            # Step 2: Build outline
            outline = await self._build_outline()

            # Step 3: Draft primary artifact
            primary_artifact = await self._draft_artifact(outline)

            # Step 4: Self-check citations
            coverage = await self._check_citation_coverage(primary_artifact)

            # Step 5: Improve coverage if needed
            if coverage < 0.8:
                primary_artifact = await self._improve_citations(primary_artifact)
                coverage = await self._check_citation_coverage(primary_artifact)

            # Step 6: Generate tonal variants for memos
            if self.artifact_type == ArtifactType.MEMO:
                for tone in self.synthesizer_config.tonal_variants:
                    if tone != TonalVariant.NEUTRAL:  # Already have neutral
                        variant = await self._generate_tonal_variant(primary_artifact, tone)
                        if variant:
                            tonal_variants[tone.value] = variant

            # Step 7: Submit artifact(s)
            await self._submit_artifacts(primary_artifact, tonal_variants)

            return SynthesizerOutput(
                success=True,
                stop_condition=StopCondition.GOAL_MET,
                artifacts=[primary_artifact] + list(tonal_variants.values()),
                primary_artifact=primary_artifact,
                tonal_variants=tonal_variants,
                citation_count=len(self.citations),
                citation_coverage=coverage,
                execution_summary={
                    "agent_id": self.agent_id,
                    "artifact_type": self.artifact_type.value,
                    "topic": self.topic,
                    "citations": len(self.citations),
                    "coverage": coverage,
                    "variants": len(tonal_variants),
                    "budget_used": {
                        "tokens": self.config.budget.tokens_used,
                        "cost": self.config.budget.cost_incurred,
                    },
                },
            )

        except Exception as e:
            return SynthesizerOutput(
                success=False,
                stop_condition=StopCondition.ERROR,
                error_message=str(e),
                primary_artifact=primary_artifact,
                citation_count=len(self.citations),
            )

    async def _gather_sources(self) -> None:
        """Gather source material for the artifact."""
        corpus_tool = self._tools.get("corpus_search")
        graph_tool = self._tools.get("graph_query")
        item_tool = self._tools.get("item_fetch")

        # Search corpus
        if corpus_tool:
            # Main topic search
            result = await corpus_tool.execute(
                query=self.topic,
                limit=30,
            )

            if result.success:
                items = result.data.get("items", [])
                for item in items:
                    self.source_items[item["id"]] = item

            # Scope-specific searches
            for key, value in self.synthesizer_config.scope.items():
                if isinstance(value, str):
                    result = await corpus_tool.execute(
                        query=f"{key}: {value}",
                        limit=10,
                    )
                    if result.success:
                        for item in result.data.get("items", []):
                            self.source_items[item["id"]] = item

        # Query graph for relevant entities
        if graph_tool:
            result = await graph_tool.execute(
                query_type="entity_neighbors",
                limit=50,
            )

            if result.success:
                entities = result.data.get("nodes", [])
                self.memory.working_memory["entities"] = entities

        # Fetch full content for top items
        if item_tool:
            top_items = sorted(
                self.source_items.values(),
                key=lambda x: x.get("relevance_score", 0),
                reverse=True,
            )[:10]

            for item in top_items:
                result = await item_tool.execute(item_id=item["id"])
                if result.success:
                    self.source_items[item["id"]].update(result.data)

        self.memory.working_memory["source_count"] = len(self.source_items)

    async def _build_outline(self) -> Dict[str, Any]:
        """Build an outline for the artifact."""
        source_summary = "\n".join([
            f"- {item.get('title', 'Untitled')}: {item.get('snippet', '')[:100]}"
            for item in list(self.source_items.values())[:20]
        ])

        messages = [
            {
                "role": "user",
                "content": f"""Create an outline for a {self.artifact_type.value} on:
{self.topic}

Available sources:
{source_summary}

Scope: {json.dumps(self.synthesizer_config.scope)}

Return a JSON outline:
{{
    "title": "...",
    "sections": [
        {{
            "heading": "...",
            "key_points": ["...", "..."],
            "relevant_sources": ["item_id", ...]
        }}
    ]
}}
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=1000)
            content = response.content[0].text.strip()

            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())

        except Exception:
            pass

        # Fallback outline
        return {
            "title": self.topic,
            "sections": [
                {"heading": "Overview", "key_points": [], "relevant_sources": []},
                {"heading": "Key Findings", "key_points": [], "relevant_sources": []},
                {"heading": "Conclusion", "key_points": [], "relevant_sources": []},
            ],
        }

    async def _draft_artifact(self, outline: Dict[str, Any]) -> Artifact:
        """Draft the main artifact content."""
        sections: List[ContentSection] = []

        for section_outline in outline.get("sections", []):
            section = await self._draft_section(section_outline)
            sections.append(section)

        # Combine into full content
        full_content = f"# {outline.get('title', self.topic)}\n\n"

        for section in sections:
            full_content += f"## {section.heading}\n\n"
            full_content += section.content + "\n\n"

        # Add citations section
        full_content += "## References\n\n"
        for i, citation in enumerate(self.citations, 1):
            item = self.source_items.get(citation.item_id, {})
            source_name = item.get("source", {}).get("name", "Unknown")
            title = item.get("title", "Untitled")
            full_content += f"[{citation.id}] {source_name}: \"{title}\"\n"

        artifact = Artifact(
            type=self.artifact_type.value,
            title=outline.get("title", self.topic),
            content=full_content,
            citations=[c.model_dump() for c in self.citations],
            created_by=self.agent_id,
            metadata={
                "topic": self.topic,
                "scope": self.synthesizer_config.scope,
                "section_count": len(sections),
            },
        )

        return artifact

    async def _draft_section(self, section_outline: Dict[str, Any]) -> ContentSection:
        """Draft a single section with citations."""
        heading = section_outline.get("heading", "Section")
        key_points = section_outline.get("key_points", [])
        relevant_sources = section_outline.get("relevant_sources", [])

        # Gather source content for this section
        source_content = []
        for source_id in relevant_sources:
            if source_id in self.source_items:
                item = self.source_items[source_id]
                source_content.append(f"[{source_id}]: {item.get('content', item.get('snippet', ''))[:500]}")

        if not source_content:
            # Use all sources
            for item_id, item in list(self.source_items.items())[:10]:
                source_content.append(f"[{item_id}]: {item.get('content', item.get('snippet', ''))[:300]}")

        messages = [
            {
                "role": "user",
                "content": f"""Write the "{heading}" section for a {self.artifact_type.value} on {self.topic}.

Key points to cover:
{json.dumps(key_points)}

Available sources:
{chr(10).join(source_content[:10])}

Requirements:
1. Write 2-4 paragraphs
2. Include inline citations in format [item_id] for each factual claim
3. Use quotes from sources where appropriate
4. Maintain professional tone

Return JSON:
{{
    "content": "...",
    "citations_used": [
        {{"item_id": "...", "quote": "...", "context": "...", "used_for": "..."}}
    ]
}}
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=1500)
            content_text = response.content[0].text.strip()

            import re
            json_match = re.search(r'\{.*\}', content_text, re.DOTALL)
            if json_match:
                section_data = json.loads(json_match.group())

                # Process citations
                section_citations = []
                for cit_data in section_data.get("citations_used", []):
                    citation = Citation(
                        id=f"cite_{len(self.citations) + len(section_citations) + 1}",
                        item_id=cit_data.get("item_id", ""),
                        quote=cit_data.get("quote", ""),
                        context=cit_data.get("context", ""),
                        used_for=cit_data.get("used_for", heading),
                    )
                    section_citations.append(citation)
                    self.citations.append(citation)

                return ContentSection(
                    heading=heading,
                    content=section_data.get("content", ""),
                    citations=section_citations,
                )

        except Exception:
            pass

        return ContentSection(heading=heading, content="[Content generation failed]")

    async def _check_citation_coverage(self, artifact: Artifact) -> float:
        """Check what percentage of assertions have citations."""
        content = artifact.content

        messages = [
            {
                "role": "user",
                "content": f"""Analyze this text for citation coverage.

Text:
{content[:4000]}

For each factual assertion:
1. Is it cited with [item_id] or similar?
2. Is the citation relevant to the claim?

Return JSON:
{{
    "total_assertions": X,
    "cited_assertions": Y,
    "uncited_assertions": ["list of uncited claims"],
    "coverage_percentage": Z
}}
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=500)
            content_text = response.content[0].text.strip()

            import re
            json_match = re.search(r'\{.*\}', content_text, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
                coverage = analysis.get("coverage_percentage", 0)

                # Store uncited for potential improvement
                self.memory.working_memory["uncited_assertions"] = analysis.get("uncited_assertions", [])

                return coverage / 100.0 if coverage > 1 else coverage

        except Exception:
            pass

        # Estimate based on citation count
        return min(1.0, len(self.citations) / max(self.synthesizer_config.min_citations, 1))

    async def _improve_citations(self, artifact: Artifact) -> Artifact:
        """Improve citation coverage for uncited assertions."""
        uncited = self.memory.working_memory.get("uncited_assertions", [])

        if not uncited:
            return artifact

        corpus_tool = self._tools.get("corpus_search")

        # Search for sources to cite
        for assertion in uncited[:5]:  # Limit iterations
            if corpus_tool:
                result = await corpus_tool.execute(query=assertion, limit=3)

                if result.success:
                    items = result.data.get("items", [])
                    if items:
                        best_item = items[0]
                        citation = Citation(
                            id=f"cite_{len(self.citations) + 1}",
                            item_id=best_item["id"],
                            quote=best_item.get("snippet", "")[:200],
                            context=assertion,
                            used_for="supplementary citation",
                        )
                        self.citations.append(citation)

                        # Add to artifact
                        artifact.citations.append(citation.model_dump())

        return artifact

    async def _generate_tonal_variant(
        self,
        primary: Artifact,
        tone: TonalVariant,
    ) -> Optional[Artifact]:
        """Generate a tonal variant of a memo."""
        tone_instructions = {
            TonalVariant.EXECUTIVE: "Rewrite for executive audience: ultra-brief, action-focused, key decisions highlighted",
            TonalVariant.ANALYTICAL: "Rewrite with analytical focus: detailed evidence, nuanced analysis, caveats noted",
            TonalVariant.URGENT: "Rewrite with urgency: alert-style, critical points first, immediate actions needed",
        }

        messages = [
            {
                "role": "user",
                "content": f"""Transform this memo into a {tone.value} variant.

Original:
{primary.content[:3000]}

Instructions: {tone_instructions.get(tone, '')}

Maintain all factual content and citations. Only change tone and emphasis.

Return the transformed text only.
"""
            }
        ]

        try:
            response = await self.call_claude(messages, max_tokens=2000)
            variant_content = response.content[0].text.strip()

            variant = Artifact(
                type=self.artifact_type.value,
                title=f"{primary.title} ({tone.value.title()})",
                content=variant_content,
                citations=primary.citations,
                created_by=self.agent_id,
                metadata={
                    "parent_artifact": primary.id,
                    "tonal_variant": tone.value,
                },
            )

            return variant

        except Exception:
            return None

    async def _submit_artifacts(
        self,
        primary: Artifact,
        variants: Dict[str, Artifact],
    ) -> None:
        """Submit artifacts to the draft system."""
        draft_tool = self._tools.get("draft_artifact")
        if not draft_tool:
            return

        # Submit primary
        await draft_tool.execute(
            artifact_type=primary.type,
            title=primary.title,
            content=primary.content,
            citations=primary.citations,
            metadata=primary.metadata,
        )

        # Submit variants
        for tone, variant in variants.items():
            await draft_tool.execute(
                artifact_type=variant.type,
                title=variant.title,
                content=variant.content,
                citations=variant.citations,
                metadata=variant.metadata,
            )

    def check_goal_met(self) -> bool:
        """Check if synthesis is complete."""
        return (
            len(self.citations) >= self.synthesizer_config.min_citations and
            self.memory.working_memory.get("artifact_drafted", False)
        )

    def check_no_new_info(self) -> bool:
        """Check if no more sources available."""
        return len(self.source_items) == 0
