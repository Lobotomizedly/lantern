"""
Artifact Service

Manages artifact creation, queuing, status tracking, and review workflow.
Handles the full lifecycle from request to publication.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.generation import (
    BaseGenerator,
    GenerationResult,
    MemoGenerator,
    NewsletterGenerator,
    ReportGenerator,
    TimelineGenerator,
)
from app.services.generation.base import GenerationContext, SourceMaterial

logger = logging.getLogger(__name__)


class ArtifactStatus(str, Enum):
    """Status of an artifact in the workflow."""

    PENDING = "pending"  # Request created, awaiting generation
    GENERATING = "generating"  # Generation in progress
    DRAFT = "draft"  # Generated, ready for review
    IN_REVIEW = "in_review"  # Under review
    REVISION_REQUESTED = "revision_requested"  # Needs changes
    APPROVED = "approved"  # Approved, ready for publication
    PUBLISHED = "published"  # Published/delivered
    REJECTED = "rejected"  # Rejected, will not be published
    FAILED = "failed"  # Generation failed


class ArtifactType(str, Enum):
    """Types of artifacts that can be generated."""

    REPORT = "report"
    MEMO = "memo"
    TIMELINE = "timeline"
    NEWSLETTER = "newsletter"


class ArtifactRequest(BaseModel):
    """Request to generate an artifact."""

    id: UUID = Field(default_factory=uuid4)
    artifact_type: ArtifactType
    title: Optional[str] = None
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    timeframe_start: Optional[datetime] = None
    timeframe_end: Optional[datetime] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    source_item_ids: List[UUID] = Field(default_factory=list)
    user_instructions: Optional[str] = None
    priority: int = Field(default=0, description="Higher = more urgent")
    requested_by: Optional[UUID] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactQueueItem(BaseModel):
    """An item in the generation queue."""

    id: UUID = Field(default_factory=uuid4)
    request: ArtifactRequest
    status: ArtifactStatus = ArtifactStatus.PENDING
    generation_result: Optional[GenerationResult] = None
    error_message: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class ArtifactRecord(BaseModel):
    """Complete artifact record with all metadata."""

    id: UUID = Field(default_factory=uuid4)
    request: ArtifactRequest
    status: ArtifactStatus
    content: Optional[str] = None
    generation_result: Optional[Dict[str, Any]] = None
    version: int = 1
    previous_versions: List[UUID] = Field(default_factory=list)
    review_notes: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ArtifactService:
    """
    Service for managing artifact generation and workflow.

    Handles:
    - Creating artifact requests
    - Queuing for generation
    - Tracking status through workflow
    - Managing review process
    - Publishing approved artifacts
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        """
        Initialize the artifact service.

        Args:
            session: Optional database session
        """
        self.session = session

        # In-memory queue for simplicity (use Redis/DB in production)
        self._queue: Dict[UUID, ArtifactQueueItem] = {}
        self._artifacts: Dict[UUID, ArtifactRecord] = {}

        # Generator registry
        self._generators: Dict[ArtifactType, Type[BaseGenerator]] = {
            ArtifactType.REPORT: ReportGenerator,
            ArtifactType.MEMO: MemoGenerator,
            ArtifactType.TIMELINE: TimelineGenerator,
            ArtifactType.NEWSLETTER: NewsletterGenerator,
        }

    async def create_request(
        self,
        artifact_type: ArtifactType,
        title: Optional[str] = None,
        subject_id: Optional[UUID] = None,
        subject_name: Optional[str] = None,
        timeframe_start: Optional[datetime] = None,
        timeframe_end: Optional[datetime] = None,
        source_item_ids: Optional[List[UUID]] = None,
        config: Optional[Dict[str, Any]] = None,
        user_instructions: Optional[str] = None,
        priority: int = 0,
        requested_by: Optional[UUID] = None,
    ) -> ArtifactRequest:
        """
        Create a new artifact generation request.

        Args:
            artifact_type: Type of artifact to generate
            title: Optional title
            subject_id: Subject ID for the artifact
            subject_name: Subject name
            timeframe_start: Start of timeframe
            timeframe_end: End of timeframe
            source_item_ids: IDs of source items to use
            config: Generator-specific configuration
            user_instructions: Additional instructions
            priority: Request priority
            requested_by: User ID of requester

        Returns:
            ArtifactRequest
        """
        request = ArtifactRequest(
            artifact_type=artifact_type,
            title=title,
            subject_id=subject_id,
            subject_name=subject_name,
            timeframe_start=timeframe_start,
            timeframe_end=timeframe_end,
            source_item_ids=source_item_ids or [],
            config=config or {},
            user_instructions=user_instructions,
            priority=priority,
            requested_by=requested_by,
        )

        logger.info(f"Created artifact request: {request.id} ({artifact_type.value})")

        return request

    async def queue_for_generation(
        self,
        request: ArtifactRequest,
    ) -> ArtifactQueueItem:
        """
        Add an artifact request to the generation queue.

        Args:
            request: Artifact request to queue

        Returns:
            ArtifactQueueItem representing the queued request
        """
        queue_item = ArtifactQueueItem(
            request=request,
            status=ArtifactStatus.PENDING,
        )

        self._queue[queue_item.id] = queue_item

        logger.info(f"Queued artifact for generation: {queue_item.id}")

        return queue_item

    async def get_queue_item(self, item_id: UUID) -> Optional[ArtifactQueueItem]:
        """Get a queue item by ID."""
        return self._queue.get(item_id)

    async def get_queue_status(self) -> Dict[str, int]:
        """Get counts of items by status."""
        counts: Dict[str, int] = {}
        for item in self._queue.values():
            status = item.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts

    async def get_pending_items(
        self,
        limit: int = 10,
    ) -> List[ArtifactQueueItem]:
        """
        Get pending items from the queue, ordered by priority.

        Args:
            limit: Maximum items to return

        Returns:
            List of pending queue items
        """
        pending = [
            item for item in self._queue.values()
            if item.status == ArtifactStatus.PENDING
        ]

        # Sort by priority (descending) then by created_at (ascending)
        pending.sort(
            key=lambda x: (-x.request.priority, x.created_at)
        )

        return pending[:limit]

    async def process_queue_item(
        self,
        item_id: UUID,
        source_materials: List[SourceMaterial],
    ) -> ArtifactQueueItem:
        """
        Process a queued item by generating the artifact.

        Args:
            item_id: ID of the queue item
            source_materials: Source materials for generation

        Returns:
            Updated queue item
        """
        item = self._queue.get(item_id)
        if not item:
            raise ValueError(f"Queue item not found: {item_id}")

        if item.status != ArtifactStatus.PENDING:
            raise ValueError(f"Item is not pending: {item.status}")

        # Update status
        item.status = ArtifactStatus.GENERATING
        item.started_at = datetime.utcnow()
        item.attempts += 1

        try:
            # Get the appropriate generator
            generator_class = self._generators.get(item.request.artifact_type)
            if not generator_class:
                raise ValueError(f"Unknown artifact type: {item.request.artifact_type}")

            # Create generator with config
            generator = generator_class(config=item.request.config)

            # Build generation context
            context = GenerationContext(
                subject_id=item.request.subject_id,
                subject_name=item.request.subject_name,
                timeframe_start=item.request.timeframe_start,
                timeframe_end=item.request.timeframe_end,
                source_materials=source_materials,
                user_instructions=item.request.user_instructions,
            )

            # Generate
            result = await generator.generate(context, title=item.request.title)

            # Update item
            item.generation_result = result
            item.status = ArtifactStatus.DRAFT
            item.completed_at = datetime.utcnow()

            # Create artifact record
            await self._create_artifact_record(item)

            logger.info(f"Successfully generated artifact: {item_id}")

        except Exception as e:
            logger.error(f"Failed to generate artifact {item_id}: {e}")

            item.error_message = str(e)

            if item.attempts >= item.max_attempts:
                item.status = ArtifactStatus.FAILED
            else:
                item.status = ArtifactStatus.PENDING  # Retry

        return item

    async def _create_artifact_record(
        self,
        queue_item: ArtifactQueueItem,
    ) -> ArtifactRecord:
        """Create an artifact record from a completed queue item."""
        if not queue_item.generation_result:
            raise ValueError("No generation result to create record from")

        record = ArtifactRecord(
            id=queue_item.generation_result.artifact_id,
            request=queue_item.request,
            status=queue_item.status,
            content=queue_item.generation_result.combined_content,
            generation_result=queue_item.generation_result.model_dump(),
            metrics={
                "grounding_score": queue_item.generation_result.overall_grounding_score,
                "total_tokens": queue_item.generation_result.total_tokens,
                "generation_time_ms": queue_item.generation_result.total_generation_time_ms,
                "citation_count": len(queue_item.generation_result.all_citations),
            },
        )

        self._artifacts[record.id] = record

        return record

    async def get_artifact(self, artifact_id: UUID) -> Optional[ArtifactRecord]:
        """Get an artifact by ID."""
        return self._artifacts.get(artifact_id)

    async def list_artifacts(
        self,
        status: Optional[ArtifactStatus] = None,
        artifact_type: Optional[ArtifactType] = None,
        subject_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ArtifactRecord]:
        """
        List artifacts with optional filters.

        Args:
            status: Filter by status
            artifact_type: Filter by type
            subject_id: Filter by subject
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of artifact records
        """
        results = list(self._artifacts.values())

        if status:
            results = [a for a in results if a.status == status]

        if artifact_type:
            results = [
                a for a in results
                if a.request.artifact_type == artifact_type
            ]

        if subject_id:
            results = [
                a for a in results
                if a.request.subject_id == subject_id
            ]

        # Sort by created_at descending
        results.sort(key=lambda x: x.created_at, reverse=True)

        return results[offset:offset + limit]

    async def update_status(
        self,
        artifact_id: UUID,
        status: ArtifactStatus,
        notes: Optional[str] = None,
    ) -> ArtifactRecord:
        """
        Update artifact status.

        Args:
            artifact_id: Artifact ID
            status: New status
            notes: Optional notes

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        old_status = artifact.status
        artifact.status = status
        artifact.updated_at = datetime.utcnow()

        if notes:
            artifact.review_notes.append(f"[{datetime.utcnow().isoformat()}] {notes}")

        if status == ArtifactStatus.PUBLISHED:
            artifact.published_at = datetime.utcnow()

        logger.info(
            f"Updated artifact {artifact_id} status: {old_status.value} -> {status.value}"
        )

        return artifact

    async def submit_for_review(
        self,
        artifact_id: UUID,
    ) -> ArtifactRecord:
        """
        Submit an artifact for review.

        Args:
            artifact_id: Artifact ID

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status not in (ArtifactStatus.DRAFT, ArtifactStatus.REVISION_REQUESTED):
            raise ValueError(f"Cannot submit for review from status: {artifact.status}")

        return await self.update_status(
            artifact_id,
            ArtifactStatus.IN_REVIEW,
            notes="Submitted for review",
        )

    async def approve(
        self,
        artifact_id: UUID,
        notes: Optional[str] = None,
    ) -> ArtifactRecord:
        """
        Approve an artifact.

        Args:
            artifact_id: Artifact ID
            notes: Optional approval notes

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status != ArtifactStatus.IN_REVIEW:
            raise ValueError(f"Cannot approve from status: {artifact.status}")

        return await self.update_status(
            artifact_id,
            ArtifactStatus.APPROVED,
            notes=notes or "Approved",
        )

    async def reject(
        self,
        artifact_id: UUID,
        reason: str,
    ) -> ArtifactRecord:
        """
        Reject an artifact.

        Args:
            artifact_id: Artifact ID
            reason: Rejection reason

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status != ArtifactStatus.IN_REVIEW:
            raise ValueError(f"Cannot reject from status: {artifact.status}")

        return await self.update_status(
            artifact_id,
            ArtifactStatus.REJECTED,
            notes=f"Rejected: {reason}",
        )

    async def request_revision(
        self,
        artifact_id: UUID,
        feedback: str,
    ) -> ArtifactRecord:
        """
        Request revisions to an artifact.

        Args:
            artifact_id: Artifact ID
            feedback: Revision feedback

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status != ArtifactStatus.IN_REVIEW:
            raise ValueError(f"Cannot request revision from status: {artifact.status}")

        return await self.update_status(
            artifact_id,
            ArtifactStatus.REVISION_REQUESTED,
            notes=f"Revision requested: {feedback}",
        )

    async def publish(
        self,
        artifact_id: UUID,
        publish_config: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """
        Publish an approved artifact.

        Args:
            artifact_id: Artifact ID
            publish_config: Publication configuration

        Returns:
            Updated artifact record
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if artifact.status != ArtifactStatus.APPROVED:
            raise ValueError(f"Cannot publish from status: {artifact.status}")

        # TODO: Implement actual publication logic
        # - Email delivery
        # - Slack posting
        # - File export
        # - API notification

        return await self.update_status(
            artifact_id,
            ArtifactStatus.PUBLISHED,
            notes="Published successfully",
        )

    async def regenerate(
        self,
        artifact_id: UUID,
        source_materials: List[SourceMaterial],
        config_overrides: Optional[Dict[str, Any]] = None,
    ) -> ArtifactQueueItem:
        """
        Regenerate an artifact.

        Args:
            artifact_id: Original artifact ID
            source_materials: Source materials
            config_overrides: Configuration overrides

        Returns:
            New queue item for regeneration
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        # Create new request based on original
        new_request = artifact.request.model_copy()
        new_request.id = uuid4()

        if config_overrides:
            new_request.config.update(config_overrides)

        # Track version history
        artifact.previous_versions.append(artifact.id)
        artifact.version += 1

        # Queue for regeneration
        queue_item = await self.queue_for_generation(new_request)

        # Process immediately
        return await self.process_queue_item(queue_item.id, source_materials)

    async def get_artifact_history(
        self,
        artifact_id: UUID,
    ) -> List[ArtifactRecord]:
        """
        Get version history for an artifact.

        Args:
            artifact_id: Artifact ID

        Returns:
            List of artifact versions
        """
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return []

        history = []
        for version_id in artifact.previous_versions:
            if version_id in self._artifacts:
                history.append(self._artifacts[version_id])

        history.append(artifact)

        return sorted(history, key=lambda x: x.version)

    async def cleanup_old_items(
        self,
        max_age_days: int = 30,
    ) -> int:
        """
        Clean up old queue items and artifacts.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of items cleaned up
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        cleaned = 0

        # Clean queue items
        to_remove = [
            item_id for item_id, item in self._queue.items()
            if item.created_at < cutoff
            and item.status in (ArtifactStatus.FAILED, ArtifactStatus.REJECTED)
        ]

        for item_id in to_remove:
            del self._queue[item_id]
            cleaned += 1

        logger.info(f"Cleaned up {cleaned} old queue items")

        return cleaned
