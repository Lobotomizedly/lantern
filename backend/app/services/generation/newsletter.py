"""
Newsletter Generator

Creates recurring intelligence digests across multiple subjects. Assembles
content from the period's Sentinel flags and provides top narratives summary.
Supports templated structure for consistent formatting.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.generation.base import (
    BaseGenerator,
    GenerationContext,
    GenerationResult,
    GeneratorConfig,
    SectionResult,
    SourceMaterial,
)
from app.services.generation.templates import (
    NewsletterTemplate,
    TemplateManager,
    TemplateSection,
)

logger = logging.getLogger(__name__)


class NewsletterFrequency(str, Enum):
    """Newsletter publication frequency."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class SentinelFlag(BaseModel):
    """A flag raised by the Sentinel monitoring agent."""

    id: UUID
    flag_type: str = Field(..., description="Type: spike, emergence, sentiment_shift, etc.")
    severity: str = Field(default="info", description="info, warning, alert, critical")
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    title: str
    description: str
    triggered_at: datetime
    evidence_item_ids: List[UUID] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SubjectUpdate(BaseModel):
    """Update summary for a single subject."""

    subject_id: UUID
    subject_name: str
    summary: str
    key_developments: List[str] = Field(default_factory=list)
    sentiment_direction: Optional[str] = None
    item_count: int = 0
    notable_item_ids: List[UUID] = Field(default_factory=list)


class NewsletterConfig(GeneratorConfig):
    """Configuration for newsletter generation."""

    frequency: NewsletterFrequency = Field(
        default=NewsletterFrequency.WEEKLY,
        description="Publication frequency",
    )
    max_flags_per_section: int = Field(
        default=5,
        description="Maximum flags to include",
    )
    max_narratives: int = Field(
        default=5,
        description="Maximum top narratives to summarize",
    )
    include_sentiment_summary: bool = Field(
        default=True,
        description="Include sentiment overview",
    )
    include_looking_ahead: bool = Field(
        default=True,
        description="Include forward-looking section",
    )
    subjects_to_cover: List[UUID] = Field(
        default_factory=list,
        description="Specific subjects to include",
    )
    audience: Optional[str] = Field(
        default=None,
        description="Target audience description",
    )


class NewsletterResult(GenerationResult):
    """Result containing newsletter-specific data."""

    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    frequency: NewsletterFrequency = NewsletterFrequency.WEEKLY
    flags_included: int = 0
    subjects_covered: int = 0
    subject_summaries: List[SubjectUpdate] = Field(default_factory=list)


class NewsletterGenerator(BaseGenerator[NewsletterConfig]):
    """
    Generates recurring intelligence digests/newsletters.

    Features:
    - Multi-subject coverage
    - Sentinel flag integration
    - Top narratives summary
    - Templated structure
    - Configurable frequency
    - Full citation support
    """

    def __init__(
        self,
        config: Optional[NewsletterConfig] = None,
        template: Optional[NewsletterTemplate] = None,
        **kwargs,
    ):
        """
        Initialize the newsletter generator.

        Args:
            config: Newsletter configuration
            template: Custom newsletter template
            **kwargs: Additional arguments for base class
        """
        super().__init__(config=config, **kwargs)

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
        return TemplateType.NEWSLETTER

    def _default_config(self) -> NewsletterConfig:
        """Return default newsletter configuration."""
        return NewsletterConfig()

    def _get_artifact_type(self) -> str:
        """Return the artifact type string."""
        return "newsletter"

    def _get_sections(self) -> List[str]:
        """Return ordered list of section names."""
        if self._template and self._template.sections:
            sorted_sections = sorted(
                self._template.sections,
                key=lambda s: s.order,
            )
            section_names = [s.name for s in sorted_sections]
        else:
            section_names = [
                "top_story",
                "sentinel_flags",
                "narrative_summary",
                "by_subject",
            ]
            if self.config.include_looking_ahead:
                section_names.append("looking_ahead")

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
        """Build the prompt for generating a specific section."""
        template_section = self._get_template_section(section_name)

        system_prompt = self._template.system_prompt if self._template else (
            "Create an engaging intelligence digest summarizing the period's developments."
        )

        source_context = self._build_source_context(context.source_materials)

        # Build flags context if available
        flags_context = self._build_flags_context(context)

        # Build subjects context if available
        subjects_context = self._build_subjects_context(context)

        previous_context = ""
        if previous_sections:
            previous_context = "\n\nPREVIOUS SECTIONS:\n"
            for name, result in previous_sections.items():
                previous_context += f"\n### {name}\n{result.content[:500]}...\n"

        if template_section:
            section_prompt = template_section.prompt
        else:
            section_prompt = self._get_default_section_prompt(section_name)

        # Period context
        period_context = ""
        if context.timeframe_start and context.timeframe_end:
            period_context = (
                f"REPORTING PERIOD: {context.timeframe_start.strftime('%B %d, %Y')} to "
                f"{context.timeframe_end.strftime('%B %d, %Y')}\n"
            )

        # Audience context
        audience_context = ""
        if self.config.audience:
            audience_context = f"TARGET AUDIENCE: {self.config.audience}\n"

        prompt = f"""{system_prompt}

{period_context}
{audience_context}

{self._build_citation_instructions()}

{flags_context}

{subjects_context}

SOURCE MATERIALS:
{source_context}

{previous_context}

TASK: Generate the "{section_name.replace('_', ' ').title()}" section.

{section_prompt}

Remember: Cite all facts using [N] format."""

        return prompt

    def _build_flags_context(self, context: GenerationContext) -> str:
        """Build context from Sentinel flags."""
        flags = context.additional_context.get("sentinel_flags", [])
        if not flags:
            return ""

        lines = ["SENTINEL FLAGS FROM THIS PERIOD:"]

        for flag in flags[: self.config.max_flags_per_section]:
            if isinstance(flag, dict):
                flag_type = flag.get("flag_type", "unknown")
                severity = flag.get("severity", "info")
                title = flag.get("title", "")
                description = flag.get("description", "")
            else:
                flag_type = getattr(flag, "flag_type", "unknown")
                severity = getattr(flag, "severity", "info")
                title = getattr(flag, "title", "")
                description = getattr(flag, "description", "")

            lines.append(f"- [{severity.upper()}] {flag_type}: {title}")
            if description:
                lines.append(f"  {description[:200]}")

        return "\n".join(lines)

    def _build_subjects_context(self, context: GenerationContext) -> str:
        """Build context from subject updates."""
        subjects = context.additional_context.get("subject_updates", [])
        if not subjects:
            return ""

        lines = ["SUBJECTS BEING MONITORED:"]

        for subject in subjects:
            if isinstance(subject, dict):
                name = subject.get("subject_name", "Unknown")
                item_count = subject.get("item_count", 0)
            else:
                name = getattr(subject, "subject_name", "Unknown")
                item_count = getattr(subject, "item_count", 0)

            lines.append(f"- {name} ({item_count} items)")

        return "\n".join(lines)

    def _get_default_section_prompt(self, section_name: str) -> str:
        """Get default prompt for a section."""
        prompts = {
            "top_story": """Identify and summarize the single most important story/development.
- What happened?
- Why does it matter?
- What are the implications?

Write 2-3 engaging paragraphs with citations.""",

            "sentinel_flags": f"""List the top {self.config.max_flags_per_section} significant alerts from monitoring:
- New narrative emergences
- Sentiment shifts
- Source activity spikes
- Unusual patterns

Format as a prioritized list with brief explanations. Include citations.""",

            "narrative_summary": f"""Summarize the top {self.config.max_narratives} narratives:
- What stories dominated?
- How did narratives evolve?
- What new angles emerged?

Provide cited examples for each narrative.""",

            "by_subject": """For each monitored subject, provide a brief update:
- Key developments
- Notable items
- Sentiment direction

Keep each subject update to 2-3 sentences with citations.""",

            "looking_ahead": """Preview what to watch for:
- Upcoming events or dates
- Developing situations
- Potential narrative shifts
- Recommended monitoring focus""",
        }

        return prompts.get(section_name, f"Generate the {section_name} section.")

    async def generate_newsletter(
        self,
        period_start: datetime,
        period_end: datetime,
        source_materials: List[SourceMaterial],
        sentinel_flags: Optional[List[SentinelFlag]] = None,
        subject_updates: Optional[List[SubjectUpdate]] = None,
        title: Optional[str] = None,
    ) -> NewsletterResult:
        """
        Generate a complete newsletter.

        Args:
            period_start: Start of reporting period
            period_end: End of reporting period
            source_materials: Source materials to summarize
            sentinel_flags: Sentinel alerts from the period
            subject_updates: Per-subject update summaries
            title: Optional custom title

        Returns:
            NewsletterResult with newsletter content
        """
        # Build additional context
        additional_context: Dict[str, Any] = {}

        if sentinel_flags:
            additional_context["sentinel_flags"] = [
                f.model_dump() if hasattr(f, "model_dump") else f
                for f in sentinel_flags
            ]

        if subject_updates:
            additional_context["subject_updates"] = [
                s.model_dump() if hasattr(s, "model_dump") else s
                for s in subject_updates
            ]

        # Create generation context
        context = GenerationContext(
            timeframe_start=period_start,
            timeframe_end=period_end,
            source_materials=source_materials,
            additional_context=additional_context,
        )

        # Generate default title based on frequency
        if not title:
            freq_label = {
                NewsletterFrequency.DAILY: "Daily",
                NewsletterFrequency.WEEKLY: "Weekly",
                NewsletterFrequency.BIWEEKLY: "Bi-Weekly",
                NewsletterFrequency.MONTHLY: "Monthly",
            }
            title = f"{freq_label.get(self.config.frequency, 'Intelligence')} Digest - {period_end.strftime('%B %d, %Y')}"

        # Generate base result
        base_result = await self.generate(context, title=title)

        # Create newsletter result
        result = NewsletterResult(
            artifact_id=base_result.artifact_id,
            artifact_type="newsletter",
            title=base_result.title,
            sections=base_result.sections,
            combined_content=base_result.combined_content,
            all_citations=base_result.all_citations,
            total_tokens=base_result.total_tokens,
            total_generation_time_ms=base_result.total_generation_time_ms,
            overall_grounding_score=base_result.overall_grounding_score,
            metadata=base_result.metadata,
            warnings=base_result.warnings,
            period_start=period_start,
            period_end=period_end,
            frequency=self.config.frequency,
            flags_included=len(sentinel_flags) if sentinel_flags else 0,
            subjects_covered=len(subject_updates) if subject_updates else 0,
            subject_summaries=subject_updates or [],
        )

        result.metadata["period"] = {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "frequency": self.config.frequency.value,
        }

        return result

    async def generate_daily_digest(
        self,
        date: datetime,
        source_materials: List[SourceMaterial],
        sentinel_flags: Optional[List[SentinelFlag]] = None,
        subject_updates: Optional[List[SubjectUpdate]] = None,
    ) -> NewsletterResult:
        """
        Generate a daily digest.

        Args:
            date: Date for the digest
            source_materials: Source materials
            sentinel_flags: Sentinel alerts
            subject_updates: Subject updates

        Returns:
            NewsletterResult
        """
        self.config.frequency = NewsletterFrequency.DAILY

        period_start = datetime(date.year, date.month, date.day, 0, 0, 0)
        period_end = datetime(date.year, date.month, date.day, 23, 59, 59)

        return await self.generate_newsletter(
            period_start=period_start,
            period_end=period_end,
            source_materials=source_materials,
            sentinel_flags=sentinel_flags,
            subject_updates=subject_updates,
            title=f"Daily Intelligence Digest - {date.strftime('%B %d, %Y')}",
        )

    async def generate_weekly_digest(
        self,
        week_ending: datetime,
        source_materials: List[SourceMaterial],
        sentinel_flags: Optional[List[SentinelFlag]] = None,
        subject_updates: Optional[List[SubjectUpdate]] = None,
    ) -> NewsletterResult:
        """
        Generate a weekly digest.

        Args:
            week_ending: Last day of the week
            source_materials: Source materials
            sentinel_flags: Sentinel alerts
            subject_updates: Subject updates

        Returns:
            NewsletterResult
        """
        self.config.frequency = NewsletterFrequency.WEEKLY

        period_end = datetime(
            week_ending.year,
            week_ending.month,
            week_ending.day,
            23, 59, 59,
        )
        period_start = period_end - timedelta(days=6)
        period_start = datetime(
            period_start.year,
            period_start.month,
            period_start.day,
            0, 0, 0,
        )

        return await self.generate_newsletter(
            period_start=period_start,
            period_end=period_end,
            source_materials=source_materials,
            sentinel_flags=sentinel_flags,
            subject_updates=subject_updates,
            title=f"Weekly Intelligence Digest - Week of {period_start.strftime('%B %d, %Y')}",
        )

    async def generate_monthly_digest(
        self,
        year: int,
        month: int,
        source_materials: List[SourceMaterial],
        sentinel_flags: Optional[List[SentinelFlag]] = None,
        subject_updates: Optional[List[SubjectUpdate]] = None,
    ) -> NewsletterResult:
        """
        Generate a monthly digest.

        Args:
            year: Year
            month: Month (1-12)
            source_materials: Source materials
            sentinel_flags: Sentinel alerts
            subject_updates: Subject updates

        Returns:
            NewsletterResult
        """
        import calendar

        self.config.frequency = NewsletterFrequency.MONTHLY

        _, last_day = calendar.monthrange(year, month)

        period_start = datetime(year, month, 1, 0, 0, 0)
        period_end = datetime(year, month, last_day, 23, 59, 59)

        month_name = calendar.month_name[month]

        return await self.generate_newsletter(
            period_start=period_start,
            period_end=period_end,
            source_materials=source_materials,
            sentinel_flags=sentinel_flags,
            subject_updates=subject_updates,
            title=f"Monthly Intelligence Digest - {month_name} {year}",
        )

    def set_subjects(self, subject_ids: List[UUID]) -> None:
        """
        Set specific subjects to cover.

        Args:
            subject_ids: List of subject IDs
        """
        self.config.subjects_to_cover = subject_ids

    def set_audience(self, audience: str) -> None:
        """
        Set target audience.

        Args:
            audience: Audience description
        """
        self.config.audience = audience

    def set_frequency(self, frequency: NewsletterFrequency) -> None:
        """
        Set newsletter frequency.

        Args:
            frequency: Publication frequency
        """
        self.config.frequency = frequency
