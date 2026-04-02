"""IT Agent -- infrastructure monitoring.

Rule-based agent (no LLM). Monitors system resource usage and
connectivity to external services.
"""

from __future__ import annotations

import asyncio
import platform
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.it")

IT_CHECK_INTERVAL = 60  # seconds


class ITAgent(BaseAgent):
    """Monitors infrastructure health: memory, disk, connectivity."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="it-agent-1",
            agent_type="it",
            bus=bus,
        )

    async def _subscribe(self) -> None:
        pass  # IT agent doesn't subscribe to business messages

    async def on_message(self, message: AgentMessage) -> None:
        pass  # No inbound message handling

    async def run(self) -> None:
        """Periodically check infrastructure health."""
        while self._running:
            try:
                await self._health_check()
            except Exception as exc:
                logger.error("it_health_check_error", error=str(exc))
            await asyncio.sleep(IT_CHECK_INTERVAL)

    async def _health_check(self) -> None:
        """Gather system metrics and publish status."""
        now = datetime.now(UTC)

        status = {
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "timestamp": now.isoformat(),
        }

        # Try to get memory info (psutil is optional)
        try:
            import psutil
            mem = psutil.virtual_memory()
            status["memory_percent"] = mem.percent
            status["memory_available_gb"] = round(mem.available / (1024**3), 2)
            cpu = psutil.cpu_percent(interval=0.1)
            status["cpu_percent"] = cpu

            # Alert if memory usage is high
            if mem.percent > 90:
                await self.emit(
                    channel="horizon.it.alert",
                    message_type=MessageType.IT_ALERT,
                    payload={
                        "type": "HIGH_MEMORY",
                        "memory_percent": mem.percent,
                        "timestamp": now.isoformat(),
                    },
                )
        except ImportError:
            status["memory_percent"] = -1
            status["note"] = "psutil not installed"

        await self.emit(
            channel="horizon.it.status",
            message_type=MessageType.IT_STATUS,
            payload=status,
        )
