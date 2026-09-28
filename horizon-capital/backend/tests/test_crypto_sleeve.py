# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4BEC0F8B84DC
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Crypto sleeve: default-off wiring, trend/vol-damper logic, Alpaca crypto I/O."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve
from app.agents.front_office.strategy.strategy_agent import StrategyAgent
from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
from app.config import settings
from app.core.memory_bus import MemoryBus


def _agent() -> StrategyAgent:
    return StrategyAgent(bus=MemoryBus())


def _crypto_bars(closes: list[float], symbol: str = "BTC-USD") -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2019-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
        index=idx,
    )
    return {symbol: df}


# --------------------------------------------------------------------------- #
# StrategyAgent wiring
# --------------------------------------------------------------------------- #

def test_crypto_disabled_is_default_and_mix_unchanged():
    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "research_stack": 0.500,
        "trend_filter": 0.333,
        "momentum_rank": 0.167,
    }
    assert "crypto_trend" not in weights


def test_crypto_enabled_carves_weight_prorata(monkeypatch):
    monkeypatch.setattr(settings, "crypto_sleeve_enabled", True, raising=False)
    monkeypatch.setattr(settings, "crypto_sleeve_weight", 0.10, raising=False)

    weights = {s.name: s.target_weight for s in _agent()._sleeves}
    assert weights == {
        "research_stack": 0.45,
        "trend_filter": 0.2997,
        "momentum_rank": 0.1503,
        "crypto_trend": 0.10,
    }
    assert abs(sum(weights.values()) - 1.0) < 1e-6


# --------------------------------------------------------------------------- #
# CryptoTrendSleeve.compute
# --------------------------------------------------------------------------- #

def test_crypto_sleeve_long_when_above_sma():
    closes = list(np.linspace(100.0, 200.0, 300))
    bars = _crypto_bars(closes)
    as_of = bars["BTC-USD"].index[-1]

    signals = CryptoTrendSleeve().compute(bars, as_of)

    assert len(signals) == 1
    assert signals[0].symbol == "BTC-USD"
    assert signals[0].target_weight == 0.5


def test_crypto_sleeve_cash_when_below_sma():
    closes = list(np.linspace(200.0, 100.0, 300))
    bars = _crypto_bars(closes)
    as_of = bars["BTC-USD"].index[-1]

    assert CryptoTrendSleeve().compute(bars, as_of) == []


def test_crypto_sleeve_vol_damper():
    closes = list(np.linspace(100.0, 200.0, 280))
    last = closes[-1]
    # Alternating +-8% moves — stays well above its 200d SMA but spikes vol.
    for i in range(20):
        last = last * (1.08 if i % 2 == 0 else 0.92)
        closes.append(last)
    bars = _crypto_bars(closes)
    as_of = bars["BTC-USD"].index[-1]

    signals = CryptoTrendSleeve().compute(bars, as_of)

    assert len(signals) == 1
    assert signals[0].symbol == "BTC-USD"
    assert signals[0].target_weight == 0.25


# --------------------------------------------------------------------------- #
# AlpacaBroker crypto payload / normalization
# --------------------------------------------------------------------------- #

async def test_alpaca_crypto_payload(monkeypatch):
    broker = AlpacaBroker()
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": "x", "status": "accepted", "filled_qty": "0", "filled_avg_price": None}

    async def fake_post(self, url, json=None, headers=None):
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    await broker.execute(
        {"symbol": "BTC-USD", "side": "BUY", "quantity": 0.5, "order_type": "MARKET", "id": "o1"}
    )
    assert captured["payload"]["symbol"] == "BTC/USD"
    assert captured["payload"]["time_in_force"] == "gtc"

    await broker.execute(
        {"symbol": "AAPL.NASDAQ", "side": "BUY", "quantity": 1, "order_type": "MARKET", "id": "o2"}
    )
    assert captured["payload"]["symbol"] == "AAPL"
    assert captured["payload"]["time_in_force"] == "day"


async def test_alpaca_crypto_sell_clamped_to_available(monkeypatch):
    """Alpaca takes the crypto fee in the base asset, so a full exit over-sells.

    Buying 0.00016 BTC leaves 0.0001596 sellable; selling the recorded 0.00016
    is rejected with "insufficient balance for BTC" and the position can never
    be closed. Positions come back as ``BTCUSD`` while orders take ``BTC/USD``.
    """
    broker = AlpacaBroker()
    captured = {}

    class PositionsResponse:
        status_code = 200

        def json(self):
            return [{"symbol": "BTCUSD", "qty": "0.0001596",
                     "qty_available": "0.0001596"}]

    class OrderResponse:
        status_code = 200

        def json(self):
            return {"id": "x", "status": "accepted", "filled_qty": "0",
                    "filled_avg_price": None}

    async def fake_get(self, url, headers=None, **kwargs):
        assert url.endswith("/v2/positions"), f"per-symbol GET 404s: {url}"
        return PositionsResponse()

    async def fake_post(self, url, json=None, headers=None):
        captured["payload"] = json
        return OrderResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    await broker.execute({
        "symbol": "BTC-USD", "side": "SELL", "quantity": 0.00016,
        "order_type": "MARKET", "id": "sell-1",
    })
    assert captured["payload"]["qty"] == "0.0001596"


async def test_alpaca_crypto_sell_refused_without_position(monkeypatch):
    broker = AlpacaBroker()

    class EmptyPositions:
        status_code = 200

        def json(self):
            return []

    async def fake_get(self, url, headers=None, **kwargs):
        return EmptyPositions()

    async def fail_post(self, url, json=None, headers=None):
        raise AssertionError("must not place a sell with no position")

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("httpx.AsyncClient.post", fail_post)

    assert await broker.execute({
        "symbol": "ETH-USD", "side": "SELL", "quantity": 1.0,
        "order_type": "MARKET", "id": "sell-2",
    }) is None


async def test_alpaca_equity_sell_not_clamped(monkeypatch):
    """Equities settle without a base-asset fee — no extra position read."""
    broker = AlpacaBroker()
    captured = {}

    class OrderResponse:
        status_code = 200

        def json(self):
            return {"id": "x", "status": "accepted", "filled_qty": "0",
                    "filled_avg_price": None}

    async def fail_get(self, url, headers=None, **kwargs):
        raise AssertionError("equity sell should not read positions")

    async def fake_post(self, url, json=None, headers=None):
        captured["payload"] = json
        return OrderResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fail_get)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    await broker.execute({
        "symbol": "AAPL.NASDAQ", "side": "SELL", "quantity": 5,
        "order_type": "MARKET", "id": "sell-3",
    })
    assert captured["payload"]["qty"] == "5"


async def test_alpaca_positions_normalize_crypto(monkeypatch):
    broker = AlpacaBroker()

    class FakeResponse:
        status_code = 200

        def json(self):
            return [
                {
                    "symbol": "BTCUSD",
                    "asset_class": "crypto",
                    "qty": "0.5",
                    "avg_entry_price": "50000",
                    "current_price": "60000",
                }
            ]

    async def fake_get(self, url, headers=None):
        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

    positions = await broker.get_positions()
    assert positions[0]["symbol"] == "BTC-USD"


# --------------------------------------------------------------------------- #
# Off-hours crypto-only emission
# --------------------------------------------------------------------------- #

async def test_offhours_emits_crypto_only(monkeypatch):
    monkeypatch.setattr(settings, "crypto_sleeve_enabled", True, raising=False)
    agent = _agent()
    agent._last_emitted_weight = {"AAPL.NASDAQ": 0.05}

    emitted = []

    async def fake_emit(channel, message_type, payload, receiver_id="*"):
        emitted.append(payload)

    monkeypatch.setattr(agent, "emit", fake_emit)
    monkeypatch.setattr(agent, "_persist_signal", lambda payload: _noop())

    await agent._emit_signals_from_targets(
        {"BTC-USD": 0.05, "AAPL.NASDAQ": 0.0}, always_open_only=True
    )

    assert len(emitted) == 1
    assert emitted[0]["symbol"] == "BTC-USD"
    assert agent._last_emitted_weight["AAPL.NASDAQ"] == 0.05


async def _noop():
    return None
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4BEC0F8B84DC - verify with scripts/authorship.py verify
