"""
Normalize Stage

Processes raw content to extract clean text and metadata:
- Strip HTML boilerplate
- Extract clean text
- Detect language
- Extract publish metadata
- Handle different content types (article, transcript, filing)
"""

import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment
import langdetect
from langdetect import detect, DetectorFactory
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    RetryableError,
    NonRetryableError,
)


# Make language detection deterministic
DetectorFactory.seed = 0


class ContentTypeDetector:
    """Detects content type based on URL patterns and content analysis."""

    # URL patterns for different content types
    FILING_PATTERNS = [
        r"sec\.gov",
        r"edgar",
        r"10-[kq]",
        r"8-k",
        r"form-",
        r"filing",
    ]

    TRANSCRIPT_PATTERNS = [
        r"transcript",
        r"earnings.?call",
        r"conference.?call",
        r"investor.?day",
        r"webcast",
        r"youtube\.com",
        r"vimeo\.com",
    ]

    @classmethod
    def detect(cls, url: Optional[str], content: str) -> str:
        """
        Detect content type from URL and content.

        Args:
            url: Source URL
            content: Raw content

        Returns:
            Content type: article, transcript, or filing
        """
        url_lower = (url or "").lower()

        # Check for filing patterns
        for pattern in cls.FILING_PATTERNS:
            if re.search(pattern, url_lower, re.IGNORECASE):
                return "filing"

        # Check for transcript patterns
        for pattern in cls.TRANSCRIPT_PATTERNS:
            if re.search(pattern, url_lower, re.IGNORECASE):
                return "transcript"

        # Content-based detection
        content_lower = content.lower()[:5000]  # Check first 5k chars

        # Filing indicators in content
        filing_indicators = [
            "united states securities and exchange commission",
            "form 10-k",
            "form 10-q",
            "form 8-k",
            "pursuant to section",
            "commission file number",
        ]
        if any(ind in content_lower for ind in filing_indicators):
            return "filing"

        # Transcript indicators
        transcript_indicators = [
            "operator:",
            "q&a session",
            "good morning, and welcome to",
            "good afternoon, and welcome to",
            "earnings call",
            "[operator instructions]",
        ]
        if any(ind in content_lower for ind in transcript_indicators):
            return "transcript"

        return "article"


class HTMLCleaner:
    """Cleans HTML content to extract readable text."""

    # Tags to completely remove (including content)
    REMOVE_TAGS = [
        "script",
        "style",
        "noscript",
        "iframe",
        "svg",
        "canvas",
        "video",
        "audio",
        "form",
        "nav",
        "header",
        "footer",
        "aside",
        "advertisement",
    ]

    # Tags that indicate boilerplate content
    BOILERPLATE_CLASSES = [
        "nav",
        "navigation",
        "menu",
        "sidebar",
        "footer",
        "header",
        "advertisement",
        "ad",
        "ads",
        "social",
        "share",
        "comment",
        "comments",
        "related",
        "recommended",
        "newsletter",
        "subscribe",
        "cookie",
        "popup",
        "modal",
    ]

    @classmethod
    def clean(cls, html: str) -> str:
        """
        Extract clean text from HTML.

        Args:
            html: Raw HTML content

        Returns:
            Clean text content
        """
        if not html or not html.strip():
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove unwanted tags completely
        for tag_name in cls.REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove boilerplate elements by class/id
        for class_pattern in cls.BOILERPLATE_CLASSES:
            for element in soup.find_all(
                class_=lambda x: x and class_pattern in str(x).lower()
            ):
                element.decompose()
            for element in soup.find_all(
                id=lambda x: x and class_pattern in str(x).lower()
            ):
                element.decompose()

        # Try to find main content area
        main_content = (
            soup.find("article")
            or soup.find("main")
            or soup.find(class_=re.compile(r"article|content|post|entry", re.I))
            or soup.find(id=re.compile(r"article|content|post|entry", re.I))
            or soup
        )

        # Extract text
        text = main_content.get_text(separator="\n", strip=True)

        # Clean up whitespace
        text = cls._normalize_whitespace(text)

        return text

    @classmethod
    def _normalize_whitespace(cls, text: str) -> str:
        """Normalize whitespace in text."""
        # Replace multiple spaces with single space
        text = re.sub(r"[ \t]+", " ", text)
        # Replace multiple newlines with double newline
        text = re.sub(r"\n\s*\n", "\n\n", text)
        # Strip leading/trailing whitespace from lines
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        return text.strip()


class MetadataExtractor:
    """Extracts metadata from HTML content."""

    @classmethod
    def extract(cls, html: str, url: Optional[str] = None) -> dict[str, Any]:
        """
        Extract metadata from HTML.

        Args:
            html: Raw HTML content
            url: Source URL

        Returns:
            Dictionary of extracted metadata
        """
        soup = BeautifulSoup(html, "html.parser")
        metadata: dict[str, Any] = {}

        # Title
        metadata["title"] = cls._extract_title(soup)

        # Author
        metadata["author"] = cls._extract_author(soup)

        # Published date
        metadata["published_at"] = cls._extract_date(soup)

        # Description
        metadata["description"] = cls._extract_description(soup)

        # Domain from URL
        if url:
            parsed = urlparse(url)
            metadata["domain"] = parsed.netloc

        return metadata

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract title from various sources."""
        # Try Open Graph title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"]

        # Try Twitter title
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            return twitter_title["content"]

        # Try standard title tag
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Remove common suffixes like " | Site Name"
            title = re.split(r"\s*[\|\-\u2013\u2014]\s*", title)[0]
            return title

        # Try h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        return None

    @classmethod
    def _extract_author(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract author from various sources."""
        # Try meta author tag
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"]

        # Try article:author
        article_author = soup.find("meta", property="article:author")
        if article_author and article_author.get("content"):
            return article_author["content"]

        # Try schema.org author
        author_elem = soup.find(itemprop="author")
        if author_elem:
            name = author_elem.find(itemprop="name")
            if name:
                return name.get_text(strip=True)
            return author_elem.get_text(strip=True)

        # Try common class names
        for class_name in ["author", "byline", "writer"]:
            elem = soup.find(class_=re.compile(class_name, re.I))
            if elem:
                text = elem.get_text(strip=True)
                # Clean up "By Author Name" patterns
                text = re.sub(r"^[Bb]y\s+", "", text)
                if text and len(text) < 100:  # Sanity check
                    return text

        return None

    @classmethod
    def _extract_date(cls, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract publication date from various sources."""
        # Try various meta tags
        date_metas = [
            ("property", "article:published_time"),
            ("property", "og:published_time"),
            ("name", "date"),
            ("name", "pubdate"),
            ("name", "publish_date"),
            ("name", "DC.date.issued"),
        ]

        for attr, value in date_metas:
            meta = soup.find("meta", attrs={attr: value})
            if meta and meta.get("content"):
                parsed = cls._parse_date(meta["content"])
                if parsed:
                    return parsed

        # Try time element with datetime attribute
        time_elem = soup.find("time", datetime=True)
        if time_elem:
            parsed = cls._parse_date(time_elem["datetime"])
            if parsed:
                return parsed

        # Try schema.org datePublished
        date_published = soup.find(itemprop="datePublished")
        if date_published:
            content = date_published.get("content") or date_published.get_text(strip=True)
            parsed = cls._parse_date(content)
            if parsed:
                return parsed

        return None

    @classmethod
    def _extract_description(cls, soup: BeautifulSoup) -> Optional[str]:
        """Extract description/summary."""
        # Try meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"]

        # Try Open Graph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"]

        return None

    @classmethod
    def _parse_date(cls, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime."""
        if not date_str:
            return None

        # Common date formats
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        # Clean up the string
        date_str = date_str.strip()

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None


class TranscriptProcessor:
    """Specialized processor for transcript content."""

    @classmethod
    def clean(cls, text: str) -> str:
        """
        Clean and normalize transcript text.

        Args:
            text: Raw transcript text

        Returns:
            Cleaned transcript
        """
        # Normalize speaker labels
        text = re.sub(
            r"^([A-Z][A-Za-z\s]+):\s*",
            r"**\1:** ",
            text,
            flags=re.MULTILINE,
        )

        # Remove operator instructions markers
        text = re.sub(r"\[operator instructions\]", "", text, flags=re.IGNORECASE)

        # Clean up excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()


class FilingProcessor:
    """Specialized processor for SEC filing content."""

    @classmethod
    def clean(cls, text: str) -> str:
        """
        Clean and normalize SEC filing text.

        Args:
            text: Raw filing text

        Returns:
            Cleaned filing content
        """
        # Remove table of contents references
        text = re.sub(r"Table of Contents.*?\n", "", text, flags=re.IGNORECASE)

        # Remove page numbers
        text = re.sub(r"\n\s*\d+\s*\n", "\n", text)

        # Remove excessive legal boilerplate at the start
        # (keep substantive content)
        lines = text.split("\n")
        content_start = 0
        for i, line in enumerate(lines):
            if any(
                marker in line.lower()
                for marker in ["part i", "item 1", "business", "risk factors"]
            ):
                content_start = i
                break

        if content_start > 50:  # Skip significant boilerplate
            text = "\n".join(lines[content_start:])

        return text.strip()


class NormalizeStage(PipelineStage):
    """
    Pipeline stage for normalizing raw content.

    Processes raw HTML/text to extract clean text, detect language,
    and extract metadata.
    """

    stage_name = "normalize"
    next_stage = "dedup"

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)
        self.max_content_length = self.config.get("max_content_length", 100000)
        self.min_content_length = self.config.get("min_content_length", 100)

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Process raw content to extract clean text and metadata.

        Args:
            context: Pipeline context with raw_content

        Returns:
            Updated context with clean_text, language, and metadata
        """
        if not context.raw_content:
            raise NonRetryableError(
                "No raw content to process",
                self.stage_name,
                context.item_id,
            )

        # Detect content type
        context.content_type = ContentTypeDetector.detect(
            context.url, context.raw_content
        )
        self.logger.debug(
            f"Detected content type: {context.content_type} for item {context.item_id}"
        )

        # Check if content is HTML
        is_html = bool(re.search(r"<[^>]+>", context.raw_content[:1000]))

        # Extract metadata from HTML
        if is_html:
            metadata = MetadataExtractor.extract(context.raw_content, context.url)
            if metadata.get("title") and not context.title:
                context.title = metadata["title"]
            if metadata.get("author") and not context.author:
                context.author = metadata["author"]
            if metadata.get("published_at") and not context.published_at:
                context.published_at = metadata["published_at"]

        # Clean content based on type
        if is_html:
            clean_text = HTMLCleaner.clean(context.raw_content)
        else:
            clean_text = context.raw_content

        # Apply content-type specific processing
        if context.content_type == "transcript":
            clean_text = TranscriptProcessor.clean(clean_text)
        elif context.content_type == "filing":
            clean_text = FilingProcessor.clean(clean_text)

        # Validate content length
        if len(clean_text) < self.min_content_length:
            raise NonRetryableError(
                f"Content too short ({len(clean_text)} chars, min {self.min_content_length})",
                self.stage_name,
                context.item_id,
            )

        # Truncate if too long
        if len(clean_text) > self.max_content_length:
            self.logger.warning(
                f"Truncating content from {len(clean_text)} to {self.max_content_length} chars"
            )
            clean_text = clean_text[: self.max_content_length]

        context.clean_text = clean_text

        # Detect language
        try:
            context.language = self._detect_language(clean_text)
        except Exception as e:
            self.logger.warning(f"Language detection failed: {e}")
            context.language = "en"  # Default to English

        self.logger.info(
            f"Normalized item {context.item_id}: "
            f"type={context.content_type}, "
            f"lang={context.language}, "
            f"chars={len(clean_text)}"
        )

        return context

    def _detect_language(self, text: str) -> str:
        """
        Detect the language of text content.

        Args:
            text: Text to analyze

        Returns:
            ISO 639-1 language code
        """
        # Use first portion of text for detection (more reliable)
        sample = text[:5000]

        try:
            lang = detect(sample)
            return lang
        except langdetect.lang_detect_exception.LangDetectException:
            return "en"  # Default to English
