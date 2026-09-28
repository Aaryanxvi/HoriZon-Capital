# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4113A3C69AAE
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""End-to-end smoke tests for the paper trading pipeline."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_happy_path_buy_fills_and_deducts_cash():
    """Full pipeline: create order → execute → verify fill, position, cash deducted."""
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash, set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.memory_bus import MemoryBus

    await init_local_db()
    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions"))
        await s.execute(text("DELETE FROM orders"))
        await s.execute(text("DELETE FROM fills"))
        await set_cash(s, "USD", 100_000.0)
        await s.commit()

    kv = get_kv_store()
    await kv.set("horizon:price:AAPL", "200.0")
    await kv.set("horizon:price:AAPL:ts", datetime.now(UTC).isoformat())

    bus = MemoryBus()
    agent = ExecutionAgent(bus)

    order = await agent.order_manager.create_order({
        "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "PAPER",
        "mode": "PAPER_TRADING",
    })

    await agent._execute_order(order)

    # Fill record exists
    async with local_session_factory() as s:
        row = await s.execute(
            text("SELECT fill_price, filled_qty FROM fills WHERE order_id = :id"),
            {"id": order["id"]},
        )
        fill_row = row.fetchone()
    assert fill_row is not None, "fill record missing"
    assert fill_row.filled_qty == 10.0
    assert fill_row.fill_price >= 200.0, "BUY fill price should be >= mid (noise clamped)"

    # Position created
    async with local_session_factory() as s:
        row = await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL'"),
        )
        pos_row = row.fetchone()
    assert pos_row is not None, "position missing"
    assert pos_row.quantity == 10.0

    # Cash deducted (should be less than 100k)
    async with local_session_factory() as s:
        cash = await get_cash(s, "USD")
    assert cash < 100_000.0, "cash not deducted"
    # Should have deducted roughly 200 * 10 = 2000 + slippage/commission
    assert cash > 90_000.0, f"cash deducted too much: {cash}"


@pytest.mark.asyncio
async def test_limit_buy_rejected_smoke():
    """Limit BUY rejected when market price is above limit — guard rail check."""
    from app.agents.front_office.trading.paper_broker import PaperBroker
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()
    await kv.set("horizon:price:MSFT", "300.0")
    await kv.set("horizon:price:MSFT:ts", datetime.now(UTC).isoformat())

    broker = PaperBroker()
    fill = await broker.execute({
        "id": "e2e-limit-1", "symbol": "MSFT", "side": "BUY",
        "quantity": 5, "limit_price": 250.0,
    })
    assert fill.get("rejected") is True
    assert "not reachable" in fill.get("rejection_reason", "")


@pytest.mark.asyncio
async def test_stale_price_rejected_smoke():
    """Order rejected when price timestamp is > 5 minutes old — guard rail check."""
    from datetime import timedelta

    from app.agents.front_office.trading.paper_broker import PaperBroker
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()
    # Use .NSE symbol so Alpaca (US-only feed) is bypassed; KV staleness is sole gatekeeper.
    await kv.set("horizon:price:RELIANCE.NSE", "2800.0")
    stale = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    await kv.set("horizon:price:RELIANCE.NSE:ts", stale)

    broker = PaperBroker()
    fill = await broker.execute({
        "id": "e2e-stale-1", "symbol": "RELIANCE.NSE", "side": "BUY", "quantity": 1,
    })
    assert fill.get("rejected") is True
    assert "No price available" in fill.get("rejection_reason", "")


@pytest.mark.asyncio
async def test_atomic_rollback_on_failure_smoke():
    """If execution fails mid-way, cash and fill records roll back cleanly."""
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash, set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.memory_bus import MemoryBus

    await init_local_db()
    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions WHERE symbol = 'NVDA'"))
        await s.execute(text(
            "DELETE FROM fills"
            " WHERE order_id IN (SELECT id FROM orders WHERE symbol = 'NVDA')"
        ))
        await s.execute(text("DELETE FROM orders WHERE symbol = 'NVDA'"))
        await set_cash(s, "USD", 50_000.0)
        await s.commit()

    kv = get_kv_store()
    await kv.set("horizon:price:NVDA", "500.0")
    await kv.set("horizon:price:NVDA:ts", datetime.now(UTC).isoformat())

    bus = MemoryBus()
    agent = ExecutionAgent(bus)

    order = await agent.order_manager.create_order({
        "symbol": "NVDA", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 5, "broker": "PAPER",
        "mode": "PAPER_TRADING",
    })

    # Inject failure mid-transaction
    original = agent.order_manager.update_position
    async def boom(*a, **kw):
        raise RuntimeError("injected failure")
    agent.order_manager.update_position = boom

    try:
        with pytest.raises(RuntimeError):
            await agent._execute_order(order)
    finally:
        agent.order_manager.update_position = original

    async with local_session_factory() as s:
        row = await s.execute(
            text("SELECT 1 FROM fills WHERE order_id = :id"), {"id": order["id"]}
        )
        assert row.fetchone() is None, "fill persisted after rollback"
        cash = await get_cash(s, "USD")
    assert cash == pytest.approx(50_000.0), f"cash corrupted: {cash}"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4113A3C69AAE - verify with scripts/authorship.py verify
