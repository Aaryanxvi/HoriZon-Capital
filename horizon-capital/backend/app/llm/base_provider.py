"""Abstract base class for LLM providers."""

from __future__ import annotations

import abc


class BaseLLMProvider(abc.ABC):
    """Base class for all LLM provider integrations.

    Each provider wraps a single LLM API (Claude, OpenAI, Gemini) and
    exposes a uniform ``complete()`` interface for agent use.
    """

    provider_name: str = ""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @abc.abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        """Send a completion request and return the response text."""
        ...

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""
        ...

    def __repr__(self) -> str:
        masked = f"***{self.api_key[-4:]}" if self.api_key else "NOT SET"
        return f"{self.__class__.__name__}(key={masked})"
