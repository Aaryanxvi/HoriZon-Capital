"""Tests for debate engine hardening: single-provider and role pinning."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.llm.provider_registry import ProviderRegistry


def _make_registry_with_one_provider():
    """Build a ProviderRegistry with only one fake provider."""
    registry = ProviderRegistry()
    fake = MagicMock()
    fake.provider_name = "claude"
    fake.complete = AsyncMock(
        return_value='{"argument": "test", "vote": "FOR", "confidence": 0.8}'
    )
    registry._providers["claude"] = fake
    return registry


def _make_registry_with_two_providers():
    registry = ProviderRegistry()
    for name in ("claude", "openai"):
        fake = MagicMock()
        fake.provider_name = name
        fake.complete = AsyncMock(
            return_value='{"argument": "test", "vote": "FOR", "confidence": 0.8}'
        )
        registry._providers[name] = fake
    return registry


def test_single_provider_assigns_to_all_roles():
    """With one provider, all 4 roles are assigned to that provider."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    role_map = engine._assign_providers()
    assert len(role_map) == 4
    for provider in role_map.values():
        assert provider.provider_name == "claude"


def test_single_provider_runs_both_rounds():
    """With one provider, both debate rounds execute (perspective rotation)."""
    import asyncio
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()
    bus = MagicMock()
    bus.publish = AsyncMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus, max_rounds=2)

    result = asyncio.run(engine.run_debate(
        symbol="AAPL",
        action="BUY",
        signal_data={"strength": 0.8, "strategy_name": "momentum"},
    ))

    # Both rounds should have run
    assert result.rounds == 2
    # 4 roles x 2 rounds = 8 arguments
    assert len(result.arguments) == 8


def test_role_pinning_assigns_correct_provider():
    """When debate_role_strategy is pinned to 'claude', STRATEGY gets Claude."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_two_providers()
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    with patch("app.agents.debate.multi_model_debate.settings") as mock_settings:
        mock_settings.debate_role_strategy = "claude"
        mock_settings.debate_role_risk = "auto"
        mock_settings.debate_role_sentiment = "auto"
        mock_settings.debate_role_portfolio = "auto"
        role_map = engine._assign_providers()

    assert role_map["STRATEGY"].provider_name == "claude"


def test_pinned_provider_unavailable_falls_back():
    """If pinned provider is not registered, role falls back to any available."""
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine

    registry = _make_registry_with_one_provider()  # only claude
    bus = MagicMock()
    engine = MultiModelDebateEngine(registry=registry, bus=bus)

    with patch("app.agents.debate.multi_model_debate.settings") as mock_settings:
        mock_settings.debate_role_strategy = "openai"  # not available
        mock_settings.debate_role_risk = "auto"
        mock_settings.debate_role_sentiment = "auto"
        mock_settings.debate_role_portfolio = "auto"
        role_map = engine._assign_providers()

    # Falls back to claude (the only available provider)
    assert role_map["STRATEGY"].provider_name == "claude"
