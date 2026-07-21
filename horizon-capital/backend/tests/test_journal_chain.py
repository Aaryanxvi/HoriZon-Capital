"""Decision-chain resolution and trade-journal 'why' annotation tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"


async def _seed_chain(session_factory) -> None:
    from sqlalchemy import text

    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO orders "
                "(id, symbol, exchange, order_type, side, quantity, broker, mode, "
                "signal_id, debate_id, status) "
                "VALUES (:id, :symbol, :exchange, :order_type, :side, :quantity, "
                ":broker, :mode, :signal_id, :debate_id, :status)"
            ),
            {
                "id": "ord-1",
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "order_type": "MARKET",
                "side": "BUY",
                "quantity": 5.0,
                "broker": "paper",
                "mode": "PAPER_TRADING",
                "signal_id": "sig-1",
                "debate_id": "deb-1",
                "status": "FILLED",
            },
        )
        await session.execute(
            text(
                "INSERT INTO signals "
                "(signal_id, agent_id, symbol, direction, strength, confidence, "
                "strategy_name, regime, metadata, created_at) "
                "VALUES (:signal_id, :agent_id, :symbol, :direction, :strength, "
                ":confidence, :strategy_name, :regime, :metadata, :now)"
            ),
            {
                "signal_id": "sig-1",
                "agent_id": "strategy-agent-1",
                "symbol": "AAPL",
                "direction": "BUY",
                "strength": 0.8,
                "confidence": 0.8,
                "strategy_name": "research_stack",
                "regime": "RISK_ON",
                "metadata": "{}",
                "now": datetime.now(UTC),
            },
        )
        await session.execute(
            text(
                "INSERT INTO debate_sessions "
                "(id, symbol, exchange, final_decision, consensus_score, reason, created_at) "
                "VALUES (:id, :symbol, :exchange, :final_decision, :consensus_score, "
                ":reason, :now)"
            ),
            {
                "id": "deb-1",
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "final_decision": "APPROVED",
                "consensus_score": 0.9,
                "reason": "momentum strong",
                "now": datetime.now(UTC),
            },
        )
        await session.commit()


@pytest.mark.asyncio
async def test_resolve_chain_full():
    from app.core.local_storage import init_local_db, local_session_factory
    from app.services.trade_journal import resolve_decision_chain

    await init_local_db()
    await _seed_chain(local_session_factory)

    chain = await resolve_decision_chain("ord-1")

    assert chain["strategy"] == "research_stack"
    assert chain["regime"] == "RISK_ON"
    assert chain["debate_decision"] == "APPROVED"


@pytest.mark.asyncio
async def test_resolve_chain_missing_order():
    from app.core.local_storage import init_local_db
    from app.services.trade_journal import resolve_decision_chain

    await init_local_db()

    chain = await resolve_decision_chain("nope")

    assert all(v is None for v in chain.values())


@pytest.mark.asyncio
async def test_on_fill_writes_why(tmp_path, monkeypatch):
    from app.config import settings
    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.memory_bus import MemoryBus
    from app.core.messaging import AgentMessage, MessageType
    from app.services.trade_journal import TradeJournal

    monkeypatch.setattr(settings, "journal_decision_chain", True, raising=False)

    await init_local_db()
    await _seed_chain(local_session_factory)

    tj = TradeJournal(bus=MemoryBus(), journal_dir=tmp_path)
    msg = AgentMessage(
        sender_id="execution-agent-1",
        channel="horizon.execution.order.fill",
        message_type=MessageType.ORDER_FILL,
        payload={
            "order_id": "ord-1",
            "symbol": "AAPL",
            "side": "BUY",
            "filled_qty": 5,
            "fill_price": 100.0,
            "commission": 0.0,
            "slippage": 0.0,
            "broker": "paper",
            "status": "FILLED",
        },
    )

    await tj._on_fill(msg)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    content = (tmp_path / f"{today}.md").read_text(encoding="utf-8")

    assert "FILLED BUY" in content
    assert "research_stack" in content


@pytest.mark.asyncio
async def test_on_fill_chain_disabled(tmp_path, monkeypatch):
    from app.config import settings
    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.memory_bus import MemoryBus
    from app.core.messaging import AgentMessage, MessageType
    from app.services.trade_journal import TradeJournal

    monkeypatch.setattr(settings, "journal_decision_chain", False, raising=False)

    await init_local_db()
    await _seed_chain(local_session_factory)

    tj = TradeJournal(bus=MemoryBus(), journal_dir=tmp_path)
    msg = AgentMessage(
        sender_id="execution-agent-1",
        channel="horizon.execution.order.fill",
        message_type=MessageType.ORDER_FILL,
        payload={
            "order_id": "ord-1",
            "symbol": "AAPL",
            "side": "BUY",
            "filled_qty": 5,
            "fill_price": 100.0,
            "commission": 0.0,
            "slippage": 0.0,
            "broker": "paper",
            "status": "FILLED",
        },
    )

    await tj._on_fill(msg)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    content = (tmp_path / f"{today}.md").read_text(encoding="utf-8")

    assert "FILLED BUY" in content
    assert "why:" not in content


@pytest.mark.asyncio
async def test_on_fill_no_chain_single_line(tmp_path):
    from app.core.local_storage import init_local_db
    from app.core.memory_bus import MemoryBus
    from app.core.messaging import AgentMessage, MessageType
    from app.services.trade_journal import TradeJournal

    await init_local_db()

    tj = TradeJournal(bus=MemoryBus(), journal_dir=tmp_path)
    msg = AgentMessage(
        sender_id="execution-agent-1",
        channel="horizon.execution.order.fill",
        message_type=MessageType.ORDER_FILL,
        payload={
            "order_id": "unknown-ord",
            "symbol": "AAPL",
            "side": "BUY",
            "filled_qty": 5,
            "fill_price": 100.0,
            "commission": 0.0,
            "slippage": 0.0,
            "broker": "paper",
            "status": "FILLED",
        },
    )

    await tj._on_fill(msg)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    content = (tmp_path / f"{today}.md").read_text(encoding="utf-8")

    assert "FILLED BUY" in content
    assert "why:" not in content
