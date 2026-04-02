"""WebSocket endpoint for real-time dashboard feed.

In POSTGRES mode, uses Redis pub/sub.
In LOCAL mode, subscribes to MemoryBus directly.
"""

import asyncio

import orjson
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import StorageBackend, settings
from app.core.runtime import get_bus
from app.core.security import decode_token

router = APIRouter(tags=["websocket"])

# Channels the dashboard subscribes to for the multiplexed feed
DASHBOARD_CHANNELS = [
    "horizon.tick.*",
    "horizon.signal.*",
    "horizon.order.*",
    "horizon.risk.*",
    "horizon.regime.*",
    "horizon.portfolio.*",
    "horizon.debate.*",
    "horizon.agent.*",
    "horizon.system.*",
    "horizon.cio.*",
]


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: str) -> None:
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


ws_router = APIRouter()


async def _local_bus_listener(ws: WebSocket) -> None:
    """Subscribe to MemoryBus and forward messages to WebSocket (LOCAL mode)."""
    bus = get_bus()
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def _handler(msg) -> None:  # noqa: ANN001
        envelope = orjson.dumps({
            "channel": msg.channel,
            "data": msg.serialize(),
        }).decode()
        await queue.put(envelope)

    for pattern in DASHBOARD_CHANNELS:
        await bus.subscribe(pattern, _handler)

    try:
        while True:
            envelope = await queue.get()
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(envelope)
            else:
                break
    except asyncio.CancelledError:
        pass
    finally:
        # Remove only our specific handler from each channel
        for pattern in DASHBOARD_CHANNELS:
            handlers = bus._handlers.get(pattern, [])
            if _handler in handlers:
                handlers.remove(_handler)


async def _redis_listener(ws: WebSocket) -> None:
    """Subscribe to Redis pub/sub and forward messages to WebSocket (POSTGRES mode)."""
    from app.core.redis_client import redis_client

    pubsub = redis_client.pubsub()
    try:
        for pattern in DASHBOARD_CHANNELS:
            await pubsub.psubscribe(pattern)

        async for raw_msg in pubsub.listen():
            if raw_msg["type"] not in ("message", "pmessage"):
                continue

            channel = raw_msg.get("channel", "")
            if isinstance(channel, bytes):
                channel = channel.decode()

            data = raw_msg.get("data", "")
            if isinstance(data, bytes):
                data = data.decode()

            envelope = orjson.dumps({"channel": channel, "data": data}).decode()

            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(envelope)
            else:
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        await pubsub.punsubscribe()
        await pubsub.close()


@ws_router.websocket("/ws/dashboard")
async def dashboard_websocket(
    ws: WebSocket,
    token: str = Query(default=""),
) -> None:
    """
    Multiplexed WebSocket feed for the CIO dashboard.

    The client connects with a JWT token as a query parameter:
        ws://host/ws/dashboard?token=<jwt>

    In LOCAL mode, auth is bypassed (no token required).
    """
    # Authenticate (skip in LOCAL mode)
    if settings.storage_backend != StorageBackend.LOCAL:
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            await ws.close(code=4001, reason="Invalid or expired token")
            return

    await manager.connect(ws)

    # Choose listener based on storage backend
    if settings.storage_backend == StorageBackend.LOCAL:
        listener_task = asyncio.create_task(_local_bus_listener(ws))
    else:
        listener_task = asyncio.create_task(_redis_listener(ws))

    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        manager.disconnect(ws)
