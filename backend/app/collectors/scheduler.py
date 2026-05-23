"""
Collection scheduler for the Lantern Narrative Intelligence Platform.

Orchestrates data collection across multiple collectors with:
- Daily collection sweeps per subject
- Fan-out to enabled collectors
- Collection manifest generation
- Integration with Celery/Temporal for job scheduling
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type

import structlog

from .base import BaseCollector, CollectorMetrics
from .news import NewsCollector
from .rss import RSSCollector
from .social import SocialCollector
from .twitter import TwitterCollector
from .filing import FilingCollector
from .podcast import PodcastCollector
from .web import WebCollector


class CollectionStatus(Enum):
    """Collection job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some collectors failed
    FAILED = "failed"
    CANCELLED = "cancelled"


class CollectorType(Enum):
    """Available collector types."""
    NEWS = "news"
    RSS = "rss"
    TWITTER = "twitter"
    FILING = "filing"
    PODCAST = "podcast"
    WEB = "web"


@dataclass
class SubjectConfig:
    """Configuration for a subject to collect data about."""
    id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    enabled_collectors: List[CollectorType] = field(default_factory=list)

    # Collector-specific configuration
    twitter_usernames: List[str] = field(default_factory=list)
    twitter_search_terms: List[str] = field(default_factory=list)
    rss_feeds: List[str] = field(default_factory=list)
    podcast_feeds: List[str] = field(default_factory=list)
    web_urls: List[str] = field(default_factory=list)
    sec_ciks: List[str] = field(default_factory=list)

    # Collection settings
    collection_frequency_hours: int = 24
    lookback_hours: int = 48

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "enabled_collectors": [c.value for c in self.enabled_collectors],
            "twitter_usernames": self.twitter_usernames,
            "twitter_search_terms": self.twitter_search_terms,
            "rss_feeds": self.rss_feeds,
            "podcast_feeds": self.podcast_feeds,
            "web_urls": self.web_urls,
            "sec_ciks": self.sec_ciks,
            "collection_frequency_hours": self.collection_frequency_hours,
            "lookback_hours": self.lookback_hours,
        }


@dataclass
class CollectorResult:
    """Result from a single collector run."""
    collector_type: CollectorType
    status: CollectionStatus
    items_collected: int
    items_new: int
    errors: int
    error_messages: List[str] = field(default_factory=list)
    metrics: Optional[CollectorMetrics] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    item_ids: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "collector_type": self.collector_type.value,
            "status": self.status.value,
            "items_collected": self.items_collected,
            "items_new": self.items_new,
            "errors": self.errors,
            "error_messages": self.error_messages,
            "duration_seconds": self.duration_seconds,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "item_ids": self.item_ids,
        }


@dataclass
class CollectionManifest:
    """Manifest for a complete collection run."""
    job_id: str
    subject_id: str
    subject_name: str
    status: CollectionStatus
    collector_results: Dict[CollectorType, CollectorResult] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_items_collected: int = 0
    total_items_new: int = 0
    total_errors: int = 0
    all_new_item_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get total duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "status": self.status.value,
            "collector_results": {
                ct.value: cr.to_dict()
                for ct, cr in self.collector_results.items()
            },
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_items_collected": self.total_items_collected,
            "total_items_new": self.total_items_new,
            "total_errors": self.total_errors,
            "all_new_item_ids": self.all_new_item_ids,
            "metadata": self.metadata,
        }


class CollectionScheduler:
    """
    Orchestrates data collection across multiple collectors.

    Features:
    - Subject-based collection configuration
    - Concurrent collector execution
    - Collection manifest generation
    - Integration hooks for Celery/Temporal
    """

    def __init__(
        self,
        # Collector instances (optional - will create defaults if not provided)
        news_collector: Optional[NewsCollector] = None,
        rss_collector: Optional[RSSCollector] = None,
        twitter_collector: Optional[TwitterCollector] = None,
        filing_collector: Optional[FilingCollector] = None,
        podcast_collector: Optional[PodcastCollector] = None,
        web_collector: Optional[WebCollector] = None,
        # Callbacks
        on_collection_complete: Optional[Callable[[CollectionManifest], None]] = None,
        on_item_collected: Optional[Callable[[CollectorType, Any], None]] = None,
        # Settings
        max_concurrent_collectors: int = 4,
        default_lookback_hours: int = 48,
    ):
        """
        Initialize collection scheduler.

        Args:
            news_collector: NewsCollector instance
            rss_collector: RSSCollector instance
            twitter_collector: TwitterCollector instance
            filing_collector: FilingCollector instance
            podcast_collector: PodcastCollector instance
            web_collector: WebCollector instance
            on_collection_complete: Callback when collection completes
            on_item_collected: Callback for each collected item
            max_concurrent_collectors: Max concurrent collector executions
            default_lookback_hours: Default time range for collection
        """
        self.collectors: Dict[CollectorType, Optional[BaseCollector]] = {
            CollectorType.NEWS: news_collector,
            CollectorType.RSS: rss_collector,
            CollectorType.TWITTER: twitter_collector,
            CollectorType.FILING: filing_collector,
            CollectorType.PODCAST: podcast_collector,
            CollectorType.WEB: web_collector,
        }

        self.on_collection_complete = on_collection_complete
        self.on_item_collected = on_item_collected
        self.max_concurrent_collectors = max_concurrent_collectors
        self.default_lookback_hours = default_lookback_hours

        self._subjects: Dict[str, SubjectConfig] = {}
        self._running_jobs: Dict[str, CollectionManifest] = {}
        self._job_history: List[CollectionManifest] = []

        self.logger = structlog.get_logger(__name__)

    def register_subject(self, config: SubjectConfig) -> None:
        """
        Register a subject for collection.

        Args:
            config: Subject configuration
        """
        self._subjects[config.id] = config
        self.logger.info(
            "subject_registered",
            subject_id=config.id,
            subject_name=config.name,
            enabled_collectors=[c.value for c in config.enabled_collectors],
        )

    def unregister_subject(self, subject_id: str) -> None:
        """Remove a subject from collection."""
        if subject_id in self._subjects:
            del self._subjects[subject_id]
            self.logger.info("subject_unregistered", subject_id=subject_id)

    def get_subject(self, subject_id: str) -> Optional[SubjectConfig]:
        """Get subject configuration by ID."""
        return self._subjects.get(subject_id)

    def list_subjects(self) -> List[SubjectConfig]:
        """List all registered subjects."""
        return list(self._subjects.values())

    async def collect_for_subject(
        self,
        subject_id: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        collector_types: Optional[List[CollectorType]] = None,
    ) -> CollectionManifest:
        """
        Run collection for a single subject.

        Args:
            subject_id: Subject ID to collect for
            since: Override start time
            until: Override end time
            collector_types: Override enabled collectors

        Returns:
            CollectionManifest with results
        """
        subject = self._subjects.get(subject_id)
        if not subject:
            raise ValueError(f"Subject not found: {subject_id}")

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Determine time range
        if until is None:
            until = datetime.now(tz=timezone.utc)
        if since is None:
            since = until - timedelta(hours=subject.lookback_hours or self.default_lookback_hours)

        # Determine which collectors to run
        target_collectors = collector_types or subject.enabled_collectors

        # Initialize manifest
        manifest = CollectionManifest(
            job_id=job_id,
            subject_id=subject_id,
            subject_name=subject.name,
            status=CollectionStatus.RUNNING,
            start_time=datetime.now(tz=timezone.utc),
        )

        self._running_jobs[job_id] = manifest

        self.logger.info(
            "collection_started",
            job_id=job_id,
            subject_id=subject_id,
            collectors=[c.value for c in target_collectors],
            since=since.isoformat(),
            until=until.isoformat(),
        )

        # Run collectors with semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent_collectors)

        async def run_collector(collector_type: CollectorType) -> CollectorResult:
            async with semaphore:
                return await self._run_single_collector(
                    collector_type, subject, since, until
                )

        tasks = [run_collector(ct) for ct in target_collectors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        all_succeeded = True
        any_succeeded = False

        for collector_type, result in zip(target_collectors, results):
            if isinstance(result, Exception):
                manifest.collector_results[collector_type] = CollectorResult(
                    collector_type=collector_type,
                    status=CollectionStatus.FAILED,
                    items_collected=0,
                    items_new=0,
                    errors=1,
                    error_messages=[str(result)],
                )
                manifest.total_errors += 1
                all_succeeded = False
            else:
                manifest.collector_results[collector_type] = result
                manifest.total_items_collected += result.items_collected
                manifest.total_items_new += result.items_new
                manifest.total_errors += result.errors
                manifest.all_new_item_ids.extend(result.item_ids)

                if result.status == CollectionStatus.COMPLETED:
                    any_succeeded = True
                else:
                    all_succeeded = False

        # Determine final status
        if all_succeeded:
            manifest.status = CollectionStatus.COMPLETED
        elif any_succeeded:
            manifest.status = CollectionStatus.PARTIAL
        else:
            manifest.status = CollectionStatus.FAILED

        manifest.end_time = datetime.now(tz=timezone.utc)

        # Remove from running, add to history
        del self._running_jobs[job_id]
        self._job_history.append(manifest)

        # Callback
        if self.on_collection_complete:
            try:
                self.on_collection_complete(manifest)
            except Exception as e:
                self.logger.error("collection_callback_error", error=str(e))

        self.logger.info(
            "collection_completed",
            job_id=job_id,
            subject_id=subject_id,
            status=manifest.status.value,
            items_collected=manifest.total_items_collected,
            items_new=manifest.total_items_new,
            errors=manifest.total_errors,
            duration_seconds=manifest.duration_seconds,
        )

        return manifest

    async def _run_single_collector(
        self,
        collector_type: CollectorType,
        subject: SubjectConfig,
        since: datetime,
        until: datetime,
    ) -> CollectorResult:
        """Run a single collector for a subject."""
        collector = self.collectors.get(collector_type)
        if collector is None:
            return CollectorResult(
                collector_type=collector_type,
                status=CollectionStatus.FAILED,
                items_collected=0,
                items_new=0,
                errors=1,
                error_messages=[f"Collector not configured: {collector_type.value}"],
            )

        start_time = datetime.now(tz=timezone.utc)

        try:
            # Build collector-specific kwargs
            kwargs = self._build_collector_kwargs(collector_type, subject)

            # Run collection
            items = await collector.collect(
                subject_name=subject.name,
                aliases=subject.aliases,
                since=since,
                until=until,
                **kwargs,
            )

            # Generate item IDs
            item_ids = [
                getattr(item, "dedup_hash", str(uuid.uuid4()))
                for item in items
            ]

            # Callback for each item
            if self.on_item_collected:
                for item in items:
                    try:
                        self.on_item_collected(collector_type, item)
                    except Exception as e:
                        self.logger.error(
                            "item_callback_error",
                            collector=collector_type.value,
                            error=str(e),
                        )

            return CollectorResult(
                collector_type=collector_type,
                status=CollectionStatus.COMPLETED,
                items_collected=len(items),
                items_new=len(items),  # All items are new for now
                errors=collector.metrics.errors,
                metrics=collector.metrics,
                start_time=start_time,
                end_time=datetime.now(tz=timezone.utc),
                item_ids=item_ids,
            )

        except Exception as e:
            self.logger.error(
                "collector_error",
                collector=collector_type.value,
                subject=subject.name,
                error=str(e),
            )
            return CollectorResult(
                collector_type=collector_type,
                status=CollectionStatus.FAILED,
                items_collected=0,
                items_new=0,
                errors=1,
                error_messages=[str(e)],
                start_time=start_time,
                end_time=datetime.now(tz=timezone.utc),
            )

    def _build_collector_kwargs(
        self,
        collector_type: CollectorType,
        subject: SubjectConfig,
    ) -> Dict[str, Any]:
        """Build collector-specific keyword arguments."""
        kwargs: Dict[str, Any] = {}

        if collector_type == CollectorType.TWITTER:
            kwargs["usernames"] = subject.twitter_usernames
            kwargs["search_terms"] = subject.twitter_search_terms

        elif collector_type == CollectorType.RSS:
            kwargs["feed_urls"] = subject.rss_feeds

        elif collector_type == CollectorType.PODCAST:
            kwargs["feed_urls"] = subject.podcast_feeds

        elif collector_type == CollectorType.WEB:
            kwargs["urls"] = subject.web_urls

        elif collector_type == CollectorType.FILING:
            kwargs["ciks"] = subject.sec_ciks

        return kwargs

    async def run_daily_sweep(
        self,
        subject_ids: Optional[List[str]] = None,
    ) -> List[CollectionManifest]:
        """
        Run daily collection sweep for subjects.

        Args:
            subject_ids: Specific subjects to collect (None = all)

        Returns:
            List of collection manifests
        """
        targets = subject_ids or list(self._subjects.keys())

        self.logger.info(
            "daily_sweep_started",
            subject_count=len(targets),
        )

        manifests = []
        for subject_id in targets:
            try:
                manifest = await self.collect_for_subject(subject_id)
                manifests.append(manifest)
            except Exception as e:
                self.logger.error(
                    "sweep_subject_error",
                    subject_id=subject_id,
                    error=str(e),
                )

        self.logger.info(
            "daily_sweep_completed",
            subject_count=len(targets),
            total_items=sum(m.total_items_collected for m in manifests),
            total_errors=sum(m.total_errors for m in manifests),
        )

        return manifests

    def get_running_jobs(self) -> List[CollectionManifest]:
        """Get currently running collection jobs."""
        return list(self._running_jobs.values())

    def get_job_history(
        self,
        limit: int = 100,
        subject_id: Optional[str] = None,
    ) -> List[CollectionManifest]:
        """
        Get collection job history.

        Args:
            limit: Maximum number of jobs to return
            subject_id: Filter by subject

        Returns:
            List of collection manifests
        """
        history = self._job_history

        if subject_id:
            history = [m for m in history if m.subject_id == subject_id]

        return history[-limit:]


# --- Celery Integration ---

class CeleryCollectionTasks:
    """
    Celery task definitions for collection scheduling.

    Usage with Celery:

        from celery import Celery
        from .scheduler import CeleryCollectionTasks

        app = Celery('lantern')
        tasks = CeleryCollectionTasks(app)

        # Schedule daily sweep
        tasks.schedule_daily_sweep()
    """

    def __init__(self, celery_app=None):
        """
        Initialize Celery tasks.

        Args:
            celery_app: Celery application instance
        """
        self.celery_app = celery_app
        self.logger = structlog.get_logger(__name__)

        if celery_app:
            self._register_tasks()

    def _register_tasks(self):
        """Register Celery tasks."""
        app = self.celery_app

        @app.task(name="lantern.collect_for_subject")
        def collect_for_subject_task(
            subject_id: str,
            since: Optional[str] = None,
            until: Optional[str] = None,
            collector_types: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Celery task to collect for a single subject."""
            # This would be implemented with actual scheduler instance
            # For now, return placeholder
            return {
                "status": "task_registered",
                "subject_id": subject_id,
            }

        @app.task(name="lantern.run_daily_sweep")
        def run_daily_sweep_task(
            subject_ids: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """Celery task for daily collection sweep."""
            return {
                "status": "task_registered",
                "subject_ids": subject_ids,
            }

        self.collect_for_subject_task = collect_for_subject_task
        self.run_daily_sweep_task = run_daily_sweep_task

    def schedule_daily_sweep(self, hour: int = 2, minute: int = 0):
        """
        Schedule daily sweep task.

        Args:
            hour: Hour to run (0-23)
            minute: Minute to run (0-59)
        """
        if not self.celery_app:
            raise RuntimeError("Celery app not configured")

        self.celery_app.conf.beat_schedule["daily-collection-sweep"] = {
            "task": "lantern.run_daily_sweep",
            "schedule": {
                "hour": hour,
                "minute": minute,
            },
        }

        self.logger.info(
            "daily_sweep_scheduled",
            hour=hour,
            minute=minute,
        )


# --- Temporal Integration ---

class TemporalCollectionWorkflows:
    """
    Temporal workflow definitions for collection scheduling.

    Usage with Temporal:

        from temporalio import workflow, activity
        from .scheduler import TemporalCollectionWorkflows

        workflows = TemporalCollectionWorkflows()

        # Register workflows with Temporal worker
        worker = Worker(
            client,
            task_queue="collection-queue",
            workflows=[workflows.CollectionWorkflow],
            activities=[workflows.collect_activity],
        )
    """

    def __init__(self, scheduler: Optional[CollectionScheduler] = None):
        """
        Initialize Temporal workflows.

        Args:
            scheduler: CollectionScheduler instance
        """
        self.scheduler = scheduler
        self.logger = structlog.get_logger(__name__)

    # Note: These would be actual Temporal workflow/activity definitions
    # Shown as placeholders for the pattern

    async def collect_activity(
        self,
        subject_id: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Temporal activity for collecting data.

        Would be decorated with @activity.defn in actual implementation.
        """
        if not self.scheduler:
            raise RuntimeError("Scheduler not configured")

        since_dt = datetime.fromisoformat(since) if since else None
        until_dt = datetime.fromisoformat(until) if until else None

        manifest = await self.scheduler.collect_for_subject(
            subject_id,
            since=since_dt,
            until=until_dt,
        )

        return manifest.to_dict()

    async def daily_sweep_workflow(
        self,
        subject_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Temporal workflow for daily collection sweep.

        Would be decorated with @workflow.defn in actual implementation.
        """
        if not self.scheduler:
            raise RuntimeError("Scheduler not configured")

        manifests = await self.scheduler.run_daily_sweep(subject_ids)
        return [m.to_dict() for m in manifests]


def create_scheduler_with_defaults(
    newsapi_key: Optional[str] = None,
    twitter_bearer_token: Optional[str] = None,
) -> CollectionScheduler:
    """
    Create a scheduler with default collector instances.

    Args:
        newsapi_key: NewsAPI API key
        twitter_bearer_token: Twitter API bearer token

    Returns:
        Configured CollectionScheduler
    """
    from .twitter import TwitterCredentials

    news_collector = NewsCollector(newsapi_key=newsapi_key) if newsapi_key else None

    twitter_collector = None
    if twitter_bearer_token:
        twitter_collector = TwitterCollector(
            credentials=TwitterCredentials(bearer_token=twitter_bearer_token)
        )

    return CollectionScheduler(
        news_collector=news_collector,
        rss_collector=RSSCollector(),
        twitter_collector=twitter_collector,
        filing_collector=FilingCollector(),
        podcast_collector=PodcastCollector(),
        web_collector=None,  # Requires Playwright - enable manually
    )
