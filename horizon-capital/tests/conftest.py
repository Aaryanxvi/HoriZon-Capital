"""Shared pytest fixtures for the Horizon Capital test suite."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Generator

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Event loop -- use session-scoped loop for all async fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a session-scoped event loop for pytest-asyncio."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

TEST_DB_URL = settings.database_url.replace(
    f"/{settings.postgres_db}",
    f"/{settings.postgres_db}_test",
)


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a test-scoped async engine pointing at the *_test database."""
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def async_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session that rolls back after each test."""
    factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def redis_client() -> AsyncGenerator[aioredis.Redis, None]:
    """Provide a test Redis connection (uses DB 1 to isolate from prod)."""
    test_redis_url = settings.redis_url.rstrip("/0") + "/1"
    pool = aioredis.ConnectionPool.from_url(
        test_redis_url,
        max_connections=5,
        decode_responses=True,
    )
    client = aioredis.Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.flushdb()
        await pool.disconnect()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def test_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the FastAPI app."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Return Authorization headers with a valid JWT for testing."""
    token = create_access_token({"sub": "test_admin", "role": "cio"})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_ohlcv_data() -> pd.DataFrame:
    """Generate a sample OHLCV DataFrame with 200 rows of synthetic data."""
    np.random.seed(42)
    n = 200
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="B")

    # Random walk for close prices starting at 100
    returns = np.random.normal(0.0005, 0.02, n)
    close = 100 * np.cumprod(1 + returns)

    # Generate OHLCV from close
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = low + (high - low) * np.random.uniform(0.2, 0.8, n)
    volume = np.random.randint(1_000_000, 50_000_000, n)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )
    df.index.name = "timestamp"
    return df


@pytest.fixture()
def sample_returns() -> np.ndarray:
    """Generate a sample returns array (252 daily returns)."""
    np.random.seed(42)
    return np.random.normal(0.0004, 0.015, 252)


@pytest.fixture()
def sample_equity_curve() -> np.ndarray:
    """Generate a sample equity curve (252 points starting at 1M)."""
    np.random.seed(42)
    returns = np.random.normal(0.0004, 0.015, 252)
    equity = 1_000_000 * np.cumprod(1 + returns)
    return equity
