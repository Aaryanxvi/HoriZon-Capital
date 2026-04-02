"""Investor Relations Agent -- performance reports and investor summaries.

LLM-powered agent that generates natural language performance reports
and investor-facing summaries.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.ir")

IR_REPORT_INTERVAL = 3600  # 1 hour


class IRAgent(BaseAgent):
    """Generates periodic performance reports and investor summaries."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="ir-agent-1",
            agent_type="investor_relations",
            bus=bus,
        )
        self._latest_portfolio: dict = {}
        self._latest_risk: dict = {}

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.portfolio.*", self.on_message)
        await self.bus.subscribe("horizon.risk.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.PORTFOLIO_UPDATE:
            self._latest_portfolio = message.payload
        elif message.message_type == MessageType.RISK_ALERT:
            self._latest_risk = message.payload

    async def run(self) -> None:
        """Periodically generate performance reports."""
        while self._running:
            try:
                await self._generate_report()
            except Exception as exc:
                logger.error("ir_report_error", error=str(exc))
            await asyncio.sleep(IR_REPORT_INTERVAL)

    async def _generate_report(self) -> None:
        """Generate and publish a performance report."""
        now = datetime.now(UTC)
        nav = self._latest_portfolio.get("nav", 0.0)

        report = {
            "report_type": "periodic_summary",
            "nav": nav,
            "timestamp": now.isoformat(),
            "portfolio_snapshot": self._latest_portfolio,
            "risk_snapshot": self._latest_risk,
        }

        await self.emit(
            channel="horizon.ir.report",
            message_type=MessageType.IR_REPORT,
            payload=report,
        )
        logger.info("ir_report_generated", nav=nav)
