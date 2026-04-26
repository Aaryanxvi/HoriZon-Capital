"""Abstract base class for LLM providers."""

from __future__ import annotations

import abc

from app.core.logging import get_logger

logger = get_logger("llm.provider")


class BaseLLMProvider(abc.ABC):
    """Base class for all LLM provider integrations.

    Each provider wraps a single LLM API (Claude, OpenAI, Gemini) and
    exposes a uniform ``complete()`` interface for agent use.
    """

    provider_name: str = ""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        # Subclasses set ``self.model`` in their own __init__. Default empty
        # so ``with_model()`` works generically.
        if not hasattr(self, "model"):
            self.model: str = ""

    def with_model(self, model: str) -> "BaseLLMProvider":
        """Return a new provider instance using a different model.

        Cheap shallow-copy: shares the underlying client when subclasses
        cache it lazily. Used by ProviderRegistry.get_provider_for_agent
        when an override is in effect.
        """
        clone = self.__class__.__new__(self.__class__)
        clone.__dict__.update(self.__dict__)
        clone.model = model
        # Force lazy client to re-create with new model if subclass caches by
        # model — most don't, but be safe.
        if hasattr(clone, "_client"):
            clone._client = None
        return clone

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        """Send a completion request."""
        try:
            return await self._do_complete(system_prompt, messages, temperature)
        except Exception as exc:
            logger.error("llm_complete_error", provider=self.provider_name, error=str(exc))
            raise

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
