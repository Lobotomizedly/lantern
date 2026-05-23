"""
News collector for the Lantern Narrative Intelligence Platform.

Supports multiple news sources:
- NewsAPI
- GDELT
- RSS feeds

Provides unified interface for collecting news articles about subjects.
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import structlog
from bs4 import BeautifulSoup

from .base import (
    BaseCollector,
    CollectedItem,
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)


class NewsSource(Enum):
    """Supported news sources."""
    NEWSAPI = "newsapi"
    GDELT = "gdelt"
    RSS = "rss"


@dataclass
class NewsArticle:
    """Normalized news article."""
    title: str
    url: str
    source_name: str
    source_type: NewsSource
    published_at: Optional[datetime]
    author: Optional[str]
    description: Optional[str]
    content: Optional[str]
    clean_text: Optional[str]
    image_url: Optional[str]
    language: Optional[str]
    raw_data: Dict[str, Any]
    dedup_hash: str
    collected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "url": self.url,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "author": self.author,
            "description": self.description,
            "content": self.content,
            "clean_text": self.clean_text,
            "image_url": self.image_url,
            "language": self.language,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
            "metadata": self.metadata,
        }


class TextExtractor:
    """Extract clean text from HTML content."""

    # Tags to remove entirely (including content)
    REMOVE_TAGS = [
        "script", "style", "nav", "footer", "header", "aside",
        "advertisement", "ads", "sidebar", "menu", "form",
    ]

    # Patterns for common boilerplate
    BOILERPLATE_PATTERNS = [
        r"cookie[s]?\s+(policy|consent|notice)",
        r"sign\s*up\s+(for|to)",
        r"subscribe\s+(to|now)",
        r"newsletter",
        r"follow\s+us\s+on",
        r"share\s+(this|on)",
        r"read\s+more\s+at",
        r"advertisement",
        r"sponsored\s+content",
    ]

    @classmethod
    def extract(cls, html: str) -> str:
        """
        Extract clean text from HTML.

        Args:
            html: Raw HTML content

        Returns:
            Clean extracted text
        """
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remove unwanted tags
        for tag in soup.find_all(cls.REMOVE_TAGS):
            tag.decompose()

        # Remove elements with common ad/navigation classes
        for element in soup.find_all(
            class_=re.compile(r"(ad|ads|advertisement|nav|menu|sidebar|footer|header)", re.I)
        ):
            element.decompose()

        # Get text
        text = soup.get_text(separator=" ", strip=True)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text)
        text = text.strip()

        # Remove common boilerplate phrases
        for pattern in cls.BOILERPLATE_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.I)

        return text

    @classmethod
    def extract_main_content(cls, html: str) -> str:
        """
        Extract main article content using heuristics.

        Looks for common article containers and paragraph density.
        """
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Try common article containers
        article_selectors = [
            "article",
            '[role="main"]',
            ".article-content",
            ".article-body",
            ".post-content",
            ".entry-content",
            ".story-body",
            "#article-body",
            ".content-body",
            "main",
        ]

        for selector in article_selectors:
            container = soup.select_one(selector)
            if container:
                return cls.extract(str(container))

        # Fall back to finding the div with most paragraph content
        best_container = None
        best_score = 0

        for div in soup.find_all("div"):
            paragraphs = div.find_all("p")
            if paragraphs:
                text_length = sum(len(p.get_text(strip=True)) for p in paragraphs)
                paragraph_count = len(paragraphs)
                score = text_length * paragraph_count

                if score > best_score:
                    best_score = score
                    best_container = div

        if best_container:
            return cls.extract(str(best_container))

        return cls.extract(html)


class NewsAPIClient:
    """Client for NewsAPI.org."""

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.logger = structlog.get_logger(__name__)

    async def search(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        language: str = "en",
        sort_by: str = "publishedAt",
        page_size: int = 100,
        page: int = 1,
    ) -> Dict[str, Any]:
        """
        Search for news articles.

        Args:
            query: Search query
            from_date: Start date
            to_date: End date
            language: Language code
            sort_by: Sort order (publishedAt, relevancy, popularity)
            page_size: Results per page (max 100)
            page: Page number

        Returns:
            API response with articles
        """
        params = {
            "q": query,
            "language": language,
            "sortBy": sort_by,
            "pageSize": min(page_size, 100),
            "page": page,
            "apiKey": self.api_key,
        }

        if from_date:
            params["from"] = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        if to_date:
            params["to"] = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.BASE_URL}/everything",
                params=params,
            ) as response:
                response.raise_for_status()
                return await response.json()


class GDELTClient:
    """Client for GDELT API."""

    BASE_URL = "https://api.gdeltproject.org/api/v2"

    def __init__(self):
        self.logger = structlog.get_logger(__name__)

    async def search(
        self,
        query: str,
        mode: str = "artlist",
        max_records: int = 250,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        sort: str = "datedesc",
    ) -> Dict[str, Any]:
        """
        Search GDELT for articles.

        Args:
            query: Search query
            mode: API mode (artlist, timeline, etc.)
            max_records: Maximum records to return
            from_date: Start date
            to_date: End date
            sort: Sort order

        Returns:
            API response with articles
        """
        params = {
            "query": query,
            "mode": mode,
            "maxrecords": min(max_records, 250),
            "sort": sort,
            "format": "json",
        }

        if from_date:
            params["startdatetime"] = from_date.strftime("%Y%m%d%H%M%S")
        if to_date:
            params["enddatetime"] = to_date.strftime("%Y%m%d%H%M%S")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.BASE_URL}/doc/doc",
                params=params,
            ) as response:
                response.raise_for_status()
                return await response.json()


class NewsCollector(BaseCollector[NewsArticle]):
    """
    Collector for news articles from multiple sources.

    Supports NewsAPI, GDELT, and RSS feeds with unified interface.
    """

    def __init__(
        self,
        newsapi_key: Optional[str] = None,
        enabled_sources: Optional[List[NewsSource]] = None,
        rss_feeds: Optional[Dict[str, List[str]]] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        """
        Initialize news collector.

        Args:
            newsapi_key: API key for NewsAPI
            enabled_sources: List of enabled news sources
            rss_feeds: Mapping of subject names to RSS feed URLs
            rate_limit_config: Rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
        """
        super().__init__(
            name="news",
            rate_limit_config=rate_limit_config or RateLimitConfig(
                requests_per_second=1.0,
                requests_per_minute=30.0,
                requests_per_hour=500.0,
            ),
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        self.newsapi_client = NewsAPIClient(newsapi_key) if newsapi_key else None
        self.gdelt_client = GDELTClient()
        self.enabled_sources = enabled_sources or list(NewsSource)
        self.rss_feeds = rss_feeds or {}
        self.text_extractor = TextExtractor()

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch news articles from all enabled sources.

        Args:
            subject_name: Primary name to search for
            aliases: Alternative names to include in search
            since: Start of time range
            until: End of time range

        Returns:
            List of raw article data
        """
        all_names = [subject_name] + (aliases or [])
        query = self._build_query(all_names)

        results: List[Dict[str, Any]] = []
        tasks = []

        if NewsSource.NEWSAPI in self.enabled_sources and self.newsapi_client:
            tasks.append(self._fetch_newsapi(query, since, until))

        if NewsSource.GDELT in self.enabled_sources:
            tasks.append(self._fetch_gdelt(query, since, until))

        if NewsSource.RSS in self.enabled_sources:
            feed_urls = self.rss_feeds.get(subject_name, [])
            if feed_urls:
                tasks.append(self._fetch_rss(feed_urls, since, until))

        # Execute all fetches concurrently
        if tasks:
            fetch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in fetch_results:
                if isinstance(result, Exception):
                    self.logger.error("fetch_error", error=str(result))
                    self.metrics.errors += 1
                else:
                    results.extend(result)

        return results

    async def _fetch_newsapi(
        self,
        query: str,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch from NewsAPI."""
        try:
            response = await self.newsapi_client.search(
                query=query,
                from_date=since,
                to_date=until,
            )

            articles = response.get("articles", [])
            for article in articles:
                article["_source"] = NewsSource.NEWSAPI.value

            self.logger.info(
                "newsapi_fetch_complete",
                article_count=len(articles),
            )
            return articles

        except Exception as e:
            self.logger.error("newsapi_fetch_error", error=str(e))
            raise

    async def _fetch_gdelt(
        self,
        query: str,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch from GDELT."""
        try:
            response = await self.gdelt_client.search(
                query=query,
                from_date=since,
                to_date=until,
            )

            articles = response.get("articles", [])
            for article in articles:
                article["_source"] = NewsSource.GDELT.value

            self.logger.info(
                "gdelt_fetch_complete",
                article_count=len(articles),
            )
            return articles

        except Exception as e:
            self.logger.error("gdelt_fetch_error", error=str(e))
            raise

    async def _fetch_rss(
        self,
        feed_urls: List[str],
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Fetch from RSS feeds."""
        import feedparser

        articles = []

        async with aiohttp.ClientSession() as session:
            for url in feed_urls:
                try:
                    async with session.get(url) as response:
                        content = await response.text()
                        feed = feedparser.parse(content)

                        for entry in feed.entries:
                            # Parse publication date
                            published = None
                            if hasattr(entry, "published_parsed") and entry.published_parsed:
                                published = datetime(*entry.published_parsed[:6])
                            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                                published = datetime(*entry.updated_parsed[:6])

                            # Filter by date range
                            if since and published and published < since:
                                continue
                            if until and published and published > until:
                                continue

                            articles.append({
                                "title": entry.get("title", ""),
                                "link": entry.get("link", ""),
                                "description": entry.get("summary", ""),
                                "published": published.isoformat() if published else None,
                                "author": entry.get("author", ""),
                                "feed_url": url,
                                "_source": NewsSource.RSS.value,
                            })

                except Exception as e:
                    self.logger.error(
                        "rss_fetch_error",
                        feed_url=url,
                        error=str(e),
                    )

        self.logger.info("rss_fetch_complete", article_count=len(articles))
        return articles

    def normalize(self, raw_item: Dict[str, Any]) -> NewsArticle:
        """
        Normalize raw article data to NewsArticle.

        Handles different formats from NewsAPI, GDELT, and RSS.
        """
        source_type = NewsSource(raw_item.get("_source", "newsapi"))

        if source_type == NewsSource.NEWSAPI:
            return self._normalize_newsapi(raw_item)
        elif source_type == NewsSource.GDELT:
            return self._normalize_gdelt(raw_item)
        else:
            return self._normalize_rss(raw_item)

    def _normalize_newsapi(self, raw: Dict[str, Any]) -> NewsArticle:
        """Normalize NewsAPI article."""
        content = raw.get("content", "") or ""
        description = raw.get("description", "") or ""

        # Extract clean text
        clean_text = self.text_extractor.extract(content) if content else ""
        if not clean_text and description:
            clean_text = self.text_extractor.extract(description)

        # Parse published date
        published_at = None
        if raw.get("publishedAt"):
            try:
                published_at = datetime.fromisoformat(
                    raw["publishedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        article = NewsArticle(
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            source_name=raw.get("source", {}).get("name", ""),
            source_type=NewsSource.NEWSAPI,
            published_at=published_at,
            author=raw.get("author"),
            description=description,
            content=content,
            clean_text=clean_text,
            image_url=raw.get("urlToImage"),
            language=None,
            raw_data=raw,
            dedup_hash="",  # Will be computed
        )

        article.dedup_hash = self.compute_dedup_hash(article)
        return article

    def _normalize_gdelt(self, raw: Dict[str, Any]) -> NewsArticle:
        """Normalize GDELT article."""
        # GDELT has different field names
        title = raw.get("title", "")
        url = raw.get("url", "")

        # Parse date
        published_at = None
        if raw.get("seendate"):
            try:
                published_at = datetime.strptime(
                    raw["seendate"], "%Y%m%dT%H%M%SZ"
                )
            except (ValueError, TypeError):
                pass

        article = NewsArticle(
            title=title,
            url=url,
            source_name=raw.get("domain", ""),
            source_type=NewsSource.GDELT,
            published_at=published_at,
            author=None,
            description=None,
            content=None,
            clean_text=None,
            image_url=raw.get("socialimage"),
            language=raw.get("language"),
            raw_data=raw,
            dedup_hash="",
        )

        article.dedup_hash = self.compute_dedup_hash(article)
        return article

    def _normalize_rss(self, raw: Dict[str, Any]) -> NewsArticle:
        """Normalize RSS feed entry."""
        description = raw.get("description", "") or ""
        clean_text = self.text_extractor.extract(description)

        published_at = None
        if raw.get("published"):
            try:
                published_at = datetime.fromisoformat(raw["published"])
            except (ValueError, TypeError):
                pass

        article = NewsArticle(
            title=raw.get("title", ""),
            url=raw.get("link", ""),
            source_name=urlparse(raw.get("feed_url", "")).netloc,
            source_type=NewsSource.RSS,
            published_at=published_at,
            author=raw.get("author"),
            description=description,
            content=None,
            clean_text=clean_text,
            image_url=None,
            language=None,
            raw_data=raw,
            dedup_hash="",
        )

        article.dedup_hash = self.compute_dedup_hash(article)
        return article

    def compute_dedup_hash(self, item: NewsArticle) -> str:
        """
        Compute deduplication hash for article.

        Uses URL as primary key, with title as fallback.
        """
        if item.url:
            # Normalize URL for deduplication
            parsed = urlparse(item.url)
            normalized_url = f"{parsed.netloc}{parsed.path}".lower()
            return self.hash_content(normalized_url)

        # Fallback to title + source
        return self.hash_content(
            item.title.lower().strip(),
            item.source_name.lower(),
        )

    def _build_query(self, names: List[str]) -> str:
        """
        Build search query from names.

        Combines names with OR operator and quotes multi-word names.
        """
        quoted_names = []
        for name in names:
            if " " in name:
                quoted_names.append(f'"{name}"')
            else:
                quoted_names.append(name)

        return " OR ".join(quoted_names)

    async def fetch_full_content(self, url: str) -> Optional[str]:
        """
        Fetch and extract full article content from URL.

        Args:
            url: Article URL

        Returns:
            Extracted clean text or None on failure
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "Lantern/1.0"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        html = await response.text()
                        return self.text_extractor.extract_main_content(html)
        except Exception as e:
            self.logger.error(
                "full_content_fetch_error",
                url=url,
                error=str(e),
            )
        return None
