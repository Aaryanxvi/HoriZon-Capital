"""Tests for honest-paper-trading plan (2026-04-26)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_cash_module_round_trip():
    """set_cash then get_cash returns the value via the same session."""
    from app.core.cash import get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 123_456.78)
        await session.commit()

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(123_456.78)


@pytest.mark.asyncio
async def test_cash_module_atomic_with_caller_session():
    """If caller rolls back, set_cash effect must not persist."""
    from app.core.cash import get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 999_999.0)
        await session.commit()

    async with local_session_factory() as session:
        await set_cash(session, "USD", 1.0)
        await session.rollback()

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(999_999.0), "rollback did not undo set_cash"


@pytest.mark.asyncio
async def test_adjust_cash_returns_new_total_and_persists():
    """adjust_cash applies the delta atomically and returns the new total."""
    from app.core.cash import adjust_cash, get_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 1_000.0)
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "USD", 250.0)
        await session.commit()
    assert new_total == pytest.approx(1_250.0)

    async with local_session_factory() as session:
        amount = await get_cash(session, "USD")
    assert amount == pytest.approx(1_250.0)


@pytest.mark.asyncio
async def test_adjust_cash_negative_delta():
    """A negative delta correctly deducts."""
    from app.core.cash import adjust_cash, set_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await set_cash(session, "USD", 5_000.0)
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "USD", -1_500.0)
        await session.commit()
    assert new_total == pytest.approx(3_500.0)


@pytest.mark.asyncio
async def test_adjust_cash_inserts_when_row_missing():
    """If no row exists for the currency, adjust_cash inserts at exactly delta.

    This documents (and pins) the contract that callers must seed before they
    expect ``adjust_cash`` to deduct from an existing balance.
    """
    from sqlalchemy import text

    from app.core.cash import adjust_cash, get_cash
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as session:
        await session.execute(text("DELETE FROM cash_balances WHERE currency = 'INR'"))
        await session.commit()

    async with local_session_factory() as session:
        new_total = await adjust_cash(session, "INR", 999.0)
        await session.commit()
    assert new_total == pytest.approx(999.0)

    async with local_session_factory() as session:
        amount = await get_cash(session, "INR")
    assert amount == pytest.approx(999.0)


@pytest.mark.asyncio
async def test_order_manager_uses_shared_session():
    """When given a session, OrderManager must not commit; rollback undoes all writes."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    async with local_session_factory() as session:
        order = await om.create_order(
            {
                "symbol": "AAPL",
                "exchange": "",
                "order_type": "MARKET",
                "side": "BUY",
                "quantity": 10,
                "broker": "PAPER",
                "mode": "PAPER_TRADING",
            },
            session=session,
        )
        await session.rollback()

    async with local_session_factory() as session:
        result = await session.execute(
            text("SELECT 1 FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )
        row = result.fetchone()
    assert row is None, "rolled-back order should not persist"


@pytest.mark.asyncio
async def test_record_fill_shared_session_rolls_back():
    """record_fill on a caller-owned session must not persist after rollback."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    # Seed an order so record_fill has something to attach to.
    order = await om.create_order({
        "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING",
    })

    async with local_session_factory() as session:
        fill = await om.record_fill(
            order_id=order["id"], qty=10, price=150.0,
            commission=0.5, slippage=0.0, session=session,
        )
        await session.rollback()

    async with local_session_factory() as session:
        result = await session.execute(
            text("SELECT 1 FROM fills WHERE id = :id"),
            {"id": fill["fill_id"]},
        )
    assert result.fetchone() is None, "rolled-back fill should not persist"


@pytest.mark.asyncio
async def test_update_status_shared_session_rolls_back():
    """update_status on a caller-owned session must not persist after rollback."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    order = await om.create_order({
        "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING",
    })

    async with local_session_factory() as session:
        ok = await om.update_status(order["id"], "OPEN", session=session)
        assert ok is True
        await session.rollback()

    async with local_session_factory() as session:
        result = await session.execute(
            text("SELECT status FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )
        row = result.fetchone()
    assert row.status == "PENDING", f"expected PENDING after rollback, got {row.status}"


@pytest.mark.asyncio
async def test_update_position_shared_session_rolls_back():
    """update_position on a caller-owned session must not persist after rollback."""
    from sqlalchemy import text

    from app.agents.front_office.trading.order_manager import OrderManager
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    om = OrderManager()

    async with local_session_factory() as session:
        await om.update_position(
            symbol="ROLLBACK_TEST", exchange="", side="BUY",
            qty=10, price=100.0, session=session,
        )
        await session.rollback()

    async with local_session_factory() as session:
        result = await session.execute(
            text("SELECT 1 FROM positions WHERE symbol = :sym"),
            {"sym": "ROLLBACK_TEST"},
        )
    assert result.fetchone() is None, "rolled-back position should not persist"


@pytest.mark.asyncio
async def test_two_concurrent_buys_cash_correct():
    """Two parallel BUY fills must deduct exactly cost_a + cost_b from cash, no race."""
    import asyncio as _asyncio

    from sqlalchemy import text

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
        await set_cash(s, "USD", 1_000_000.0)
        await s.commit()

    kv = get_kv_store()
    await kv.set("horizon:price:AAPL", "150.0")
    await kv.set("horizon:price:MSFT", "300.0")

    bus = MemoryBus()
    agent = ExecutionAgent(bus)

    order_a = await agent.order_manager.create_order({
        "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 100, "broker": "PAPER",
        "mode": "PAPER_TRADING",
    })
    order_b = await agent.order_manager.create_order({
        "symbol": "MSFT", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 50, "broker": "PAPER",
        "mode": "PAPER_TRADING",
    })

    await _asyncio.gather(
        agent._execute_order(order_a),
        agent._execute_order(order_b),
    )

    async with local_session_factory() as s:
        cash = await get_cash(s, "USD")

    expected_max = 1_000_000.0 - (100 * 150 + 50 * 300)  # 985_000 ignoring slippage
    assert cash <= expected_max, (
        f"cash {cash} not deducted enough — race likely (expected <= {expected_max})"
    )
    # Allow up to 3% headroom for impact + commission + Gaussian noise.
    assert cash >= expected_max * 0.97, (
        f"cash {cash} deducted too much (expected >= {expected_max * 0.97})"
    )


@pytest.mark.asyncio
async def test_atomic_fill_rolls_back_all_four_mutations_on_failure():
    """If update_position raises mid-transaction, fill/status/cash all rollback."""
    from sqlalchemy import text

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
        await set_cash(s, "USD", 500_000.0)
        await s.commit()

    kv = get_kv_store()
    await kv.set("horizon:price:AAPL", "200.0")

    bus = MemoryBus()
    agent = ExecutionAgent(bus)

    order = await agent.order_manager.create_order({
        "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "PAPER",
        "mode": "PAPER_TRADING",
    })

    # Force update_position to raise mid-transaction.
    original_update_position = agent.order_manager.update_position

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated update_position failure")

    agent.order_manager.update_position = boom

    try:
        with pytest.raises(RuntimeError, match="simulated"):
            await agent._execute_order(order)
    finally:
        agent.order_manager.update_position = original_update_position

    # Verify all four mutations rolled back.
    async with local_session_factory() as s:
        result = await s.execute(
            text("SELECT 1 FROM fills WHERE order_id = :id"),
            {"id": order["id"]},
        )
        assert result.fetchone() is None, "fill row should not persist"

        result = await s.execute(
            text("SELECT status FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )
        row = result.fetchone()
        # Status should still be OPEN (set BEFORE the atomic transaction starts);
        # only fill/position/cash are inside the atomic block.
        assert row is not None and row.status == "OPEN", (
            f"order status changed unexpectedly to {row.status if row else None}"
        )

        result = await s.execute(
            text("SELECT 1 FROM positions WHERE symbol = 'AAPL'"),
        )
        assert result.fetchone() is None, "position should not persist"

        cash = await get_cash(s, "USD")
    assert cash == pytest.approx(500_000.0), f"cash deducted on failure: {cash}"


@pytest.mark.asyncio
async def test_handle_new_order_rejects_on_atomic_failure():
    """If _execute_order raises, _handle_new_order must REJECT the order."""
    from sqlalchemy import text

    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.memory_bus import MemoryBus
    from app.core.messaging import AgentMessage, MessageType

    await init_local_db()
    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions"))
        await s.execute(text("DELETE FROM orders"))
        await s.execute(text("DELETE FROM fills"))
        await set_cash(s, "USD", 500_000.0)
        await s.commit()

    kv = get_kv_store()
    await kv.set("horizon:price:AAPL", "200.0")

    bus = MemoryBus()
    agent = ExecutionAgent(bus)

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated update_position failure")

    agent.order_manager.update_position = boom

    msg = AgentMessage(
        sender_id="test",
        channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={
            "symbol": "AAPL", "exchange": "", "order_type": "MARKET",
            "side": "BUY", "quantity": 10,
        },
    )

    # Should NOT raise — _handle_new_order swallows + emits REJECTED.
    await agent._handle_new_order(msg)

    async with local_session_factory() as s:
        result = await s.execute(
            text(
                "SELECT status, rejection_reason FROM orders"
                " WHERE symbol = 'AAPL' ORDER BY created_at DESC LIMIT 1"
            ),
        )
        row = result.fetchone()
    assert row is not None
    assert row.status == "REJECTED", f"expected REJECTED, got {row.status}"
    assert "Atomic fill rollback" in (row.rejection_reason or "")
