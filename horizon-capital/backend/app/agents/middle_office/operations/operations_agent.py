"""Operations Agent -- stuck order detection and reconciliation.

Rule-based agent (no LLM needed). Monitors order lifecycle and detects
orders that have been pending too long.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.operations")

OPS_CHECK_INTERVAL = 60  # seconds
STUCK_ORDER_THRESHOLD = 300  # 5 minutes


class OperationsAgent(BaseAgent):
    """Detects stuck orders and reconciliation issues."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="operations-agent-1",
            agent_type="operations",
            bus=bus,
        )
        self._pending_orders: dict[str, datetime] = {}

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        payload = message.payload
        order_id = payload.get("order_id", "")

        if message.message_type == MessageType.ORDER_NEW:
            self._pending_orders[order_id] = datetime.now(UTC)
        elif message.message_type in (MessageType.ORDER_FILL, MessageType.ORDER_CANCEL):
            status = payload.get("status", "")
            if status in ("FILLED", "CANCELLED", "REJECTED"):
                self._pending_orders.pop(order_id, None)

    async def run(self) -> None:
        """Periodically check for stuck orders."""
        while self._running:
            try:
                await self._check_stuck_orders()
            except Exception as exc:
                logger.error("ops_check_error", error=str(exc))
            await asyncio.sleep(OPS_CHECK_INTERVAL)

    async def _check_stuck_orders(self) -> None:
        """Flag orders that have been pending beyond threshold."""
        now = datetime.now(UTC)
        stuck = []

        for order_id, created_at in list(self._pending_orders.items()):
            elapsed = (now - created_at).total_seconds()
            if elapsed > STUCK_ORDER_THRESHOLD:
                stuck.append(order_id)

        if stuck:
            await self.emit(
                channel="horizon.operations.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "type": "STUCK_ORDERS",
                    "order_ids": stuck,
                    "count": len(stuck),
                    "timestamp": now.isoformat(),
                },
            )
            logger.warning("stuck_orders_detected", count=len(stuck), orders=stuck)
