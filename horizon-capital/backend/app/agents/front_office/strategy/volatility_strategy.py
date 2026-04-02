"""Volatility strategy -- active in HIGH_VOL regimes.

Primary: GJR-GARCH(1,1) with Student-t innovations for conditional volatility
forecasting.  Captures leverage effect (negative returns increase vol more).
Fallback: ATR ratio when arch library is unavailable or insufficient data.

References
----------
- Hansen & Lunde (2005), "A Forecast Comparison of Volatility Models:
  Does Anything Beat a GARCH(1,1)?", J. Applied Econometrics.
  (Compared 330 models; asymmetric GJR-GARCH dominates for equities.)
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal
from app.core.logging import get_logger

logger = get_logger("strategy.volatility")

# GARCH parameters
_GARCH_MIN_SAMPLES = 60
_VOL_SPIKE_THRESHOLD = 1.5  # forecast / recent avg
_VOL_DANGER_THRESHOLD = 2.0


class VolatilityStrategy(BaseStrategy):

    ATR_DANGER_MULTIPLE = 2.0

    @property
    def llm_system_prompt(self) -> str:
        return (
            "You are a volatility-aware risk specialist using GARCH models. "
            "You monitor conditional volatility forecasts and leverage effects "
            "to determine when exposure should be reduced. Position sizing "
            "scales inversely with forecast volatility, not just historical ATR. "
            "Analyze the given indicators and return a JSON signal. "
            '{"direction": 1|-1|0, "strength": 0.0-1.0, "reasoning": "..."}'
        )

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
        # Try GARCH-based signal first if we have return history
        return_history = features.get("return_history")
        if return_history is not None and len(return_history) >= _GARCH_MIN_SAMPLES:
            signal = self._garch_signal(symbol, features, regime, return_history)
            if signal is not None:
                return signal

        # Fallback to ATR-based signal
        return self._atr_signal(symbol, features, regime)

    # ------------------------------------------------------------------ #
    # Primary: GJR-GARCH conditional volatility forecast
    # ------------------------------------------------------------------ #

    def _garch_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
        returns: Any,
    ) -> Signal | None:
        """Generate signal using GJR-GARCH(1,1)-t conditional vol forecast."""
        try:
            from arch import arch_model
        except ImportError:
            return None

        returns_arr = np.array(returns, dtype=np.float64)
        close = features.get("close", 0.0)

        # Scale to percentage for numerical stability
        scaled = returns_arr * 100.0

        try:
            model = arch_model(
                scaled,
                vol="GARCH",
                p=1,
                o=1,  # GJR asymmetric term
                q=1,
                dist="StudentsT",
                mean="Zero",
            )
            result = model.fit(disp="off", show_warning=False)
        except Exception as exc:
            logger.debug("garch_fit_failed_in_vol_strategy", error=str(exc))
            return None

        # One-step-ahead forecast
        forecast = result.forecast(horizon=1)
        next_var = forecast.variance.values[-1, 0]
        next_vol = float(np.sqrt(next_var)) / 100.0  # back to decimal

        # Historical average conditional volatility
        cond_vol = result.conditional_volatility / 100.0
        avg_vol = (
            float(np.mean(cond_vol[-20:])) if len(cond_vol) >= 20 else float(np.mean(cond_vol))
        )
        if avg_vol <= 0:
            return None

        vol_ratio = next_vol / avg_vol

        # Leverage effect: GJR gamma parameter
        gamma = float(result.params.get("gamma[1]", 0.0))
        leverage_flag = gamma > 0.05  # asymmetric effect present

        # Position factor: inverse of vol ratio
        position_factor = max(0.2, min(1.0 / vol_ratio, 1.0))

        meta = {
            "close": close,
            "forecast_vol": round(next_vol, 6),
            "avg_vol_20d": round(avg_vol, 6),
            "vol_ratio": round(vol_ratio, 4),
            "position_factor": round(position_factor, 4),
            "gjr_gamma": round(gamma, 4),
            "leverage_effect": leverage_flag,
            "method": "gjr_garch",
        }

        # SELL/reduce when vol forecast is dangerously high
        if vol_ratio > _VOL_DANGER_THRESHOLD:
            excess = (vol_ratio - _VOL_DANGER_THRESHOLD) / _VOL_DANGER_THRESHOLD
            strength = round(min(0.5 + 0.5 * excess, 1.0), 4)
            extra = " + leverage effect detected" if leverage_flag else ""

            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"GARCH REDUCE: forecast vol={next_vol:.4f} is {vol_ratio:.1f}x "
                    f"avg ({avg_vol:.4f}){extra}. Position factor={position_factor:.2f}"
                ),
                meta=meta,
            )

        # Advisory when vol is elevated
        if vol_ratio > _VOL_SPIKE_THRESHOLD:
            strength = round(0.3 * (vol_ratio - 1.0), 4)
            return Signal(
                symbol=symbol,
                direction=0,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"GARCH advisory: forecast vol {vol_ratio:.1f}x avg, "
                    f"suggest reduced sizing (factor={position_factor:.2f})"
                ),
                meta=meta,
            )

        return None

    # ------------------------------------------------------------------ #
    # Fallback: ATR ratio (legacy)
    # ------------------------------------------------------------------ #

    def _atr_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        """ATR-based volatility signal (fallback)."""
        atr = features.get("atr")
        atr_avg_20 = features.get("atr_avg_20")
        close = features.get("close")

        if any(v is None for v in [atr, atr_avg_20, close]):
            return None
        if atr_avg_20 <= 0:
            return None

        atr_ratio = atr / atr_avg_20
        position_factor = max(0.2, min(1.0 / atr_ratio, 1.0))

        meta = {
            "atr": atr,
            "atr_avg_20": atr_avg_20,
            "atr_ratio": round(atr_ratio, 4),
            "position_factor": round(position_factor, 4),
            "close": close,
            "method": "atr",
        }

        if atr_ratio > self.ATR_DANGER_MULTIPLE:
            excess = (atr_ratio - self.ATR_DANGER_MULTIPLE) / self.ATR_DANGER_MULTIPLE
            strength = round(min(0.5 + 0.5 * excess, 1.0), 4)
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"ATR REDUCE: ATR={atr:.4f} is {atr_ratio:.1f}x the 20-day avg "
                    f"({atr_avg_20:.4f}). Position factor={position_factor:.2f}"
                ),
                meta=meta,
            )

        if atr_ratio > 1.5:
            return Signal(
                symbol=symbol,
                direction=0,
                strength=round(0.3 * (atr_ratio - 1.0), 4),
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"ATR advisory: ATR {atr_ratio:.1f}x avg, suggest reduced sizing "
                    f"(factor={position_factor:.2f})"
                ),
                meta=meta,
            )

        return None
