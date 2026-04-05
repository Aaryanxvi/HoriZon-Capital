"""Accounting Agent -- NAV computation and P&L snapshots.

Rule-based agent (no LLM). Periodically computes net asset value and
records P&L snapshots.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.accounting")

ACCOUNTING_INTERVAL = 120  # seconds


class AccountingAgent(BaseAgent):
    """Computes NAV and records P&L snapshots."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="accounting-agent-1",
            agent_type="accounting",
            bus=bus,
        )
        self._last_nav: float = 0.0

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.portfolio.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.PORTFOLIO_UPDATE:
            nav = message.payload.get("nav", 0.0)
            self._last_nav = nav

    async def run(self) -> None:
        """Periodically compute and publish accounting snapshots."""
        while self._running:
            try:
                await self._compute_snapshot()
            except Exception as exc:
                logger.error("accounting_snapshot_error", error=str(exc))
            await asyncio.sleep(ACCOUNTING_INTERVAL)

    async def _compute_snapshot(self) -> None:
        """Publish an accounting snapshot with current NAV and P&L."""
        now = datetime.now(UTC)

        snapshot = {
            "nav": self._last_nav,
            "timestamp": now.isoformat(),
            "period": "intraday",
        }

        await self.emit(
            channel="horizon.accounting.snapshot",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload=snapshot,
        )
        logger.info("accounting_snapshot", nav=self._last_nav)
