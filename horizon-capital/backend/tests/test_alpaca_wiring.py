"""Alpaca broker wiring: guard fallback, async fill settlement, reconciliation."""
from __future__ import annotations

import pytest

from app.agents.front_office.trading.execution_agent import ExecutionAgent, _alpaca_guard_ok
from app.core.memory_bus import MemoryBus


def _make_agent() -> ExecutionAgent:
    return ExecutionAgent(bus=MemoryBus())


def _set_alpaca_settings(
    monkeypatch, *, key="key", secret="secret", paper_mode=True,
    base_url="https://paper-api.alpaca.markets", execution_broker="ALPACA",
) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "alpaca_api_key", key, raising=False)
    monkeypatch.setattr(settings, "alpaca_api_secret", secret, raising=False)
    monkeypatch.setattr(settings, "alpaca_paper_mode", paper_mode, raising=False)
    monkeypatch.setattr(settings, "alpaca_base_url", base_url, raising=False)
    monkeypatch.setattr(settings, "execution_broker", execution_broker, raising=False)


# --------------------------------------------------------------------------- #
# Guard: PAPER fallback on any misconfiguration
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guard_fails_without_keys(monkeypatch):
    _set_alpaca_settings(monkeypatch, key="")

    assert _alpaca_guard_ok() is False
    agent = _make_agent()
    assert agent.broker_name == "PAPER"
    assert agent.broker is agent.paper_broker


@pytest.mark.asyncio
async def test_guard_fails_when_paper_mode_false(monkeypatch):
    _set_alpaca_settings(monkeypatch, paper_mode=False)

    assert _alpaca_guard_ok() is False
    agent = _make_agent()
    assert agent.broker_name == "PAPER"


@pytest.mark.asyncio
async def test_guard_fails_on_live_url(monkeypatch):
    """The hard safety net: even with valid keys + paper_mode=True, a
    non-paper-api base_url must never route live."""
    _set_alpaca_settings(monkeypatch, base_url="https://api.alpaca.markets")

    assert _alpaca_guard_ok() is False
    agent = _make_agent()
    assert agent.broker_name == "PAPER"


@pytest.mark.asyncio
async def test_guard_passes_selects_alpaca(monkeypatch):
    _set_alpaca_settings(monkeypatch)

    assert _alpaca_guard_ok() is True
    agent = _make_agent()
    assert agent.broker_name == "ALPACA"
    assert agent.broker is agent.alpaca_broker


@pytest.mark.asyncio
async def test_default_stays_paper(monkeypatch):
    """EXECUTION_BROKER defaults to PAPER regardless of alpaca settings."""
    _set_alpaca_settings(monkeypatch, execution_broker="PAPER")

    agent = _make_agent()
    assert agent.broker_name == "PAPER"
    assert agent.broker is agent.paper_broker


# --------------------------------------------------------------------------- #
# Accepted-then-filled: instant path defers, poll settles exactly once
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_accepted_then_filled_settles_once_via_poll(monkeypatch):
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)

    await init_local_db()
    agent = _make_agent()
    assert agent.broker_name == "ALPACA"

    # Seed cash so the BUY passes the cash guard.
    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM cash_balances"))
        await s.execute(
            text("INSERT INTO cash_balances (currency, amount) VALUES ('USD', 100000)")
        )
        await s.commit()

    from app.core import kv_store
    kv = kv_store.get_kv_store()
    await kv.set("horizon:price:AAPL.NASDAQ", "100.0")

    # Broker accepts but does not fill on the initial POST.
    async def fake_execute(order):
        return {
            "order_id": order.get("id", ""),
            "broker_order_id": "bo-123",
            "filled_qty": 0.0,
            "fill_price": 0.0,
            "commission": 0.0,
            "slippage": 0.0,
            "broker": "ALPACA",
            "alpaca_status": "accepted",
        }
    monkeypatch.setattr(agent.alpaca_broker, "execute", fake_execute)

    order = await agent.order_manager.create_order({
        "symbol": "AAPL.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "ALPACA", "mode": "PAPER_TRADING",
    })

    await agent._execute_order(order)

    # Still OPEN, broker_order_id persisted, no fill/position/cash yet.
    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT status, broker_order_id FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )).fetchone()
    assert row.status == "OPEN"
    assert row.broker_order_id == "bo-123"

    async with local_session_factory() as s:
        pos = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
    assert pos is None

    # Now the broker reports it filled.
    async def fake_status(broker_order_id):
        return {
            "broker_order_id": broker_order_id,
            "status": "filled",
            "filled_qty": 10.0,
            "filled_avg_price": 101.0,
            "filled_at": "2026-01-01T00:00:00Z",
        }
    monkeypatch.setattr(agent.alpaca_broker, "get_order_status", fake_status)

    await agent._poll_open_orders()

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT status FROM orders WHERE id = :id"), {"id": order["id"]},
        )).fetchone()
        pos = (await s.execute(
            text("SELECT quantity, avg_entry_price FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
        cash = (await s.execute(
            text("SELECT amount FROM cash_balances WHERE currency = 'USD'"),
        )).fetchone()

    assert row.status == "FILLED"
    assert pos.quantity == pytest.approx(10.0)
    assert pos.avg_entry_price == pytest.approx(101.0)
    assert cash.amount == pytest.approx(100000 - 10 * 101.0)

    # Second poll of the same (now-terminal) order must be a no-op — no
    # double-fill, no double cash deduction.
    await agent._poll_open_orders()

    async with local_session_factory() as s:
        pos = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
        cash = (await s.execute(
            text("SELECT amount FROM cash_balances WHERE currency = 'USD'"),
        )).fetchone()
        fills = (await s.execute(
            text("SELECT COUNT(*) AS n FROM fills WHERE order_id = :id"), {"id": order["id"]},
        )).fetchone()

    assert pos.quantity == pytest.approx(10.0)
    assert cash.amount == pytest.approx(100000 - 10 * 101.0)
    assert fills.n == 1


# --------------------------------------------------------------------------- #
# Reconciliation: mismatch reported, local positions never mutated
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_reconciliation_reports_mismatch_without_mutating_local(monkeypatch):
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)

    await init_local_db()
    agent = _make_agent()
    assert agent.broker_name == "ALPACA"

    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions WHERE symbol = 'MSFT.NASDAQ'"))
        await s.execute(text("""
            INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price, currency)
            VALUES ('pos-1', 'MSFT.NASDAQ', 'NASDAQ', 'LONG', 50, 300.0, 'USD')
        """))
        await s.commit()

    async def fake_account():
        return {"equity": 100000.0, "cash": 50000.0}
    monkeypatch.setattr(agent.alpaca_broker, "get_account", fake_account)

    async def fake_positions():
        # Broker only shows 30 shares vs local 50 — mismatch.
        return [{"symbol": "MSFT", "qty": 30.0, "avg_entry": 300.0,
                 "current_price": 305.0, "side": "LONG"}]
    monkeypatch.setattr(agent.alpaca_broker, "get_positions", fake_positions)

    alerts = []
    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        alerts.append((channel, payload))
    monkeypatch.setattr(agent, "emit", fake_emit)

    await agent._reconcile_alpaca_startup()

    risk_alerts = [p for (c, p) in alerts if p.get("reason") == "alpaca_position_mismatch"]
    assert len(risk_alerts) == 1
    assert risk_alerts[0]["mismatches"] == [
        {"symbol": "MSFT.NASDAQ", "local_qty": 50.0, "broker_qty": 30.0}
    ]

    # Local position table is untouched — reconciliation only reports.
    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'MSFT.NASDAQ'"),
        )).fetchone()
    assert row.quantity == pytest.approx(50.0)
    assert agent.broker_name == "ALPACA"  # unreachable path did not trigger


@pytest.mark.asyncio
async def test_reconciliation_falls_back_to_paper_when_unreachable(monkeypatch):
    from app.core.local_storage import init_local_db

    _set_alpaca_settings(monkeypatch)

    await init_local_db()
    agent = _make_agent()
    assert agent.broker_name == "ALPACA"

    async def fake_account():
        return None
    monkeypatch.setattr(agent.alpaca_broker, "get_account", fake_account)

    alerts = []
    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        alerts.append(payload)
    monkeypatch.setattr(agent, "emit", fake_emit)

    await agent._reconcile_alpaca_startup()

    assert agent.broker_name == "PAPER"
    assert agent.broker is agent.paper_broker
    assert any(p.get("reason") == "alpaca_unreachable" for p in alerts)
