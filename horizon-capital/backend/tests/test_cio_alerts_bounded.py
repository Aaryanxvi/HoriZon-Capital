"""CIO alert buffer is bounded."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_alerts_bounded_to_256():
    from app.agents.executive.cio.cio_agent import CIOAgent
    from app.core.messaging import AgentMessage, MessageType

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    for i in range(1000):
        msg = AgentMessage(
            sender_id="risk",
            channel="horizon.risk.metrics",
            message_type=MessageType.RISK_ALERT,
            payload={"action": "METRICS_UPDATE", "i": i},
        )
        await agent.on_message(msg)

    assert len(agent._alerts) <= 256
    assert agent._alerts[-1]["i"] == 999
