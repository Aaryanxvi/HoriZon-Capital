"""AgentRegistry -- CRUD operations on the ``agent_states`` table."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("agent_registry")


class AgentRegistry:
    """Centralised registry for querying / mutating agent lifecycle state."""

    async def register(
        self,
        agent_id: str,
        agent_type: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update an agent's entry in ``agent_states``."""
        import orjson

        now = datetime.now(UTC)
        config_json = orjson.dumps(config or {}).decode()
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO agent_states
                        (agent_id, agent_type, status, last_heartbeat,
                         config, metrics, created_at, updated_at)
                    VALUES
                        (:agent_id, :agent_type, 'RUNNING', :now, :config, '{}', :now, :now)
                    ON CONFLICT (agent_id) DO UPDATE
                    SET agent_type = :agent_type,
                        status = 'RUNNING',
                        config = :config,
                        last_heartbeat = :now,
                        updated_at = :now,
                        error_message = NULL
                    """
                ),
                {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "now": now,
                    "config": config_json,
                },
            )
            await session.commit()
        logger.info("agent_registered", agent_id=agent_id, agent_type=agent_type)

    async def update_status(self, agent_id: str, status: str) -> None:
        """Set the status column for the given agent."""
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    UPDATE agent_states
                    SET status = :status, updated_at = :now
                    WHERE agent_id = :agent_id
                    """
                ),
                {
                    "agent_id": agent_id,
                    "status": status,
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()

    async def update_heartbeat(self, agent_id: str) -> None:
        """Bump the ``last_heartbeat`` timestamp for the agent."""
        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    UPDATE agent_states
                    SET last_heartbeat = :now, updated_at = :now
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id, "now": now},
            )
            await session.commit()

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Return every agent's state as a list of dicts."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT agent_id, agent_type, status, last_heartbeat,
                           config, metrics, error_message,
                           created_at, updated_at
                    FROM agent_states
                    ORDER BY agent_id
                    """
                )
            )
            rows = result.mappings().all()
            return [dict(r) for r in rows]

    async def get_state(self, agent_id: str) -> dict[str, Any] | None:
        """Return a single agent's state dict, or ``None`` if not found."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT agent_id, agent_type, status, last_heartbeat,
                           config, metrics, error_message,
                           created_at, updated_at
                    FROM agent_states
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None
