"""AgentMessage model + AgentBus (Redis pub/sub) for inter-agent communication.

The message models (MessageType, AgentMessage) are always importable.
The AgentBus class requires Redis and is only instantiated when using
the POSTGRES storage backend.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import orjson
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from redis.asyncio import Redis


class MessageType(StrEnum):
    """Core message types for the trading platform."""
    TICK = "tick"
    OHLCV = "ohlcv"
    FEATURE_UPDATE = "feature_update"
    SIGNAL = "signal"
    RISK_CHECK = "risk_check"
    RISK_ALERT = "risk_alert"
    DEBATE_START = "debate_start"
    DEBATE_VOTE = "debate_vote"
    DEBATE_CONCLUSION = "debate_conclusion"
    ORDER_NEW = "order_new"
    ORDER_FILL = "order_fill"
    ORDER_CANCEL = "order_cancel"
    PORTFOLIO_UPDATE = "portfolio_update"
    HEALTH_CHECK = "health_check"
    SENTIMENT_UPDATE = "sentiment_update"
    AGENT_STATUS = "agent_status"
    HEARTBEAT = "heartbeat"


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sender_id: str
    receiver_id: str = "*"  # "*" = broadcast
    channel: str
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None

    def serialize(self) -> str:
        return orjson.dumps(self.model_dump(), default=str).decode()

    @classmethod
    def deserialize(cls, data: str) -> AgentMessage:
        return cls.model_validate(orjson.loads(data))


MessageHandler = Callable[[AgentMessage], Coroutine[Any, Any, None]]


class AgentBus:
    """Redis pub/sub wrapper for agent communication.

    Only instantiate this when running with the POSTGRES storage backend
    (i.e. when Redis is available). For LOCAL mode, use MemoryBus instead.
    """

    def __init__(self, redis: Redis | None = None):
        from app.core.redis_client import redis_client
        self._redis = redis or redis_client
        self._pubsub = self._redis.pubsub()
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._listener_task: asyncio.Task[None] | None = None

    async def publish(self, message: AgentMessage) -> int:
        """Publish a message to its channel. Returns number of subscribers that received it."""
        return await self._redis.publish(message.channel, message.serialize())

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        """Subscribe to a channel pattern. Supports wildcards (e.g., 'horizon.signal.*')."""
        if channel not in self._handlers:
            self._handlers[channel] = []
            if "*" in channel:
                await self._pubsub.psubscribe(channel)
            else:
                await self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)

    async def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel."""
        if channel in self._handlers:
            del self._handlers[channel]
            if "*" in channel:
                await self._pubsub.punsubscribe(channel)
            else:
                await self._pubsub.unsubscribe(channel)

    async def start_listening(self) -> None:
        """Start the message listener loop."""
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Internal listener loop."""
        try:
            async for raw_message in self._pubsub.listen():
                if raw_message["type"] not in ("message", "pmessage"):
                    continue

                channel = raw_message.get("channel", "")
                if isinstance(channel, bytes):
                    channel = channel.decode()

                data = raw_message.get("data", "")
                if isinstance(data, bytes):
                    data = data.decode()

                try:
                    message = AgentMessage.deserialize(data)
                except Exception:
                    continue

                # Match exact channel subscriptions
                if channel in self._handlers:
                    for handler in self._handlers[channel]:
                        asyncio.create_task(handler(message))

                # Match pattern subscriptions
                pattern = raw_message.get("pattern")
                if pattern:
                    if isinstance(pattern, bytes):
                        pattern = pattern.decode()
                    if pattern in self._handlers:
                        for handler in self._handlers[pattern]:
                            asyncio.create_task(handler(message))

        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the listener and clean up."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self._pubsub.close()


def get_agent_bus() -> AgentBus:
    """Create a new AgentBus instance. Only call when Redis is available."""
    return AgentBus()
