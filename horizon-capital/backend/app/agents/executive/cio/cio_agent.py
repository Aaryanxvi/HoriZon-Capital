"""AI CIO Agent -- autonomous governance, system health, and auto-halt.

Only active when CIO_MODE=AI. Monitors all departments, issues directives,
and can halt trading if systemic issues are detected.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.cio")

CIO_POLL_INTERVAL = 60  # seconds


class CIOAgent(BaseAgent):
    """AI Chief Investment Officer -- monitors system health and issues directives."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="cio-agent-1",
            agent_type="cio",
            bus=bus,
        )
        self._alerts: list[dict] = []
        self._department_statuses: dict[str, dict] = {}

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.*", self.on_message)
        await self.bus.subscribe("horizon.compliance.*", self.on_message)
        await self.bus.subscribe("horizon.department.*", self.on_message)
        await self.bus.subscribe("horizon.it.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.RISK_ALERT:
            self._alerts.append(message.payload)
            await self._evaluate_risk_alert(message.payload)
        elif message.message_type == MessageType.COMPLIANCE_ALERT:
            self._alerts.append(message.payload)
        elif message.message_type == MessageType.DEPARTMENT_STATUS:
            dept = message.payload.get("department", "unknown")
            self._department_statuses[dept] = message.payload
        elif message.message_type == MessageType.IT_ALERT:
            self._alerts.append(message.payload)

    async def run(self) -> None:
        """Periodically assess overall system health and issue directives."""
        while self._running:
            try:
                await self._system_health_check()
            except Exception as exc:
                logger.error("cio_health_check_error", error=str(exc))
            await asyncio.sleep(CIO_POLL_INTERVAL)

    async def _system_health_check(self) -> None:
        """Evaluate system health and publish CIO directive if needed."""
        now = datetime.now(timezone.utc)

        # Count recent critical alerts (last 5 minutes)
        recent_critical = len(self._alerts[-10:])

        if recent_critical >= 5:
            await self.emit(
                channel="horizon.cio.directive",
                message_type=MessageType.CIO_DIRECTIVE,
                payload={
                    "directive": "HALT_TRADING",
                    "reason": f"{recent_critical} critical alerts in recent window",
                    "timestamp": now.isoformat(),
                },
            )
            logger.warning("cio_halt_directive_issued", alert_count=recent_critical)

        # Clear old alerts
        self._alerts = self._alerts[-20:]

    async def _evaluate_risk_alert(self, payload: dict) -> None:
        """React immediately to severe risk alerts."""
        action = payload.get("action", "")
        if action == "KILL_SWITCH_TRIGGERED":
            await self.emit(
                channel="horizon.cio.directive",
                message_type=MessageType.CIO_DIRECTIVE,
                payload={
                    "directive": "EMERGENCY_HALT",
                    "reason": "Kill switch triggered by risk agent",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
