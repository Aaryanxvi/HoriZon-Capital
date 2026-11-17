"""Tests for the desktop morning-brief + regime endpoints."""
from __future__ import annotations

import math
import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio

_TITLES = [
    "Overnight P&L", "Regime", "Risk Snapshot",
    "Pending Approvals", "Positions Near Stop", "Debates (last 24h)",
]


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


def _db():
    return sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))


async def test_brief_sections_match_markup():
    """The structured sections render to exactly the markup string."""
    from app.core.local_storage import init_local_db
    from app.services.morning_brief import (
        _render,
        build_morning_brief,
        build_morning_brief_sections,
    )

    await init_local_db()
    sections = await build_morning_brief_sections()
    assert [s["title"] for s in sections] == _TITLES
    markup = await build_morning_brief()
    assert markup.split("\n\n")[1:] == [_render(s) for s in sections]


async def test_brief_endpoint_on_empty_db(client):
    body = client.get("/api/desktop/brief").json()
    assert [s["title"] for s in body["sections"]] == _TITLES
    regime = body["sections"][1]["lines"]
    assert regime == [[["unavailable (insufficient SPY history)", "dim"]]]


async def test_regime_empty_db_is_honest(client):
    body = client.get("/api/desktop/brief/regime").json()
    assert body["available"] is False
    assert body["state"] is None and body["history"] == []
    assert body["sleeves_live"] is False
    # Engine off still shows the configured mix, weights summing to 1.
    names = {s["name"] for s in body["sleeves"]}
    assert {"research_stack", "trend_filter", "momentum_rank"} <= names
    assert math.isclose(sum(s["weight"] for s in body["sleeves"]), 1.0, abs_tol=1e-6)


async def test_regime_computed_from_daily_bars_and_history(client):
    base = datetime(2025, 1, 1, tzinfo=UTC)
    with _db() as db:
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp, close)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                ("SPY", "NYSE", "1d", (base + timedelta(days=d)).isoformat(),
                 400 + d * 0.3 + 8 * math.sin(d / 7))
                for d in range(300)
            ]
            # Intraday bars must not leak into the daily regime fit.
            + [("SPY", "NYSE", "1m", "2099-01-01T00:00:00+00:00", 1.0)],
        )
        db.executemany(
            "INSERT INTO regime_states (id, regime, confidence, created_at) VALUES (?, ?, ?, ?)",
            [
                ("a", "RISK_OFF", 0.2, "2026-10-01T09:00:00+00:00"),
                ("b", "RISK_ON", 0.9, "2026-10-01T15:00:00+00:00"),
                ("c", "RISK_ON", 0.7, "2026-10-02T09:00:00+00:00"),
            ],
        )
    db.close()

    body = client.get("/api/desktop/brief/regime").json()
    assert body["available"] is True and body["source"] == "computed"
    assert body["state"] in {"RISK_ON", "RISK_OFF"}
    assert 0.0 <= body["p_risk_on"] <= 1.0
    assert (body["state"] == "RISK_ON") == (body["p_risk_on"] > 0.5)
    assert body["as_of"].startswith((base + timedelta(days=299)).date().isoformat())
    assert body["history"] == [
        {"date": "2026-10-01", "state": "RISK_ON", "p_risk_on": 0.9},
        {"date": "2026-10-02", "state": "RISK_ON", "p_risk_on": 0.7},
    ]


async def test_regime_falls_back_to_last_stored(client):
    with _db() as db:
        db.execute(
            "INSERT INTO regime_states (id, regime, confidence, created_at) VALUES (?, ?, ?, ?)",
            ("a", "RISK_OFF", 0.1, "2026-10-03T09:00:00+00:00"),
        )
    db.close()

    body = client.get("/api/desktop/brief/regime").json()
    assert body["available"] is True and body["source"] == "stored"
    assert (body["state"], body["p_risk_on"], body["as_of"]) == ("RISK_OFF", 0.1, "2026-10-03")
