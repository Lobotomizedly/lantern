"""
Timeline Generator

Creates ordered sequences of events with evidence links. Pulls from Event
graph data and links each entry to source Items. Supports Markdown and
JSON output formats.
"""

import json
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
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
    TemplateManager,
    TemplateSection,
    TimelineTemplate,
)

logger = logging.getLogger(__name__)


class TimelineFormat(str, Enum):
    """Supported timeline output formats."""

    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"


class TimelineEntry(BaseModel):
    """A single timeline entry."""

    date: datetime
    date_precision: str = Field(
        default="day",
        description="Precision: day, month, year, or approximate",
    )
    title: str
    description: str
    significance: Optional[str] = None
    source_item_ids: List[UUID] = Field(default_factory=list)
    source_citations: List[int] = Field(
        default_factory=list,
        description="Citation indices [1], [2], etc.",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Type of event (announcement, incident, etc.)",
    )
    entities_involved: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TimelineConfig(GeneratorConfig):
    """Configuration for timeline generation."""

    output_format: TimelineFormat = Field(
        default=TimelineFormat.MARKDOWN,
        description="Output format for the timeline",
    )
    include_evidence_links: bool = Field(
        default=True,
        description="Include links to source evidence",
    )
    include_significance: bool = Field(
        default=True,
        description="Include significance notes for events",
    )
    max_entries: int = Field(
        default=50,
        description="Maximum number of timeline entries",
    )
    group_by_date: bool = Field(
        default=False,
        description="Group multiple events on same date",
    )
    date_format: str = Field(
        default="%Y-%m-%d",
        description="Date display format",
    )
    sort_order: str = Field(
        default="ascending",
        description="Sort order: ascending or descending",
    )


class TimelineResult(GenerationResult):
    """Result containing parsed timeline entries."""

    entries: List[TimelineEntry] = Field(default_factory=list)
    date_range: Dict[str, Optional[str]] = Field(default_factory=dict)
    entry_count: int = 0
    formatted_output: str = ""


class TimelineGenerator(BaseGenerator[TimelineConfig]):
    """
    Generates ordered timelines of events with evidence links.

    Features:
    - Chronological event ordering
    - Links to source Items for evidence
    - Multiple output formats (Markdown, JSON, HTML)
    - Event grouping and significance notes
    - Full citation support
    """

    def __init__(
        self,
        config: Optional[TimelineConfig] = None,
        template: Optional[TimelineTemplate] = None,
        **kwargs,
    ):
        """
        Initialize the timeline generator.

        Args:
            config: Timeline generation configuration
            template: Custom timeline template
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
        return TemplateType.TIMELINE

    def _default_config(self) -> TimelineConfig:
        """Return default timeline configuration."""
        return TimelineConfig()

    def _get_artifact_type(self) -> str:
        """Return the artifact type string."""
        return "timeline"

    def _get_sections(self) -> List[str]:
        """Return ordered list of section names."""
        if self._template and self._template.sections:
            sorted_sections = sorted(
                self._template.sections,
                key=lambda s: s.order,
            )
            return [s.name for s in sorted_sections]

        return ["timeline_entries", "timeline_summary"]

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

        # Build system prompt
        system_prompt = self._template.system_prompt if self._template else (
            "Create a precise chronological timeline of events. "
            "Each entry must be dated and linked to source evidence."
        )

        # Build source context
        source_context = self._build_source_context(context.source_materials)

        # Previous context
        previous_context = ""
        if previous_sections:
            previous_context = "\n\nPREVIOUS SECTIONS:\n"
            for name, result in previous_sections.items():
                previous_context += f"\n{result.content}\n"

        # Section prompt
        if template_section:
            section_prompt = template_section.prompt
        else:
            section_prompt = self._get_default_section_prompt(section_name)

        # Subject/timeframe context
        subject_context = ""
        if context.subject_name:
            subject_context = f"Subject: {context.subject_name}\n"
        if context.timeframe_start and context.timeframe_end:
            subject_context += (
                f"Timeframe: {context.timeframe_start.strftime('%Y-%m-%d')} to "
                f"{context.timeframe_end.strftime('%Y-%m-%d')}\n"
            )

        prompt = f"""{system_prompt}

{subject_context}

{self._build_citation_instructions()}

MAXIMUM ENTRIES: {self.config.max_entries}
SORT ORDER: {self.config.sort_order}
INCLUDE SIGNIFICANCE: {self.config.include_significance}

SOURCE MATERIALS:
{source_context}

{previous_context}

TASK: {section_prompt}

FORMAT EACH ENTRY AS:
### [DATE]
**Event:** [Title]
[Description with citation [N]]
*Significance:* [Why this matters] (if applicable)
*Sources:* [List of source numbers]

End with a CITATIONS section."""

        return prompt

    def _get_default_section_prompt(self, section_name: str) -> str:
        """Get default prompt for a section."""
        prompts = {
            "timeline_entries": f"""Create a chronological timeline from the source materials.

For each significant event, provide:
1. Date (be as specific as sources allow)
2. Event title (brief, descriptive)
3. Description (1-2 sentences)
4. Source citation [N]
5. Significance (if notable)

Limit to {self.config.max_entries} most significant events.
Order from {'earliest to latest' if self.config.sort_order == 'ascending' else 'latest to earliest'}.""",

            "timeline_summary": """Provide a brief summary of the timeline:
- Total timespan covered
- Number of significant events
- Key turning points or clusters
- Overall trajectory or pattern""",
        }

        return prompts.get(section_name, f"Generate the {section_name} section.")

    async def generate_timeline(
        self,
        subject_id: UUID,
        subject_name: str,
        source_materials: List[SourceMaterial],
        timeframe_start: Optional[datetime] = None,
        timeframe_end: Optional[datetime] = None,
        title: Optional[str] = None,
        output_format: Optional[TimelineFormat] = None,
    ) -> TimelineResult:
        """
        Generate a complete timeline.

        Args:
            subject_id: Subject ID
            subject_name: Subject name
            source_materials: Source materials
            timeframe_start: Optional start date
            timeframe_end: Optional end date
            title: Optional title
            output_format: Override output format

        Returns:
            TimelineResult with entries and formatted output
        """
        if output_format:
            self.config.output_format = output_format

        context = GenerationContext(
            subject_id=subject_id,
            subject_name=subject_name,
            timeframe_start=timeframe_start,
            timeframe_end=timeframe_end,
            source_materials=source_materials,
        )

        # Generate base result
        base_result = await self.generate(context, title=title)

        # Parse entries from generated content
        entries = self._parse_timeline_entries(
            base_result.combined_content,
            source_materials,
        )

        # Sort entries
        entries = sorted(
            entries,
            key=lambda e: e.date,
            reverse=(self.config.sort_order == "descending"),
        )

        # Limit to max entries
        entries = entries[: self.config.max_entries]

        # Create formatted output
        formatted_output = self._format_timeline(
            entries,
            subject_name,
            self.config.output_format,
        )

        # Build result
        result = TimelineResult(
            artifact_id=base_result.artifact_id,
            artifact_type="timeline",
            title=base_result.title,
            sections=base_result.sections,
            combined_content=base_result.combined_content,
            all_citations=base_result.all_citations,
            total_tokens=base_result.total_tokens,
            total_generation_time_ms=base_result.total_generation_time_ms,
            overall_grounding_score=base_result.overall_grounding_score,
            metadata=base_result.metadata,
            warnings=base_result.warnings,
            entries=entries,
            entry_count=len(entries),
            formatted_output=formatted_output,
        )

        # Add date range
        if entries:
            result.date_range = {
                "start": entries[0].date.isoformat() if self.config.sort_order == "ascending" else entries[-1].date.isoformat(),
                "end": entries[-1].date.isoformat() if self.config.sort_order == "ascending" else entries[0].date.isoformat(),
            }

        result.metadata["output_format"] = self.config.output_format.value
        result.metadata["entry_count"] = len(entries)

        return result

    def _parse_timeline_entries(
        self,
        content: str,
        sources: List[SourceMaterial],
    ) -> List[TimelineEntry]:
        """
        Parse timeline entries from generated content.

        Args:
            content: Generated timeline content
            sources: Source materials for linking

        Returns:
            List of TimelineEntry objects
        """
        entries: List[TimelineEntry] = []

        # Pattern for timeline entries
        # Matches: ### [DATE] followed by **Event:** and content
        entry_pattern = re.compile(
            r"###\s*\[?(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\w+\s+\d{1,2},?\s*\d{4}|\d{4})\]?\s*\n"
            r"\*?\*?Event:?\*?\*?\s*(.+?)\n"
            r"(.*?)(?=###|\Z)",
            re.DOTALL | re.IGNORECASE,
        )

        matches = entry_pattern.findall(content)

        for date_str, title, body in matches:
            # Parse date
            date = self._parse_date(date_str)
            if not date:
                continue

            # Clean title
            title = title.strip().strip("*")

            # Extract description and significance from body
            description, significance = self._parse_entry_body(body)

            # Extract citations
            citation_indices = [
                int(m) for m in re.findall(r"\[(\d+)\]", body)
            ]

            # Link to source items
            source_ids = []
            for idx in citation_indices:
                if 0 < idx <= len(sources):
                    source_ids.append(sources[idx - 1].item_id)

            entries.append(
                TimelineEntry(
                    date=date,
                    date_precision=self._determine_precision(date_str),
                    title=title,
                    description=description,
                    significance=significance if self.config.include_significance else None,
                    source_item_ids=source_ids,
                    source_citations=citation_indices,
                )
            )

        return entries

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime."""
        date_str = date_str.strip()

        # Try various formats
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%B %d, %Y",
            "%B %d %Y",
            "%b %d, %Y",
            "%b %d %Y",
            "%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Try loose parsing
        try:
            from dateutil import parser
            return parser.parse(date_str)
        except Exception:
            pass

        return None

    def _determine_precision(self, date_str: str) -> str:
        """Determine date precision from string format."""
        if re.match(r"^\d{4}$", date_str.strip()):
            return "year"
        elif re.match(r"^\w+\s+\d{4}$", date_str.strip()):
            return "month"
        elif "circa" in date_str.lower() or "~" in date_str:
            return "approximate"
        return "day"

    def _parse_entry_body(self, body: str) -> tuple:
        """Parse entry body into description and significance."""
        lines = body.strip().split("\n")

        description_parts = []
        significance = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.lower().startswith("*significance:") or line.lower().startswith("significance:"):
                significance = re.sub(r"^\*?significance:\*?\s*", "", line, flags=re.IGNORECASE).strip()
            elif line.lower().startswith("*sources:") or line.lower().startswith("sources:"):
                continue  # Skip sources line
            elif not line.startswith("CITATIONS"):
                description_parts.append(line)

        description = " ".join(description_parts).strip()
        # Clean up asterisks
        description = re.sub(r"\*{1,2}", "", description)

        return description, significance

    def _format_timeline(
        self,
        entries: List[TimelineEntry],
        subject_name: str,
        output_format: TimelineFormat,
    ) -> str:
        """
        Format timeline entries to specified format.

        Args:
            entries: List of timeline entries
            subject_name: Subject name for title
            output_format: Output format

        Returns:
            Formatted timeline string
        """
        if output_format == TimelineFormat.JSON:
            return self._format_as_json(entries, subject_name)
        elif output_format == TimelineFormat.HTML:
            return self._format_as_html(entries, subject_name)
        else:
            return self._format_as_markdown(entries, subject_name)

    def _format_as_markdown(
        self,
        entries: List[TimelineEntry],
        subject_name: str,
    ) -> str:
        """Format timeline as Markdown."""
        lines = [
            f"# Timeline: {subject_name}",
            "",
            f"*{len(entries)} events*",
            "",
        ]

        current_month = None

        for entry in entries:
            # Add month header if grouping
            if self.config.group_by_date:
                month = entry.date.strftime("%B %Y")
                if month != current_month:
                    lines.append(f"\n## {month}\n")
                    current_month = month

            date_str = entry.date.strftime(self.config.date_format)

            lines.append(f"### {date_str}")
            lines.append(f"**{entry.title}**")
            lines.append("")
            lines.append(entry.description)

            if entry.significance:
                lines.append("")
                lines.append(f"*Significance:* {entry.significance}")

            if self.config.include_evidence_links and entry.source_citations:
                citations = ", ".join(f"[{c}]" for c in entry.source_citations)
                lines.append(f"\n*Sources:* {citations}")

            lines.append("")

        return "\n".join(lines)

    def _format_as_json(
        self,
        entries: List[TimelineEntry],
        subject_name: str,
    ) -> str:
        """Format timeline as JSON."""
        data = {
            "subject": subject_name,
            "entry_count": len(entries),
            "date_range": {
                "start": entries[0].date.isoformat() if entries else None,
                "end": entries[-1].date.isoformat() if entries else None,
            },
            "entries": [
                {
                    "date": entry.date.isoformat(),
                    "date_precision": entry.date_precision,
                    "title": entry.title,
                    "description": entry.description,
                    "significance": entry.significance,
                    "source_item_ids": [str(uid) for uid in entry.source_item_ids],
                    "source_citations": entry.source_citations,
                    "event_type": entry.event_type,
                    "entities_involved": entry.entities_involved,
                }
                for entry in entries
            ],
        }

        return json.dumps(data, indent=2)

    def _format_as_html(
        self,
        entries: List[TimelineEntry],
        subject_name: str,
    ) -> str:
        """Format timeline as HTML."""
        html_parts = [
            f"<div class='timeline'>",
            f"<h1>Timeline: {subject_name}</h1>",
            f"<p class='summary'>{len(entries)} events</p>",
        ]

        for entry in entries:
            date_str = entry.date.strftime(self.config.date_format)

            html_parts.append("<div class='timeline-entry'>")
            html_parts.append(f"<div class='timeline-date'>{date_str}</div>")
            html_parts.append(f"<h3 class='timeline-title'>{entry.title}</h3>")
            html_parts.append(f"<p class='timeline-description'>{entry.description}</p>")

            if entry.significance:
                html_parts.append(
                    f"<p class='timeline-significance'><em>Significance:</em> {entry.significance}</p>"
                )

            if self.config.include_evidence_links and entry.source_item_ids:
                html_parts.append("<div class='timeline-sources'>")
                for item_id in entry.source_item_ids:
                    html_parts.append(
                        f"<a href='/items/{item_id}' class='source-link'>{item_id}</a>"
                    )
                html_parts.append("</div>")

            html_parts.append("</div>")

        html_parts.append("</div>")

        return "\n".join(html_parts)

    async def generate_from_events(
        self,
        events: List[Any],
        subject_name: str,
        output_format: Optional[TimelineFormat] = None,
    ) -> TimelineResult:
        """
        Generate timeline from Event objects.

        Args:
            events: List of Event objects from the graph
            subject_name: Subject name
            output_format: Output format

        Returns:
            TimelineResult
        """
        # Convert events to entries directly
        entries: List[TimelineEntry] = []

        for event in events:
            # Handle both dict and object formats
            if isinstance(event, dict):
                date = event.get("occurred_at") or event.get("date")
                title = event.get("title", event.get("name", "Unknown Event"))
                description = event.get("description", "")
                item_ids = event.get("evidence_item_ids", [])
            else:
                date = getattr(event, "occurred_at", None) or getattr(event, "date", None)
                title = getattr(event, "title", getattr(event, "name", "Unknown Event"))
                description = getattr(event, "description", "")
                item_ids = getattr(event, "evidence_item_ids", [])

            if not date:
                continue

            if isinstance(date, str):
                date = self._parse_date(date)

            if date:
                entries.append(
                    TimelineEntry(
                        date=date,
                        title=title,
                        description=description,
                        source_item_ids=[UUID(str(i)) for i in item_ids] if item_ids else [],
                    )
                )

        # Sort entries
        entries = sorted(
            entries,
            key=lambda e: e.date,
            reverse=(self.config.sort_order == "descending"),
        )

        # Limit entries
        entries = entries[: self.config.max_entries]

        # Format output
        format_type = output_format or self.config.output_format
        formatted_output = self._format_timeline(entries, subject_name, format_type)

        # Create result
        result = TimelineResult(
            artifact_type="timeline",
            title=f"Timeline: {subject_name}",
            combined_content=formatted_output,
            entries=entries,
            entry_count=len(entries),
            formatted_output=formatted_output,
            overall_grounding_score=1.0,  # Direct from events = fully grounded
        )

        if entries:
            result.date_range = {
                "start": entries[0].date.isoformat(),
                "end": entries[-1].date.isoformat(),
            }

        result.metadata = {
            "output_format": format_type.value,
            "source": "events",
            "entry_count": len(entries),
        }

        return result
