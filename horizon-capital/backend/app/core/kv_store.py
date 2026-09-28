# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-768CBE88B945
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Key-value store abstraction for LOCAL and POSTGRES modes.

In LOCAL mode, uses a simple in-memory dict with SQLite-backed persistence
for crash recovery of critical keys.
In POSTGRES mode, delegates to Redis.
"""

from __future__ import annotations

import time

from app.core.logging import get_logger

logger = get_logger("core.kv_store")


class MemoryKVStore:
    """In-memory key-value store mimicking the Redis interface used by agents."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._expiry: dict[str, float] = {}

    async def get(self, key: str) -> str | None:
        if key in self._expiry and time.monotonic() >= self._expiry[key]:
            self._data.pop(key, None)
            del self._expiry[key]
            return None
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = str(value)
        if ex is not None:
            self._expiry[key] = time.monotonic() + ex
        elif key in self._expiry:
            del self._expiry[key]

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

    async def expire(self, key: str, seconds: int) -> None:
        """No-op in memory mode — no TTL support needed."""

    async def publish(self, channel: str, message: str) -> None:
        """No-op in memory mode — use the message bus instead."""

    async def ping(self) -> bool:
        return True


class PersistentKVStore(MemoryKVStore):
    """MemoryKVStore with periodic SQLite backup for crash recovery.

    Critical keys (cash balances, NAV, forex rates, system mode, kill switch)
    are persisted to a ``kv_cache`` table in SQLite on every write. On startup,
    ``restore()`` loads persisted keys back into memory.
    """

    _PERSIST_KEYS = {
        "horizon:cash:usd",
        "horizon:cash:inr",
        "horizon:portfolio:nav",
        "horizon:forex:usdinr",  # must match currency.FOREX_KEY
        "horizon:system:mode",
        # Kill switch must survive restart — a crash/deploy while halted must
        # NOT come back trading. risk_agent writes "horizon:system:halted";
        # the human ack clears it. (Old dead key "horizon:system:kill_switch"
        # had no writer and is removed.)
        "horizon:system:halted",
        "horizon:system:halted:ack",
        "horizon:report:eod:last_date",
        "horizon:brief:push:last_date",
    }

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        await super().set(key, value, ex=ex)
        if key in self._PERSIST_KEYS:
            await self._persist(key, value)

    async def delete(self, key: str) -> None:
        await super().delete(key)
        if key in self._PERSIST_KEYS:
            await self._delete_persisted(key)

    async def _persist(self, key: str, value: str) -> None:
        """Write key to SQLite kv_cache table."""
        try:
            from app.core.runtime import get_session_factory
            async with get_session_factory()() as session:
                from sqlalchemy import text
                await session.execute(
                    text(
                        """
                        INSERT INTO kv_cache (key, value, updated_at)
                        VALUES (:key, :value, CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE
                        SET value = :value, updated_at = CURRENT_TIMESTAMP
                        """
                    ),
                    {"key": key, "value": str(value)},
                )
                await session.commit()
        except Exception as exc:
            logger.debug("kv_persist_error", key=key, error=str(exc))

    async def _delete_persisted(self, key: str) -> None:
        """Remove a key from the SQLite kv_cache table."""
        try:
            from app.core.runtime import get_session_factory
            async with get_session_factory()() as session:
                from sqlalchemy import text
                await session.execute(
                    text("DELETE FROM kv_cache WHERE key = :key"),
                    {"key": key},
                )
                await session.commit()
        except Exception as exc:
            logger.debug("kv_delete_persist_error", key=key, error=str(exc))

    async def restore(self) -> None:
        """On startup, load persisted keys from SQLite."""
        try:
            from app.core.runtime import get_session_factory
            async with get_session_factory()() as session:
                from sqlalchemy import text
                result = await session.execute(text("SELECT key, value FROM kv_cache"))
                rows = result.fetchall()

            restored = 0
            for row in rows:
                self._data[row.key] = row.value
                restored += 1

            if restored > 0:
                logger.info("kv_store_restored", keys_restored=restored)
        except Exception as exc:
            logger.warning("kv_restore_error", error=str(exc))


# Singleton
_persistent_kv = PersistentKVStore()


def get_kv_store():
    """Return the appropriate KV store based on storage backend."""
    from app.config import StorageBackend, settings

    if settings.storage_backend == StorageBackend.LOCAL:
        return _persistent_kv
    else:
        from app.core.redis_client import redis_client
        return redis_client
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 768CBE88B945 - verify with scripts/authorship.py verify
