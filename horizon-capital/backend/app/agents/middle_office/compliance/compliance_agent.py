"""Compliance Agent -- rule-based position limits, trade rules, and restricted symbols.

This agent is entirely deterministic (no LLM needed). It monitors signals
and orders for compliance violations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.compliance")

# Symbols that are restricted from trading (regulatory, sanctions, etc.)
RESTRICTED_SYMBOLS: set[str] = set()

COMPLIANCE_CHECK_INTERVAL = 30  # seconds


class ComplianceAgent(BaseAgent):
    """Monitors trading activity for compliance rule violations."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="compliance-agent-1",
            agent_type="compliance",
            bus=bus,
        )
        self._violations: list[dict] = []

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.signal.*", self.on_message)
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.SIGNAL:
            await self._check_signal_compliance(message.payload)
        elif message.message_type in (MessageType.ORDER_NEW, MessageType.ORDER_FILL):
            await self._check_order_compliance(message.payload)

    async def run(self) -> None:
        """Periodic compliance sweep."""
        while self._running:
            try:
                await self._periodic_check()
            except Exception as exc:
                logger.error("compliance_check_error", error=str(exc))
            await asyncio.sleep(COMPLIANCE_CHECK_INTERVAL)

    async def _check_signal_compliance(self, payload: dict) -> None:
        """Check if a signal targets a restricted symbol."""
        symbol = payload.get("symbol", "")

        if symbol in RESTRICTED_SYMBOLS:
            violation = {
                "type": "RESTRICTED_SYMBOL",
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Signal for restricted symbol: {symbol}",
            }
            self._violations.append(violation)
            await self.emit(
                channel="horizon.compliance.alert",
                message_type=MessageType.COMPLIANCE_ALERT,
                payload=violation,
            )
            logger.warning("compliance_violation", **violation)

    async def _check_order_compliance(self, payload: dict) -> None:
        """Check order-level compliance rules."""
        symbol = payload.get("symbol", "")

        # Check max position count
        # (In production, query DB for current position count)
        if symbol in RESTRICTED_SYMBOLS:
            violation = {
                "type": "RESTRICTED_SYMBOL_ORDER",
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Order for restricted symbol: {symbol}",
            }
            self._violations.append(violation)
            await self.emit(
                channel="horizon.compliance.alert",
                message_type=MessageType.COMPLIANCE_ALERT,
                payload=violation,
            )

    async def _periodic_check(self) -> None:
        """Run periodic compliance checks (position limits, concentration)."""
        # Placeholder for periodic compliance sweeps
        pass
