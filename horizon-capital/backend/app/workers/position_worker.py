"""PositionMonitorWorker -- mark-to-market and stop-loss enforcement.

Runs every 30 seconds and:
  1. Updates current_price and unrealized_pnl for all open positions.
  2. Computes portfolio NAV and publishes PORTFOLIO_UPDATE.
  3. Triggers stop-loss signals (LONG: SELL, SHORT: BUY) when price breaches stop.
  4. Skips stale prices (>60s old) with a warning.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.logging import get_logger

logger = get_logger("worker.position_monitor")

_INTERVAL_SECONDS = 30


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_bus():
    from app.core.runtime import get_bus
    return get_bus()


class PositionMonitorWorker:
    """Marks positions to market and enforces stop-losses every 30 seconds."""

    def __init__(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("position_monitor_started")
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.error("position_monitor_error", error=str(exc))
            await asyncio.sleep(_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------ #

    async def _cycle(self) -> None:
        kv = _get_kv()
        positions = await self._load_positions()
        if not positions:
            return

        total_unrealized = 0.0
        total_realized = 0.0
        positions_count = 0

        async with _get_session_factory()() as session:
            for pos in positions:
                symbol = pos["symbol"]
                qty = pos["quantity"]
                avg_entry = pos["avg_entry_price"]
                side = pos["side"]
                stop_loss_price = pos.get("stop_loss_price")

                # Look up latest price
                price_str = await kv.get(f"horizon:price:{symbol}")
                if price_str is None:
                    # Try raw symbol (strip exchange suffix)
                    raw = symbol.split(".")[0] if "." in symbol else symbol
                    price_str = await kv.get(f"horizon:price:{raw}")

                if price_str is None:
                    total_unrealized += pos.get("unrealized_pnl", 0.0)
                    total_realized += pos.get("realized_pnl", 0.0)
                    if qty > 0:
                        positions_count += 1
                    continue

                # Price staleness check (skip mark-to-market if >60s old)
                updated_at_str = await kv.get(f"horizon:price:{symbol}:updated_at")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str)
                        age = (datetime.now(UTC) - updated_at).total_seconds()
                        if age > 60:
                            logger.warning(
                                "stale_price_skipped",
                                symbol=symbol,
                                age_seconds=int(age),
                            )
                            total_unrealized += pos.get("unrealized_pnl", 0.0)
                            total_realized += pos.get("realized_pnl", 0.0)
                            if qty > 0:
                                positions_count += 1
                            continue
                    except (ValueError, TypeError):
                        pass

                try:
                    current_price = float(price_str)
                except (ValueError, TypeError):
                    continue

                # Compute unrealized PnL
                if side == "LONG":
                    unrealized = (current_price - avg_entry) * qty
                else:
                    unrealized = (avg_entry - current_price) * qty

                total_unrealized += unrealized
                total_realized += pos.get("realized_pnl", 0.0)
                if qty > 0:
                    positions_count += 1

                # Update position in DB
                await session.execute(
                    text(
                        """
                        UPDATE positions
                        SET current_price = :price,
                            unrealized_pnl = :pnl,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "price": current_price,
                        "pnl": unrealized,
                        "now": datetime.now(UTC),
                        "id": pos["id"],
                    },
                )

                # Stop-loss enforcement (LONG and SHORT)
                stop_triggered = False
                if side == "LONG" and qty > 0 and stop_loss_price is not None:
                    stop_triggered = current_price <= stop_loss_price
                elif side == "SHORT" and qty > 0 and stop_loss_price is not None:
                    stop_triggered = current_price >= stop_loss_price

                if stop_triggered:
                    logger.warning(
                        "stop_loss_triggered",
                        symbol=symbol,
                        side=side,
                        current_price=current_price,
                        stop_loss_price=stop_loss_price,
                    )
                    await self._emit_stop_loss_order(symbol, pos)

            await session.commit()

        # Read cash from KV for NAV
        usd_str = await kv.get("horizon:cash:usd")
        inr_str = await kv.get("horizon:cash:inr")
        cash_usd = float(usd_str or 0.0)
        cash_inr = float(inr_str or 0.0)

        # Convert INR cash to USD (rough: read forex rate)
        forex_str = await kv.get("horizon:forex:usd_inr")
        usd_inr = float(forex_str or 83.0)
        cash_usd_equiv = cash_usd + (cash_inr / usd_inr if usd_inr > 0 else 0)

        nav = cash_usd_equiv + total_unrealized + total_realized

        # Cache NAV
        await kv.set("horizon:portfolio:nav", str(nav))

        # Build position details list for dashboard
        position_details = []
        for pos in positions:
            if pos["quantity"] > 0:
                position_details.append({
                    "symbol": pos["symbol"],
                    "qty": pos["quantity"],
                    "avg_cost": pos["avg_entry_price"],
                    "current_price": pos.get("current_price") or pos["avg_entry_price"],
                    "unrealized_pnl": round(pos.get("unrealized_pnl", 0.0), 2),
                    "side": pos["side"],
                })

        # Publish PORTFOLIO_UPDATE
        from app.core.messaging import AgentMessage, MessageType
        bus = _get_bus()
        await bus.publish(
            AgentMessage(
                sender_id="position-monitor-worker",
                channel="horizon.portfolio.update",
                message_type=MessageType.PORTFOLIO_UPDATE,
                payload={
                    "nav": nav,
                    "cash": cash_usd_equiv,
                    "positions": position_details,
                    "total_unrealized": total_unrealized,
                    "total_realized": total_realized,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

        logger.info(
            "positions_marked_to_market",
            nav=f"{nav:.2f}",
            positions=positions_count,
            unrealized=f"{total_unrealized:.2f}",
        )

    async def _emit_stop_loss_order(self, symbol: str, pos: dict) -> None:
        """Emit ORDER_NEW directly for stop-loss (bypasses debate gate)."""
        from app.core.messaging import AgentMessage, MessageType
        bus = _get_bus()
        side = "SELL" if pos["side"] == "LONG" else "BUY"
        await bus.publish(
            AgentMessage(
                sender_id="position-monitor-worker",
                channel="horizon.execution.order.new",
                message_type=MessageType.ORDER_NEW,
                payload={
                    "signal_id": str(uuid.uuid4()),
                    "symbol": symbol,
                    "exchange": pos.get("exchange", ""),
                    "side": side,
                    "quantity": pos["quantity"],
                    "order_type": "MARKET",
                    "strategy_name": "stop_loss",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

    async def _load_positions(self) -> list[dict]:
        """Load all open positions from DB."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, symbol, exchange, side, quantity,
                           avg_entry_price, current_price,
                           unrealized_pnl, realized_pnl,
                           stop_loss_price
                    FROM positions
                    WHERE quantity > 0
                    """
                )
            )
            rows = result.fetchall()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "side": r.side,
                "quantity": r.quantity,
                "avg_entry_price": r.avg_entry_price,
                "current_price": r.current_price,
                "unrealized_pnl": r.unrealized_pnl,
                "realized_pnl": r.realized_pnl,
                "stop_loss_price": r.stop_loss_price,
            }
            for r in rows
        ]
