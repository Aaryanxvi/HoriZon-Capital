"""Three basic trading strategies using fixed technical indicator thresholds."""

from __future__ import annotations

import pandas as pd
import ta

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class RSIStrategy(BaseStrategy):
    """Buy when RSI < 30 (oversold), sell when RSI > 70 (overbought)."""

    @property
    def name(self) -> str:
        return "rsi"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 14:
            return None
        rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
        current_rsi = rsi.iloc[-1]
        if pd.isna(current_rsi):
            return None
        if current_rsi < 30:
            return Signal(
                symbol=symbol, direction=1,
                strength=min((30 - current_rsi) / 30, 1.0),
                strategy_name=self.name,
                reasoning=f"RSI oversold at {current_rsi:.1f}",
            )
        elif current_rsi > 70:
            return Signal(
                symbol=symbol, direction=-1,
                strength=min((current_rsi - 70) / 30, 1.0),
                strategy_name=self.name,
                reasoning=f"RSI overbought at {current_rsi:.1f}",
            )
        return None


class MACDStrategy(BaseStrategy):
    """Buy on MACD crossover above signal line, sell on crossover below."""

    @property
    def name(self) -> str:
        return "macd"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 26:
            return None
        macd_ind = ta.trend.MACD(df["close"])
        macd_line = macd_ind.macd()
        signal_line = macd_ind.macd_signal()
        if len(macd_line) < 2 or pd.isna(macd_line.iloc[-1]):
            return None
        current_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
        prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
        # Crossover detection — only on the bar the cross happens.
        # Pure crossover strategy: no trend-follow duplicate branch (caused double signals).
        if prev_diff <= 0 < current_diff:
            return Signal(
                symbol=symbol, direction=1,
                strength=min(abs(current_diff) / 2, 1.0),
                strategy_name=self.name,
                reasoning=f"MACD crossed above signal ({current_diff:.4f})",
            )
        elif prev_diff >= 0 > current_diff:
            return Signal(
                symbol=symbol, direction=-1,
                strength=min(abs(current_diff) / 2, 1.0),
                strategy_name=self.name,
                reasoning=f"MACD crossed below signal ({current_diff:.4f})",
            )
        return None


class BollingerBandStrategy(BaseStrategy):
    """Buy below lower Bollinger Band, sell above upper band."""

    @property
    def name(self) -> str:
        return "bollinger"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or len(df) < 20:
            return None
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        upper = bb.bollinger_hband().iloc[-1]
        lower = bb.bollinger_lband().iloc[-1]
        price = df["close"].iloc[-1]
        if pd.isna(upper) or pd.isna(lower):
            return None
        band_width = upper - lower
        if band_width == 0:
            return None
        # Symmetric band-edge entries: touch-or-pierce of upper/lower band.
        position_in_band = (price - lower) / band_width
        if position_in_band <= 0.1:
            return Signal(
                symbol=symbol, direction=1,
                strength=min((0.1 - position_in_band) / 0.1 + 0.1, 1.0),
                strategy_name=self.name,
                reasoning=f"Price {price:.2f} at lower BB (pos={position_in_band:.2f})",
            )
        elif position_in_band >= 0.9:
            return Signal(
                symbol=symbol, direction=-1,
                strength=min((position_in_band - 0.9) / 0.1 + 0.1, 1.0),
                strategy_name=self.name,
                reasoning=f"Price {price:.2f} at upper BB (pos={position_in_band:.2f})",
            )
        return None
