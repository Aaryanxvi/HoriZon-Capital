"""LLM provider registry -- factory + lookup for configured providers."""

from __future__ import annotations

from app.core.logging import get_logger
from app.llm.base_provider import BaseLLMProvider

logger = get_logger("llm.registry")


class ProviderRegistry:
    """Central registry for LLM providers.

    Providers are registered with an API key.  The registry lazily
    instantiates provider objects on first ``get_provider()`` call.
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseLLMProvider] = {}

    def register(self, provider_name: str, api_key: str) -> None:
        """Register (or update) a provider with its API key."""
        if not api_key:
            return

        if provider_name == "claude":
            from app.llm.claude_provider import ClaudeProvider
            self._providers[provider_name] = ClaudeProvider(api_key=api_key)
        elif provider_name == "openai":
            from app.llm.openai_provider import OpenAIProvider
            self._providers[provider_name] = OpenAIProvider(api_key=api_key)
        elif provider_name == "gemini":
            from app.llm.gemini_provider import GeminiProvider
            self._providers[provider_name] = GeminiProvider(api_key=api_key)
        else:
            logger.warning("unknown_llm_provider", provider=provider_name)
            return

        logger.info("llm_provider_registered", provider=provider_name)

    def get_provider(self, provider_name: str) -> BaseLLMProvider | None:
        """Return a registered provider, or None if not configured."""
        return self._providers.get(provider_name)

    def list_available(self) -> list[str]:
        """Return names of all registered (configured) providers."""
        return list(self._providers.keys())

    def auto_register_from_settings(self) -> None:
        """Register all providers whose API keys are set in config."""
        from app.config import settings

        self.register("claude", settings.anthropic_api_key)
        self.register("openai", settings.openai_api_key)
        self.register("gemini", settings.google_api_key)

        available = self.list_available()
        logger.info("llm_providers_available", providers=available)


# Module-level singleton
provider_registry = ProviderRegistry()
