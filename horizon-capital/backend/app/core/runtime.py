"""Runtime bootstrap -- selects storage backend and wires dependencies.

Depending on ``settings.storage_backend``:
  - LOCAL  -> SQLite + MemoryBus   (zero infrastructure)
  - POSTGRES -> PostgreSQL + Redis  (production)

This module exposes:
  - ``get_session_factory()`` -- returns the correct async session maker
  - ``get_bus()``             -- returns the correct message bus
  - ``startup()`` / ``shutdown()`` -- lifecycle hooks
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import StorageBackend, settings
from app.core.logging import get_logger, setup_logging

if TYPE_CHECKING:
    pass

logger = get_logger("runtime")

# ── Global singletons set at startup ──────────────────────────────────
_bus = None
_session_factory = None


def _has_balance(raw: str | None) -> bool:
    """True if a stored cash string represents a usable positive balance."""
    if raw is None:
        return False
    try:
        return float(raw) > 0
    except (ValueError, TypeError):
        return False


def get_bus():
    """Return the active message bus (MemoryBus or AgentBus)."""
    global _bus  # noqa: PLW0603
    if _bus is None:
        if settings.storage_backend == StorageBackend.LOCAL:
            from app.core.memory_bus import MemoryBus
            _bus = MemoryBus()
        else:
            from app.core.messaging import get_agent_bus
            _bus = get_agent_bus()
    return _bus


def get_session_factory():
    """Return the active async session factory."""
    global _session_factory  # noqa: PLW0603
    if _session_factory is None:
        if settings.storage_backend == StorageBackend.LOCAL:
            from app.core.local_storage import local_session_factory
            _session_factory = local_session_factory
        else:
            from app.core.database import async_session_factory
            _session_factory = async_session_factory
    return _session_factory


async def startup(*, headless: bool = False) -> None:
    """Initialise the system: create tables, start bus, etc."""
    setup_logging(debug=settings.app_debug, headless=headless)
    logger.info(
        "horizon_capital_starting",
        mode=settings.system_mode.value,
        storage=settings.storage_backend.value,
    )

    import os as _os
    force_reseed = _os.environ.pop("HORIZON_FORCE_RESEED_CAPITAL", None) == "1"

    if settings.storage_backend == StorageBackend.LOCAL:
        from app.core.local_storage import init_local_db
        await init_local_db()
        logger.info("local_sqlite_initialised")

        # Restore persisted KV keys from SQLite (crash recovery)
        from app.core.kv_store import get_kv_store
        kv = get_kv_store()
        if hasattr(kv, "restore"):
            await kv.restore()

        # Seed capital on first run (no prior cash) OR when the persisted
        # value is empty/zero so a fresh install actually shows balance.
        # Also reseed when wizard explicitly changed INITIAL_CAPITAL_*.
        existing_usd = await kv.get("horizon:cash:usd")
        existing_inr = await kv.get("horizon:cash:inr")
        if force_reseed or not _has_balance(existing_usd):
            await kv.set("horizon:cash:usd", str(int(settings.initial_capital_usd)))
            await kv.set("horizon:portfolio:nav", str(int(settings.initial_capital_usd)))
            logger.info("initial_capital_seeded_usd", usd=settings.initial_capital_usd, forced=force_reseed)
        if force_reseed or existing_inr is None:
            await kv.set("horizon:cash:inr", str(int(settings.initial_capital_inr)))
            logger.info("initial_capital_seeded_inr", inr=settings.initial_capital_inr, forced=force_reseed)
    else:
        from app.core.redis_client import redis_client
        await redis_client.set("horizon:system:mode", settings.system_mode.value)

        existing_usd = await redis_client.get("horizon:cash:usd")
        existing_inr = await redis_client.get("horizon:cash:inr")
        if force_reseed or not _has_balance(existing_usd):
            await redis_client.set("horizon:cash:usd", str(int(settings.initial_capital_usd)))
            await redis_client.set("horizon:portfolio:nav", str(int(settings.initial_capital_usd)))
            logger.info("initial_capital_seeded_usd", usd=settings.initial_capital_usd, forced=force_reseed)
        if force_reseed or existing_inr is None:
            await redis_client.set("horizon:cash:inr", str(int(settings.initial_capital_inr)))
            logger.info("initial_capital_seeded_inr", inr=settings.initial_capital_inr, forced=force_reseed)

    bus = get_bus()
    await bus.start_listening()
    logger.info("message_bus_started")


async def get_db():
    """Yield an async DB session using the correct backend."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def shutdown() -> None:
    """Graceful shutdown."""
    logger.info("horizon_capital_shutting_down")
    bus = get_bus()
    await bus.stop()

    if settings.storage_backend == StorageBackend.LOCAL:
        from app.core.local_storage import local_engine
        await local_engine.dispose()
    else:
        from app.core.database import engine
        from app.core.redis_client import close_redis
        await close_redis()
        await engine.dispose()
