"""Execution Agent -- routes orders to the correct broker based on system mode."""

import asyncio
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
from app.agents.front_office.trading.order_manager import OrderManager
from app.agents.front_office.trading.paper_broker import PaperBroker
from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_redis():
    from app.core.kv_store import get_kv_store
    return get_kv_store()

from sqlalchemy import text  # noqa: E402

logger = get_logger("agent.execution")

SYSTEM_MODE_KEY = "horizon:system:mode"


class ExecutionAgent(BaseAgent):
    """Routes orders to the appropriate broker and tracks state.

    System modes:
    - ``PAPER_TRADING``     -- all orders go to :class:`PaperBroker`.
    - ``HUMAN_APPROVAL``    -- orders are queued as PENDING until a human
                               approves them via the API.
    - ``FULLY_AUTONOMOUS``  -- orders route to the real broker matching the
                               exchange (Alpaca for US, Zerodha for India).

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
        self.redis = _get_redis()
        self.order_manager = OrderManager()
        self.paper_broker = PaperBroker()
        self.alpaca_broker = AlpacaBroker()
        self.zerodha_broker = ZerodhaBroker()

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)
        await self.bus.subscribe("horizon.execution.order.cancel_all", self.on_message)

    # ------------------------------------------------------------------ #
    # Main loop -- process approved / pending orders
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Periodically check for pending orders and poll open orders."""
        # Reconcile positions on startup
        await self._reconcile_positions()
        while self._running:
            try:
                await self._process_approved_orders()
                await self._poll_open_orders()
            except Exception as exc:
                logger.error("execution_loop_error", error=str(exc))
            await asyncio.sleep(5)

    # ------------------------------------------------------------------ #
    # Message handler
    # ------------------------------------------------------------------ #

    async def on_message(self, message: AgentMessage) -> None:
        """Handle new order requests and approval messages."""
        if message.message_type == MessageType.ORDER_NEW:
            await self._handle_new_order(message)
        elif message.message_type == MessageType.ORDER_UPDATE:
            await self._handle_order_update(message)
        elif message.message_type == MessageType.ORDER_APPROVE:
            await self._handle_order_approve(message)
        elif message.message_type == MessageType.ORDER_REJECT:
            await self._handle_order_reject(message)
        elif message.message_type == MessageType.ORDER_CANCEL_ALL:
            await self._handle_cancel_all(message)

    # ------------------------------------------------------------------ #
    # New order flow
    # ------------------------------------------------------------------ #

    async def _handle_new_order(self, message: AgentMessage) -> None:
        """Receive a new order request, create it, and route based on mode."""
        payload = message.payload
        mode = await self._get_system_mode()

        # Check kill switch
        kill_active = await self.redis.get("horizon:system:kill_switch")
        if kill_active == "1" and mode != "PAPER_TRADING":
            mode = "PAPER_TRADING"

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
            "broker": self._select_broker_name(payload.get("exchange", ""), mode),
            "mode": mode,
        }

        order = await self.order_manager.create_order(order_data)
        order_id = order["id"]

        if mode == "PAPER_TRADING":
            # Execute immediately with paper broker
            await self._execute_order(order, broker_type="PAPER")

        elif mode == "HUMAN_APPROVAL":
            # Leave as PENDING; emit update so dashboard shows it
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_UPDATE,
                payload={
                    "order_id": order_id,
                    "status": "PENDING",
                    "mode": mode,
                    "symbol": order_data["symbol"],
                    "side": order_data["side"],
                    "quantity": order_data["quantity"],
                    "awaiting_approval": True,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.info("order_awaiting_approval", order_id=order_id)

        elif mode == "FULLY_AUTONOMOUS":
            exchange = payload.get("exchange", "")
            broker_type = self._select_broker_type(exchange)
            await self._execute_order(order, broker_type=broker_type)

    # ------------------------------------------------------------------ #
    # Order update (approval flow)
    # ------------------------------------------------------------------ #

    async def _handle_order_update(self, message: AgentMessage) -> None:
        """Handle approval or cancellation from the CIO dashboard."""
        payload = message.payload
        order_id = payload.get("order_id")
        action = payload.get("action", "").upper()

        if not order_id:
            return

        if action == "APPROVE":
            # Transition to OPEN and execute
            updated = await self.order_manager.update_status(order_id, "OPEN")
            if updated:
                order = await self._load_order(order_id)
                if order:
                    exchange = order.get("exchange", "")
                    broker_type = self._select_broker_type(exchange)
                    await self._execute_order(order, broker_type=broker_type)

        elif action == "REJECT":
            reason = payload.get("reason", "Rejected by CIO")
            await self.order_manager.update_status(
                order_id, "REJECTED", rejection_reason=reason
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_UPDATE,
                payload={
                    "order_id": order_id,
                    "status": "REJECTED",
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        elif action == "CANCEL":
            await self.order_manager.update_status(order_id, "CANCELLED")
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_UPDATE,
                payload={
                    "order_id": order_id,
                    "status": "CANCELLED",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

    # ------------------------------------------------------------------ #
    # Order execution
    # ------------------------------------------------------------------ #

    async def _execute_order(self, order: dict, broker_type: str) -> None:
        """Route the order to the appropriate broker and handle the fill."""
        order_id = order["id"]

        # Transition to OPEN
        await self.order_manager.update_status(order_id, "OPEN")

        # Market hours check (warn but allow -- user may want pre-market)
        exchange = order.get("exchange", "")
        if not self._is_market_open(exchange) and broker_type != "PAPER":
            logger.warning(
                "market_closed_warning",
                exchange=exchange,
                symbol=order.get("symbol", ""),
            )

        # Order splitting for large orders on real brokers
        if broker_type != "PAPER":
            from app.agents.front_office.trading.order_splitter import OrderSplitter
            splitter = OrderSplitter()
            schedule = splitter.create_schedule(
                parent_order_id=order_id,
                symbol=order["symbol"],
                side=order["side"],
                total_quantity=order["quantity"],
            )
            if schedule.n_slices > 1:
                logger.info(
                    "order_split",
                    order_id=order_id,
                    algorithm=schedule.algorithm,
                    slices=schedule.n_slices,
                )
                for child in schedule.child_orders:
                    child_order = {**order, "quantity": child.quantity}
                    child_fill = None
                    for attempt in range(3):
                        broker_inst = self._get_broker_instance(broker_type)
                        if broker_inst:
                            child_fill = await broker_inst.execute(child_order)
                        if child_fill is not None:
                            break
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                    if child_fill and not child_fill.get("rejected"):
                        await self.order_manager.record_fill(
                            order_id=order_id,
                            qty=child_fill["filled_qty"],
                            price=child_fill["fill_price"],
                            commission=child_fill.get("commission", 0.0),
                            slippage=child_fill.get("slippage", 0.0),
                        )
                        await self.order_manager.update_position(
                            symbol=order["symbol"],
                            exchange=order.get("exchange", ""),
                            side=order["side"],
                            qty=child_fill["filled_qty"],
                            price=child_fill["fill_price"],
                            stop_loss_price=order.get("stop_loss"),
                        )
                    if schedule.n_slices > 1 and child != schedule.child_orders[-1]:
                        await asyncio.sleep(60)  # Default interval between slices

                # After all child orders, mark parent as FILLED
                await self.order_manager.update_status(order_id, "FILLED")
                await self.emit(
                    channel="horizon.execution.order.fill",
                    message_type=MessageType.ORDER_FILL,
                    payload={
                        "order_id": order_id,
                        "symbol": order["symbol"],
                        "side": order["side"],
                        "filled_qty": order["quantity"],
                        "fill_price": 0,  # Average computed from fills
                        "broker": broker_type,
                        "status": "FILLED",
                        "split_execution": True,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                return  # Skip normal execution path

        # Select broker with retry logic (3 attempts, exponential backoff)
        fill = None
        for attempt in range(3):
            if broker_type == "PAPER":
                fill = await self.paper_broker.execute(order)
            elif broker_type == "ALPACA":
                fill = await self.alpaca_broker.execute(order)
            elif broker_type == "ZERODHA":
                fill = await self.zerodha_broker.execute(order)
            else:
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
                message_type=MessageType.ORDER_UPDATE,
                payload={
                    "order_id": order_id,
                    "status": "REJECTED",
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return

        # Record fill
        await self.order_manager.record_fill(
            order_id=order_id,
            qty=fill["filled_qty"],
            price=fill["fill_price"],
            commission=fill.get("commission", 0.0),
            slippage=fill.get("slippage", 0.0),
        )

        # Update order status
        if fill["filled_qty"] >= order.get("quantity", 0):
            await self.order_manager.update_status(
                order_id, "FILLED",
                broker_order_id=fill.get("broker_order_id"),
            )
            new_status = "FILLED"
        else:
            await self.order_manager.update_status(
                order_id, "PARTIAL",
                broker_order_id=fill.get("broker_order_id"),
            )
            new_status = "PARTIAL"

        # Update position
        await self.order_manager.update_position(
            symbol=order["symbol"],
            exchange=order.get("exchange", ""),
            side=order["side"],
            qty=fill["filled_qty"],
            price=fill["fill_price"],
            stop_loss_price=order.get("stop_loss"),
        )

        # Publish fill event
        await self.emit(
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": order_id,
                "symbol": order["symbol"],
                "side": order["side"],
                "filled_qty": fill["filled_qty"],
                "fill_price": fill["fill_price"],
                "commission": fill.get("commission", 0.0),
                "slippage": fill.get("slippage", 0.0),
                "broker": fill.get("broker", broker_type),
                "status": new_status,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "order_executed",
            order_id=order_id,
            symbol=order["symbol"],
            side=order["side"],
            qty=fill["filled_qty"],
            price=fill["fill_price"],
            broker=broker_type,
        )

    # ------------------------------------------------------------------ #
    # REPL approve / reject handlers (HUMAN_APPROVAL mode)
    # ------------------------------------------------------------------ #

    async def _handle_order_approve(self, message: AgentMessage) -> None:
        """Approve a pending order by ID and route it to the broker."""
        order_id = message.payload.get("order_id")
        if not order_id:
            return
        order = await self._load_order(order_id)
        if not order:
            logger.warning("approve_order_not_found", order_id=order_id)
            return
        exchange = order.get("exchange", "")
        broker_type = self._select_broker_type(exchange)
        await self._execute_order(order, broker_type=broker_type)
        logger.info("order_approved_and_routed", order_id=order_id)

    async def _handle_order_reject(self, message: AgentMessage) -> None:
        """Reject a pending order by ID."""
        order_id = message.payload.get("order_id")
        reason = message.payload.get("reason", "Rejected by CIO via REPL")
        if not order_id:
            return
        await self.order_manager.update_status(
            order_id, "REJECTED", rejection_reason=reason
        )
        await self.emit(
            channel="horizon.execution.order.update",
            message_type=MessageType.ORDER_UPDATE,
            payload={
                "order_id": order_id,
                "status": "REJECTED",
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        logger.info("order_rejected_via_repl", order_id=order_id)

    # ------------------------------------------------------------------ #
    # Cancel all orders (kill switch)
    # ------------------------------------------------------------------ #

    async def _handle_cancel_all(self, message: AgentMessage) -> None:
        """Cancel all open/partial orders at the broker level."""
        reason = message.payload.get("reason", "kill switch")
        logger.warning("cancel_all_orders", reason=reason)

        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, broker_order_id, broker
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker_order_id IS NOT NULL
                      AND broker != 'PAPER'
                """)
            )
            rows = result.fetchall()

        cancelled = 0
        for row in rows:
            broker = self._get_broker_instance(row.broker)
            if broker is None:
                continue
            try:
                success = await broker.cancel_order(row.broker_order_id)
                if success:
                    await self.order_manager.update_status(row.id, "CANCELLED")
                    cancelled += 1
            except Exception as exc:
                logger.error("cancel_order_error", order_id=row.id, error=str(exc))

        logger.info("cancel_all_complete", cancelled=cancelled, total=len(rows))

    # ------------------------------------------------------------------ #
    # Open-order polling (real brokers)
    # ------------------------------------------------------------------ #

    async def _poll_open_orders(self) -> None:
        """Poll brokers for OPEN/PARTIAL orders until they reach a terminal state."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity, broker_order_id, broker, status
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker_order_id IS NOT NULL
                      AND broker != 'PAPER'
                    ORDER BY created_at ASC
                    LIMIT 20
                """)
            )
            rows = result.fetchall()

        for row in rows:
            broker = self._get_broker_instance(row.broker)
            if broker is None:
                continue
            try:
                status = await broker.get_order_status(row.broker_order_id)
            except Exception as exc:
                logger.error("poll_order_error", order_id=row.id, error=str(exc))
                continue
            if status is None:
                continue

            # If newly filled qty > previously recorded fills, record additional fill
            total_filled = status.get("filled_qty", 0)
            prev_fills = await self._get_total_filled(row.id)
            new_qty = total_filled - prev_fills

            if new_qty > 0:
                await self.order_manager.record_fill(
                    order_id=row.id, qty=new_qty,
                    price=status.get("filled_avg_price", 0),
                )
                await self.order_manager.update_position(
                    symbol=row.symbol, exchange=row.exchange,
                    side=row.side, qty=new_qty,
                    price=status.get("filled_avg_price", 0),
                )

            # Terminal state check
            broker_status = status.get("status", "")
            if broker_status in ("filled", "COMPLETE"):
                await self.order_manager.update_status(row.id, "FILLED")
            elif broker_status in ("cancelled", "CANCELLED", "rejected", "REJECTED"):
                await self.order_manager.update_status(row.id, "CANCELLED")

    # ------------------------------------------------------------------ #
    # Startup reconciliation
    # ------------------------------------------------------------------ #

    async def _reconcile_positions(self) -> None:
        """On startup, check broker for actual positions and reconcile with DB."""
        mode = await self._get_system_mode()
        if mode == "PAPER_TRADING":
            return
        logger.info("reconciling_positions_on_startup")
        # Check for orphaned OPEN orders
        await self._poll_open_orders()
        logger.info("position_reconciliation_complete")

    # ------------------------------------------------------------------ #
    # Approved-order polling
    # ------------------------------------------------------------------ #

    async def _process_approved_orders(self) -> None:
        """Find PENDING orders that have been approved and execute them."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, symbol, exchange, order_type, side, quantity,
                           limit_price, stop_price, signal_id, debate_id,
                           broker, mode
                    FROM orders
                    WHERE status = 'PENDING'
                      AND mode = 'HUMAN_APPROVAL'
                    ORDER BY created_at ASC
                    LIMIT 10
                    """
                )
            )
            rows = result.fetchall()

        for row in rows:
            order = {
                "id": str(row.id),
                "symbol": row.symbol,
                "exchange": row.exchange,
                "order_type": row.order_type,
                "side": row.side,
                "quantity": row.quantity,
                "limit_price": row.limit_price,
                "stop_price": row.stop_price,
                "signal_id": str(row.signal_id) if row.signal_id else None,
                "broker": row.broker,
                "mode": row.mode,
            }
            broker_type = self._select_broker_type(row.exchange)
            await self._execute_order(order, broker_type=broker_type)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _get_system_mode(self) -> str:
        """Read current system mode from Redis, falling back to settings."""
        mode = await self.redis.get(SYSTEM_MODE_KEY)
        if mode and mode in ("PAPER_TRADING", "HUMAN_APPROVAL", "FULLY_AUTONOMOUS"):
            return mode
        return "PAPER_TRADING"

    @staticmethod
    def _is_market_open(exchange: str) -> bool:
        """Check if the exchange market is currently open."""
        from zoneinfo import ZoneInfo
        now_utc = datetime.now(UTC)
        if exchange in ("NSE", "BSE"):
            ist = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))
            return ist.weekday() < 5 and 9 <= ist.hour < 16
        elif exchange in ("NASDAQ", "NYSE", "AMEX"):
            et = now_utc.astimezone(ZoneInfo("America/New_York"))
            return et.weekday() < 5 and 9 <= et.hour < 16
        return True  # Crypto/other: always open

    @staticmethod
    def _select_broker_type(exchange: str) -> str:
        """Pick the broker based on exchange."""
        if exchange in ("NSE", "BSE"):
            return "ZERODHA"
        elif exchange in ("NASDAQ", "NYSE", "AMEX"):
            return "ALPACA"
        else:
            return "PAPER"

    @staticmethod
    def _select_broker_name(exchange: str, mode: str) -> str:
        """Determine the broker name for the order record."""
        if mode == "PAPER_TRADING":
            return "PAPER"
        if exchange in ("NSE", "BSE"):
            return "ZERODHA"
        elif exchange in ("NASDAQ", "NYSE", "AMEX"):
            return "ALPACA"
        return "PAPER"

    def _get_broker_instance(self, broker_name: str):
        """Return the broker instance for the given name."""
        if broker_name == "ALPACA":
            return self.alpaca_broker
        elif broker_name == "ZERODHA":
            return self.zerodha_broker
        elif broker_name == "PAPER":
            return self.paper_broker
        return None

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

    async def _load_order(self, order_id: str) -> dict | None:
        """Load a full order from the database."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, symbol, exchange, order_type, side, quantity,
                           limit_price, stop_price, signal_id, broker, mode
                    FROM orders
                    WHERE id = :id
                    """
                ),
                {"id": order_id},
            )
            row = result.fetchone()

        if not row:
            return None

        return {
            "id": str(row.id),
            "symbol": row.symbol,
            "exchange": row.exchange,
            "order_type": row.order_type,
            "side": row.side,
            "quantity": row.quantity,
            "limit_price": row.limit_price,
            "stop_price": row.stop_price,
            "signal_id": str(row.signal_id) if row.signal_id else None,
            "broker": row.broker,
            "mode": row.mode,
        }
