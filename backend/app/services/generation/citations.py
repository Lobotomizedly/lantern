"""
Citation Management

Provides comprehensive citation parsing, validation, and formatting for
the Lantern generation layer. Ensures all claims are properly linked
to source materials.
"""

import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.generation.base import Citation, SourceMaterial

logger = logging.getLogger(__name__)


class CitationFormat(str, Enum):
    """Supported citation output formats."""

    INLINE_NUMERIC = "inline_numeric"  # [1], [2]
    INLINE_AUTHOR_DATE = "inline_author_date"  # (Author, 2024)
    FOOTNOTE = "footnote"  # Superscript numbers with footnotes
    ENDNOTE = "endnote"  # Numbers with endnotes section
    MARKDOWN_LINKS = "markdown_links"  # [text](url)


class CitationStyle(str, Enum):
    """Citation display styles."""

    BRIEF = "brief"  # Title only
    STANDARD = "standard"  # Title + date
    DETAILED = "detailed"  # Title + date + URL + quote
    ACADEMIC = "academic"  # Author, date, title, source


class CitationValidationError(BaseModel):
    """Details of a citation validation error."""

    citation_marker: str
    error_type: str
    message: str
    line_number: Optional[int] = None
    suggestion: Optional[str] = None


class CitationValidationResult(BaseModel):
    """Result of citation validation."""

    is_valid: bool = True
    total_citations: int = 0
    unique_sources: int = 0
    coverage_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Percentage of content sentences with citations",
    )
    errors: List[CitationValidationError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    orphan_citations: List[str] = Field(
        default_factory=list,
        description="Citations referencing non-existent sources",
    )
    unused_sources: List[UUID] = Field(
        default_factory=list,
        description="Source IDs that were provided but not cited",
    )


class CitationEntry(BaseModel):
    """A formatted citation entry for output."""

    index: int
    item_id: UUID
    formatted_text: str
    source_title: str
    source_url: Optional[str] = None
    source_date: Optional[datetime] = None
    quote: Optional[str] = None


class CitationManager:
    """
    Manages citation parsing, validation, and formatting.

    Provides tools to:
    - Parse citation markers from generated content
    - Validate citations against source materials
    - Check citation coverage
    - Format citations for various output formats
    - Link citations to source Items
    """

    def __init__(
        self,
        citation_format: CitationFormat = CitationFormat.INLINE_NUMERIC,
        citation_style: CitationStyle = CitationStyle.STANDARD,
    ):
        """
        Initialize the citation manager.

        Args:
            citation_format: Format for citation markers
            citation_style: Style for citation display
        """
        self.citation_format = citation_format
        self.citation_style = citation_style

    def parse_citations(
        self,
        content: str,
        sources: List[SourceMaterial],
    ) -> Tuple[List[Citation], List[CitationValidationError]]:
        """
        Parse citation markers from content and create Citation objects.

        Args:
            content: Content with citation markers
            sources: Available source materials

        Returns:
            Tuple of (citations, errors)
        """
        citations: List[Citation] = []
        errors: List[CitationValidationError] = []
        seen_indices: Set[int] = set()

        # Pattern for numeric citations [N] or [N][M]
        pattern = r"\[(\d+)\]"
        matches = list(re.finditer(pattern, content))

        for match in matches:
            idx = int(match.group(1))
            source_idx = idx - 1  # Convert to 0-indexed

            if source_idx in seen_indices:
                continue

            if source_idx < 0 or source_idx >= len(sources):
                # Find line number
                line_number = content[: match.start()].count("\n") + 1
                errors.append(
                    CitationValidationError(
                        citation_marker=f"[{idx}]",
                        error_type="invalid_reference",
                        message=f"Citation [{idx}] references non-existent source",
                        line_number=line_number,
                        suggestion=f"Valid range is [1] to [{len(sources)}]",
                    )
                )
                continue

            seen_indices.add(source_idx)
            source = sources[source_idx]

            # Extract quote context if available
            quote = self._extract_quote_context(content, match)

            citations.append(
                Citation(
                    item_id=source.item_id,
                    text=quote or f"Reference to: {source.title}",
                    source_title=source.title,
                    source_url=source.url,
                    timestamp=source.published_at,
                )
            )

        return citations, errors

    def _extract_quote_context(
        self,
        content: str,
        match: re.Match,
        context_chars: int = 150,
    ) -> Optional[str]:
        """
        Extract the text context around a citation marker.

        Args:
            content: Full content
            match: Regex match object for citation
            context_chars: Characters of context to extract

        Returns:
            Context string or None
        """
        start = max(0, match.start() - context_chars)
        end = min(len(content), match.end() + context_chars)

        context = content[start:end]

        # Try to find sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", context)
        for sentence in sentences:
            if match.group() in sentence:
                return sentence.strip()

        return context.strip()

    def validate_citations(
        self,
        content: str,
        citations: List[Citation],
        sources: List[SourceMaterial],
    ) -> CitationValidationResult:
        """
        Validate citations in content against source materials.

        Args:
            content: Content with citations
            citations: Parsed citations
            sources: Available source materials

        Returns:
            Validation result with errors and warnings
        """
        result = CitationValidationResult(
            total_citations=len(citations),
            unique_sources=len(set(c.item_id for c in citations)),
        )

        # Find orphan citations (references to non-existent sources)
        source_ids = {s.item_id for s in sources}
        for citation in citations:
            if citation.item_id not in source_ids:
                result.orphan_citations.append(str(citation.item_id))
                result.errors.append(
                    CitationValidationError(
                        citation_marker=citation.id,
                        error_type="orphan_citation",
                        message=f"Citation references unknown source: {citation.item_id}",
                    )
                )

        # Find unused sources
        cited_ids = {c.item_id for c in citations}
        for source in sources:
            if source.item_id not in cited_ids:
                result.unused_sources.append(source.item_id)
                result.warnings.append(
                    f"Source '{source.title}' ({source.item_id}) was not cited"
                )

        # Calculate coverage score
        result.coverage_score = self._calculate_coverage(content, citations)

        # Determine overall validity
        result.is_valid = len(result.errors) == 0 and result.coverage_score >= 0.5

        return result

    def _calculate_coverage(
        self,
        content: str,
        citations: List[Citation],
    ) -> float:
        """
        Calculate citation coverage score.

        Measures what percentage of content sentences have citations.

        Args:
            content: Content to analyze
            citations: List of citations

        Returns:
            Coverage score from 0 to 1
        """
        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", content)

        if not sentences:
            return 0.0

        # Filter out non-substantive sentences
        substantive_sentences = [
            s
            for s in sentences
            if len(s) > 30  # Minimum length
            and not s.strip().startswith("#")  # Not headers
            and not s.strip().startswith("-")  # Not list items without content
            and not re.match(r"^\[?\d+\]", s.strip())  # Not just citations
        ]

        if not substantive_sentences:
            return 1.0  # No substantive content to cite

        # Count sentences with citations
        citation_pattern = r"\[\d+\]"
        cited_count = sum(
            1 for s in substantive_sentences if re.search(citation_pattern, s)
        )

        return cited_count / len(substantive_sentences)

    def check_citation_coverage(
        self,
        content: str,
        sources: List[SourceMaterial],
        min_coverage: float = 0.7,
    ) -> Tuple[bool, float, List[str]]:
        """
        Check if content has adequate citation coverage.

        Args:
            content: Content to check
            sources: Available source materials
            min_coverage: Minimum required coverage score

        Returns:
            Tuple of (meets_threshold, coverage_score, uncited_sentences)
        """
        citations, _ = self.parse_citations(content, sources)
        coverage = self._calculate_coverage(content, citations)

        # Find uncited sentences
        sentences = re.split(r"(?<=[.!?])\s+", content)
        citation_pattern = r"\[\d+\]"

        uncited = []
        for sentence in sentences:
            if (
                len(sentence) > 50
                and not sentence.strip().startswith("#")
                and not re.search(citation_pattern, sentence)
                and self._is_factual_claim(sentence)
            ):
                uncited.append(sentence.strip()[:100] + "...")

        return coverage >= min_coverage, coverage, uncited[:10]  # Return max 10

    def _is_factual_claim(self, sentence: str) -> bool:
        """
        Determine if a sentence contains a factual claim requiring citation.

        Args:
            sentence: Sentence to analyze

        Returns:
            True if sentence appears to be a factual claim
        """
        # Patterns indicating factual claims
        factual_patterns = [
            r"\b(reported|stated|said|announced|revealed|showed|found)\b",
            r"\b(according to|studies show|research indicates)\b",
            r"\b(increased|decreased|rose|fell|grew|declined)\s+by\b",
            r"\b\d+%\b",  # Percentages
            r"\b\d{4}\b",  # Years
            r"\b(million|billion|thousand)\b",  # Large numbers
            r"\b(company|organization|government|study|report)\b",
        ]

        # Opinion/analysis patterns (don't require citation)
        opinion_patterns = [
            r"^(However|Therefore|In conclusion|Overall|Thus)",
            r"\b(might|could|may|perhaps|possibly|likely)\b",
            r"\b(I think|we believe|it seems|appears to be)\b",
            r"^(The|This|These)\s+(analysis|assessment|evaluation)",
        ]

        sentence_lower = sentence.lower()

        # Check if it looks like an opinion
        for pattern in opinion_patterns:
            if re.search(pattern, sentence, re.IGNORECASE):
                return False

        # Check if it looks like a factual claim
        for pattern in factual_patterns:
            if re.search(pattern, sentence_lower):
                return True

        return False

    def format_citations(
        self,
        citations: List[Citation],
        format_override: Optional[CitationFormat] = None,
        style_override: Optional[CitationStyle] = None,
    ) -> str:
        """
        Format citations for output.

        Args:
            citations: List of citations to format
            format_override: Override the default format
            style_override: Override the default style

        Returns:
            Formatted citations string
        """
        format_type = format_override or self.citation_format
        style = style_override or self.citation_style

        if not citations:
            return ""

        entries: List[str] = []

        for idx, citation in enumerate(citations, 1):
            entry = self._format_single_citation(citation, idx, style)
            entries.append(entry)

        if format_type == CitationFormat.FOOTNOTE:
            return "\n---\n### Footnotes\n" + "\n".join(entries)
        elif format_type == CitationFormat.ENDNOTE:
            return "\n---\n### References\n" + "\n".join(entries)
        else:
            return "\n---\n### Sources\n" + "\n".join(entries)

    def _format_single_citation(
        self,
        citation: Citation,
        index: int,
        style: CitationStyle,
    ) -> str:
        """
        Format a single citation entry.

        Args:
            citation: Citation to format
            index: Citation index number
            style: Display style

        Returns:
            Formatted citation string
        """
        if style == CitationStyle.BRIEF:
            return f"[{index}] {citation.source_title}"

        elif style == CitationStyle.STANDARD:
            date_str = ""
            if citation.timestamp:
                date_str = f" ({citation.timestamp.strftime('%Y-%m-%d')})"
            return f"[{index}] {citation.source_title}{date_str}"

        elif style == CitationStyle.DETAILED:
            parts = [f"[{index}] {citation.source_title}"]
            if citation.timestamp:
                parts.append(f"  Date: {citation.timestamp.strftime('%Y-%m-%d')}")
            if citation.source_url:
                parts.append(f"  URL: {citation.source_url}")
            if citation.text and len(citation.text) > 20:
                parts.append(f"  Quote: \"{citation.text[:200]}...\"")
            return "\n".join(parts)

        elif style == CitationStyle.ACADEMIC:
            date_str = citation.timestamp.strftime("%Y") if citation.timestamp else "n.d."
            return f"[{index}] {citation.source_title}. ({date_str})"

        return f"[{index}] {citation.source_title}"

    def link_citations_to_items(
        self,
        citations: List[Citation],
        item_lookup: Dict[UUID, Any],
    ) -> List[Citation]:
        """
        Enrich citations with additional item data.

        Args:
            citations: Citations to enrich
            item_lookup: Mapping of item IDs to Item objects

        Returns:
            Enriched citations
        """
        enriched = []

        for citation in citations:
            if citation.item_id in item_lookup:
                item = item_lookup[citation.item_id]

                # Update with item data
                enriched_citation = citation.model_copy()

                if hasattr(item, "title") and not citation.source_title:
                    enriched_citation.source_title = item.title

                if hasattr(item, "url") and not citation.source_url:
                    enriched_citation.source_url = item.url

                if hasattr(item, "published_at") and not citation.timestamp:
                    enriched_citation.timestamp = item.published_at

                enriched.append(enriched_citation)
            else:
                enriched.append(citation)

        return enriched

    def merge_citation_sections(
        self,
        sections: Dict[str, List[Citation]],
    ) -> Tuple[List[Citation], Dict[str, List[int]]]:
        """
        Merge citations from multiple sections and create index mapping.

        Args:
            sections: Dictionary mapping section names to their citations

        Returns:
            Tuple of (deduplicated_citations, section_to_indices_mapping)
        """
        merged: List[Citation] = []
        seen_ids: Dict[UUID, int] = {}
        section_mapping: Dict[str, List[int]] = {}

        for section_name, citations in sections.items():
            section_indices: List[int] = []

            for citation in citations:
                if citation.item_id in seen_ids:
                    # Reference existing citation
                    section_indices.append(seen_ids[citation.item_id])
                else:
                    # Add new citation
                    idx = len(merged) + 1
                    seen_ids[citation.item_id] = idx
                    merged.append(citation)
                    section_indices.append(idx)

            section_mapping[section_name] = section_indices

        return merged, section_mapping

    def reindex_content(
        self,
        content: str,
        old_to_new_mapping: Dict[int, int],
    ) -> str:
        """
        Reindex citation markers in content after merging.

        Args:
            content: Content with old citation markers
            old_to_new_mapping: Mapping from old indices to new

        Returns:
            Content with updated citation markers
        """

        def replace_citation(match: re.Match) -> str:
            old_idx = int(match.group(1))
            new_idx = old_to_new_mapping.get(old_idx, old_idx)
            return f"[{new_idx}]"

        return re.sub(r"\[(\d+)\]", replace_citation, content)

    def generate_bibliography(
        self,
        citations: List[Citation],
        title: str = "Bibliography",
        include_item_ids: bool = False,
    ) -> str:
        """
        Generate a formatted bibliography section.

        Args:
            citations: Citations to include
            title: Section title
            include_item_ids: Whether to include item IDs

        Returns:
            Formatted bibliography string
        """
        if not citations:
            return ""

        lines = [f"\n## {title}\n"]

        for idx, citation in enumerate(citations, 1):
            entry = f"{idx}. **{citation.source_title}**"

            if citation.timestamp:
                entry += f" ({citation.timestamp.strftime('%B %d, %Y')})"

            if citation.source_url:
                entry += f"\n   - URL: [{citation.source_url}]({citation.source_url})"

            if citation.text:
                # Clean up the quote text
                quote = citation.text.replace("\n", " ").strip()
                if len(quote) > 200:
                    quote = quote[:200] + "..."
                entry += f'\n   - Key excerpt: "{quote}"'

            if include_item_ids:
                entry += f"\n   - Item ID: `{citation.item_id}`"

            lines.append(entry)

        return "\n".join(lines)
