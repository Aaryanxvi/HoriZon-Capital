# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-29C3F9DCE4AF
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""PositionMonitorWorker -- marks positions to market and enforces stop-losses.

Runs every 30 seconds:
  1. Loads all open positions from the database.
  2. Fetches the current price AND its timestamp from the KV store. A missing
     or stale print (see ``_is_stale``) is NOT acted on: the symbol is skipped
     and a RISK_ALERT ``stale_price`` is raised (throttled per symbol).
  3. Updates current_price and unrealized_pnl in the database.
  4. Ratchets the long's high-water mark and the trailing stop derived from it
     (stop = HWM x (1 - STOP_LOSS_TRAIL_PCT)); a stop never moves down.
  5. If the price is at/below the stop, emits a synthetic SELL signal
     (``strategy_name="stop_loss"``) that PortfolioAgent sizes as a full exit.

This is the second stop layer. On ALPACA the ExecutionAgent also rests a GTC
trailing_stop at the broker; here is what protects a PAPER book, and an
ALPACA book whenever the broker stop is missing.

NAV is owned exclusively by PortfolioAgent (`horizon:portfolio:nav` KV key,
written from `_update_snapshot()` using `compute_unified_nav()`). This worker
must not write NAV.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.agents.front_office.trading.order_manager import trailing_stop_price
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger("worker.position_monitor")

POLL_INTERVAL = 30  # seconds
# A print older than this during the regular session is not a live price.
STALE_OPEN_SEC = 15 * 60
# 24/7 venues (crypto, Polymarket): their feeds poll every 1-60 min.
STALE_24X7_SEC = 60 * 60
# Outside US hours the last print must be from the last session's close.
CLOSE_GRACE = timedelta(minutes=30)
STALE_ALERT_EVERY_SEC = 30 * 60


def _et_offset_hours(now: datetime) -> int:
    """Same DST approximation as strategy_agent._is_us_market_open."""
    m, d = now.month, now.day
    return -4 if (3, 8) <= (m, d) < (11, 1) else -5


def _last_us_close(now: datetime) -> datetime:
    """UTC instant of the most recent weekday 16:00 ET at or before ``now``.

    ponytail: no holiday calendar -- on a US holiday this points at the
    holiday's 16:00, so the Friday print reads as stale until the next
    session's first tick. Alert only, no action: nothing trades that day.
    """
    off = timedelta(hours=_et_offset_hours(now))
    et = now + off
    close = et.replace(hour=16, minute=0, second=0, microsecond=0)
    if close > et:
        close -= timedelta(days=1)
    while close.weekday() >= 5:
        close -= timedelta(days=1)
    return close - off


def _is_24x7(symbol: str, exchange: str) -> bool:
    return exchange in ("CRYPTO", "POLY") or symbol.endswith(("-USD", "-USDT", ".POLY"))


def _is_stale(ts: datetime | None, symbol: str, exchange: str, now: datetime | None = None) -> bool:
    """True when the print cannot be trusted as the current price."""
    from app.agents.front_office.strategy.strategy_agent import _is_us_market_open

    now = now or datetime.now(UTC)
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (now - ts).total_seconds()
    if _is_24x7(symbol, exchange):
        return age > STALE_24X7_SEC
    if _is_us_market_open(now):
        return age > STALE_OPEN_SEC
    return ts < _last_us_close(now) - CLOSE_GRACE


class PositionMonitorWorker:
    """Marks positions to market and enforces stop-losses."""

    def __init__(self) -> None:
        self._running = False
        self._stale_alerted_at: dict[str, float] = {}

    async def run(self) -> None:
        self._running = True
        logger.info("position_monitor_worker.started")
        try:
            while self._running:
                try:
                    await self._mark_to_market()
                except Exception as exc:
                    logger.error("position_monitor_error", error=str(exc))
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False

    @staticmethod
    async def _lookup_price(kv, symbol: str, exchange: str) -> tuple[float, datetime | None]:
        """(price, timestamp) from the first KV key that holds a price."""
        raw_symbol = symbol.split(".")[0] if "." in symbol else symbol
        for key in (f"horizon:price:{raw_symbol}", f"horizon:price:{symbol}",
                    f"horizon:price:{symbol}.{exchange}"):
            price_str = await kv.get(key)
            if not price_str:
                continue
            try:
                price = float(price_str)
            except (TypeError, ValueError):
                continue
            ts = None
            ts_str = await kv.get(f"{key}:ts")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    ts = None
            return price, ts
        return 0.0, None

    async def _alert_stale(self, bus, symbol: str, ts: datetime | None, price: float) -> None:
        """RISK_ALERT stale_price, at most once per symbol per 30 min."""
        from app.core.messaging import AgentMessage, MessageType

        now_mono = time.monotonic()
        if now_mono - self._stale_alerted_at.get(symbol, -1e9) < STALE_ALERT_EVERY_SEC:
            return
        self._stale_alerted_at[symbol] = now_mono
        age = None if ts is None else int((datetime.now(UTC) - ts).total_seconds())
        logger.error("stale_price_stop_not_evaluated", symbol=symbol, age_seconds=age,
                     price=price)
        await bus.publish(AgentMessage(
            sender_id="position-monitor-worker",
            channel="horizon.risk.alert",
            message_type=MessageType.RISK_ALERT,
            payload={
                "reason": "stale_price",
                "symbol": symbol,
                "age_seconds": age,
                "last_price": price or None,
                "action": "stop-loss NOT evaluated for this symbol until a fresh print arrives",
                "severity": "HIGH",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        ))

    async def _mark_to_market(self) -> None:
        """Update all open positions with current prices and compute P&L."""
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        kv = get_kv_store()
        bus = get_bus()

        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity,
                           avg_entry_price, stop_loss_price, high_water_mark
                    FROM positions
                    WHERE quantity != 0
                """)
            )
            positions = result.fetchall()

        total_value = 0.0
        total_unrealized = 0.0
        stop_loss_signals: list[dict] = []
        now = datetime.now(UTC)

        for pos in (positions or []):
            current_price, ts = await self._lookup_price(kv, pos.symbol, pos.exchange)
            if current_price <= 0 or _is_stale(ts, pos.symbol, pos.exchange, now):
                await self._alert_stale(bus, pos.symbol, ts, current_price)
                continue

            # Compute unrealized P&L
            if pos.side == "LONG":
                unrealized = (current_price - pos.avg_entry_price) * pos.quantity
            else:  # SHORT
                unrealized = (pos.avg_entry_price - current_price) * pos.quantity

            position_value = current_price * pos.quantity
            total_value += position_value
            total_unrealized += unrealized

            # Trailing stop: ratchet the HWM on a new high and lift the stop with
            # it. The stop never moves down, and an explicit (signal) stop that
            # sits higher is kept.
            hwm = pos.high_water_mark
            stop = pos.stop_loss_price
            if pos.side == "LONG" and (hwm is None or current_price > hwm):
                hwm = current_price
                trail = trailing_stop_price(hwm)
                if trail is not None and (stop is None or trail > stop):
                    stop = trail

            async with _get_session_factory()() as session:
                await session.execute(
                    text("""
                        UPDATE positions
                        SET current_price = :price,
                            unrealized_pnl = :pnl,
                            high_water_mark = :hwm,
                            stop_loss_price = :stop,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "price": current_price,
                        "pnl": round(unrealized, 2),
                        "hwm": hwm,
                        "stop": stop,
                        "now": now,
                        "id": pos.id,
                    },
                )
                await session.commit()

            # Check stop-loss
            if (
                stop is not None
                and stop > 0
                and pos.side == "LONG"
                and current_price <= stop
            ):
                stop_loss_signals.append({
                    "symbol": pos.symbol,
                    "exchange": pos.exchange,
                    "quantity": pos.quantity,
                    "trigger_price": current_price,
                    "stop_price": stop,
                    "hwm": hwm,
                })

        # NAV is owned by PortfolioAgent's snapshot loop. This worker only
        # marks positions to market and surfaces stop-loss triggers below.

        # Emit stop-loss sell signals
        for sl in stop_loss_signals:
            logger.warning("stop_loss_triggered",
                           symbol=sl["symbol"],
                           price=sl["trigger_price"],
                           stop=sl["stop_price"],
                           hwm=sl["hwm"])
            await bus.publish(
                AgentMessage(
                    sender_id="position-monitor-worker",
                    channel=f"horizon.signal.{sl['symbol']}",
                    message_type=MessageType.SIGNAL,
                    payload={
                        "symbol": sl["symbol"],
                        "exchange": sl["exchange"],
                        "direction": -1,
                        "strength": 1.0,
                        "strategy_name": "stop_loss",
                        "reasoning": (
                            f"Stop-loss triggered: price {sl['trigger_price']:.2f} "
                            f"<= stop {sl['stop_price']:.2f} (HWM {sl['hwm']:.2f})"
                        ),
                    },
                )
            )

        logger.debug(
            "positions_marked_to_market",
            count=len(positions),
            total_value=f"{total_value:.2f}",
            unrealized=f"{total_unrealized:.2f}",
        )
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 29C3F9DCE4AF - verify with scripts/authorship.py verify
