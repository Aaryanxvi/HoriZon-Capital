"""Abstract base class for LLM providers with circuit breaker + rate limiting."""

from __future__ import annotations

import abc

from app.core.logging import get_logger
from app.core.resilience import CircuitBreaker, RateLimiter, RateLimitError

logger = get_logger("llm.provider")

# Shared rate limiter — initialized lazily from settings
_llm_rate_limiter: RateLimiter | None = None


def _get_llm_rate_limiter() -> RateLimiter:
    global _llm_rate_limiter  # noqa: PLW0603
    if _llm_rate_limiter is None:
        from app.config import settings
        _llm_rate_limiter = RateLimiter(
            name="llm_global",
            max_calls=settings.llm_max_calls_per_minute,
            window_seconds=60.0,
        )
    return _llm_rate_limiter

# Per-provider circuit breakers (created on demand)
_circuit_breakers: dict[str, CircuitBreaker] = {}


def _get_circuit_breaker(name: str) -> CircuitBreaker:
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=f"llm_{name}",
            failure_threshold=3,
            recovery_timeout=30.0,
            half_open_max=1,
        )
    return _circuit_breakers[name]


class BaseLLMProvider(abc.ABC):
    """Base class for all LLM provider integrations.

    Each provider wraps a single LLM API (Claude, OpenAI, Gemini) and
    exposes a uniform ``complete()`` interface for agent use.

    Calls are protected by:
    - A global rate limiter (60 calls/min across all providers)
    - Per-provider circuit breakers (open after 3 consecutive failures)
    """

    provider_name: str = ""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        """Send a completion request with rate limiting and circuit breaker."""
        limiter = _get_llm_rate_limiter()
        if not await limiter.acquire():
            raise RateLimitError(
                limiter.name,
                limiter.max_calls,
                limiter.window_seconds,
            )

        cb = _get_circuit_breaker(self.provider_name)
        return await cb.call(self._do_complete, system_prompt, messages, temperature)

    @abc.abstractmethod
    async def _do_complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        """Provider-specific completion implementation."""
        ...

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        ...

    def __repr__(self) -> str:
        masked = f"***{self.api_key[-4:]}" if self.api_key else "NOT SET"
        return f"{self.__class__.__name__}(key={masked})"
