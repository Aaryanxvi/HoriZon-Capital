"""Tests for the desktop backtest endpoints — stub bars in the per-test SQLite DB."""
from __future__ import annotations

import math
import os
import sqlite3
import time
from datetime import date, timedelta

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


def _seed(days: int = 120) -> tuple[str, str]:
    """Sine-wave closes for TEST and SPY; returns the (start, end) date range."""
    start = date(2024, 1, 1)
    rows = []
    for i in range(days):
        ts = f"{start + timedelta(days=i)} 00:00:00+00:00"
        for sym, amp in (("TEST", 0.15), ("SPY", 0.05)):
            px = 100 * (1 + amp * math.sin(i / 8))
            rows.append((sym, "NYSE", "1d", ts, px, px * 1.01, px * 0.99, px, 1e6))
    db = sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))
    with db:
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp,"
            " open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    db.close()
    return start.isoformat(), (start + timedelta(days=days - 1)).isoformat()


def _wait(client, run_id: str) -> dict:
    for _ in range(200):
        run = client.get(f"/api/desktop/backtest/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("backtest did not finish")


def test_run_produces_curve_benchmark_and_metrics(client):
    start, end = _seed()
    body = {"strategy": "momentum", "symbols": ["test"], "start": start, "end": end,
            "capital": 100_000}
    res = client.post("/api/desktop/backtest/run", json=body)
    assert res.status_code == 202
    run = _wait(client, res.json()["id"])

    assert run["status"] == "done", run.get("error")
    assert run["symbols"] == ["TEST"]
    assert len(run["equity"]) == 120 and len(run["benchmark"]) == 120
    assert run["equity"][0]["value"] == pytest.approx(100_000, rel=1e-3)
    assert run["trades"], "a 15% sine should trigger the 5/20 SMA cross"
    m = run["metrics"]
    assert m["trades"] == len(run["trades"])
    assert 0 <= m["max_drawdown"] < 1
    assert m["total_return"] == pytest.approx(run["final_capital"] / 100_000 - 1, abs=1e-4)

    listed = client.get("/api/desktop/backtest/runs").json()
    assert listed["active"] is None
    assert [r["id"] for r in listed["runs"]] == [run["id"]]


def test_missing_data_is_an_error_not_a_crash(client, monkeypatch):
    from app.data_layer import alpaca_quotes

    monkeypatch.setattr(alpaca_quotes, "is_configured", lambda: False)  # stay offline
    _seed(30)
    body = {"strategy": "crisis", "symbols": ["TEST"], "start": "2010-01-01",
            "end": "2010-03-01", "capital": 1000}
    run = _wait(client, client.post("/api/desktop/backtest/run", json=body).json()["id"])
    assert run["status"] == "error" and "no daily bars" in run["error"]


@pytest.mark.parametrize(
    "patch",
    [
        {"symbols": ["../etc"]},
        {"symbols": []},
        {"capital": 0},
        {"start": "1999-12-31"},
        {"start": "2024-02-01", "end": "2024-01-01"},
        {"end": (date.today() + timedelta(days=2)).isoformat()},
        {"strategy": "yolo"},
    ],
)
def test_validation(client, patch):
    body = {"strategy": "momentum", "symbols": ["AAPL"], "start": "2024-01-01",
            "end": "2024-06-01", "capital": 1000, **patch}
    assert client.post("/api/desktop/backtest/run", json=body).status_code == 422


def test_one_run_at_a_time(client, monkeypatch):
    from app.api import desktop_backtest

    monkeypatch.setitem(desktop_backtest._active, "run", {"id": "abc", "status": "running"})
    body = {"symbols": ["AAPL"], "start": "2024-01-01", "end": "2024-06-01", "capital": 1000}
    assert client.post("/api/desktop/backtest/run", json=body).status_code == 409
    assert client.get("/api/desktop/backtest/runs/nothex!").status_code == 422
    assert client.get("/api/desktop/backtest/runs/0123456789ab").status_code == 404
