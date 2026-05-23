"""
Base Pipeline Stage

Provides the abstract base class for all pipeline stages with:
- Queue-driven architecture (Redis-based)
- Retry logic on failure
- Metrics and logging
- Context management
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar, Optional
import asyncio
import hashlib
import json
import logging
import time
import traceback
from uuid import UUID, uuid4

import redis.asyncio as redis
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for pipeline errors."""

    def __init__(self, message: str, stage: str, item_id: Optional[UUID] = None):
        self.message = message
        self.stage = stage
        self.item_id = item_id
        super().__init__(f"[{stage}] {message}")


class RetryableError(PipelineError):
    """Error that can be retried (transient failures)."""

    def __init__(
        self,
        message: str,
        stage: str,
        item_id: Optional[UUID] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message, stage, item_id)
        self.retry_after = retry_after  # Seconds to wait before retry


class NonRetryableError(PipelineError):
    """Error that should not be retried (permanent failures)."""

    pass


class StageStatus(str, Enum):
    """Status of a pipeline stage execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QueuePriority(int, Enum):
    """Priority levels for queue items."""

    HIGH = 1
    NORMAL = 5
    LOW = 10


@dataclass
class StageMetrics:
    """Metrics collected during stage execution."""

    stage_name: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    items_processed: int = 0
    items_failed: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def complete(self, success: bool = True) -> None:
        """Mark the stage as complete and calculate duration."""
        self.end_time = datetime.now(timezone.utc)
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000
        if success:
            self.items_processed += 1
        else:
            self.items_failed += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for logging/storage."""
        return {
            "stage_name": self.stage_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "items_processed": self.items_processed,
            "items_failed": self.items_failed,
            "retries": self.retries,
            "errors": self.errors,
            "metadata": self.metadata,
        }


class PipelineContext(BaseModel):
    """
    Context passed through pipeline stages.

    Contains the item being processed, accumulated data from previous stages,
    and metadata about the processing run.
    """

    # Core identifiers
    run_id: UUID = Field(default_factory=uuid4)
    item_id: UUID
    source_id: Optional[UUID] = None

    # Content data (populated by normalize stage)
    raw_content: Optional[str] = None
    clean_text: Optional[str] = None
    content_type: str = "article"  # article, transcript, filing
    language: Optional[str] = None

    # Metadata
    url: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None

    # Deduplication data
    dedup_hash: Optional[str] = None
    is_duplicate: bool = False
    canonical_item_id: Optional[UUID] = None  # If duplicate, points to original

    # Embedding data
    embedding: Optional[list[float]] = None
    embedding_model: Optional[str] = None

    # Extracted entities and claims
    entities: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)

    # Classification data
    sentiment_scores: dict[str, float] = Field(default_factory=dict)
    salience_scores: dict[str, float] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)

    # Event and narrative data
    event_id: Optional[UUID] = None
    narrative_ids: list[UUID] = Field(default_factory=list)

    # Processing metadata
    stage_history: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Priority and retry info
    priority: int = QueuePriority.NORMAL
    retry_count: int = 0
    max_retries: int = 3

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True

    def add_stage(self, stage_name: str) -> None:
        """Record that a stage was processed."""
        self.stage_history.append(stage_name)
        self.updated_at = datetime.now(timezone.utc)

    def add_error(self, stage: str, error: str, traceback_str: Optional[str] = None) -> None:
        """Record an error that occurred during processing."""
        self.errors.append({
            "stage": stage,
            "error": error,
            "traceback": traceback_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def to_queue_message(self) -> str:
        """Serialize context for queue storage."""
        return self.model_dump_json()

    @classmethod
    def from_queue_message(cls, message: str) -> "PipelineContext":
        """Deserialize context from queue storage."""
        return cls.model_validate_json(message)


# Type variable for stage input/output
T = TypeVar("T")


class PipelineStage(ABC, Generic[T]):
    """
    Abstract base class for pipeline stages.

    Each stage processes items from a Redis queue, performs its work,
    and pushes results to the next stage's queue.
    """

    # Stage configuration
    stage_name: str = "base"
    next_stage: Optional[str] = None
    max_retries: int = 3
    retry_delay_base: int = 1  # Base delay in seconds (exponential backoff)
    batch_size: int = 1
    processing_timeout: int = 300  # Seconds

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize the pipeline stage.

        Args:
            redis_client: Redis client for queue operations
            db_session: Async database session
            config: Optional stage-specific configuration
        """
        self.redis = redis_client
        self.db = db_session
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.stage_name}")

    @property
    def queue_name(self) -> str:
        """Get the input queue name for this stage."""
        return f"lantern:pipeline:{self.stage_name}"

    @property
    def processing_queue_name(self) -> str:
        """Get the processing queue name (for in-flight items)."""
        return f"lantern:pipeline:{self.stage_name}:processing"

    @property
    def dead_letter_queue_name(self) -> str:
        """Get the dead letter queue name."""
        return f"lantern:pipeline:{self.stage_name}:dlq"

    @property
    def next_queue_name(self) -> Optional[str]:
        """Get the output queue name (next stage's input)."""
        if self.next_stage:
            return f"lantern:pipeline:{self.next_stage}"
        return None

    @abstractmethod
    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Process a single item through this stage.

        Args:
            context: Pipeline context containing item data

        Returns:
            Updated pipeline context

        Raises:
            RetryableError: For transient failures that should be retried
            NonRetryableError: For permanent failures
        """
        pass

    async def pre_process(self, context: PipelineContext) -> PipelineContext:
        """
        Hook called before processing. Override for setup logic.

        Args:
            context: Pipeline context

        Returns:
            Potentially modified context
        """
        return context

    async def post_process(self, context: PipelineContext) -> PipelineContext:
        """
        Hook called after successful processing. Override for cleanup logic.

        Args:
            context: Pipeline context

        Returns:
            Potentially modified context
        """
        context.add_stage(self.stage_name)
        return context

    async def on_error(
        self, context: PipelineContext, error: Exception
    ) -> None:
        """
        Hook called when an error occurs.

        Args:
            context: Pipeline context
            error: The exception that occurred
        """
        tb_str = traceback.format_exc()
        context.add_error(self.stage_name, str(error), tb_str)
        self.logger.error(
            f"Error processing item {context.item_id}: {error}",
            extra={
                "item_id": str(context.item_id),
                "stage": self.stage_name,
                "error": str(error),
                "traceback": tb_str,
            },
        )

    async def enqueue(
        self,
        context: PipelineContext,
        priority: Optional[int] = None,
    ) -> None:
        """
        Add an item to this stage's input queue.

        Args:
            context: Pipeline context to enqueue
            priority: Optional priority override
        """
        if priority is not None:
            context.priority = priority

        score = context.priority + (time.time() / 1e10)  # Priority + FIFO tiebreaker
        await self.redis.zadd(
            self.queue_name,
            {context.to_queue_message(): score},
        )
        self.logger.debug(f"Enqueued item {context.item_id} to {self.queue_name}")

    async def dequeue(self, timeout: int = 0) -> Optional[PipelineContext]:
        """
        Get the next item from this stage's input queue.

        Uses ZPOPMIN for priority queue semantics with BRPOPLPUSH
        for reliable queue processing.

        Args:
            timeout: Blocking timeout in seconds (0 = non-blocking)

        Returns:
            Pipeline context or None if queue is empty
        """
        # Pop lowest score item (highest priority)
        result = await self.redis.zpopmin(self.queue_name, count=1)

        if not result:
            if timeout > 0:
                # Blocking wait for new items
                await asyncio.sleep(min(timeout, 1))
                return await self.dequeue(timeout - 1)
            return None

        message, _score = result[0]

        # Move to processing queue for reliability
        await self.redis.hset(
            self.processing_queue_name,
            str(uuid4()),
            message,
        )

        return PipelineContext.from_queue_message(message)

    async def forward(self, context: PipelineContext) -> None:
        """
        Forward processed item to the next stage.

        Args:
            context: Pipeline context to forward
        """
        if not self.next_queue_name:
            self.logger.debug(f"No next stage for {self.stage_name}, item {context.item_id} complete")
            return

        score = context.priority + (time.time() / 1e10)
        await self.redis.zadd(
            self.next_queue_name,
            {context.to_queue_message(): score},
        )
        self.logger.debug(f"Forwarded item {context.item_id} to {self.next_queue_name}")

    async def send_to_dlq(self, context: PipelineContext, error: Exception) -> None:
        """
        Send a failed item to the dead letter queue.

        Args:
            context: Pipeline context that failed
            error: The error that caused the failure
        """
        dlq_entry = {
            "context": context.model_dump(),
            "error": str(error),
            "error_type": type(error).__name__,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": self.stage_name,
        }
        await self.redis.lpush(
            self.dead_letter_queue_name,
            json.dumps(dlq_entry, default=str),
        )
        self.logger.warning(
            f"Sent item {context.item_id} to DLQ: {error}",
            extra={"item_id": str(context.item_id), "stage": self.stage_name},
        )

    async def run_once(self, context: PipelineContext) -> Optional[PipelineContext]:
        """
        Run a single item through this stage with retry logic.

        Args:
            context: Pipeline context to process

        Returns:
            Processed context or None if failed
        """
        metrics = StageMetrics(stage_name=self.stage_name)

        try:
            # Pre-process hook
            context = await self.pre_process(context)

            # Main processing
            context = await self.process(context)

            # Post-process hook
            context = await self.post_process(context)

            metrics.complete(success=True)
            await self._record_metrics(metrics)

            return context

        except RetryableError as e:
            metrics.retries += 1
            context.retry_count += 1

            if context.retry_count >= self.max_retries:
                self.logger.error(
                    f"Max retries exceeded for item {context.item_id}"
                )
                metrics.complete(success=False)
                metrics.errors.append(str(e))
                await self.on_error(context, e)
                await self.send_to_dlq(context, e)
                await self._record_metrics(metrics)
                return None

            # Calculate exponential backoff delay
            delay = self.retry_delay_base * (2 ** (context.retry_count - 1))
            if e.retry_after:
                delay = max(delay, e.retry_after)

            self.logger.warning(
                f"Retryable error for item {context.item_id}, "
                f"retry {context.retry_count}/{self.max_retries} in {delay}s: {e}"
            )

            await asyncio.sleep(delay)
            return await self.run_once(context)

        except NonRetryableError as e:
            metrics.complete(success=False)
            metrics.errors.append(str(e))
            await self.on_error(context, e)
            await self.send_to_dlq(context, e)
            await self._record_metrics(metrics)
            return None

        except Exception as e:
            # Unexpected error - treat as retryable
            self.logger.exception(f"Unexpected error processing item {context.item_id}")
            metrics.complete(success=False)
            metrics.errors.append(str(e))
            await self.on_error(context, e)

            context.retry_count += 1
            if context.retry_count >= self.max_retries:
                await self.send_to_dlq(context, e)
                await self._record_metrics(metrics)
                return None

            delay = self.retry_delay_base * (2 ** (context.retry_count - 1))
            await asyncio.sleep(delay)
            return await self.run_once(context)

    async def run(self, poll_interval: float = 1.0) -> None:
        """
        Run the stage continuously, processing items from the queue.

        Args:
            poll_interval: Seconds to wait between queue polls when empty
        """
        self.logger.info(f"Starting {self.stage_name} stage worker")

        while True:
            try:
                context = await self.dequeue(timeout=int(poll_interval))

                if context is None:
                    continue

                result = await self.run_once(context)

                if result is not None:
                    await self.forward(result)

            except asyncio.CancelledError:
                self.logger.info(f"Shutting down {self.stage_name} stage worker")
                break

            except Exception as e:
                self.logger.exception(f"Error in {self.stage_name} run loop: {e}")
                await asyncio.sleep(poll_interval)

    async def _record_metrics(self, metrics: StageMetrics) -> None:
        """
        Record stage metrics to Redis for monitoring.

        Args:
            metrics: Metrics to record
        """
        metrics_key = f"lantern:metrics:{self.stage_name}"

        # Store latest metrics
        await self.redis.hset(
            metrics_key,
            mapping={
                "last_run": metrics.to_dict().__str__(),
                "last_duration_ms": str(metrics.duration_ms or 0),
                "last_status": "success" if metrics.items_failed == 0 else "failed",
            },
        )

        # Increment counters
        await self.redis.hincrby(metrics_key, "total_processed", metrics.items_processed)
        await self.redis.hincrby(metrics_key, "total_failed", metrics.items_failed)
        await self.redis.hincrby(metrics_key, "total_retries", metrics.retries)

    @classmethod
    def compute_content_hash(cls, content: str) -> str:
        """
        Compute a hash of content for deduplication.

        Args:
            content: Text content to hash

        Returns:
            SHA-256 hash of the content
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
