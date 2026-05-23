"""
Web content collector for the Lantern Narrative Intelligence Platform.

Uses Playwright for headless browser automation to handle:
- JavaScript-heavy sites
- Dynamic content loading
- Complex rendering requirements

Also includes:
- robots.txt compliance
- Readability-style content extraction
- Smart waiting for content
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
import structlog

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from bs4 import BeautifulSoup

from .base import (
    BaseCollector,
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)


@dataclass
class WebPage:
    """Extracted web page content."""
    url: str
    final_url: str  # After redirects
    title: str
    main_content: str
    clean_text: str
    author: Optional[str]
    published_at: Optional[datetime]
    description: Optional[str]
    keywords: List[str]
    images: List[str]
    links: List[str]
    word_count: int
    language: Optional[str]
    html_content: str
    raw_data: Dict[str, Any] = field(default_factory=dict)
    dedup_hash: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "final_url": self.final_url,
            "title": self.title,
            "main_content": self.main_content,
            "clean_text": self.clean_text,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "description": self.description,
            "keywords": self.keywords,
            "images": self.images,
            "links": self.links,
            "word_count": self.word_count,
            "language": self.language,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
            "metadata": self.metadata,
        }


class RobotsChecker:
    """
    Check and respect robots.txt rules.

    Caches robots.txt files per domain with configurable TTL.
    """

    def __init__(
        self,
        user_agent: str = "Lantern/1.0",
        cache_ttl_seconds: int = 3600,
    ):
        self.user_agent = user_agent
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, tuple] = {}  # domain -> (parser, timestamp)
        self.logger = structlog.get_logger(__name__)

    async def can_fetch(self, url: str) -> bool:
        """
        Check if URL can be fetched according to robots.txt.

        Args:
            url: URL to check

        Returns:
            True if allowed, False if disallowed
        """
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        parser = await self._get_parser(domain)
        if parser is None:
            return True  # Allow if no robots.txt

        return parser.can_fetch(self.user_agent, url)

    async def get_crawl_delay(self, url: str) -> Optional[float]:
        """
        Get crawl delay from robots.txt.

        Args:
            url: URL to check

        Returns:
            Crawl delay in seconds or None
        """
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        parser = await self._get_parser(domain)
        if parser is None:
            return None

        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay else None

    async def _get_parser(self, domain: str) -> Optional[RobotFileParser]:
        """Get robots.txt parser for domain, using cache."""
        now = datetime.utcnow()

        # Check cache
        if domain in self._cache:
            parser, cached_at = self._cache[domain]
            if (now - cached_at).total_seconds() < self.cache_ttl:
                return parser

        # Fetch robots.txt
        robots_url = f"{domain}/robots.txt"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    robots_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": self.user_agent},
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                        parser = RobotFileParser()
                        parser.parse(content.splitlines())
                        self._cache[domain] = (parser, now)
                        return parser
                    else:
                        # No robots.txt or error - allow all
                        self._cache[domain] = (None, now)
                        return None

        except Exception as e:
            self.logger.debug(
                "robots_txt_error",
                domain=domain,
                error=str(e),
            )
            return None


class ContentExtractor:
    """
    Extract main content from web pages using readability-like heuristics.

    Identifies the main content area and removes boilerplate.
    """

    # Elements to remove entirely
    REMOVE_ELEMENTS = [
        "script", "style", "nav", "footer", "header", "aside",
        "noscript", "iframe", "embed", "object", "svg", "form",
        "input", "button", "select", "textarea",
    ]

    # Classes/IDs suggesting navigation/boilerplate
    BOILERPLATE_PATTERNS = [
        r"nav", r"menu", r"sidebar", r"footer", r"header",
        r"comment", r"share", r"social", r"advertisement", r"ads",
        r"related", r"popular", r"trending", r"widget", r"modal",
        r"popup", r"cookie", r"newsletter", r"subscribe",
    ]

    # Classes/IDs suggesting main content
    CONTENT_PATTERNS = [
        r"article", r"content", r"post", r"entry", r"main",
        r"body", r"text", r"story",
    ]

    def __init__(self):
        self.logger = structlog.get_logger(__name__)

    def extract(self, html: str, url: str = "") -> Dict[str, Any]:
        """
        Extract main content and metadata from HTML.

        Args:
            html: Raw HTML content
            url: Page URL for resolving relative links

        Returns:
            Dictionary with extracted content
        """
        soup = BeautifulSoup(html, "html.parser")

        # Extract metadata first
        metadata = self._extract_metadata(soup)

        # Remove unwanted elements
        self._remove_boilerplate(soup)

        # Find main content container
        main_content = self._find_main_content(soup)

        # Extract text
        if main_content:
            clean_text = main_content.get_text(separator=" ", strip=True)
        else:
            clean_text = soup.get_text(separator=" ", strip=True)

        # Clean up whitespace
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        # Extract images
        images = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                if url:
                    src = urljoin(url, src)
                images.append(src)

        # Extract links
        links = []
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                if url:
                    href = urljoin(url, href)
                links.append(href)

        return {
            "title": metadata.get("title", ""),
            "main_content": str(main_content) if main_content else "",
            "clean_text": clean_text,
            "author": metadata.get("author"),
            "published_at": metadata.get("published_at"),
            "description": metadata.get("description"),
            "keywords": metadata.get("keywords", []),
            "images": images[:50],  # Limit
            "links": links[:100],  # Limit
            "word_count": len(clean_text.split()),
            "language": metadata.get("language"),
        }

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract page metadata from head."""
        metadata = {}

        # Title
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        # Open Graph / Twitter metadata
        for meta in soup.find_all("meta"):
            name = meta.get("name", "").lower()
            prop = meta.get("property", "").lower()
            content = meta.get("content", "")

            if prop == "og:title" or name == "twitter:title":
                if "title" not in metadata:
                    metadata["title"] = content
            elif prop == "og:description" or name == "description" or name == "twitter:description":
                if "description" not in metadata:
                    metadata["description"] = content
            elif name == "author" or prop == "article:author":
                metadata["author"] = content
            elif name == "keywords":
                metadata["keywords"] = [k.strip() for k in content.split(",")]
            elif prop == "article:published_time":
                try:
                    metadata["published_at"] = datetime.fromisoformat(
                        content.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

        # Language
        html_tag = soup.find("html")
        if html_tag:
            metadata["language"] = html_tag.get("lang")

        return metadata

    def _remove_boilerplate(self, soup: BeautifulSoup) -> None:
        """Remove boilerplate elements from soup."""
        # Remove specific tags
        for tag in soup.find_all(self.REMOVE_ELEMENTS):
            tag.decompose()

        # Remove elements with boilerplate classes/IDs
        boilerplate_re = re.compile(
            "|".join(self.BOILERPLATE_PATTERNS),
            re.IGNORECASE
        )

        for element in soup.find_all(True):
            classes = element.get("class", [])
            element_id = element.get("id", "")

            class_str = " ".join(classes) if isinstance(classes, list) else classes

            if boilerplate_re.search(class_str) or boilerplate_re.search(element_id):
                element.decompose()

    def _find_main_content(self, soup: BeautifulSoup) -> Optional[Any]:
        """Find the main content container."""
        # Try semantic HTML5 elements first
        for selector in ["article", "main", '[role="main"]', ".article", ".content"]:
            element = soup.select_one(selector)
            if element:
                return element

        # Try common content class patterns
        content_re = re.compile(
            "|".join(self.CONTENT_PATTERNS),
            re.IGNORECASE
        )

        candidates = []
        for element in soup.find_all(["div", "section"]):
            classes = element.get("class", [])
            element_id = element.get("id", "")

            class_str = " ".join(classes) if isinstance(classes, list) else classes

            if content_re.search(class_str) or content_re.search(element_id):
                # Score by text density
                text_length = len(element.get_text(strip=True))
                tag_count = len(element.find_all(True))
                score = text_length / max(tag_count, 1)
                candidates.append((element, score))

        if candidates:
            # Return highest scored
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]

        # Fall back to body
        return soup.find("body")


class WebCollector(BaseCollector[WebPage]):
    """
    Playwright-based web content collector.

    Features:
    - Headless browser for JavaScript rendering
    - robots.txt compliance
    - Smart content extraction
    - Configurable waiting strategies
    """

    USER_AGENT = "Mozilla/5.0 (compatible; Lantern/1.0; +https://lantern.ai/bot)"

    def __init__(
        self,
        urls: Optional[Dict[str, List[str]]] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        respect_robots_txt: bool = True,
        headless: bool = True,
        page_timeout_ms: int = 30000,
        wait_for_selector: Optional[str] = None,
        wait_for_load_state: str = "networkidle",
        browser_type: str = "chromium",  # chromium, firefox, webkit
    ):
        """
        Initialize web collector.

        Args:
            urls: Mapping of subject names to URLs
            rate_limit_config: Rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            respect_robots_txt: Check robots.txt before fetching
            headless: Run browser in headless mode
            page_timeout_ms: Page load timeout
            wait_for_selector: CSS selector to wait for
            wait_for_load_state: Page load state to wait for
            browser_type: Browser to use
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "playwright is required: pip install playwright && playwright install"
            )

        super().__init__(
            name="web",
            rate_limit_config=rate_limit_config or RateLimitConfig(
                requests_per_second=0.5,
                requests_per_minute=20.0,
                requests_per_hour=200.0,
            ),
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        self.urls = urls or {}
        self.respect_robots_txt = respect_robots_txt
        self.headless = headless
        self.page_timeout_ms = page_timeout_ms
        self.wait_for_selector = wait_for_selector
        self.wait_for_load_state = wait_for_load_state
        self.browser_type = browser_type

        self.robots_checker = RobotsChecker(user_agent=self.USER_AGENT)
        self.content_extractor = ContentExtractor()

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None

    async def _ensure_browser(self) -> None:
        """Ensure browser is initialized."""
        if self._browser is None:
            self._playwright = await async_playwright().start()

            if self.browser_type == "firefox":
                self._browser = await self._playwright.firefox.launch(
                    headless=self.headless
                )
            elif self.browser_type == "webkit":
                self._browser = await self._playwright.webkit.launch(
                    headless=self.headless
                )
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless
                )

            self._context = await self._browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={"width": 1920, "height": 1080},
            )

            self.logger.info("browser_initialized", type=self.browser_type)

    async def close(self) -> None:
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self._context = None
        self._browser = None
        self._playwright = None
        self.logger.info("browser_closed")

    def register_urls(self, subject_name: str, urls: List[str]) -> None:
        """Register URLs for a subject."""
        if subject_name not in self.urls:
            self.urls[subject_name] = []
        self.urls[subject_name].extend(urls)

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        urls: Optional[List[str]] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch web pages for a subject.

        Args:
            subject_name: Subject identifier
            aliases: Not used for web collection
            since: Not used (web pages don't have inherent dates)
            until: Not used
            urls: Override URLs to fetch

        Returns:
            List of raw page data
        """
        target_urls = urls or self.urls.get(subject_name, [])
        if not target_urls:
            self.logger.warning("no_urls_configured", subject=subject_name)
            return []

        await self._ensure_browser()

        results = []
        for url in target_urls:
            try:
                # Check robots.txt
                if self.respect_robots_txt:
                    if not await self.robots_checker.can_fetch(url):
                        self.logger.info(
                            "robots_txt_disallowed",
                            url=url,
                        )
                        continue

                    # Respect crawl delay
                    delay = await self.robots_checker.get_crawl_delay(url)
                    if delay:
                        await asyncio.sleep(delay)

                # Fetch page
                page_data = await self._fetch_page(url)
                if page_data:
                    results.append(page_data)

            except Exception as e:
                self.logger.error(
                    "page_fetch_error",
                    url=url,
                    error=str(e),
                )
                self.metrics.errors += 1

        return results

    async def _fetch_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch single page using Playwright."""
        page = await self._context.new_page()

        try:
            # Navigate to URL
            response = await page.goto(
                url,
                timeout=self.page_timeout_ms,
                wait_until=self.wait_for_load_state,
            )

            if not response:
                self.logger.warning("no_response", url=url)
                return None

            if response.status >= 400:
                self.logger.warning(
                    "http_error",
                    url=url,
                    status=response.status,
                )
                return None

            # Wait for selector if specified
            if self.wait_for_selector:
                try:
                    await page.wait_for_selector(
                        self.wait_for_selector,
                        timeout=10000,
                    )
                except Exception:
                    self.logger.debug(
                        "selector_not_found",
                        url=url,
                        selector=self.wait_for_selector,
                    )

            # Get final URL (after redirects)
            final_url = page.url

            # Get HTML content
            html = await page.content()

            # Get title
            title = await page.title()

            self.logger.debug(
                "page_fetched",
                url=url,
                final_url=final_url,
                title=title[:50] if title else None,
            )

            return {
                "url": url,
                "final_url": final_url,
                "html": html,
                "title": title,
                "status": response.status,
            }

        finally:
            await page.close()

    async def fetch_with_interaction(
        self,
        url: str,
        interactions: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch page with user interactions.

        Args:
            url: URL to fetch
            interactions: List of interactions to perform
                - {"type": "click", "selector": "..."}
                - {"type": "fill", "selector": "...", "value": "..."}
                - {"type": "wait", "ms": 1000}
                - {"type": "scroll", "y": 500}

        Returns:
            Page data or None on failure
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(url, timeout=self.page_timeout_ms)

            for interaction in interactions:
                action_type = interaction.get("type")

                if action_type == "click":
                    await page.click(interaction["selector"])
                elif action_type == "fill":
                    await page.fill(
                        interaction["selector"],
                        interaction["value"],
                    )
                elif action_type == "wait":
                    await asyncio.sleep(interaction.get("ms", 1000) / 1000)
                elif action_type == "scroll":
                    await page.evaluate(
                        f"window.scrollBy(0, {interaction.get('y', 500)})"
                    )
                elif action_type == "wait_for":
                    await page.wait_for_selector(interaction["selector"])

            html = await page.content()

            return {
                "url": url,
                "final_url": page.url,
                "html": html,
                "title": await page.title(),
            }

        finally:
            await page.close()

    def normalize(self, raw_item: Dict[str, Any]) -> WebPage:
        """
        Normalize raw page data to WebPage.

        Args:
            raw_item: Raw page data

        Returns:
            Normalized WebPage
        """
        html = raw_item.get("html", "")
        url = raw_item.get("url", "")

        # Extract content
        extracted = self.content_extractor.extract(html, url)

        page = WebPage(
            url=url,
            final_url=raw_item.get("final_url", url),
            title=extracted.get("title") or raw_item.get("title", ""),
            main_content=extracted.get("main_content", ""),
            clean_text=extracted.get("clean_text", ""),
            author=extracted.get("author"),
            published_at=extracted.get("published_at"),
            description=extracted.get("description"),
            keywords=extracted.get("keywords", []),
            images=extracted.get("images", []),
            links=extracted.get("links", []),
            word_count=extracted.get("word_count", 0),
            language=extracted.get("language"),
            html_content=html,
            raw_data=raw_item,
            dedup_hash="",
        )

        page.dedup_hash = self.compute_dedup_hash(page)
        return page

    def compute_dedup_hash(self, item: WebPage) -> str:
        """
        Compute deduplication hash for web page.

        Uses URL as primary identifier.
        """
        # Normalize URL
        parsed = urlparse(item.final_url or item.url)
        normalized = f"{parsed.netloc}{parsed.path}".lower().rstrip("/")
        return self.hash_content(normalized)

    async def screenshot(self, url: str, path: str) -> bool:
        """
        Take screenshot of a web page.

        Args:
            url: URL to screenshot
            path: Path to save screenshot

        Returns:
            True on success
        """
        await self._ensure_browser()
        page = await self._context.new_page()

        try:
            await page.goto(url, timeout=self.page_timeout_ms)
            await page.screenshot(path=path, full_page=True)
            return True

        except Exception as e:
            self.logger.error(
                "screenshot_error",
                url=url,
                error=str(e),
            )
            return False

        finally:
            await page.close()

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
