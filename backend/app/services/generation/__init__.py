"""
Lantern Generation Layer

This module provides the complete generation infrastructure for creating
grounded, citation-backed artifacts including reports, memos, timelines,
and newsletters.

All generators enforce grounding - every non-trivial claim must be backed
by a citation to source material.
"""

from app.services.generation.base import (
    BaseGenerator,
    GeneratorConfig,
    GenerationResult,
    SectionResult,
)
from app.services.generation.report import (
    ReportGenerator,
    ReportConfig,
)
from app.services.generation.memo import (
    MemoGenerator,
    MemoConfig,
    MemoTone,
)
from app.services.generation.timeline import (
    TimelineGenerator,
    TimelineConfig,
    TimelineFormat,
)
from app.services.generation.newsletter import (
    NewsletterGenerator,
    NewsletterConfig,
)
from app.services.generation.templates import (
    TemplateManager,
    Template,
    TemplateSection,
    ReportTemplate,
    MemoTemplate,
    TimelineTemplate,
    NewsletterTemplate,
)
from app.services.generation.citations import (
    CitationManager,
    Citation,
    CitationFormat,
    CitationValidationResult,
)
from app.services.generation.grounding import (
    GroundingEnforcer,
    GroundingResult,
    UngroundedClaim,
)

__all__ = [
    # Base components
    "BaseGenerator",
    "GeneratorConfig",
    "GenerationResult",
    "SectionResult",
    # Report generation
    "ReportGenerator",
    "ReportConfig",
    # Memo generation
    "MemoGenerator",
    "MemoConfig",
    "MemoTone",
    # Timeline generation
    "TimelineGenerator",
    "TimelineConfig",
    "TimelineFormat",
    # Newsletter generation
    "NewsletterGenerator",
    "NewsletterConfig",
    # Templates
    "TemplateManager",
    "Template",
    "TemplateSection",
    "ReportTemplate",
    "MemoTemplate",
    "TimelineTemplate",
    "NewsletterTemplate",
    # Citations
    "CitationManager",
    "Citation",
    "CitationFormat",
    "CitationValidationResult",
    # Grounding
    "GroundingEnforcer",
    "GroundingResult",
    "UngroundedClaim",
]
