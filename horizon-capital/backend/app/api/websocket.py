"""WebSocket endpoint for real-time dashboard feed via Redis pub/sub multiplexing."""

import asyncio
from collections.abc import Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.redis_client import redis_client
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


@ws_router.websocket("/ws/dashboard")
async def dashboard_websocket(
    ws: WebSocket,
    token: str = Query(...),
) -> None:
    """
    Multiplexed WebSocket feed for the CIO dashboard.

    The client connects with a JWT token as a query parameter:
        ws://host/ws/dashboard?token=<jwt>

    Once authenticated, the server subscribes to all relevant Redis pub/sub
    channels and forwards every message to the client as a JSON text frame.

    The client can also send JSON commands (e.g., subscribe/unsubscribe to
    specific channels) but the default behaviour is to receive everything.
    """
    # Authenticate
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        await ws.close(code=4001, reason="Invalid or expired token")
        return

    await manager.connect(ws)

    # Create a dedicated Redis pub/sub for this connection
    pubsub = redis_client.pubsub()

    async def _redis_listener() -> None:
        """Listen to Redis pub/sub and forward messages to the WebSocket."""
        try:
            # Subscribe to all dashboard channels (pattern subscriptions)
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

                # Wrap in envelope so the client knows the channel
                import orjson

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

    # Start the Redis listener as a background task
    listener_task = asyncio.create_task(_redis_listener())

    try:
        # Keep the connection alive; process any inbound client messages
        while True:
            data = await ws.receive_text()
            # Clients can send ping/pong or future commands here
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
