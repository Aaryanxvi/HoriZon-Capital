"""REPL `cio why` and `cio confirm halt` exercise the right CIO fields."""
from unittest.mock import AsyncMock, MagicMock

import pytest


def _stub_agent_with_override(reasoning: str):
    from app.agents.executive.cio.cio_agent import CIOAgent
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._last_override = {
        "override_id": "ov-7",
        "timestamp": "2026-04-26T00:00:00Z",
        "trigger": "KILL_SWITCH",
        "confidence": 0.92,
        "actions": ["HALT"],
        "reasoning": reasoning,
        "provider": "claude",
    }
    return agent


@pytest.mark.asyncio
async def test_cio_why_renders_reasoning_field():
    from app.tui.commands import CommandHandler

    agent = _stub_agent_with_override("Drawdown breach 18%, regime risk-off.")
    handler = CommandHandler(orchestrator=None, dashboard=None)
    handler._get_cio_agent = MagicMock(return_value=agent)

    out = await handler._cmd_cio(["why"])
    assert "Drawdown breach 18%" in out
    assert "No reasoning recorded" not in out


@pytest.mark.asyncio
async def test_cio_confirm_halt_publishes_override():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._pending_halt_confirmation = True

    await agent.set_halt_confirmed()

    assert agent._pending_halt_confirmation is False
    assert bus.publish.await_count == 1
    sent = bus.publish.await_args.args[0]
    assert sent.message_type == MessageType.CIO_OVERRIDE
    assert "HALT" in sent.payload.get("actions", [])
    assert sent.payload.get("trigger") == "MANUAL_CONFIRM"
