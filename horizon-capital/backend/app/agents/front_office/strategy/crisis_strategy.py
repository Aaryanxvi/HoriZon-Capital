"""Crisis strategy -- active in CRISIS regimes.

Generates defensive SELL / close signals when the VIX proxy exceeds 30,
instructing the portfolio to move to cash.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class CrisisStrategy(BaseStrategy):

    VIX_THRESHOLD = 30.0

    @property
    def name(self) -> str:
        return "crisis"

    @property
    def active_regimes(self) -> list[str]:
        return ["CRISIS"]

    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        vix_proxy = features.get("vix_proxy")
        close = features.get("close")
        atr = features.get("atr")

        if vix_proxy is None:
            return None

        # ----- Full defensive mode when VIX > 30 -----
        if vix_proxy > self.VIX_THRESHOLD:
            # Strength proportional to how far above threshold
            overshoot = (vix_proxy - self.VIX_THRESHOLD) / self.VIX_THRESHOLD
            strength = round(min(0.7 + 0.3 * overshoot, 1.0), 4)

            return Signal(
                symbol=symbol,
                direction=-1,  # SELL / close longs
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"CRISIS SELL: VIX proxy={vix_proxy:.1f} > {self.VIX_THRESHOLD}. "
                    f"Close all equity longs, move to cash."
                ),
                meta={
                    "vix_proxy": vix_proxy,
                    "vix_overshoot": round(overshoot, 4),
                    "close": close,
                    "atr": atr,
                },
            )

        # ----- VIX elevated but below threshold: cautionary -----
        if vix_proxy > self.VIX_THRESHOLD * 0.8:
            strength = round(0.3 + 0.4 * ((vix_proxy - self.VIX_THRESHOLD * 0.8) / (self.VIX_THRESHOLD * 0.2)), 4)
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=min(strength, 0.6),
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"CRISIS warning: VIX proxy={vix_proxy:.1f} approaching threshold. "
                    f"Reduce equity exposure."
                ),
                meta={
                    "vix_proxy": vix_proxy,
                    "close": close,
                },
            )

        return None
