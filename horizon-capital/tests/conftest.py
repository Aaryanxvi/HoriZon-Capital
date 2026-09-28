# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-49617DA9543B
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Shared pytest fixtures for the Horizon Capital test suite.

Works in LOCAL storage mode (SQLite + MemoryBus) without requiring
PostgreSQL or Redis.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

# Force LOCAL mode for tests
os.environ.setdefault("STORAGE_BACKEND", "LOCAL")
os.environ.setdefault("SYSTEM_MODE", "PAPER_TRADING")
os.environ.setdefault("CIO_MODE", "HUMAN")


# ---------------------------------------------------------------------------
# Event loop -- use session-scoped loop for all async fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for pytest-asyncio."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 49617DA9543B - verify with scripts/authorship.py verify
