"""ExecutionAgent halts further orders on CIO_OVERRIDE HALT."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_bus():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.mark.asyncio
async def test_execution_subscribes_to_cio_override():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    bus = _make_bus()
    agent = ExecutionAgent(bus=bus)
    await agent._subscribe()

    channels = [c.args[0] for c in bus.subscribe.await_args_list]
    assert "horizon.executive.cio" in channels


@pytest.mark.asyncio
async def test_cio_halt_blocks_new_orders():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = _make_bus()
    agent = ExecutionAgent(bus=bus)

    halt_msg = AgentMessage(
        sender_id="cio",
        channel="horizon.executive.cio",
        message_type=MessageType.CIO_OVERRIDE,
        payload={"override_id": "ov-1", "actions": ["HALT"], "confidence": 0.9},
    )
    await agent.on_message(halt_msg)
    assert agent._cio_halt_active is True

    new_order = AgentMessage(
        sender_id="portfolio",
        channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"order_id": "ord-1", "symbol": "AAPL"},
    )
    with patch.object(agent, "_handle_new_order", AsyncMock()) as m:
        await agent.on_message(new_order)
        m.assert_not_awaited()


@pytest.mark.asyncio
async def test_cio_resume_clears_halt():
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = _make_bus()
    agent = ExecutionAgent(bus=bus)
    agent._cio_halt_active = True

    resume_msg = AgentMessage(
        sender_id="cio",
        channel="horizon.executive.cio",
        message_type=MessageType.CIO_OVERRIDE,
        payload={"override_id": "ov-2", "actions": ["RESUME"], "confidence": 1.0},
    )
    await agent.on_message(resume_msg)
    assert agent._cio_halt_active is False
