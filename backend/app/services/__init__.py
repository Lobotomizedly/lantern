"""
Lantern Services Layer

This module exports all service components for the Lantern platform,
including generation services, artifact management, and review workflows.
"""

from app.services.generation import (
    # Base components
    BaseGenerator,
    GeneratorConfig,
    GenerationResult,
    SectionResult,
    # Generators
    ReportGenerator,
    ReportConfig,
    MemoGenerator,
    MemoConfig,
    MemoTone,
    TimelineGenerator,
    TimelineConfig,
    TimelineFormat,
    NewsletterGenerator,
    NewsletterConfig,
    # Templates
    TemplateManager,
    Template,
    TemplateSection,
    ReportTemplate,
    MemoTemplate,
    TimelineTemplate,
    NewsletterTemplate,
    # Citations
    CitationManager,
    Citation,
    CitationFormat,
    CitationValidationResult,
    # Grounding
    GroundingEnforcer,
    GroundingResult,
    UngroundedClaim,
)
from app.services.artifact_service import (
    ArtifactService,
    ArtifactRequest,
    ArtifactStatus,
    ArtifactQueueItem,
)
from app.services.review_service import (
    ReviewService,
    ReviewQueueItem,
    ReviewDecision,
    ReviewFeedback,
    ReviewStatus,
)

__all__ = [
    # Base components
    "BaseGenerator",
    "GeneratorConfig",
    "GenerationResult",
    "SectionResult",
    # Generators
    "ReportGenerator",
    "ReportConfig",
    "MemoGenerator",
    "MemoConfig",
    "MemoTone",
    "TimelineGenerator",
    "TimelineConfig",
    "TimelineFormat",
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
    # Artifact Service
    "ArtifactService",
    "ArtifactRequest",
    "ArtifactStatus",
    "ArtifactQueueItem",
    # Review Service
    "ReviewService",
    "ReviewQueueItem",
    "ReviewDecision",
    "ReviewFeedback",
    "ReviewStatus",
]
