"""Execution Agent -- routes orders to the correct broker based on system mode."""

import asyncio
from datetime import datetime, timezone

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
    try:
        from app.core.redis_client import redis_client
        return redis_client
    except Exception:
        from app.core.kv_store import MemoryKVStore
        return MemoryKVStore()

from sqlalchemy import text

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
        self.paper_broker = PaperBroker(redis=_get_redis())
        self.alpaca_broker = AlpacaBroker()
        self.zerodha_broker = ZerodhaBroker()

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)

    # ------------------------------------------------------------------ #
    # Main loop -- process approved / pending orders
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Periodically check for pending orders that have been approved."""
        while self._running:
            try:
                await self._process_approved_orders()
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
            # Could be an approval from the CIO dashboard
            await self._handle_order_update(message)

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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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

        # Select broker
        if broker_type == "PAPER":
            fill = await self.paper_broker.execute(order)
        elif broker_type == "ALPACA":
            fill = await self.alpaca_broker.execute(order)
        elif broker_type == "ZERODHA":
            fill = await self.zerodha_broker.execute(order)
        else:
            fill = await self.paper_broker.execute(order)

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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return

        # Record fill
        fill_record = await self.order_manager.record_fill(
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                      AND broker_order_id IS NOT NULL
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
