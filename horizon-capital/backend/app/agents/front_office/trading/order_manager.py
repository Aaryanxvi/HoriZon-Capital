# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1EEAE49B869A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Order state machine and persistence layer."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import settings
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("execution.order_manager")


def trailing_stop_price(high_water_mark: float | None) -> float | None:
    """Stop level for a long: HWM x (1 - STOP_LOSS_TRAIL_PCT). None when disabled."""
    pct = float(settings.stop_loss_trail_pct or 0.0)
    if pct <= 0 or not high_water_mark or high_water_mark <= 0:
        return None
    return round(float(high_water_mark) * (1.0 - pct / 100.0), 6)


# Valid state transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"OPEN", "CANCELLED", "REJECTED"},
    "OPEN": {"FILLED", "PARTIAL", "CANCELLED", "REJECTED"},
    "PARTIAL": {"FILLED", "CANCELLED"},
    "FILLED": set(),      # terminal
    "CANCELLED": set(),   # terminal
    "REJECTED": set(),    # terminal
}


class OrderManager:
    """Manages order lifecycle: creation, status transitions, fills, and positions.

    Every mutation writes directly to the database so that the order book
    is always durable and queryable.
    """

    # ------------------------------------------------------------------ #
    # Session dispatch helper
    # ------------------------------------------------------------------ #

    async def _run_in_session(self, fn, session):
        """Run an async session-using callable in the caller's session, or
        in our own freshly-opened session with a commit at the end.

        ``fn`` must be an ``async def fn(s) -> X``. Returns whatever ``fn``
        returns. When ``session is None`` we manage the lifecycle (open,
        commit, close); otherwise the caller owns it and we never commit.
        """
        if session is None:
            async with _get_session_factory()() as s:
                result = await fn(s)
                await s.commit()
                return result
        return await fn(session)

    # ------------------------------------------------------------------ #
    # Order creation
    # ------------------------------------------------------------------ #

    async def create_order(self, order_data: dict, *, session=None) -> dict:
        """Insert a new order row and return its representation.

        Parameters
        ----------
        order_data:
            Must include: symbol, exchange, order_type, side, quantity, broker, mode.
            Optional: limit_price, stop_price, signal_id, debate_id.
        session:
            Optional caller-owned SQLAlchemy session.  When provided the method
            does NOT commit — the caller owns the transaction boundary.  When
            ``None`` (default) the method opens its own session and commits.

        Returns
        -------
        dict
            The created order (mirrors the ``orders`` table row).
        """
        order_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        async def _do(s):
            await s.execute(
                text(
                    """
                    INSERT INTO orders
                        (id, symbol, exchange, order_type, side, quantity,
                         limit_price, stop_price, status, broker, mode,
                         signal_id, debate_id, strategy_name, created_at, updated_at)
                    VALUES
                        (:id, :symbol, :exchange, :order_type, :side, :quantity,
                         :limit_price, :stop_price, 'PENDING', :broker, :mode,
                         :signal_id, :debate_id, :strategy_name, :now, :now)
                    """
                ),
                {
                    "id": order_id,
                    "symbol": order_data["symbol"],
                    "exchange": order_data["exchange"],
                    "order_type": order_data.get("order_type", "MARKET"),
                    "side": order_data["side"],
                    "quantity": order_data["quantity"],
                    "limit_price": order_data.get("limit_price"),
                    "stop_price": order_data.get("stop_price"),
                    "broker": order_data.get("broker", "PAPER"),
                    "mode": order_data.get("mode", "PAPER_TRADING"),
                    "signal_id": order_data.get("signal_id"),
                    "debate_id": order_data.get("debate_id"),
                    "strategy_name": order_data.get("strategy_name"),
                    "now": now,
                },
            )

        await self._run_in_session(_do, session)

        order = {
            **order_data,
            "id": order_id,
            "status": "PENDING",
            "created_at": now.isoformat(),
        }
        logger.info("order_created", order_id=order_id, symbol=order_data["symbol"])
        return order

    # ------------------------------------------------------------------ #
    # Status transitions
    # ------------------------------------------------------------------ #

    async def update_status(
        self,
        order_id: str,
        new_status: str,
        *,
        broker_order_id: str | None = None,
        rejection_reason: str | None = None,
        session=None,
    ) -> bool:
        """Transition an order to a new status.

        Parameters
        ----------
        session:
            Optional caller-owned session.  When provided, the method does NOT
            commit and passes the same session through to ``_get_status`` so
            that uncommitted writes made by the caller are visible.

        Returns True on success, False if the transition is invalid.
        """
        # Validate the transition before opening/using the write session so we
        # can return early without touching DB state.
        current_status = await self._get_status(order_id, session=session)
        if current_status is None:
            logger.warning("order_not_found", order_id=order_id)
            return False

        if new_status not in _VALID_TRANSITIONS.get(current_status, set()):
            logger.warning(
                "invalid_transition",
                order_id=order_id,
                current=current_status,
                requested=new_status,
            )
            return False

        now = datetime.now(UTC)

        async def _do(s):
            await s.execute(
                text(
                    """
                    UPDATE orders
                    SET status = :status,
                        broker_order_id = COALESCE(:broker_order_id, broker_order_id),
                        rejection_reason = COALESCE(:rejection_reason, rejection_reason),
                        updated_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "id": order_id,
                    "status": new_status,
                    "broker_order_id": broker_order_id,
                    "rejection_reason": rejection_reason,
                    "now": now,
                },
            )

        await self._run_in_session(_do, session)

        logger.info("order_status_updated", order_id=order_id, status=new_status)
        return True

    async def set_broker_order_id(
        self, order_id: str, broker_order_id: str, *, session=None,
    ) -> None:
        """Attach a broker order id without a status transition.

        Used when a broker (e.g. Alpaca) accepts an order but hasn't filled
        it yet — the order stays OPEN, so ``update_status``'s state-machine
        check (OPEN -> OPEN is not a valid transition) doesn't apply here.
        """
        now = datetime.now(UTC)

        async def _do(s):
            await s.execute(
                text(
                    "UPDATE orders SET broker_order_id = :boid, updated_at = :now"
                    " WHERE id = :id"
                ),
                {"id": order_id, "boid": broker_order_id, "now": now},
            )

        await self._run_in_session(_do, session)
        logger.info("broker_order_id_set", order_id=order_id, broker_order_id=broker_order_id)

    # ------------------------------------------------------------------ #
    # Fill recording
    # ------------------------------------------------------------------ #

    async def record_fill(
        self,
        order_id: str,
        qty: float,
        price: float,
        commission: float = 0.0,
        slippage: float = 0.0,
        *,
        broker: str | None = None,
        session=None,
    ) -> dict:
        """Record a fill against an order and return the fill record.

        Parameters
        ----------
        broker:
            Who produced the fill (PAPER / ALPACA / POLYMARKET) -- tagged on the
            row so simulated and real fills are tellable apart.
        session:
            Optional caller-owned session.  When provided, the method does NOT
            commit.
        """
        fill_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        async def _do(s):
            await s.execute(
                text(
                    """
                    INSERT INTO fills
                        (id, order_id, filled_qty, fill_price, commission,
                         slippage, filled_at, broker, created_at, updated_at)
                    VALUES
                        (:id, :order_id, :qty, :price, :commission,
                         :slippage, :now, :broker, :now, :now)
                    """
                ),
                {
                    "id": fill_id,
                    "order_id": order_id,
                    "qty": qty,
                    "price": price,
                    "commission": commission,
                    "slippage": slippage,
                    "broker": broker,
                    "now": now,
                },
            )

        await self._run_in_session(_do, session)

        logger.info(
            "fill_recorded",
            fill_id=str(fill_id),
            order_id=order_id,
            qty=qty,
            price=price,
        )
        return {
            "fill_id": str(fill_id),
            "order_id": order_id,
            "filled_qty": qty,
            "fill_price": price,
            "commission": commission,
            "slippage": slippage,
            "filled_at": now.isoformat(),
        }

    # ------------------------------------------------------------------ #
    # Position management
    # ------------------------------------------------------------------ #

    async def update_position(
        self,
        symbol: str,
        exchange: str,
        side: str,
        qty: float,
        price: float,
        stop_loss_price: float | None = None,
        *,
        commission: float = 0.0,
        stopped_out: bool = False,
        broker: str | None = None,
        session=None,
    ) -> None:
        """Upsert into the positions table after a fill.

        Parameters
        ----------
        symbol:  Instrument symbol.
        exchange:  Exchange identifier.
        side:  ``BUY`` or ``SELL``.
        qty:  Filled quantity.
        price:  Fill price.
        stop_loss_price:
            Explicit stop from the signal. When None and STOP_LOSS_TRAIL_PCT > 0
            a BUY arms/ratchets the trailing stop from the high-water mark.
        commission:
            Commission paid on this fill. Reduces realized_pnl on every fill
            (opening legs included), so lifetime realized_pnl == gross
            trading P&L minus all commissions paid — matching cash exactly.
        stopped_out:
            True when this SELL is a stop-loss exit: the flat row keeps a
            ``stopped_out=1`` marker so PortfolioAgent._reconcile does not buy
            the name straight back; the next BUY fill clears it.
        session:
            Optional caller-owned session.  When provided, the method does NOT
            commit.
        """
        now = datetime.now(UTC)

        # Determine currency from exchange
        currency = "INR" if exchange in ("NSE", "BSE") else "USD"

        async def _do(s):
            # Fetch existing position
            result = await s.execute(
                text(
                    "SELECT id, side, quantity, avg_entry_price, realized_pnl,"
                    " high_water_mark, stop_loss_price"
                    " FROM positions WHERE symbol = :sym AND exchange = :exch LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            existing = result.fetchone()

            if existing is None:
                # Create new position
                pos_side = "LONG" if side == "BUY" else "SHORT"
                hwm = price if side == "BUY" else None
                stop = stop_loss_price if stop_loss_price else trailing_stop_price(hwm)
                await s.execute(
                    text(
                        """
                        INSERT INTO positions
                            (id, symbol, exchange, side, quantity, avg_entry_price,
                             current_price, unrealized_pnl, realized_pnl,
                             weight_pct, currency, stop_loss_price, high_water_mark,
                             broker, created_at, updated_at)
                        VALUES
                            (:id, :symbol, :exchange, :side, :qty,
                             :price, :price, 0.0, :realized,
                             0.0, :currency, :stop_loss, :hwm,
                             :broker, :now, :now)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "exchange": exchange,
                        "side": pos_side,
                        "qty": qty,
                        "price": price,
                        "realized": -commission,
                        "currency": currency,
                        "stop_loss": stop,
                        "hwm": hwm,
                        "broker": broker,
                        "now": now,
                    },
                )
            else:
                # Update existing position
                old_qty = existing.quantity
                old_avg = existing.avg_entry_price
                old_realized = existing.realized_pnl or 0.0
                old_hwm = existing.high_water_mark
                new_hwm = old_hwm
                new_stop = stop_loss_price  # None -> keep/ratchet below
                new_stopped = None  # NULL unless this SELL is a stop exit

                if side == "BUY":
                    if existing.side == "LONG" or old_qty <= 0:
                        # Adding to long (or re-entering a flat/stopped-out row)
                        new_qty = old_qty + qty
                        new_avg = (
                            ((old_avg * old_qty) + (price * qty)) / new_qty
                            if new_qty > 0 else price
                        )
                        new_side = "LONG"
                        realized_delta = 0.0
                        # Fresh entry resets the HWM; an add ratchets it.
                        new_hwm = price if old_qty <= 0 else max(old_hwm or 0.0, price)
                        if not new_stop:
                            trail = trailing_stop_price(new_hwm)
                            prev = existing.stop_loss_price if old_qty > 0 else None
                            new_stop = max(prev or 0.0, trail or 0.0) or None
                    else:
                        # Covering short
                        new_qty = old_qty - qty
                        new_avg = old_avg
                        realized_delta = (old_avg - price) * min(qty, old_qty)
                        new_side = "SHORT" if new_qty > 0 else ("LONG" if new_qty < 0 else "FLAT")
                        new_qty = abs(new_qty)
                        if new_side == "LONG":
                            new_avg = price
                        new_stop = new_stop or existing.stop_loss_price
                elif side == "SELL":
                    if existing.side == "LONG":
                        # Selling long — clamp to held quantity. Oversized SELL
                        # used to silently flip to a short; that's blocked by
                        # execution's naked-short check but would bypass it here.
                        effective_qty = min(qty, old_qty)
                        new_qty = old_qty - effective_qty
                        new_avg = old_avg
                        realized_delta = (price - old_avg) * effective_qty
                        new_side = "LONG" if new_qty > 0 else "FLAT"
                        if new_qty <= 0:
                            # Flat: disarm. Keep the row (UNIQUE symbol/exchange)
                            # with the stopped-out marker if this was a stop.
                            new_hwm, new_stop = None, None
                            new_stopped = 1 if stopped_out else None
                        elif not new_stop:
                            new_stop = existing.stop_loss_price
                    else:
                        # Adding to short
                        new_qty = old_qty + qty
                        new_avg = (
                            ((old_avg * old_qty) + (price * qty)) / new_qty
                            if new_qty > 0 else price
                        )
                        new_side = "SHORT"
                        realized_delta = 0.0
                        new_stop = new_stop or existing.stop_loss_price
                else:
                    return

                new_realized = old_realized + realized_delta - commission
                if side == "BUY" and new_side == "LONG" and new_hwm is None:
                    new_hwm = price  # covering a short into a long
                flat = new_qty <= 0

                await s.execute(
                    text(
                        """
                        UPDATE positions
                        SET side = :side, quantity = :qty, avg_entry_price = :avg,
                            current_price = :price, realized_pnl = :realized,
                            stop_loss_price = :stop_loss,
                            high_water_mark = :hwm,
                            stop_order_id = CASE WHEN :flat THEN NULL ELSE stop_order_id END,
                            stopped_out = :stopped,
                            broker = COALESCE(:broker, broker),
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": existing.id,
                        "side": new_side,
                        "qty": new_qty,
                        "avg": new_avg,
                        "price": price,
                        "realized": new_realized,
                        "stop_loss": new_stop if not flat else None,
                        "hwm": new_hwm if not flat else None,
                        "flat": 1 if flat else 0,
                        "stopped": new_stopped,
                        "broker": broker,
                        "now": now,
                    },
                )

        await self._run_in_session(_do, session)

        logger.info("position_updated", symbol=symbol, side=side, qty=qty, price=price)

    async def set_stop_order_id(
        self, symbol: str, exchange: str, stop_order_id: str | None, *, session=None,
    ) -> None:
        """Record (or clear) the broker-side resting stop order for a position."""

        async def _do(s):
            await s.execute(
                text(
                    "UPDATE positions SET stop_order_id = :soid, updated_at = :now"
                    " WHERE symbol = :sym AND exchange = :exch"
                ),
                {"soid": stop_order_id, "now": datetime.now(UTC),
                 "sym": symbol, "exch": exchange},
            )

        await self._run_in_session(_do, session)

    async def get_position(self, symbol: str, exchange: str, *, session=None):
        """Row for (symbol, exchange) with the stop columns, or None."""

        async def _do(s):
            result = await s.execute(
                text(
                    "SELECT id, side, quantity, avg_entry_price, stop_loss_price,"
                    " high_water_mark, stop_order_id, stopped_out"
                    " FROM positions WHERE symbol = :sym AND exchange = :exch LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            return result.fetchone()

        return await self._run_in_session(_do, session)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _get_status(self, order_id: str, *, session=None) -> str | None:
        """Fetch the current status of an order.

        Parameters
        ----------
        session:
            Optional caller-owned session.  When provided the read uses the
            caller's transaction so uncommitted writes are visible.
        """

        async def _do(s):
            result = await s.execute(
                text("SELECT status FROM orders WHERE id = :id"),
                {"id": order_id},
            )
            row = result.fetchone()
            return row.status if row else None

        return await self._run_in_session(_do, session)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1EEAE49B869A - verify with scripts/authorship.py verify
