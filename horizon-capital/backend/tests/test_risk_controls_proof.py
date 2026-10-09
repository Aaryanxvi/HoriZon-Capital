# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-6783A2825981
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Regression suite for docs/REAL_MONEY_READINESS_AUDIT.md.

Originally every ``test_B*``/``test_H*`` here REPRODUCED a defect. Each was
inverted when its fix landed (see the audit's "Fixes" section); a test named
``test_B*``/``test_H*`` passing now means the control WORKS. Nothing was
deleted -- every proof became a regression test.

Every test drives the REAL agents over a real MemoryBus against the per-test
SQLite DB (conftest) and the PaperBroker / fakes. No network, no Alpaca, no LLM.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.config import SystemMode, settings
from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType

SYM, EXCH = "AAPL.NASDAQ", "NASDAQ"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class Recorder:
    """Subscribe to everything on a bus and remember it."""

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
        """Wait until ``pred(self)`` holds, or ``timeout`` elapses (then just return)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
            if pred is not None and pred(self):
                await asyncio.sleep(0.2)  # let trailing emits land
                return
        return


async def _bus() -> tuple[MemoryBus, Recorder]:
    bus = MemoryBus()
    rec = Recorder()
    await bus.subscribe("horizon.*", rec)
    await bus.start_listening()
    import app.core.runtime as rt
    rt._bus = bus  # workers resolve the bus through runtime.get_bus()
    return bus, rec


async def _fresh(cash_usd: float = 100_000.0, nav: float | None = None):
    """Clean DB + KV for one test; returns the session factory."""
    from app.core.cash import mirror_to_kv, set_cash
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db, local_session_factory

    await init_local_db()
    async with local_session_factory() as s:
        for t in ("positions", "orders", "fills", "portfolio_snapshots", "alert_history",
                  "pending_approvals", "kv_cache", "risk_metrics", "agent_messages"):
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


async def _price(symbol: str, px: float, age: timedelta | None = None, raw: bool = True) -> None:
    """Write the price keys the way the live feeds do (full symbol + bare ticker)."""
    from app.core.kv_store import get_kv_store
    kv = get_kv_store()
    ts = (datetime.now(UTC) - (age or timedelta(0))).isoformat()
    await kv.set(f"horizon:price:{symbol}", str(px))
    await kv.set(f"horizon:price:{symbol}:ts", ts)
    if raw and "." in symbol:
        base = symbol.split(".")[0]
        await kv.set(f"horizon:price:{base}", str(px))
        await kv.set(f"horizon:price:{base}:ts", ts)


async def _position(sf, symbol: str, exchange: str, qty: float, price: float,
                    stop: float | None = None, currency: str = "USD",
                    hwm: float | None = None, stop_order_id: str | None = None) -> None:
    async with sf() as s:
        await s.execute(text(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price,"
            " current_price, currency, stop_loss_price, high_water_mark, stop_order_id,"
            " created_at, updated_at)"
            " VALUES (:id, :sym, :ex, 'LONG', :q, :p, :p, :cur, :sl, :hwm, :soid, :now, :now)"),
            {"id": str(uuid.uuid4()), "sym": symbol, "ex": exchange, "q": qty, "p": price,
             "cur": currency, "sl": stop, "hwm": hwm, "soid": stop_order_id,
             "now": datetime.now(UTC)})
        await s.commit()


async def _snapshot(sf, total: float, when: datetime) -> None:
    async with sf() as s:
        await s.execute(text(
            "INSERT INTO portfolio_snapshots (id, total_value, created_at, updated_at)"
            " VALUES (:id, :t, :w, :w)"),
            {"id": str(uuid.uuid4()), "t": total, "w": when})
        await s.commit()


async def _row(sf, sql: str, **params):
    async with sf() as s:
        return (await s.execute(text(sql), params)).fetchone()


async def _pos(sf, symbol=SYM):
    return await _row(sf, "SELECT quantity, stop_loss_price, high_water_mark, stop_order_id,"
                          " stopped_out, side FROM positions WHERE symbol=:s", s=symbol)


def _stop_signal(symbol=SYM, exchange=EXCH, qty=100.0, px=80.0, stop=90.0) -> AgentMessage:
    """Exactly what PositionMonitorWorker publishes."""
    return AgentMessage(
        sender_id="position-monitor-worker", channel=f"horizon.signal.{symbol}",
        message_type=MessageType.SIGNAL,
        payload={"symbol": symbol, "exchange": exchange, "direction": -1, "strength": 1.0,
                 "strategy_name": "stop_loss",
                 "reasoning": f"Stop-loss triggered: price {px:.2f} <= stop {stop:.2f}"})


def _sleeve(direction: int, symbol=SYM, exchange=EXCH, target=0.0, prev=0.2) -> dict:
    """A sleeve signal the way StrategyAgent emits it."""
    return {"signal_id": str(uuid.uuid4()), "symbol": symbol, "exchange": exchange,
            "direction": direction, "strength": 0.4, "strategy_name": "sleeve_system",
            "target_weight": target, "previous_weight": prev, "stop_loss": None,
            "bar_timestamp": datetime.now(UTC).isoformat()}


def _sleeve_sell(symbol=SYM, exchange=EXCH) -> dict:
    return _sleeve(-1, symbol, exchange, target=0.0, prev=0.2)


def _order_msg(side: str, qty: float, symbol=SYM, exchange=EXCH, sender="portfolio-agent",
               **extra) -> AgentMessage:
    return AgentMessage(
        sender_id=sender, channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"symbol": symbol, "exchange": exchange, "side": side, "quantity": qty,
                 "order_type": "MARKET", **extra})


def _alpaca_mode(monkeypatch) -> None:
    """Satisfy _alpaca_guard_ok() with fake creds; never reaches the network here."""
    monkeypatch.setattr(settings, "alpaca_api_key", "test-key")
    monkeypatch.setattr(settings, "alpaca_api_secret", "test-secret")
    monkeypatch.setattr(settings, "alpaca_paper_mode", True)
    monkeypatch.setattr(settings, "alpaca_base_url", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(settings, "execution_broker", "ALPACA")
    # PaperBroker prefers Alpaca's live trade when creds exist — keep tests offline.
    from app.data_layer import alpaca_quotes

    async def _none(_symbol):
        return None
    monkeypatch.setattr(alpaca_quotes, "get_latest_price", _none)


class FakeAlpaca:
    """Scriptable stand-in for the AlpacaBroker methods ExecutionAgent calls.

    Records every call in ``calls`` (name, *args). Orders POSTed via
    ``execute`` fill in full unless ``execute_result`` says otherwise; resting
    stops are tracked in ``stops`` and can be marked filled by a test.
    """

    def __init__(self, *, broker_qty: float | None = None) -> None:
        self.calls: list[tuple] = []
        self.execute_result = "fill"   # "fill" | "accept" | None | dict
        self.stops: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.lookup: dict | None = {"found": False}
        self.broker_qty = broker_qty
        self.positions: list[dict] | None = []
        self.account: dict | None = {"equity": 100_000.0, "cash": 100_000.0}

    def install(self, ex, monkeypatch) -> None:
        b = ex.alpaca_broker
        for name in ("execute", "place_trailing_stop", "cancel_and_wait", "get_order_status",
                     "get_order_by_client_id", "get_position_qty", "get_positions",
                     "get_account", "cancel_order"):
            monkeypatch.setattr(b, name, getattr(self, name))

    async def execute(self, order):
        self.calls.append(("execute", order["side"], float(order["quantity"]), order["id"]))
        r = self.execute_result
        if r is None:
            return None
        if isinstance(r, dict):
            return r
        boid = f"bo-{len(self.orders) + 1}"
        filled = float(order["quantity"]) if r == "fill" else 0.0
        px = float(order.get("limit_price") or 100.0)
        self.orders[boid] = {"broker_order_id": boid, "status": "filled" if filled else
                             "accepted", "filled_qty": filled, "filled_avg_price": px,
                             "qty": float(order["quantity"])}
        return {"order_id": order["id"], "broker_order_id": boid, "filled_qty": filled,
                "fill_price": px if filled else 0.0, "commission": 0.0, "slippage": 0.0,
                "broker": "ALPACA", "alpaca_status": self.orders[boid]["status"]}

    async def place_trailing_stop(self, symbol, qty, trail_percent, client_order_id):
        self.calls.append(("stop", symbol, qty, trail_percent))
        boid = f"stop-{len(self.stops) + 1}"
        self.stops[boid] = {"broker_order_id": boid, "status": "accepted", "qty": float(qty),
                            "filled_qty": 0.0, "filled_avg_price": 0.0, "type": "trailing_stop"}
        return dict(self.stops[boid])

    async def cancel_and_wait(self, boid, timeout_sec=5.0):
        self.calls.append(("cancel", boid))
        st = self.stops.get(boid) or self.orders.get(boid)
        if st and st["status"] not in ("filled", "canceled"):
            st["status"] = "canceled"
        return dict(st) if st else None

    async def cancel_order(self, boid):
        self.calls.append(("cancel_order", boid))
        return True

    async def get_order_status(self, boid):
        self.calls.append(("status", boid))
        st = self.stops.get(boid) or self.orders.get(boid)
        return dict(st) if st else None

    async def get_order_by_client_id(self, cid):
        self.calls.append(("lookup", cid))
        return None if self.lookup is None else dict(self.lookup)

    async def get_position_qty(self, symbol):
        self.calls.append(("broker_qty", symbol))
        return self.broker_qty

    async def get_positions(self):
        return None if self.positions is None else list(self.positions)

    async def get_account(self):
        return None if self.account is None else dict(self.account)

    def fill_stop(self, boid: str, qty: float, price: float) -> None:
        self.stops[boid].update({"status": "filled", "filled_qty": qty, "filled_avg_price": price})


def _alpaca_ex(bus, monkeypatch, **kw):
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    ex = ExecutionAgent(bus)
    assert ex.broker_name == "ALPACA"
    ex._broker_ok = True  # as after a successful startup sync
    fake = FakeAlpaca(**kw)
    fake.install(ex, monkeypatch)
    return ex, fake


class _FakeHTTP:
    """Stand-in for httpx.AsyncClient that records the POST and answers 422."""
    captured: list[dict] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeHTTP.captured.append({"url": url, "json": json})

        class R:
            status_code = 422
            text = "fake"

            def json(self):
                return {}
        return R()


# ==========================================================================
# BLOCKERS
# ==========================================================================

@pytest.mark.asyncio
async def test_B1_trailing_stop_is_armed_on_fill_ratchets_with_the_hwm_and_fires():
    """Every long gets a 20% trailing stop from its high-water mark (owner
    decision). The sleeve signal still carries no explicit stop -- the stop is
    system-wide, not per signal. PAPER path: worker is the only layer."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.strategy.strategy_agent import StrategyAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.workers.position_worker import PositionMonitorWorker

    strat = StrategyAgent(bus=bus)
    await strat._emit_signals_from_targets({"SPY.NYSE": 0.20})
    await rec.settle(lambda r: r.on("horizon.signal."))
    sig = rec.on("horizon.signal.")[0].payload
    assert sig["strategy_name"] == "sleeve_system" and sig["stop_loss"] is None

    # Fill a BUY through the real execution path -> stop + HWM are armed.
    await _price("SPY.NYSE", 400.0)
    ex = ExecutionAgent(bus)
    order = await ex.order_manager.create_order({
        "symbol": "SPY.NYSE", "exchange": "NYSE", "order_type": "MARKET", "side": "BUY",
        "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING", "stop_loss": None})
    await ex._execute_order(order)
    pos = await _pos(sf, "SPY.NYSE")
    assert pos.quantity == 10.0
    assert pos.high_water_mark == pytest.approx(400.0, rel=1e-3)   # fill price (+impact)
    assert pos.stop_loss_price == pytest.approx(pos.high_water_mark * 0.8, rel=1e-6)

    # Price rallies: HWM and stop ratchet up. Pullback above the stop: nothing.
    w = PositionMonitorWorker()
    await _price("SPY.NYSE", 450.0)
    await w._mark_to_market()
    pos = await _pos(sf, "SPY.NYSE")
    assert pos.high_water_mark == 450.0 and pos.stop_loss_price == pytest.approx(360.0)
    await _price("SPY.NYSE", 420.0)
    rec.msgs.clear()
    await w._mark_to_market()
    await asyncio.sleep(0.3)
    pos = await _pos(sf, "SPY.NYSE")
    assert pos.high_water_mark == 450.0 and pos.stop_loss_price == pytest.approx(360.0)
    assert [m for m in rec.on("horizon.signal.") if m.payload.get("strategy_name") == "stop_loss"] == []

    # Through the stop: the worker fires and the whole pipeline closes it.
    for a in (RiskAgent(bus), PortfolioAgent(bus), ExecutionAgent(bus)):
        await a._subscribe()
    await _price("SPY.NYSE", 355.0)
    await w._mark_to_market()
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"), timeout=8)
    fills = rec.on("horizon.execution.order.fill")
    assert len(fills) == 1 and fills[0].payload["side"] == "SELL"
    assert fills[0].payload["filled_qty"] == 10 and fills[0].payload["strategy_name"] == "stop_loss"
    pos = await _pos(sf, "SPY.NYSE")
    assert pos.quantity == 0 and pos.stopped_out == 1
    assert pos.stop_loss_price is None and pos.high_water_mark is None
    await bus.stop()


@pytest.mark.asyncio
async def test_B1_stopped_out_name_is_not_rebought_by_reconcile_until_a_fresh_buy_signal():
    """Without this the 15-min reconciler would buy the name straight back
    (target still 20%) and the stop would be theatre."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    await _price(SYM, 100.0)
    pa = PortfolioAgent(bus)
    await _position(sf, SYM, EXCH, 100, 100.0, stop=90.0)
    await pa._handle_signal(_sleeve(1, target=0.2, prev=0.0))  # records the target
    await rec.settle(lambda r: r.orders)
    rec.msgs.clear()
    await _price(SYM, 80.0)
    await pa._handle_signal(_stop_signal().payload)
    await rec.settle(lambda r: r.orders)
    assert rec.orders[0].payload["side"] == "SELL"
    # Simulate the fill's bookkeeping (ExecutionAgent sets stopped_out on a stop fill).
    async with sf() as s:
        await s.execute(text("UPDATE positions SET quantity=0, side='FLAT', stopped_out=1"
                             " WHERE symbol=:s"), {"s": SYM})
        await s.commit()
    rec.msgs.clear()
    pa._last_reconcile = datetime.now(UTC) - timedelta(hours=1)
    await pa._reconcile()
    await asyncio.sleep(0.3)
    assert rec.orders == [], "reconcile re-bought a stopped-out name"

    # A fresh sleeve BUY re-enters (the flag is cleared by that BUY's fill).
    await pa._handle_signal(_sleeve(1, target=0.2, prev=0.0))
    await rec.settle(lambda r: r.orders)
    assert rec.orders and rec.orders[0].payload["side"] == "BUY"
    await bus.stop()


@pytest.mark.asyncio
async def test_B1_alpaca_rests_a_gtc_trailing_stop_cancels_it_before_sells_and_books_its_fill(
    monkeypatch,
):
    """ALPACA: whole-share BUY -> trailing_stop(20%, gtc) rests at the broker;
    a strategy SELL cancels it first (Alpaca reserves the shares), then
    re-arms for the remainder; a broker-side stop fill is booked exactly once."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=10.0)
    await _price(SYM, 100.0)

    await ex._handle_new_order(_order_msg("BUY", 10.7, allocation_usd=1070.0))
    o = await _row(sf, "SELECT quantity, status FROM orders")
    assert o.quantity == 10.0 and o.status == "FILLED", "rounded DOWN to whole shares"
    pos = await _pos(sf)
    assert pos.quantity == 10 and pos.stop_order_id == "stop-1"
    assert ("stop", SYM, 10, 20.0) in fake.calls

    # Strategy SELL 4: cancel stop-1 BEFORE the SELL hits the broker, re-arm 6.
    fake.calls.clear()
    await ex._handle_new_order(_order_msg("SELL", 4))
    names = [c[0] for c in fake.calls]
    assert names.index("cancel") < names.index("execute"), fake.calls
    assert fake.calls[0] == ("cancel", "stop-1")
    assert ("stop", SYM, 6, 20.0) in fake.calls
    pos = await _pos(sf)
    assert pos.quantity == 6 and pos.stop_order_id == "stop-2"

    # The broker's stop fires (6 @ 70). Poll books it once; a second poll is a no-op.
    fake.fill_stop("stop-2", 6.0, 70.0)
    await ex._poll_broker_stops()
    await ex._poll_broker_stops()
    pos = await _pos(sf)
    assert pos.quantity == 0 and pos.stopped_out == 1 and pos.stop_order_id is None
    stop_orders = await _row(sf, "SELECT COUNT(*) AS c, SUM(quantity) AS q FROM orders"
                                 " WHERE broker_order_id='stop-2'")
    fills = await _row(sf, "SELECT COUNT(*) AS c, SUM(filled_qty) AS q FROM fills f"
                           " JOIN orders o ON o.id=f.order_id WHERE o.broker_order_id='stop-2'")
    assert stop_orders.c == 1 and fills.c == 1 and fills.q == 6
    from app.core.cash import get_cash
    async with sf() as s:
        cash = await get_cash(s, "USD")
    assert cash == pytest.approx(100_000 - 10 * 100 + 4 * 100 + 6 * 70)
    assert rec.alerts("broker_stop_filled")
    await bus.stop()


@pytest.mark.asyncio
async def test_B1_alpaca_missing_broker_stop_is_armed_by_the_poller_or_alerted(monkeypatch):
    """A position with no resting stop (restart, broker cancelled it, placement
    failed) gets one from the 5s poller; if Alpaca refuses, the owner hears it."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=10.0)
    await _position(sf, SYM, EXCH, 10, 100.0)  # no stop_order_id
    await ex._poll_broker_stops()
    assert (await _pos(sf)).stop_order_id == "stop-1"
    assert ("stop", SYM, 10, 20.0) in fake.calls

    # Broker-side cancel (e.g. corporate action): detected, re-armed.
    fake.stops["stop-1"]["status"] = "canceled"
    await ex._poll_broker_stops()
    assert (await _pos(sf)).stop_order_id == "stop-2"

    # Placement refused: HIGH alert, worker remains the only layer, retried later.
    async def refuse(symbol, qty, trail_percent, client_order_id):
        return None
    monkeypatch.setattr(ex.alpaca_broker, "place_trailing_stop", refuse)
    await _position(sf, "MSFT.NASDAQ", EXCH, 5, 100.0)
    await ex._poll_broker_stops()
    assert (await _pos(sf, "MSFT.NASDAQ")).stop_order_id is None
    assert rec.alerts("broker_stop_missing")[0].payload["symbol"] == "MSFT.NASDAQ"
    await bus.stop()


@pytest.mark.asyncio
async def test_B1_alpaca_stop_that_fills_during_the_cancel_before_sell_is_booked_not_doubled(
    monkeypatch,
):
    """Race: strategy SELL arrives as the broker stop fires. The cancel comes
    back 'filled'; we book the stop fill and refuse the SELL (nothing left)."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=0.0)
    fake.stops["stop-9"] = {"broker_order_id": "stop-9", "status": "accepted", "qty": 10.0,
                            "filled_qty": 0.0, "filled_avg_price": 0.0}
    await _position(sf, SYM, EXCH, 10, 100.0, stop_order_id="stop-9")
    await _price(SYM, 79.0)
    fake.fill_stop("stop-9", 10.0, 79.5)  # fires just before our cancel lands

    await ex._handle_new_order(_order_msg("SELL", 10))
    sells = await _row(sf, "SELECT status, rejection_reason FROM orders"
                           " WHERE order_type='MARKET' AND side='SELL'")
    assert sells.status == "REJECTED" and "closed by the broker stop" in sells.rejection_reason
    assert [c for c in fake.calls if c[0] == "execute"] == [], "no second SELL went out"
    pos = await _pos(sf)
    assert pos.quantity == 0 and pos.stopped_out == 1
    fills = await _row(sf, "SELECT COUNT(*) AS c, SUM(filled_qty) AS q FROM fills")
    assert (fills.c, fills.q) == (1, 10.0)
    await bus.stop()


@pytest.mark.asyncio
async def test_B1_alpaca_sizing_is_whole_shares_for_us_equities_only(monkeypatch):
    sf = await _fresh(cash_usd=1_000_000.0, nav=1_000_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    await _price(SYM, 333.0)
    await _price("BTC-USD", 60_000.0, raw=False)
    pa = PortfolioAgent(bus)
    eq = await pa._compute_position_size(SYM, 1, EXCH, target_weight=0.10)
    assert eq["quantity"] == float(int(eq["quantity"])) and eq["quantity"] >= 1
    btc = await pa._compute_position_size("BTC-USD", 1, "CRYPTO", target_weight=0.10)
    assert btc["quantity"] != float(int(btc["quantity"])), "crypto stays fractional"
    await bus.stop()


@pytest.mark.asyncio
async def test_B2_daily_loss_breach_never_blocks_an_exit_but_still_blocks_buys():
    """The daily-loss limit exists to stop ADDING risk. Exits pass."""
    sf = await _fresh(cash_usd=94_000.0, nav=94_000.0)
    bus, rec = await _bus()
    await _snapshot(sf, 100_000.0, datetime.now(UTC) - timedelta(hours=1))  # SOD baseline
    from app.agents.middle_office.risk.risk_agent import RiskAgent

    risk = RiskAgent(bus)
    await risk._subscribe()

    await bus.publish(_stop_signal())
    await rec.settle(lambda r: r.on("horizon.risk.approved."))
    assert len(rec.on("horizon.risk.approved.")) == 1 and rec.on("horizon.risk.rejected.") == []

    rec.msgs.clear()
    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL, payload=_sleeve_sell()))
    await rec.settle(lambda r: r.on("horizon.risk.approved."))
    assert len(rec.on("horizon.risk.approved.")) == 1 and rec.on("horizon.risk.rejected.") == []

    rec.msgs.clear()
    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL,
                                   payload=_sleeve(1, target=0.2, prev=0.0)))
    await rec.settle(lambda r: r.on("horizon.risk.rejected.") or r.on("horizon.risk.approved."))
    rej = rec.on("horizon.risk.rejected.")
    assert rej and any("Daily loss" in v for v in rej[0].payload["violations"])
    assert rec.on("horizon.risk.approved.") == []
    await bus.stop()


@pytest.mark.asyncio
async def test_B3_kill_switch_blocks_buys_but_sleeve_exits_still_flow():
    """Owner decision: a halt stops NEW risk. It never auto-flattens and it
    never freezes a losing book -- exits keep working."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.kv_store import get_kv_store

    now = datetime.now(UTC)
    await _snapshot(sf, 100_000.0, now - timedelta(days=2))
    await _snapshot(sf, 70_000.0, now)  # -30% vs peak; limit is 25%
    await _position(sf, SYM, EXCH, 700, 100.0)

    risk = RiskAgent(bus)
    await risk._recompute_risk()
    await rec.settle(lambda r: any(m.payload.get("action") == "KILL_SWITCH_TRIGGERED"
                                   for m in r.on("horizon.risk.alert")))
    kv = get_kv_store()
    assert await kv.get("horizon:system:halted") == "1"
    assert rec.orders == [], "no auto-flatten (owner decision)"

    await _price(SYM, 100.0)
    pa = PortfolioAgent(bus)
    await pa._handle_signal(_sleeve(1, symbol="MSFT.NASDAQ", target=0.1, prev=0.0))
    await asyncio.sleep(0.3)
    assert rec.orders == [], "BUY must be blocked while halted"

    await pa._handle_signal(_sleeve_sell())
    await rec.settle(lambda r: r.orders)
    assert len(rec.orders) == 1 and rec.orders[0].payload["side"] == "SELL"
    assert rec.orders[0].payload["quantity"] == 700

    # Sticky: a manual `risk reset` is re-tripped 30s later while DD persists.
    await kv.set("horizon:system:halted", "0")
    await risk._recompute_risk()
    assert await kv.get("horizon:system:halted") == "1"
    await bus.stop()


@pytest.mark.asyncio
async def test_B4_broker_is_the_source_of_truth_and_the_simulator_is_never_a_fallback(monkeypatch):
    """900% equity mismatch: no PAPER swap. The local ledger is overwritten
    from Alpaca (positions, cash, NAV), the differences audited, and a
    protective SELL goes to the REAL broker. Unreachable: refuse BUYs."""
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=100.0)
    fake.account = {"equity": 1_000_000.0, "cash": 990_000.0}
    fake.positions = [{"symbol": "AAPL", "qty": 100.0, "avg_entry": 100.0, "current_price": 100.0,
                       "side": "LONG", "exchange": "NASDAQ", "asset_class": "us_equity"}]

    assert await ex._sync_from_broker() is True
    assert ex.broker_name == "ALPACA" and ex.broker is ex.alpaca_broker
    pos = await _pos(sf)
    assert pos.quantity == 100, "broker position materialised locally"
    from app.core.cash import get_cash
    from app.core.kv_store import get_kv_store
    async with sf() as s:
        assert await get_cash(s, "USD") == 990_000.0
    assert await get_kv_store().get("horizon:portfolio:nav") == "1000000.0"
    crit = rec.alerts("broker_sync_overwrote_local")
    assert crit and crit[0].payload["severity"] == "CRITICAL"
    assert {d["kind"] for d in crit[0].payload["diffs"]} == {"position", "cash"}
    audit = await _row(sf, "SELECT COUNT(*) AS c FROM alert_history WHERE rule_name='broker_sync'")
    assert audit.c == 1

    # The protective SELL reaches Alpaca, not the simulator.
    await _price(SYM, 80.0)
    await ex._handle_new_order(_order_msg("SELL", 100))
    st = await _row(sf, "SELECT status, broker FROM orders WHERE side='SELL'")
    assert st.status == "FILLED" and st.broker == "ALPACA"
    assert [c for c in fake.calls if c[0] == "execute"] == [("execute", "SELL", 100.0,
                                                            fake.calls[-1][3] if False else
                                                            [c for c in fake.calls if c[0] == "execute"][0][3])]

    # Unreachable at boot: still ALPACA, BUYs refused, exits still attempted.
    ex2, fake2 = _alpaca_ex(bus, monkeypatch, broker_qty=None)
    fake2.account = None
    ex2._broker_ok = True
    assert await ex2._sync_from_broker() is False
    assert ex2.broker_name == "ALPACA" and ex2._broker_ok is False
    assert rec.alerts("alpaca_unreachable")[0].payload["severity"] == "CRITICAL"
    await _position(sf, "MSFT.NASDAQ", EXCH, 10, 100.0)
    await _price("MSFT.NASDAQ", 100.0)
    await ex2._handle_new_order(_order_msg("BUY", 1, symbol="MSFT.NASDAQ"))
    await ex2._handle_new_order(_order_msg("SELL", 10, symbol="MSFT.NASDAQ"))
    b = await _row(sf, "SELECT status, rejection_reason FROM orders"
                       " WHERE symbol='MSFT.NASDAQ' AND side='BUY'")
    assert b.status == "REJECTED" and "unreachable" in b.rejection_reason
    assert ("execute", "SELL", 10.0, (await _row(
        sf, "SELECT id FROM orders WHERE symbol='MSFT.NASDAQ' AND side='SELL'")).id) in fake2.calls
    await bus.stop()


@pytest.mark.asyncio
async def test_B5_restart_subscribes_once_and_executes_once():
    """Bus subscription is idempotent per (channel, handler) and BaseAgent
    guards re-subscribe: a restarted ExecutionAgent handles one ORDER_NEW once."""
    await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.workers.agent_orchestrator import AgentOrchestrator, _AgentSlot

    orch = AgentOrchestrator(bus=bus)
    ex = ExecutionAgent(bus)

    async def crash_once():  # simulates any exception escaping run()
        raise RuntimeError("boom")
    created: list[dict] = []
    real_create = ex.order_manager.create_order

    async def spy_create(data, **kw):
        created.append(data)
        return await real_create(data, **kw)

    async def noop(order):
        return None
    ex.run = crash_once  # type: ignore[method-assign]
    ex.order_manager.create_order = spy_create  # type: ignore[method-assign]
    ex._execute_order = noop  # type: ignore[method-assign]

    slot = _AgentSlot(ex, department="front_office")
    await orch._launch_agent(slot)
    await asyncio.sleep(0.5)
    assert slot.task.done()
    assert len(bus._handlers["horizon.execution.order.new"]) == 1

    await orch._restart_agent(slot)  # exactly what _health_monitor does
    await asyncio.sleep(0.5)
    assert len(bus._handlers["horizon.execution.order.new"]) == 1, "duplicate subscription"

    await bus.publish(_order_msg("BUY", 10))
    await rec.settle(lambda r: len(created) >= 1, timeout=3)
    await asyncio.sleep(0.5)
    assert len(created) == 1, f"one ORDER_NEW produced {len(created)} orders"

    # Source-level guarantee for both buses.
    async def h(_m):
        return None
    mb = MemoryBus()
    await mb.subscribe("x", h)
    await mb.subscribe("x", h)
    assert mb._handlers["x"] == [h]

    from app.core.messaging import AgentBus

    class _PubSub:
        async def psubscribe(self, *a): ...
        async def subscribe(self, *a): ...

    class _Redis:
        def pubsub(self):
            return _PubSub()
    ab = AgentBus(redis=_Redis())
    await ab.subscribe("horizon.signal.*", h)
    await ab.subscribe("horizon.signal.*", h)
    assert ab._handlers["horizon.signal.*"] == [h]
    await bus.stop()


# ==========================================================================
# HIGH
# ==========================================================================

@pytest.mark.asyncio
async def test_H1_cio_halt_blocks_buys_only_and_is_persisted():
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.kv_store import get_kv_store

    ex = ExecutionAgent(bus)
    await ex._subscribe()
    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)

    await bus.publish(AgentMessage(sender_id="cio-agent-1", channel="horizon.executive.cio",
                                   message_type=MessageType.CIO_OVERRIDE,
                                   payload={"override_id": "o1", "actions": ["HALT"]}))
    await rec.settle(lambda r: ex._cio_halt_active)
    assert await get_kv_store().get("horizon:system:halted") == "1", "persisted"

    await bus.publish(_order_msg("BUY", 1, symbol="MSFT.NASDAQ"))
    await bus.publish(_order_msg("SELL", 100))
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"))
    rows = await _row(sf, "SELECT COUNT(*) AS c FROM orders")
    assert rows.c == 1, "the BUY never became an order; the SELL did"
    pos = await _pos(sf)
    assert pos.quantity == 0, "protective SELL filled during a CIO halt"

    # A fresh instance (restart) is still halted through the KV flag.
    ex2 = ExecutionAgent(bus)
    assert ex2._cio_halt_active is False
    o = await ex2.order_manager.create_order({
        "symbol": "MSFT.NASDAQ", "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 1, "broker": "PAPER", "mode": "PAPER_TRADING"})
    await ex2._execute_order(o)
    st = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE id=:i", i=o["id"])
    assert st.status == "REJECTED" and "halted" in st.rejection_reason

    await bus.publish(AgentMessage(sender_id="cio-agent-1", channel="horizon.executive.cio",
                                   message_type=MessageType.CIO_OVERRIDE,
                                   payload={"override_id": "o2", "actions": ["RESUME"]}))
    await rec.settle(lambda r: not ex._cio_halt_active)
    assert await get_kv_store().get("horizon:system:halted") == "0"
    await bus.stop()


@pytest.mark.asyncio
async def test_H2_qty_dedup_never_mutes_a_stop_loss_and_clears_on_rejection(monkeypatch):
    sf = await _fresh(cash_usd=50_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    pa = PortfolioAgent(bus)
    stop = _stop_signal().payload

    await pa._handle_signal(stop)
    await rec.settle(lambda r: r.orders)
    assert len(rec.orders) == 1 and rec.orders[0].payload["quantity"] == 100

    # Downstream rejected it (broker down). Position unchanged. Worker fires again.
    await pa._handle_signal(stop)
    await rec.settle(lambda r: len(r.orders) >= 2)
    assert len(rec.orders) == 2, "second stop-loss SELL must go out"

    # Sleeve SELLs: an identical re-size IS de-duped... until a rejection clears it.
    pa._last_emitted_qty.clear()
    await pa._handle_signal(_sleeve_sell())
    await rec.settle(lambda r: len(r.orders) >= 3)
    await pa._handle_signal(_sleeve_sell())
    await asyncio.sleep(0.3)
    assert len(rec.orders) == 3
    await pa.on_message(AgentMessage(
        sender_id="execution-agent", channel="horizon.execution.order.update",
        message_type=MessageType.ORDER_CANCEL,
        payload={"order_id": "x", "symbol": SYM, "side": "SELL", "status": "REJECTED"}))
    await pa._handle_signal(_sleeve_sell())
    await rec.settle(lambda r: len(r.orders) >= 4)
    assert len(rec.orders) == 4

    # Reconcile retries SELL-side drift in EVERY mode (HUMAN_APPROVAL -> pending).
    monkeypatch.setattr(settings, "system_mode", SystemMode.HUMAN_APPROVAL)
    pa._last_reconcile = datetime.now(UTC) - timedelta(hours=1)
    pa._sleeve_targets[SYM] = (0.0, EXCH)
    await pa._reconcile()
    await rec.settle(lambda r: r.on("horizon.execution.order.pending"))
    pend = rec.on("horizon.execution.order.pending")
    assert pend and pend[0].payload["side"] == "SELL" and pend[0].payload["quantity"] == 100
    await bus.stop()


@pytest.mark.asyncio
async def test_H3_stop_monitor_alerts_and_takes_no_action_on_missing_or_stale_prices():
    sf = await _fresh()
    bus, rec = await _bus()
    from app.workers.position_worker import PositionMonitorWorker

    await _position(sf, SYM, EXCH, 100, 100.0, stop=90.0, hwm=100.0)
    w = PositionMonitorWorker()

    await w._mark_to_market()  # no price key at all
    await rec.settle(lambda r: r.alerts("stale_price"))
    assert len(rec.alerts("stale_price")) == 1 and rec.on("horizon.signal.") == []

    await _price(SYM, 80.0, age=timedelta(days=3))  # 3-day-old print below the stop
    await w._mark_to_market()
    await asyncio.sleep(0.3)
    assert rec.on("horizon.signal.") == [], "stale print must not fire the stop"
    pos = await _pos(sf)
    assert pos.stop_loss_price == 90.0 and pos.high_water_mark == 100.0, "and must not ratchet"

    await _price(SYM, 80.0)  # fresh print
    await w._mark_to_market()
    await rec.settle(lambda r: r.on("horizon.signal."))
    assert rec.on("horizon.signal.")[0].payload["strategy_name"] == "stop_loss"
    await bus.stop()


@pytest.mark.asyncio
async def test_H4_fully_autonomous_exits_bypass_the_debate_gate_and_drift_is_retried(monkeypatch):
    sf = await _fresh()
    bus, rec = await _bus()
    monkeypatch.setattr(settings, "system_mode", SystemMode.FULLY_AUTONOMOUS)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.middle_office.debate_agent import DebateAgent

    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    pa = PortfolioAgent(bus)

    await pa._handle_signal(_sleeve_sell())
    await rec.settle(lambda r: r.orders)
    assert SYM not in pa._pending_signals and rec.orders[0].payload["side"] == "SELL"
    assert rec.orders[0].payload["quantity"] == 100

    # BUYs are still debate-gated; a REJECTED conclusion discards only the BUY.
    rec.msgs.clear()
    await pa._handle_signal(_sleeve(1, symbol="MSFT.NASDAQ", target=0.1, prev=0.0))
    assert pa._pending_signals.get("MSFT.NASDAQ")
    await pa._handle_debate_conclusion({"symbol": "MSFT.NASDAQ", "decision": "REJECTED",
                                        "session_id": "d1"})
    await asyncio.sleep(0.2)
    assert rec.orders == [] and "MSFT.NASDAQ" not in pa._pending_signals

    # The debate agent itself never queues an exit.
    da = DebateAgent(bus)
    await da.on_message(AgentMessage(sender_id="risk-agent", channel=f"horizon.risk.approved.{SYM}",
                                     message_type=MessageType.SIGNAL, payload=_sleeve_sell()))
    assert da._pending_signals.empty()

    # Reconcile retries SELL-side drift in FULLY_AUTONOMOUS (never BUY-side).
    pa._sleeve_targets[SYM] = (0.0, EXCH)
    pa._sleeve_targets["MSFT.NASDAQ"] = (0.1, EXCH)
    await _price("MSFT.NASDAQ", 100.0)
    pa._last_reconcile = datetime.now(UTC) - timedelta(hours=1)
    await pa._reconcile()
    await rec.settle(lambda r: r.orders)
    assert [o.payload["side"] for o in rec.orders] == ["SELL"]
    await bus.stop()


@pytest.mark.asyncio
async def test_H5_alpaca_timeout_is_resolved_by_client_order_id_before_rejecting(monkeypatch):
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=100.0)
    fake.execute_result = None  # POST timed out
    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)

    # (a) The order DID land: adopt its broker id, leave OPEN, poll it.
    fake.lookup = {"found": True, "broker_order_id": "bo-landed", "status": "accepted",
                   "filled_qty": 0.0, "filled_avg_price": 0.0}
    fake.orders["bo-landed"] = {"broker_order_id": "bo-landed", "status": "accepted",
                                "filled_qty": 0.0, "filled_avg_price": 0.0}
    o = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex._execute_order(o)
    row = await _row(sf, "SELECT status, broker_order_id FROM orders WHERE id=:i", i=o["id"])
    assert row.status == "OPEN" and row.broker_order_id == "bo-landed"
    assert [c for c in fake.calls if c[0] == "execute"].__len__() == 1, "no blind re-POST"
    fake.calls.clear()
    await ex._poll_open_orders()
    assert ("status", "bo-landed") in fake.calls

    # (b) Broker unreachable for the lookup too: stay OPEN, alert, resolve later.
    fake.lookup = None
    o2 = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 50, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex._execute_order(o2)
    row = await _row(sf, "SELECT status, broker_order_id FROM orders WHERE id=:i", i=o2["id"])
    assert row.status == "OPEN" and row.broker_order_id is None
    assert rec.alerts("alpaca_order_outcome_unknown")
    fake.lookup = {"found": True, "broker_order_id": "bo-late", "status": "filled",
                   "filled_qty": 50.0, "filled_avg_price": 81.0}
    await ex._poll_open_orders()
    row = await _row(sf, "SELECT status, broker_order_id FROM orders WHERE id=:i", i=o2["id"])
    assert row.status == "FILLED" and row.broker_order_id == "bo-late"
    assert (await _pos(sf)).quantity == 50

    # (c) Definitively not at the broker: REJECTED.
    fake.lookup = {"found": False}
    o3 = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 10, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex._execute_order(o3)
    row = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=o3["id"])
    assert row.status == "REJECTED"
    await bus.stop()


@pytest.mark.asyncio
async def test_H6_partial_fill_then_cancel_books_the_filled_shares_exactly_once(monkeypatch):
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch)
    from app.core.cash import get_cash

    order = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex.order_manager.update_status(order["id"], "OPEN")
    await ex.order_manager.set_broker_order_id(order["id"], "bo-1")
    fake.orders["bo-1"] = {"broker_order_id": "bo-1", "status": "canceled",
                           "filled_qty": 60.0, "filled_avg_price": 100.0}

    for _ in range(2):  # second poll must be a no-op
        await ex._poll_open_orders()

    st = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=order["id"])
    fills = await _row(sf, "SELECT COUNT(*) AS c, SUM(filled_qty) AS q FROM fills"
                           " WHERE order_id=:i", i=order["id"])
    pos = await _pos(sf)
    async with sf() as s:
        cash = await get_cash(s, "USD")
    assert st.status == "CANCELLED" and fills.c == 1 and fills.q == 60
    assert pos.quantity == 60 and cash == 94_000.0
    assert pos.stop_loss_price == pytest.approx(80.0) and pos.stop_order_id == "stop-1"
    await bus.stop()


@pytest.mark.asyncio
async def test_H7_indian_symbols_are_refused_under_alpaca_and_inr_cash_is_guarded(monkeypatch):
    sf = await _fresh(cash_usd=100_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading import alpaca_broker as ab
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash

    # (a) ALPACA: not routable; nothing is ever POSTed.
    _alpaca_mode(monkeypatch)
    ex = ExecutionAgent(bus)
    ex._broker_ok = True
    assert ex._broker_for("INFY.NSE", "NSE") == (None, "UNROUTABLE")
    assert ex._broker_for("INFY.NSE") == (None, "UNROUTABLE")
    _FakeHTTP.captured.clear()
    monkeypatch.setattr(ab.httpx, "AsyncClient", _FakeHTTP)
    await _price("INFY.NSE", 1500.0, raw=False)
    await ex._handle_new_order(_order_msg("BUY", 10, symbol="INFY.NSE", exchange="NSE"))
    st = await _row(sf, "SELECT status, rejection_reason FROM orders")
    assert st.status == "REJECTED" and "US-only" in st.rejection_reason
    assert _FakeHTTP.captured == []

    # (b) PAPER path: INR cash is 0 -> BUY on NSE is refused by the cash guard.
    monkeypatch.setattr(settings, "execution_broker", "PAPER")
    ex = ExecutionAgent(bus)
    order = await ex.order_manager.create_order({
        "symbol": "INFY.NSE", "exchange": "NSE", "order_type": "MARKET", "side": "BUY",
        "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING"})
    await ex._execute_order(order)
    st = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE id=:i", i=order["id"])
    async with sf() as s:
        inr = await get_cash(s, "INR")
    assert st.status == "REJECTED" and "Insufficient cash" in st.rejection_reason
    assert inr == 0.0
    await bus.stop()


@pytest.mark.asyncio
async def test_H8_protective_exits_flow_with_the_risk_agent_dead():
    """PortfolioAgent consumes exits straight from horizon.signal.*."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    pa, ex = PortfolioAgent(bus), ExecutionAgent(bus)
    await pa._subscribe()
    await ex._subscribe()

    await bus.publish(_stop_signal())
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"), timeout=8)
    assert len(rec.orders) == 1
    pos = await _pos(sf)
    assert pos.quantity == 0

    # A sleeve BUY on the raw channel is NOT taken without risk approval.
    rec.msgs.clear()
    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL,
                                   payload=_sleeve(1, target=0.2, prev=0.0)))
    await asyncio.sleep(0.5)
    assert rec.orders == []
    await bus.stop()


@pytest.mark.asyncio
async def test_H8_dead_risk_critical_agent_halts_buys_and_raises_critical():
    await _fresh()
    bus, rec = await _bus()
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.kv_store import get_kv_store
    from app.workers.agent_orchestrator import MAX_RETRIES, AgentOrchestrator, _AgentSlot

    orch = AgentOrchestrator(bus=bus)
    slot = _AgentSlot(RiskAgent(bus), department="middle_office")
    slot.retries = MAX_RETRIES
    await orch._restart_agent(slot)
    await rec.settle(lambda r: r.alerts("agent_dead"))
    assert slot.status == "DEAD"
    assert rec.alerts("agent_dead")[0].payload["severity"] == "CRITICAL"
    assert await get_kv_store().get("horizon:system:halted") == "1"
    await bus.stop()


@pytest.mark.asyncio
async def test_B6_phantom_positions_cannot_be_born_and_are_wiped_by_the_sync(monkeypatch):
    """No PAPER fallback => no phantom fills. A phantom row planted anyway is
    zeroed by the next sync, and a SELL for shares the broker does not hold is
    refused by the broker-verified reduce-only check."""
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=0.0)
    fake.account = None
    assert await ex._sync_from_broker() is False
    await _price(SYM, 100.0)
    await ex._handle_new_order(_order_msg("BUY", 100))
    assert (await _row(sf, "SELECT status FROM orders")).status == "REJECTED"
    assert await _pos(sf) is None, "nothing filled in a simulator"

    await _position(sf, SYM, EXCH, 100, 100.0)  # a phantom, planted
    fake.account = {"equity": 100_000.0, "cash": 100_000.0}
    fake.positions = []
    assert await ex._sync_from_broker() is True
    assert (await _pos(sf)).quantity == 0
    assert rec.alerts("broker_sync_overwrote_local")[0].payload["diffs"][0]["broker_qty"] == 0.0

    await _position(sf, "MSFT.NASDAQ", EXCH, 100, 100.0)  # local says 100, broker 0
    await _price("MSFT.NASDAQ", 100.0)
    rec.msgs.clear()
    await ex._handle_new_order(_order_msg("SELL", 100, symbol="MSFT.NASDAQ"))
    st = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE symbol='MSFT.NASDAQ'")
    assert st.status == "REJECTED" and "broker position" in st.rejection_reason
    assert [c for c in fake.calls if c[0] == "execute"] == []
    # ...and the phantom is reconciled away on the spot, so the stop worker's
    # 30s re-fire does not reject forever: next SELL is a plain naked short.
    assert (await _pos(sf, "MSFT.NASDAQ")).quantity == 0
    assert rec.alerts("broker_sync_overwrote_local")
    await ex._handle_new_order(_order_msg("SELL", 100, symbol="MSFT.NASDAQ"))
    st = await _row(sf, "SELECT rejection_reason FROM orders WHERE symbol='MSFT.NASDAQ'"
                        " ORDER BY created_at DESC LIMIT 1")
    assert "naked short" in st.rejection_reason
    await bus.stop()


@pytest.mark.asyncio
async def test_B6_simulator_orders_are_refused_in_a_real_session_and_rows_carry_their_broker(
    monkeypatch,
):
    """.POLY always routed to PaperBroker, even next to real Alpaca fills. In a
    real-broker session that is refused (+ alert); every fill/position row says
    which broker produced it."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    ex, fake = _alpaca_ex(bus, monkeypatch, broker_qty=10.0)
    assert ex._broker_for("PM-x.POLY", "POLY") == (None, "UNROUTABLE_SIM")
    await _price("PM-x.POLY", 0.6, raw=False)
    await ex._handle_new_order(_order_msg("BUY", 100, symbol="PM-x.POLY", exchange="POLY"))
    st = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE symbol='PM-x.POLY'")
    assert st.status == "REJECTED" and "Simulator" in st.rejection_reason
    assert rec.alerts("simulator_order_refused") and await _pos(sf, "PM-x.POLY") is None

    q = ("SELECT f.broker AS fb, p.broker AS pb FROM fills f JOIN orders o ON o.id=f.order_id"
         " JOIN positions p ON p.symbol=o.symbol WHERE o.symbol=:s")
    await _price(SYM, 100.0)
    await ex._handle_new_order(_order_msg("BUY", 10))
    r = await _row(sf, q, s=SYM)
    assert (r.fb, r.pb) == ("ALPACA", "ALPACA")

    monkeypatch.setattr(settings, "execution_broker", "PAPER")
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    await _price("MSFT.NASDAQ", 100.0)
    await ExecutionAgent(bus)._handle_new_order(_order_msg("BUY", 10, symbol="MSFT.NASDAQ"))
    r = await _row(sf, q, s="MSFT.NASDAQ")
    assert (r.fb, r.pb) == ("PAPER", "PAPER")
    await bus.stop()


@pytest.mark.asyncio
async def test_B6_nav_and_kill_switch_read_broker_equity_in_a_real_session(monkeypatch):
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.core.kv_store import get_kv_store

    ex, fake = _alpaca_ex(bus, monkeypatch)
    fake.account = {"equity": 70_000.0, "cash": 100_000.0}  # local arithmetic would say 100k
    await ex._sync_from_broker()
    pa = PortfolioAgent(bus)
    assert await pa._broker_equity() == 70_000.0
    await pa._update_snapshot()
    snap = await _row(sf, "SELECT total_value FROM portfolio_snapshots"
                          " ORDER BY created_at DESC LIMIT 1")
    assert snap.total_value == 70_000.0
    assert await get_kv_store().get("horizon:portfolio:nav") == "70000.0"

    await _snapshot(sf, 100_000.0, datetime.now(UTC) - timedelta(days=2))
    await RiskAgent(bus)._recompute_risk()  # -30% on BROKER equity -> kill switch
    assert await get_kv_store().get("horizon:system:halted") == "1"

    # A stale broker number is not trusted: local NAV stands in (loudly).
    await get_kv_store().set("horizon:broker:equity:ts",
                             (datetime.now(UTC) - timedelta(hours=1)).isoformat())
    assert await pa._broker_equity() is None
    await bus.stop()


@pytest.mark.asyncio
async def test_M8_leverage_cap_blocks_buys_beyond_max_leverage():
    sf = await _fresh(cash_usd=300_000.0, nav=100_000.0)  # margin-like: cash > NAV
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    await _price(SYM, 100.0)
    await _price("MSFT.NASDAQ", 100.0)
    await _position(sf, "MSFT.NASDAQ", EXCH, 900, 100.0)  # 0.90x gross
    await ex._handle_new_order(_order_msg("BUY", 150))  # -> 1.05x
    st = await _row(sf, "SELECT status, rejection_reason FROM orders")
    assert st.status == "REJECTED" and "Leverage cap" in st.rejection_reason
    await ex._handle_new_order(_order_msg("BUY", 90))  # -> 0.99x
    st = await _row(sf, "SELECT status FROM orders WHERE quantity=90")
    assert st.status == "FILLED"
    await bus.stop()


# ==========================================================================
# MEDIUM
# ==========================================================================

@pytest.mark.asyncio
async def test_M1_notional_cap_price_band_and_position_cap_reject_fat_fingers():
    sf = await _fresh(cash_usd=1_000_000.0, nav=1_000_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    await _price(SYM, 100.0)

    async def place(side, qty, **extra):
        await ex._handle_new_order(_order_msg(side, qty, **extra))
        return await _row(sf, "SELECT status, rejection_reason FROM orders"
                              " ORDER BY created_at DESC LIMIT 1")

    r = await place("BUY", 3_000)  # $300k > 25% of $1M
    assert r.status == "REJECTED" and "Notional cap" in r.rejection_reason
    r = await place("BUY", 1_000, allocation_usd=120_000.0)  # sized at $120 vs last $100
    assert r.status == "REJECTED" and "Price band" in r.rejection_reason
    await _position(sf, SYM, EXCH, 1_500, 100.0)  # 15% held
    r = await place("BUY", 1_000)  # -> 25% post-trade > 20% cap
    assert r.status == "REJECTED" and "Position cap" in r.rejection_reason
    r = await place("BUY", 400, allocation_usd=40_000.0)  # 19% post-trade, in band
    assert r.status == "FILLED"
    await bus.stop()


@pytest.mark.asyncio
async def test_M2_manual_repl_orders_pass_the_same_guards_and_reduce_only_sells_work_halted():
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.kv_store import get_kv_store

    ex = ExecutionAgent(bus)
    await ex._subscribe()
    await _price(SYM, 100.0)
    await _position(sf, SYM, EXCH, 50, 100.0)

    await bus.publish(_order_msg("BUY", 5_000, sender="manual-cio"))  # $500k vs $100k
    await rec.settle(lambda r: r.on("horizon.execution.order.update"))
    st = await _row(sf, "SELECT status, rejection_reason FROM orders WHERE side='BUY'")
    assert st.status == "REJECTED" and "cap" in st.rejection_reason.lower()

    await get_kv_store().set("horizon:system:halted", "1")
    await bus.publish(_order_msg("SELL", 60, sender="manual-cio"))  # more than held
    await bus.publish(_order_msg("SELL", 50, sender="manual-cio"))
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"))
    over = await _row(sf, "SELECT status, rejection_reason FROM orders"
                          " WHERE side='SELL' AND quantity=60")
    ok = await _row(sf, "SELECT status FROM orders WHERE side='SELL' AND quantity=50")
    assert over.status == "REJECTED" and "reduce-only" in over.rejection_reason
    assert ok.status == "FILLED" and (await _pos(sf)).quantity == 0
    await bus.stop()


@pytest.mark.asyncio
async def test_M3_kill_switch_persist_failure_is_logged_at_error(monkeypatch):
    await _fresh()
    from app.core import kv_store
    from app.core.kv_store import PersistentKVStore

    calls: list[tuple] = []

    class _Log:
        def error(self, *a, **k):
            calls.append(("error", a, k))

        def debug(self, *a, **k):
            calls.append(("debug", a, k))

        def info(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass
    monkeypatch.setattr(kv_store, "logger", _Log())

    def boom():
        raise RuntimeError("sqlite busy")
    import app.core.runtime as rt
    monkeypatch.setattr(rt, "get_session_factory", boom)
    await PersistentKVStore().set("horizon:system:halted", "1")
    assert calls and calls[0][0] == "error" and calls[0][1][0] == "kv_persist_error"


# ==========================================================================
# Controls verified working
# ==========================================================================

@pytest.mark.asyncio
async def test_OK_armed_stop_fills_end_to_end_in_paper_trading():
    """When a stop IS set, mode is PAPER_TRADING, no halt and no daily-loss breach,
    the plumbing works: worker -> Risk -> Portfolio -> Execution -> PaperBroker."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.agents.middle_office.risk.risk_agent import RiskAgent
    from app.workers.position_worker import PositionMonitorWorker

    for a in (RiskAgent(bus), PortfolioAgent(bus), ExecutionAgent(bus)):
        await a._subscribe()
    await _position(sf, SYM, EXCH, 100, 100.0, stop=90.0)
    await _price(SYM, 80.0)

    await PositionMonitorWorker()._mark_to_market()
    await rec.settle(lambda r: r.on("horizon.execution.order.fill"), timeout=8)
    fill = rec.on("horizon.execution.order.fill")
    assert fill and fill[0].payload["side"] == "SELL" and fill[0].payload["filled_qty"] == 100
    assert len(rec.orders) == 1, "risk-approved copy must not produce a second order"
    pos = await _pos(sf)
    assert pos.quantity == 0
    await bus.stop()


@pytest.mark.asyncio
async def test_OK_stop_loss_bypasses_halt_and_debate_gate_in_portfolio_agent(monkeypatch):
    sf = await _fresh()
    bus, rec = await _bus()
    monkeypatch.setattr(settings, "system_mode", SystemMode.FULLY_AUTONOMOUS)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.core.kv_store import get_kv_store

    await get_kv_store().set("horizon:system:halted", "1")
    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    await PortfolioAgent(bus)._handle_signal(_stop_signal().payload)
    await rec.settle(lambda r: r.orders)
    assert rec.orders and rec.orders[0].payload["side"] == "SELL"
    await bus.stop()


@pytest.mark.asyncio
async def test_OK_execution_guards_halt_buy_naked_short_cash_and_allow_sell():
    sf = await _fresh(cash_usd=100_000.0, nav=1_000_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.kv_store import get_kv_store

    ex = ExecutionAgent(bus)
    await _price(SYM, 100.0)

    async def place(side, qty):
        o = await ex.order_manager.create_order({
            "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": side,
            "quantity": qty, "broker": "PAPER", "mode": "PAPER_TRADING"})
        await ex._execute_order(o)
        return await _row(sf, "SELECT status, rejection_reason FROM orders WHERE id=:i", i=o["id"])

    r = await place("SELL", 10)
    assert r.status == "REJECTED" and "naked short" in r.rejection_reason
    r = await place("BUY", 2_000)  # $200k: 20% of NAV (in cap) but > $100k cash
    assert r.status == "REJECTED" and "Insufficient cash" in r.rejection_reason

    await get_kv_store().set("horizon:system:halted", "1")
    r = await place("BUY", 10)
    assert r.status == "REJECTED" and "halted" in r.rejection_reason
    await _position(sf, SYM, EXCH, 10, 100.0)
    r = await place("SELL", 10)
    assert r.status == "FILLED", "SELL allowed while halted at the execution layer"
    await bus.stop()


@pytest.mark.asyncio
async def test_OK_halt_flag_survives_restart():
    await _fresh()
    from app.core.kv_store import PersistentKVStore, get_kv_store

    await get_kv_store().set("horizon:system:halted", "1")
    fresh = PersistentKVStore()  # new process
    await fresh.restore()
    assert await fresh.get("horizon:system:halted") == "1"


@pytest.mark.asyncio
async def test_OK_alpaca_guard_refuses_live_url_and_non_paper_without_a_simulator(monkeypatch):
    bus, _ = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    _alpaca_mode(monkeypatch)
    monkeypatch.setattr(settings, "alpaca_base_url", "https://api.alpaca.markets")
    assert ExecutionAgent(bus).broker_name == "NONE"
    monkeypatch.setattr(settings, "alpaca_base_url", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(settings, "alpaca_paper_mode", False)
    assert ExecutionAgent(bus).broker_name == "NONE"
    await bus.stop()


@pytest.mark.asyncio
async def test_OK_alpaca_order_carries_client_order_id_and_whole_qty(monkeypatch):
    from app.agents.front_office.trading import alpaca_broker as ab

    _FakeHTTP.captured.clear()
    monkeypatch.setattr(ab.httpx, "AsyncClient", _FakeHTTP)
    await ab.AlpacaBroker().execute({"id": "local-123", "symbol": SYM, "side": "BUY",
                                     "quantity": 10.0, "order_type": "MARKET"})
    sent = _FakeHTTP.captured[0]["json"]
    assert sent["client_order_id"] == "local-123" and sent["qty"] == "10"
    _FakeHTTP.captured.clear()
    await ab.AlpacaBroker().place_trailing_stop(SYM, 10, 20.0, "stop-abc")
    sent = _FakeHTTP.captured[0]["json"]
    assert sent == {"symbol": "AAPL", "qty": "10", "side": "sell", "type": "trailing_stop",
                    "trail_percent": "20.0", "time_in_force": "gtc", "client_order_id": "stop-abc"}
    assert await ab.AlpacaBroker().place_trailing_stop(SYM, 0.7, 20.0, "x") is None


@pytest.mark.asyncio
async def test_OK_settle_fill_is_idempotent_on_terminal_status():
    sf = await _fresh()
    bus, _ = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    o = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING"})
    await ex.order_manager.update_status(o["id"], "OPEN")
    fill = {"filled_qty": 10.0, "fill_price": 100.0, "commission": 0.0, "slippage": 0.0}
    await ex._settle_fill(o, fill)
    await ex._settle_fill(o, fill)
    n = await _row(sf, "SELECT COUNT(*) AS c FROM fills WHERE order_id=:i", i=o["id"])
    pos = await _pos(sf)
    assert n.c == 1 and pos.quantity == 10
    await bus.stop()


@pytest.mark.asyncio
async def test_FACT_local_mode_bypasses_auth():
    from app.dependencies import get_current_user
    user = await get_current_user(credentials=None)
    assert user["role"] == "cio"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 6783A2825981 - verify with scripts/authorship.py verify
