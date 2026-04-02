"""Technical indicators per QTMRL Paper 2.

Provides 23 indicators across four categories: Trend, Volatility, Momentum,
and Volume/Other.  Each static method returns a ``pd.Series`` or ``pd.DataFrame``
that can be concatenated onto the main OHLCV frame.  The convenience method
``compute_all`` adds every indicator column in one call.

Dependencies: pandas, ta (Technical Analysis Library in Python).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ta


class TechnicalIndicators:
    """All 23 QTMRL-2 indicators implemented with pandas + ta library."""

    # ------------------------------------------------------------------
    # Trend indicators (4)
    # ------------------------------------------------------------------

    @staticmethod
    def sma(series: pd.Series, period: int = 20) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period, min_periods=1).mean().rename(f"sma_{period}")

    @staticmethod
    def ema(series: pd.Series, period: int = 20) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean().rename(f"ema_{period}")

    @staticmethod
    def heiken_ashi(df: pd.DataFrame) -> pd.DataFrame:
        """Heiken-Ashi candles derived from OHLCV data.

        Returns DataFrame with columns: ha_open, ha_high, ha_low, ha_close.
        """
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        ha_open = pd.Series(np.nan, index=df.index, dtype=float)
        ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
        ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
        ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)
        return pd.DataFrame(
            {"ha_open": ha_open, "ha_high": ha_high, "ha_low": ha_low, "ha_close": ha_close},
            index=df.index,
        )

    @staticmethod
    def ichimoku(df: pd.DataFrame) -> pd.DataFrame:
        """Ichimoku Kinko Hyo (5 lines).

        Returns: tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # Tenkan-sen (conversion line) -- 9-period midpoint
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        # Kijun-sen (base line) -- 26-period midpoint
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        # Senkou span A -- midpoint of tenkan and kijun, shifted 26 periods forward
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        # Senkou span B -- 52-period midpoint, shifted 26 periods forward
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        # Chikou span -- close shifted 26 periods back
        chikou = close.shift(-26)

        return pd.DataFrame(
            {
                "ichimoku_tenkan": tenkan,
                "ichimoku_kijun": kijun,
                "ichimoku_senkou_a": senkou_a,
                "ichimoku_senkou_b": senkou_b,
                "ichimoku_chikou": chikou,
            },
            index=df.index,
        )

    # ------------------------------------------------------------------
    # Volatility indicators (3)
    # ------------------------------------------------------------------

    @staticmethod
    def stddev(series: pd.Series, period: int = 20) -> pd.Series:
        """Rolling standard deviation."""
        return series.rolling(window=period, min_periods=1).std().rename(f"stddev_{period}")

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        indicator = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=period
        )
        return indicator.average_true_range().rename(f"atr_{period}")

    @staticmethod
    def bollinger_bands(
        series: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> pd.DataFrame:
        """Bollinger Bands (upper, middle, lower, bandwidth, %B)."""
        bb = ta.volatility.BollingerBands(close=series, window=period, window_dev=std_dev)
        return pd.DataFrame(
            {
                "bb_upper": bb.bollinger_hband(),
                "bb_middle": bb.bollinger_mavg(),
                "bb_lower": bb.bollinger_lband(),
                "bb_bandwidth": bb.bollinger_wband(),
                "bb_pct_b": bb.bollinger_pband(),
            },
            index=series.index,
        )

    # ------------------------------------------------------------------
    # Momentum indicators (4)
    # ------------------------------------------------------------------

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        indicator = ta.momentum.RSIIndicator(close=series, window=period)
        return indicator.rsi().rename(f"rsi_{period}")

    @staticmethod
    def macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """MACD (line, signal, histogram)."""
        indicator = ta.trend.MACD(
            close=series, window_fast=fast, window_slow=slow, window_sign=signal
        )
        return pd.DataFrame(
            {
                "macd_line": indicator.macd(),
                "macd_signal": indicator.macd_signal(),
                "macd_histogram": indicator.macd_diff(),
            },
            index=series.index,
        )

    @staticmethod
    def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """Supertrend indicator.

        Returns DataFrame with columns: supertrend, supertrend_direction (+1 up, -1 down).
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]

        atr_vals = ta.volatility.AverageTrueRange(
            high=high, low=low, close=close, window=period
        ).average_true_range()

        hl2 = (high + low) / 2
        upper_band = hl2 + multiplier * atr_vals
        lower_band = hl2 - multiplier * atr_vals

        supertrend_line = pd.Series(np.nan, index=df.index)
        direction = pd.Series(1, index=df.index, dtype=int)

        for i in range(period, len(df)):
            if close.iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif close.iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            if direction.iloc[i] == 1:
                lower_band.iloc[i] = max(lower_band.iloc[i], lower_band.iloc[i - 1])
                supertrend_line.iloc[i] = lower_band.iloc[i]
            else:
                upper_band.iloc[i] = min(upper_band.iloc[i], upper_band.iloc[i - 1])
                supertrend_line.iloc[i] = upper_band.iloc[i]

        return pd.DataFrame(
            {"supertrend": supertrend_line, "supertrend_direction": direction},
            index=df.index,
        )

    @staticmethod
    def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        """Stochastic Oscillator (%K and %D)."""
        indicator = ta.momentum.StochasticOscillator(
            high=df["high"], low=df["low"], close=df["close"],
            window=k_period, smooth_window=d_period,
        )
        return pd.DataFrame(
            {
                "stoch_k": indicator.stoch(),
                "stoch_d": indicator.stoch_signal(),
            },
            index=df.index,
        )

    # ------------------------------------------------------------------
    # Volume indicators (4)
    # ------------------------------------------------------------------

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        indicator = ta.volume.OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"])
        return indicator.on_balance_volume().rename("obv")

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """Volume-Weighted Average Price (intraday-style cumulative)."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        return (cumulative_tp_vol / cumulative_vol.replace(0, np.nan)).rename("vwap")

    @staticmethod
    def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Money Flow Index."""
        indicator = ta.volume.MFIIndicator(
            high=df["high"], low=df["low"], close=df["close"],
            volume=df["volume"], window=period,
        )
        return indicator.money_flow_index().rename(f"mfi_{period}")

    @staticmethod
    def ad_line(df: pd.DataFrame) -> pd.Series:
        """Accumulation/Distribution Line."""
        indicator = ta.volume.AccDistIndexIndicator(
            high=df["high"], low=df["low"], close=df["close"], volume=df["volume"]
        )
        return indicator.acc_dist_index().rename("ad_line")

    # ------------------------------------------------------------------
    # Additional trend / misc indicators (8) to reach 23 total
    # ------------------------------------------------------------------

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average Directional Index."""
        indicator = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=period
        )
        return indicator.adx().rename(f"adx_{period}")

    @staticmethod
    def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        indicator = ta.trend.CCIIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=period
        )
        return indicator.cci().rename(f"cci_{period}")

    @staticmethod
    def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Williams %R."""
        indicator = ta.momentum.WilliamsRIndicator(
            high=df["high"], low=df["low"], close=df["close"], lbp=period
        )
        return indicator.williams_r().rename(f"williams_r_{period}")

    @staticmethod
    def roc(series: pd.Series, period: int = 12) -> pd.Series:
        """Rate of Change."""
        indicator = ta.momentum.ROCIndicator(close=series, window=period)
        return indicator.roc().rename(f"roc_{period}")

    @staticmethod
    def psar(df: pd.DataFrame) -> pd.DataFrame:
        """Parabolic SAR (value and direction)."""
        indicator = ta.trend.PSARIndicator(
            high=df["high"], low=df["low"], close=df["close"]
        )
        return pd.DataFrame(
            {
                "psar": indicator.psar(),
                "psar_up": indicator.psar_up(),
                "psar_down": indicator.psar_down(),
            },
            index=df.index,
        )

    @staticmethod
    def keltner_channel(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Keltner Channel (upper, middle, lower)."""
        indicator = ta.volatility.KeltnerChannel(
            high=df["high"], low=df["low"], close=df["close"], window=period
        )
        return pd.DataFrame(
            {
                "keltner_upper": indicator.keltner_channel_hband(),
                "keltner_middle": indicator.keltner_channel_mband(),
                "keltner_lower": indicator.keltner_channel_lband(),
            },
            index=df.index,
        )

    @staticmethod
    def donchian_channel(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Donchian Channel (upper, middle, lower)."""
        indicator = ta.volatility.DonchianChannel(
            high=df["high"], low=df["low"], close=df["close"], window=period
        )
        return pd.DataFrame(
            {
                "donchian_upper": indicator.donchian_channel_hband(),
                "donchian_middle": indicator.donchian_channel_mband(),
                "donchian_lower": indicator.donchian_channel_lband(),
            },
            index=df.index,
        )

    @staticmethod
    def trix(series: pd.Series, period: int = 15) -> pd.Series:
        """TRIX oscillator."""
        indicator = ta.trend.TRIXIndicator(close=series, window=period)
        return indicator.trix().rename(f"trix_{period}")

    # ------------------------------------------------------------------
    # Master method: attach all 23 indicators
    # ------------------------------------------------------------------

    @classmethod
    def compute_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Add all 23 indicator columns to an OHLCV DataFrame (in-place copy).

        Expects columns: open, high, low, close, volume.
        Returns a new DataFrame with original + indicator columns.
        """
        out = df.copy()
        close = out["close"]

        # Trend (4): SMA, EMA, Heiken-Ashi, Ichimoku
        out["sma_20"] = cls.sma(close, 20)
        out["ema_20"] = cls.ema(close, 20)
        ha = cls.heiken_ashi(out)
        out = pd.concat([out, ha], axis=1)
        ichi = cls.ichimoku(out)
        out = pd.concat([out, ichi], axis=1)

        # Volatility (3): StdDev, ATR, Bollinger Bands
        out["stddev_20"] = cls.stddev(close, 20)
        out["atr_14"] = cls.atr(out, 14)
        bb = cls.bollinger_bands(close, 20, 2.0)
        out = pd.concat([out, bb], axis=1)

        # Momentum (4): RSI, MACD, Supertrend, Stochastic
        out["rsi_14"] = cls.rsi(close, 14)
        macd_df = cls.macd(close, 12, 26, 9)
        out = pd.concat([out, macd_df], axis=1)
        st = cls.supertrend(out, 10, 3.0)
        out = pd.concat([out, st], axis=1)
        stoch = cls.stochastic(out, 14, 3)
        out = pd.concat([out, stoch], axis=1)

        # Volume (4): OBV, VWAP, MFI, A/D Line
        out["obv"] = cls.obv(out)
        out["vwap"] = cls.vwap(out)
        out["mfi_14"] = cls.mfi(out, 14)
        out["ad_line"] = cls.ad_line(out)

        # Additional (8): ADX, CCI, Williams %R, ROC, PSAR, Keltner, Donchian, TRIX
        out["adx_14"] = cls.adx(out, 14)
        out["cci_20"] = cls.cci(out, 20)
        out["williams_r_14"] = cls.williams_r(out, 14)
        out["roc_12"] = cls.roc(close, 12)
        psar_df = cls.psar(out)
        out = pd.concat([out, psar_df], axis=1)
        keltner = cls.keltner_channel(out, 20)
        out = pd.concat([out, keltner], axis=1)
        donchian = cls.donchian_channel(out, 20)
        out = pd.concat([out, donchian], axis=1)
        out["trix_15"] = cls.trix(close, 15)

        return out
