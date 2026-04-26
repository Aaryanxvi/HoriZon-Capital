"""Tests for the CIO agent (Modes A, B, C)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


def _make_provider(response: str):
    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(return_value=response)
    return provider


ADVISORY_RESPONSE = json.dumps({
    "outlook": "neutral",
    "summary": "Portfolio is balanced with moderate risk exposure.",
    "recommended_adjustments": [],
    "risk_flags": [],
})

CRISIS_RESPONSE = json.dumps({
    "stance": "REDUCE",
    "confidence": 0.75,
    "reasoning": "Elevated risk detected, recommend reducing exposure.",
    "specific_actions": ["Reduce equity allocation by 10%"],
})

CRISIS_HALT_RESPONSE = json.dumps({
    "stance": "HALT",
    "confidence": 0.90,
    "reasoning": "Systemic crisis detected, immediate halt required.",
    "specific_actions": ["Halt all trading", "Liquidate risky positions"],
})


@pytest.mark.asyncio
async def test_cio_mode_a_publishes_advisory():
    """Mode A: CIO publishes CIO_ADVISORY message with structured outlook."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    provider = _make_provider(ADVISORY_RESPONSE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider

        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={"nav": 1000000.0})):
            await agent._run_mode_a()

    calls = bus.publish.call_args_list
    assert any(
        call.args[0].message_type == MessageType.CIO_ADVISORY
        for call in calls
    )


@pytest.mark.asyncio
async def test_cio_mode_a_silent_without_provider():
    """Mode A: CIO does nothing when no LLM provider is configured."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = []
        await agent._run_mode_a()

    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cio_mode_a_handles_llm_error_gracefully():
    """Mode A: LLM error does not crash the agent."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(side_effect=RuntimeError("API error"))

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={})):
            await agent._run_mode_a()  # Should not raise

    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cio_mode_a_parses_advisory_json():
    """Mode A: Advisory payload contains parsed outlook/summary fields."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    provider = _make_provider(ADVISORY_RESPONSE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={"nav": 500000.0})):
            await agent._run_mode_a()

    advisory_calls = [
        c for c in bus.publish.call_args_list
        if c.args[0].message_type == MessageType.CIO_ADVISORY
    ]
    assert len(advisory_calls) == 1
    payload = advisory_calls[0].args[0].payload
    assert payload["outlook"] == "neutral"
    assert "balanced" in payload["summary"]


@pytest.mark.asyncio
async def test_cio_mode_b_publishes_crisis_advisory():
    """Mode B: Crisis response publishes CIO_ADVISORY with is_crisis=True."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    provider = _make_provider(CRISIS_RESPONSE)

    trigger_payload = {"severity": "CRITICAL", "message": "VaR breach"}

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={"nav": 800000.0})):
            await agent._run_mode_b(trigger_payload, trigger="RISK_ALERT")

    advisory_calls = [
        c for c in bus.publish.call_args_list
        if c.args[0].message_type == MessageType.CIO_ADVISORY
    ]
    assert len(advisory_calls) >= 1
    payload = advisory_calls[0].args[0].payload
    assert payload["is_crisis"] is True
    assert payload["stance"] == "REDUCE"


@pytest.mark.asyncio
async def test_cio_mode_b_no_provider_no_crash():
    """Mode B: No provider available does not crash."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = []
        await agent._run_mode_b({"severity": "HIGH"}, trigger="RISK_ALERT")

    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_cio_mode_c_triggered_on_halt_with_high_confidence():
    """Mode C: Override published when kill switch active + HALT + confidence >= threshold."""
    from app.agents.executive.cio.cio_agent import CIO_OVERRIDE_CONFIDENCE_THRESHOLD, CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True
    agent._kill_switch_active = True

    provider = _make_provider(CRISIS_HALT_RESPONSE)

    trigger_payload = {"severity": "CRITICAL", "action": "KILL_SWITCH_TRIGGERED"}

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={"nav": 800000.0})):
            await agent._run_mode_b(trigger_payload, trigger="KILL_SWITCH")

    override_calls = [
        c for c in bus.publish.call_args_list
        if c.args[0].message_type == MessageType.CIO_OVERRIDE
    ]
    assert len(override_calls) == 1
    payload = override_calls[0].args[0].payload
    assert payload["confidence"] >= CIO_OVERRIDE_CONFIDENCE_THRESHOLD
    assert "HALT" in payload["actions"] or any("halt" in a.lower() for a in payload["actions"])


@pytest.mark.asyncio
async def test_cio_mode_c_not_triggered_below_confidence():
    """Mode C: Override NOT published when confidence is below threshold."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True
    agent._kill_switch_active = True

    # Low confidence crisis response
    low_conf = json.dumps({
        "stance": "HALT",
        "confidence": 0.50,
        "reasoning": "Uncertain situation.",
        "specific_actions": ["Monitor closely"],
    })
    provider = _make_provider(low_conf)

    trigger_payload = {"severity": "CRITICAL", "action": "KILL_SWITCH_TRIGGERED"}

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={"nav": 800000.0})):
            await agent._run_mode_b(trigger_payload, trigger="KILL_SWITCH")

    override_calls = [
        c for c in bus.publish.call_args_list
        if c.args[0].message_type == MessageType.CIO_OVERRIDE
    ]
    assert len(override_calls) == 0


@pytest.mark.asyncio
async def test_cio_on_message_risk_alert():
    """on_message: RISK_ALERT with HIGH severity triggers Mode B."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk-agent",
        channel="horizon.risk.alerts",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "HIGH", "message": "Drawdown limit approaching"},
    )

    with patch.object(agent, "_run_mode_b", new_callable=AsyncMock) as mock_b:
        await agent.on_message(msg)
        mock_b.assert_called_once()


@pytest.mark.asyncio
async def test_cio_on_message_kill_switch():
    """on_message: RISK_ALERT with KILL_SWITCH action activates kill switch and triggers B."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk-agent",
        channel="horizon.risk.alerts",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "CRITICAL", "action": "KILL_SWITCH_TRIGGERED"},
    )

    with patch.object(agent, "_run_mode_b", new_callable=AsyncMock) as mock_b:
        await agent.on_message(msg)
        assert agent._kill_switch_active is True
        mock_b.assert_called_once()


@pytest.mark.asyncio
async def test_cio_circuit_breaker_opens_after_failures():
    """Circuit breaker opens after N consecutive LLM failures."""
    from app.agents.executive.cio.cio_agent import (
        CIO_CIRCUIT_BREAKER_FAILURES,
        CIOAgent,
    )

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    # Simulate failures up to the threshold
    for _ in range(CIO_CIRCUIT_BREAKER_FAILURES):
        agent._record_failure()

    assert agent._llm_circuit_open_until > 0


@pytest.mark.asyncio
async def test_cio_circuit_breaker_resets_on_success():
    """Circuit breaker resets after a successful LLM call."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._llm_failures = 2
    agent._llm_circuit_open_until = 999999999999.0

    agent._reset_circuit_breaker()

    assert agent._llm_failures == 0
    assert agent._llm_circuit_open_until == 0


@pytest.mark.asyncio
async def test_cio_get_last_override():
    """get_last_override returns the most recent override."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    assert agent.get_last_override() is None

    override = {"actions": ["HALT"], "confidence": 0.9}
    agent._last_override = override

    assert agent.get_last_override() == override


@pytest.mark.asyncio
async def test_cio_set_halt_confirmed():
    """set_halt_confirmed clears the pending halt flag."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._pending_halt_confirmation = True

    await agent.set_halt_confirmed()

    assert agent._pending_halt_confirmation is False


@pytest.mark.asyncio
async def test_cio_subscribe():
    """CIO subscribes to risk and settings channels."""
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    await agent._subscribe()

    channels = [call.args[0] for call in bus.subscribe.call_args_list]
    assert "horizon.risk.*" in channels


# ---------------------------------------------------------------------------
# Additional Mode B / C / circuit-breaker tests
# ---------------------------------------------------------------------------

CRISIS_HOLD_RESPONSE = json.dumps({
    "stance": "HOLD",
    "confidence": 0.6,
    "reasoning": "Drawdown is concerning but within limits. Monitor.",
    "specific_actions": [],
})

CRISIS_HALT_HIGH_CONFIDENCE = json.dumps({
    "stance": "HALT",
    "confidence": 0.92,
    "reasoning": "Kill switch triggered. Systemic risk detected. Halt all trading.",
    "specific_actions": [{"symbol": "AAPL", "action": "close", "urgency": "immediate", "pct": 100}],
})

CRISIS_HALT_LOW_CONFIDENCE = json.dumps({
    "stance": "HALT",
    "confidence": 0.70,
    "reasoning": "Uncertain situation.",
    "specific_actions": [],
})


@pytest.mark.asyncio
async def test_cio_mode_c_fires_when_kill_switch_and_high_confidence():
    """Mode C fires when kill switch is active AND confidence >= threshold."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True
    provider = _make_provider(CRISIS_HALT_HIGH_CONFIDENCE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={})):
            with patch.object(agent, "_persist_override", AsyncMock()):
                await agent._run_mode_b({"action": "KILL_SWITCH_TRIGGERED"}, trigger="kill_switch")

    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert any(c.message_type == MessageType.CIO_OVERRIDE for c in calls)


@pytest.mark.asyncio
async def test_cio_mode_c_does_not_fire_below_confidence_threshold():
    """Mode C does NOT fire when confidence is below threshold, even with kill switch."""
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = _make_bus()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True
    provider = _make_provider(CRISIS_HALT_LOW_CONFIDENCE)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={})):
            await agent._run_mode_b({"action": "KILL_SWITCH_TRIGGERED"}, trigger="kill_switch")

    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert not any(c.message_type == MessageType.CIO_OVERRIDE for c in calls)


@pytest.mark.asyncio
async def test_cio_circuit_breaker_silences_after_failures():
    """After 3 LLM failures via _run_mode_a, CIO circuit opens (llm_circuit_open_until > 0)."""
    from app.agents.executive.cio.cio_agent import CIO_CIRCUIT_BREAKER_FAILURES, CIOAgent

    bus = _make_bus()
    agent = CIOAgent(bus=bus)

    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(side_effect=RuntimeError("LLM error"))

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as mock_reg:
        mock_reg.get_providers_for_department.return_value = [provider]
        mock_reg.get_provider_for_agent.return_value = provider
        with patch.object(agent, "_build_portfolio_digest", new=AsyncMock(return_value={})):
            for _ in range(CIO_CIRCUIT_BREAKER_FAILURES):
                await agent._run_mode_a()

    assert agent._llm_circuit_open_until > 0
