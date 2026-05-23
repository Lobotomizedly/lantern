"""
Lantern Processing Pipeline

This module provides a queue-driven processing pipeline for ingesting,
normalizing, and enriching content items for narrative intelligence analysis.
"""

from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    PipelineError,
    RetryableError,
    NonRetryableError,
)
from app.pipeline.normalize import NormalizeStage
from app.pipeline.dedup import DedupStage
from app.pipeline.embed import EmbedStage
from app.pipeline.entity import EntityExtractionStage
from app.pipeline.claim import ClaimExtractionStage
from app.pipeline.classify import ClassifyStage
from app.pipeline.event import EventDetectionStage
from app.pipeline.narrative import NarrativeAssignmentStage
from app.pipeline.orchestrator import (
    PipelineOrchestrator,
    ProcessingStatus,
    QueueManager,
)

__all__ = [
    # Base
    "PipelineStage",
    "PipelineContext",
    "PipelineError",
    "RetryableError",
    "NonRetryableError",
    # Stages
    "NormalizeStage",
    "DedupStage",
    "EmbedStage",
    "EntityExtractionStage",
    "ClaimExtractionStage",
    "ClassifyStage",
    "EventDetectionStage",
    "NarrativeAssignmentStage",
    # Orchestrator
    "PipelineOrchestrator",
    "ProcessingStatus",
    "QueueManager",
]
