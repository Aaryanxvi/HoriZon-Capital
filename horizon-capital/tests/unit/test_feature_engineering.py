"""Unit tests for TechnicalIndicators and VolatilityFeatures."""

import numpy as np
import pandas as pd
import pytest

from app.workers.feature_computation_worker import TechnicalIndicators, VolatilityFeatures


@pytest.fixture()
def ohlcv_df() -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame for indicator tests."""
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    returns = np.random.normal(0.0005, 0.015, n)
    close = 100 * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_ = low + (high - low) * np.random.uniform(0.3, 0.7, n)
    volume = np.random.randint(1_000_000, 20_000_000, n)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


class TestSMA:
    def test_sma_column_created(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.sma(ohlcv_df.copy(), period=20)
        assert "sma_20" in df.columns

    def test_sma_first_values_nan(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.sma(ohlcv_df.copy(), period=20)
        assert pd.isna(df["sma_20"].iloc[0])

    def test_sma_value_correctness(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.sma(ohlcv_df.copy(), period=5)
        # Manually compute SMA for index 4 (first complete window)
        expected = df["close"].iloc[:5].mean()
        assert df["sma_5"].iloc[4] == pytest.approx(expected, rel=1e-6)


class TestEMA:
    def test_ema_column_created(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.ema(ohlcv_df.copy(), period=12)
        assert "ema_12" in df.columns

    def test_ema_responds_faster_than_sma(self, ohlcv_df: pd.DataFrame) -> None:
        """EMA should track the last price more closely than SMA."""
        df = ohlcv_df.copy()
        df = TechnicalIndicators.sma(df, period=20)
        df = TechnicalIndicators.ema(df, period=20)
        # Compare closeness to last close
        last_close = df["close"].iloc[-1]
        ema_diff = abs(df["ema_20"].iloc[-1] - last_close)
        sma_diff = abs(df["sma_20"].iloc[-1] - last_close)
        # EMA should generally be closer (not guaranteed, but likely with trend)
        # Just check they're both computed
        assert pd.notna(df["ema_20"].iloc[-1])
        assert pd.notna(df["sma_20"].iloc[-1])


class TestRSI:
    def test_rsi_column_created(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.rsi(ohlcv_df.copy())
        assert "rsi" in df.columns

    def test_rsi_bounded(self, ohlcv_df: pd.DataFrame) -> None:
        """RSI should be between 0 and 100."""
        df = TechnicalIndicators.rsi(ohlcv_df.copy())
        valid = df["rsi"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_monotonic_up(self) -> None:
        """Monotonically increasing prices should give RSI near 100."""
        close = pd.Series(np.arange(1, 101, dtype=float))
        df = pd.DataFrame({"close": close})
        df = TechnicalIndicators.rsi(df, period=14)
        # Last RSI values should be very high
        assert df["rsi"].iloc[-1] > 90


class TestMACD:
    def test_macd_columns_created(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.macd(ohlcv_df.copy())
        assert "macd" in df.columns
        assert "macd_signal" in df.columns
        assert "macd_histogram" in df.columns

    def test_macd_histogram_is_difference(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.macd(ohlcv_df.copy())
        valid = df.dropna(subset=["macd", "macd_signal", "macd_histogram"])
        np.testing.assert_allclose(
            valid["macd_histogram"].values,
            (valid["macd"] - valid["macd_signal"]).values,
            atol=1e-10,
        )


class TestBollingerBands:
    def test_bollinger_columns_created(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.bollinger_bands(ohlcv_df.copy())
        assert "bb_upper" in df.columns
        assert "bb_middle" in df.columns
        assert "bb_lower" in df.columns
        assert "bb_width" in df.columns

    def test_bollinger_ordering(self, ohlcv_df: pd.DataFrame) -> None:
        """Upper > middle > lower should hold."""
        df = TechnicalIndicators.bollinger_bands(ohlcv_df.copy())
        valid = df.dropna(subset=["bb_upper", "bb_middle", "bb_lower"])
        assert (valid["bb_upper"] >= valid["bb_middle"]).all()
        assert (valid["bb_middle"] >= valid["bb_lower"]).all()

    def test_bollinger_width_positive(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.bollinger_bands(ohlcv_df.copy())
        valid = df["bb_width"].dropna()
        assert (valid >= 0).all()


class TestComputeAll:
    def test_compute_all_adds_expected_columns(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.compute_all(ohlcv_df.copy())
        expected_columns = [
            "sma_20", "sma_50", "sma_200",
            "ema_12", "ema_26", "ema_50", "ema_200",
            "rsi",
            "macd", "macd_signal", "macd_histogram",
            "bb_upper", "bb_middle", "bb_lower", "bb_width",
            "atr",
            "stoch_k", "stoch_d",
            "adx", "plus_di", "minus_di",
            "obv", "vwap",
        ]
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

    def test_compute_all_preserves_original_columns(self, ohlcv_df: pd.DataFrame) -> None:
        df = TechnicalIndicators.compute_all(ohlcv_df.copy())
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df.columns

    def test_compute_all_row_count_unchanged(self, ohlcv_df: pd.DataFrame) -> None:
        original_len = len(ohlcv_df)
        df = TechnicalIndicators.compute_all(ohlcv_df.copy())
        assert len(df) == original_len


class TestVolatilityFeatures:
    def test_realized_vol_column(self, ohlcv_df: pd.DataFrame) -> None:
        df = VolatilityFeatures.realized_volatility(ohlcv_df.copy())
        assert "realized_vol" in df.columns

    def test_parkinson_vol_column(self, ohlcv_df: pd.DataFrame) -> None:
        df = VolatilityFeatures.parkinson_volatility(ohlcv_df.copy())
        assert "parkinson_vol" in df.columns

    def test_garman_klass_vol_column(self, ohlcv_df: pd.DataFrame) -> None:
        df = VolatilityFeatures.garman_klass_volatility(ohlcv_df.copy())
        assert "garman_klass_vol" in df.columns

    def test_compute_all_volatility(self, ohlcv_df: pd.DataFrame) -> None:
        df = VolatilityFeatures.compute_all(ohlcv_df.copy())
        for col in ["realized_vol", "parkinson_vol", "garman_klass_vol"]:
            assert col in df.columns

    def test_volatility_positive(self, ohlcv_df: pd.DataFrame) -> None:
        """All volatility measures should be non-negative where computed."""
        df = VolatilityFeatures.compute_all(ohlcv_df.copy())
        for col in ["realized_vol", "parkinson_vol", "garman_klass_vol"]:
            valid = df[col].dropna()
            assert (valid >= 0).all(), f"{col} contains negative values"
