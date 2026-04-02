"""Token bucket rate limiter for API quota management.

Prevents quota exhaustion across broker APIs, data feeds, and LLM calls
by enforcing per-service rate limits using the token bucket algorithm.

Research references
-------------------
- Turner 1986, RFC 970 — token bucket as traffic shaping mechanism.
- BIS 2025, "Project Rio: Fast-Paced Market Monitoring" — recommends
  rate limiting at the API gateway level for trading systems.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger("core.rate_limiter")


@dataclass
class BucketConfig:
    """Configuration for a single rate limit bucket."""

    name: str
    max_tokens: float  # Maximum burst capacity
    refill_rate: float  # Tokens added per second
    tokens: float = 0.0  # Current tokens
    last_refill: float = 0.0  # Timestamp of last refill


class RateLimiter:
    """Multi-service token bucket rate limiter.

    Usage::

        limiter = RateLimiter()
        limiter.add_bucket("alpaca", max_tokens=200, refill_rate=3.3)  # 200/min
        limiter.add_bucket("anthropic", max_tokens=60, refill_rate=1.0)  # 60/min
        limiter.add_bucket("yahoo", max_tokens=100, refill_rate=1.67)

        # Before making an API call:
        await limiter.acquire("alpaca")  # Blocks if rate exceeded
    """

    def __init__(self) -> None:
        self._buckets: dict[str, BucketConfig] = {}
        self._lock = asyncio.Lock()

    def add_bucket(
        self,
        name: str,
        max_tokens: float,
        refill_rate: float,
    ) -> None:
        """Register a rate limit bucket for a service.

        Parameters
        ----------
        name:
            Service identifier (e.g., "alpaca", "anthropic").
        max_tokens:
            Maximum burst capacity (e.g., 200 for 200 requests burst).
        refill_rate:
            Tokens added per second (e.g., 3.33 for 200/min).
        """
        self._buckets[name] = BucketConfig(
            name=name,
            max_tokens=max_tokens,
            refill_rate=refill_rate,
            tokens=max_tokens,  # Start full
            last_refill=time.monotonic(),
        )
        logger.info(
            "rate_bucket_added",
            name=name, max_tokens=max_tokens,
            refill_rate=refill_rate,
        )

    async def acquire(self, name: str, tokens: float = 1.0) -> float:
        """Acquire tokens from a bucket, waiting if necessary.

        Parameters
        ----------
        name:
            Service bucket name.
        tokens:
            Number of tokens to consume (default 1).

        Returns
        -------
        float
            Wait time in seconds (0.0 if no wait was needed).
        """
        bucket = self._buckets.get(name)
        if bucket is None:
            return 0.0  # No limit configured

        total_wait = 0.0

        async with self._lock:
            self._refill(bucket)

            while bucket.tokens < tokens:
                # Calculate wait time
                deficit = tokens - bucket.tokens
                wait = deficit / bucket.refill_rate if bucket.refill_rate > 0 else 1.0
                wait = min(wait, 10.0)  # Cap at 10 seconds

                logger.debug(
                    "rate_limit_wait",
                    bucket=name, wait_secs=round(wait, 3),
                    current_tokens=round(bucket.tokens, 2),
                )

                # Release lock while waiting
                self._lock.release()
                await asyncio.sleep(wait)
                total_wait += wait
                await self._lock.acquire()

                self._refill(bucket)

            bucket.tokens -= tokens

        if total_wait > 0:
            logger.info(
                "rate_limit_throttled",
                bucket=name, waited_secs=round(total_wait, 3),
            )

        return total_wait

    def try_acquire(self, name: str, tokens: float = 1.0) -> bool:
        """Non-blocking acquire. Returns True if tokens available, False otherwise."""
        bucket = self._buckets.get(name)
        if bucket is None:
            return True

        self._refill(bucket)
        if bucket.tokens >= tokens:
            bucket.tokens -= tokens
            return True
        return False

    def get_status(self) -> dict[str, dict]:
        """Return current status of all buckets."""
        status = {}
        for name, bucket in self._buckets.items():
            self._refill(bucket)
            status[name] = {
                "tokens_available": round(bucket.tokens, 2),
                "max_tokens": bucket.max_tokens,
                "refill_rate": bucket.refill_rate,
                "utilization_pct": round(
                    (1 - bucket.tokens / bucket.max_tokens) * 100, 1
                ) if bucket.max_tokens > 0 else 0,
            }
        return status

    @staticmethod
    def _refill(bucket: BucketConfig) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(
                bucket.max_tokens,
                bucket.tokens + elapsed * bucket.refill_rate,
            )
            bucket.last_refill = now


# Default rate limits for common services
DEFAULT_LIMITS = {
    "alpaca": {"max_tokens": 200, "refill_rate": 3.33},      # 200/min
    "zerodha": {"max_tokens": 3, "refill_rate": 0.33},       # 3 req/s burst, ~20/min
    "anthropic": {"max_tokens": 50, "refill_rate": 0.83},    # 50/min
    "openai": {"max_tokens": 60, "refill_rate": 1.0},        # 60/min
    "google": {"max_tokens": 60, "refill_rate": 1.0},        # 60/min
    "yahoo": {"max_tokens": 100, "refill_rate": 1.67},       # 100/min
    "newsapi": {"max_tokens": 100, "refill_rate": 1.67},     # 100/min
    "polygon": {"max_tokens": 5, "refill_rate": 0.083},      # 5/min (free tier)
}


def create_default_limiter() -> RateLimiter:
    """Create a RateLimiter with sensible defaults for all services."""
    limiter = RateLimiter()
    for name, config in DEFAULT_LIMITS.items():
        limiter.add_bucket(name, **config)
    return limiter
