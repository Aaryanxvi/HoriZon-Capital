"""Order state machine and persistence layer."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("execution.order_manager")


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

        owns_session = session is None

        async def _do(s):
            await s.execute(
                text(
                    """
                    INSERT INTO orders
                        (id, symbol, exchange, order_type, side, quantity,
                         limit_price, stop_price, status, broker, mode,
                         signal_id, debate_id, created_at, updated_at)
                    VALUES
                        (:id, :symbol, :exchange, :order_type, :side, :quantity,
                         :limit_price, :stop_price, 'PENDING', :broker, :mode,
                         :signal_id, :debate_id, :now, :now)
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
                    "now": now,
                },
            )

        if owns_session:
            async with _get_session_factory()() as s:
                await _do(s)
                await s.commit()
        else:
            await _do(session)

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
        owns_session = session is None

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

        if owns_session:
            async with _get_session_factory()() as s:
                await _do(s)
                await s.commit()
        else:
            await _do(session)

        logger.info("order_status_updated", order_id=order_id, status=new_status)
        return True

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
        session=None,
    ) -> dict:
        """Record a fill against an order and return the fill record.

        Parameters
        ----------
        session:
            Optional caller-owned session.  When provided, the method does NOT
            commit.
        """
        fill_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        owns_session = session is None

        async def _do(s):
            await s.execute(
                text(
                    """
                    INSERT INTO fills
                        (id, order_id, filled_qty, fill_price, commission,
                         slippage, filled_at, created_at, updated_at)
                    VALUES
                        (:id, :order_id, :qty, :price, :commission,
                         :slippage, :now, :now, :now)
                    """
                ),
                {
                    "id": fill_id,
                    "order_id": order_id,
                    "qty": qty,
                    "price": price,
                    "commission": commission,
                    "slippage": slippage,
                    "now": now,
                },
            )

        if owns_session:
            async with _get_session_factory()() as s:
                await _do(s)
                await s.commit()
        else:
            await _do(session)

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
        session:
            Optional caller-owned session.  When provided, the method does NOT
            commit.
        """
        now = datetime.now(UTC)

        # Determine currency from exchange
        currency = "INR" if exchange in ("NSE", "BSE") else "USD"

        owns_session = session is None

        async def _do(s):
            # Fetch existing position
            result = await s.execute(
                text(
                    "SELECT id, side, quantity, avg_entry_price, realized_pnl"
                    " FROM positions WHERE symbol = :sym AND exchange = :exch LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            existing = result.fetchone()

            if existing is None:
                # Create new position
                pos_side = "LONG" if side == "BUY" else "SHORT"
                await s.execute(
                    text(
                        """
                        INSERT INTO positions
                            (id, symbol, exchange, side, quantity, avg_entry_price,
                             current_price, unrealized_pnl, realized_pnl,
                             weight_pct, currency, stop_loss_price,
                             created_at, updated_at)
                        VALUES
                            (:id, :symbol, :exchange, :side, :qty,
                             :price, :price, 0.0, 0.0,
                             0.0, :currency, :stop_loss,
                             :now, :now)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "exchange": exchange,
                        "side": pos_side,
                        "qty": qty,
                        "price": price,
                        "currency": currency,
                        "stop_loss": stop_loss_price,
                        "now": now,
                    },
                )
            else:
                # Update existing position
                old_qty = existing.quantity
                old_avg = existing.avg_entry_price
                old_realized = existing.realized_pnl or 0.0

                if side == "BUY":
                    if existing.side == "LONG":
                        # Adding to long
                        new_qty = old_qty + qty
                        new_avg = (
                            ((old_avg * old_qty) + (price * qty)) / new_qty
                            if new_qty > 0 else price
                        )
                        new_side = "LONG"
                        realized_delta = 0.0
                    else:
                        # Covering short
                        new_qty = old_qty - qty
                        new_avg = old_avg
                        realized_delta = (old_avg - price) * min(qty, old_qty)
                        new_side = "SHORT" if new_qty > 0 else ("LONG" if new_qty < 0 else "FLAT")
                        new_qty = abs(new_qty)
                        if new_side == "LONG":
                            new_avg = price
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
                    else:
                        # Adding to short
                        new_qty = old_qty + qty
                        new_avg = (
                            ((old_avg * old_qty) + (price * qty)) / new_qty
                            if new_qty > 0 else price
                        )
                        new_side = "SHORT"
                        realized_delta = 0.0
                else:
                    return

                new_realized = old_realized + realized_delta

                await s.execute(
                    text(
                        """
                        UPDATE positions
                        SET side = :side, quantity = :qty, avg_entry_price = :avg,
                            current_price = :price, realized_pnl = :realized,
                            stop_loss_price = COALESCE(:stop_loss, stop_loss_price),
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
                        "stop_loss": stop_loss_price,
                        "now": now,
                    },
                )

        if owns_session:
            async with _get_session_factory()() as s:
                await _do(s)
                await s.commit()
        else:
            await _do(session)

        logger.info("position_updated", symbol=symbol, side=side, qty=qty, price=price)

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
        owns_session = session is None

        async def _do(s):
            result = await s.execute(
                text("SELECT status FROM orders WHERE id = :id"),
                {"id": order_id},
            )
            row = result.fetchone()
            return row.status if row else None

        if owns_session:
            async with _get_session_factory()() as s:
                return await _do(s)
        else:
            return await _do(session)
