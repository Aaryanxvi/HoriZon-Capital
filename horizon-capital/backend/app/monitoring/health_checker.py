"""System and agent health checker.

Monitors agent heartbeats and overall system health, reporting any agents
that have gone silent (no heartbeat within the threshold window).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis_client import redis_client

logger = get_logger("monitoring.health")

# An agent is considered unhealthy if its last heartbeat is older than this.
HEARTBEAT_THRESHOLD_SECONDS = 30


class HealthChecker:
    """Monitor agent liveness and overall system health."""

    # ------------------------------------------------------------------
    # Agent heartbeat check
    # ------------------------------------------------------------------

    @staticmethod
    async def check_agent_heartbeats() -> list[dict]:
        """Return a list of agents with stale or missing heartbeats.

        An agent is flagged if:
        - Its ``last_heartbeat`` is more than 30 seconds ago, OR
        - It has status ``RUNNING`` but no heartbeat recorded.

        Returns
        -------
        list[dict]
            Each dict: ``{agent_id, agent_type, status, last_heartbeat,
            seconds_since, healthy}``.
        """
        now = datetime.now(UTC)
        threshold = now - timedelta(seconds=HEARTBEAT_THRESHOLD_SECONDS)

        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT agent_id, agent_type, status, last_heartbeat
                    FROM agent_states
                    ORDER BY agent_id
                    """
                ),
            )
            rows = result.fetchall()

        flagged: list[dict] = []
        for row in rows:
            agent_id = row[0]
            agent_type = row[1]
            status = row[2]
            last_hb = row[3]

            if last_hb is None:
                seconds_since = None
                healthy = status != "RUNNING"  # only unhealthy if supposed to be running
            else:
                if last_hb.tzinfo is None:
                    last_hb = last_hb.replace(tzinfo=UTC)
                seconds_since = (now - last_hb).total_seconds()
                healthy = last_hb >= threshold or status in ("STOPPED", "PAUSED")

            if not healthy:
                flagged.append({
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "status": status,
                    "last_heartbeat": last_hb.isoformat() if last_hb else None,
                    "seconds_since": round(seconds_since, 1) if seconds_since is not None else None,
                    "healthy": False,
                })

        if flagged:
            logger.warning("stale_heartbeats", count=len(flagged))

        return flagged

    # ------------------------------------------------------------------
    # System-wide health
    # ------------------------------------------------------------------

    @staticmethod
    async def check_system_health() -> dict:
        """Aggregate system health across DB, Redis, and agents.

        Returns
        -------
        dict
            ``{status, db_connected, redis_connected, agents_total,
            agents_healthy, agents_unhealthy, unhealthy_agents}``
        """
        # Database connectivity
        db_ok = False
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as exc:
            logger.error("db_health_check_failed", error=str(exc))

        # Redis connectivity
        redis_ok = False
        try:
            await redis_client.ping()
            redis_ok = True
        except Exception as exc:
            logger.error("redis_health_check_failed", error=str(exc))

        # Agent counts
        agents_total = 0
        agents_running = 0
        try:
            async with async_session_factory() as session:
                count_result = await session.execute(
                    text(
                        "SELECT COUNT(*), SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END)"
                        " FROM agent_states"
                    )
                )
                row = count_result.fetchone()
                if row:
                    agents_total = int(row[0])
                    agents_running = int(row[1] or 0)
        except Exception:
            pass

        # Check for stale heartbeats
        unhealthy_agents = await HealthChecker.check_agent_heartbeats()
        agents_healthy = agents_running - len(unhealthy_agents)

        overall_status = "HEALTHY"
        if not db_ok or not redis_ok:
            overall_status = "DEGRADED"
        if len(unhealthy_agents) > 0:
            overall_status = "WARNING"
        if not db_ok and not redis_ok:
            overall_status = "CRITICAL"

        health = {
            "status": overall_status,
            "db_connected": db_ok,
            "redis_connected": redis_ok,
            "agents_total": agents_total,
            "agents_running": agents_running,
            "agents_healthy": max(agents_healthy, 0),
            "agents_unhealthy": len(unhealthy_agents),
            "unhealthy_agents": [a["agent_id"] for a in unhealthy_agents],
            "checked_at": datetime.now(UTC).isoformat(),
        }

        logger.info("system_health_checked", status=overall_status)
        return health
