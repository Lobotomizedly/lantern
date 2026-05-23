"""
Memo Generator

Creates short, audience-targeted intelligence briefs with tone-controlled
output. Supports generating multiple tonal variants (formal, concise, detailed).
"""

import logging
from datetime import datetime
from enum import Enum
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
    MemoTemplate,
    MemoToneVariant,
    TemplateManager,
    TemplateSection,
)

logger = logging.getLogger(__name__)


class MemoTone(str, Enum):
    """Available memo tones."""

    FORMAL = "formal"
    CONCISE = "concise"
    DETAILED = "detailed"


class MemoConfig(GeneratorConfig):
    """Configuration for memo generation."""

    tone: MemoTone = Field(
        default=MemoTone.FORMAL,
        description="Primary tone for the memo",
    )
    target_audience: Optional[str] = Field(
        default=None,
        description="Description of target audience",
    )
    max_length_words: int = Field(
        default=500,
        description="Target maximum word count",
    )
    generate_variants: bool = Field(
        default=False,
        description="Generate all tone variants",
    )
    include_action_items: bool = Field(
        default=True,
        description="Include recommended actions section",
    )
    urgency_level: Optional[str] = Field(
        default=None,
        description="Urgency indicator (routine, important, urgent, critical)",
    )


class MemoVariant(GenerationResult):
    """A single memo variant with its tone."""

    tone: MemoTone
    word_count: int = 0


class MemoGenerationResult(GenerationResult):
    """Result containing one or more memo variants."""

    primary_variant: Optional[MemoVariant] = None
    all_variants: Dict[str, MemoVariant] = Field(default_factory=dict)


class MemoGenerator(BaseGenerator[MemoConfig]):
    """
    Generates short, audience-targeted intelligence briefs.

    Features:
    - Tone-controlled output (formal, concise, detailed)
    - Audience targeting
    - Multiple variant generation
    - Tight, immediately usable output
    - Full citation support
    """

    def __init__(
        self,
        config: Optional[MemoConfig] = None,
        template: Optional[MemoTemplate] = None,
        **kwargs,
    ):
        """
        Initialize the memo generator.

        Args:
            config: Memo generation configuration
            template: Custom memo template
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
        return TemplateType.MEMO

    def _default_config(self) -> MemoConfig:
        """Return default memo configuration."""
        return MemoConfig()

    def _get_artifact_type(self) -> str:
        """Return the artifact type string."""
        return "memo"

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
                "key_takeaways",
                "situation",
                "assessment",
            ]
            if self.config.include_action_items:
                section_names.append("recommended_actions")

        return section_names

    def _get_template_section(self, section_name: str) -> Optional[TemplateSection]:
        """Get the template section definition."""
        if not self._template:
            return None

        for section in self._template.sections:
            if section.name == section_name:
                return section

        return None

    def _get_tone_variant(self, tone: MemoTone) -> Optional[MemoToneVariant]:
        """Get tone variant configuration from template."""
        if not self._template or not hasattr(self._template, "tone_variants"):
            return None

        for variant in self._template.tone_variants:
            if variant.name == tone.value:
                return variant

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
        # Get tone settings
        tone_variant = self._get_tone_variant(self.config.tone)
        tone_instructions = ""
        max_words = self.config.max_length_words

        if tone_variant:
            tone_instructions = tone_variant.tone_instructions
            max_words = min(max_words, tone_variant.max_length)

        # Get template section
        template_section = self._get_template_section(section_name)

        # Build system prompt with tone
        system_prompt = self._template.system_prompt if self._template else (
            "You are creating a tight, immediately actionable intelligence brief."
        )

        # Build source context
        source_context = self._build_source_context(context.source_materials)

        # Build previous sections context
        previous_context = ""
        if previous_sections:
            previous_context = "\n\nPREVIOUS SECTIONS:\n"
            for name, result in previous_sections.items():
                previous_context += f"\n### {name}\n{result.content}\n"

        # Get section-specific prompt
        if template_section:
            section_prompt = template_section.prompt
        else:
            section_prompt = self._get_default_section_prompt(section_name)

        # Build audience context
        audience_context = ""
        if self.config.target_audience:
            audience_context = f"\nTARGET AUDIENCE: {self.config.target_audience}\n"

        # Build urgency indicator
        urgency_context = ""
        if self.config.urgency_level:
            urgency_context = f"\nURGENCY: {self.config.urgency_level.upper()}\n"

        # Subject context
        subject_context = ""
        if context.subject_name:
            subject_context = f"Subject: {context.subject_name}\n"

        # Citation instructions
        citation_instructions = self._build_citation_instructions()

        # Assemble prompt
        prompt = f"""{system_prompt}

{audience_context}
{urgency_context}
{subject_context}

TONE REQUIREMENTS:
{tone_instructions}

Maximum length: approximately {max_words} words for entire memo.
Be concise and direct. Every word must earn its place.

{citation_instructions}

SOURCE MATERIALS:
{source_context}

{previous_context}

TASK: Generate the "{section_name.replace('_', ' ').title()}" section.

{section_prompt}

Remember: Cite facts using [N] format. Keep it brief but complete."""

        return prompt

    def _get_default_section_prompt(self, section_name: str) -> str:
        """Get default prompt for a section."""
        prompts = {
            "key_takeaways": """List 3-5 key takeaways. Each should be:
- Actionable or directly informative
- Supported by cited evidence
- One sentence max

Format as a bulleted list.""",

            "situation": """Briefly describe the current situation:
- What is happening?
- Who is involved?
- What is the timeline?

Keep it factual and cited. 2-3 short paragraphs max.""",

            "assessment": """Provide a brief assessment:
- What does this mean for the subject?
- What are potential implications?
- What should be monitored?

Be direct and specific.""",

            "recommended_actions": """Suggest 2-3 specific actions:
- What should the reader do?
- What decisions need to be made?
- What requires immediate attention?

Make actions concrete and achievable.""",
        }

        return prompts.get(section_name, f"Generate the {section_name} section.")

    async def generate_memo(
        self,
        subject_id: UUID,
        subject_name: str,
        source_materials: List[SourceMaterial],
        title: Optional[str] = None,
        tone: Optional[MemoTone] = None,
        target_audience: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate a single memo.

        Args:
            subject_id: Subject ID
            subject_name: Subject name
            source_materials: Source materials
            title: Optional title
            tone: Override default tone
            target_audience: Override target audience

        Returns:
            GenerationResult with memo content
        """
        # Override config if specified
        if tone:
            self.config.tone = tone
        if target_audience:
            self.config.target_audience = target_audience

        context = GenerationContext(
            subject_id=subject_id,
            subject_name=subject_name,
            source_materials=source_materials,
        )

        result = await self.generate(context, title=title)

        # Add memo-specific metadata
        result.metadata["tone"] = self.config.tone.value
        result.metadata["target_audience"] = self.config.target_audience
        result.metadata["word_count"] = self._count_words(result.combined_content)

        return result

    async def generate_variants(
        self,
        subject_id: UUID,
        subject_name: str,
        source_materials: List[SourceMaterial],
        title: Optional[str] = None,
        tones: Optional[List[MemoTone]] = None,
    ) -> MemoGenerationResult:
        """
        Generate multiple tonal variants of a memo.

        Args:
            subject_id: Subject ID
            subject_name: Subject name
            source_materials: Source materials
            title: Optional title
            tones: Specific tones to generate (default: all)

        Returns:
            MemoGenerationResult with all variants
        """
        if not tones:
            tones = [MemoTone.FORMAL, MemoTone.CONCISE, MemoTone.DETAILED]

        # Store original config
        original_tone = self.config.tone

        result = MemoGenerationResult(
            artifact_type="memo_variants",
            title=title or f"Intelligence Brief - {subject_name}",
        )

        variants: Dict[str, MemoVariant] = {}
        primary_variant: Optional[MemoVariant] = None

        for tone in tones:
            logger.info(f"Generating {tone.value} variant")

            self.config.tone = tone

            variant_result = await self.generate_memo(
                subject_id=subject_id,
                subject_name=subject_name,
                source_materials=source_materials,
                title=f"{title} ({tone.value})" if title else None,
                tone=tone,
            )

            variant = MemoVariant(
                artifact_id=variant_result.artifact_id,
                artifact_type="memo",
                title=variant_result.title,
                sections=variant_result.sections,
                combined_content=variant_result.combined_content,
                all_citations=variant_result.all_citations,
                total_tokens=variant_result.total_tokens,
                total_generation_time_ms=variant_result.total_generation_time_ms,
                overall_grounding_score=variant_result.overall_grounding_score,
                metadata=variant_result.metadata,
                warnings=variant_result.warnings,
                tone=tone,
                word_count=self._count_words(variant_result.combined_content),
            )

            variants[tone.value] = variant

            # Track primary (first or formal)
            if tone == original_tone or primary_variant is None:
                primary_variant = variant

        # Restore original config
        self.config.tone = original_tone

        # Populate result
        result.all_variants = variants
        result.primary_variant = primary_variant
        result.combined_content = primary_variant.combined_content if primary_variant else ""
        result.all_citations = primary_variant.all_citations if primary_variant else []
        result.metadata = {
            "variant_count": len(variants),
            "tones": [t.value for t in tones],
        }

        # Aggregate totals
        result.total_tokens = sum(v.total_tokens for v in variants.values())
        result.total_generation_time_ms = sum(
            v.total_generation_time_ms for v in variants.values()
        )

        return result

    def _count_words(self, text: str) -> int:
        """Count words in text."""
        import re
        # Remove markdown formatting and count
        clean = re.sub(r"[#*_\[\]()]", "", text)
        words = clean.split()
        return len(words)

    async def generate_quick_brief(
        self,
        subject_name: str,
        key_points: List[str],
        source_materials: List[SourceMaterial],
    ) -> str:
        """
        Generate a very quick briefing from key points.

        Args:
            subject_name: Subject name
            key_points: Pre-identified key points
            source_materials: Source materials for citation

        Returns:
            Brief text content
        """
        source_context = self._build_source_context(source_materials)

        prompt = f"""Create a 100-word intelligence brief about {subject_name}.

Key points to cover:
{chr(10).join(f'- {p}' for p in key_points)}

Sources:
{source_context}

Requirements:
- Maximum 100 words
- Cite key facts using [N] format
- Direct and actionable
- Lead with most important information"""

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=256,
            temperature=self.config.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text

    def set_tone(self, tone: MemoTone) -> None:
        """
        Set the memo tone.

        Args:
            tone: Tone to use
        """
        self.config.tone = tone

    def set_audience(self, audience: str) -> None:
        """
        Set the target audience.

        Args:
            audience: Description of target audience
        """
        self.config.target_audience = audience

    def set_urgency(self, level: str) -> None:
        """
        Set urgency level.

        Args:
            level: Urgency level (routine, important, urgent, critical)
        """
        valid_levels = {"routine", "important", "urgent", "critical"}
        if level.lower() in valid_levels:
            self.config.urgency_level = level.lower()
