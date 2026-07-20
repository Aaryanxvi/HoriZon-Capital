"""Polymarket sleeve: default-off wiring, momentum/tail logic, pm_bars fetch."""
from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest

from app.agents.front_office.strategy.sleeves.polymarket_momentum import (
    PolymarketMomentumSleeve,
)
from app.agents.front_office.strategy.strategy_agent import StrategyAgent
from app.config import settings
from app.core.memory_bus import MemoryBus


def _agent() -> StrategyAgent:
    return StrategyAgent(bus=MemoryBus())


def _pm_bars(closes: list[float], symbol: str = "PM-x.POLY") -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 0.0},
        index=idx,
    )
    return {symbol: df}


# --------------------------------------------------------------------------- #
# StrategyAgent wiring
# --------------------------------------------------------------------------- #

def test_sleeve_disabled_default_mix_unchanged():
    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "research_stack": 0.500,
        "trend_filter": 0.333,
        "momentum_rank": 0.167,
    }
    assert "polymarket_momentum" not in weights


def test_both_optional_sleeves_carve(monkeypatch):
    monkeypatch.setattr(settings, "crypto_sleeve_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_sleeve_weight", 0.10, raising=False)
    monkeypatch.setattr(settings, "polymarket_sleeve_enabled", True, raising=False)
    monkeypatch.setattr(settings, "polymarket_sleeve_weight", 0.05, raising=False)

    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "research_stack": 0.425,
        "trend_filter": 0.28305,
        "momentum_rank": 0.14195,
        "crypto_trend": 0.10,
        "polymarket_momentum": 0.05,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-6


# --------------------------------------------------------------------------- #
# PolymarketMomentumSleeve.compute
# --------------------------------------------------------------------------- #

def test_pm_momentum_qualifies():
    # 23 flat days at 0.40, then 7 days rising to 0.55: 7d mom = +0.15 >= 0.05.
    closes = [0.40] * 23 + [0.42, 0.45, 0.48, 0.50, 0.52, 0.53, 0.55]
    bars = _pm_bars(closes)
    as_of = bars["PM-x.POLY"].index[-1]

    signals = PolymarketMomentumSleeve().compute(bars, as_of)

    assert len(signals) == 1
    assert signals[0].symbol == "PM-x.POLY"
    assert signals[0].target_weight == pytest.approx(0.25)


def test_pm_momentum_tail_skipped():
    closes = [0.95] * 30
    bars = _pm_bars(closes)
    as_of = bars["PM-x.POLY"].index[-1]

    assert PolymarketMomentumSleeve().compute(bars, as_of) == []


def test_pm_momentum_flat_no_signal():
    closes = [0.50] * 30
    bars = _pm_bars(closes)
    as_of = bars["PM-x.POLY"].index[-1]

    assert PolymarketMomentumSleeve().compute(bars, as_of) == []


# --------------------------------------------------------------------------- #
# fetch_pm_bars
# --------------------------------------------------------------------------- #

async def test_fetch_pm_bars_shape(monkeypatch):
    from app.core.kv_store import get_kv_store
    from app.data_layer.pm_bars import fetch_pm_bars

    symbol = "PM-y.POLY"
    kv = get_kv_store()
    await kv.set(
        f"horizon:pm:meta:{symbol}",
        json.dumps({"token_id": "tok123", "condition_id": "c", "slug": "y",
                    "question": "q", "end_date": ""}),
    )

    base_t = 1_700_000_000
    history = [{"t": base_t + i * 86400, "p": 0.3 + i * 0.01} for i in range(10)]

    async def fake_get(self, url, params=None, **kwargs):
        assert "prices-history" in url
        assert params["market"] == "tok123"
        return httpx.Response(200, json={"history": history})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    out = await fetch_pm_bars([symbol])

    assert symbol in out
    df = out[symbol]
    assert len(df) == 10
    assert isinstance(df.index, pd.DatetimeIndex)
    assert (df.index == df.index.normalize()).all()
    assert (df["close"] == df["open"]).all()
    assert (df["close"] == df["high"]).all()
    assert (df["close"] == df["low"]).all()
    assert df["close"].iloc[0] == pytest.approx(0.3)


# --------------------------------------------------------------------------- #
# Off-hours emission covers Polymarket
# --------------------------------------------------------------------------- #

async def test_always_open_only_covers_poly(monkeypatch):
    agent = _agent()
    agent._last_emitted_weight = {"AAPL.NASDAQ": 0.05}

    emitted = []

    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        emitted.append(payload)

    monkeypatch.setattr(agent, "emit", fake_emit)
    monkeypatch.setattr(agent, "_persist_signal", lambda payload: _noop())

    await agent._emit_signals_from_targets(
        {"PM-x.POLY": 0.03, "BTC-USD": 0.05}, always_open_only=True
    )

    symbols = {p["symbol"] for p in emitted}
    assert symbols == {"PM-x.POLY", "BTC-USD"}
    assert agent._last_emitted_weight["AAPL.NASDAQ"] == 0.05


async def _noop():
    return None
