"""Tests for the read-only desktop analysis endpoints."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio

ENDPOINTS = ("pnl", "exposure", "debates", "signals", "execution")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


def _db() -> sqlite3.Connection:
    return sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))


def _bars(symbol: str, closes: list[float], start: date = date(2026, 1, 1)) -> list[tuple]:
    return [
        (symbol, "NYSE", "1d", f"{start + timedelta(days=i)} 00:00:00+00:00", c)
        for i, c in enumerate(closes)
    ]


async def test_endpoints_answer_on_empty_db(client):
    for name in ENDPOINTS:
        assert client.get(f"/api/desktop/analysis/{name}").status_code == 200, name


async def test_small_samples_return_null_not_numbers(client):
    """Two debates and a handful of bars: every aggregate is None with its n."""
    db = _db()
    with db:
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp, close) VALUES (?,?,?,?,?)",
            _bars("SPY", [100, 101, 102, 103]) + _bars("AAPL", [10, 11, 12, 13]),
        )
        db.executemany(
            "INSERT INTO debate_sessions (id, symbol, proposed_action, status, final_decision,"
            " created_at) VALUES (?,?,?,?,?,?)",
            [
                ("d1", "AAPL.NASDAQ", "BUY", "COMPLETED", "APPROVED", "2026-01-01 15:00:00+00:00"),
                ("d2", "AAPL.NASDAQ", "SELL", "COMPLETED", "REJECTED", "2026-01-01 15:00:00+00:00"),
            ],
        )
        db.executemany(
            "INSERT INTO debate_arguments (id, session_id, agent_id, role, vote, round_number)"
            " VALUES (?,?,?,?,?,?)",
            [
                ("a1", "d1", "openai", "RISK", "FOR", 1),
                ("a2", "d1", "openai", "RISK (as STRATEGY)", "AGAINST", 2),
            ],
        )
        db.execute(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, current_price)"
            " VALUES ('p1', 'AAPL.NASDAQ', 'NASDAQ', 'LONG', 10, 13)"
        )
    db.close()

    deb = client.get("/api/desktop/analysis/debates").json()
    assert deb["approval_rate"] == {"value": None, "n": 2, "min": 5}
    assert deb["round2_flips"] == {"value": None, "n": 1, "min": 5, "flips": 1}
    assert deb["by_role"][0]["name"] == "RISK"
    assert {r["name"] for r in deb["by_role"]} == {"RISK", "STRATEGY"}
    # Per-session forward returns are facts, the aggregate is withheld.
    d1 = next(s for s in deb["sessions"] if s["id"] == "d1")
    assert d1["fwd_1d"] == pytest.approx(0.1)  # entry 10 (day-0 close) -> 11
    assert next(s for s in deb["sessions"] if s["id"] == "d2")["fwd_1d"] == pytest.approx(-0.1)
    assert d1["fwd_5d"] is None  # not enough bars
    assert deb["outcome"]["APPROVED"]["1d"]["avg"] == {"value": None, "n": 1, "min": 5}

    exp = client.get("/api/desktop/analysis/exposure").json()
    assert exp["holdings"][0]["beta"] == {"value": None, "n": 3, "min": 20}
    assert exp["correlation"]["matrix"] == [[None]]


async def test_beta_and_forward_stats_with_enough_data(client):
    spy = [100 * (1 + 0.01 * ((i % 3) - 1)) ** i for i in range(30)]
    twice = [100.0]
    for a, b in zip(spy, spy[1:], strict=False):
        twice.append(twice[-1] * (1 + 2 * (b / a - 1)))  # exactly 2x SPY's daily return
    db = _db()
    with db:
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp, close) VALUES (?,?,?,?,?)",
            _bars("SPY", spy) + _bars("TWO", twice),
        )
        db.execute(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, current_price)"
            " VALUES ('p1', 'TWO.NYSE', 'NYSE', 'LONG', 1, 1)"
        )
        db.executemany(
            "INSERT INTO signals (signal_id, agent_id, symbol, direction, strategy_name,"
            " created_at) VALUES (?,?,?,?,?,?)",
            [(f"s{i}", "x", "TWO.NYSE", "BUY", "sleeve_system", f"2026-01-0{i + 1} 15:00:00+00:00")
             for i in range(5)],
        )
    db.close()

    exp = client.get("/api/desktop/analysis/exposure").json()
    beta = exp["holdings"][0]["beta"]
    assert beta["n"] == 29 and beta["value"] == pytest.approx(2.0)
    assert exp["correlation"]["matrix"][0][0] == pytest.approx(1.0)

    sig = client.get("/api/desktop/analysis/signals").json()["sleeves"]
    assert [s["sleeve"] for s in sig] == ["equity sleeves"]
    one_day = sig[0]["1d"]
    assert one_day["avg"]["n"] == 5 and one_day["avg"]["value"] is not None
    assert 0 <= one_day["hit_rate"]["value"] <= 1
