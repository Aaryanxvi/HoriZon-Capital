"""Execution Agent -- routes orders to the paper broker.

Handles the full trade lifecycle:
  1. Receives ORDER_NEW from PortfolioAgent
  2. In HUMAN_APPROVAL mode, buffers orders marked ``requires_approval``
  3. Executes via PaperBroker (with Almgren-Chriss market impact)
  4. Updates cash balances after fills (deduct on BUY, add on SELL)
  5. Updates positions and publishes ORDER_FILL
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.trading.order_manager import OrderManager
from app.agents.front_office.trading.paper_broker import PaperBroker
from app.config import settings
from app.core.cash import adjust_cash, mirror_to_kv
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()


logger = get_logger("agent.execution")


class ExecutionAgent(BaseAgent):
    """Routes orders to the paper broker and tracks state.

    All orders are executed through the paper broker for simulation.

    Subscribes to:
      - ``horizon.execution.order.*``

    Publishes:
      - ``horizon.execution.order.fill``  -- after a successful fill
      - ``horizon.execution.order.update`` -- status changes
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="execution-agent",
            agent_type="execution",
            bus=bus,
        )
        self.order_manager = OrderManager()
        self.paper_broker = PaperBroker()
        # Orders awaiting human CIO approval: order_id -> order dict
        self._pending_approval: dict[str, dict] = {}

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)

    async def run(self) -> None:
        """Periodically poll for any stale open orders."""
        while self._running:
            try:
                await self._poll_open_orders()
            except Exception as exc:
                logger.error("execution_loop_error", error=str(exc))
            await asyncio.sleep(5)

    async def on_message(self, message: AgentMessage) -> None:
        """Handle new order requests and approval/rejection."""
        if message.message_type == MessageType.ORDER_NEW:
            await self._handle_new_order(message)
        elif message.message_type == MessageType.ORDER_CANCEL:
            # Handle rejection of pending orders
            order_id = message.payload.get("order_id", "")
            if order_id in self._pending_approval:
                del self._pending_approval[order_id]
                await self.order_manager.update_status(order_id, "REJECTED",
                                                       rejection_reason="CIO rejected")
                logger.info("order_rejected_by_cio", order_id=order_id)

    async def _handle_new_order(self, message: AgentMessage) -> None:
        """Receive a new order request and execute via paper broker."""
        payload = message.payload

        order_data = {
            "symbol": payload["symbol"],
            "exchange": payload.get("exchange", ""),
            "order_type": payload.get("order_type", "MARKET"),
            "side": payload["side"],
            "quantity": payload["quantity"],
            "limit_price": payload.get("limit_price"),
            "stop_price": payload.get("stop_price"),
            "signal_id": payload.get("signal_id"),
            "debate_id": payload.get("debate_id"),
            "stop_loss": payload.get("stop_loss"),
            "broker": "PAPER",
            "mode": settings.system_mode.value,
        }

        order = await self.order_manager.create_order(order_data)

        # Emit tracked order with real order_id for dashboard
        await self.emit(
            channel="horizon.execution.order.tracked",
            message_type=MessageType.ORDER_NEW,
            payload={
                "order_id": order["id"],
                "symbol": order["symbol"],
                "exchange": order.get("exchange", ""),
                "side": order["side"],
                "quantity": order["quantity"],
                "status": "OPEN",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # In HUMAN_APPROVAL mode, buffer orders that need approval
        if payload.get("requires_approval"):
            self._pending_approval[order["id"]] = order
            await self.order_manager.update_status(order["id"], "OPEN")
            logger.info("order_pending_approval", order_id=order["id"],
                        symbol=order["symbol"])
            return

        try:
            await self._execute_order(order)
        except Exception as exc:
            await self.order_manager.update_status(
                order["id"], "REJECTED",
                rejection_reason=f"Atomic fill rollback: {type(exc).__name__}",
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order["id"],
                    "status": "REJECTED",
                    "reason": f"Atomic fill rollback: {type(exc).__name__}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.error(
                "execute_order_failed",
                order_id=order["id"],
                error=str(exc),
            )

    async def approve_order(self, order_id: str) -> bool:
        """Approve a pending order (called from REPL 'approve' command)."""
        order = self._pending_approval.pop(order_id, None)
        if order is None:
            # Try partial match
            for oid, o in list(self._pending_approval.items()):
                if oid.startswith(order_id):
                    order = self._pending_approval.pop(oid)
                    order_id = oid
                    break
        if order is None:
            return False
        try:
            await self._execute_order(order)
        except Exception as exc:
            await self.order_manager.update_status(
                order["id"], "REJECTED",
                rejection_reason=f"Atomic fill rollback: {type(exc).__name__}",
            )
            logger.error(
                "approve_order_failed",
                order_id=order["id"], error=str(exc),
            )
            return False
        return True

    async def reject_order(self, order_id: str) -> bool:
        """Reject a pending order (called from REPL 'reject' command)."""
        order = self._pending_approval.pop(order_id, None)
        if order is None:
            for oid in list(self._pending_approval.keys()):
                if oid.startswith(order_id):
                    order = self._pending_approval.pop(oid)
                    order_id = oid
                    break
        if order is None:
            return False
        await self.order_manager.update_status(order_id, "REJECTED",
                                               rejection_reason="CIO rejected")
        return True

    def get_pending_approvals(self) -> list[dict]:
        """Return list of orders awaiting CIO approval."""
        return list(self._pending_approval.values())

    async def _execute_order(self, order: dict) -> None:
        """Execute the order via the paper broker."""
        order_id = order["id"]

        # Kill switch enforcement — second layer of defense
        kv = _get_kv()
        halted = await kv.get("horizon:system:halted")
        if halted == "1" and order.get("side") == "BUY":
            await self.order_manager.update_status(
                order_id, "REJECTED",
                rejection_reason="System halted — kill switch active",
            )
            logger.warning("order_blocked_system_halted",
                           order_id=order_id, symbol=order["symbol"])
            return

        # Block naked shorts: reject SELL if no open position exists
        if order.get("side") == "SELL":
            has_position = await self._has_open_position(
                order["symbol"], order.get("exchange", "")
            )
            if not has_position:
                await self.order_manager.update_status(
                    order_id, "REJECTED",
                    rejection_reason="No open position to sell (naked short blocked)",
                )
                await self.emit(
                    channel="horizon.execution.order.update",
                    message_type=MessageType.ORDER_CANCEL,
                    payload={
                        "order_id": order_id,
                        "status": "REJECTED",
                        "reason": "Naked short blocked",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                logger.info("naked_short_blocked", order_id=order_id,
                            symbol=order["symbol"])
                return

        # Set OPEN before the atomic block so the order is visible if the system
        # crashes mid-fill. If the atomic block rolls back, the order stays OPEN
        # and the stale-order poller will CANCEL it after its timeout.
        await self.order_manager.update_status(order_id, "OPEN")

        fill = None
        for attempt in range(3):
            fill = await self.paper_broker.execute(order)
            if fill is not None:
                break
            if attempt < 2:
                logger.warning("broker_retry", order_id=order_id, attempt=attempt + 1)
                await asyncio.sleep(2 ** attempt)

        if fill is None or fill.get("rejected"):
            reason = (fill or {}).get("rejection_reason", "Broker returned no fill")
            await self.order_manager.update_status(
                order_id, "REJECTED", rejection_reason=reason
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order_id,
                    "status": "REJECTED",
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return

        # Atomic transaction: fill + status + position + cash
        side = order["side"]
        qty = float(fill["filled_qty"])
        price = float(fill["fill_price"])
        commission = float(fill.get("commission", 0.0))
        slippage = float(fill.get("slippage", 0.0))
        exchange = order.get("exchange", "")
        currency = "INR" if exchange in ("NSE", "BSE") else "USD"
        cost = qty * price
        delta = -(cost + commission) if side == "BUY" else (cost - commission)

        if qty >= order.get("quantity", 0):
            new_status = "FILLED"
        else:
            new_status = "PARTIAL"

        try:
            async with _get_session_factory()() as session:
                await self.order_manager.record_fill(
                    order_id=order_id,
                    qty=qty,
                    price=price,
                    commission=commission,
                    slippage=slippage,
                    session=session,
                )
                await self.order_manager.update_status(
                    order_id, new_status, session=session,
                )
                await self.order_manager.update_position(
                    symbol=order["symbol"],
                    exchange=exchange,
                    side=side,
                    qty=qty,
                    price=price,
                    stop_loss_price=order.get("stop_loss"),
                    session=session,
                )
                new_cash = await adjust_cash(session, currency, delta)
                await session.commit()
        except Exception:
            logger.exception("atomic_fill_rollback", order_id=order_id)
            raise

        await mirror_to_kv(currency, new_cash)

        await self.emit(
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": order_id,
                "symbol": order["symbol"],
                "side": side,
                "filled_qty": qty,
                "fill_price": price,
                "commission": commission,
                "slippage": slippage,
                "broker": "PAPER",
                "status": new_status,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "order_executed",
            order_id=order_id,
            symbol=order["symbol"],
            side=side,
            qty=qty,
            price=price,
            new_cash=f"{new_cash:.2f}",
        )

    async def _poll_open_orders(self) -> None:
        """Cancel stale OPEN orders that weren't filled within 60 seconds.

        Paper broker fills are instant, so any OPEN order older than 60s
        is stuck due to an error. Mark it CANCELLED instead of re-executing
        (re-execution without position/cash updates causes infinite fills).
        """
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, side, created_at
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker = 'PAPER'
                      AND created_at < datetime('now', '-60 seconds')
                    ORDER BY created_at ASC
                    LIMIT 20
                """)
            )
            rows = result.fetchall()

        for row in rows:
            try:
                await self.order_manager.update_status(
                    str(row.id), "CANCELLED",
                    rejection_reason="Stale order — not filled within 60s",
                )
                logger.warning(
                    "stale_order_cancelled",
                    order_id=str(row.id), symbol=row.symbol,
                )
            except Exception as exc:
                logger.error(
                    "poll_order_error",
                    order_id=str(row.id), error=str(exc),
                )

    async def _has_open_position(self, symbol: str, exchange: str) -> bool:
        """Check if there is an open position for this symbol."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT quantity FROM positions"
                    " WHERE symbol = :sym AND exchange = :exch AND quantity > 0"
                    " LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            row = result.fetchone()
        return row is not None

    async def _get_total_filled(self, order_id: str) -> float:
        """Sum filled_qty from all fills for an order."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT COALESCE(SUM(filled_qty), 0) AS total"
                    " FROM fills WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
            row = result.fetchone()
        return float(row.total) if row else 0.0

