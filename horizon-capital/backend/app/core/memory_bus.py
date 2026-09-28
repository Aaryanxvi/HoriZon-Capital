# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-0AD0F2E89732
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""In-memory message bus for running without Redis.

Drop-in replacement for the Redis-backed AgentBus. Uses asyncio.Queue
for pub/sub so no external infrastructure is needed.
"""

from __future__ import annotations

import asyncio
from fnmatch import fnmatch

from app.core.messaging import AgentMessage, MessageHandler


class MemoryBus:
    """In-memory pub/sub bus that mimics the Redis-backed AgentBus interface."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._running: bool = False
        self._queue: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._dispatch_task: asyncio.Task[None] | None = None

    async def publish(self, message: AgentMessage) -> int:
        """Enqueue a message for dispatch. Returns estimated subscriber count."""
        await self._queue.put(message)
        count = 0
        for pattern, handlers in self._handlers.items():
            if pattern == message.channel or fnmatch(message.channel, pattern):
                count += len(handlers)
        return count

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        """Register a handler for a channel (supports glob patterns)."""
        if channel not in self._handlers:
            self._handlers[channel] = []
        self._handlers[channel].append(handler)

    async def unsubscribe(self, channel: str) -> None:
        """Remove all handlers for a channel."""
        self._handlers.pop(channel, None)

    async def start_listening(self) -> None:
        """Start the dispatch loop."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        """Pull messages from the queue and dispatch to matching handlers."""
        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                channel = message.channel
                for pattern, handlers in list(self._handlers.items()):
                    if pattern == channel or fnmatch(channel, pattern):
                        for handler in handlers:
                            asyncio.create_task(handler(message))
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the dispatch loop."""
        self._running = False
        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 0AD0F2E89732 - verify with scripts/authorship.py verify
