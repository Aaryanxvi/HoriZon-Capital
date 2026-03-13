"""Volatility strategy -- active in HIGH_VOL regimes.

Uses ATR (Average True Range) to size positions and generates exposure-reduction
signals when current ATR exceeds 2x the 20-day average ATR.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class VolatilityStrategy(BaseStrategy):

    ATR_DANGER_MULTIPLE = 2.0

    @property
    def name(self) -> str:
        return "volatility"

    @property
    def active_regimes(self) -> list[str]:
        return ["HIGH_VOL"]

    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        atr = features.get("atr")
        atr_avg_20 = features.get("atr_avg_20")
        close = features.get("close")

        if any(v is None for v in [atr, atr_avg_20, close]):
            return None

        if atr_avg_20 <= 0:
            return None

        atr_ratio = atr / atr_avg_20

        # Position-size factor: inverse of ATR ratio, clamped to [0.2, 1.0]
        position_factor = max(0.2, min(1.0 / atr_ratio, 1.0))

        # ----- Reduce exposure when ATR is dangerously high -----
        if atr_ratio > self.ATR_DANGER_MULTIPLE:
            # Strength scales with how far above the threshold we are
            excess = (atr_ratio - self.ATR_DANGER_MULTIPLE) / self.ATR_DANGER_MULTIPLE
            strength = round(min(0.5 + 0.5 * excess, 1.0), 4)

            return Signal(
                symbol=symbol,
                direction=-1,  # reduce / sell
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Volatility REDUCE: ATR={atr:.4f} is {atr_ratio:.1f}x the 20-day avg "
                    f"({atr_avg_20:.4f}). Position factor={position_factor:.2f}"
                ),
                meta={
                    "atr": atr,
                    "atr_avg_20": atr_avg_20,
                    "atr_ratio": round(atr_ratio, 4),
                    "position_factor": round(position_factor, 4),
                    "close": close,
                },
            )

        # ----- Mild vol expansion: emit a neutral/sizing advisory -----
        if atr_ratio > 1.5:
            return Signal(
                symbol=symbol,
                direction=0,  # neutral -- advisory only
                strength=round(0.3 * (atr_ratio - 1.0), 4),
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Volatility advisory: ATR {atr_ratio:.1f}x avg, suggest reduced sizing "
                    f"(factor={position_factor:.2f})"
                ),
                meta={
                    "atr": atr,
                    "atr_avg_20": atr_avg_20,
                    "atr_ratio": round(atr_ratio, 4),
                    "position_factor": round(position_factor, 4),
                    "close": close,
                },
            )

        return None
