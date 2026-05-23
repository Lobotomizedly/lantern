"""
Social media collector base for the Lantern Narrative Intelligence Platform.

Provides abstract base class for platform-specific social media collectors
with common interface for rate limiting and authentication.
"""

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

import structlog

from .base import (
    BaseCollector,
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)


class SocialPlatform(Enum):
    """Supported social media platforms."""
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    REDDIT = "reddit"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    MASTODON = "mastodon"
    BLUESKY = "bluesky"
    THREADS = "threads"


class PostType(Enum):
    """Types of social media posts."""
    POST = "post"
    REPLY = "reply"
    REPOST = "repost"  # Retweet, share, etc.
    QUOTE = "quote"  # Quote tweet, quote post
    STORY = "story"
    VIDEO = "video"
    THREAD = "thread"
    COMMENT = "comment"


@dataclass
class SocialMediaAuthor:
    """Normalized social media author/account."""
    platform: SocialPlatform
    platform_id: str
    username: str
    display_name: Optional[str]
    profile_url: Optional[str]
    avatar_url: Optional[str]
    verified: bool = False
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    post_count: Optional[int] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "platform": self.platform.value,
            "platform_id": self.platform_id,
            "username": self.username,
            "display_name": self.display_name,
            "profile_url": self.profile_url,
            "avatar_url": self.avatar_url,
            "verified": self.verified,
            "follower_count": self.follower_count,
            "following_count": self.following_count,
            "post_count": self.post_count,
            "bio": self.bio,
            "location": self.location,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata,
        }


@dataclass
class SocialMediaPost:
    """Normalized social media post."""
    platform: SocialPlatform
    platform_id: str
    post_type: PostType
    author: SocialMediaAuthor
    text: str
    html_text: Optional[str]
    url: str
    created_at: datetime
    language: Optional[str]

    # Engagement metrics
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0
    quote_count: int = 0
    view_count: Optional[int] = None
    bookmark_count: Optional[int] = None

    # Media attachments
    media_urls: List[str] = field(default_factory=list)
    media_types: List[str] = field(default_factory=list)

    # Reply/thread context
    reply_to_id: Optional[str] = None
    reply_to_author: Optional[str] = None
    conversation_id: Optional[str] = None

    # Quoted/reposted content
    quoted_post_id: Optional[str] = None
    reposted_post_id: Optional[str] = None

    # Hashtags and mentions
    hashtags: List[str] = field(default_factory=list)
    mentions: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)

    # Raw data and deduplication
    raw_data: Dict[str, Any] = field(default_factory=dict)
    dedup_hash: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "platform": self.platform.value,
            "platform_id": self.platform_id,
            "post_type": self.post_type.value,
            "author": self.author.to_dict(),
            "text": self.text,
            "html_text": self.html_text,
            "url": self.url,
            "created_at": self.created_at.isoformat(),
            "language": self.language,
            "like_count": self.like_count,
            "reply_count": self.reply_count,
            "repost_count": self.repost_count,
            "quote_count": self.quote_count,
            "view_count": self.view_count,
            "bookmark_count": self.bookmark_count,
            "media_urls": self.media_urls,
            "media_types": self.media_types,
            "reply_to_id": self.reply_to_id,
            "reply_to_author": self.reply_to_author,
            "conversation_id": self.conversation_id,
            "quoted_post_id": self.quoted_post_id,
            "reposted_post_id": self.reposted_post_id,
            "hashtags": self.hashtags,
            "mentions": self.mentions,
            "urls": self.urls,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
            "metadata": self.metadata,
        }


# Type variable for platform-specific post types
T = TypeVar("T", bound=SocialMediaPost)


@dataclass
class PlatformRateLimits:
    """Platform-specific rate limit information."""
    platform: SocialPlatform
    endpoint: str
    requests_remaining: int
    requests_limit: int
    reset_at: datetime
    window_seconds: int

    @property
    def is_limited(self) -> bool:
        """Check if rate limited."""
        return self.requests_remaining <= 0

    @property
    def seconds_until_reset(self) -> float:
        """Seconds until rate limit resets."""
        return max(0, (self.reset_at - datetime.utcnow()).total_seconds())


class SocialCollector(BaseCollector[T], Generic[T]):
    """
    Abstract base class for social media platform collectors.

    Provides common interface for:
    - Platform-specific authentication
    - Rate limit handling per endpoint
    - Search by keywords, mentions, user posts
    - Pagination handling
    - Post type detection
    """

    # Subclasses must define
    PLATFORM: SocialPlatform = None

    # Default rate limits (subclasses should override)
    DEFAULT_RATE_LIMITS = {
        "search": RateLimitConfig(
            requests_per_second=1.0,
            requests_per_minute=30.0,
            requests_per_hour=300.0,
        ),
        "user_timeline": RateLimitConfig(
            requests_per_second=1.0,
            requests_per_minute=30.0,
            requests_per_hour=300.0,
        ),
        "mentions": RateLimitConfig(
            requests_per_second=1.0,
            requests_per_minute=30.0,
            requests_per_hour=300.0,
        ),
    }

    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        endpoint_rate_limits: Optional[Dict[str, RateLimitConfig]] = None,
    ):
        """
        Initialize social collector.

        Args:
            rate_limit_config: Global rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            endpoint_rate_limits: Per-endpoint rate limits
        """
        if self.PLATFORM is None:
            raise NotImplementedError("Subclasses must define PLATFORM")

        super().__init__(
            name=f"social_{self.PLATFORM.value}",
            rate_limit_config=rate_limit_config,
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        # Per-endpoint rate limiters
        self.endpoint_rate_limits = endpoint_rate_limits or self.DEFAULT_RATE_LIMITS
        self._platform_rate_limits: Dict[str, PlatformRateLimits] = {}

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the platform.

        Returns:
            True if authentication successful
        """
        pass

    @abstractmethod
    async def search_posts(
        self,
        query: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Search for posts matching query.

        Args:
            query: Search query string
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return
            **kwargs: Platform-specific parameters

        Returns:
            List of raw post data
        """
        pass

    @abstractmethod
    async def get_user_posts(
        self,
        username: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Get posts from a specific user.

        Args:
            username: Username to fetch posts from
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return
            **kwargs: Platform-specific parameters

        Returns:
            List of raw post data
        """
        pass

    @abstractmethod
    async def get_mentions(
        self,
        username: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Get posts mentioning a specific user.

        Args:
            username: Username to find mentions of
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return
            **kwargs: Platform-specific parameters

        Returns:
            List of raw post data
        """
        pass

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        search_terms: Optional[List[str]] = None,
        usernames: Optional[List[str]] = None,
        include_mentions: bool = True,
        include_user_posts: bool = True,
        max_results_per_query: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch posts from social platform.

        Combines search, user posts, and mentions into unified collection.

        Args:
            subject_name: Primary subject name
            aliases: Alternative names/aliases
            since: Start of time range
            until: End of time range
            search_terms: Additional search terms
            usernames: Usernames to collect from/about
            include_mentions: Include posts mentioning usernames
            include_user_posts: Include posts by usernames
            max_results_per_query: Max results per query type
            **kwargs: Platform-specific parameters

        Returns:
            List of raw post data
        """
        all_posts = []
        tasks = []

        # Build search queries
        search_queries = [subject_name] + (aliases or []) + (search_terms or [])

        # Search posts
        for query in search_queries:
            tasks.append(
                self._fetch_with_endpoint_limit(
                    "search",
                    self.search_posts,
                    query,
                    since=since,
                    until=until,
                    max_results=max_results_per_query,
                    **kwargs,
                )
            )

        # User posts
        if include_user_posts and usernames:
            for username in usernames:
                tasks.append(
                    self._fetch_with_endpoint_limit(
                        "user_timeline",
                        self.get_user_posts,
                        username,
                        since=since,
                        until=until,
                        max_results=max_results_per_query,
                        **kwargs,
                    )
                )

        # Mentions
        if include_mentions and usernames:
            for username in usernames:
                tasks.append(
                    self._fetch_with_endpoint_limit(
                        "mentions",
                        self.get_mentions,
                        username,
                        since=since,
                        until=until,
                        max_results=max_results_per_query,
                        **kwargs,
                    )
                )

        # Execute all queries
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.error("fetch_error", error=str(result))
                self.metrics.errors += 1
            else:
                all_posts.extend(result)

        return all_posts

    async def _fetch_with_endpoint_limit(
        self,
        endpoint: str,
        func,
        *args,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Execute fetch with endpoint-specific rate limiting."""
        # Check platform rate limits
        if endpoint in self._platform_rate_limits:
            limit_info = self._platform_rate_limits[endpoint]
            if limit_info.is_limited:
                wait_time = limit_info.seconds_until_reset
                self.logger.warning(
                    "platform_rate_limited",
                    endpoint=endpoint,
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

        return await func(*args, **kwargs)

    def update_platform_rate_limits(
        self,
        endpoint: str,
        remaining: int,
        limit: int,
        reset_at: datetime,
        window_seconds: int = 900,
    ) -> None:
        """
        Update rate limit info from API response headers.

        Args:
            endpoint: Endpoint name
            remaining: Requests remaining
            limit: Total request limit
            reset_at: When limit resets
            window_seconds: Rate limit window size
        """
        self._platform_rate_limits[endpoint] = PlatformRateLimits(
            platform=self.PLATFORM,
            endpoint=endpoint,
            requests_remaining=remaining,
            requests_limit=limit,
            reset_at=reset_at,
            window_seconds=window_seconds,
        )

    def get_platform_rate_limits(self) -> Dict[str, PlatformRateLimits]:
        """Get current platform rate limit info."""
        return self._platform_rate_limits.copy()

    def build_search_query(
        self,
        keywords: List[str],
        include_hashtags: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        from_users: Optional[List[str]] = None,
        to_users: Optional[List[str]] = None,
        mention_users: Optional[List[str]] = None,
        language: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Build platform-specific search query.

        Default implementation - subclasses should override for platform syntax.

        Args:
            keywords: Required keywords (OR)
            include_hashtags: Hashtags to include
            exclude_keywords: Keywords to exclude
            from_users: Posts from these users
            to_users: Posts to these users
            mention_users: Posts mentioning these users
            language: Language filter
            **kwargs: Platform-specific parameters

        Returns:
            Formatted query string
        """
        parts = []

        # Keywords
        if keywords:
            keyword_str = " OR ".join(f'"{k}"' if " " in k else k for k in keywords)
            parts.append(f"({keyword_str})")

        # Exclusions
        if exclude_keywords:
            for kw in exclude_keywords:
                parts.append(f'-"{kw}"' if " " in kw else f"-{kw}")

        return " ".join(parts)

    def detect_post_type(self, raw_post: Dict[str, Any]) -> PostType:
        """
        Detect post type from raw data.

        Default implementation - subclasses should override.
        """
        return PostType.POST

    def extract_entities(
        self,
        text: str,
    ) -> Dict[str, List[str]]:
        """
        Extract hashtags, mentions, and URLs from text.

        Args:
            text: Post text

        Returns:
            Dictionary with 'hashtags', 'mentions', 'urls' lists
        """
        import re

        hashtags = re.findall(r"#(\w+)", text)
        mentions = re.findall(r"@(\w+)", text)
        urls = re.findall(
            r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*",
            text
        )

        return {
            "hashtags": hashtags,
            "mentions": mentions,
            "urls": urls,
        }

    def compute_dedup_hash(self, item: T) -> str:
        """
        Compute deduplication hash for social post.

        Uses platform + platform_id as unique identifier.
        """
        return self.hash_content(
            item.platform.value,
            item.platform_id,
        )
