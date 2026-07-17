"""IT Agent -- infrastructure monitoring.

Rule-based agent (no LLM). Monitors system resource usage and
connectivity to external services.
"""

from __future__ import annotations

import asyncio
import platform
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.it")

IT_CHECK_INTERVAL = 60  # seconds
AGENT_MESSAGES_PRUNE_INTERVAL = timedelta(hours=1)


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


class ITAgent(BaseAgent):
    """Monitors infrastructure health: memory, disk, connectivity."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="it-agent-1",
            agent_type="it",
            bus=bus,
        )
        # epoch so the first loop iteration prunes immediately at startup
        self._last_pruned = datetime.fromtimestamp(0, tz=UTC)

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
            try:
                await self._prune_agent_messages()
            except Exception as exc:
                logger.error("agent_messages_prune_error", error=str(exc))
            await asyncio.sleep(IT_CHECK_INTERVAL)

    async def _prune_agent_messages(self) -> None:
        """Delete agent_messages rows older than the retention window.

        Runs at most once per hour (agent_messages has no other cleanup and
        grows unbounded — every bus publish inserts a row via BaseAgent.emit).
        """
        now = datetime.now(UTC)
        if now - self._last_pruned < AGENT_MESSAGES_PRUNE_INTERVAL:
            return
        self._last_pruned = now

        cutoff = now - timedelta(days=settings.agent_messages_retention_days)
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("DELETE FROM agent_messages WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            await session.commit()
        logger.info("agent_messages_pruned", rowcount=result.rowcount)

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
                    message_type=MessageType.HEALTH_CHECK,
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
            message_type=MessageType.HEALTH_CHECK,
            payload=status,
        )
