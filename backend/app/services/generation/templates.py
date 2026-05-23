"""
Template Definitions

Provides template management for all artifact types including reports,
memos, timelines, and newsletters. Supports both built-in and custom templates.
"""

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TemplateType(str, Enum):
    """Types of templates available."""

    REPORT = "report"
    MEMO = "memo"
    TIMELINE = "timeline"
    NEWSLETTER = "newsletter"
    CUSTOM = "custom"


class TemplateSection(BaseModel):
    """Definition of a single template section."""

    name: str = Field(..., description="Section identifier")
    title: str = Field(..., description="Section display title")
    prompt: str = Field(..., description="Prompt for generating this section")
    required: bool = Field(default=True, description="Whether section is required")
    max_tokens: int = Field(default=1024, description="Max tokens for this section")
    order: int = Field(default=0, description="Section order in output")
    depends_on: List[str] = Field(
        default_factory=list,
        description="Sections that must be generated first",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Additional formatting instructions",
    )


class Template(BaseModel):
    """Base template definition."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., description="Template name")
    template_type: TemplateType
    description: Optional[str] = None
    sections: List[TemplateSection] = Field(default_factory=list)
    system_prompt: str = Field(
        default="You are an expert analyst creating well-cited, accurate content.",
        description="System prompt for all generations",
    )
    citation_instructions: str = Field(
        default="Cite all factual claims using [N] format.",
        description="Citation format instructions",
    )
    custom_variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom template variables",
    )


class ReportTemplate(Template):
    """Template for long-form reports."""

    template_type: TemplateType = TemplateType.REPORT

    @classmethod
    def default(cls) -> "ReportTemplate":
        """Create the default report template."""
        return cls(
            name="Standard Report",
            description="Comprehensive analysis report with full narrative coverage",
            system_prompt="""You are an expert narrative intelligence analyst creating a comprehensive report.
Your analysis must be:
- Well-structured and clear
- Fully grounded in the provided source materials
- Every factual claim must cite its source using [N] format
- Objective and balanced in assessment
- Actionable where appropriate""",
            sections=[
                TemplateSection(
                    name="summary",
                    title="Executive Summary",
                    order=1,
                    max_tokens=512,
                    prompt="""Write a concise executive summary (2-3 paragraphs) covering:
- The subject and timeframe of analysis
- Key findings and their significance
- Critical developments requiring attention

Keep it high-level but impactful. Cite key claims.""",
                ),
                TemplateSection(
                    name="narrative_landscape",
                    title="Narrative Landscape",
                    order=2,
                    max_tokens=1024,
                    depends_on=["summary"],
                    prompt="""Analyze the narrative landscape around this subject:
- What are the dominant narratives being told?
- Who are the key voices/sources shaping discourse?
- What themes are emerging or declining?
- Are there competing narratives or framings?

Provide specific examples from sources with citations.""",
                ),
                TemplateSection(
                    name="key_events",
                    title="Key Events",
                    order=3,
                    max_tokens=1024,
                    depends_on=["summary"],
                    prompt="""Identify and analyze key events from the timeframe:
- List major events chronologically
- Explain significance of each event
- Connect events to broader narratives
- Note any causal relationships

Each event must be cited to its source.""",
                ),
                TemplateSection(
                    name="sentiment_trend",
                    title="Sentiment Trends",
                    order=4,
                    max_tokens=768,
                    depends_on=["narrative_landscape"],
                    prompt="""Analyze sentiment trends:
- Overall sentiment direction (positive/negative/neutral)
- Sentiment by source type or audience
- Notable sentiment shifts and their triggers
- Comparison to previous periods if relevant

Support observations with cited examples.""",
                ),
                TemplateSection(
                    name="notable_items",
                    title="Notable Items",
                    order=5,
                    max_tokens=768,
                    depends_on=["key_events"],
                    prompt="""Highlight particularly notable items:
- Unusually high-impact content
- Viral or highly-shared items
- Items from influential sources
- Surprising or unexpected coverage

For each, explain why it's notable and cite the source.""",
                ),
                TemplateSection(
                    name="open_questions",
                    title="Open Questions",
                    order=6,
                    max_tokens=512,
                    depends_on=["narrative_landscape", "key_events"],
                    required=False,
                    prompt="""Identify open questions and areas for further investigation:
- Unanswered questions raised by the analysis
- Information gaps
- Emerging situations to monitor
- Recommended follow-up actions

Be specific about what additional information would be valuable.""",
                ),
            ],
        )


class MemoToneVariant(BaseModel):
    """A tone variant for memo generation."""

    name: str
    description: str
    tone_instructions: str
    max_length: int = Field(default=500, description="Target max words")


class MemoTemplate(Template):
    """Template for short memos/briefs."""

    template_type: TemplateType = TemplateType.MEMO
    tone_variants: List[MemoToneVariant] = Field(default_factory=list)
    target_audience: Optional[str] = None

    @classmethod
    def default(cls) -> "MemoTemplate":
        """Create the default memo template."""
        return cls(
            name="Executive Brief",
            description="Concise, audience-targeted intelligence brief",
            system_prompt="""You are creating a tight, immediately actionable intelligence brief.
Be concise but comprehensive. Every word should earn its place.
Cite sources for all factual claims using [N] format.""",
            tone_variants=[
                MemoToneVariant(
                    name="formal",
                    description="Professional, formal tone for executive audiences",
                    tone_instructions="""Use formal, professional language.
Avoid contractions and casual phrasing.
Structure with clear headers.
Lead with the most important information.
Maintain an objective, analytical voice.""",
                    max_length=400,
                ),
                MemoToneVariant(
                    name="concise",
                    description="Extremely brief, bullet-point focused",
                    tone_instructions="""Maximum brevity. Use bullets and short sentences.
No filler words or phrases.
Lead with action items or key takeaways.
Skip introductions - get straight to content.
Each bullet should be self-contained.""",
                    max_length=250,
                ),
                MemoToneVariant(
                    name="detailed",
                    description="More comprehensive with supporting context",
                    tone_instructions="""Include supporting context and background.
Explain significance and implications.
Provide relevant historical context.
Include specific recommendations.
Balance detail with readability.""",
                    max_length=600,
                ),
            ],
            sections=[
                TemplateSection(
                    name="key_takeaways",
                    title="Key Takeaways",
                    order=1,
                    max_tokens=256,
                    prompt="""List 3-5 key takeaways. Each should be:
- Actionable or directly informative
- Supported by cited evidence
- One sentence max

Format as a bulleted list.""",
                ),
                TemplateSection(
                    name="situation",
                    title="Situation",
                    order=2,
                    max_tokens=384,
                    prompt="""Briefly describe the current situation:
- What is happening?
- Who is involved?
- What is the timeline?

Keep it factual and cited. 2-3 short paragraphs max.""",
                ),
                TemplateSection(
                    name="assessment",
                    title="Assessment",
                    order=3,
                    max_tokens=256,
                    depends_on=["situation"],
                    prompt="""Provide a brief assessment:
- What does this mean for the subject?
- What are potential implications?
- What should be monitored?

Be direct and specific.""",
                ),
                TemplateSection(
                    name="recommended_actions",
                    title="Recommended Actions",
                    order=4,
                    max_tokens=192,
                    depends_on=["assessment"],
                    required=False,
                    prompt="""If appropriate, suggest 2-3 specific actions:
- What should the reader do?
- What decisions need to be made?
- What requires immediate attention?

Make actions concrete and achievable.""",
                ),
            ],
        )


class TimelineTemplate(Template):
    """Template for timeline generation."""

    template_type: TemplateType = TemplateType.TIMELINE
    include_evidence_links: bool = True
    date_format: str = "%Y-%m-%d"
    output_formats: List[str] = Field(
        default=["markdown", "json"],
        description="Supported output formats",
    )

    @classmethod
    def default(cls) -> "TimelineTemplate":
        """Create the default timeline template."""
        return cls(
            name="Event Timeline",
            description="Chronological sequence of events with evidence",
            system_prompt="""Create a precise chronological timeline of events.
Each entry must:
- Have a specific date or date range
- Be linked to source evidence
- Include brief but complete description
- Note significance where relevant""",
            sections=[
                TemplateSection(
                    name="timeline_entries",
                    title="Timeline",
                    order=1,
                    max_tokens=2048,
                    prompt="""Create a chronological timeline from the source materials.

For each event:
1. Date (be as specific as sources allow)
2. Event title (brief, descriptive)
3. Description (1-2 sentences)
4. Source citation [N]
5. Significance (optional, if notable)

Format each entry as:
### [DATE]
**Event:** Title
Description with citation [N].
*Significance:* Why this matters (if applicable)

Order from earliest to latest.""",
                ),
                TemplateSection(
                    name="timeline_summary",
                    title="Summary",
                    order=2,
                    max_tokens=256,
                    depends_on=["timeline_entries"],
                    required=False,
                    prompt="""Provide a brief summary of the timeline:
- Total timespan covered
- Number of significant events
- Key turning points or clusters
- Overall trajectory or pattern""",
                ),
            ],
        )


class NewsletterTemplate(Template):
    """Template for recurring newsletter/digest generation."""

    template_type: TemplateType = TemplateType.NEWSLETTER
    frequency: str = Field(default="weekly", description="Daily, weekly, monthly")
    max_items_per_section: int = 5
    include_sentiment_summary: bool = True

    @classmethod
    def default(cls) -> "NewsletterTemplate":
        """Create the default newsletter template."""
        return cls(
            name="Intelligence Digest",
            description="Recurring digest of narrative intelligence",
            system_prompt="""Create an engaging intelligence digest summarizing the period's developments.
Balance comprehensiveness with readability.
Highlight what's most important and actionable.
Cite sources for all claims using [N] format.""",
            sections=[
                TemplateSection(
                    name="top_story",
                    title="Top Story",
                    order=1,
                    max_tokens=384,
                    prompt="""Identify and summarize the single most important story/development.
- What happened?
- Why does it matter?
- What are the implications?

Write 2-3 engaging paragraphs with citations.""",
                ),
                TemplateSection(
                    name="sentinel_flags",
                    title="Alerts & Flags",
                    order=2,
                    max_tokens=512,
                    prompt="""List significant alerts from the monitoring period:
- New narrative emergences
- Sentiment shifts
- Source activity spikes
- Unusual patterns

Format as a prioritized list with brief explanations.
Include citations for each flag.""",
                ),
                TemplateSection(
                    name="narrative_summary",
                    title="Narrative Summary",
                    order=3,
                    max_tokens=512,
                    prompt="""Summarize the top narratives across all subjects:
- What stories dominated?
- How did narratives evolve?
- What new angles emerged?

Cover 3-5 top narratives with cited examples.""",
                ),
                TemplateSection(
                    name="by_subject",
                    title="Subject Updates",
                    order=4,
                    max_tokens=768,
                    prompt="""For each monitored subject, provide a brief update:
- Key developments
- Notable items
- Sentiment direction

Keep each subject update to 2-3 sentences with citations.""",
                ),
                TemplateSection(
                    name="looking_ahead",
                    title="Looking Ahead",
                    order=5,
                    max_tokens=256,
                    depends_on=["narrative_summary"],
                    required=False,
                    prompt="""Preview what to watch for:
- Upcoming events or dates
- Developing situations
- Potential narrative shifts
- Recommended monitoring focus""",
                ),
            ],
        )


class TemplateManager:
    """
    Manages template loading, customization, and storage.

    Provides:
    - Built-in template access
    - Custom template registration
    - Template validation
    - Variable interpolation
    """

    def __init__(self):
        """Initialize with built-in templates."""
        self._templates: Dict[str, Template] = {}
        self._load_builtin_templates()

    def _load_builtin_templates(self) -> None:
        """Load all built-in templates."""
        defaults = [
            ReportTemplate.default(),
            MemoTemplate.default(),
            TimelineTemplate.default(),
            NewsletterTemplate.default(),
        ]

        for template in defaults:
            self._templates[template.name.lower().replace(" ", "_")] = template
            # Also register by type
            self._templates[f"default_{template.template_type.value}"] = template

    def get_template(self, name: str) -> Optional[Template]:
        """
        Get a template by name.

        Args:
            name: Template name or "default_<type>"

        Returns:
            Template if found, None otherwise
        """
        return self._templates.get(name.lower().replace(" ", "_"))

    def get_default_template(self, template_type: TemplateType) -> Template:
        """
        Get the default template for a type.

        Args:
            template_type: Type of template

        Returns:
            Default template for the type
        """
        key = f"default_{template_type.value}"
        template = self._templates.get(key)

        if not template:
            # Fallback to creating new default
            if template_type == TemplateType.REPORT:
                return ReportTemplate.default()
            elif template_type == TemplateType.MEMO:
                return MemoTemplate.default()
            elif template_type == TemplateType.TIMELINE:
                return TimelineTemplate.default()
            elif template_type == TemplateType.NEWSLETTER:
                return NewsletterTemplate.default()
            else:
                raise ValueError(f"No default template for type: {template_type}")

        return template

    def register_template(self, template: Template) -> None:
        """
        Register a custom template.

        Args:
            template: Template to register
        """
        key = template.name.lower().replace(" ", "_")
        self._templates[key] = template
        logger.info(f"Registered template: {key}")

    def list_templates(
        self,
        template_type: Optional[TemplateType] = None,
    ) -> List[Dict[str, Any]]:
        """
        List available templates.

        Args:
            template_type: Filter by type (optional)

        Returns:
            List of template summaries
        """
        templates = []

        for key, template in self._templates.items():
            if template_type and template.template_type != template_type:
                continue

            templates.append({
                "key": key,
                "name": template.name,
                "type": template.template_type.value,
                "description": template.description,
                "section_count": len(template.sections),
            })

        return templates

    def validate_template(self, template: Template) -> List[str]:
        """
        Validate a template configuration.

        Args:
            template: Template to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not template.name:
            errors.append("Template must have a name")

        if not template.sections:
            errors.append("Template must have at least one section")

        # Check section dependencies
        section_names = {s.name for s in template.sections}
        for section in template.sections:
            for dep in section.depends_on:
                if dep not in section_names:
                    errors.append(
                        f"Section '{section.name}' depends on non-existent "
                        f"section '{dep}'"
                    )

        # Check for duplicate section names
        seen = set()
        for section in template.sections:
            if section.name in seen:
                errors.append(f"Duplicate section name: {section.name}")
            seen.add(section.name)

        # Validate section ordering
        orders = [s.order for s in template.sections]
        if len(orders) != len(set(orders)):
            errors.append("Section orders should be unique")

        return errors

    def interpolate_template(
        self,
        template: Template,
        variables: Dict[str, Any],
    ) -> Template:
        """
        Interpolate variables into template prompts.

        Args:
            template: Template to interpolate
            variables: Variable values to insert

        Returns:
            New template with interpolated values
        """
        # Create a copy
        new_template = template.model_copy(deep=True)

        # Interpolate system prompt
        new_template.system_prompt = self._interpolate_string(
            new_template.system_prompt, variables
        )

        # Interpolate section prompts
        for section in new_template.sections:
            section.prompt = self._interpolate_string(section.prompt, variables)
            if section.instructions:
                section.instructions = self._interpolate_string(
                    section.instructions, variables
                )

        return new_template

    def _interpolate_string(
        self,
        text: str,
        variables: Dict[str, Any],
    ) -> str:
        """Interpolate variables into a string using {var} syntax."""
        result = text
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, str(value))
        return result

    def create_custom_template(
        self,
        name: str,
        template_type: TemplateType,
        sections: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Template:
        """
        Create a custom template from configuration.

        Args:
            name: Template name
            template_type: Type of template
            sections: List of section configurations
            system_prompt: Custom system prompt
            description: Template description

        Returns:
            New Template instance
        """
        template_sections = [
            TemplateSection(
                name=s.get("name", f"section_{i}"),
                title=s.get("title", s.get("name", f"Section {i}")),
                prompt=s.get("prompt", ""),
                required=s.get("required", True),
                max_tokens=s.get("max_tokens", 1024),
                order=s.get("order", i),
                depends_on=s.get("depends_on", []),
                instructions=s.get("instructions"),
            )
            for i, s in enumerate(sections)
        ]

        return Template(
            name=name,
            template_type=template_type,
            description=description,
            system_prompt=system_prompt or "You are an expert analyst.",
            sections=template_sections,
        )

    def export_template(self, template: Template) -> Dict[str, Any]:
        """Export template to dictionary format."""
        return template.model_dump()

    def import_template(self, data: Dict[str, Any]) -> Template:
        """Import template from dictionary format."""
        template_type = TemplateType(data.get("template_type", "custom"))

        if template_type == TemplateType.REPORT:
            return ReportTemplate(**data)
        elif template_type == TemplateType.MEMO:
            return MemoTemplate(**data)
        elif template_type == TemplateType.TIMELINE:
            return TimelineTemplate(**data)
        elif template_type == TemplateType.NEWSLETTER:
            return NewsletterTemplate(**data)
        else:
            return Template(**data)
