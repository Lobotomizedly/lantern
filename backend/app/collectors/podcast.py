"""
Podcast collector for the Lantern Narrative Intelligence Platform.

Supports:
- Podcast RSS feed monitoring
- Episode metadata extraction
- Audio file downloading
- Transcription queue integration (Whisper placeholder)
"""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
import structlog

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


class TranscriptionStatus(Enum):
    """Transcription job status."""
    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class AudioFormat(Enum):
    """Supported audio formats."""
    MP3 = "mp3"
    M4A = "m4a"
    WAV = "wav"
    OGG = "ogg"
    FLAC = "flac"
    AAC = "aac"
    UNKNOWN = "unknown"

    @classmethod
    def from_mime_type(cls, mime_type: str) -> "AudioFormat":
        """Get format from MIME type."""
        mime_map = {
            "audio/mpeg": cls.MP3,
            "audio/mp3": cls.MP3,
            "audio/mp4": cls.M4A,
            "audio/x-m4a": cls.M4A,
            "audio/m4a": cls.M4A,
            "audio/wav": cls.WAV,
            "audio/x-wav": cls.WAV,
            "audio/ogg": cls.OGG,
            "audio/flac": cls.FLAC,
            "audio/aac": cls.AAC,
        }
        return mime_map.get(mime_type.lower(), cls.UNKNOWN)

    @classmethod
    def from_extension(cls, filename: str) -> "AudioFormat":
        """Get format from file extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_map = {
            "mp3": cls.MP3,
            "m4a": cls.M4A,
            "wav": cls.WAV,
            "ogg": cls.OGG,
            "flac": cls.FLAC,
            "aac": cls.AAC,
        }
        return ext_map.get(ext, cls.UNKNOWN)


@dataclass
class PodcastMetadata:
    """Podcast show metadata."""
    feed_url: str
    title: str
    description: Optional[str]
    author: Optional[str]
    link: Optional[str]
    language: Optional[str]
    image_url: Optional[str]
    categories: List[str] = field(default_factory=list)
    last_build_date: Optional[datetime] = None
    episode_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feed_url": self.feed_url,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "link": self.link,
            "language": self.language,
            "image_url": self.image_url,
            "categories": self.categories,
            "last_build_date": self.last_build_date.isoformat() if self.last_build_date else None,
            "episode_count": self.episode_count,
            "metadata": self.metadata,
        }


@dataclass
class PodcastEpisode:
    """Podcast episode data."""
    feed_url: str
    episode_id: str
    title: str
    description: Optional[str]
    clean_description: Optional[str]
    link: Optional[str]
    published_at: Optional[datetime]
    duration_seconds: Optional[int]
    audio_url: str
    audio_format: AudioFormat
    audio_size_bytes: Optional[int]
    image_url: Optional[str]
    season: Optional[int]
    episode_number: Optional[int]
    episode_type: Optional[str]  # full, trailer, bonus
    explicit: bool = False
    keywords: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    dedup_hash: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)

    # Transcription tracking
    transcription_status: TranscriptionStatus = TranscriptionStatus.PENDING
    transcription_job_id: Optional[str] = None
    transcript: Optional[str] = None
    local_audio_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feed_url": self.feed_url,
            "episode_id": self.episode_id,
            "title": self.title,
            "description": self.description,
            "clean_description": self.clean_description,
            "link": self.link,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "duration_seconds": self.duration_seconds,
            "audio_url": self.audio_url,
            "audio_format": self.audio_format.value,
            "audio_size_bytes": self.audio_size_bytes,
            "image_url": self.image_url,
            "season": self.season,
            "episode_number": self.episode_number,
            "episode_type": self.episode_type,
            "explicit": self.explicit,
            "keywords": self.keywords,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
            "transcription_status": self.transcription_status.value,
            "transcription_job_id": self.transcription_job_id,
            "transcript": self.transcript,
            "local_audio_path": self.local_audio_path,
        }


@dataclass
class TranscriptionJob:
    """Transcription job for queuing."""
    job_id: str
    episode: PodcastEpisode
    audio_path: str
    status: TranscriptionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "episode_id": self.episode.episode_id,
            "episode_title": self.episode.title,
            "audio_path": self.audio_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


class TranscriptionQueue:
    """
    Queue for podcast transcription jobs.

    Placeholder for Whisper integration - implements a simple in-memory queue
    that can be replaced with Celery/Redis/etc.
    """

    def __init__(
        self,
        transcription_callback: Optional[Callable[[TranscriptionJob], None]] = None,
    ):
        self.logger = structlog.get_logger(__name__)
        self._queue: asyncio.Queue[TranscriptionJob] = asyncio.Queue()
        self._jobs: Dict[str, TranscriptionJob] = {}
        self._callback = transcription_callback
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def enqueue(self, episode: PodcastEpisode, audio_path: str) -> TranscriptionJob:
        """
        Add episode to transcription queue.

        Args:
            episode: Podcast episode
            audio_path: Path to downloaded audio file

        Returns:
            TranscriptionJob
        """
        job_id = hashlib.sha256(
            f"{episode.episode_id}:{audio_path}".encode()
        ).hexdigest()[:16]

        job = TranscriptionJob(
            job_id=job_id,
            episode=episode,
            audio_path=audio_path,
            status=TranscriptionStatus.QUEUED,
            created_at=datetime.utcnow(),
        )

        self._jobs[job_id] = job
        await self._queue.put(job)

        self.logger.info(
            "transcription_job_queued",
            job_id=job_id,
            episode_id=episode.episode_id,
            title=episode.title,
        )

        return job

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def get_pending_jobs(self) -> List[TranscriptionJob]:
        """Get all pending/queued jobs."""
        return [
            job for job in self._jobs.values()
            if job.status in [TranscriptionStatus.PENDING, TranscriptionStatus.QUEUED]
        ]

    async def start_worker(self) -> None:
        """Start background worker for processing queue."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        self.logger.info("transcription_worker_started")

    async def stop_worker(self) -> None:
        """Stop background worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self.logger.info("transcription_worker_stopped")

    async def _process_queue(self) -> None:
        """Process transcription queue."""
        while self._running:
            try:
                job = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )

                job.status = TranscriptionStatus.IN_PROGRESS
                job.started_at = datetime.utcnow()

                try:
                    # Placeholder for actual transcription
                    # In production, this would call Whisper API or local model
                    result = await self._transcribe_audio(job)

                    job.status = TranscriptionStatus.COMPLETED
                    job.completed_at = datetime.utcnow()
                    job.result = result
                    job.episode.transcript = result
                    job.episode.transcription_status = TranscriptionStatus.COMPLETED

                    self.logger.info(
                        "transcription_completed",
                        job_id=job.job_id,
                        episode_id=job.episode.episode_id,
                    )

                    if self._callback:
                        self._callback(job)

                except Exception as e:
                    job.status = TranscriptionStatus.FAILED
                    job.completed_at = datetime.utcnow()
                    job.error = str(e)
                    job.episode.transcription_status = TranscriptionStatus.FAILED

                    self.logger.error(
                        "transcription_failed",
                        job_id=job.job_id,
                        error=str(e),
                    )

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("queue_processing_error", error=str(e))

    async def _transcribe_audio(self, job: TranscriptionJob) -> str:
        """
        Transcribe audio file.

        This is a placeholder for Whisper integration.
        In production, implement actual transcription logic here.
        """
        # Placeholder: return empty transcript
        # Real implementation would:
        # 1. Load audio file
        # 2. Run Whisper model (local or API)
        # 3. Return transcript text

        self.logger.info(
            "transcription_placeholder",
            job_id=job.job_id,
            audio_path=job.audio_path,
        )

        # Simulate processing time
        await asyncio.sleep(0.1)

        return f"[Transcription pending for: {job.episode.title}]"


class PodcastCollector(BaseCollector[PodcastEpisode]):
    """
    Podcast RSS feed collector.

    Features:
    - Monitor podcast RSS feeds
    - Extract episode metadata
    - Download audio files
    - Queue for transcription
    """

    USER_AGENT = "Lantern/1.0 (+https://lantern.ai/bot)"
    REQUEST_TIMEOUT = 60
    DOWNLOAD_CHUNK_SIZE = 8192

    def __init__(
        self,
        feed_urls: Optional[Dict[str, List[str]]] = None,
        download_directory: Optional[str] = None,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        auto_download: bool = False,
        auto_transcribe: bool = False,
        transcription_callback: Optional[Callable[[TranscriptionJob], None]] = None,
    ):
        """
        Initialize podcast collector.

        Args:
            feed_urls: Mapping of subject names to podcast feed URLs
            download_directory: Directory for downloaded audio files
            rate_limit_config: Rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            auto_download: Automatically download audio files
            auto_transcribe: Automatically queue for transcription
            transcription_callback: Callback when transcription completes
        """
        if feedparser is None:
            raise ImportError("feedparser is required: pip install feedparser")

        super().__init__(
            name="podcast",
            rate_limit_config=rate_limit_config or RateLimitConfig(
                requests_per_second=2.0,
                requests_per_minute=60.0,
                requests_per_hour=500.0,
            ),
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        self.feed_urls = feed_urls or {}
        self.download_directory = download_directory or "/tmp/lantern/podcasts"
        self.auto_download = auto_download
        self.auto_transcribe = auto_transcribe

        self._podcast_metadata_cache: Dict[str, PodcastMetadata] = {}
        self.transcription_queue = TranscriptionQueue(
            transcription_callback=transcription_callback
        )

        # Ensure download directory exists
        Path(self.download_directory).mkdir(parents=True, exist_ok=True)

    def register_feeds(self, subject_name: str, urls: List[str]) -> None:
        """Register podcast feed URLs for a subject."""
        if subject_name not in self.feed_urls:
            self.feed_urls[subject_name] = []
        self.feed_urls[subject_name].extend(urls)
        self.logger.info(
            "podcast_feeds_registered",
            subject=subject_name,
            feed_count=len(urls),
        )

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        feed_urls: Optional[List[str]] = None,
        max_episodes_per_feed: int = 50,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch podcast episodes from RSS feeds.

        Args:
            subject_name: Subject identifier
            aliases: Not used for podcasts
            since: Only return episodes published after this time
            until: Only return episodes published before this time
            feed_urls: Override feed URLs
            max_episodes_per_feed: Maximum episodes per feed

        Returns:
            List of raw episode data
        """
        urls = feed_urls or self.feed_urls.get(subject_name, [])
        if not urls:
            self.logger.warning("no_podcast_feeds_configured", subject=subject_name)
            return []

        all_episodes = []
        tasks = [
            self._fetch_feed(url, since, until, max_episodes_per_feed)
            for url in urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                self.logger.error(
                    "podcast_feed_error",
                    feed_url=url,
                    error=str(result),
                )
                self.metrics.errors += 1
            else:
                all_episodes.extend(result)

        self.logger.info(
            "podcast_episodes_fetched",
            subject=subject_name,
            total_episodes=len(all_episodes),
        )

        return all_episodes

    async def _fetch_feed(
        self,
        url: str,
        since: Optional[datetime],
        until: Optional[datetime],
        max_episodes: int,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse single podcast feed."""
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                content = await response.text()

        feed = feedparser.parse(content)

        # Cache podcast metadata
        self._cache_podcast_metadata(url, feed)

        # Extract episodes
        episodes = []
        for entry in feed.entries[:max_episodes]:
            episode_data = self._parse_episode(url, entry)

            # Filter by date
            if episode_data.get("published_at"):
                try:
                    pub_date = datetime.fromisoformat(episode_data["published_at"])
                    if since and pub_date < since:
                        continue
                    if until and pub_date > until:
                        continue
                except (ValueError, TypeError):
                    pass

            episodes.append(episode_data)

        return episodes

    def _cache_podcast_metadata(self, url: str, feed) -> None:
        """Extract and cache podcast metadata."""
        # Parse last build date
        last_build = None
        if hasattr(feed.feed, "updated_parsed") and feed.feed.updated_parsed:
            try:
                last_build = datetime(*feed.feed.updated_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        # Extract categories
        categories = []
        if hasattr(feed.feed, "tags"):
            categories = [tag.get("term", "") for tag in feed.feed.tags if tag.get("term")]

        # Extract image
        image_url = None
        if hasattr(feed.feed, "image") and feed.feed.image:
            image_url = feed.feed.image.get("href") or feed.feed.image.get("url")
        elif hasattr(feed.feed, "itunes_image"):
            image_url = feed.feed.itunes_image

        self._podcast_metadata_cache[url] = PodcastMetadata(
            feed_url=url,
            title=feed.feed.get("title", ""),
            description=feed.feed.get("description") or feed.feed.get("subtitle"),
            author=feed.feed.get("author") or feed.feed.get("itunes_author"),
            link=feed.feed.get("link"),
            language=feed.feed.get("language"),
            image_url=image_url,
            categories=categories,
            last_build_date=last_build,
            episode_count=len(feed.entries),
        )

    def _parse_episode(self, feed_url: str, entry) -> Dict[str, Any]:
        """Parse feedparser entry to episode data."""
        # Get audio enclosure
        audio_url = ""
        audio_type = ""
        audio_size = None

        for enc in getattr(entry, "enclosures", []):
            enc_type = enc.get("type", "")
            if enc_type.startswith("audio/"):
                audio_url = enc.get("href") or enc.get("url", "")
                audio_type = enc_type
                audio_size = enc.get("length")
                break

        # Parse duration
        duration_seconds = None
        if hasattr(entry, "itunes_duration"):
            duration_seconds = self._parse_duration(entry.itunes_duration)

        # Parse published date
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        # Get episode image
        image_url = None
        if hasattr(entry, "image") and entry.image:
            image_url = entry.image.get("href") or entry.image.get("url")
        elif hasattr(entry, "itunes_image"):
            image_url = entry.itunes_image

        return {
            "feed_url": feed_url,
            "id": entry.get("id") or entry.get("guid") or audio_url,
            "title": entry.get("title", ""),
            "description": entry.get("summary") or entry.get("description"),
            "link": entry.get("link"),
            "published_at": published_at.isoformat() if published_at else None,
            "duration_seconds": duration_seconds,
            "audio_url": audio_url,
            "audio_type": audio_type,
            "audio_size": int(audio_size) if audio_size else None,
            "image_url": image_url,
            "season": getattr(entry, "itunes_season", None),
            "episode_number": getattr(entry, "itunes_episode", None),
            "episode_type": getattr(entry, "itunes_episodetype", None),
            "explicit": getattr(entry, "itunes_explicit", "no") == "yes",
            "keywords": getattr(entry, "itunes_keywords", "").split(",") if hasattr(entry, "itunes_keywords") else [],
        }

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Parse iTunes duration to seconds."""
        if not duration_str:
            return None

        try:
            # Try as integer (seconds)
            return int(duration_str)
        except ValueError:
            pass

        # Try HH:MM:SS or MM:SS format
        parts = duration_str.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass

        return None

    def normalize(self, raw_item: Dict[str, Any]) -> PodcastEpisode:
        """
        Normalize raw episode data to PodcastEpisode.

        Args:
            raw_item: Raw episode data

        Returns:
            Normalized PodcastEpisode
        """
        # Parse published date
        published_at = None
        if raw_item.get("published_at"):
            try:
                published_at = datetime.fromisoformat(raw_item["published_at"])
            except (ValueError, TypeError):
                pass

        # Determine audio format
        audio_format = AudioFormat.UNKNOWN
        if raw_item.get("audio_type"):
            audio_format = AudioFormat.from_mime_type(raw_item["audio_type"])
        if audio_format == AudioFormat.UNKNOWN and raw_item.get("audio_url"):
            audio_format = AudioFormat.from_extension(raw_item["audio_url"])

        # Clean description
        clean_description = None
        if raw_item.get("description"):
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_item["description"], "html.parser")
            clean_description = soup.get_text(separator=" ", strip=True)

        episode = PodcastEpisode(
            feed_url=raw_item.get("feed_url", ""),
            episode_id=raw_item.get("id", ""),
            title=raw_item.get("title", ""),
            description=raw_item.get("description"),
            clean_description=clean_description,
            link=raw_item.get("link"),
            published_at=published_at,
            duration_seconds=raw_item.get("duration_seconds"),
            audio_url=raw_item.get("audio_url", ""),
            audio_format=audio_format,
            audio_size_bytes=raw_item.get("audio_size"),
            image_url=raw_item.get("image_url"),
            season=raw_item.get("season"),
            episode_number=raw_item.get("episode_number"),
            episode_type=raw_item.get("episode_type"),
            explicit=raw_item.get("explicit", False),
            keywords=raw_item.get("keywords", []),
            raw_data=raw_item,
            dedup_hash="",
        )

        episode.dedup_hash = self.compute_dedup_hash(episode)
        return episode

    def compute_dedup_hash(self, item: PodcastEpisode) -> str:
        """
        Compute deduplication hash for episode.

        Uses episode ID and feed URL.
        """
        return self.hash_content(item.feed_url, item.episode_id)

    async def download_audio(
        self,
        episode: PodcastEpisode,
        directory: Optional[str] = None,
    ) -> Optional[str]:
        """
        Download episode audio file.

        Args:
            episode: Podcast episode
            directory: Override download directory

        Returns:
            Path to downloaded file or None on failure
        """
        if not episode.audio_url:
            self.logger.warning(
                "no_audio_url",
                episode_id=episode.episode_id,
            )
            return None

        target_dir = directory or self.download_directory
        Path(target_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename
        ext = episode.audio_format.value
        if ext == "unknown":
            ext = "mp3"
        safe_title = re.sub(r"[^\w\-_]", "_", episode.title)[:50]
        filename = f"{episode.dedup_hash[:8]}_{safe_title}.{ext}"
        filepath = os.path.join(target_dir, filename)

        # Skip if already downloaded
        if os.path.exists(filepath):
            self.logger.debug(
                "audio_already_downloaded",
                episode_id=episode.episode_id,
                path=filepath,
            )
            episode.local_audio_path = filepath
            return filepath

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    episode.audio_url,
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=600),  # 10 min for large files
                ) as response:
                    response.raise_for_status()

                    with open(filepath, "wb") as f:
                        async for chunk in response.content.iter_chunked(
                            self.DOWNLOAD_CHUNK_SIZE
                        ):
                            f.write(chunk)

            episode.local_audio_path = filepath
            self.logger.info(
                "audio_downloaded",
                episode_id=episode.episode_id,
                path=filepath,
            )
            return filepath

        except Exception as e:
            self.logger.error(
                "audio_download_error",
                episode_id=episode.episode_id,
                audio_url=episode.audio_url,
                error=str(e),
            )
            return None

    async def queue_for_transcription(
        self,
        episode: PodcastEpisode,
    ) -> Optional[TranscriptionJob]:
        """
        Queue episode for transcription.

        Will download audio first if not already downloaded.

        Args:
            episode: Podcast episode

        Returns:
            TranscriptionJob or None on failure
        """
        # Download if needed
        if not episode.local_audio_path:
            path = await self.download_audio(episode)
            if not path:
                return None

        episode.transcription_status = TranscriptionStatus.QUEUED
        job = await self.transcription_queue.enqueue(
            episode,
            episode.local_audio_path,
        )

        return job

    async def collect_and_transcribe(
        self,
        subject_name: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> Tuple[List[PodcastEpisode], List[TranscriptionJob]]:
        """
        Collect episodes and queue for transcription.

        Args:
            subject_name: Subject identifier
            since: Start of time range
            until: End of time range

        Returns:
            Tuple of (episodes, transcription_jobs)
        """
        episodes = await self.collect(
            subject_name,
            since=since,
            until=until,
            **kwargs,
        )

        jobs = []
        for episode in episodes:
            job = await self.queue_for_transcription(episode)
            if job:
                jobs.append(job)

        return episodes, jobs

    def get_podcast_metadata(self, feed_url: str) -> Optional[PodcastMetadata]:
        """Get cached metadata for a podcast feed."""
        return self._podcast_metadata_cache.get(feed_url)

    async def start_transcription_worker(self) -> None:
        """Start the transcription queue worker."""
        await self.transcription_queue.start_worker()

    async def stop_transcription_worker(self) -> None:
        """Stop the transcription queue worker."""
        await self.transcription_queue.stop_worker()
