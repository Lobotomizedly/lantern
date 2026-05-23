"""
Pipeline Orchestrator

Manages the processing pipeline:
- Queue management
- Stage routing
- Error handling and dead-letter queue
- Processing status tracking
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Optional, Type
from uuid import UUID, uuid4

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import get_session_context
from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    PipelineError,
    RetryableError,
    NonRetryableError,
    StageMetrics,
)
from app.pipeline.normalize import NormalizeStage
from app.pipeline.dedup import DedupStage
from app.pipeline.embed import EmbedStage
from app.pipeline.entity import EntityExtractionStage
from app.pipeline.claim import ClaimExtractionStage
from app.pipeline.classify import ClassifyStage
from app.pipeline.event import EventDetectionStage
from app.pipeline.narrative import NarrativeAssignmentStage


logger = logging.getLogger(__name__)


class ProcessingStatus(str, Enum):
    """Status of item processing."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Some stages completed


# Pipeline stage order
PIPELINE_STAGES = [
    "normalize",
    "dedup",
    "embed",
    "entity",
    "claim",
    "classify",
    "event",
    "narrative",
]

# Stage class mapping
STAGE_CLASSES: dict[str, Type[PipelineStage]] = {
    "normalize": NormalizeStage,
    "dedup": DedupStage,
    "embed": EmbedStage,
    "entity": EntityExtractionStage,
    "claim": ClaimExtractionStage,
    "classify": ClassifyStage,
    "event": EventDetectionStage,
    "narrative": NarrativeAssignmentStage,
}


@dataclass
class ProcessingJob:
    """Represents a processing job in the pipeline."""

    job_id: UUID
    item_id: UUID
    source_id: Optional[UUID]
    raw_content: str
    url: Optional[str] = None
    title: Optional[str] = None
    content_type: str = "article"
    priority: int = 5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> PipelineContext:
        """Convert job to pipeline context."""
        return PipelineContext(
            run_id=self.job_id,
            item_id=self.item_id,
            source_id=self.source_id,
            raw_content=self.raw_content,
            url=self.url,
            title=self.title,
            content_type=self.content_type,
            priority=self.priority,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "job_id": str(self.job_id),
            "item_id": str(self.item_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "raw_content": self.raw_content,
            "url": self.url,
            "title": self.title,
            "content_type": self.content_type,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessingJob":
        """Create from dictionary."""
        return cls(
            job_id=UUID(data["job_id"]),
            item_id=UUID(data["item_id"]),
            source_id=UUID(data["source_id"]) if data.get("source_id") else None,
            raw_content=data["raw_content"],
            url=data.get("url"),
            title=data.get("title"),
            content_type=data.get("content_type", "article"),
            priority=data.get("priority", 5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ProcessingResult:
    """Result of processing an item through the pipeline."""

    job_id: UUID
    item_id: UUID
    status: ProcessingStatus
    stages_completed: list[str]
    stages_failed: list[str]
    errors: list[dict[str, Any]]
    duration_ms: float
    context: Optional[PipelineContext] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": str(self.job_id),
            "item_id": str(self.item_id),
            "status": self.status.value,
            "stages_completed": self.stages_completed,
            "stages_failed": self.stages_failed,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


class QueueManager:
    """
    Manages Redis queues for the pipeline.

    Provides operations for:
    - Enqueueing items
    - Monitoring queue status
    - Managing dead letter queue
    - Reprocessing failed items
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        prefix: str = "lantern:pipeline:",
    ):
        self.redis = redis_client
        self.prefix = prefix

    # Queue name helpers
    def _queue_name(self, stage: str) -> str:
        return f"{self.prefix}{stage}"

    def _processing_queue_name(self, stage: str) -> str:
        return f"{self.prefix}{stage}:processing"

    def _dlq_name(self, stage: str) -> str:
        return f"{self.prefix}{stage}:dlq"

    async def enqueue(
        self,
        stage: str,
        context: PipelineContext,
        priority: Optional[int] = None,
    ) -> None:
        """
        Add item to a stage's queue.

        Args:
            stage: Stage name
            context: Pipeline context
            priority: Optional priority override
        """
        if priority is not None:
            context.priority = priority

        import time
        score = context.priority + (time.time() / 1e10)
        await self.redis.zadd(
            self._queue_name(stage),
            {context.to_queue_message(): score},
        )

    async def get_queue_lengths(self) -> dict[str, int]:
        """Get the length of all stage queues."""
        lengths = {}
        for stage in PIPELINE_STAGES:
            queue_len = await self.redis.zcard(self._queue_name(stage))
            lengths[stage] = queue_len
        return lengths

    async def get_dlq_lengths(self) -> dict[str, int]:
        """Get the length of all dead letter queues."""
        lengths = {}
        for stage in PIPELINE_STAGES:
            dlq_len = await self.redis.llen(self._dlq_name(stage))
            lengths[stage] = dlq_len
        return lengths

    async def get_processing_counts(self) -> dict[str, int]:
        """Get the count of items currently being processed per stage."""
        counts = {}
        for stage in PIPELINE_STAGES:
            count = await self.redis.hlen(self._processing_queue_name(stage))
            counts[stage] = count
        return counts

    async def get_dlq_items(
        self,
        stage: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get items from a dead letter queue.

        Args:
            stage: Stage name
            limit: Maximum items to return

        Returns:
            List of DLQ entries
        """
        items = await self.redis.lrange(self._dlq_name(stage), 0, limit - 1)
        return [json.loads(item) for item in items]

    async def requeue_dlq_item(
        self,
        stage: str,
        index: int = 0,
    ) -> bool:
        """
        Move an item from DLQ back to the main queue.

        Args:
            stage: Stage name
            index: Index of item in DLQ

        Returns:
            True if successful
        """
        # Get item from DLQ
        items = await self.redis.lrange(self._dlq_name(stage), index, index)
        if not items:
            return False

        dlq_entry = json.loads(items[0])
        context_data = dlq_entry.get("context")

        if not context_data:
            return False

        # Reset retry count and re-enqueue
        context = PipelineContext.model_validate(context_data)
        context.retry_count = 0

        await self.enqueue(stage, context)

        # Remove from DLQ
        await self.redis.lrem(self._dlq_name(stage), 1, items[0])

        return True

    async def requeue_all_dlq(self, stage: str) -> int:
        """
        Move all items from DLQ back to main queue.

        Args:
            stage: Stage name

        Returns:
            Number of items requeued
        """
        count = 0
        while True:
            items = await self.redis.lpop(self._dlq_name(stage))
            if not items:
                break

            try:
                dlq_entry = json.loads(items)
                context_data = dlq_entry.get("context")
                if context_data:
                    context = PipelineContext.model_validate(context_data)
                    context.retry_count = 0
                    await self.enqueue(stage, context)
                    count += 1
            except Exception as e:
                logger.error(f"Failed to requeue DLQ item: {e}")

        return count

    async def clear_dlq(self, stage: str) -> int:
        """
        Clear all items from a dead letter queue.

        Args:
            stage: Stage name

        Returns:
            Number of items cleared
        """
        count = await self.redis.llen(self._dlq_name(stage))
        await self.redis.delete(self._dlq_name(stage))
        return count

    async def get_metrics(self, stage: str) -> dict[str, Any]:
        """
        Get processing metrics for a stage.

        Args:
            stage: Stage name

        Returns:
            Metrics dictionary
        """
        metrics_key = f"lantern:metrics:{stage}"
        metrics = await self.redis.hgetall(metrics_key)

        return {
            k.decode(): v.decode() if isinstance(v, bytes) else v
            for k, v in metrics.items()
        }


class PipelineOrchestrator:
    """
    Orchestrates the processing pipeline.

    Manages:
    - Stage instantiation and configuration
    - Job submission and tracking
    - Worker coordination
    - Error handling and monitoring
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            redis_url: Redis connection URL
            config: Stage configuration overrides
        """
        self.redis_url = redis_url or settings.redis_url
        self.config = config or {}
        self.redis: Optional[redis.Redis] = None
        self.queue_manager: Optional[QueueManager] = None
        self._workers: dict[str, asyncio.Task] = {}
        self._running = False

    async def connect(self) -> None:
        """Establish Redis connection."""
        self.redis = redis.from_url(self.redis_url)
        self.queue_manager = QueueManager(self.redis)
        logger.info("Pipeline orchestrator connected to Redis")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            self.redis = None
        logger.info("Pipeline orchestrator disconnected")

    async def submit_job(
        self,
        item_id: UUID,
        raw_content: str,
        source_id: Optional[UUID] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
        content_type: str = "article",
        priority: int = 5,
        metadata: Optional[dict[str, Any]] = None,
    ) -> UUID:
        """
        Submit a new processing job.

        Args:
            item_id: ID of the item to process
            raw_content: Raw content to process
            source_id: Optional source ID
            url: Optional source URL
            title: Optional title
            content_type: Type of content
            priority: Processing priority (1=highest)
            metadata: Optional additional metadata

        Returns:
            Job ID
        """
        if not self.redis or not self.queue_manager:
            raise RuntimeError("Orchestrator not connected")

        job = ProcessingJob(
            job_id=uuid4(),
            item_id=item_id,
            source_id=source_id,
            raw_content=raw_content,
            url=url,
            title=title,
            content_type=content_type,
            priority=priority,
            metadata=metadata or {},
        )

        context = job.to_context()

        # Track job
        await self._track_job(job)

        # Enqueue to first stage
        await self.queue_manager.enqueue("normalize", context, priority)

        logger.info(f"Submitted job {job.job_id} for item {item_id}")

        return job.job_id

    async def _track_job(self, job: ProcessingJob) -> None:
        """
        Track a job in Redis.

        Args:
            job: Processing job
        """
        key = f"lantern:jobs:{job.job_id}"
        await self.redis.hset(
            key,
            mapping={
                "item_id": str(job.item_id),
                "status": ProcessingStatus.PENDING.value,
                "submitted_at": job.created_at.isoformat(),
                "current_stage": "normalize",
                "stages_completed": json.dumps([]),
                "errors": json.dumps([]),
            },
        )
        # Expire after 7 days
        await self.redis.expire(key, 86400 * 7)

    async def get_job_status(self, job_id: UUID) -> Optional[dict[str, Any]]:
        """
        Get the status of a job.

        Args:
            job_id: Job ID

        Returns:
            Job status dictionary or None if not found
        """
        key = f"lantern:jobs:{job_id}"
        data = await self.redis.hgetall(key)

        if not data:
            return None

        return {
            k.decode(): v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()
        }

    async def update_job_status(
        self,
        job_id: UUID,
        status: ProcessingStatus,
        current_stage: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update job status.

        Args:
            job_id: Job ID
            status: New status
            current_stage: Current processing stage
            error: Error message if failed
        """
        key = f"lantern:jobs:{job_id}"

        updates = {"status": status.value}
        if current_stage:
            updates["current_stage"] = current_stage
        if error:
            # Append to errors list
            errors_raw = await self.redis.hget(key, "errors")
            errors = json.loads(errors_raw) if errors_raw else []
            errors.append({
                "stage": current_stage,
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            updates["errors"] = json.dumps(errors)

        await self.redis.hset(key, mapping=updates)

    async def process_item(
        self,
        item_id: UUID,
        raw_content: str,
        source_id: Optional[UUID] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
        content_type: str = "article",
        start_stage: str = "normalize",
        end_stage: Optional[str] = None,
    ) -> ProcessingResult:
        """
        Process an item through the pipeline synchronously.

        This method processes the item through all stages in sequence,
        useful for testing or synchronous processing needs.

        Args:
            item_id: Item ID
            raw_content: Raw content
            source_id: Optional source ID
            url: Optional source URL
            title: Optional title
            content_type: Content type
            start_stage: Stage to start from
            end_stage: Stage to end at (None = all stages)

        Returns:
            Processing result
        """
        import time
        start_time = time.time()

        job_id = uuid4()
        context = PipelineContext(
            run_id=job_id,
            item_id=item_id,
            source_id=source_id,
            raw_content=raw_content,
            url=url,
            title=title,
            content_type=content_type,
        )

        stages_completed: list[str] = []
        stages_failed: list[str] = []
        errors: list[dict[str, Any]] = []

        # Determine stages to run
        start_idx = PIPELINE_STAGES.index(start_stage)
        if end_stage:
            end_idx = PIPELINE_STAGES.index(end_stage) + 1
        else:
            end_idx = len(PIPELINE_STAGES)

        stages_to_run = PIPELINE_STAGES[start_idx:end_idx]

        async with get_session_context() as db_session:
            for stage_name in stages_to_run:
                try:
                    stage_class = STAGE_CLASSES[stage_name]
                    stage_config = self.config.get(stage_name, {})

                    stage = stage_class(
                        redis_client=self.redis,
                        db_session=db_session,
                        config=stage_config,
                    )

                    context = await stage.run_once(context)

                    if context is None:
                        # Stage failed
                        stages_failed.append(stage_name)
                        errors.append({
                            "stage": stage_name,
                            "error": "Stage returned None",
                        })
                        break

                    stages_completed.append(stage_name)

                    # Check for duplicates - stop processing if exact duplicate
                    if stage_name == "dedup" and context.is_duplicate:
                        if context.canonical_item_id:
                            # Skip remaining stages for exact duplicates
                            logger.info(
                                f"Item {item_id} is duplicate of {context.canonical_item_id}, "
                                "stopping processing"
                            )
                            break

                except Exception as e:
                    stages_failed.append(stage_name)
                    errors.append({
                        "stage": stage_name,
                        "error": str(e),
                    })
                    logger.exception(f"Stage {stage_name} failed for item {item_id}")
                    break

        duration_ms = (time.time() - start_time) * 1000

        # Determine final status
        if stages_failed:
            status = ProcessingStatus.FAILED
        elif len(stages_completed) < len(stages_to_run):
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.COMPLETED

        return ProcessingResult(
            job_id=job_id,
            item_id=item_id,
            status=status,
            stages_completed=stages_completed,
            stages_failed=stages_failed,
            errors=errors,
            duration_ms=duration_ms,
            context=context,
        )

    async def start_workers(
        self,
        stages: Optional[list[str]] = None,
        workers_per_stage: int = 1,
    ) -> None:
        """
        Start worker tasks for pipeline stages.

        Args:
            stages: Stages to start workers for (None = all)
            workers_per_stage: Number of workers per stage
        """
        if not self.redis:
            raise RuntimeError("Orchestrator not connected")

        self._running = True
        stages = stages or PIPELINE_STAGES

        async with get_session_context() as db_session:
            for stage_name in stages:
                for worker_idx in range(workers_per_stage):
                    worker_id = f"{stage_name}:{worker_idx}"

                    stage_class = STAGE_CLASSES[stage_name]
                    stage_config = self.config.get(stage_name, {})

                    stage = stage_class(
                        redis_client=self.redis,
                        db_session=db_session,
                        config=stage_config,
                    )

                    task = asyncio.create_task(
                        self._run_worker(stage, worker_id),
                        name=f"worker:{worker_id}",
                    )
                    self._workers[worker_id] = task

        logger.info(f"Started {len(self._workers)} workers")

    async def _run_worker(self, stage: PipelineStage, worker_id: str) -> None:
        """
        Run a worker for a specific stage.

        Args:
            stage: Stage instance
            worker_id: Worker identifier
        """
        logger.info(f"Worker {worker_id} starting")

        while self._running:
            try:
                context = await stage.dequeue(timeout=5)

                if context is None:
                    continue

                # Update job status
                await self.update_job_status(
                    context.run_id,
                    ProcessingStatus.PROCESSING,
                    stage.stage_name,
                )

                result = await stage.run_once(context)

                if result is not None:
                    # Update stages completed
                    job_key = f"lantern:jobs:{context.run_id}"
                    stages_raw = await self.redis.hget(job_key, "stages_completed")
                    stages = json.loads(stages_raw) if stages_raw else []
                    stages.append(stage.stage_name)
                    await self.redis.hset(job_key, "stages_completed", json.dumps(stages))

                    # Forward to next stage
                    await stage.forward(result)

                    # Check if final stage
                    if stage.next_stage is None:
                        await self.update_job_status(
                            context.run_id,
                            ProcessingStatus.COMPLETED,
                        )

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.exception(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(1)

        logger.info(f"Worker {worker_id} stopped")

    async def stop_workers(self) -> None:
        """Stop all worker tasks."""
        self._running = False

        for worker_id, task in self._workers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._workers.clear()
        logger.info("All workers stopped")

    async def get_pipeline_status(self) -> dict[str, Any]:
        """
        Get overall pipeline status.

        Returns:
            Status dictionary with queue lengths, metrics, etc.
        """
        if not self.queue_manager:
            return {"error": "Not connected"}

        queue_lengths = await self.queue_manager.get_queue_lengths()
        dlq_lengths = await self.queue_manager.get_dlq_lengths()
        processing_counts = await self.queue_manager.get_processing_counts()

        metrics = {}
        for stage in PIPELINE_STAGES:
            metrics[stage] = await self.queue_manager.get_metrics(stage)

        return {
            "queues": queue_lengths,
            "dlq": dlq_lengths,
            "processing": processing_counts,
            "metrics": metrics,
            "workers": list(self._workers.keys()),
            "running": self._running,
        }


# Singleton orchestrator instance
_orchestrator: Optional[PipelineOrchestrator] = None


async def get_orchestrator() -> PipelineOrchestrator:
    """
    Get or create the pipeline orchestrator singleton.

    Returns:
        Pipeline orchestrator instance
    """
    global _orchestrator

    if _orchestrator is None:
        _orchestrator = PipelineOrchestrator()
        await _orchestrator.connect()

    return _orchestrator


async def shutdown_orchestrator() -> None:
    """Shutdown the pipeline orchestrator."""
    global _orchestrator

    if _orchestrator:
        await _orchestrator.stop_workers()
        await _orchestrator.disconnect()
        _orchestrator = None
