# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-2AD892A10399
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""CIO Mode B fires on HIGH and CRITICAL severities."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_mode_b_fires_on_critical_severity():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.alert",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "CRITICAL", "action": "BREACH", "current_drawdown": 0.18},
    )

    with patch.object(agent, "_run_mode_b", AsyncMock()) as m:
        await agent.on_message(msg)
        # Mode B is dispatched in background — check it was scheduled, not directly awaited
        assert m.call_count == 1


@pytest.mark.asyncio
async def test_mode_b_fires_on_high_severity():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.alert",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "HIGH", "action": "BREACH"},
    )

    with patch.object(agent, "_run_mode_b", AsyncMock()) as m:
        await agent.on_message(msg)
        # Mode B is dispatched in background — check it was scheduled, not directly awaited
        assert m.call_count == 1


@pytest.mark.asyncio
async def test_mode_b_legacy_emergency_alias_still_routes():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.alert",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "EMERGENCY", "action": "KILL_SWITCH_TRIGGERED"},
    )

    with patch.object(agent, "_run_mode_b", AsyncMock()) as m:
        await agent.on_message(msg)
        # Mode B is dispatched in background — check it was scheduled, not directly awaited
        assert m.call_count == 1


@pytest.mark.asyncio
async def test_mode_b_does_not_fire_on_metrics_update():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.metrics",
        message_type=MessageType.RISK_ALERT,
        payload={"action": "METRICS_UPDATE", "var_95": 0.01},
    )

    with patch.object(agent, "_run_mode_b", AsyncMock()) as m:
        await agent.on_message(msg)
        m.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_clears_on_explicit_clear_message():
    from unittest.mock import patch

    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._kill_switch_active = True

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.alert",
        message_type=MessageType.RISK_ALERT,
        payload={"action": "KILL_SWITCH_CLEARED"},
    )
    with patch.object(agent, "_run_mode_b", AsyncMock()):
        await agent.on_message(msg)

    assert agent._kill_switch_active is False


@pytest.mark.asyncio
async def test_mode_b_does_not_block_on_message():
    import asyncio

    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    async def slow_mode_b(*a, **kw):
        await asyncio.sleep(0.5)
    agent._run_mode_b = slow_mode_b

    msg = AgentMessage(
        sender_id="risk",
        channel="horizon.risk.alert",
        message_type=MessageType.RISK_ALERT,
        payload={"severity": "HIGH", "action": "BREACH"},
    )
    start = asyncio.get_event_loop().time()
    await agent.on_message(msg)
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.1, f"on_message blocked for {elapsed:.2f}s"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 2AD892A10399 - verify with scripts/authorship.py verify
