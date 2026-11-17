"""Tests for the read-only desktop insights endpoints."""
from __future__ import annotations

import os
import sqlite3

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


def _db():
    return sqlite3.connect(os.path.join(os.environ["HORIZON_DATA_DIR"], "horizon.db"))


async def test_every_tab_answers_on_empty_db(client):
    for tab in ("risk", "trades", "benchmark", "costs", "health"):
        assert client.get(f"/api/desktop/insights/{tab}").status_code == 200, tab

    trades = client.get("/api/desktop/insights/trades").json()
    assert trades["stats"]["count"] == 0
    assert trades["stats"]["win_rate"] == {"value": None, "n": 0, "min": 10}

    bench = client.get("/api/desktop/insights/benchmark").json()
    assert bench["beta"]["value"] is None and bench["days"] == 0

    costs = client.get("/api/desktop/insights/costs").json()
    assert costs["llm"] == {"recorded": False}  # no llm_usage table in a fresh DB

    health = client.get("/api/desktop/insights/health").json()
    assert health["engine"]["running"] is False and health["agents_live"] is False


async def test_spy_shock_arithmetic():
    from app.api.desktop_insights import _spy_shock

    book = [
        {"mv": 100_000.0, "beta": 1.2},
        {"mv": -50_000.0, "beta": 0.5},  # short gains when SPY falls
        {"mv": 20_000.0, "beta": None},  # no history: reported, not guessed
    ]
    out = _spy_shock(book, -0.10)
    assert out["pnl"] == pytest.approx(-12_000 + 2_500)
    assert out["unmodeled_usd"] == 20_000


async def test_risk_tab_stops_scenarios_and_sample_gates(client):
    db = _db()
    with db:
        db.execute("DELETE FROM positions")
        db.executemany(
            "INSERT INTO positions (id, symbol, exchange, side, quantity, avg_entry_price,"
            " current_price, stop_loss_price) VALUES (?, ?, ?, 'LONG', ?, ?, ?, ?)",
            [
                ("a", "SPY.NYSE", "NYSE", 10, 500.0, 500.0, 400.0),
                ("b", "BTC-USD", "CRYPTO", 1, 50_000.0, 50_000.0, None),
            ],
        )
        # 70 daily SPY bars alternating +1% / -1%, then 10 for a thin symbol.
        price, rows = 400.0, []
        for i in range(70):
            price *= 1.01 if i % 2 else 0.99
            day = f"2026-0{1 + i // 28}-{1 + i % 28:02d} 00:00:00+00:00"
            rows.append(("SPY", "NYSE", "1d", day, price, price * 1.01, price * 0.99, 1_000_000))
        db.executemany(
            "INSERT INTO ohlcv (symbol, exchange, timeframe, timestamp, close, high, low, volume)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )
    db.close()

    body = client.get("/api/desktop/insights/risk").json()
    spy = next(p for p in body["positions"] if p["symbol"] == "SPY.NYSE")
    btc = next(p for p in body["positions"] if p["symbol"] == "BTC-USD")

    assert spy["beta"] == pytest.approx(1.0)
    assert spy["loss_at_stop"] == pytest.approx(10 * (500 - 400))
    assert spy["days_to_exit"] is not None and spy["risk_share"] == pytest.approx(1.0)
    assert btc["beta"] is None and btc["vol"] is None and btc["bars"] == 0

    assert body["stops"]["loss_if_all_hit"] == pytest.approx(1_000)
    assert body["stops"]["unprotected_count"] == 1
    assert body["stops"]["unprotected_usd"] == pytest.approx(50_000)

    by_key = {s["key"]: s for s in body["scenarios"]}
    assert by_key["spy-10"]["pnl"] == pytest.approx(-500)
    assert by_key["spy-10"]["unmodeled_usd"] == pytest.approx(50_000)
    assert by_key["crypto30"]["pnl"] == pytest.approx(-15_000)
    assert by_key["worst_day"]["pnl"] is not None

    conc = body["concentration"]
    assert conc["hhi"] == pytest.approx((5_000 / 55_000) ** 2 + (50_000 / 55_000) ** 2)


async def test_round_trips_fifo_and_unmatched_exit():
    from app.api.desktop_insights import _round_trips, _trade_stats

    fills = [
        {"symbol": "X", "side": "BUY", "filled_qty": 10, "fill_price": 100.0,
         "commission": 1.0, "filled_at": "2026-10-01 10:00:00+00:00"},
        {"symbol": "X", "side": "BUY", "filled_qty": 10, "fill_price": 110.0,
         "commission": 0.0, "filled_at": "2026-10-02 10:00:00+00:00"},
        {"symbol": "X", "side": "SELL", "filled_qty": 15, "fill_price": 120.0,
         "commission": 1.5, "filled_at": "2026-10-03 10:00:00+00:00"},
        {"symbol": "Y", "side": "SELL", "filled_qty": 5, "fill_price": 10.0,
         "commission": 0.0, "filled_at": "2026-10-03 11:00:00+00:00"},
    ]
    closed, unmatched = _round_trips(fills)
    assert len(closed) == 1
    t = closed[0]
    assert t["qty"] == 15
    assert t["entry_price"] == pytest.approx((10 * 100 + 5 * 110) / 15)
    assert t["pnl"] == pytest.approx(15 * 120 - 1550 - 1.0 - 1.5)
    assert t["holding_days"] == pytest.approx(2.0)
    assert unmatched == [{"symbol": "Y", "qty": 5, "price": 10.0,
                          "filled_at": "2026-10-03 11:00:00+00:00"}]

    stats = _trade_stats(closed)
    assert stats["count"] == 1 and stats["expectancy"]["value"] is None  # 1 of 10 trades
    many = _trade_stats([{"pnl": p} for p in (5, 5, -2, 5, -1, -1, -1, 3, 3, 3)])
    assert many["win_rate"]["value"] == pytest.approx(0.6)
    assert many["profit_factor"]["value"] == pytest.approx(24 / 5)
    assert many["max_loss_streak"]["value"] == 3


async def test_benchmark_withholds_stats_below_minimum():
    import pandas as pd

    from app.api.desktop_insights import _bench_math

    idx = pd.date_range("2026-01-01", periods=4, freq="B")
    out = _bench_math(pd.Series([100, 101, 102, 101.0], idx),
                      pd.Series([10, 10.1, 10.3, 10.0], idx))
    assert out["days"] == 3
    assert out["beta"] == {"value": None, "n": 3, "min": 30}
    assert out["excess_return"]["value"] is None

    idx = pd.date_range("2026-01-01", periods=41, freq="B")
    bench = pd.Series([100 * (1.01 if i % 2 else 0.995) ** i for i in range(41)], idx)
    out = _bench_math(bench * 3, bench)  # same returns, different scale
    assert out["beta"]["value"] == pytest.approx(1.0)
    assert out["correlation"]["value"] == pytest.approx(1.0)
    assert out["excess_return"]["value"] == pytest.approx(0.0)
