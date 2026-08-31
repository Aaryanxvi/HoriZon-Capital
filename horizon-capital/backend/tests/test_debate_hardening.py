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
        mock_settings.debate_model = ""  # provider default, no with_model() re-wrap
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
        mock_settings.debate_model = ""  # provider default, no with_model() re-wrap
        role_map = engine._assign_providers()

    # Falls back to claude (the only available provider)
    assert role_map["STRATEGY"].provider_name == "claude"


# --------------------------------------------------------------------------- #
# Argument persistence + `debate <id>` detail view
# --------------------------------------------------------------------------- #

def _multi_round_result(session_id: str = "sess-detail-1"):
    from app.agents.debate.multi_model_debate import (
        MultiModelArgument,
        MultiModelDebateResult,
    )

    return MultiModelDebateResult(
        session_id=session_id,
        symbol="PM-will-the-fed-cut.POLY",
        proposed_action="BUY",
        decision="APPROVED",
        consensus_score=0.62,
        arguments=[],
        for_count=2, against_count=1, abstain_count=1,
        rounds=2,
        providers_used=["openai"],
        round_arguments={
            1: [
                MultiModelArgument(
                    role="STRATEGY", argument="Probability drift favours YES.",
                    vote="FOR", confidence=0.7, provider="openai", round_number=1,
                ),
                MultiModelArgument(
                    role="RISK", argument="Resolution risk is material.",
                    vote="AGAINST", confidence=0.6, provider="openai", round_number=1,
                ),
            ],
            2: [
                MultiModelArgument(
                    role="RISK", argument="Rotated: the drift is real.",
                    vote="FOR", confidence=0.55, provider="openai",
                    round_number=2, rotated_from="STRATEGY",
                ),
            ],
        },
    )


@pytest.mark.asyncio
async def test_debate_arguments_are_persisted():
    """Every debater's reasoning must survive the process, not just the summary."""
    from sqlalchemy import text

    from app.agents.middle_office.debate_agent import DebateAgent
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    result = _multi_round_result("sess-persist-1")
    async with local_session_factory() as s:
        await s.execute(
            text("DELETE FROM debate_arguments WHERE session_id = :sid"),
            {"sid": result.session_id},
        )
        await s.commit()

    await DebateAgent._persist_debate(result)

    async with local_session_factory() as s:
        rows = (await s.execute(text(
            "SELECT role, vote, confidence, round_number, argument, agent_id "
            "FROM debate_arguments WHERE session_id = :sid ORDER BY round_number, role"
        ), {"sid": result.session_id})).fetchall()

    assert len(rows) == 3, "one row per debater per round"
    assert {r.vote for r in rows} == {"FOR", "AGAINST"}
    assert all(r.agent_id == "openai" for r in rows)
    # A rotated debater is labelled so the transcript shows the perspective swap.
    rotated = [r for r in rows if r.round_number == 2][0]
    assert rotated.role == "RISK (as STRATEGY)"


@pytest.mark.asyncio
async def test_debate_detail_renders_transcript():
    from app.agents.middle_office.debate_agent import DebateAgent
    from app.core.local_storage import init_local_db
    from app.tui.commands import CommandHandler

    await init_local_db()
    result = _multi_round_result("sess-detail-2")
    await DebateAgent._persist_debate(result)

    out = await CommandHandler().handle(f"debate {result.session_id[:8]}")

    assert "Round 1" in out and "Round 2" in out
    assert "Probability drift favours YES." in out
    assert "Resolution risk is material." in out
    assert "RISK (as STRATEGY)" in out
    assert "APPROVED" in out


@pytest.mark.asyncio
async def test_debate_detail_unknown_key_is_not_an_error():
    from app.core.local_storage import init_local_db
    from app.tui.commands import CommandHandler

    await init_local_db()
    out = await CommandHandler().handle("debate NO-SUCH-SYMBOL-XYZ")
    assert "No debate found" in out


# --------------------------------------------------------------------------- #
# Provider failures must not vote
# --------------------------------------------------------------------------- #

def _registry_with(complete_side_effect):
    registry = ProviderRegistry()
    fake = MagicMock()
    fake.provider_name = "openai"
    fake.with_model = MagicMock(return_value=fake)
    fake.complete = AsyncMock(side_effect=complete_side_effect)
    registry._providers["openai"] = fake
    return registry, fake


async def _run(registry):
    from app.agents.debate.multi_model_debate import MultiModelDebateEngine
    from app.core.memory_bus import MemoryBus

    engine = MultiModelDebateEngine(registry=registry, bus=MemoryBus(), max_rounds=1)
    return await engine.run_debate(
        symbol="PM-x.POLY", action="BUY",
        signal_data={"strength": 0.02, "target_weight": 0.0125},
    )


@pytest.mark.asyncio
async def test_rate_limited_debate_is_inconclusive_not_rejected(monkeypatch):
    """A 429 storm must not read as a considered rejection."""
    import app.agents.debate.multi_model_debate as mmd

    monkeypatch.setattr(mmd, "_RATE_LIMIT_RETRIES", 0)
    registry, _ = _registry_with(Exception("Error code: 429 - rate limit reached"))

    result = await _run(registry)

    assert result.decision == "INCONCLUSIVE"
    assert result.error_count == 4
    assert result.abstain_count == 0, "an error is not an abstention"
    assert result.consensus_score == 0.0


@pytest.mark.asyncio
async def test_errors_excluded_from_consensus(monkeypatch):
    """One live FOR vote plus three failures should still approve."""
    import app.agents.debate.multi_model_debate as mmd

    monkeypatch.setattr(mmd, "_RATE_LIMIT_RETRIES", 0)
    calls = {"n": 0}

    async def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"argument": "Good trade.", "vote": "FOR", "confidence": 0.9}'
        raise Exception("Error code: 429 - rate limit reached")

    registry, _ = _registry_with(flaky)
    result = await _run(registry)

    assert result.error_count == 3
    assert result.for_count == 1
    assert result.consensus_score == 1.0
    assert result.decision == "APPROVED"


@pytest.mark.asyncio
async def test_rate_limit_is_retried(monkeypatch):
    """Transient 429s are retried before the debater is written off."""
    import app.agents.debate.multi_model_debate as mmd

    monkeypatch.setattr(mmd, "_RATE_LIMIT_RETRIES", 1)
    monkeypatch.setattr(mmd, "_RATE_LIMIT_BASE_DELAY", 0.0)
    monkeypatch.setattr(mmd, "_RATE_LIMIT_MAX_DELAY", 0.0)

    # Debaters run concurrently, so fail the FIRST attempt per role rather than
    # every other global call.
    seen: set[str] = set()

    async def once_limited(system_prompt=None, **_kwargs):
        key = str(system_prompt)
        if key not in seen:
            seen.add(key)
            raise Exception("Error code: 429 - rate limit reached, try again in 10ms")
        return '{"argument": "ok", "vote": "FOR", "confidence": 0.8}'

    registry, _ = _registry_with(once_limited)
    result = await _run(registry)

    assert result.error_count == 0, "retry should rescue every debater"
    assert result.for_count == 4


@pytest.mark.asyncio
async def test_debate_model_override_applied(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "debate_model", "gpt-4o-mini", raising=False)
    registry, fake = _registry_with(
        lambda *a, **k: '{"argument": "ok", "vote": "FOR", "confidence": 0.8}'
    )
    fake.complete = AsyncMock(
        return_value='{"argument": "ok", "vote": "FOR", "confidence": 0.8}'
    )

    await _run(registry)
    fake.with_model.assert_called_with("gpt-4o-mini")


def test_rate_limit_delay_honours_provider_hint():
    from app.agents.debate.multi_model_debate import _rate_limit_delay

    assert _rate_limit_delay(Exception("try again in 1.5s"), 0) == pytest.approx(1.75)
    assert _rate_limit_delay(Exception("try again in 200ms"), 0) == pytest.approx(0.5)
    # No hint -> exponential backoff.
    assert _rate_limit_delay(Exception("boom"), 1) == pytest.approx(4.0)
