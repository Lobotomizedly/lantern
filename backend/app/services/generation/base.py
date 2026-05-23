"""
Base Generator

Provides the foundational generator class with template loading, section-by-section
generation, citation tracking, and grounding enforcement.

All generators inherit from BaseGenerator to ensure consistent citation handling
and quality metrics.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypeVar, Generic
from uuid import UUID, uuid4

import anthropic
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="GeneratorConfig")


class GeneratorConfig(BaseModel):
    """Base configuration for all generators."""

    model: str = Field(
        default_factory=lambda: settings.anthropic_model,
        description="Claude model to use for generation",
    )
    max_tokens: int = Field(
        default=4096,
        description="Maximum tokens per section generation",
    )
    temperature: float = Field(
        default=0.3,
        description="Temperature for generation (lower = more focused)",
    )
    require_grounding: bool = Field(
        default=True,
        description="Require all claims to be grounded with citations",
    )
    min_grounding_score: float = Field(
        default=0.85,
        description="Minimum grounding score (0-1) to accept output",
    )
    enable_self_check: bool = Field(
        default=True,
        description="Enable self-check pass for citation coverage",
    )


class Citation(BaseModel):
    """A citation linking a claim to source material."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    item_id: UUID = Field(..., description="ID of the source Item")
    text: str = Field(..., description="Relevant quote or summary from source")
    source_title: str = Field(default="", description="Title of the source")
    source_url: Optional[str] = Field(default=None, description="URL if available")
    timestamp: Optional[datetime] = Field(default=None, description="Publication date")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in citation relevance",
    )


class SectionResult(BaseModel):
    """Result of generating a single section."""

    section_name: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    token_count: int = 0
    generation_time_ms: int = 0
    grounding_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Percentage of claims that are grounded",
    )
    ungrounded_claims: List[str] = Field(
        default_factory=list,
        description="Claims that lack citations",
    )


class GenerationResult(BaseModel):
    """Complete result of a generation operation."""

    artifact_id: UUID = Field(default_factory=uuid4)
    artifact_type: str
    title: str
    sections: Dict[str, SectionResult] = Field(default_factory=dict)
    combined_content: str = Field(default="")
    all_citations: List[Citation] = Field(default_factory=list)
    total_tokens: int = 0
    total_generation_time_ms: int = 0
    overall_grounding_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class SourceMaterial(BaseModel):
    """Source material provided for generation."""

    item_id: UUID
    title: str
    content: str
    source_type: str = "item"
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    relevance_score: float = 1.0


class GenerationContext(BaseModel):
    """Context for a generation operation."""

    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    timeframe_start: Optional[datetime] = None
    timeframe_end: Optional[datetime] = None
    source_materials: List[SourceMaterial] = Field(default_factory=list)
    additional_context: Dict[str, Any] = Field(default_factory=dict)
    user_instructions: Optional[str] = None


class BaseGenerator(ABC, Generic[T]):
    """
    Base class for all Lantern generators.

    Provides:
    - Template loading and management
    - Section-by-section generation with Claude
    - Citation tracking and validation
    - Grounding enforcement (every claim needs citation)
    - Self-check for citation coverage
    """

    def __init__(
        self,
        config: Optional[T] = None,
        client: Optional[anthropic.Anthropic] = None,
    ):
        """
        Initialize the generator.

        Args:
            config: Generator configuration
            client: Anthropic client (creates new one if not provided)
        """
        self.config = config or self._default_config()
        self.client = client or self._create_client()
        self._template: Optional[Any] = None

    @abstractmethod
    def _default_config(self) -> T:
        """Return the default configuration for this generator type."""
        pass

    @abstractmethod
    def _get_artifact_type(self) -> str:
        """Return the artifact type string (e.g., 'report', 'memo')."""
        pass

    @abstractmethod
    def _get_sections(self) -> List[str]:
        """Return the ordered list of section names to generate."""
        pass

    @abstractmethod
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
            previous_sections: Already generated sections for reference

        Returns:
            Complete prompt for section generation
        """
        pass

    def _create_client(self) -> anthropic.Anthropic:
        """Create an Anthropic client."""
        api_key = settings.anthropic_api_key
        if api_key:
            return anthropic.Anthropic(api_key=api_key.get_secret_value())
        return anthropic.Anthropic()

    def _build_source_context(
        self,
        sources: List[SourceMaterial],
        max_chars: int = 50000,
    ) -> str:
        """
        Build a formatted context string from source materials.

        Args:
            sources: List of source materials
            max_chars: Maximum total characters to include

        Returns:
            Formatted source context string with IDs for citation
        """
        context_parts = []
        total_chars = 0

        for idx, source in enumerate(sources):
            source_text = f"""
<source id="{source.item_id}" index="{idx + 1}">
<title>{source.title}</title>
<type>{source.source_type}</type>
{f'<url>{source.url}</url>' if source.url else ''}
{f'<date>{source.published_at.isoformat()}</date>' if source.published_at else ''}
<content>
{source.content}
</content>
</source>
"""
            if total_chars + len(source_text) > max_chars:
                break
            context_parts.append(source_text)
            total_chars += len(source_text)

        return "\n".join(context_parts)

    def _build_citation_instructions(self) -> str:
        """Build instructions for citation formatting."""
        return """
CITATION REQUIREMENTS:
- Every factual claim MUST be cited using [source_index] format (e.g., [1], [2])
- Use the source index from the <source index="X"> tags provided
- Multiple sources can be combined: [1][3]
- Direct quotes should use quotation marks with citation: "quote" [1]
- Do NOT make claims that cannot be supported by the provided sources
- If you cannot find supporting evidence for a claim, do not include it
- At the end of your response, include a CITATIONS section listing all sources used

Example format:
The company reported record earnings [1] despite market headwinds [2].

CITATIONS:
[1] Source title - key quote or summary
[2] Source title - key quote or summary
"""

    def _parse_citations_from_content(
        self,
        content: str,
        sources: List[SourceMaterial],
    ) -> List[Citation]:
        """
        Parse citation references from generated content.

        Args:
            content: Generated content with citation markers
            sources: Source materials for looking up references

        Returns:
            List of Citation objects
        """
        import re

        citations = []
        seen_indices = set()

        # Find all citation markers [N]
        pattern = r"\[(\d+)\]"
        matches = re.findall(pattern, content)

        for match in matches:
            idx = int(match) - 1  # Convert to 0-indexed
            if idx in seen_indices or idx < 0 or idx >= len(sources):
                continue

            seen_indices.add(idx)
            source = sources[idx]

            # Extract context around citation in the CITATIONS section if present
            citation_text = ""
            citations_section = content.split("CITATIONS:")
            if len(citations_section) > 1:
                citation_line_pattern = rf"\[{match}\]\s*(.+?)(?:\n|$)"
                line_match = re.search(
                    citation_line_pattern, citations_section[1], re.IGNORECASE
                )
                if line_match:
                    citation_text = line_match.group(1).strip()

            citations.append(
                Citation(
                    item_id=source.item_id,
                    text=citation_text or f"Reference to: {source.title}",
                    source_title=source.title,
                    source_url=source.url,
                    timestamp=source.published_at,
                )
            )

        return citations

    async def _generate_section(
        self,
        section_name: str,
        context: GenerationContext,
        previous_sections: Dict[str, SectionResult],
    ) -> SectionResult:
        """
        Generate a single section with citation tracking.

        Args:
            section_name: Name of the section
            context: Generation context
            previous_sections: Previously generated sections

        Returns:
            SectionResult with content and citations
        """
        import time

        start_time = time.time()

        prompt = self._get_section_prompt(section_name, context, previous_sections)

        try:
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            token_count = response.usage.input_tokens + response.usage.output_tokens

            # Parse citations from the generated content
            citations = self._parse_citations_from_content(
                content, context.source_materials
            )

            # Calculate grounding score
            from app.services.generation.grounding import GroundingEnforcer

            enforcer = GroundingEnforcer()
            grounding_result = enforcer.check_grounding(
                content, citations, context.source_materials
            )

            generation_time = int((time.time() - start_time) * 1000)

            return SectionResult(
                section_name=section_name,
                content=content,
                citations=citations,
                token_count=token_count,
                generation_time_ms=generation_time,
                grounding_score=grounding_result.grounding_score,
                ungrounded_claims=grounding_result.ungrounded_claims,
            )

        except Exception as e:
            logger.error(f"Error generating section {section_name}: {e}")
            return SectionResult(
                section_name=section_name,
                content=f"Error generating section: {str(e)}",
                grounding_score=0.0,
            )

    async def _self_check_citations(
        self,
        result: GenerationResult,
        context: GenerationContext,
    ) -> GenerationResult:
        """
        Perform a self-check pass to verify citation coverage.

        Args:
            result: Initial generation result
            context: Generation context

        Returns:
            Updated result with any corrections
        """
        if not self.config.enable_self_check:
            return result

        self_check_prompt = f"""
Review the following generated content for citation coverage and grounding.

Content to review:
{result.combined_content}

Available sources:
{self._build_source_context(context.source_materials)}

Tasks:
1. Identify any claims that are not properly cited
2. Verify all citations are accurate and relevant
3. Flag any potentially misleading or ungrounded statements

Provide your analysis in this format:
<analysis>
<ungrounded_claims>
- List any claims without proper citations
</ungrounded_claims>
<citation_issues>
- List any citation accuracy issues
</citation_issues>
<overall_assessment>
Brief assessment of grounding quality
</overall_assessment>
<grounding_score>0.XX</grounding_score>
</analysis>
"""

        try:
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=1024,
                temperature=0.1,
                messages=[{"role": "user", "content": self_check_prompt}],
            )

            analysis = response.content[0].text

            # Parse grounding score from analysis
            import re

            score_match = re.search(
                r"<grounding_score>([\d.]+)</grounding_score>", analysis
            )
            if score_match:
                try:
                    result.overall_grounding_score = float(score_match.group(1))
                except ValueError:
                    pass

            # Extract ungrounded claims
            claims_match = re.search(
                r"<ungrounded_claims>(.*?)</ungrounded_claims>", analysis, re.DOTALL
            )
            if claims_match:
                claims_text = claims_match.group(1).strip()
                if claims_text and claims_text != "- None":
                    result.warnings.append(f"Self-check found issues: {claims_text}")

        except Exception as e:
            logger.warning(f"Self-check failed: {e}")
            result.warnings.append(f"Self-check could not be completed: {str(e)}")

        return result

    async def generate(
        self,
        context: GenerationContext,
        title: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate a complete artifact with all sections.

        Args:
            context: Generation context with source materials
            title: Optional title for the artifact

        Returns:
            Complete GenerationResult
        """
        import time

        start_time = time.time()

        result = GenerationResult(
            artifact_type=self._get_artifact_type(),
            title=title or f"{self._get_artifact_type().title()} - {datetime.utcnow().strftime('%Y-%m-%d')}",
        )

        if context.subject_name:
            result.title = f"{context.subject_name} - {result.title}"

        sections = self._get_sections()
        previous_sections: Dict[str, SectionResult] = {}
        all_citations: List[Citation] = []
        combined_parts: List[str] = []
        total_tokens = 0

        for section_name in sections:
            logger.info(f"Generating section: {section_name}")

            section_result = await self._generate_section(
                section_name, context, previous_sections
            )

            result.sections[section_name] = section_result
            previous_sections[section_name] = section_result
            all_citations.extend(section_result.citations)
            total_tokens += section_result.token_count

            # Add to combined content
            combined_parts.append(f"## {section_name.replace('_', ' ').title()}\n\n")
            combined_parts.append(section_result.content)
            combined_parts.append("\n\n")

            # Check for grounding issues
            if (
                self.config.require_grounding
                and section_result.grounding_score < self.config.min_grounding_score
            ):
                result.warnings.append(
                    f"Section '{section_name}' has low grounding score: "
                    f"{section_result.grounding_score:.2%}"
                )

        result.combined_content = "".join(combined_parts)
        result.all_citations = self._deduplicate_citations(all_citations)
        result.total_tokens = total_tokens
        result.total_generation_time_ms = int((time.time() - start_time) * 1000)

        # Calculate overall grounding score
        if result.sections:
            scores = [s.grounding_score for s in result.sections.values()]
            result.overall_grounding_score = sum(scores) / len(scores)

        # Perform self-check if enabled
        if self.config.enable_self_check:
            result = await self._self_check_citations(result, context)

        # Add final warnings
        if result.overall_grounding_score < self.config.min_grounding_score:
            result.warnings.append(
                f"Overall grounding score ({result.overall_grounding_score:.2%}) "
                f"is below minimum threshold ({self.config.min_grounding_score:.2%})"
            )

        result.metadata = {
            "config": self.config.model_dump(),
            "subject_id": str(context.subject_id) if context.subject_id else None,
            "timeframe": {
                "start": context.timeframe_start.isoformat()
                if context.timeframe_start
                else None,
                "end": context.timeframe_end.isoformat()
                if context.timeframe_end
                else None,
            },
            "source_count": len(context.source_materials),
        }

        return result

    def _deduplicate_citations(self, citations: List[Citation]) -> List[Citation]:
        """Remove duplicate citations based on item_id."""
        seen = set()
        unique = []
        for citation in citations:
            if citation.item_id not in seen:
                seen.add(citation.item_id)
                unique.append(citation)
        return unique

    def set_template(self, template: Any) -> None:
        """
        Set a custom template for generation.

        Args:
            template: Template configuration object
        """
        self._template = template

    def get_template(self) -> Optional[Any]:
        """Get the current template."""
        return self._template
