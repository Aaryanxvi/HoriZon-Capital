"""Momentum strategy -- active in BULL regimes.

Generates BUY signals on RSI oversold + MACD bullish crossover + price above
EMA-20, and SELL signals on RSI overbought + MACD bearish crossover.
Signal strength is proportional to indicator confluence.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "momentum"

    @property
    def active_regimes(self) -> list[str]:
        return ["BULL"]

    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        rsi = features.get("rsi")
        macd = features.get("macd")
        macd_signal = features.get("macd_signal")
        ema_20 = features.get("ema_20")
        close = features.get("close")

        if any(v is None for v in [rsi, macd, macd_signal, ema_20, close]):
            return None

        # ----- BUY conditions -----
        rsi_oversold = rsi < 30
        macd_bullish = macd > macd_signal  # MACD above signal line
        price_above_ema = close > ema_20

        buy_score = sum([rsi_oversold, macd_bullish, price_above_ema])

        if buy_score >= 2 and macd_bullish:
            strength = self._compute_strength(rsi, macd, macd_signal, buy_score, direction=1)
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Momentum BUY: RSI={rsi:.1f}, MACD crossover "
                    f"({macd:.4f}>{macd_signal:.4f}), price {'above' if price_above_ema else 'below'} EMA20"
                ),
                meta={
                    "rsi": rsi,
                    "macd": macd,
                    "macd_signal": macd_signal,
                    "ema_20": ema_20,
                    "close": close,
                    "confluence": buy_score,
                },
            )

        # ----- SELL conditions -----
        rsi_overbought = rsi > 70
        macd_bearish = macd < macd_signal

        sell_score = sum([rsi_overbought, macd_bearish])

        if sell_score >= 2:
            strength = self._compute_strength(rsi, macd, macd_signal, sell_score, direction=-1)
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Momentum SELL: RSI={rsi:.1f}, MACD bearish "
                    f"({macd:.4f}<{macd_signal:.4f})"
                ),
                meta={
                    "rsi": rsi,
                    "macd": macd,
                    "macd_signal": macd_signal,
                    "confluence": sell_score,
                },
            )

        return None

    @staticmethod
    def _compute_strength(
        rsi: float,
        macd: float,
        macd_signal: float,
        confluence: int,
        direction: int,
    ) -> float:
        """Compute signal strength in [0.0, 1.0] based on indicator confluence.

        Factors:
        - Number of confirming indicators (confluence / 3 for buy, /2 for sell)
        - Magnitude of RSI deviation from 50
        - MACD-signal spread magnitude
        """
        # Confluence contribution
        max_indicators = 3 if direction == 1 else 2
        conf_score = confluence / max_indicators  # 0.66 - 1.0

        # RSI extremity
        rsi_deviation = abs(rsi - 50) / 50  # 0 - 1

        # MACD spread (normalised loosely)
        spread = abs(macd - macd_signal)
        macd_score = min(spread / (abs(macd_signal) + 1e-8), 1.0)

        raw = 0.5 * conf_score + 0.3 * rsi_deviation + 0.2 * macd_score
        return round(max(0.0, min(raw, 1.0)), 4)
