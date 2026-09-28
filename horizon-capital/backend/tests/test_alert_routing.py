# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-C016E4B6B9C7
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Alert routing coverage for stop-loss signals, pending-order approvals,
VaR breach alerts, and the Telegram approval command parser.
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
from app.services.telegram_approvals import TelegramApprovalWorker


@pytest.mark.asyncio
async def test_stop_loss_signal_triggers_alert():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    await bus.publish(
        AgentMessage(
            sender_id="position-monitor-worker",
            channel="horizon.signal.AAPL",
            message_type=MessageType.SIGNAL,
            payload={
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "direction": -1,
                "strength": 1.0,
                "strategy_name": "stop_loss",
                "reasoning": "Stop-loss triggered: price 100.00 <= stop 105.00",
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(
        a["rule_name"] == "stop_loss_triggered" and "Stop-loss" in a["title"]
        for a in alerts
    )
    count_before = len(alerts)

    await bus.publish(
        AgentMessage(
            sender_id="strategy-agent",
            channel="horizon.signal.MSFT",
            message_type=MessageType.SIGNAL,
            payload={
                "symbol": "MSFT",
                "exchange": "NASDAQ",
                "direction": 1,
                "strength": 0.5,
                "strategy_name": "momentum",
            },
        )
    )
    await asyncio.sleep(0.2)

    assert len(manager.get_recent_alerts()) == count_before
    await bus.stop()


@pytest.mark.asyncio
async def test_pending_order_triggers_alert():
    bus = MemoryBus()
    await bus.start_listening()
    manager = AlertManager(bus=bus)
    await manager.start()

    await bus.publish(
        AgentMessage(
            sender_id="portfolio-agent",
            channel="horizon.execution.order.pending",
            message_type=MessageType.ORDER_NEW,
            payload={
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "side": "BUY",
                "quantity": 10,
                "order_type": "MARKET",
                "signal_id": "sig-12345678",
                "stop_loss": None,
                "allocation_usd": 1000.0,
                "requires_approval": True,
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(a["rule_name"] == "order_pending_approval" for a in alerts)
    await bus.stop()


@pytest.mark.asyncio
async def test_var_breach_alert():
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
                "action": "VAR_BREACH",
                "alert_type": "VAR_BREACH",
                "var_pct": 4.5,
                "limit_pct": 3.0,
            },
        )
    )
    await asyncio.sleep(0.2)

    alerts = manager.get_recent_alerts()
    assert any(a["rule_name"] == "var_breach" for a in alerts)
    await bus.stop()


@pytest.mark.asyncio
async def test_telegram_command_parsing():
    worker = TelegramApprovalWorker(orchestrator=None)

    assert await worker._handle_command("/pending") == "Execution agent unavailable."
    assert await worker._handle_command("/approve") == "Usage: /approve <id-prefix>"
    assert await worker._handle_command("hello there") is None

    class FakeAgent:
        agent_type = "execution"

        def get_pending_approvals(self):
            return [
                {
                    "id": "abcd1234efgh",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "quantity": 10,
                    "order_type": "MARKET",
                }
            ]

        async def approve_order(self, order_id):
            return True

        async def reject_order(self, order_id):
            return True

    class FakeSlot:
        def __init__(self, agent):
            self.agent = agent

    class FakeOrchestrator:
        def __init__(self, agent):
            self._slots = {"execution-agent-1": FakeSlot(agent)}

    orchestrator = FakeOrchestrator(FakeAgent())
    worker = TelegramApprovalWorker(orchestrator=orchestrator)

    reply = await worker._handle_command("/pending")
    assert "abcd1234" in reply
    assert "AAPL" in reply

    assert await worker._handle_command("/approve abcd") == "Approved abcd."
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token C016E4B6B9C7 - verify with scripts/authorship.py verify
