"""Mean-reversion strategy -- active in BEAR and NEUTRAL regimes.

Generates BUY signals when price touches the lower Bollinger Band with RSI < 30,
and SELL signals when price touches the upper Bollinger Band with RSI > 70.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "mean_reversion"

    @property
    def active_regimes(self) -> list[str]:
        return ["BEAR", "NEUTRAL"]

    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        close = features.get("close")
        rsi = features.get("rsi")
        bb_upper = features.get("bb_upper")
        bb_lower = features.get("bb_lower")
        bb_mid = features.get("bb_mid")

        if any(v is None for v in [close, rsi, bb_upper, bb_lower]):
            return None

        bb_width = bb_upper - bb_lower
        if bb_width <= 0:
            return None

        # ----- BUY: price at/below lower band + RSI oversold -----
        at_lower_band = close <= bb_lower * 1.005  # within 0.5% of lower band
        rsi_oversold = rsi < 30

        if at_lower_band and rsi_oversold:
            # Strength: how far below the band + how extreme RSI is
            band_depth = max(0.0, (bb_lower - close) / bb_width)
            rsi_strength = (30 - rsi) / 30  # 0..1
            strength = round(min(0.5 + 0.3 * band_depth + 0.2 * rsi_strength, 1.0), 4)

            target = bb_mid if bb_mid else (bb_upper + bb_lower) / 2
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Mean-reversion BUY: price {close:.2f} at lower BB {bb_lower:.2f}, "
                    f"RSI={rsi:.1f}"
                ),
                meta={
                    "close": close,
                    "rsi": rsi,
                    "bb_lower": bb_lower,
                    "bb_upper": bb_upper,
                    "band_depth": band_depth,
                },
                target_price=target,
                stop_loss=bb_lower * 0.98,  # 2% below lower band
            )

        # ----- SELL: price at/above upper band + RSI overbought -----
        at_upper_band = close >= bb_upper * 0.995  # within 0.5% of upper band
        rsi_overbought = rsi > 70

        if at_upper_band and rsi_overbought:
            band_height = max(0.0, (close - bb_upper) / bb_width)
            rsi_strength = (rsi - 70) / 30  # 0..1
            strength = round(min(0.5 + 0.3 * band_height + 0.2 * rsi_strength, 1.0), 4)

            target = bb_mid if bb_mid else (bb_upper + bb_lower) / 2
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Mean-reversion SELL: price {close:.2f} at upper BB {bb_upper:.2f}, "
                    f"RSI={rsi:.1f}"
                ),
                meta={
                    "close": close,
                    "rsi": rsi,
                    "bb_lower": bb_lower,
                    "bb_upper": bb_upper,
                    "band_height": band_height,
                },
                target_price=target,
                stop_loss=bb_upper * 1.02,
            )

        return None
