"""
Base collector class for the Lantern Narrative Intelligence Platform.

Provides common functionality for all data collectors including:
- Rate limiting with backoff
- Circuit breaker pattern
- Retry logic with exponential backoff
- Metrics and logging hooks
"""

import asyncio
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

import structlog

# Type variable for collected item types
T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5  # Failures before opening circuit
    success_threshold: int = 2  # Successes in half-open before closing
    timeout_seconds: float = 60.0  # Time before half-open attempt
    excluded_exceptions: tuple = ()  # Exceptions that don't trip breaker


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_second: float = 1.0
    requests_per_minute: float = 60.0
    requests_per_hour: float = 1000.0
    burst_size: int = 10  # Max burst before rate limiting kicks in


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd
    retryable_exceptions: tuple = (Exception,)


@dataclass
class CollectorMetrics:
    """Metrics collected during collection runs."""
    items_fetched: int = 0
    items_normalized: int = 0
    items_deduplicated: int = 0
    errors: int = 0
    retries: int = 0
    rate_limit_waits: int = 0
    circuit_breaker_rejections: int = 0
    total_fetch_time_seconds: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging/reporting."""
        return {
            "items_fetched": self.items_fetched,
            "items_normalized": self.items_normalized,
            "items_deduplicated": self.items_deduplicated,
            "errors": self.errors,
            "retries": self.retries,
            "rate_limit_waits": self.rate_limit_waits,
            "circuit_breaker_rejections": self.circuit_breaker_rejections,
            "total_fetch_time_seconds": self.total_fetch_time_seconds,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (
                (self.end_time - self.start_time).total_seconds()
                if self.start_time and self.end_time else None
            ),
        }


@dataclass
class CollectedItem:
    """Base class for collected items."""
    source: str
    source_id: str
    collected_at: datetime
    raw_data: Dict[str, Any]
    dedup_hash: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class CircuitBreaker:
    """
    Circuit breaker implementation to prevent cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests rejected immediately
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()
        self.logger = structlog.get_logger(__name__)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transition."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time and (
                time.time() - self._last_failure_time >= self.config.timeout_seconds
            ):
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.

        Raises:
            CircuitBreakerOpenError: When circuit is open
        """
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open, rejecting request"
                )

            if current_state == CircuitState.HALF_OPEN:
                self._state = CircuitState.HALF_OPEN

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._on_success()
            return result

        except self.config.excluded_exceptions:
            raise
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self.logger.info("circuit_breaker_closed")
            else:
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._success_count = 0
                self.logger.warning("circuit_breaker_reopened")
            elif self._failure_count >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                self.logger.warning(
                    "circuit_breaker_opened",
                    failure_count=self._failure_count
                )

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting requests."""
    pass


class RateLimiter:
    """
    Token bucket rate limiter with multiple time windows.

    Supports per-second, per-minute, and per-hour limits with burst capacity.
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._tokens: Dict[str, float] = {
            "second": self.config.burst_size,
            "minute": self.config.requests_per_minute,
            "hour": self.config.requests_per_hour,
        }
        self._last_update: Dict[str, float] = {
            "second": time.time(),
            "minute": time.time(),
            "hour": time.time(),
        }
        self._lock = asyncio.Lock()
        self.logger = structlog.get_logger(__name__)

    async def acquire(self) -> float:
        """
        Acquire a token, waiting if necessary.

        Returns:
            Wait time in seconds (0 if no wait needed)
        """
        async with self._lock:
            now = time.time()
            wait_time = 0.0

            # Replenish tokens based on elapsed time
            self._replenish_tokens(now)

            # Check each time window
            for window, limit in [
                ("second", self.config.requests_per_second),
                ("minute", self.config.requests_per_minute),
                ("hour", self.config.requests_per_hour),
            ]:
                if self._tokens[window] < 1:
                    # Calculate wait time
                    window_wait = self._calculate_wait(window, limit)
                    wait_time = max(wait_time, window_wait)

            if wait_time > 0:
                self.logger.debug("rate_limit_wait", wait_seconds=wait_time)
                await asyncio.sleep(wait_time)
                self._replenish_tokens(time.time())

            # Consume tokens
            for window in self._tokens:
                self._tokens[window] -= 1

            return wait_time

    def _replenish_tokens(self, now: float) -> None:
        """Replenish tokens based on elapsed time."""
        windows = {
            "second": (1.0, self.config.requests_per_second, self.config.burst_size),
            "minute": (60.0, self.config.requests_per_minute, self.config.requests_per_minute),
            "hour": (3600.0, self.config.requests_per_hour, self.config.requests_per_hour),
        }

        for window, (duration, rate, max_tokens) in windows.items():
            elapsed = now - self._last_update[window]
            new_tokens = elapsed * (rate / duration)
            self._tokens[window] = min(max_tokens, self._tokens[window] + new_tokens)
            self._last_update[window] = now

    def _calculate_wait(self, window: str, rate: float) -> float:
        """Calculate wait time to get one token."""
        durations = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
        return durations[window] / rate


class BaseCollector(ABC, Generic[T]):
    """
    Abstract base class for all Lantern data collectors.

    Provides common infrastructure for:
    - Rate limiting
    - Circuit breaker pattern
    - Retry with exponential backoff
    - Metrics collection
    - Structured logging

    Subclasses must implement:
    - fetch(): Retrieve raw data from source
    - normalize(): Convert raw data to standard format
    - compute_dedup_hash(): Generate deduplication hash
    """

    def __init__(
        self,
        name: str,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
    ):
        self.name = name
        self.rate_limiter = RateLimiter(rate_limit_config)
        self.circuit_breaker = CircuitBreaker(circuit_breaker_config)
        self.retry_config = retry_config or RetryConfig()
        self.metrics = CollectorMetrics()
        self.logger = structlog.get_logger(__name__).bind(collector=name)
        self._seen_hashes: set = set()

    @abstractmethod
    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch raw data from the source.

        Args:
            subject_name: Primary name to search for
            aliases: Alternative names/aliases to include
            since: Start of time range
            until: End of time range
            **kwargs: Source-specific parameters

        Returns:
            List of raw data items from source
        """
        pass

    @abstractmethod
    def normalize(self, raw_item: Dict[str, Any]) -> T:
        """
        Normalize raw item to standard format.

        Args:
            raw_item: Raw data from source

        Returns:
            Normalized item in standard format
        """
        pass

    @abstractmethod
    def compute_dedup_hash(self, item: T) -> str:
        """
        Compute deduplication hash for item.

        Args:
            item: Normalized item

        Returns:
            Hash string for deduplication
        """
        pass

    async def collect(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> List[T]:
        """
        Main collection method with all protections applied.

        Args:
            subject_name: Primary name to search for
            aliases: Alternative names/aliases to include
            since: Start of time range
            until: End of time range
            **kwargs: Source-specific parameters

        Returns:
            List of normalized, deduplicated items
        """
        self.metrics = CollectorMetrics()
        self.metrics.start_time = datetime.utcnow()
        self._seen_hashes.clear()

        self.logger.info(
            "collection_started",
            subject=subject_name,
            aliases=aliases,
            since=since,
            until=until,
        )

        try:
            # Fetch with rate limiting, circuit breaker, and retry
            raw_items = await self._fetch_with_protections(
                subject_name, aliases, since, until, **kwargs
            )
            self.metrics.items_fetched = len(raw_items)

            # Normalize and deduplicate
            normalized_items: List[T] = []
            for raw_item in raw_items:
                try:
                    item = self.normalize(raw_item)
                    self.metrics.items_normalized += 1

                    # Deduplicate
                    dedup_hash = self.compute_dedup_hash(item)
                    if dedup_hash not in self._seen_hashes:
                        self._seen_hashes.add(dedup_hash)
                        normalized_items.append(item)
                    else:
                        self.metrics.items_deduplicated += 1

                except Exception as e:
                    self.metrics.errors += 1
                    self.logger.error(
                        "normalization_error",
                        error=str(e),
                        raw_item=raw_item,
                    )

            self.metrics.end_time = datetime.utcnow()
            self._log_metrics()

            return normalized_items

        except Exception as e:
            self.metrics.errors += 1
            self.metrics.end_time = datetime.utcnow()
            self.logger.error("collection_failed", error=str(e))
            self._log_metrics()
            raise

    async def _fetch_with_protections(
        self,
        subject_name: str,
        aliases: Optional[List[str]],
        since: Optional[datetime],
        until: Optional[datetime],
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Execute fetch with rate limiting, circuit breaker, and retry."""

        async def _do_fetch():
            # Rate limit
            wait_time = await self.rate_limiter.acquire()
            if wait_time > 0:
                self.metrics.rate_limit_waits += 1

            start_time = time.time()
            result = await self.fetch(subject_name, aliases, since, until, **kwargs)
            self.metrics.total_fetch_time_seconds += time.time() - start_time
            return result

        # Apply circuit breaker
        try:
            return await self._retry_with_backoff(
                lambda: self.circuit_breaker.call(_do_fetch)
            )
        except CircuitBreakerOpenError:
            self.metrics.circuit_breaker_rejections += 1
            raise

    async def _retry_with_backoff(self, func: Callable) -> Any:
        """Execute function with exponential backoff retry."""
        last_exception = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                return await func()
            except self.retry_config.retryable_exceptions as e:
                last_exception = e

                if attempt < self.retry_config.max_retries:
                    delay = self._calculate_backoff_delay(attempt)
                    self.metrics.retries += 1
                    self.logger.warning(
                        "retry_attempt",
                        attempt=attempt + 1,
                        max_retries=self.retry_config.max_retries,
                        delay_seconds=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

        raise last_exception

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with optional jitter."""
        import random

        delay = self.retry_config.base_delay_seconds * (
            self.retry_config.exponential_base ** attempt
        )
        delay = min(delay, self.retry_config.max_delay_seconds)

        if self.retry_config.jitter:
            delay = delay * (0.5 + random.random())

        return delay

    def _log_metrics(self) -> None:
        """Log collection metrics."""
        self.logger.info("collection_metrics", **self.metrics.to_dict())

    def get_metrics(self) -> CollectorMetrics:
        """Get current metrics."""
        return self.metrics

    @staticmethod
    def hash_content(*args: Any) -> str:
        """
        Generate SHA-256 hash from content.

        Useful for implementing compute_dedup_hash.
        """
        content = "|".join(str(arg) for arg in args)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def with_rate_limit(func: Callable) -> Callable:
    """Decorator to apply rate limiting to a method."""
    @wraps(func)
    async def wrapper(self: BaseCollector, *args, **kwargs):
        await self.rate_limiter.acquire()
        return await func(self, *args, **kwargs)
    return wrapper


def with_retry(func: Callable) -> Callable:
    """Decorator to apply retry logic to a method."""
    @wraps(func)
    async def wrapper(self: BaseCollector, *args, **kwargs):
        return await self._retry_with_backoff(lambda: func(self, *args, **kwargs))
    return wrapper
