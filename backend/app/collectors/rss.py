"""
RSS feed collector for the Lantern Narrative Intelligence Platform.

Supports multiple RSS/Atom feed formats with robust parsing
and error handling.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
import structlog
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:
    feedparser = None

from .base import (
    BaseCollector,
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)


class FeedFormat(Enum):
    """Supported feed formats."""
    RSS_2_0 = "rss_2.0"
    RSS_1_0 = "rss_1.0"
    ATOM = "atom"
    UNKNOWN = "unknown"


@dataclass
class FeedMetadata:
    """Metadata about an RSS/Atom feed."""
    url: str
    title: str
    description: Optional[str]
    link: Optional[str]
    language: Optional[str]
    format: FeedFormat
    last_build_date: Optional[datetime]
    ttl: Optional[int]  # Time to live in minutes
    image_url: Optional[str]
    generator: Optional[str]


@dataclass
class FeedEntry:
    """Normalized feed entry."""
    feed_url: str
    entry_id: str
    title: str
    link: str
    published_at: Optional[datetime]
    updated_at: Optional[datetime]
    author: Optional[str]
    summary: Optional[str]
    content: Optional[str]
    clean_text: Optional[str]
    categories: List[str]
    enclosures: List[Dict[str, Any]]
    raw_data: Dict[str, Any]
    dedup_hash: str
    collected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feed_url": self.feed_url,
            "entry_id": self.entry_id,
            "title": self.title,
            "link": self.link,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "author": self.author,
            "summary": self.summary,
            "content": self.content,
            "clean_text": self.clean_text,
            "categories": self.categories,
            "enclosures": self.enclosures,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
        }


class FeedParser:
    """
    Wrapper around feedparser with additional utilities.

    Handles format detection and date parsing for various feed types.
    """

    def __init__(self):
        if feedparser is None:
            raise ImportError("feedparser is required: pip install feedparser")
        self.logger = structlog.get_logger(__name__)

    def parse(self, content: str, url: str = "") -> Tuple[FeedMetadata, List[Dict[str, Any]]]:
        """
        Parse RSS/Atom feed content.

        Args:
            content: Raw feed XML content
            url: Feed URL for reference

        Returns:
            Tuple of (FeedMetadata, list of raw entries)
        """
        feed = feedparser.parse(content)

        # Detect format
        format_type = self._detect_format(feed)

        # Extract metadata
        metadata = FeedMetadata(
            url=url,
            title=feed.feed.get("title", ""),
            description=feed.feed.get("description") or feed.feed.get("subtitle"),
            link=feed.feed.get("link"),
            language=feed.feed.get("language"),
            format=format_type,
            last_build_date=self._parse_date(feed.feed.get("updated_parsed")),
            ttl=feed.feed.get("ttl"),
            image_url=self._extract_image(feed.feed),
            generator=feed.feed.get("generator"),
        )

        # Extract entries with raw data
        entries = []
        for entry in feed.entries:
            entries.append(self._entry_to_dict(entry, url))

        return metadata, entries

    def _detect_format(self, feed) -> FeedFormat:
        """Detect feed format from parsed feed."""
        version = getattr(feed, "version", "")

        if "atom" in version.lower():
            return FeedFormat.ATOM
        elif "rss20" in version.lower() or "2.0" in version:
            return FeedFormat.RSS_2_0
        elif "rss10" in version.lower() or "1.0" in version:
            return FeedFormat.RSS_1_0
        else:
            return FeedFormat.UNKNOWN

    def _parse_date(self, time_struct) -> Optional[datetime]:
        """Parse feedparser time_struct to datetime."""
        if not time_struct:
            return None
        try:
            return datetime(*time_struct[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _extract_image(self, feed_data: Dict) -> Optional[str]:
        """Extract feed image URL."""
        if "image" in feed_data:
            img = feed_data["image"]
            if isinstance(img, dict):
                return img.get("href") or img.get("url")
            elif isinstance(img, str):
                return img
        return None

    def _entry_to_dict(self, entry, feed_url: str) -> Dict[str, Any]:
        """Convert feedparser entry to dictionary."""
        # Get content (try multiple fields)
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary or ""

        # Get enclosures (for podcasts, etc.)
        enclosures = []
        if hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                enclosures.append({
                    "url": enc.get("href") or enc.get("url"),
                    "type": enc.get("type"),
                    "length": enc.get("length"),
                })

        # Get categories
        categories = []
        if hasattr(entry, "tags"):
            categories = [tag.get("term", "") for tag in entry.tags if tag.get("term")]

        return {
            "feed_url": feed_url,
            "id": entry.get("id") or entry.get("link", ""),
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published_parsed": entry.get("published_parsed"),
            "updated_parsed": entry.get("updated_parsed"),
            "author": entry.get("author"),
            "summary": entry.get("summary"),
            "content": content,
            "categories": categories,
            "enclosures": enclosures,
        }


class RSSCollector(BaseCollector[FeedEntry]):
    """
    RSS/Atom feed collector.

    Supports:
    - Multiple feed URLs per subject
    - RSS 2.0, RSS 1.0, and Atom formats
    - Concurrent feed fetching
    - Date filtering
    - Content extraction
    """

    # Common User-Agent for feed requests
    USER_AGENT = "Lantern/1.0 (+https://lantern.ai/bot)"

    # Request timeout in seconds
    REQUEST_TIMEOUT = 30

    def __init__(
        self,
        feed_urls: Optional[Dict[str, List[str]]] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        max_concurrent_feeds: int = 10,
    ):
        """
        Initialize RSS collector.

        Args:
            feed_urls: Mapping of subject names to feed URLs
            rate_limit_config: Rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            max_concurrent_feeds: Maximum concurrent feed fetches
        """
        super().__init__(
            name="rss",
            rate_limit_config=rate_limit_config or RateLimitConfig(
                requests_per_second=5.0,
                requests_per_minute=100.0,
                requests_per_hour=2000.0,
            ),
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        self.feed_urls = feed_urls or {}
        self.max_concurrent_feeds = max_concurrent_feeds
        self.parser = FeedParser()
        self._feed_metadata_cache: Dict[str, FeedMetadata] = {}

    def register_feeds(self, subject_name: str, urls: List[str]) -> None:
        """
        Register feed URLs for a subject.

        Args:
            subject_name: Subject identifier
            urls: List of feed URLs
        """
        if subject_name not in self.feed_urls:
            self.feed_urls[subject_name] = []
        self.feed_urls[subject_name].extend(urls)
        self.logger.info(
            "feeds_registered",
            subject=subject_name,
            feed_count=len(urls),
        )

    def get_feeds_for_subject(self, subject_name: str) -> List[str]:
        """Get registered feed URLs for a subject."""
        return self.feed_urls.get(subject_name, [])

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        feed_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch entries from RSS/Atom feeds.

        Args:
            subject_name: Subject identifier (used to look up feeds)
            aliases: Not used for RSS (feeds are explicitly configured)
            since: Only return entries published after this time
            until: Only return entries published before this time
            feed_urls: Override feed URLs (if not using registered feeds)

        Returns:
            List of raw feed entries
        """
        # Get feed URLs
        urls = feed_urls or self.feed_urls.get(subject_name, [])
        if not urls:
            self.logger.warning("no_feeds_configured", subject=subject_name)
            return []

        self.logger.info(
            "fetching_feeds",
            subject=subject_name,
            feed_count=len(urls),
        )

        # Fetch feeds concurrently with semaphore
        semaphore = asyncio.Semaphore(self.max_concurrent_feeds)
        tasks = [
            self._fetch_feed_with_semaphore(semaphore, url, since, until)
            for url in urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect entries
        all_entries = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "feed_fetch_error",
                    feed_url=url,
                    error=str(result),
                )
                self.metrics.errors += 1
            else:
                all_entries.extend(result)

        self.logger.info(
            "feeds_fetched",
            subject=subject_name,
            total_entries=len(all_entries),
        )

        return all_entries

    async def _fetch_feed_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        url: str,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch single feed with semaphore control."""
        async with semaphore:
            return await self._fetch_single_feed(url, since, until)

    async def _fetch_single_feed(
        self,
        url: str,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """
        Fetch and parse a single feed.

        Args:
            url: Feed URL
            since: Start date filter
            until: End date filter

        Returns:
            List of feed entries
        """
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                content = await response.text()

        # Parse feed
        metadata, entries = self.parser.parse(content, url)

        # Cache metadata
        self._feed_metadata_cache[url] = metadata

        # Filter by date
        filtered_entries = []
        for entry in entries:
            entry_date = self._get_entry_date(entry)
            if since and entry_date and entry_date < since:
                continue
            if until and entry_date and entry_date > until:
                continue
            filtered_entries.append(entry)

        self.logger.debug(
            "feed_parsed",
            feed_url=url,
            format=metadata.format.value,
            total_entries=len(entries),
            filtered_entries=len(filtered_entries),
        )

        return filtered_entries

    def _get_entry_date(self, entry: Dict[str, Any]) -> Optional[datetime]:
        """Extract date from entry."""
        # Try published first, then updated
        for key in ["published_parsed", "updated_parsed"]:
            time_struct = entry.get(key)
            if time_struct:
                try:
                    return datetime(*time_struct[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
        return None

    def normalize(self, raw_item: Dict[str, Any]) -> FeedEntry:
        """
        Normalize raw feed entry to FeedEntry.

        Args:
            raw_item: Raw entry from feedparser

        Returns:
            Normalized FeedEntry
        """
        # Parse dates
        published_at = self._get_entry_date(raw_item)
        updated_at = None
        if raw_item.get("updated_parsed"):
            try:
                updated_at = datetime(
                    *raw_item["updated_parsed"][:6],
                    tzinfo=timezone.utc
                )
            except (TypeError, ValueError):
                pass

        # Extract clean text from content
        content = raw_item.get("content", "") or ""
        summary = raw_item.get("summary", "") or ""
        clean_text = self._extract_clean_text(content or summary)

        entry = FeedEntry(
            feed_url=raw_item.get("feed_url", ""),
            entry_id=raw_item.get("id", ""),
            title=raw_item.get("title", ""),
            link=raw_item.get("link", ""),
            published_at=published_at,
            updated_at=updated_at,
            author=raw_item.get("author"),
            summary=summary,
            content=content,
            clean_text=clean_text,
            categories=raw_item.get("categories", []),
            enclosures=raw_item.get("enclosures", []),
            raw_data=raw_item,
            dedup_hash="",
        )

        entry.dedup_hash = self.compute_dedup_hash(entry)
        return entry

    def _extract_clean_text(self, html: str) -> str:
        """Extract plain text from HTML content."""
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remove scripts and styles
        for element in soup(["script", "style"]):
            element.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # Clean up whitespace
        import re
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def compute_dedup_hash(self, item: FeedEntry) -> str:
        """
        Compute deduplication hash for feed entry.

        Uses entry ID (GUID) if available, otherwise URL.
        """
        # Prefer entry ID (GUID)
        if item.entry_id:
            return self.hash_content(item.feed_url, item.entry_id)

        # Fall back to link
        if item.link:
            return self.hash_content(item.link)

        # Last resort: title + feed
        return self.hash_content(item.feed_url, item.title)

    def get_feed_metadata(self, url: str) -> Optional[FeedMetadata]:
        """
        Get cached metadata for a feed.

        Args:
            url: Feed URL

        Returns:
            FeedMetadata or None if not cached
        """
        return self._feed_metadata_cache.get(url)

    async def discover_feeds(self, page_url: str) -> List[str]:
        """
        Discover RSS/Atom feeds from a webpage.

        Looks for <link> tags with rel="alternate" and RSS/Atom types.

        Args:
            page_url: URL of webpage to scan

        Returns:
            List of discovered feed URLs
        """
        headers = {"User-Agent": self.USER_AGENT}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    page_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                ) as response:
                    response.raise_for_status()
                    html = await response.text()
        except Exception as e:
            self.logger.error(
                "feed_discovery_error",
                page_url=page_url,
                error=str(e),
            )
            return []

        soup = BeautifulSoup(html, "html.parser")
        feeds = []

        # Find feed links
        feed_types = [
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
        ]

        for link in soup.find_all("link", rel="alternate"):
            link_type = link.get("type", "")
            if any(ft in link_type for ft in feed_types):
                href = link.get("href", "")
                if href:
                    # Convert relative URLs to absolute
                    if href.startswith("/"):
                        parsed = urlparse(page_url)
                        href = f"{parsed.scheme}://{parsed.netloc}{href}"
                    feeds.append(href)

        self.logger.info(
            "feeds_discovered",
            page_url=page_url,
            feed_count=len(feeds),
        )

        return feeds

    async def validate_feed(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Validate that a URL is a valid RSS/Atom feed.

        Args:
            url: URL to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            headers = {"User-Agent": self.USER_AGENT}

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                ) as response:
                    response.raise_for_status()
                    content = await response.text()

            metadata, entries = self.parser.parse(content, url)

            if not metadata.title and not entries:
                return False, "Feed appears empty or invalid"

            if metadata.format == FeedFormat.UNKNOWN:
                return False, "Unknown feed format"

            return True, None

        except aiohttp.ClientError as e:
            return False, f"HTTP error: {str(e)}"
        except Exception as e:
            return False, f"Parse error: {str(e)}"
