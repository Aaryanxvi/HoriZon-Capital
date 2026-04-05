"""Tests for fast module dispatcher."""

import numpy as np
import pytest

from app.core.fast import compute_indicators, is_rust_available, run_backtest


class TestFastDispatcher:
    def test_is_rust_available_returns_bool(self):
        assert isinstance(is_rust_available(), bool)

    def test_compute_indicators_returns_dict(self):
        np.random.seed(42)
        n = 50
        close = np.cumsum(np.random.randn(n)) + 100
        high = close + np.abs(np.random.randn(n))
        low = close - np.abs(np.random.randn(n))
        volume = np.random.randint(1000, 10000, n).astype(np.float64)
        result = compute_indicators(close, high, low, volume)
        assert isinstance(result, dict)
        assert "rsi" in result
        assert "macd" in result
        assert len(result["rsi"]) == n

    def test_run_backtest_returns_metrics(self):
        np.random.seed(42)
        close = np.cumsum(np.random.randn(100) * 0.01) + 100
        signals = np.zeros(100, dtype=np.int32)
        signals[10] = 1
        signals[80] = -1
        result = run_backtest(close, signals, 100000.0, 10.0)
        assert "total_return" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result
        assert result["num_trades"] == 1

    def test_run_backtest_no_trades(self):
        np.random.seed(0)
        close = np.cumsum(np.random.randn(50) * 0.01) + 100
        signals = np.zeros(50, dtype=np.int32)
        result = run_backtest(close, signals, 100000.0, 10.0)
        assert result["num_trades"] == 0
        assert result["win_rate"] == 0.0

    def test_run_backtest_open_position_at_end(self):
        """Signal to buy but never sell — position auto-closes at end."""
        np.random.seed(7)
        close = np.cumsum(np.random.randn(50) * 0.01) + 100
        signals = np.zeros(50, dtype=np.int32)
        signals[5] = 1  # buy only, never sell
        result = run_backtest(close, signals, 100000.0, 10.0)
        assert result["num_trades"] == 1

    def test_compute_indicators_all_expected_keys(self):
        np.random.seed(1)
        n = 100
        close = np.cumsum(np.random.randn(n) * 0.5) + 100
        high = close + np.abs(np.random.randn(n) * 0.3)
        low = close - np.abs(np.random.randn(n) * 0.3)
        volume = np.random.randint(1000, 50000, n).astype(np.float64)
        result = compute_indicators(close, high, low, volume)
        expected_keys = {
            "rsi", "macd", "macd_signal", "macd_hist",
            "bb_upper", "bb_middle", "bb_lower",
            "atr", "sma_20", "sma_50", "ema_12", "ema_26",
        }
        assert expected_keys.issubset(result.keys())

    def test_run_backtest_metrics_types(self):
        np.random.seed(99)
        close = np.cumsum(np.random.randn(60) * 0.01) + 100
        signals = np.zeros(60, dtype=np.int32)
        signals[5] = 1
        signals[40] = -1
        result = run_backtest(close, signals, 50000.0, 5.0)
        assert isinstance(result["total_return"], float)
        assert isinstance(result["sharpe_ratio"], float)
        assert isinstance(result["max_drawdown"], float)
        assert isinstance(result["win_rate"], float)
        assert isinstance(result["num_trades"], int)
        assert 0.0 <= result["max_drawdown"] <= 1.0
        assert 0.0 <= result["win_rate"] <= 1.0
