"""
Twitter/X collector for the Lantern Narrative Intelligence Platform.

Implements Twitter API v2 integration with support for:
- Recent search
- User timeline lookup
- Mention search
- Pagination handling
- Rate limit management
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
import structlog

from .base import (
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)
from .social import (
    SocialCollector,
    SocialPlatform,
    SocialMediaPost,
    SocialMediaAuthor,
    PostType,
    PlatformRateLimits,
)


@dataclass
class TwitterCredentials:
    """Twitter API credentials."""
    bearer_token: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    access_token_secret: Optional[str] = None


class TwitterAPIError(Exception):
    """Twitter API error."""

    def __init__(
        self,
        message: str,
        status_code: int,
        error_code: Optional[int] = None,
        detail: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail


class TwitterRateLimitError(TwitterAPIError):
    """Rate limit exceeded error."""

    def __init__(self, reset_at: datetime, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429)
        self.reset_at = reset_at


class TwitterCollector(SocialCollector[SocialMediaPost]):
    """
    Twitter/X API v2 collector.

    Supports:
    - Recent search (last 7 days for standard, full archive for academic)
    - User tweet timeline
    - User mention timeline
    - Full pagination
    - Rate limit tracking from response headers
    """

    PLATFORM = SocialPlatform.TWITTER

    # API endpoints
    BASE_URL = "https://api.twitter.com/2"

    # Default rate limits (per 15-minute window)
    DEFAULT_RATE_LIMITS = {
        "search": RateLimitConfig(
            requests_per_second=0.5,
            requests_per_minute=30.0,
            requests_per_hour=180.0,  # 180 per 15 min
        ),
        "user_timeline": RateLimitConfig(
            requests_per_second=0.5,
            requests_per_minute=30.0,
            requests_per_hour=180.0,  # 180 per 15 min for app auth
        ),
        "mentions": RateLimitConfig(
            requests_per_second=0.5,
            requests_per_minute=30.0,
            requests_per_hour=180.0,
        ),
        "users": RateLimitConfig(
            requests_per_second=0.5,
            requests_per_minute=60.0,
            requests_per_hour=300.0,
        ),
    }

    # Default fields to request
    TWEET_FIELDS = [
        "id",
        "text",
        "author_id",
        "conversation_id",
        "created_at",
        "entities",
        "in_reply_to_user_id",
        "lang",
        "public_metrics",
        "referenced_tweets",
        "attachments",
        "context_annotations",
        "reply_settings",
    ]

    USER_FIELDS = [
        "id",
        "name",
        "username",
        "created_at",
        "description",
        "location",
        "profile_image_url",
        "protected",
        "public_metrics",
        "url",
        "verified",
    ]

    MEDIA_FIELDS = [
        "media_key",
        "type",
        "url",
        "preview_image_url",
        "alt_text",
    ]

    EXPANSIONS = [
        "author_id",
        "referenced_tweets.id",
        "referenced_tweets.id.author_id",
        "in_reply_to_user_id",
        "attachments.media_keys",
    ]

    def __init__(
        self,
        credentials: TwitterCredentials,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        endpoint_rate_limits: Optional[Dict[str, RateLimitConfig]] = None,
        use_academic_endpoint: bool = False,
    ):
        """
        Initialize Twitter collector.

        Args:
            credentials: Twitter API credentials
            rate_limit_config: Global rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            endpoint_rate_limits: Per-endpoint rate limits
            use_academic_endpoint: Use academic research endpoints (full archive)
        """
        super().__init__(
            rate_limit_config=rate_limit_config,
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
            endpoint_rate_limits=endpoint_rate_limits,
        )

        self.credentials = credentials
        self.use_academic_endpoint = use_academic_endpoint
        self._user_cache: Dict[str, Dict[str, Any]] = {}
        self._authenticated = False

    async def authenticate(self) -> bool:
        """
        Verify authentication with Twitter API.

        Returns:
            True if authentication successful
        """
        try:
            # Test auth by fetching authenticated user info
            headers = self._get_headers()

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/users/me",
                    headers=headers,
                ) as response:
                    if response.status == 200:
                        self._authenticated = True
                        self.logger.info("twitter_authenticated")
                        return True
                    elif response.status == 401:
                        self.logger.error("twitter_auth_failed", status=401)
                        return False
                    else:
                        data = await response.json()
                        self.logger.error(
                            "twitter_auth_error",
                            status=response.status,
                            response=data,
                        )
                        return False

        except Exception as e:
            self.logger.error("twitter_auth_exception", error=str(e))
            return False

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with auth."""
        return {
            "Authorization": f"Bearer {self.credentials.bearer_token}",
            "Content-Type": "application/json",
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make authenticated request to Twitter API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request body

        Returns:
            API response data
        """
        url = f"{self.BASE_URL}/{endpoint}"
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                # Update rate limits from headers
                self._update_rate_limits_from_headers(endpoint, response.headers)

                if response.status == 429:
                    reset_time = self._parse_rate_limit_reset(response.headers)
                    raise TwitterRateLimitError(
                        reset_at=reset_time,
                        message=f"Rate limit exceeded for {endpoint}",
                    )

                response_data = await response.json()

                if response.status >= 400:
                    error = response_data.get("errors", [{}])[0]
                    raise TwitterAPIError(
                        message=error.get("message", "Unknown error"),
                        status_code=response.status,
                        error_code=error.get("code"),
                        detail=error.get("detail"),
                    )

                return response_data

    def _update_rate_limits_from_headers(
        self,
        endpoint: str,
        headers: Dict[str, str],
    ) -> None:
        """Update rate limit tracking from response headers."""
        remaining = headers.get("x-rate-limit-remaining")
        limit = headers.get("x-rate-limit-limit")
        reset = headers.get("x-rate-limit-reset")

        if remaining and limit and reset:
            self.update_platform_rate_limits(
                endpoint=endpoint.split("/")[0],  # Use first part of endpoint
                remaining=int(remaining),
                limit=int(limit),
                reset_at=datetime.fromtimestamp(int(reset), tz=timezone.utc),
                window_seconds=900,  # 15 minutes
            )

    def _parse_rate_limit_reset(self, headers: Dict[str, str]) -> datetime:
        """Parse rate limit reset time from headers."""
        reset = headers.get("x-rate-limit-reset")
        if reset:
            return datetime.fromtimestamp(int(reset), tz=timezone.utc)
        # Default: 15 minutes from now
        return datetime.now(tz=timezone.utc).replace(
            second=0, microsecond=0
        ) + timedelta(minutes=15)

    async def search_posts(
        self,
        query: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Search for tweets matching query.

        Args:
            query: Search query (Twitter query syntax)
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return

        Returns:
            List of raw tweet data
        """
        endpoint = "tweets/search/all" if self.use_academic_endpoint else "tweets/search/recent"

        params = {
            "query": query,
            "max_results": min(max_results, 100),  # API max per page
            "tweet.fields": ",".join(self.TWEET_FIELDS),
            "user.fields": ",".join(self.USER_FIELDS),
            "media.fields": ",".join(self.MEDIA_FIELDS),
            "expansions": ",".join(self.EXPANSIONS),
        }

        if since:
            params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        if until:
            params["end_time"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        return await self._paginate_request(
            endpoint,
            params,
            max_results,
        )

    async def get_user_posts(
        self,
        username: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        exclude_replies: bool = False,
        exclude_retweets: bool = False,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Get tweets from a specific user.

        Args:
            username: Twitter username (without @)
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return
            exclude_replies: Exclude reply tweets
            exclude_retweets: Exclude retweets

        Returns:
            List of raw tweet data
        """
        # First, get user ID
        user_id = await self._get_user_id(username)
        if not user_id:
            self.logger.warning("user_not_found", username=username)
            return []

        endpoint = f"users/{user_id}/tweets"

        params = {
            "max_results": min(max_results, 100),
            "tweet.fields": ",".join(self.TWEET_FIELDS),
            "user.fields": ",".join(self.USER_FIELDS),
            "media.fields": ",".join(self.MEDIA_FIELDS),
            "expansions": ",".join(self.EXPANSIONS),
        }

        excludes = []
        if exclude_replies:
            excludes.append("replies")
        if exclude_retweets:
            excludes.append("retweets")
        if excludes:
            params["exclude"] = ",".join(excludes)

        if since:
            params["start_time"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        if until:
            params["end_time"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")

        return await self._paginate_request(
            endpoint,
            params,
            max_results,
        )

    async def get_mentions(
        self,
        username: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: int = 100,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Get tweets mentioning a specific user.

        Args:
            username: Twitter username (without @)
            since: Start of time range
            until: End of time range
            max_results: Maximum results to return

        Returns:
            List of raw tweet data
        """
        # For mentions, use search with @username
        query = f"@{username}"
        return await self.search_posts(
            query=query,
            since=since,
            until=until,
            max_results=max_results,
            **kwargs,
        )

    async def _get_user_id(self, username: str) -> Optional[str]:
        """Get user ID from username."""
        # Check cache
        if username.lower() in self._user_cache:
            return self._user_cache[username.lower()].get("id")

        try:
            response = await self._make_request(
                "GET",
                f"users/by/username/{username}",
                params={"user.fields": ",".join(self.USER_FIELDS)},
            )

            if response.get("data"):
                user_data = response["data"]
                self._user_cache[username.lower()] = user_data
                return user_data.get("id")

        except TwitterAPIError as e:
            self.logger.error(
                "user_lookup_error",
                username=username,
                error=str(e),
            )

        return None

    async def _paginate_request(
        self,
        endpoint: str,
        params: Dict[str, Any],
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """
        Handle pagination for Twitter API requests.

        Args:
            endpoint: API endpoint
            params: Query parameters
            max_results: Maximum total results

        Returns:
            List of all collected tweets
        """
        all_tweets = []
        next_token = None
        total_collected = 0

        while total_collected < max_results:
            if next_token:
                params["pagination_token"] = next_token

            try:
                response = await self._make_request("GET", endpoint, params=params)
            except TwitterRateLimitError as e:
                wait_time = (e.reset_at - datetime.now(tz=timezone.utc)).total_seconds()
                self.logger.warning(
                    "rate_limit_wait",
                    endpoint=endpoint,
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(max(wait_time, 1))
                continue

            tweets = response.get("data", [])
            if not tweets:
                break

            # Attach includes (users, media, etc.) to tweets
            includes = response.get("includes", {})
            for tweet in tweets:
                tweet["_includes"] = includes
                all_tweets.append(tweet)

            total_collected += len(tweets)

            # Check for next page
            meta = response.get("meta", {})
            next_token = meta.get("next_token")
            if not next_token:
                break

        self.logger.info(
            "pagination_complete",
            endpoint=endpoint,
            total_tweets=len(all_tweets),
        )

        return all_tweets

    def normalize(self, raw_item: Dict[str, Any]) -> SocialMediaPost:
        """
        Normalize raw tweet to SocialMediaPost.

        Args:
            raw_item: Raw tweet data from API

        Returns:
            Normalized SocialMediaPost
        """
        # Parse created_at
        created_at = datetime.now(tz=timezone.utc)
        if raw_item.get("created_at"):
            try:
                created_at = datetime.strptime(
                    raw_item["created_at"],
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    created_at = datetime.strptime(
                        raw_item["created_at"],
                        "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

        # Get author info from includes
        author = self._extract_author(raw_item)

        # Get metrics
        metrics = raw_item.get("public_metrics", {})

        # Detect post type
        post_type = self._detect_post_type(raw_item)

        # Extract entities
        entities = raw_item.get("entities", {})
        hashtags = [h["tag"] for h in entities.get("hashtags", [])]
        mentions = [m["username"] for m in entities.get("mentions", [])]
        urls = [u["expanded_url"] for u in entities.get("urls", []) if u.get("expanded_url")]

        # Extract media
        media_urls = []
        media_types = []
        includes = raw_item.get("_includes", {})
        if raw_item.get("attachments", {}).get("media_keys"):
            media_lookup = {m["media_key"]: m for m in includes.get("media", [])}
            for key in raw_item["attachments"]["media_keys"]:
                media = media_lookup.get(key, {})
                if media.get("url"):
                    media_urls.append(media["url"])
                elif media.get("preview_image_url"):
                    media_urls.append(media["preview_image_url"])
                if media.get("type"):
                    media_types.append(media["type"])

        # Extract reply/quote context
        reply_to_id = None
        quoted_post_id = None
        reposted_post_id = None
        conversation_id = raw_item.get("conversation_id")

        for ref in raw_item.get("referenced_tweets", []):
            if ref["type"] == "replied_to":
                reply_to_id = ref["id"]
            elif ref["type"] == "quoted":
                quoted_post_id = ref["id"]
            elif ref["type"] == "retweeted":
                reposted_post_id = ref["id"]

        post = SocialMediaPost(
            platform=SocialPlatform.TWITTER,
            platform_id=raw_item["id"],
            post_type=post_type,
            author=author,
            text=raw_item.get("text", ""),
            html_text=None,
            url=f"https://twitter.com/{author.username}/status/{raw_item['id']}",
            created_at=created_at,
            language=raw_item.get("lang"),
            like_count=metrics.get("like_count", 0),
            reply_count=metrics.get("reply_count", 0),
            repost_count=metrics.get("retweet_count", 0),
            quote_count=metrics.get("quote_count", 0),
            view_count=metrics.get("impression_count"),
            bookmark_count=metrics.get("bookmark_count"),
            media_urls=media_urls,
            media_types=media_types,
            reply_to_id=reply_to_id,
            reply_to_author=raw_item.get("in_reply_to_user_id"),
            conversation_id=conversation_id,
            quoted_post_id=quoted_post_id,
            reposted_post_id=reposted_post_id,
            hashtags=hashtags,
            mentions=mentions,
            urls=urls,
            raw_data=raw_item,
            dedup_hash="",
        )

        post.dedup_hash = self.compute_dedup_hash(post)
        return post

    def _extract_author(self, raw_item: Dict[str, Any]) -> SocialMediaAuthor:
        """Extract author information from tweet and includes."""
        author_id = raw_item.get("author_id", "")
        includes = raw_item.get("_includes", {})

        # Find author in includes
        author_data = {}
        for user in includes.get("users", []):
            if user.get("id") == author_id:
                author_data = user
                break

        # Also check cache
        if not author_data:
            for username, cached in self._user_cache.items():
                if cached.get("id") == author_id:
                    author_data = cached
                    break

        user_metrics = author_data.get("public_metrics", {})

        return SocialMediaAuthor(
            platform=SocialPlatform.TWITTER,
            platform_id=author_id,
            username=author_data.get("username", "unknown"),
            display_name=author_data.get("name"),
            profile_url=f"https://twitter.com/{author_data.get('username', '')}",
            avatar_url=author_data.get("profile_image_url"),
            verified=author_data.get("verified", False),
            follower_count=user_metrics.get("followers_count"),
            following_count=user_metrics.get("following_count"),
            post_count=user_metrics.get("tweet_count"),
            bio=author_data.get("description"),
            location=author_data.get("location"),
            created_at=self._parse_datetime(author_data.get("created_at")),
        )

    def _detect_post_type(self, raw_item: Dict[str, Any]) -> PostType:
        """Detect tweet type from referenced_tweets."""
        refs = raw_item.get("referenced_tweets", [])

        for ref in refs:
            if ref["type"] == "retweeted":
                return PostType.REPOST
            elif ref["type"] == "quoted":
                return PostType.QUOTE
            elif ref["type"] == "replied_to":
                return PostType.REPLY

        return PostType.POST

    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse Twitter datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.strptime(
                dt_str, "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                return datetime.strptime(
                    dt_str, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                return None

    def build_search_query(
        self,
        keywords: List[str],
        include_hashtags: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        from_users: Optional[List[str]] = None,
        to_users: Optional[List[str]] = None,
        mention_users: Optional[List[str]] = None,
        language: Optional[str] = None,
        has_media: Optional[bool] = None,
        has_links: Optional[bool] = None,
        is_reply: Optional[bool] = None,
        is_retweet: Optional[bool] = None,
        **kwargs,
    ) -> str:
        """
        Build Twitter search query.

        Uses Twitter query syntax:
        https://developer.twitter.com/en/docs/twitter-api/tweets/search/integrate/build-a-query

        Args:
            keywords: Required keywords (OR)
            include_hashtags: Hashtags to include
            exclude_keywords: Keywords to exclude
            from_users: Posts from these users
            to_users: Posts to these users
            mention_users: Posts mentioning these users
            language: Language filter (ISO 639-1)
            has_media: Filter to tweets with media
            has_links: Filter to tweets with links
            is_reply: Filter by reply status
            is_retweet: Filter by retweet status

        Returns:
            Twitter query string
        """
        parts = []

        # Keywords (OR logic)
        if keywords:
            keyword_parts = []
            for kw in keywords:
                if " " in kw:
                    keyword_parts.append(f'"{kw}"')
                else:
                    keyword_parts.append(kw)
            parts.append(f"({' OR '.join(keyword_parts)})")

        # Hashtags
        if include_hashtags:
            for tag in include_hashtags:
                tag = tag.lstrip("#")
                parts.append(f"#{tag}")

        # Exclusions
        if exclude_keywords:
            for kw in exclude_keywords:
                if " " in kw:
                    parts.append(f'-"{kw}"')
                else:
                    parts.append(f"-{kw}")

        # From users
        if from_users:
            user_parts = [f"from:{u.lstrip('@')}" for u in from_users]
            if len(user_parts) > 1:
                parts.append(f"({' OR '.join(user_parts)})")
            else:
                parts.extend(user_parts)

        # To users
        if to_users:
            for u in to_users:
                parts.append(f"to:{u.lstrip('@')}")

        # Mentions
        if mention_users:
            for u in mention_users:
                parts.append(f"@{u.lstrip('@')}")

        # Language
        if language:
            parts.append(f"lang:{language}")

        # Media filter
        if has_media is True:
            parts.append("has:media")
        elif has_media is False:
            parts.append("-has:media")

        # Links filter
        if has_links is True:
            parts.append("has:links")
        elif has_links is False:
            parts.append("-has:links")

        # Reply filter
        if is_reply is True:
            parts.append("is:reply")
        elif is_reply is False:
            parts.append("-is:reply")

        # Retweet filter
        if is_retweet is True:
            parts.append("is:retweet")
        elif is_retweet is False:
            parts.append("-is:retweet")

        return " ".join(parts)


# Import timedelta for rate limit handling
from datetime import timedelta
