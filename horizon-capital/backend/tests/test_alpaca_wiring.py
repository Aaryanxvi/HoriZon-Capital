# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1195D125476C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Alpaca broker wiring: guard refusal, async fill settlement, broker sync."""
from __future__ import annotations

import pytest

from app.agents.front_office.trading.execution_agent import ExecutionAgent, _alpaca_guard_ok
from app.core.memory_bus import MemoryBus


def _make_agent(monkeypatch=None) -> ExecutionAgent:
    agent = ExecutionAgent(bus=MemoryBus())
    if monkeypatch is not None:
        # Tests here drive _execute_order directly, without the startup sync
        # that marks the broker reachable, and the fill path then rests a
        # trailing stop at the broker -- stub both so nothing touches the network.
        agent._broker_ok = True
        agent.stop_calls = []  # type: ignore[attr-defined]

        async def fake_stop(symbol, qty, trail_percent, client_order_id):
            agent.stop_calls.append((symbol, qty, trail_percent))  # type: ignore[attr-defined]
            return {"broker_order_id": f"stop-{len(agent.stop_calls)}",  # type: ignore[attr-defined]
                    "status": "accepted"}
        monkeypatch.setattr(agent.alpaca_broker, "place_trailing_stop", fake_stop)

        async def fake_cancel_and_wait(boid, timeout_sec=5.0):
            return {"broker_order_id": boid, "status": "canceled", "filled_qty": 0.0,
                    "filled_avg_price": 0.0}
        monkeypatch.setattr(agent.alpaca_broker, "cancel_and_wait", fake_cancel_and_wait)
    return agent


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
# Guard: NO broker on any misconfiguration (never the simulator for a real
# broker configuration -- audit B4)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_guard_fails_without_keys(monkeypatch):
    _set_alpaca_settings(monkeypatch, key="")

    assert _alpaca_guard_ok() is False
    agent = _make_agent()
    assert agent.broker_name == "NONE"
    assert agent.broker is None


@pytest.mark.asyncio
async def test_guard_fails_when_paper_mode_false(monkeypatch):
    _set_alpaca_settings(monkeypatch, paper_mode=False)

    assert _alpaca_guard_ok() is False
    agent = _make_agent()
    assert agent.broker_name == "NONE"


@pytest.mark.asyncio
async def test_guard_fails_on_live_url(monkeypatch):
    """The hard safety net: even with valid keys + paper_mode=True, a
    non-paper-api base_url must never route live -- and must not quietly
    trade in the simulator either: every order is refused."""
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory
    from app.core.messaging import AgentMessage, MessageType

    _set_alpaca_settings(monkeypatch, base_url="https://api.alpaca.markets")

    assert _alpaca_guard_ok() is False
    await init_local_db()
    agent = _make_agent()
    assert agent.broker_name == "NONE"

    await agent._handle_new_order(AgentMessage(
        sender_id="t", channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"symbol": "AAPL.NASDAQ", "exchange": "NASDAQ", "side": "BUY",
                 "quantity": 1, "order_type": "MARKET"},
    ))
    async with local_session_factory() as s:
        row = (await s.execute(text("SELECT status, rejection_reason FROM orders"))).fetchone()
    assert row.status == "REJECTED" and "No execution broker" in row.rejection_reason


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
    agent = _make_agent(monkeypatch)
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
    # The fill armed exactly one broker-side trailing stop for the whole lot.
    assert agent.stop_calls == [("AAPL.NASDAQ", 10, 20.0)]


@pytest.mark.asyncio
async def test_partial_fill_on_post_defers_to_poll_settles_once(monkeypatch):
    """POST returns a PARTIAL fill (5 of 10) — must NOT settle immediately;
    only the poll's final cumulative fill (qty 10) settles, exactly once."""
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)

    await init_local_db()
    agent = _make_agent(monkeypatch)

    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM cash_balances"))
        await s.execute(
            text("INSERT INTO cash_balances (currency, amount) VALUES ('USD', 100000)")
        )
        await s.commit()

    from app.core import kv_store
    kv = kv_store.get_kv_store()
    await kv.set("horizon:price:AAPL.NASDAQ", "100.0")

    async def fake_execute(order):
        return {
            "order_id": order.get("id", ""),
            "broker_order_id": "bo-partial",
            "filled_qty": 5.0,
            "fill_price": 100.5,
            "commission": 0.0,
            "slippage": 0.0,
            "broker": "ALPACA",
            "alpaca_status": "partially_filled",
        }
    monkeypatch.setattr(agent.alpaca_broker, "execute", fake_execute)

    order = await agent.order_manager.create_order({
        "symbol": "AAPL.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "ALPACA", "mode": "PAPER_TRADING",
    })

    await agent._execute_order(order)

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT status, broker_order_id FROM orders WHERE id = :id"),
            {"id": order["id"]},
        )).fetchone()
        pos = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
    assert row.status == "OPEN"
    assert row.broker_order_id == "bo-partial"
    assert pos is None  # no settle on the partial POST response

    # Poll later reports the completed cumulative fill.
    async def fake_status(broker_order_id):
        return {
            "broker_order_id": broker_order_id,
            "status": "filled",
            "filled_qty": 10.0,
            "filled_avg_price": 100.8,
            "filled_at": "2026-01-01T00:00:00Z",
        }
    monkeypatch.setattr(agent.alpaca_broker, "get_order_status", fake_status)

    await agent._poll_open_orders()

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT status FROM orders WHERE id = :id"), {"id": order["id"]},
        )).fetchone()
        pos = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
        cash = (await s.execute(
            text("SELECT amount FROM cash_balances WHERE currency = 'USD'"),
        )).fetchone()
        fills = (await s.execute(
            text("SELECT COUNT(*) AS n FROM fills WHERE order_id = :id"), {"id": order["id"]},
        )).fetchone()

    assert row.status == "FILLED"
    assert pos.quantity == pytest.approx(10.0)
    assert cash.amount == pytest.approx(100000 - 10 * 100.8)
    assert fills.n == 1  # settled exactly once, at the final cumulative qty/price


@pytest.mark.asyncio
async def test_poll_skips_settle_when_filled_without_price(monkeypatch):
    """Alpaca reports status=filled but filled_avg_price is 0/None — must not
    settle at price 0; wait for a later poll to see a real price."""
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)

    await init_local_db()
    agent = _make_agent(monkeypatch)

    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM cash_balances"))
        await s.execute(
            text("INSERT INTO cash_balances (currency, amount) VALUES ('USD', 100000)")
        )
        await s.commit()

    order = await agent.order_manager.create_order({
        "symbol": "AAPL.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "ALPACA", "mode": "PAPER_TRADING",
    })
    await agent.order_manager.update_status(order["id"], "OPEN")
    await agent.order_manager.set_broker_order_id(order["id"], "bo-nopricce")

    async def fake_status(broker_order_id):
        return {
            "broker_order_id": broker_order_id,
            "status": "filled",
            "filled_qty": 10.0,
            "filled_avg_price": 0.0,
            "filled_at": "2026-01-01T00:00:00Z",
        }
    monkeypatch.setattr(agent.alpaca_broker, "get_order_status", fake_status)

    await agent._poll_open_orders()

    async with local_session_factory() as s:
        row = (await s.execute(
            text("SELECT status FROM orders WHERE id = :id"), {"id": order["id"]},
        )).fetchone()
        pos = (await s.execute(
            text("SELECT quantity FROM positions WHERE symbol = 'AAPL.NASDAQ'"),
        )).fetchone()
        cash = (await s.execute(
            text("SELECT amount FROM cash_balances WHERE currency = 'USD'"),
        )).fetchone()

    assert row.status == "OPEN"  # not settled
    assert pos is None
    assert cash.amount == pytest.approx(100000)


# --------------------------------------------------------------------------- #
# Broker sync: Alpaca is the source of truth; the local ledger is overwritten,
# every difference audited, and the simulator is never a fallback (audit B4)
# --------------------------------------------------------------------------- #

async def _seed(local_session_factory, *, cash: float, positions: list[tuple]):
    from sqlalchemy import text
    async with local_session_factory() as s:
        await s.execute(text("DELETE FROM positions"))
        await s.execute(text("DELETE FROM cash_balances"))
        await s.execute(text("INSERT INTO cash_balances (currency, amount) VALUES ('USD', :c)"),
                        {"c": cash})
        for i, (sym, exch, qty, avg) in enumerate(positions):
            await s.execute(text(
                "INSERT INTO positions (id, symbol, exchange, side, quantity,"
                " avg_entry_price, currency) VALUES (:id, :s, :e, 'LONG', :q, :a, 'USD')"
            ), {"id": f"pos-{i}", "s": sym, "e": exch, "q": qty, "a": avg})
        await s.commit()


@pytest.mark.asyncio
async def test_sync_overwrites_local_from_broker_and_audits_every_difference(monkeypatch):
    from sqlalchemy import text

    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)
    await init_local_db()
    agent = _make_agent(monkeypatch)
    await get_kv_store().set("horizon:portfolio:nav", "100000")
    # Local book: MSFT 50, GLD 5 (broker has none), cash 50k.
    await _seed(local_session_factory, cash=50_000.0,
                positions=[("MSFT.NASDAQ", "NASDAQ", 50, 300.0), ("GLD.NYSE", "NYSE", 5, 180.0)])

    async def fake_account():
        return {"equity": 123_456.0, "cash": 60_000.0}

    async def fake_positions():
        # Broker: MSFT 30 (not 50), AAPL 10 (unknown locally), no GLD.
        return [{"symbol": "MSFT", "qty": 30.0, "qty_available": 30.0, "avg_entry": 300.0,
                 "current_price": 305.0, "side": "LONG", "exchange": "NASDAQ",
                 "asset_class": "us_equity"},
                {"symbol": "AAPL", "qty": 10.0, "qty_available": 10.0, "avg_entry": 150.0,
                 "current_price": 155.0, "side": "LONG", "exchange": "NASDAQ",
                 "asset_class": "us_equity"}]
    monkeypatch.setattr(agent.alpaca_broker, "get_account", fake_account)
    monkeypatch.setattr(agent.alpaca_broker, "get_positions", fake_positions)
    alerts = []

    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        alerts.append(payload)
    monkeypatch.setattr(agent, "emit", fake_emit)

    assert await agent._sync_from_broker() is True
    assert agent.broker_name == "ALPACA" and agent._broker_ok is True

    async with local_session_factory() as s:
        rows = {r.symbol: r.quantity for r in (await s.execute(
            text("SELECT symbol, quantity FROM positions"))).fetchall()}
        cash = (await s.execute(text(
            "SELECT amount FROM cash_balances WHERE currency = 'USD'"))).fetchone().amount
        audit = (await s.execute(text(
            "SELECT rule_name, severity, payload FROM alert_history"))).fetchall()
    assert rows["MSFT.NASDAQ"] == pytest.approx(30.0)
    assert rows["GLD.NYSE"] == pytest.approx(0.0)
    assert rows["AAPL.NASDAQ"] == pytest.approx(10.0)
    assert cash == pytest.approx(60_000.0)
    assert await get_kv_store().get("horizon:portfolio:nav") == "123456.0"
    assert await get_kv_store().get("horizon:cash:usd") == "60000.0"

    crit = [a for a in alerts if a.get("reason") == "broker_sync_overwrote_local"]
    assert len(crit) == 1 and crit[0]["severity"] == "CRITICAL"
    kinds = sorted((d["kind"], d.get("symbol", d.get("currency"))) for d in crit[0]["diffs"])
    assert kinds == [("cash", "USD"), ("position", "AAPL.NASDAQ"),
                     ("position", "GLD.NYSE"), ("position", "MSFT.NASDAQ")]
    assert len(audit) == 1 and audit[0].rule_name == "broker_sync" \
        and audit[0].severity == "CRITICAL" and "GLD.NYSE" in audit[0].payload


@pytest.mark.asyncio
async def test_sync_matching_books_raise_nothing(monkeypatch):
    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)
    await init_local_db()
    agent = _make_agent(monkeypatch)
    await _seed(local_session_factory, cash=50_000.0,
                positions=[("MSFT.NASDAQ", "NASDAQ", 30, 300.0)])

    async def fake_account():
        return {"equity": 59_150.0, "cash": 50_000.0}

    async def fake_positions():
        return [{"symbol": "MSFT", "qty": 30.0, "avg_entry": 300.0, "current_price": 305.0,
                 "side": "LONG", "exchange": "NASDAQ", "asset_class": "us_equity"}]
    monkeypatch.setattr(agent.alpaca_broker, "get_account", fake_account)
    monkeypatch.setattr(agent.alpaca_broker, "get_positions", fake_positions)
    alerts = []

    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        alerts.append(payload)
    monkeypatch.setattr(agent, "emit", fake_emit)

    assert await agent._sync_from_broker() is True
    assert alerts == []


@pytest.mark.asyncio
async def test_sync_unreachable_refuses_buys_and_never_falls_back_to_paper(monkeypatch):
    from sqlalchemy import text

    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)
    await init_local_db()
    agent = _make_agent(monkeypatch)
    await _seed(local_session_factory, cash=100_000.0,
                positions=[("MSFT.NASDAQ", "NASDAQ", 30, 300.0)])
    await get_kv_store().set("horizon:price:MSFT.NASDAQ", "300")

    async def down():
        return None
    monkeypatch.setattr(agent.alpaca_broker, "get_account", down)
    alerts = []

    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        alerts.append(payload)
    monkeypatch.setattr(agent, "emit", fake_emit)

    assert await agent._sync_from_broker() is False
    assert agent.broker_name == "ALPACA" and agent.broker is agent.alpaca_broker
    assert agent._broker_ok is False
    assert [a["severity"] for a in alerts if a.get("reason") == "alpaca_unreachable"] == ["CRITICAL"]

    # The ledger is untouched (no overwrite from an unreachable broker).
    async with local_session_factory() as s:
        row = (await s.execute(text("SELECT quantity FROM positions"))).fetchone()
    assert row.quantity == pytest.approx(30.0)

    sent = []

    async def real_execute(order):
        sent.append(order)
        return None
    monkeypatch.setattr(agent.alpaca_broker, "execute", real_execute)

    async def lookup(cid):
        return {"found": False}
    monkeypatch.setattr(agent.alpaca_broker, "get_order_by_client_id", lookup)

    async def qty(symbol):
        return None  # unreachable -> cannot verify, local check only
    monkeypatch.setattr(agent.alpaca_broker, "get_position_qty", qty)

    buy = await agent.order_manager.create_order({
        "symbol": "MSFT.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "BUY", "quantity": 1, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await agent._execute_order(buy)
    sell = await agent.order_manager.create_order({
        "symbol": "MSFT.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "SELL", "quantity": 30, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await agent._execute_order(sell)
    async with local_session_factory() as s:
        b = (await s.execute(text("SELECT status, rejection_reason FROM orders WHERE id = :i"),
                             {"i": buy["id"]})).fetchone()
    assert b.status == "REJECTED" and "unreachable" in b.rejection_reason
    # The exit was still attempted against the real broker (not the simulator).
    assert [o["id"] for o in sent] == [sell["id"]]


@pytest.mark.asyncio
async def test_sync_is_deferred_while_alpaca_orders_are_in_flight(monkeypatch):
    """A fill the poller has not booked yet would be counted twice if the sync
    copied the broker's position at the same time -- so the sync waits."""
    from sqlalchemy import text

    from app.core.local_storage import init_local_db, local_session_factory

    _set_alpaca_settings(monkeypatch)
    await init_local_db()
    agent = _make_agent(monkeypatch)
    await _seed(local_session_factory, cash=100_000.0, positions=[])
    order = await agent.order_manager.create_order({
        "symbol": "AAPL.NASDAQ", "exchange": "NASDAQ", "order_type": "MARKET",
        "side": "BUY", "quantity": 10, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await agent.order_manager.update_status(order["id"], "OPEN")
    await agent.order_manager.set_broker_order_id(order["id"], "bo-inflight")

    async def fake_account():
        return {"equity": 100_000.0, "cash": 99_000.0}

    async def fake_positions():
        return [{"symbol": "AAPL", "qty": 10.0, "avg_entry": 100.0, "current_price": 100.0,
                 "side": "LONG", "exchange": "NASDAQ", "asset_class": "us_equity"}]

    async def still_open(boid):
        return {"broker_order_id": boid, "status": "accepted", "filled_qty": 0.0,
                "filled_avg_price": 0.0}
    monkeypatch.setattr(agent.alpaca_broker, "get_account", fake_account)
    monkeypatch.setattr(agent.alpaca_broker, "get_positions", fake_positions)
    monkeypatch.setattr(agent.alpaca_broker, "get_order_status", still_open)

    assert await agent._sync_from_broker() is True
    async with local_session_factory() as s:
        n = (await s.execute(text("SELECT COUNT(*) FROM positions"))).scalar()
        cash = (await s.execute(text(
            "SELECT amount FROM cash_balances WHERE currency='USD'"))).fetchone().amount
    assert n == 0 and cash == pytest.approx(100_000.0)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1195D125476C - verify with scripts/authorship.py verify
