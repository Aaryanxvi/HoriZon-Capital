"""Crisis strategy -- active in CRISIS regimes.

Uses trend-following overlay as crisis alpha + partial drawdown hedging
instead of hard VIX thresholds.  Dynamic trailing stop-losses replace
binary risk-off positioning.

References
----------
- "Enhancing Global Equity Returns with Trend-Following and Tail Risk Hedging
  Overlays" (Investment Analysts Journal, Taylor & Francis, 2025)
  — Trend-following as "crisis alpha" source.
- "Tail Risk Hedging: The Superiority of the Naive Hedging Strategy"
  (J. Futures Markets, Wiley, 2025) — Simple hedging outperforms complex.
- LongTail Alpha (2021), "Tail Risk Hedging Performance"
  — Hedging first 10-15% of drawdown secures most compounding benefit.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal
from app.core.logging import get_logger

logger = get_logger("strategy.crisis")

# Trend-following parameters
_EMA_FAST = 10  # fast EMA for trend detection
_EMA_SLOW = 50  # slow EMA for trend confirmation
_DRAWDOWN_HEDGE_START = 0.05  # start hedging at 5% drawdown
_DRAWDOWN_HEDGE_FULL = 0.15  # full hedge at 15% drawdown
_TRAILING_STOP_ATR_MULTIPLE = 3.0  # dynamic trailing stop = 3x ATR


class CrisisStrategy(BaseStrategy):

    VIX_THRESHOLD = 30.0  # legacy threshold (still used as one signal)

    @property
    def llm_system_prompt(self) -> str:
        return (
            "You are a defensive capital preservation strategist using trend-following "
            "overlays and partial drawdown hedging. You monitor VIX levels, trend "
            "indicators, and drawdown depth. Your key insight: hedge the first 10-15% "
            "of drawdown (that's where most compounding benefit is). Use dynamic "
            "trailing stops, not hard thresholds. "
            "Analyze the given indicators and return a JSON signal. "
            '{"direction": 1|-1|0, "strength": 0.0-1.0, "reasoning": "..."}'
        )

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
        close = features.get("close")
        vix_proxy = features.get("vix_proxy")
        atr = features.get("atr")  # noqa: F841

        if close is None:
            return None

        # Collect signals from multiple crisis detection methods
        crisis_signals: list[dict] = []

        # 1. Trend-following overlay (crisis alpha)
        tf_signal = self._trend_following_signal(features)
        if tf_signal is not None:
            crisis_signals.append(tf_signal)

        # 2. Drawdown-based partial hedging
        dd_signal = self._drawdown_hedge_signal(features)
        if dd_signal is not None:
            crisis_signals.append(dd_signal)

        # 3. VIX/fear gauge (enhanced with gradual scaling)
        vix_signal = self._vix_signal(vix_proxy)
        if vix_signal is not None:
            crisis_signals.append(vix_signal)

        # 4. Dynamic trailing stop
        stop_signal = self._trailing_stop_signal(features)
        if stop_signal is not None:
            crisis_signals.append(stop_signal)

        if not crisis_signals:
            return None

        # Combine signals: take the strongest defensive signal
        # Weight by reliability: trend-following > drawdown > VIX > stop
        weights = {"trend_following": 0.35, "drawdown_hedge": 0.30,
                    "vix_fear": 0.20, "trailing_stop": 0.15}

        total_weight = 0.0
        weighted_strength = 0.0
        reasons: list[str] = []
        all_meta: dict[str, Any] = {"close": close, "method": "multi_signal"}

        for sig in crisis_signals:
            w = weights.get(sig["type"], 0.2)
            weighted_strength += sig["strength"] * w
            total_weight += w
            reasons.append(sig["reason"])
            all_meta.update(sig.get("meta", {}))

        if total_weight > 0:
            final_strength = weighted_strength / total_weight
        else:
            final_strength = 0.0

        if final_strength < 0.2:
            return None

        # Count how many signals fired
        signal_count = len(crisis_signals)
        all_meta["crisis_signal_count"] = signal_count
        all_meta["signal_types"] = [s["type"] for s in crisis_signals]

        # Boost strength when multiple signals confirm
        if signal_count >= 3:
            final_strength = min(final_strength * 1.2, 1.0)
        elif signal_count >= 2:
            final_strength = min(final_strength * 1.1, 1.0)

        return Signal(
            symbol=symbol,
            direction=-1,
            strength=round(final_strength, 4),
            strategy_name=self.name,
            regime=regime,
            reasoning=f"CRISIS ({signal_count} signals): " + "; ".join(reasons),
            meta=all_meta,
        )

    # ------------------------------------------------------------------ #
    # Signal components
    # ------------------------------------------------------------------ #

    @staticmethod
    def _trend_following_signal(features: dict[str, Any]) -> dict | None:
        """Trend-following overlay: bearish EMA crossover + price breakdown.

        This is the "crisis alpha" source — trend-following systems
        historically generate positive returns during equity drawdowns.
        """
        close = features.get("close", 0)
        ema_short = features.get("ema_10") or features.get("ema_20")
        ema_long = features.get("ema_50") or features.get("ema_200")

        if ema_short is None or ema_long is None or close <= 0:
            return None

        # Bearish crossover: fast EMA below slow EMA
        if ema_short >= ema_long:
            return None

        # How far below (trend strength)
        crossover_depth = (ema_long - ema_short) / ema_long
        price_below_ema = (ema_short - close) / ema_short if close < ema_short else 0

        strength = min(0.4 + crossover_depth * 5 + price_below_ema * 3, 1.0)

        return {
            "type": "trend_following",
            "strength": strength,
            "reason": (
                f"Trend breakdown: EMA{_EMA_FAST}={ema_short:.2f} < EMA{_EMA_SLOW}={ema_long:.2f}"
            ),
            "meta": {
                "ema_fast": ema_short,
                "ema_slow": ema_long,
                "crossover_depth": round(crossover_depth, 4),
            },
        }

    @staticmethod
    def _drawdown_hedge_signal(features: dict[str, Any]) -> dict | None:
        """Partial drawdown hedging: hedge first 10-15% of drawdown.

        Per LongTail Alpha research, hedging the first 10-15% of drawdown
        captures most of the compounding benefit.
        """
        current_drawdown = features.get("current_drawdown", 0.0)
        if current_drawdown < _DRAWDOWN_HEDGE_START:
            return None

        # Gradual scaling: 0% hedge at 5% DD, 100% hedge at 15% DD
        hedge_range = _DRAWDOWN_HEDGE_FULL - _DRAWDOWN_HEDGE_START
        if hedge_range <= 0:
            hedge_ratio = 1.0
        else:
            hedge_ratio = min(
                (current_drawdown - _DRAWDOWN_HEDGE_START) / hedge_range,
                1.0,
            )

        strength = 0.3 + 0.7 * hedge_ratio

        return {
            "type": "drawdown_hedge",
            "strength": strength,
            "reason": f"Drawdown hedge: {current_drawdown:.1%} DD, hedge ratio={hedge_ratio:.0%}",
            "meta": {
                "current_drawdown": round(current_drawdown, 4),
                "hedge_ratio": round(hedge_ratio, 4),
            },
        }

    @staticmethod
    def _vix_signal(vix_proxy: float | None) -> dict | None:
        """VIX/fear gauge with gradual scaling (not hard threshold)."""
        if vix_proxy is None:
            return None

        # Gradual response starting at VIX 20 (elevated), full at 35+
        if vix_proxy < 20:
            return None

        # Smooth scaling from 20 to 40
        normalised = (vix_proxy - 20) / 20  # 0 at VIX=20, 1.0 at VIX=40
        strength = min(0.3 + 0.7 * normalised, 1.0)

        return {
            "type": "vix_fear",
            "strength": strength,
            "reason": f"VIX elevated: {vix_proxy:.1f}",
            "meta": {"vix_proxy": vix_proxy},
        }

    @staticmethod
    def _trailing_stop_signal(features: dict[str, Any]) -> dict | None:
        """Dynamic trailing stop-loss based on ATR.

        Stop = recent high - 3x ATR. More adaptive than fixed percentages.
        """
        close = features.get("close")
        atr = features.get("atr")
        recent_high = features.get("recent_high") or features.get("high_20d")

        if close is None or atr is None or recent_high is None:
            return None
        if atr <= 0 or recent_high <= 0:
            return None

        # Dynamic trailing stop level
        stop_level = recent_high - _TRAILING_STOP_ATR_MULTIPLE * atr

        if close > stop_level:
            return None

        # How far below the stop
        breach_depth = (stop_level - close) / stop_level
        strength = min(0.5 + breach_depth * 5, 1.0)

        return {
            "type": "trailing_stop",
            "strength": strength,
            "reason": (
                f"Trailing stop hit: close={close:.2f} < stop={stop_level:.2f}"
                f" (high={recent_high:.2f} - {_TRAILING_STOP_ATR_MULTIPLE}xATR)"
            ),
            "meta": {
                "stop_level": round(stop_level, 4),
                "recent_high": recent_high,
                "breach_depth": round(breach_depth, 4),
            },
        }
