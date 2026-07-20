"""Alert pipeline wiring: bus subscriptions must match real publishers.

Covers the rewire from dead channels (horizon.risk.kill_switch,
horizon.debate.conclusion, horizon.trade.executed) to the channels agents
actually emit on, plus the SQLite busy_timeout pragma.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"

from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType
from app.services.alert_manager import AlertManager


@pytest.mark.asyncio
async def test_fill_triggers_trade_alert():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    await bus.publish(
        AgentMessage(
            sender_id="execution-agent",
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": "order-1",
                "symbol": "AAPL.NASDAQ",
                "side": "BUY",
                "filled_qty": 1000,
                "fill_price": 200.0,
                "commission": 1.0,
                "slippage": 0.0,
                "broker": "paper",
                "status": "FILLED",
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(a["rule_name"] == "large_trade" for a in alerts)
    await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_marker_routes_to_kill_rule():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    await bus.publish(
        AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.alert",
            message_type=MessageType.RISK_ALERT,
            payload={
                "action": "KILL_SWITCH_TRIGGERED",
                "severity": "CRITICAL",
                "current_drawdown": 0.12,
                "limit": 10.0,
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(a["rule_name"] == "kill_switch_activated" for a in alerts)
    assert not any(a["rule_name"] == "drawdown_critical" for a in alerts)
    await bus.stop()


@pytest.mark.asyncio
async def test_debate_conclusion_subscription_matches_real_channel():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    await bus.publish(
        AgentMessage(
            sender_id="debate-agent",
            channel="horizon.debate.AAPL.NASDAQ",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={
                "session_id": "sess-1",
                "symbol": "AAPL.NASDAQ",
                "decision": "REJECTED",
                "consensus_score": 0.2,
                "mode": "auto_reject",
                "reason": "test",
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(a["rule_name"] == "debate_rejection" for a in alerts)
    await bus.stop()


@pytest.mark.asyncio
async def test_heartbeat_does_not_spam_alerts():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    for _ in range(3):
        await bus.publish(
            AgentMessage(
                sender_id="test-agent",
                channel="horizon.system.health",
                message_type=MessageType.HEARTBEAT,
                payload={"agent_id": "test-agent", "agent_type": "test", "status": "RUNNING"},
            )
        )
    await asyncio.sleep(0.2)

    assert manager.get_recent_alerts() == []
    await bus.stop()


@pytest.mark.asyncio
async def test_busy_timeout_pragma():
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        result = await session.execute(text("PRAGMA busy_timeout"))
        row = result.fetchone()

    assert row[0] == 5000
