# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A3D13FA74DDA
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Re-audit of the hardening wave (commit 8e43201) -- adversarial proofs.

Same method as test_risk_controls_proof.py: real agents, real MemoryBus, per-test
SQLite, PaperBroker or fakes for Alpaca. No network, no broker calls, no LLM.

``test_R*`` PASSING means a residual defect is REPRODUCED on the fixed code.
``test_OK2_*`` independently re-confirms a fix without trusting the fixer's
inverted regression tests.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from app.config import settings
from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType

SYM, EXCH = "AAPL.NASDAQ", "NASDAQ"


# --------------------------------------------------------------------------
# Helpers (same shape as test_risk_controls_proof.py)
# --------------------------------------------------------------------------

class Recorder:
    def __init__(self) -> None:
        self.msgs: list[AgentMessage] = []

    async def __call__(self, msg: AgentMessage) -> None:
        self.msgs.append(msg)

    def on(self, prefix: str) -> list[AgentMessage]:
        return [m for m in self.msgs if m.channel.startswith(prefix)]

    @property
    def orders(self) -> list[AgentMessage]:
        return self.on("horizon.execution.order.new")

    def alerts(self, reason: str) -> list[AgentMessage]:
        return [m for m in self.on("horizon.risk.alert") if m.payload.get("reason") == reason]

    async def settle(self, pred=None, timeout: float = 5.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if pred is not None and pred(self):
                await asyncio.sleep(0.2)
                return


async def _bus() -> tuple[MemoryBus, Recorder]:
    bus = MemoryBus()
    rec = Recorder()
    await bus.subscribe("horizon.*", rec)
    await bus.start_listening()
    import app.core.runtime as rt
    rt._bus = bus
    return bus, rec


async def _fresh(cash_usd: float = 100_000.0, nav: float | None = None):
    from app.core.cash import mirror_to_kv, set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as s:
        for t in ("positions", "orders", "fills", "portfolio_snapshots", "pending_approvals",
                  "kv_cache", "risk_metrics", "agent_messages", "alert_history"):
            await s.execute(text(f"DELETE FROM {t}"))  # noqa: S608
        await set_cash(s, "USD", cash_usd)
        await set_cash(s, "INR", 0.0)
        await s.commit()
    kv = get_kv_store()
    kv._data.clear()
    kv._hashes.clear()
    await mirror_to_kv("USD", cash_usd)
    await mirror_to_kv("INR", 0.0)
    await kv.set("horizon:portfolio:nav", str(nav if nav is not None else cash_usd))
    return local_session_factory


async def _price(symbol: str, px: float, age: timedelta | None = None) -> None:
    from app.core.kv_store import get_kv_store
    kv = get_kv_store()
    ts = (datetime.now(UTC) - (age or timedelta(0))).isoformat()
    keys = [symbol]
    if "." in symbol:
        keys.append(symbol.split(".")[0])
    for k in keys:
        await kv.set(f"horizon:price:{k}", str(px))
        await kv.set(f"horizon:price:{k}:ts", ts)


async def _position(sf, symbol: str, exchange: str, qty: float, price: float, *,
                    stop: float | None = None, hwm: float | None = None,
                    stop_order_id: str | None = None, stopped_out: int | None = None,
                    side: str = "LONG") -> None:
    async with sf() as s:
        await s.execute(text(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price,"
            " current_price, currency, stop_loss_price, high_water_mark, stop_order_id,"
            " stopped_out, created_at, updated_at)"
            " VALUES (:id, :sym, :ex, :side, :q, :p, :p, 'USD', :sl, :hwm, :soid, :so, :now, :now)"),
            {"id": str(uuid.uuid4()), "sym": symbol, "ex": exchange, "side": side, "q": qty,
             "p": price, "sl": stop, "hwm": hwm, "soid": stop_order_id, "so": stopped_out,
             "now": datetime.now(UTC)})
        await s.commit()


async def _row(sf, sql: str, **params):
    async with sf() as s:
        return (await s.execute(text(sql), params)).fetchone()


async def _rows(sf, sql: str, **params):
    async with sf() as s:
        return (await s.execute(text(sql), params)).fetchall()


def _alpaca_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "alpaca_api_key", "test-key")
    monkeypatch.setattr(settings, "alpaca_api_secret", "test-secret")
    monkeypatch.setattr(settings, "alpaca_paper_mode", True)
    monkeypatch.setattr(settings, "alpaca_base_url", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(settings, "execution_broker", "ALPACA")
    from app.data_layer import alpaca_quotes

    async def _none(_symbol):
        return None
    monkeypatch.setattr(alpaca_quotes, "get_latest_price", _none)


def _bp(symbol: str, qty: float, px: float, *, available: float | None = None,
        exchange: str = "NASDAQ", asset_class: str = "us_equity") -> dict:
    """A broker position exactly as AlpacaBroker.get_positions() shapes it."""
    return {"symbol": symbol, "qty": qty, "qty_available": qty if available is None else available,
            "avg_entry": px, "current_price": px, "side": "LONG", "exchange": exchange,
            "asset_class": asset_class}


def _fake_broker(monkeypatch, ex, *, equity: float, cash: float, positions: list[dict],
                 order_status: dict | None = None):
    """Wire the agent's AlpacaBroker to canned answers; records every POST."""
    calls = {"execute": [], "stops": [], "cancel": [], "status": []}

    async def account():
        return {"equity": equity, "cash": cash}

    async def get_positions():
        return [dict(p) for p in positions]

    async def execute(order):
        calls["execute"].append(dict(order))
        return None

    async def by_client_id(_cid):
        return {"found": False}

    async def place_stop(symbol, qty, trail, client_order_id):
        calls["stops"].append({"symbol": symbol, "qty": qty})
        return {"broker_order_id": f"stp-{len(calls['stops'])}", "status": "accepted",
                "filled_qty": 0.0, "filled_avg_price": 0.0}

    async def get_status(boid):
        calls["status"].append(boid)
        return order_status

    monkeypatch.setattr(ex.alpaca_broker, "get_account", account)
    monkeypatch.setattr(ex.alpaca_broker, "get_positions", get_positions)
    monkeypatch.setattr(ex.alpaca_broker, "execute", execute)
    monkeypatch.setattr(ex.alpaca_broker, "get_order_by_client_id", by_client_id)
    monkeypatch.setattr(ex.alpaca_broker, "place_trailing_stop", place_stop)
    monkeypatch.setattr(ex.alpaca_broker, "get_order_status", get_status)
    return calls


def _sleeve(direction: int, target: float, symbol=SYM, exchange=EXCH) -> dict:
    return {"signal_id": str(uuid.uuid4()), "symbol": symbol, "exchange": exchange,
            "direction": direction, "strength": 0.4, "strategy_name": "sleeve_system",
            "target_weight": target, "previous_weight": 0.0 if direction > 0 else target,
            "stop_loss": None, "bar_timestamp": datetime.now(UTC).isoformat()}


def _stop_signal(symbol=SYM, exchange=EXCH) -> AgentMessage:
    return AgentMessage(
        sender_id="position-monitor-worker", channel=f"horizon.signal.{symbol}",
        message_type=MessageType.SIGNAL,
        payload={"symbol": symbol, "exchange": exchange, "direction": -1, "strength": 1.0,
                 "strategy_name": "stop_loss", "reasoning": "test"})


# ==========================================================================
# Residual defects on the fixed code
# ==========================================================================

@pytest.mark.asyncio
async def test_R1_synced_in_position_has_no_worker_stop_until_price_makes_a_new_high(monkeypatch):
    """_sync_from_broker materialises a broker-only position with high_water_mark but
    stop_loss_price NULL (execution_agent.py:326-333); the worker only derives a stop
    when price > HWM (position_worker.py:221-225). A position synced in at the top
    rides any decline with no worker stop. (The broker stop is a separate layer and
    does not exist for crypto -- see test_R10.)"""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.workers.position_worker import PositionMonitorWorker

    ex = ExecutionAgent(bus)
    _fake_broker(monkeypatch, ex, equity=100_000, cash=90_000,
                 positions=[_bp("AAPL", 100, 100.0)])
    await ex._sync_from_broker()
    row = await _row(sf, "SELECT quantity, high_water_mark, stop_loss_price FROM positions"
                         " WHERE symbol=:s", s=SYM)
    assert row.quantity == 100 and row.high_water_mark == 100.0
    assert row.stop_loss_price is None, "sync arms no stop"

    w = PositionMonitorWorker()
    await _price(SYM, 70.0)  # -30% from the sync price, fresh print
    await w._mark_to_market()
    await asyncio.sleep(0.3)
    stops = [m for m in rec.on("horizon.signal.") if m.payload.get("strategy_name") == "stop_loss"]
    assert stops == [], "no stop-loss after a 30% drop on a synced-in position"
    row = await _row(sf, "SELECT stop_loss_price FROM positions WHERE symbol=:s", s=SYM)
    assert row.stop_loss_price is None

    # Only a NEW high arms it (then it works).
    await _price(SYM, 101.0)
    await w._mark_to_market()
    row = await _row(sf, "SELECT stop_loss_price FROM positions WHERE symbol=:s", s=SYM)
    assert row.stop_loss_price == pytest.approx(80.8)
    await bus.stop()


@pytest.mark.asyncio
async def test_R2_broker_stop_that_fills_while_app_is_down_or_between_poll_and_sync_is_wiped_unbooked(monkeypatch):
    """A resting GTC stop fires while the process is down (or in the 5 s between
    _poll_broker_stops and _sync_from_broker). The sync sees broker qty 0 and zeroes
    the row (execution_agent.py:302-307): no fill row, no realised P&L, and
    stopped_out stays NULL -- so re-entry rule A has nothing to key on and the
    next BUY signal buys the name straight back."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    await _position(sf, SYM, EXCH, 100, 100.0, stop=80.0, hwm=100.0, stop_order_id="stp-1")
    ex = ExecutionAgent(bus)
    _fake_broker(monkeypatch, ex, equity=97_900, cash=97_900, positions=[],
                 order_status={"broker_order_id": "stp-1", "status": "filled",
                               "filled_qty": 100.0, "filled_avg_price": 79.0})
    await ex._sync_from_broker()
    await rec.settle(lambda r: r.alerts("broker_sync_overwrote_local"))

    row = await _row(sf, "SELECT quantity, stop_order_id, stopped_out FROM positions"
                         " WHERE symbol=:s", s=SYM)
    fills = await _row(sf, "SELECT COUNT(*) AS c FROM fills")
    assert row.quantity == 0 and row.stop_order_id is None
    assert fills.c == 0, "the stop fill was never booked"
    assert row.stopped_out is None, "re-entry guard never set"
    assert rec.alerts("broker_stop_filled") == []

    # Next sleeve BUY (the strategy re-emits every target on its first tick after a
    # restart) re-buys the name immediately.
    await _price(SYM, 79.0)
    pa = PortfolioAgent(bus)
    assert await pa._stopped_out_symbols() == set()
    await pa._handle_signal(_sleeve(+1, 0.15))
    await rec.settle(lambda r: r.orders)
    assert rec.orders and rec.orders[0].payload["side"] == "BUY"
    await bus.stop()


@pytest.mark.asyncio
async def test_R3_stopped_out_marker_only_gates_reconcile_not_the_signal_path():
    """Rule A (stay out after a stop) lives only in _reconcile (portfolio_agent.py:430).
    _handle_signal has no such check: a sleeve BUY -- which StrategyAgent re-emits for
    every target on its first tick after any restart -- re-enters a stopped-out name
    within 60 s of boot. The backtest in the audit doc assumed rule A holds."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    await _position(sf, SYM, EXCH, 0, 80.0, side="FLAT", stopped_out=1)
    await _price(SYM, 80.0)
    pa = PortfolioAgent(bus)
    assert await pa._stopped_out_symbols() == {SYM}
    await pa._handle_signal(_sleeve(+1, 0.15))
    await rec.settle(lambda r: r.orders)
    assert rec.orders and rec.orders[0].payload["side"] == "BUY"
    await bus.stop()


@pytest.mark.asyncio
async def test_R4_concurrent_sells_on_one_symbol_oversell_the_paper_book_and_mint_cash(monkeypatch):
    """The reduce-only check (execution_agent.py:767-773) runs outside the per-symbol
    lock that guards settlement. Two SELLs for the same name arriving together (stop
    worker + sleeve exit on the same crash print) both read held=100, both fill in the
    simulator; update_position clamps the second to 0 shares but record_fill and
    adjust_cash book the full 100 -> $10k from nothing in the PAPER ledger."""
    sf = await _fresh(cash_usd=100_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash

    await _position(sf, SYM, EXCH, 100, 100.0, stop=80.0, hwm=100.0)
    await _price(SYM, 100.0)
    ex = ExecutionAgent(bus)

    async def slow_fill(order):  # a broker round-trip takes time
        await asyncio.sleep(0.05)
        return {"filled_qty": order["quantity"], "fill_price": 100.0,
                "commission": 0.0, "slippage": 0.0, "broker": "PAPER"}
    monkeypatch.setattr(ex.paper_broker, "execute", slow_fill)

    async def order(strategy):
        return await ex.order_manager.create_order({
            "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
            "quantity": 100, "broker": "PAPER", "mode": "PAPER_TRADING",
            "strategy_name": strategy})
    o1, o2 = await order("stop_loss"), await order("sleeve_system")
    await asyncio.gather(ex._execute_order(o1), ex._execute_order(o2))

    st = await _rows(sf, "SELECT status FROM orders ORDER BY created_at")
    fills = await _row(sf, "SELECT COUNT(*) AS c, COALESCE(SUM(filled_qty),0) AS q FROM fills")
    pos = await _row(sf, "SELECT side, quantity FROM positions WHERE symbol=:s", s=SYM)
    async with sf() as s:
        cash = await get_cash(s, "USD")
    assert [r.status for r in st] == ["FILLED", "FILLED"]
    assert fills.c == 2 and fills.q == 200, "200 shares 'sold' from a 100-share position"
    # Second settle finds the row FLAT and takes update_position's "adding to short"
    # branch (order_manager.py:449-458): the book now shows a 100-share SHORT.
    assert (pos.side, pos.quantity) == ("SHORT", 100.0), f"ledger now {pos.side} {pos.quantity}"
    assert cash == pytest.approx(120_000.0), f"cash {cash:,.0f}: $10k minted by the oversell"
    await bus.stop()


@pytest.mark.asyncio
async def test_R5_price_timestamp_is_the_write_time_so_the_staleness_check_can_be_lied_to():
    """StrategyAgent._publish_ticks stamps horizon:price:<sym>:ts with now() for a daily
    bar that fetch_batch caches for 6 h (strategy_agent.py:277-278, batch_bars.py:30);
    data_manager._handle_tick/_handle_ohlcv do the same (data_manager.py:112, 125).
    _is_stale therefore sees a 'fresh' print for a close that is days old."""
    await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.strategy.strategy_agent import StrategyAgent
    from app.core.kv_store import get_kv_store
    from app.workers.position_worker import _is_stale

    three_days_ago = pd.Timestamp(datetime.now(UTC) - timedelta(days=3)).normalize()
    idx = pd.DatetimeIndex([three_days_ago - pd.Timedelta(days=1), three_days_ago])
    bars = {s: pd.DataFrame({"open": [1, 1], "high": [1, 1], "low": [1, 1],
                             "close": [50_000.0, 48_000.0], "volume": [10, 10]}, index=idx)
            for s in ("BTC-USD", "SPY.NYSE")}
    strat = StrategyAgent(bus=bus)
    await strat._publish_ticks(bars)

    kv = get_kv_store()
    for sym, exch in (("BTC-USD", "CRYPTO"), ("SPY.NYSE", "NYSE")):
        ts = datetime.fromisoformat(await kv.get(f"horizon:price:{sym}:ts"))
        assert (datetime.now(UTC) - ts).total_seconds() < 5, "stamped with the write time"
        assert not _is_stale(ts, sym, exch), f"{sym}: 3-day-old close passes as live"
    await bus.stop()


@pytest.mark.asyncio
async def test_R6_release_stop_with_unknown_cancel_outcome_forgets_the_resting_stop(monkeypatch):
    """_release_broker_stop clears stop_order_id whenever cancel_and_wait returns
    (execution_agent.py:1051-1057), including None = 'never reached a terminal
    status' (timeout / broker unreachable). The next _sync_broker_stop then rests a
    SECOND trailing stop; the first is orphaned -- when it fires the sync wipes the
    position unbooked (test_R2)."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    await _position(sf, SYM, EXCH, 100, 100.0, stop=80.0, hwm=100.0, stop_order_id="stp-orig")
    ex = ExecutionAgent(bus)
    calls = _fake_broker(monkeypatch, ex, equity=100_000, cash=90_000,
                         positions=[_bp("AAPL", 100, 100.0, available=0.0)])
    cancelled: list[str] = []

    async def unknown(boid, timeout_sec=5.0):
        cancelled.append(boid)
        return None  # documented: "never settled within the timeout"
    monkeypatch.setattr(ex.alpaca_broker, "cancel_and_wait", unknown)

    await ex._release_broker_stop(SYM, EXCH)
    row = await _row(sf, "SELECT stop_order_id FROM positions WHERE symbol=:s", s=SYM)
    assert cancelled == ["stp-orig"] and row.stop_order_id is None, \
        "forgot stp-orig although its cancel never settled"

    # Re-arm (what _execute_order / _poll_broker_stops do next): a second stop rests at
    # the broker and the agent now tracks only that one.
    await ex._sync_broker_stop(SYM, EXCH)
    row = await _row(sf, "SELECT stop_order_id FROM positions WHERE symbol=:s", s=SYM)
    assert calls["stops"] == [{"symbol": SYM, "qty": 100}]
    assert row.stop_order_id == "stp-1" and "stp-orig" not in (row.stop_order_id,), \
        "stp-orig is orphaned: still possibly resting, unknown to the agent"
    await bus.stop()


@pytest.mark.asyncio
async def test_R7_polymarket_sleeve_enabled_under_alpaca_is_not_refused_just_rejected_every_time(monkeypatch):
    """settings allow POLYMARKET_SLEEVE_ENABLED=true with EXECUTION_BROKER=ALPACA (the
    developer .env has both). The sleeve keeps emitting; every order is refused as
    UNROUTABLE_SIM with a HIGH alert (execution_agent.py:177-179, 510-519), and
    reconcile re-emits the BUY-side drift every 15 min per market."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    monkeypatch.setattr(settings, "polymarket_sleeve_enabled", True)
    monkeypatch.setattr(settings, "polymarket_markets", "will-x-happen")
    from app.agents.front_office.strategy.strategy_agent import StrategyAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    assert any(s.name == "polymarket_momentum" for s in StrategyAgent(bus)._sleeves), \
        "config contradiction accepted at construction"
    ex = ExecutionAgent(bus)
    await ex._subscribe()
    poly = "PM-will-x-happen.POLY"
    await _price(poly, 0.42)
    await bus.publish(AgentMessage(
        sender_id="portfolio-agent", channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"symbol": poly, "exchange": "POLY", "side": "BUY", "quantity": 100,
                 "order_type": "MARKET", "allocation_usd": 42.0,
                 "strategy_name": "sleeve_system"}))
    await rec.settle(lambda r: r.alerts("simulator_order_refused"))
    o = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE symbol=:s", s=poly)
    assert o.status == "REJECTED" and "Simulator fills are not allowed" in o.rejection_reason
    assert rec.alerts("simulator_order_refused")[0].payload["severity"] == "HIGH"
    await bus.stop()


@pytest.mark.asyncio
async def test_R8_broker_reduce_only_check_uses_total_qty_not_qty_available(monkeypatch):
    """get_position_qty returns Alpaca's total ``qty`` (alpaca_broker.py:408-417), not
    ``qty_available``. Shares reserved by a resting order (a stop whose cancel did not
    settle, a queued SELL overnight) still pass the check; the SELL is POSTed, Alpaca
    rejects it, and the agent then rests another stop that is rejected too -- a
    30 s reject/alert loop driven by the stop worker, with no second gate locally."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    await _position(sf, SYM, EXCH, 100, 100.0, stop=80.0, hwm=100.0)
    await _price(SYM, 79.0)
    ex = ExecutionAgent(bus)
    calls = _fake_broker(monkeypatch, ex, equity=100_000, cash=90_000,
                         positions=[_bp("AAPL", 100, 79.0, available=0.0)])
    assert await ex.alpaca_broker.get_position_qty(SYM) == 100.0

    o = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING", "strategy_name": "stop_loss"})
    await ex._execute_order(o)
    assert len(calls["execute"]) == 1, "SELL went to the broker although qty_available is 0"
    st = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=o["id"])
    assert st.status == "REJECTED"
    assert calls["stops"] == [{"symbol": SYM, "qty": 100}], "and a new stop was placed on reserved shares"
    await bus.stop()


@pytest.mark.asyncio
async def test_R9_sync_names_broker_only_positions_by_alpaca_exchange_while_the_universe_uses_dot_us(monkeypatch):
    """get_universe suffixes every non-anchor S&P name '.US' (universe.py:112; the
    pre-reset ledger held SNDK.US, MU.US, MRNA.US). _local_symbol only knows anchors +
    US_SYMBOLS, so a broker-only SNDK becomes 'SNDK.NASDAQ' (execution_agent.py:378-390).
    The next sleeve fill books 'SNDK.US' beside it; the following sync sets BOTH rows to
    the broker qty -> exposure double-counted, two stops armed for one holding."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    assert ex._local_symbol(_bp("SNDK", 50, 100.0)) == ("SNDK.NASDAQ", "NASDAQ")

    broker = [_bp("SNDK", 50, 100.0)]
    calls = _fake_broker(monkeypatch, ex, equity=100_000, cash=95_000, positions=broker)
    await ex._sync_from_broker()
    assert (await _row(sf, "SELECT quantity FROM positions WHERE symbol='SNDK.NASDAQ'")).quantity == 50

    # The sleeve trades the universe name: a 10-share fill books a second row.
    fill_order = {"id": str(uuid.uuid4()), "symbol": "SNDK.US", "exchange": "US", "side": "BUY",
                  "quantity": 10, "broker": "ALPACA", "strategy_name": "sleeve_system"}
    await ex.order_manager.create_order({**fill_order, "order_type": "MARKET",
                                         "mode": "PAPER_TRADING"})
    oid = (await _row(sf, "SELECT id FROM orders WHERE symbol='SNDK.US'")).id
    fill_order["id"] = oid
    await ex.order_manager.update_status(oid, "OPEN")
    await ex._settle_fill(fill_order, {"filled_qty": 10.0, "fill_price": 100.0,
                                       "commission": 0.0, "slippage": 0.0})
    broker[0]["qty"] = broker[0]["qty_available"] = 60.0
    await ex._sync_from_broker()

    rows = await _rows(sf, "SELECT symbol, quantity FROM positions WHERE symbol LIKE 'SNDK%'")
    assert sorted((r.symbol, r.quantity) for r in rows) == [("SNDK.NASDAQ", 60.0), ("SNDK.US", 60.0)]
    gross = await ex._gross_exposure_usd()
    assert gross == pytest.approx(12_000.0), "one 60-share holding counted twice"
    assert len(calls["stops"]) >= 1
    await bus.stop()


@pytest.mark.asyncio
async def test_R10_no_broker_stop_for_crypto_the_only_real_positions_so_far(monkeypatch):
    """_stop_enabled requires is_us_equity (execution_agent.py:998-1003). Every real
    Alpaca fill in the pre-reset ledger was crypto (BTC/ETH/XRP/SOL/DOGE-USD, 10 fills,
    $71,478): none of the owner's actual positions gets a broker-side stop; the worker
    (60-min staleness window, write-time timestamps -- test_R5) is the only layer."""
    await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    calls = _fake_broker(monkeypatch, ex, equity=100_000, cash=90_000, positions=[])
    assert ex._stop_enabled("BTC-USD", "CRYPTO") is False
    assert ex._stop_enabled("ETH-USD", "CRYPTO") is False
    await ex._sync_broker_stop("BTC-USD", "CRYPTO")
    assert calls["stops"] == []
    assert ex._stop_enabled(SYM, EXCH) is True
    await bus.stop()


@pytest.mark.asyncio
async def test_R11_buy_guards_fail_open_when_the_cash_read_raises(monkeypatch):
    """_check_buy_guards returns None (= allow) if get_cash raises (execution_agent.py:737-742).
    A locked SQLite file at the wrong moment lets a BUY through with no cash check."""
    # NAV large so the notional / position / leverage caps pass; cash tiny so ONLY the
    # cash guard would block this $10k BUY.
    sf = await _fresh(cash_usd=1_000.0, nav=100_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading import execution_agent as ea
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    await _price(SYM, 100.0)
    ex = ExecutionAgent(bus)
    real_get_cash = ea.get_cash

    async def boom(session, currency):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(ea, "get_cash", boom)
    o = {"id": "o-1", "symbol": SYM, "exchange": EXCH, "quantity": 100, "side": "BUY",
         "ref_price": 100.0}
    try:
        reason = await ex._check_buy_guards(o, "PAPER")
    finally:
        monkeypatch.setattr(ea, "get_cash", real_get_cash)
    assert reason is None, "$10,000 BUY allowed against $1,000 cash because the read failed"
    await bus.stop()


# ==========================================================================
# Independent re-confirmation of the fixes (not trusting the inverted tests)
# ==========================================================================

@pytest.mark.asyncio
async def test_OK2_buy_arms_stop_worker_fires_and_exit_is_sized_exactly_once():
    """PAPER, full org chart on one bus: BUY fill arms stop at 80% of entry; a print at
    79 fires the worker; the exit is taken from horizon.signal.* and the approved copy
    is ignored -> exactly one ORDER_NEW; position 0, stopped_out=1."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.workers.position_worker import PositionMonitorWorker

    ex = ExecutionAgent(bus)
    for a in (RiskAgent(bus), PortfolioAgent(bus), ex):
        await a._subscribe()
    await _price(SYM, 100.0)
    buy = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 100, "broker": "PAPER", "mode": "PAPER_TRADING"})
    await ex._execute_order(buy)
    row = await _row(sf, "SELECT quantity, stop_loss_price, high_water_mark FROM positions"
                         " WHERE symbol=:s", s=SYM)
    assert row.quantity == 100 and row.stop_loss_price == pytest.approx(row.high_water_mark * 0.8)

    rec.msgs.clear()
    await _price(SYM, 79.0)
    await PositionMonitorWorker()._mark_to_market()
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"), timeout=8)
    assert len(rec.orders) == 1, "dual-channel exit sized exactly once"
    assert len(rec.on("horizon.risk.approved.")) == 1, "RiskAgent approved the exit (audit copy)"
    row = await _row(sf, "SELECT quantity, stopped_out FROM positions WHERE symbol=:s", s=SYM)
    assert row.quantity == 0 and row.stopped_out == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_OK2_halt_and_daily_loss_breach_let_sleeve_exits_fill_but_block_buys():
    # SOD NAV 100k; book = 84k cash + 100 sh @100 = 94k (-6%). After selling at ~90 the
    # book is ~93k, still in breach, so the BUY must be rejected by RiskAgent as well
    # as blocked by the halt.
    sf = await _fresh(cash_usd=84_000.0, nav=94_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.kv_store import get_kv_store

    async with sf() as s:
        await s.execute(text("INSERT INTO portfolio_snapshots (id, total_value, created_at, updated_at)"
                             " VALUES (:i, 100000, :w, :w)"),
                        {"i": "snap", "w": datetime.now(UTC) - timedelta(hours=1)})
        await s.commit()
    await get_kv_store().set("horizon:system:halted", "1")
    for a in (RiskAgent(bus), PortfolioAgent(bus), ExecutionAgent(bus)):
        await a._subscribe()
    await _position(sf, SYM, EXCH, 100, 100.0, stop=80.0, hwm=100.0)
    await _price(SYM, 90.0)

    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL, payload=_sleeve(-1, 0.0)))
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"), timeout=8)
    assert rec.on("horizon.execution.order.fill"), "exit filled while halted and -6% on the day"
    assert (await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)).quantity == 0

    rec.msgs.clear()
    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL, payload=_sleeve(+1, 0.15)))
    await rec.settle(lambda r: r.on("horizon.risk.rejected.") or r.orders, timeout=3)
    assert rec.orders == [] and rec.on("horizon.risk.rejected."), "BUY still gated"
    await bus.stop()


@pytest.mark.asyncio
async def test_OK2_guard_failure_means_no_broker_at_all_not_the_simulator(monkeypatch):
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    monkeypatch.setattr(settings, "alpaca_paper_mode", False)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    assert ex.broker_name == "NONE" and ex.broker is None
    await ex._subscribe()
    await _price(SYM, 100.0)
    await bus.publish(AgentMessage(
        sender_id="manual-cio", channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"symbol": SYM, "exchange": EXCH, "side": "BUY", "quantity": 10,
                 "order_type": "MARKET", "allocation_usd": 1000.0}))
    await rec.settle(lambda r: r.on("horizon.execution.order.update"))
    o = await _row(sf, "SELECT status, rejection_reason, broker FROM orders WHERE symbol=:s", s=SYM)
    assert o.status == "REJECTED" and "No execution broker" in o.rejection_reason
    assert (await _row(sf, "SELECT COUNT(*) AS c FROM fills")).c == 0
    await bus.stop()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A3D13FA74DDA - verify with scripts/authorship.py verify
