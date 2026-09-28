# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-FC22AF916D5A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Trade journal: fills, kill-switch alerts, and debate conclusions get
narrative markdown lines appended to a daily file.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"

from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType
from app.services.trade_journal import TradeJournal


def _today_file(journal_dir):
    from datetime import UTC, datetime

    return journal_dir / f"{datetime.now(UTC):%Y-%m-%d}.md"


@pytest.mark.asyncio
async def test_fill_creates_file_with_header_and_line(tmp_path):
    bus = MemoryBus()
    await bus.start_listening()
    journal = TradeJournal(bus=bus, journal_dir=tmp_path)
    await journal.start()

    await bus.publish(
        AgentMessage(
            sender_id="execution-agent",
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": "order-1",
                "symbol": "AAPL.NASDAQ",
                "side": "BUY",
                "filled_qty": 10.5,
                "fill_price": 189.23,
                "broker": "alpaca",
            },
        )
    )
    await asyncio.sleep(0.2)

    path = _today_file(tmp_path)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Trade Journal")
    assert "FILLED BUY 10.5 AAPL.NASDAQ" in content
    assert "189.23" in content
    await bus.stop()


@pytest.mark.asyncio
async def test_kill_switch_journaled_other_risk_alert_not(tmp_path):
    bus = MemoryBus()
    await bus.start_listening()
    journal = TradeJournal(bus=bus, journal_dir=tmp_path)
    await journal.start()

    await bus.publish(
        AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.alert",
            message_type=MessageType.RISK_ALERT,
            payload={"alert_type": "DRAWDOWN_WARNING", "current_drawdown": 4.0},
        )
    )
    await bus.publish(
        AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.alert",
            message_type=MessageType.RISK_ALERT,
            payload={
                "action": "KILL_SWITCH_TRIGGERED",
                "current_drawdown": 0.1234,
                "limit": 15.0,
            },
        )
    )
    await asyncio.sleep(0.2)

    content = _today_file(tmp_path).read_text(encoding="utf-8")
    assert "KILL SWITCH" in content
    assert "12.34%" in content
    assert "15.0% limit" in content
    assert content.count("- **") == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_debate_rejected_journaled_debounced_not(tmp_path):
    bus = MemoryBus()
    await bus.start_listening()
    journal = TradeJournal(bus=bus, journal_dir=tmp_path)
    await journal.start()

    await bus.publish(
        AgentMessage(
            sender_id="debate-agent",
            channel="horizon.debate.AAPL.NASDAQ",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={
                "symbol": "AAPL.NASDAQ",
                "decision": "REJECTED",
                "reason": "weak consensus",
            },
        )
    )
    await bus.publish(
        AgentMessage(
            sender_id="debate-agent",
            channel="horizon.debate.AAPL.NASDAQ",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={"symbol": "AAPL.NASDAQ", "decision": "DEBOUNCED"},
        )
    )
    await asyncio.sleep(0.2)

    content = _today_file(tmp_path).read_text(encoding="utf-8")
    assert "Debate REJECTED for AAPL.NASDAQ — weak consensus" in content
    assert content.count("- **") == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_two_events_same_day_single_file_two_bullets(tmp_path):
    bus = MemoryBus()
    await bus.start_listening()
    journal = TradeJournal(bus=bus, journal_dir=tmp_path)
    await journal.start()

    await bus.publish(
        AgentMessage(
            sender_id="execution-agent",
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={"symbol": "MSFT.NASDAQ", "side": "SELL", "filled_qty": 2, "fill_price": 400.0},
        )
    )
    await bus.publish(
        AgentMessage(
            sender_id="debate-agent",
            channel="horizon.debate.MSFT.NASDAQ",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={"symbol": "MSFT.NASDAQ", "decision": "APPROVED"},
        )
    )
    await asyncio.sleep(0.2)

    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert content.count("# Trade Journal") == 1
    assert content.count("- **") == 2
    await bus.stop()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token FC22AF916D5A - verify with scripts/authorship.py verify
