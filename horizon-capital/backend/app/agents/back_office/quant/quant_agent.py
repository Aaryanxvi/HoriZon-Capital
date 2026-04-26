"""Quant Agent -- feature computation and pipeline health monitoring.

Rule-based agent (no LLM). Monitors feature pipeline health and
flags stale or missing data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.quant")

QUANT_CHECK_INTERVAL = 120  # seconds


class QuantAgent(BaseAgent):
    """Monitors feature pipelines and model health."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="quant-agent-1",
            agent_type="quant",
            bus=bus,
        )
        self._feature_timestamps: dict[str, datetime] = {}

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.features.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.FEATURE_UPDATE:
            scope = message.payload.get("market_scope", "unknown")
            self._feature_timestamps[scope] = datetime.now(UTC)

    async def run(self) -> None:
        """Monitor feature pipeline freshness and model health."""
        while self._running:
            try:
                await self._check_feature_freshness()
            except Exception as exc:
                logger.error("quant_check_error", error=str(exc))
            await asyncio.sleep(QUANT_CHECK_INTERVAL)

    async def _check_feature_freshness(self) -> None:
        """Check that feature data is being updated regularly."""
        now = datetime.now(UTC)
        stale_scopes = []

        for scope, last_ts in self._feature_timestamps.items():
            elapsed = (now - last_ts).total_seconds()
            if elapsed > 300:  # 5 minutes stale threshold
                stale_scopes.append(scope)

        if stale_scopes:
            logger.warning("stale_features", scopes=stale_scopes)
