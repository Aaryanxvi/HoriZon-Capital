"""Kill-switch: emergency circuit breaker that flips the system to paper trading."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("risk.kill_switch")

KILL_SWITCH_KEY = "horizon:system:kill_switch"
SYSTEM_MODE_KEY = "horizon:system:mode"


class KillSwitch:
    """Redis-backed kill switch.

    When activated the switch:
    1. Sets ``horizon:system:kill_switch`` to ``1`` in Redis.
    2. Overrides ``horizon:system:mode`` to ``PAPER_TRADING``.
    3. Publishes a ``KILL_SWITCH`` event so every agent is notified immediately.
    """

    def __init__(self, bus: AgentBus, redis: Redis) -> None:
        self.bus = bus
        self.redis = redis

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def activate(self, reason: str) -> None:
        """Activate the kill switch."""
        await self.redis.set(KILL_SWITCH_KEY, "1")
        await self.redis.set(SYSTEM_MODE_KEY, "PAPER_TRADING")

        logger.warning("kill_switch_activated", reason=reason)

        await self.bus.publish(
            AgentMessage(
                sender_id="risk.kill_switch",
                channel="horizon.risk.kill_switch",
                message_type=MessageType.KILL_SWITCH,
                payload={
                    "active": True,
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    async def deactivate(self) -> None:
        """Deactivate the kill switch (manual override only)."""
        await self.redis.delete(KILL_SWITCH_KEY)
        logger.info("kill_switch_deactivated")

        await self.bus.publish(
            AgentMessage(
                sender_id="risk.kill_switch",
                channel="horizon.risk.kill_switch",
                message_type=MessageType.KILL_SWITCH,
                payload={
                    "active": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    async def is_active(self) -> bool:
        """Check whether the kill switch is currently engaged."""
        val = await self.redis.get(KILL_SWITCH_KEY)
        return val == "1"

    # ------------------------------------------------------------------ #
    # Threshold checking
    # ------------------------------------------------------------------ #

    async def check_thresholds(
        self,
        drawdown: float,
        var_95: float,
        var_99: float,
    ) -> bool:
        """Auto-activate if risk metrics breach configured limits.

        Limits are read from the ``risk_limits`` table via Redis cache keys
        ``horizon:risk_limits:<name>``.  Falls back to reasonable defaults
        when no limits are cached.

        Returns True if the kill switch was triggered.
        """
        # Read cached limits from Redis (set by risk agent on startup)
        max_drawdown = await self._get_limit("max_drawdown_pct", default=10.0)
        max_var_95 = await self._get_limit("max_var_95_pct", default=3.0)
        max_var_99 = await self._get_limit("max_var_99_pct", default=5.0)

        # Convert from percentage to decimal for comparison
        drawdown_pct = drawdown * 100
        var_95_pct = var_95 * 100
        var_99_pct = var_99 * 100

        reasons: list[str] = []
        if drawdown_pct >= max_drawdown:
            reasons.append(f"drawdown {drawdown_pct:.2f}% >= limit {max_drawdown:.2f}%")
        if var_95_pct >= max_var_95:
            reasons.append(f"VaR95 {var_95_pct:.2f}% >= limit {max_var_95:.2f}%")
        if var_99_pct >= max_var_99:
            reasons.append(f"VaR99 {var_99_pct:.2f}% >= limit {max_var_99:.2f}%")

        if reasons:
            await self.activate("; ".join(reasons))
            return True
        return False

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _get_limit(self, name: str, default: float) -> float:
        """Read a single risk limit from Redis cache."""
        val = await self.redis.get(f"horizon:risk_limits:{name}")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return default
