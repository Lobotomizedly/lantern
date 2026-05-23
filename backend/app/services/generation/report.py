"""
Report Generator

Creates long-form analysis reports for subjects/narratives over timeframes.
Includes sections for summary, narrative landscape, key events, sentiment
trends, notable items, and open questions.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from app.services.generation.base import (
    BaseGenerator,
    GenerationContext,
    GenerationResult,
    GeneratorConfig,
    SectionResult,
    SourceMaterial,
)
from app.services.generation.templates import (
    ReportTemplate,
    TemplateManager,
    TemplateSection,
)

logger = logging.getLogger(__name__)


class ReportConfig(GeneratorConfig):
    """Configuration for report generation."""

    include_citations_section: bool = Field(
        default=True,
        description="Include a final citations/references section",
    )
    include_summary_stats: bool = Field(
        default=True,
        description="Include statistics in the summary",
    )
    max_events: int = Field(
        default=10,
        description="Maximum number of key events to include",
    )
    max_notable_items: int = Field(
        default=5,
        description="Maximum notable items to highlight",
    )
    sentiment_granularity: str = Field(
        default="daily",
        description="Granularity for sentiment trends (daily, weekly, monthly)",
    )
    custom_sections: List[str] = Field(
        default_factory=list,
        description="Additional custom section names to include",
    )


class ReportGenerator(BaseGenerator[ReportConfig]):
    """
    Generates comprehensive long-form analysis reports.

    Reports include:
    - Executive summary with key findings
    - Narrative landscape analysis
    - Key events timeline
    - Sentiment trend analysis
    - Notable items highlights
    - Open questions and areas for further investigation

    All claims are grounded with citations to source materials.
    """

    def __init__(
        self,
        config: Optional[ReportConfig] = None,
        template: Optional[ReportTemplate] = None,
        **kwargs,
    ):
        """
        Initialize the report generator.

        Args:
            config: Report generation configuration
            template: Custom report template
            **kwargs: Additional arguments for base class
        """
        super().__init__(config=config, **kwargs)

        # Load template
        if template:
            self._template = template
        else:
            manager = TemplateManager()
            self._template = manager.get_default_template(
                template_type=self._template_type()
            )

    def _template_type(self):
        """Get template type for this generator."""
        from app.services.generation.templates import TemplateType
        return TemplateType.REPORT

    def _default_config(self) -> ReportConfig:
        """Return default report configuration."""
        return ReportConfig()

    def _get_artifact_type(self) -> str:
        """Return the artifact type string."""
        return "report"

    def _get_sections(self) -> List[str]:
        """Return ordered list of section names."""
        # Use template sections if available
        if self._template and self._template.sections:
            sorted_sections = sorted(
                self._template.sections,
                key=lambda s: s.order,
            )
            section_names = [s.name for s in sorted_sections]
        else:
            # Default sections
            section_names = [
                "summary",
                "narrative_landscape",
                "key_events",
                "sentiment_trend",
                "notable_items",
                "open_questions",
            ]

        # Add custom sections
        section_names.extend(self.config.custom_sections)

        return section_names

    def _get_template_section(self, section_name: str) -> Optional[TemplateSection]:
        """Get the template section definition."""
        if not self._template:
            return None

        for section in self._template.sections:
            if section.name == section_name:
                return section

        return None

    def _get_section_prompt(
        self,
        section_name: str,
        context: GenerationContext,
        previous_sections: Dict[str, SectionResult],
    ) -> str:
        """
        Build the prompt for generating a specific section.

        Args:
            section_name: Name of the section to generate
            context: Generation context with source materials
            previous_sections: Already generated sections

        Returns:
            Complete prompt for the Claude API
        """
        # Get template section if available
        template_section = self._get_template_section(section_name)

        # Build system context
        system_prompt = self._template.system_prompt if self._template else (
            "You are an expert narrative intelligence analyst creating a "
            "comprehensive report. All claims must be cited using [N] format."
        )

        # Build source context
        source_context = self._build_source_context(context.source_materials)

        # Build previous sections context
        previous_context = ""
        if previous_sections:
            previous_context = "\n\nPREVIOUSLY GENERATED SECTIONS:\n"
            for name, result in previous_sections.items():
                previous_context += f"\n### {name.replace('_', ' ').title()}\n"
                previous_context += result.content[:500] + "...\n"

        # Get section-specific prompt
        if template_section:
            section_prompt = template_section.prompt
        else:
            section_prompt = self._get_default_section_prompt(section_name, context)

        # Build subject and timeframe context
        subject_context = ""
        if context.subject_name:
            subject_context = f"Subject: {context.subject_name}\n"
        if context.timeframe_start and context.timeframe_end:
            subject_context += (
                f"Timeframe: {context.timeframe_start.strftime('%Y-%m-%d')} to "
                f"{context.timeframe_end.strftime('%Y-%m-%d')}\n"
            )

        # Build citation instructions
        citation_instructions = self._build_citation_instructions()

        # Assemble full prompt
        prompt = f"""{system_prompt}

{subject_context}

{citation_instructions}

SOURCE MATERIALS:
{source_context}

{previous_context}

TASK: Generate the "{section_name.replace('_', ' ').title()}" section.

{section_prompt}

{self._get_section_instructions(section_name)}

Remember: Every factual claim must be cited using [N] format referring to the source index.
End your response with a CITATIONS section listing sources used."""

        return prompt

    def _get_default_section_prompt(
        self,
        section_name: str,
        context: GenerationContext,
    ) -> str:
        """Get default prompt for a section if not in template."""
        prompts = {
            "summary": """Write a concise executive summary (2-3 paragraphs) covering:
- The subject and timeframe of analysis
- Key findings and their significance
- Critical developments requiring attention

Keep it high-level but impactful. Cite key claims.""",

            "narrative_landscape": """Analyze the narrative landscape around this subject:
- What are the dominant narratives being told?
- Who are the key voices/sources shaping discourse?
- What themes are emerging or declining?
- Are there competing narratives or framings?

Provide specific examples from sources with citations.""",

            "key_events": f"""Identify and analyze the top {self.config.max_events} key events:
- List major events chronologically
- Explain significance of each event
- Connect events to broader narratives
- Note any causal relationships

Each event must be cited to its source.""",

            "sentiment_trend": """Analyze sentiment trends:
- Overall sentiment direction (positive/negative/neutral)
- Sentiment by source type or audience
- Notable sentiment shifts and their triggers
- Comparison to previous periods if relevant

Support observations with cited examples.""",

            "notable_items": f"""Highlight the top {self.config.max_notable_items} notable items:
- Unusually high-impact content
- Viral or highly-shared items
- Items from influential sources
- Surprising or unexpected coverage

For each, explain why it's notable and cite the source.""",

            "open_questions": """Identify open questions and areas for further investigation:
- Unanswered questions raised by the analysis
- Information gaps
- Emerging situations to monitor
- Recommended follow-up actions

Be specific about what additional information would be valuable.""",
        }

        return prompts.get(section_name, f"Generate content for the {section_name} section.")

    def _get_section_instructions(self, section_name: str) -> str:
        """Get formatting instructions for a section."""
        instructions = {
            "summary": "Format as 2-3 well-structured paragraphs.",
            "narrative_landscape": "Use subheadings for different narrative threads.",
            "key_events": "Format as a numbered list with details for each event.",
            "sentiment_trend": "Include directional indicators (rising, falling, stable).",
            "notable_items": "Format as a numbered list with brief explanations.",
            "open_questions": "Format as a bulleted list of questions/areas.",
        }
        return instructions.get(section_name, "")

    async def generate_report(
        self,
        subject_id: UUID,
        subject_name: str,
        timeframe_start: datetime,
        timeframe_end: datetime,
        source_materials: List[SourceMaterial],
        title: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        Generate a complete report.

        Args:
            subject_id: ID of the subject being analyzed
            subject_name: Name of the subject
            timeframe_start: Start of analysis period
            timeframe_end: End of analysis period
            source_materials: Source materials to analyze
            title: Optional custom title
            additional_context: Additional context for generation

        Returns:
            GenerationResult with complete report
        """
        context = GenerationContext(
            subject_id=subject_id,
            subject_name=subject_name,
            timeframe_start=timeframe_start,
            timeframe_end=timeframe_end,
            source_materials=source_materials,
            additional_context=additional_context or {},
        )

        result = await self.generate(context, title=title)

        # Add citations section if configured
        if self.config.include_citations_section and result.all_citations:
            from app.services.generation.citations import CitationManager

            citation_manager = CitationManager()
            citations_section = citation_manager.generate_bibliography(
                result.all_citations,
                title="References",
                include_item_ids=False,
            )
            result.combined_content += f"\n{citations_section}"

        # Add summary statistics if configured
        if self.config.include_summary_stats:
            result.metadata["summary_stats"] = {
                "source_count": len(source_materials),
                "section_count": len(result.sections),
                "citation_count": len(result.all_citations),
                "grounding_score": result.overall_grounding_score,
                "generation_time_sec": result.total_generation_time_ms / 1000,
            }

        return result

    async def generate_from_items(
        self,
        subject_id: UUID,
        subject_name: str,
        items: List[Any],
        timeframe_start: Optional[datetime] = None,
        timeframe_end: Optional[datetime] = None,
        title: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate a report from Item objects.

        Convenience method that converts Items to SourceMaterial.

        Args:
            subject_id: Subject ID
            subject_name: Subject name
            items: List of Item objects
            timeframe_start: Optional start date
            timeframe_end: Optional end date
            title: Optional title

        Returns:
            GenerationResult
        """
        # Convert items to source materials
        source_materials = []
        for item in items:
            source_materials.append(
                SourceMaterial(
                    item_id=item.id if hasattr(item, "id") else UUID(str(item.get("id"))),
                    title=item.title if hasattr(item, "title") else item.get("title", "Untitled"),
                    content=item.content if hasattr(item, "content") else item.get("content", ""),
                    source_type=item.item_type if hasattr(item, "item_type") else item.get("item_type", "item"),
                    url=item.url if hasattr(item, "url") else item.get("url"),
                    published_at=item.published_at if hasattr(item, "published_at") else item.get("published_at"),
                )
            )

        # Determine timeframe from items if not provided
        if not timeframe_start and source_materials:
            dates = [
                s.published_at for s in source_materials
                if s.published_at
            ]
            if dates:
                timeframe_start = min(dates)

        if not timeframe_end and source_materials:
            dates = [
                s.published_at for s in source_materials
                if s.published_at
            ]
            if dates:
                timeframe_end = max(dates)

        # Default to current date if still not set
        if not timeframe_start:
            timeframe_start = datetime.utcnow()
        if not timeframe_end:
            timeframe_end = datetime.utcnow()

        return await self.generate_report(
            subject_id=subject_id,
            subject_name=subject_name,
            timeframe_start=timeframe_start,
            timeframe_end=timeframe_end,
            source_materials=source_materials,
            title=title,
        )

    def set_custom_template(self, template: ReportTemplate) -> None:
        """
        Set a custom template for report generation.

        Args:
            template: Custom ReportTemplate
        """
        self._template = template

    def add_custom_section(
        self,
        name: str,
        prompt: str,
        order: int = 99,
        required: bool = True,
    ) -> None:
        """
        Add a custom section to the report.

        Args:
            name: Section name
            prompt: Generation prompt
            order: Order in report (higher = later)
            required: Whether section is required
        """
        from app.services.generation.templates import TemplateSection

        if not self._template:
            manager = TemplateManager()
            self._template = manager.get_default_template(self._template_type())

        section = TemplateSection(
            name=name,
            title=name.replace("_", " ").title(),
            prompt=prompt,
            order=order,
            required=required,
        )

        self._template.sections.append(section)

        if name not in self.config.custom_sections:
            self.config.custom_sections.append(name)
