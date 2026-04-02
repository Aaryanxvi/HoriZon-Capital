"""SQLAlchemy async engine + session factory.

In LOCAL mode, the engine/factory are never created — all callers should use
``get_db()`` which delegates to ``runtime.get_db()`` (works in both modes).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Lazy engine / factory (only materialised in POSTGRES mode) ────────────
_engine = None
_factory = None


def _ensure_engine():
    global _engine, _factory  # noqa: PLW0603
    if _engine is None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession as _AsyncSession,
        )
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker,
            create_async_engine,
        )
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.app_debug,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
        )
        _factory = async_sessionmaker(
            _engine,
            class_=_AsyncSession,
            expire_on_commit=False,
        )


@property
def _get_engine():
    _ensure_engine()
    return _engine


# Public accessors — import these instead of bare module-level globals
class _Lazy:
    """Namespace so ``from app.core.database import engine`` still works."""

    @staticmethod
    def _get_engine():
        _ensure_engine()
        return _engine

    @staticmethod
    def _get_factory():
        _ensure_engine()
        return _factory


def __getattr__(name: str):
    """Module-level __getattr__ for lazy access to engine / async_session_factory."""
    if name == "engine":
        _ensure_engine()
        return _engine
    if name == "async_session_factory":
        _ensure_engine()
        return _factory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a DB session — routes to the correct backend via runtime."""
    from app.core.runtime import get_db as _runtime_get_db
    async for session in _runtime_get_db():
        yield session
