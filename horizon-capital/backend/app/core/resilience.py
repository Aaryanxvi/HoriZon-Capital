"""Resilience patterns: circuit breaker, retry with backoff, and timeout helpers.

These utilities wrap external API calls (brokers, data feeds, etc.) to prevent
cascade failures and provide graceful degradation.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, TypeVar

from app.core.logging import get_logger

logger = get_logger("resilience")

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"       # Normal operation
    OPEN = "OPEN"           # Failing — reject calls immediately
    HALF_OPEN = "HALF_OPEN"  # Testing recovery — allow one probe call


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, name: str, until: float) -> None:
        remaining = max(0, until - time.monotonic())
        super().__init__(
            f"Circuit '{name}' is OPEN. Retry in {remaining:.0f}s."
        )
        self.name = name
        self.retry_after = remaining


class CircuitBreaker:
    """Async circuit breaker that tracks consecutive failures.

    Parameters
    ----------
    name : str
        Identifier for logging.
    failure_threshold : int
        Consecutive failures before opening the circuit.
    recovery_timeout : float
        Seconds to wait before attempting a probe call.
    half_open_max : int
        Successful probe calls needed to close the circuit.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute *func* through the circuit breaker."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(
                self.name,
                self._last_failure_time + self.recovery_timeout,
            )

        # Transition internal state for HALF_OPEN so _on_success/_on_failure can see it
        if current_state == CircuitState.HALF_OPEN and self._state == CircuitState.OPEN:
            self._state = CircuitState.HALF_OPEN

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("circuit_closed", circuit=self.name)
            else:
                self._failure_count = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen
                self._state = CircuitState.OPEN
                self._success_count = 0
                logger.warning("circuit_reopened", circuit=self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_opened",
                    circuit=self.name,
                    failures=self._failure_count,
                    recovery_timeout=self.recovery_timeout,
                )

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0


async def retry_with_backoff(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    operation_name: str = "",
    **kwargs: Any,
) -> T:
    """Retry an async function with exponential backoff and jitter.

    Raises the last exception after all retries are exhausted.
    """
    import random

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retry_on as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.25)  # noqa: S311
            total_delay = delay + jitter
            logger.warning(
                "retry_backoff",
                operation=operation_name or func.__name__,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=round(total_delay, 2),
                error=str(exc),
            )
            await asyncio.sleep(total_delay)

    raise last_exc  # type: ignore[misc]


async def with_timeout(
    coro: Awaitable[T],
    timeout_seconds: float,
    operation_name: str = "",
) -> T:
    """Run a coroutine with a timeout. Raises asyncio.TimeoutError on expiry."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError:
        logger.error(
            "operation_timeout",
            operation=operation_name,
            timeout=timeout_seconds,
        )
        raise


class RateLimiter:
    """Sliding-window rate limiter for async calls.

    Tracks calls within a rolling window and rejects when the limit is hit.
    """

    def __init__(self, name: str, max_calls: int, window_seconds: float) -> None:
        self.name = name
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Return True if the call is allowed, False if rate-limited."""
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self.max_calls:
                logger.warning(
                    "rate_limited",
                    limiter=self.name,
                    calls=len(self._timestamps),
                    limit=self.max_calls,
                    window=self.window_seconds,
                )
                return False
            self._timestamps.append(now)
            return True

    @property
    def current_count(self) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        return len([t for t in self._timestamps if t > cutoff])


class RateLimitError(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, name: str, limit: int, window: float) -> None:
        super().__init__(f"Rate limit '{name}' exceeded: {limit} calls per {window}s")
        self.name = name
        self.limit = limit
        self.window = window
