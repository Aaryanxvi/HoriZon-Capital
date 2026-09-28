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
  2. Fetches current price from the KV store.
  3. Updates current_price and unrealized_pnl in the database.
  4. If a stop_loss_price is set and breached, emits a synthetic SELL signal.

NAV is owned exclusively by PortfolioAgent (`horizon:portfolio:nav` KV key,
written from `_update_snapshot()` using `compute_unified_nav()`). This worker
must not write NAV — doing so created a stale-formula race with the snapshot
loop and produced inconsistent values across dashboard panels.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger("worker.position_monitor")

POLL_INTERVAL = 30  # seconds


class PositionMonitorWorker:
    """Marks positions to market and enforces stop-losses."""

    def __init__(self) -> None:
        self._running = False

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

    async def _mark_to_market(self) -> None:
        """Update all open positions with current prices and compute P&L."""
        kv = get_kv_store()

        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity,
                           avg_entry_price, stop_loss_price
                    FROM positions
                    WHERE quantity != 0
                """)
            )
            positions = result.fetchall()

        total_value = 0.0
        total_unrealized = 0.0
        stop_loss_signals: list[dict] = []

        for pos in (positions or []):
            # Try multiple key formats for price lookup
            raw_symbol = pos.symbol.split(".")[0] if "." in pos.symbol else pos.symbol
            price_str = (
                await kv.get(f"horizon:price:{raw_symbol}")
                or await kv.get(f"horizon:price:{pos.symbol}")
                or await kv.get(f"horizon:price:{pos.symbol}.{pos.exchange}")
            )

            if not price_str:
                continue

            current_price = float(price_str)
            if current_price <= 0:
                continue

            # Compute unrealized P&L
            if pos.side == "LONG":
                unrealized = (current_price - pos.avg_entry_price) * pos.quantity
            else:  # SHORT
                unrealized = (pos.avg_entry_price - current_price) * pos.quantity

            position_value = current_price * pos.quantity
            total_value += position_value
            total_unrealized += unrealized

            # Update the position
            async with _get_session_factory()() as session:
                await session.execute(
                    text("""
                        UPDATE positions
                        SET current_price = :price,
                            unrealized_pnl = :pnl,
                            updated_at = :now
                        WHERE id = :id
                    """),
                    {
                        "price": current_price,
                        "pnl": round(unrealized, 2),
                        "now": datetime.now(UTC),
                        "id": pos.id,
                    },
                )
                await session.commit()

            # Check stop-loss
            if (
                pos.stop_loss_price is not None
                and pos.stop_loss_price > 0
                and pos.side == "LONG"
                and current_price <= pos.stop_loss_price
            ):
                stop_loss_signals.append({
                    "symbol": pos.symbol,
                    "exchange": pos.exchange,
                    "quantity": pos.quantity,
                    "trigger_price": current_price,
                    "stop_price": pos.stop_loss_price,
                })

        # NAV is owned by PortfolioAgent's snapshot loop. This worker only
        # marks positions to market and surfaces stop-loss triggers below.
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        bus = get_bus()

        # Emit stop-loss sell signals
        for sl in stop_loss_signals:
            logger.warning("stop_loss_triggered",
                           symbol=sl["symbol"],
                           price=sl["trigger_price"],
                           stop=sl["stop_price"])
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
                            f"<= stop {sl['stop_price']:.2f}"
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
