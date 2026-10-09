# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-6783A2825981
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Executable proof for docs/REAL_MONEY_READINESS_AUDIT.md.

Every test drives the REAL agents over a real MemoryBus against the per-test
SQLite DB (conftest) and the PaperBroker / fakes. No network, no Alpaca, no LLM.

Naming: ``test_B*`` = BLOCKER finding, ``test_H*`` = HIGH finding,
``test_OK_*`` = control verified working, ``test_FACT_*`` = factual evidence.
A ``test_B*``/``test_H*`` test PASSING means the defect is REPRODUCED.
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
        for t in ("positions", "orders", "fills", "portfolio_snapshots",
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
                    stop: float | None = None, currency: str = "USD") -> None:
    async with sf() as s:
        await s.execute(text(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price,"
            " current_price, currency, stop_loss_price, created_at, updated_at)"
            " VALUES (:id, :sym, :ex, 'LONG', :q, :p, :p, :cur, :sl, :now, :now)"),
            {"id": str(uuid.uuid4()), "sym": symbol, "ex": exchange, "q": qty, "p": price,
             "cur": currency, "sl": stop, "now": datetime.now(UTC)})
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


def _stop_signal(symbol=SYM, exchange=EXCH, qty=100.0, px=80.0, stop=90.0) -> AgentMessage:
    """Exactly what PositionMonitorWorker publishes (position_worker.py:157-174)."""
    return AgentMessage(
        sender_id="position-monitor-worker", channel=f"horizon.signal.{symbol}",
        message_type=MessageType.SIGNAL,
        payload={"symbol": symbol, "exchange": exchange, "direction": -1, "strength": 1.0,
                 "strategy_name": "stop_loss",
                 "reasoning": f"Stop-loss triggered: price {px:.2f} <= stop {stop:.2f}"})


def _sleeve_sell(symbol=SYM, exchange=EXCH) -> dict:
    """A risk-off exit the way StrategyAgent emits it (strategy_agent.py:416-429)."""
    return {"signal_id": str(uuid.uuid4()), "symbol": symbol, "exchange": exchange,
            "direction": -1, "strength": 0.4, "strategy_name": "sleeve_system",
            "target_weight": 0.0, "previous_weight": 0.2, "stop_loss": None,
            "bar_timestamp": datetime.now(UTC).isoformat()}


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
async def test_B1_live_sleeves_never_arm_a_stop_so_stop_loss_is_dead_code():
    """strategy_agent.py:427 hardcodes stop_loss=None -> positions.stop_loss_price stays
    NULL -> position_worker.py:131 never fires. A 50% crash produces no exit."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.strategy.strategy_agent import StrategyAgent
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.workers.position_worker import PositionMonitorWorker

    strat = StrategyAgent(bus=bus)
    await strat._emit_signals_from_targets({"SPY.NYSE": 0.20})
    await rec.settle(lambda r: r.on("horizon.signal."))
    sig = rec.on("horizon.signal.")[0].payload
    assert sig["strategy_name"] == "sleeve_system"
    assert sig["stop_loss"] is None, "live sleeve signal carries no stop"

    # Same target again -> nothing (strategy only emits on >50bps drift; it never
    # re-emits a dropped/vetoed intent — see test_H4).
    n = len(rec.on("horizon.signal."))
    await strat._emit_signals_from_targets({"SPY.NYSE": 0.20})
    await asyncio.sleep(0.3)
    assert len(rec.on("horizon.signal.")) == n

    # Fill that BUY through the real execution path -> stop_loss_price is NULL.
    await _price("SPY.NYSE", 400.0)
    ex = ExecutionAgent(bus)
    order = await ex.order_manager.create_order({
        "symbol": "SPY.NYSE", "exchange": "NYSE", "order_type": "MARKET", "side": "BUY",
        "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING",
        "stop_loss": sig["stop_loss"]})
    await ex._execute_order(order)
    pos = await _row(sf, "SELECT quantity, stop_loss_price FROM positions WHERE symbol='SPY.NYSE'")
    assert pos.quantity == 10.0
    assert pos.stop_loss_price is None

    # Price halves. The stop-loss worker runs. Nothing happens.
    await _price("SPY.NYSE", 200.0)
    rec.msgs.clear()
    await PositionMonitorWorker()._mark_to_market()
    await asyncio.sleep(0.4)
    stops = [m for m in rec.on("horizon.signal.") if m.payload.get("strategy_name") == "stop_loss"]
    assert stops == [], "no stop-loss SELL after a 50% drawdown on the position"
    assert rec.on("horizon.risk.alert") == [], "and no alert either"
    await bus.stop()


@pytest.mark.asyncio
async def test_B2_daily_loss_limit_rejects_the_protective_sell():
    """risk_agent.py:103 applies _check_daily_loss_limit() to every signal, SELLs
    included. Once the day is -5% the book can no longer be exited via the pipeline."""
    sf = await _fresh(cash_usd=94_000.0, nav=94_000.0)
    bus, rec = await _bus()
    await _snapshot(sf, 100_000.0, datetime.now(UTC) - timedelta(hours=1))  # SOD baseline
    from app.agents.middle_office.risk.risk_agent import RiskAgent

    risk = RiskAgent(bus)
    await risk._subscribe()

    await bus.publish(_stop_signal())
    await rec.settle(lambda r: r.on("horizon.risk.rejected.") or r.on("horizon.risk.approved."))
    assert rec.on("horizon.risk.approved.") == [], "stop-loss SELL was NOT approved"
    rej = rec.on("horizon.risk.rejected.")
    assert rej and any("Daily loss" in v for v in rej[0].payload["violations"])

    # A normal sleeve risk-off exit is blocked the same way.
    rec.msgs.clear()
    await bus.publish(AgentMessage(sender_id="strategy-agent-1", channel=f"horizon.signal.{SYM}",
                                   message_type=MessageType.SIGNAL, payload=_sleeve_sell()))
    await rec.settle(lambda r: r.on("horizon.risk.rejected.") or r.on("horizon.risk.approved."))
    assert rec.on("horizon.risk.approved.") == []
    assert rec.on("horizon.risk.rejected.")
    await bus.stop()


@pytest.mark.asyncio
async def test_B3_kill_switch_freezes_the_book_instead_of_flattening_it():
    """At max drawdown risk_agent.py:255 sets halted=1. ExecutionAgent then blocks BUYs
    (execution_agent.py:460) and PortfolioAgent drops ALL new signals including sleeve
    exits (portfolio_agent.py:143). No liquidation is ever issued."""
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
    assert rec.orders == [], "kill switch emitted ZERO sell orders"

    # Sleeve says exit (risk-off). Portfolio agent drops it because halted.
    await _price(SYM, 100.0)
    pa = PortfolioAgent(bus)
    await pa._handle_signal(_sleeve_sell())
    await asyncio.sleep(0.3)
    assert rec.orders == [], "sleeve SELL discarded while halted — book frozen long"
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert pos.quantity == 700

    # Sticky: a manual `risk reset` (commands.py:699) is re-tripped 30s later.
    await kv.set("horizon:system:halted", "0")
    await risk._recompute_risk()
    assert await kv.get("horizon:system:halted") == "1"
    await bus.stop()


@pytest.mark.asyncio
async def test_B4_equity_mismatch_silently_detaches_risk_from_the_real_account(monkeypatch):
    """execution_agent.py:180-198: >2% NAV/equity gap -> broker swapped to PAPER for the
    session. Every later exit fills in the simulator; the real Alpaca book is untouched."""
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    assert ex.broker_name == "ALPACA"

    async def fake_account():
        return {"equity": 1_000_000.0, "cash": 1_000_000.0}
    real_calls: list[dict] = []

    async def real_execute(order):
        real_calls.append(order)
        return None
    monkeypatch.setattr(ex.alpaca_broker, "get_account", fake_account)
    monkeypatch.setattr(ex.alpaca_broker, "execute", real_execute)

    await ex._reconcile_alpaca_startup()
    assert ex.broker_name == "PAPER", "fell back to PAPER on 900% mismatch"
    assert any(m.payload.get("reason") == "alpaca_equity_mismatch" for m in rec.on("horizon.risk.alert"))

    # The owner holds AAPL for real. A protective SELL now goes to the simulator.
    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    order = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 100, "broker": ex._broker_for(SYM)[1], "mode": "PAPER_TRADING"})
    await ex._execute_order(order)
    st = await _row(sf, "SELECT status, broker FROM orders WHERE id=:i", i=order["id"])
    assert st.status == "FILLED" and st.broker == "PAPER"
    assert real_calls == [], "Alpaca never saw the exit"
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert pos.quantity == 0, "local book says flat; the real account is still long"

    # Same outcome when the broker is merely unreachable at boot.
    ex2 = ExecutionAgent(bus)

    async def down():
        return None
    monkeypatch.setattr(ex2.alpaca_broker, "get_account", down)
    await ex2._reconcile_alpaca_startup()
    assert ex2.broker_name == "PAPER"
    await bus.stop()


@pytest.mark.asyncio
async def test_B5_orchestrator_restart_double_subscribes_and_double_executes():
    """agent_orchestrator.py:248-275 relaunches agent.start() which re-runs _subscribe();
    MemoryBus.subscribe appends (memory_bus.py:40-44). After ONE restart every ORDER_NEW
    is handled twice by the same ExecutionAgent."""
    await _fresh()
    bus, rec = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.workers.agent_orchestrator import AgentOrchestrator, _AgentSlot

    orch = AgentOrchestrator(bus=bus)
    ex = ExecutionAgent(bus)

    async def crash_once():  # simulates any exception escaping run() (e.g. reconcile)
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
    assert len(bus._handlers["horizon.execution.order.new"]) == 2, "duplicate subscription"

    await bus.publish(AgentMessage(
        sender_id="portfolio-agent", channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={"symbol": SYM, "exchange": EXCH, "side": "BUY", "quantity": 10,
                 "order_type": "MARKET"}))
    await rec.settle(lambda r: len(created) >= 2, timeout=3)
    assert len(created) == 2, f"one ORDER_NEW produced {len(created)} orders"
    await bus.stop()


# ==========================================================================
# HIGH
# ==========================================================================

@pytest.mark.asyncio
async def test_H1_cio_halt_blocks_every_sell_and_is_not_persisted():
    """execution_agent.py:266-269 drops ALL ORDER_NEW (SELLs included) while
    _cio_halt_active; the flag lives only in memory."""
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
    assert ex._cio_halt_active

    await bus.publish(AgentMessage(sender_id="portfolio-agent", channel="horizon.execution.order.new",
                                   message_type=MessageType.ORDER_NEW,
                                   payload={"symbol": SYM, "exchange": EXCH, "side": "SELL",
                                            "quantity": 100, "order_type": "MARKET"}))
    await asyncio.sleep(0.5)
    n = await _row(sf, "SELECT COUNT(*) AS c FROM orders")
    assert n.c == 0, "protective SELL never even became an order row"

    # Restart => silently un-halted (nothing in KV, fresh instance is clear).
    assert await get_kv_store().get("horizon:system:halted") != "1"
    assert ExecutionAgent(bus)._cio_halt_active is False
    await bus.stop()


@pytest.mark.asyncio
async def test_H2_qty_dedup_swallows_a_repeated_stop_loss_sell(monkeypatch):
    """portfolio_agent.py:290-293: identical (symbol, SELL, qty) within 1 share is
    dropped. A stop that fires every 30s after a rejected first attempt is muted."""
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

    # Downstream rejected it (broker down, no fill). Position unchanged. Worker fires again.
    await pa._handle_signal(stop)
    await asyncio.sleep(0.3)
    assert len(rec.orders) == 1, "second stop-loss SELL deduped away"

    # _reconcile() is the only thing that clears the dedup map and it exits early
    # outside PAPER_TRADING (portfolio_agent.py:346).
    monkeypatch.setattr(settings, "system_mode", SystemMode.HUMAN_APPROVAL)
    pa._last_reconcile = datetime.now(UTC) - timedelta(hours=1)
    pa._sleeve_targets[SYM] = (0.0, EXCH)
    await pa._reconcile()
    await pa._handle_signal(stop)
    await asyncio.sleep(0.3)
    assert len(rec.orders) == 1
    await bus.stop()


@pytest.mark.asyncio
async def test_H3_stop_monitor_is_silent_without_a_price_and_trusts_a_stale_one():
    """position_worker.py:87-98 has no staleness check and `continue`s silently when
    the key is missing. Feed outage == stop quietly disarmed."""
    sf = await _fresh()
    bus, rec = await _bus()
    from app.workers.position_worker import PositionMonitorWorker

    await _position(sf, SYM, EXCH, 100, 100.0, stop=90.0)  # armed by hand
    w = PositionMonitorWorker()

    await w._mark_to_market()  # no price key at all
    await asyncio.sleep(0.3)
    assert rec.msgs == [], "no stop, no alert, no log-visible event on the bus"

    await _price(SYM, 80.0, age=timedelta(days=3))  # 3-day-old print below the stop
    await w._mark_to_market()
    await rec.settle(lambda r: r.on("horizon.signal."))
    sig = rec.on("horizon.signal.")[0].payload
    assert sig["strategy_name"] == "stop_loss" and "80.00" in sig["reasoning"]
    await bus.stop()


@pytest.mark.asyncio
async def test_H4_fully_autonomous_debate_veto_strands_a_risk_off_exit(monkeypatch):
    """FULLY_AUTONOMOUS buffers the exit until DEBATE_CONCLUSION; REJECTED/DEBOUNCED
    discards it (portfolio_agent.py:221) and nothing re-issues it: StrategyAgent already
    advanced _last_emitted_weight (strategy_agent.py:436) and _reconcile() is
    PAPER_TRADING-only (portfolio_agent.py:346)."""
    sf = await _fresh()
    bus, rec = await _bus()
    monkeypatch.setattr(settings, "system_mode", SystemMode.FULLY_AUTONOMOUS)
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    pa = PortfolioAgent(bus)

    sell = _sleeve_sell()
    await pa._handle_signal(sell)
    assert pa._pending_signals.get(SYM) == [sell]
    await pa._handle_debate_conclusion({"symbol": SYM, "decision": "REJECTED", "session_id": "d1"})
    await asyncio.sleep(0.3)
    assert rec.orders == [] and SYM not in pa._pending_signals

    pa._last_reconcile = datetime.now(UTC) - timedelta(hours=1)
    await pa._reconcile()
    await asyncio.sleep(0.3)
    assert rec.orders == [], "no retry path exists outside PAPER_TRADING"
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert pos.quantity == 100
    await bus.stop()


@pytest.mark.asyncio
async def test_H5_alpaca_timeout_marks_rejected_and_never_looks_again(monkeypatch):
    """alpaca_broker.py:208-210 returns None on any httpx error (incl. a read timeout
    AFTER the POST landed). execution_agent.py:534-555 then marks REJECTED with no
    broker_order_id, so _poll_open_orders never reconciles the live order."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    ex = ExecutionAgent(bus)
    calls = {"exec": 0, "status": 0}

    async def timed_out(order):
        calls["exec"] += 1
        return None

    async def status(_id):
        calls["status"] += 1
        return None
    monkeypatch.setattr(ex.alpaca_broker, "execute", timed_out)
    monkeypatch.setattr(ex.alpaca_broker, "get_order_status", status)

    await _position(sf, SYM, EXCH, 100, 100.0)
    await _price(SYM, 80.0)
    order = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex._execute_order(order)
    row = await _row(sf, "SELECT status, broker_order_id FROM orders WHERE id=:i", i=order["id"])
    assert row.status == "REJECTED" and row.broker_order_id is None
    assert calls["exec"] == 1, "no retry (correct) but also no status lookup by client_order_id"

    await ex._poll_open_orders()
    assert calls["status"] == 0, "orphan at the broker is never polled"
    await bus.stop()


@pytest.mark.asyncio
async def test_H6_partial_fill_then_cancel_drops_the_filled_shares(monkeypatch):
    """execution_agent.py:769-773: status 'canceled' with filled_qty>0 -> CANCELLED,
    no fill row, no position. The shares exist at the broker, not in the book."""
    sf = await _fresh()
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash

    ex = ExecutionAgent(bus)
    order = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex.order_manager.update_status(order["id"], "OPEN")
    await ex.order_manager.set_broker_order_id(order["id"], "bo-1")

    async def canceled_after_partial(_id):
        return {"status": "canceled", "filled_qty": 60.0, "filled_avg_price": 100.0}
    monkeypatch.setattr(ex.alpaca_broker, "get_order_status", canceled_after_partial)

    row = await _row(sf, "SELECT id, symbol, exchange, side, quantity, stop_price,"
                         " broker_order_id, created_at FROM orders WHERE id=:i", i=order["id"])
    await ex._poll_alpaca_order(row)

    st = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=order["id"])
    fills = await _row(sf, "SELECT COUNT(*) AS c FROM fills WHERE order_id=:i", i=order["id"])
    pos = await _row(sf, "SELECT COUNT(*) AS c FROM positions WHERE symbol=:s", s=SYM)
    async with sf() as s:
        cash = await get_cash(s, "USD")
    assert st.status == "CANCELLED" and fills.c == 0 and pos.c == 0
    assert cash == 100_000.0, "60 shares bought for real, $6,000 never left the local ledger"
    await bus.stop()


@pytest.mark.asyncio
async def test_H7_indian_symbol_is_sent_to_alpaca_as_a_us_ticker_and_inr_has_no_cash_guard(monkeypatch):
    """No Indian broker exists. execution_agent.py:124-130 routes every non-.POLY symbol
    to the session broker; alpaca_broker.py:136 strips '.NSE' -> 'INFY' (the NYSE ADR).
    execution_agent.py:471 skips the cash guard for NSE/BSE entirely."""
    sf = await _fresh(cash_usd=100_000.0)
    bus, rec = await _bus()
    from app.agents.front_office.trading import alpaca_broker as ab
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash

    # (a) Routing + symbol mangling under ALPACA.
    _alpaca_mode(monkeypatch)
    ex = ExecutionAgent(bus)
    assert ex._broker_for("INFY.NSE")[1] == "ALPACA"
    _FakeHTTP.captured.clear()
    monkeypatch.setattr(ab.httpx, "AsyncClient", _FakeHTTP)
    await ab.AlpacaBroker().execute({"id": "o1", "symbol": "INFY.NSE", "side": "BUY",
                                     "quantity": 10, "order_type": "MARKET"})
    sent = _FakeHTTP.captured[0]["json"]
    assert sent["symbol"] == "INFY" and "INR" not in str(sent)

    # (b) PAPER path: INR cash is 0, BUY on NSE still fills and drives INR negative.
    monkeypatch.setattr(settings, "execution_broker", "PAPER")
    ex = ExecutionAgent(bus)
    await _price("INFY.NSE", 1500.0, raw=False)
    order = await ex.order_manager.create_order({
        "symbol": "INFY.NSE", "exchange": "NSE", "order_type": "MARKET", "side": "BUY",
        "quantity": 10, "broker": "PAPER", "mode": "PAPER_TRADING"})
    await ex._execute_order(order)
    st = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=order["id"])
    async with sf() as s:
        inr = await get_cash(s, "INR")
    assert st.status == "FILLED" and inr < -14_000, f"INR went to {inr:.0f} with no guard"
    await bus.stop()


@pytest.mark.asyncio
async def test_H8_dead_risk_agent_also_kills_protective_exits():
    """PortfolioAgent only listens on horizon.risk.approved.* (portfolio_agent.py:92).
    With RiskAgent DEAD (3 strikes, agent_orchestrator.py:250-257) stop-loss SELLs
    published on horizon.signal.* go nowhere."""
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
    await asyncio.sleep(0.6)
    assert rec.orders == []
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert pos.quantity == 100
    await bus.stop()


@pytest.mark.asyncio
async def test_B6_simulator_fills_land_in_the_broker_mirror_ledger_and_reconcile_is_report_only(monkeypatch):
    """There is ONE ledger (positions/cash_balances have no broker/account column,
    local_storage.py:111-115, 212-228). After a PAPER fallback (execution_agent.py:173,
    :197) PaperBroker fills are settled into it (_settle_fill :578-660). On the next
    boot _reconcile_alpaca_startup only emits an alert (:201-234, "never mutates local
    state"), so the phantom row survives — and the naked-short guard (:817-829) then
    lets a SELL for it reach the real broker because it only checks the local table."""
    sf = await _fresh(cash_usd=100_000.0, nav=100_000.0)
    bus, rec = await _bus()
    _alpaca_mode(monkeypatch)
    from app.agents.front_office.trading.execution_agent import ExecutionAgent
    from app.core.cash import get_cash

    # Session 1: Alpaca down at boot -> PAPER for the session -> a BUY fills in the
    # simulator and is booked in the only ledger there is.
    ex = ExecutionAgent(bus)

    async def down():
        return None
    monkeypatch.setattr(ex.alpaca_broker, "get_account", down)
    await ex._reconcile_alpaca_startup()
    assert ex.broker_name == "PAPER"
    await _price(SYM, 100.0)
    buy = await ex.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "BUY",
        "quantity": 100, "broker": ex._broker_for(SYM)[1], "mode": "PAPER_TRADING"})
    await ex._execute_order(buy)
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    o = await _row(sf, "SELECT broker, status FROM orders WHERE id=:i", i=buy["id"])
    async with sf() as s:
        cash = await get_cash(s, "USD")
    assert pos.quantity == 100 and o.broker == "PAPER" and o.status == "FILLED"
    assert cash < 90_100, "simulated purchase debited the ledger that mirrors the real account"

    # Session 2 (restart): Alpaca is back, equity matches local NAV so the session
    # stays ALPACA, but the broker holds nothing. Reconcile: alert only, row kept.
    ex2 = ExecutionAgent(bus)
    assert ex2.broker_name == "ALPACA"
    calls = {"positions": 0}

    async def account():
        return {"equity": 100_000.0, "cash": 100_000.0}

    async def no_positions():
        calls["positions"] += 1
        return []
    sent: list[dict] = []

    async def real_execute(order):
        sent.append(order)
        return None  # broker rejects (nothing to sell) — or, on a margin account, opens a short
    monkeypatch.setattr(ex2.alpaca_broker, "get_account", account)
    monkeypatch.setattr(ex2.alpaca_broker, "get_positions", no_positions)
    monkeypatch.setattr(ex2.alpaca_broker, "execute", real_execute)
    rec.msgs.clear()
    await ex2._reconcile_alpaca_startup()
    assert ex2.broker_name == "ALPACA"
    mism = [m for m in rec.on("horizon.risk.alert")
            if m.payload.get("reason") == "alpaca_position_mismatch"]
    assert mism and mism[0].payload["mismatches"][0]["broker_qty"] == 0.0
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert pos.quantity == 100, "report-only: phantom position survives reconciliation"

    # A protective SELL for the phantom goes to the REAL broker with no broker-side
    # position check (only crypto has _clamp_to_available, alpaca_broker.py:138-145).
    calls["positions"] = 0
    sell = await ex2.order_manager.create_order({
        "symbol": SYM, "exchange": EXCH, "order_type": "MARKET", "side": "SELL",
        "quantity": 100, "broker": "ALPACA", "mode": "PAPER_TRADING"})
    await ex2._execute_order(sell)
    assert sent and sent[0]["side"] == "SELL" and sent[0]["quantity"] == 100
    assert calls["positions"] == 0, "naked-short guard consulted the local table only"
    st = await _row(sf, "SELECT status FROM orders WHERE id=:i", i=sell["id"])
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert st.status == "REJECTED" and pos.quantity == 100, "and the phantom is still there for the next 30s retry"
    await bus.stop()


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
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
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
    sf = await _fresh(cash_usd=100_000.0)
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
    r = await place("BUY", 10_000)  # $1M vs $100k cash
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
async def test_OK_alpaca_guard_refuses_live_url_and_non_paper(monkeypatch):
    bus, _ = await _bus()
    from app.agents.front_office.trading.execution_agent import ExecutionAgent

    _alpaca_mode(monkeypatch)
    monkeypatch.setattr(settings, "alpaca_base_url", "https://api.alpaca.markets")
    assert ExecutionAgent(bus).broker_name == "PAPER"
    monkeypatch.setattr(settings, "alpaca_base_url", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(settings, "alpaca_paper_mode", False)
    assert ExecutionAgent(bus).broker_name == "PAPER"
    await bus.stop()


@pytest.mark.asyncio
async def test_OK_alpaca_order_carries_client_order_id(monkeypatch):
    from app.agents.front_office.trading import alpaca_broker as ab

    _FakeHTTP.captured.clear()
    monkeypatch.setattr(ab.httpx, "AsyncClient", _FakeHTTP)
    await ab.AlpacaBroker().execute({"id": "local-123", "symbol": SYM, "side": "BUY",
                                     "quantity": 1, "order_type": "MARKET"})
    assert _FakeHTTP.captured[0]["json"]["client_order_id"] == "local-123"


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
    pos = await _row(sf, "SELECT quantity FROM positions WHERE symbol=:s", s=SYM)
    assert n.c == 1 and pos.quantity == 10
    await bus.stop()


@pytest.mark.asyncio
async def test_FACT_local_mode_bypasses_auth():
    from app.dependencies import get_current_user
    user = await get_current_user(credentials=None)
    assert user["role"] == "cio"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 6783A2825981 - verify with scripts/authorship.py verify
