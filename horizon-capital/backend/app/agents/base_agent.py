"""Abstract base agent with lifecycle management, heartbeats, and message bus integration."""

import abc
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    """Lazy session factory lookup -- avoids importing database at module level."""
    from app.core.runtime import get_session_factory
    return get_session_factory()


class BaseAgent(abc.ABC):
    """Base class for all Horizon Capital agents.

    Provides:
    - Registration in the ``agent_states`` table on startup.
    - Periodic heartbeat publishing (Redis + DB).
    - Helper ``emit()`` that publishes via the bus **and** persists to ``agent_messages``.
    - Lifecycle hooks (``start`` / ``stop``) with a clean shutdown flag.
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        bus: AgentBus,
        department: str = "",
        llm_provider: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.bus = bus
        self.department = department
        self.llm_provider = llm_provider
        self.logger = get_logger(f"agent.{agent_type}.{agent_id}")
        self._running: bool = False
        self._heartbeat_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Boot the agent: register, subscribe, launch heartbeat + main loop."""
        self._running = True
        await self._register()
        await self._subscribe()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.logger.info("agent_started", agent_id=self.agent_id)
        try:
            await self.run()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.logger.error("agent_run_error", agent_id=self.agent_id, error=str(exc))
            await self._set_status("ERROR", error_message=str(exc))
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Graceful shutdown."""
        if not self._running:
            return
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        await self._set_status("STOPPED")
        self.logger.info("agent_stopped", agent_id=self.agent_id)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def run(self) -> None:
        """Main agent loop.  Must respect ``self._running`` flag."""
        ...

    @abc.abstractmethod
    async def on_message(self, message: AgentMessage) -> None:
        """Called when a subscribed message arrives."""
        ...

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------

    async def emit(
        self,
        channel: str,
        message_type: MessageType,
        payload: dict,
        receiver_id: str = "*",
    ) -> None:
        """Publish a message on the bus **and** persist it to the ``agent_messages`` table."""
        msg = AgentMessage(
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            channel=channel,
            message_type=message_type,
            payload=payload,
        )
        await self.bus.publish(msg)

        # Persist to DB
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO agent_messages
                        (message_id, sender_id, receiver_id, channel, message_type, payload)
                    VALUES
                        (:message_id, :sender_id, :receiver_id, :channel, :message_type, :payload)
                    """
                ),
                {
                    "message_id": msg.message_id,
                    "sender_id": msg.sender_id,
                    "receiver_id": msg.receiver_id,
                    "channel": msg.channel,
                    "message_type": msg.message_type.value,
                    "payload": json.dumps(msg.payload, default=str),
                },
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Publish a heartbeat every 10 seconds on ``horizon.system.health``."""
        try:
            while self._running:
                now = datetime.now(UTC)
                await self.bus.publish(
                    AgentMessage(
                        sender_id=self.agent_id,
                        channel="horizon.system.health",
                        message_type=MessageType.HEARTBEAT,
                        payload={
                            "agent_id": self.agent_id,
                            "agent_type": self.agent_type,
                            "status": "RUNNING",
                            "timestamp": now.isoformat(),
                        },
                    )
                )
                # Update DB heartbeat
                async with _get_session_factory()() as session:
                    await session.execute(
                        text(
                            """
                            UPDATE agent_states
                            SET last_heartbeat = :ts, updated_at = :ts
                            WHERE agent_id = :agent_id
                            """
                        ),
                        {"ts": now, "agent_id": self.agent_id},
                    )
                    await session.commit()

                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def _register(self) -> None:
        """Upsert into ``agent_states`` with status RUNNING."""
        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO agent_states
                        (agent_id, agent_type, status, last_heartbeat,
                         config, metrics, created_at, updated_at)
                    VALUES (:agent_id, :agent_type, 'RUNNING', :now, '{}', '{}', :now, :now)
                    ON CONFLICT (agent_id) DO UPDATE
                    SET status = 'RUNNING',
                        last_heartbeat = :now,
                        updated_at = :now,
                        error_message = NULL
                    """
                ),
                {"agent_id": self.agent_id, "agent_type": self.agent_type, "now": now},
            )
            await session.commit()

    async def _subscribe(self) -> None:
        """Override in subclasses to subscribe to channels via ``self.bus.subscribe(...)``."""
        pass

    async def _set_status(self, status: str, *, error_message: str | None = None) -> None:
        """Update the agent's status in the database."""
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    UPDATE agent_states
                    SET status = :status, error_message = :error_message, updated_at = :now
                    WHERE agent_id = :agent_id
                    """
                ),
                {
                    "status": status,
                    "error_message": error_message,
                    "agent_id": self.agent_id,
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()
