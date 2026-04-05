"""Mean-reversion strategy using Ornstein-Uhlenbeck process and Bollinger Bands."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal
from app.core.logging import get_logger

logger = get_logger("strategy.mean_reversion")

_OU_MIN_SAMPLES = 30
_S_SCORE_ENTRY = 1.25
_S_SCORE_EXIT = 0.5
_S_SCORE_EXTREME = 2.0


class MeanReversionStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "mean_reversion"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or df.empty:
            return None
        features = df.iloc[-1].to_dict() if isinstance(df, pd.DataFrame) else df
        return self._rule_based(symbol, features)

    def generate_signal_from_features(
        self,
        symbol: str,
        features: dict[str, Any],
    ) -> Signal | None:
        return self._rule_based(symbol, features)

    def _rule_based(self, symbol: str, features: dict[str, Any]) -> Signal | None:
        price_history = features.get("price_history")
        if price_history is not None and len(price_history) >= _OU_MIN_SAMPLES:
            return self._ou_signal(symbol, features, price_history)
        return self._bollinger_signal(symbol, features)

    def _ou_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        prices: Any,
    ) -> Signal | None:
        prices_arr = np.array(prices, dtype=np.float64)
        close = features.get("close", prices_arr[-1])

        ou_params = self._calibrate_ou(prices_arr)
        if ou_params is None:
            return self._bollinger_signal(symbol, features)

        mu, kappa, sigma, s_score = ou_params

        half_life = np.log(2) / kappa if kappa > 0 else float("inf")

        if s_score < -_S_SCORE_ENTRY:
            intensity = min(abs(s_score) / _S_SCORE_EXTREME, 1.0)
            strength = round(0.5 + 0.5 * intensity, 4)
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"OU BUY: s-score={s_score:.2f} (below -{_S_SCORE_ENTRY}), "
                    f"equilibrium={mu:.2f}, half-life={half_life:.1f}d"
                ),
                target_price=mu,
                stop_loss=close * 0.97,
            )

        if s_score > _S_SCORE_ENTRY:
            intensity = min(s_score / _S_SCORE_EXTREME, 1.0)
            strength = round(0.5 + 0.5 * intensity, 4)
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"OU SELL: s-score={s_score:.2f} (above {_S_SCORE_ENTRY}), "
                    f"equilibrium={mu:.2f}, half-life={half_life:.1f}d"
                ),
                target_price=mu,
                stop_loss=close * 1.03,
            )

        return None

    @staticmethod
    def _calibrate_ou(prices: np.ndarray) -> tuple[float, float, float, float] | None:
        if len(prices) < 20:
            return None

        log_prices = np.log(prices)
        dx = np.diff(log_prices)
        x = log_prices[:-1]

        x_mean = np.mean(x)
        dx_mean = np.mean(dx)

        ss_xx = np.sum((x - x_mean) ** 2)
        if ss_xx == 0:
            return None

        ss_xy = np.sum((x - x_mean) * (dx - dx_mean))
        b = ss_xy / ss_xx
        a = dx_mean - b * x_mean

        if b >= 0:
            return None

        kappa = -b
        mu_log = -a / b
        mu = np.exp(mu_log)

        residuals = dx - (a + b * x)
        sigma = float(np.std(residuals)) * np.sqrt(2 * kappa)

        if sigma <= 0 or kappa <= 0:
            return None

        sigma_eq = sigma / np.sqrt(2 * kappa)
        if sigma_eq <= 0:
            return None

        s_score = (log_prices[-1] - mu_log) / sigma_eq

        return mu, kappa, sigma, s_score

    def _bollinger_signal(
        self,
        symbol: str,
        features: dict[str, Any],
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

        if close <= bb_lower * 1.005 and rsi < 30:
            band_depth = max(0.0, (bb_lower - close) / bb_width)
            rsi_strength = (30 - rsi) / 30
            strength = round(min(0.5 + 0.3 * band_depth + 0.2 * rsi_strength, 1.0), 4)
            target = bb_mid if bb_mid else (bb_upper + bb_lower) / 2
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"BB BUY: price {close:.2f} at lower BB {bb_lower:.2f}, RSI={rsi:.1f}"
                ),
                target_price=target,
                stop_loss=bb_lower * 0.98,
            )

        if close >= bb_upper * 0.995 and rsi > 70:
            band_height = max(0.0, (close - bb_upper) / bb_width)
            rsi_strength = (rsi - 70) / 30
            strength = round(min(0.5 + 0.3 * band_height + 0.2 * rsi_strength, 1.0), 4)
            target = bb_mid if bb_mid else (bb_upper + bb_lower) / 2
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"BB SELL: price {close:.2f} at upper BB {bb_upper:.2f}, RSI={rsi:.1f}"
                ),
                target_price=target,
                stop_loss=bb_upper * 1.02,
            )

        return None
