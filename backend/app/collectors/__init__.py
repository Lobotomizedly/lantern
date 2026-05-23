"""
Lantern Narrative Intelligence Platform - Data Collectors

This module provides data collection capabilities from various sources:

- News articles (NewsAPI, GDELT, RSS)
- Social media (Twitter/X)
- SEC filings (EDGAR)
- Podcasts (with transcription support)
- Web pages (JavaScript rendering with Playwright)

Usage:
    from lantern.collectors import (
        NewsCollector,
        TwitterCollector,
        FilingCollector,
        CollectionScheduler,
    )

    # Create individual collectors
    news = NewsCollector(newsapi_key="...")
    twitter = TwitterCollector(credentials=TwitterCredentials(...))

    # Or use the scheduler for orchestrated collection
    scheduler = CollectionScheduler(
        news_collector=news,
        twitter_collector=twitter,
    )

    # Register subjects
    scheduler.register_subject(SubjectConfig(
        id="apple",
        name="Apple Inc.",
        aliases=["AAPL", "Apple"],
        enabled_collectors=[CollectorType.NEWS, CollectorType.TWITTER],
    ))

    # Run collection
    manifest = await scheduler.collect_for_subject("apple")
"""

# Base classes and utilities
from .base import (
    BaseCollector,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    CollectedItem,
    CollectorMetrics,
    RateLimiter,
    RateLimitConfig,
    RetryConfig,
    with_rate_limit,
    with_retry,
)

# News collection
from .news import (
    NewsCollector,
    NewsArticle,
    NewsSource,
    NewsAPIClient,
    GDELTClient,
    TextExtractor,
)

# RSS collection
from .rss import (
    RSSCollector,
    FeedEntry,
    FeedMetadata,
    FeedFormat,
    FeedParser,
)

# Social media collection
from .social import (
    SocialCollector,
    SocialMediaPost,
    SocialMediaAuthor,
    SocialPlatform,
    PostType,
    PlatformRateLimits,
)

# Twitter/X collection
from .twitter import (
    TwitterCollector,
    TwitterCredentials,
    TwitterAPIError,
    TwitterRateLimitError,
)

# SEC filing collection
from .filing import (
    FilingCollector,
    FilingMetadata,
    FilingDocument,
    FilingType,
    FilingParser,
    EDGARClient,
)

# Podcast collection
from .podcast import (
    PodcastCollector,
    PodcastEpisode,
    PodcastMetadata,
    TranscriptionJob,
    TranscriptionQueue,
    TranscriptionStatus,
    AudioFormat,
)

# Web collection
from .web import (
    WebCollector,
    WebPage,
    ContentExtractor,
    RobotsChecker,
)

# Scheduler and orchestration
from .scheduler import (
    CollectionScheduler,
    CollectionManifest,
    CollectionStatus,
    CollectorResult,
    CollectorType,
    SubjectConfig,
    CeleryCollectionTasks,
    TemporalCollectionWorkflows,
    create_scheduler_with_defaults,
)

__all__ = [
    # Base
    "BaseCollector",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitState",
    "CollectedItem",
    "CollectorMetrics",
    "RateLimiter",
    "RateLimitConfig",
    "RetryConfig",
    "with_rate_limit",
    "with_retry",
    # News
    "NewsCollector",
    "NewsArticle",
    "NewsSource",
    "NewsAPIClient",
    "GDELTClient",
    "TextExtractor",
    # RSS
    "RSSCollector",
    "FeedEntry",
    "FeedMetadata",
    "FeedFormat",
    "FeedParser",
    # Social
    "SocialCollector",
    "SocialMediaPost",
    "SocialMediaAuthor",
    "SocialPlatform",
    "PostType",
    "PlatformRateLimits",
    # Twitter
    "TwitterCollector",
    "TwitterCredentials",
    "TwitterAPIError",
    "TwitterRateLimitError",
    # Filing
    "FilingCollector",
    "FilingMetadata",
    "FilingDocument",
    "FilingType",
    "FilingParser",
    "EDGARClient",
    # Podcast
    "PodcastCollector",
    "PodcastEpisode",
    "PodcastMetadata",
    "TranscriptionJob",
    "TranscriptionQueue",
    "TranscriptionStatus",
    "AudioFormat",
    # Web
    "WebCollector",
    "WebPage",
    "ContentExtractor",
    "RobotsChecker",
    # Scheduler
    "CollectionScheduler",
    "CollectionManifest",
    "CollectionStatus",
    "CollectorResult",
    "CollectorType",
    "SubjectConfig",
    "CeleryCollectionTasks",
    "TemporalCollectionWorkflows",
    "create_scheduler_with_defaults",
]

__version__ = "1.0.0"
