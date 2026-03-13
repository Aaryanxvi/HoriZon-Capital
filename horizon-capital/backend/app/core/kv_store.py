"""Key-value store abstraction for LOCAL and POSTGRES modes.

In LOCAL mode, uses a simple in-memory dict.
In POSTGRES mode, delegates to Redis.
"""

from __future__ import annotations

from typing import Any


class MemoryKVStore:
    """In-memory key-value store mimicking the Redis interface used by agents."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str) -> None:
        self._data[key] = str(value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def hset(self, name: str, mapping: dict[str, str] | None = None, **kwargs: str) -> int:
        if name not in self._hashes:
            self._hashes[name] = {}
        data = mapping or {}
        data.update(kwargs)
        self._hashes[name].update({k: str(v) for k, v in data.items()})
        return len(data)

    async def hget(self, name: str, key: str) -> str | None:
        return self._hashes.get(name, {}).get(key)

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self._hashes.get(name, {}))

    async def ping(self) -> bool:
        return True


# Singleton
_memory_kv = MemoryKVStore()


def get_kv_store():
    """Return the appropriate KV store based on storage backend."""
    from app.config import StorageBackend, settings

    if settings.storage_backend == StorageBackend.LOCAL:
        return _memory_kv
    else:
        from app.core.redis_client import redis_client
        return redis_client
