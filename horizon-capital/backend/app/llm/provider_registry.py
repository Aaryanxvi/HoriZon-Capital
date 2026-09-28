# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-07727A2F545A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""LLM provider registry -- factory + lookup for configured providers."""

from __future__ import annotations

from app.config import settings
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

    def reload_from_settings(self) -> None:
        """Re-register all providers from current settings values.

        Call this after settings have been mutated in-place (e.g. from the
        settings panel).  Clears existing registrations and re-registers
        from scratch so removed keys take effect.
        """
        # Clear existing registrations
        self._providers.clear()

        # Re-register from current (possibly updated) settings
        self.register("claude", settings.anthropic_api_key)
        self.register("openai", settings.openai_api_key)
        self.register("gemini", settings.google_api_key)

        available = self.list_available()
        logger.info("llm_providers_reloaded", providers=available)

    def get_providers_for_department(self, department: str) -> list[BaseLLMProvider]:
        """Return the providers configured for a given department.

        Respects per-department AI routing settings (ai_front_office, etc.).
        Falls back to all available providers when set to "auto".
        Returns empty list if set to "none".
        """
        from app.config import settings

        dept_map = {
            "front_office": settings.ai_front_office,
            "middle_office": settings.ai_middle_office,
            "back_office": settings.ai_back_office,
            "executive": settings.ai_executive,
        }
        configured = dept_map.get(department, "auto").lower().strip()

        if configured == "none":
            return []
        if configured == "auto":
            return [p for p in self._providers.values()]

        # Specific provider requested
        provider = self._providers.get(configured)
        if provider is not None:
            return [provider]

        # Requested provider not registered — fall back to any available
        logger.warning(
            "dept_provider_not_available",
            department=department,
            requested=configured,
        )
        return [p for p in self._providers.values()]

    def get_provider_name_for_department(self, department: str) -> str:
        """Return a single provider name for a department, or empty string."""
        providers = self.get_providers_for_department(department)
        return providers[0].provider_name if providers else ""

    def get_provider_for_agent(
        self, agent_id: str, default_provider: str = "",
    ) -> BaseLLMProvider | None:
        """Resolve provider+model for a specific agent.

        Resolution order:
          1. Per-agent override (set via UI/REPL) -> overrides both provider + model
          2. Department default provider (default_provider arg)
          3. Any registered provider as last resort

        When an override exists, returns a fresh provider instance whose
        ``model`` attribute reflects the user's pick.
        """
        from app.llm.agent_model_overrides import get_override

        ov = get_override(agent_id)
        if ov:
            base = self._providers.get(ov["provider"])
            if base is not None:
                return base.with_model(ov["model"])
            logger.warning(
                "agent_override_provider_unavailable",
                agent=agent_id, provider=ov["provider"],
            )

        if default_provider:
            base = self._providers.get(default_provider)
            if base is not None:
                return base

        # Fallback: any registered provider
        if self._providers:
            return next(iter(self._providers.values()))
        return None


# Module-level singleton
provider_registry = ProviderRegistry()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 07727A2F545A - verify with scripts/authorship.py verify
