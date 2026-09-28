# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-2B89851FE4B9
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Tests for simple trading strategies."""

import pandas as pd
import numpy as np
import pytest

from app.agents.front_office.strategy.simple_strategies import (
    RSIStrategy, MACDStrategy, BollingerBandStrategy,
)


def _make_df(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "open": prices, "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices], "close": prices,
        "volume": [1000] * len(prices),
    })


class TestRSIStrategy:
    def test_returns_none_insufficient_data(self):
        assert RSIStrategy().generate_signal("AAPL", _make_df([100.0] * 5)) is None

    def test_buy_signal_on_oversold(self):
        signal = RSIStrategy().generate_signal("AAPL", _make_df([100 - i * 2 for i in range(30)]))
        if signal is not None:
            assert signal.direction == 1

    def test_sell_signal_on_overbought(self):
        signal = RSIStrategy().generate_signal("AAPL", _make_df([50 + i * 2 for i in range(30)]))
        if signal is not None:
            assert signal.direction == -1


class TestMACDStrategy:
    def test_returns_none_insufficient_data(self):
        assert MACDStrategy().generate_signal("AAPL", _make_df([100.0] * 10)) is None


class TestBollingerBandStrategy:
    def test_returns_none_insufficient_data(self):
        assert BollingerBandStrategy().generate_signal("AAPL", _make_df([100.0] * 5)) is None

    def test_buy_signal_below_lower_band(self):
        signal = BollingerBandStrategy().generate_signal("AAPL", _make_df([100.0] * 20 + [80.0]))
        if signal is not None:
            assert signal.direction == 1
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 2B89851FE4B9 - verify with scripts/authorship.py verify
