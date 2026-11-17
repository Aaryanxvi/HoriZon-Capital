# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-EDC13AE88244
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Tests for the read-only desktop viz endpoints."""
from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    """TestClient over the real app; lifespan seeds the per-test SQLite DB."""
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


async def test_viz_endpoints_answer_on_empty_db(client):
    nav = client.get("/api/desktop/viz/nav-daily")
    assert nav.status_code == 200
    assert set(nav.json()) == {"points", "days_recorded"}

    bench = client.get("/api/desktop/viz/benchmark")
    assert bench.status_code == 200
    assert bench.json() == {"symbol": "SPY", "points": []}

    sleeves = client.get("/api/desktop/viz/sleeves").json()
    assert sleeves == {"available": False, "market_open": None, "sleeves": [], "targets": {}}


async def test_benchmark_rejects_bad_symbol(client):
    assert client.get("/api/desktop/viz/benchmark?symbol=../x").status_code == 422
    assert client.get("/api/desktop/viz/nav-daily?days=0").status_code == 422


async def test_daily_rows_dedupe_to_last_per_day(client):
    """Last snapshot per day wins; benchmark matches bare and suffixed symbols."""
    db = sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))
    with db:
        db.execute("DELETE FROM portfolio_snapshots")
        db.executemany(
            "INSERT INTO portfolio_snapshots (id, total_value, cash_usd, equity_value, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                ("a", 100.0, 50.0, 50.0, "2026-08-30 15:00:00.000001+00:00"),
                ("b", 101.0, 50.0, 51.0, "2026-08-30 17:11:38.363417+00:00"),
                ("c", 99.0, 40.0, 59.0, "2026-08-31 09:00:00+00:00"),
            ],
        )
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp, close)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                ("SPY", "NYSE", "1d", "2026-08-30 00:00:00+00:00", 500.0),
                ("SPY.NYSE", "NYSE", "1d", "2026-08-30 20:00:00+00:00", 501.0),
                ("SPY", "NYSE", "1m", "2026-08-30 21:00:00+00:00", 999.0),
                ("SPYX", "NYSE", "1d", "2026-08-30 20:00:00+00:00", 7.0),
            ],
        )
    db.close()

    nav = client.get("/api/desktop/viz/nav-daily").json()
    assert nav["days_recorded"] == 2
    assert nav["points"][0] == {
        "date": "2026-08-30", "nav": 101.0, "cash_usd": 50.0, "equity_value": 51.0,
    }
    assert nav["points"][1]["date"] == "2026-08-31"

    bench = client.get("/api/desktop/viz/benchmark?symbol=spy&days=20000").json()
    assert bench == {"symbol": "SPY", "points": [{"date": "2026-08-30", "close": 501.0}]}


async def test_sleeves_reads_running_strategy_agent(client):
    sleeve = SimpleNamespace(name="trend", target_weight=0.5, rebalance_days=5)
    agent = SimpleNamespace(
        agent_type="strategy",
        _sleeves=[sleeve],
        _sleeve_last_refresh={"trend": None},
        _sleeve_cache={"trend": [SimpleNamespace(symbol="SPY", target_weight=0.4)]},
        _last_emitted_weight={"SPY": 0.2},
    )
    client.app.state.orchestrator = SimpleNamespace(_slots={"s": SimpleNamespace(agent=agent)})
    try:
        body = client.get("/api/desktop/viz/sleeves").json()
    finally:
        client.app.state.orchestrator = None

    assert body["available"] is True
    assert isinstance(body["market_open"], bool)
    assert body["sleeves"] == [{
        "name": "trend", "weight": 0.5, "cadence_days": 5, "last_refresh": None,
        "signals": [{"symbol": "SPY", "weight": 0.2}],
    }]
    assert body["targets"] == {"SPY": 0.2}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token EDC13AE88244 - verify with scripts/authorship.py verify
