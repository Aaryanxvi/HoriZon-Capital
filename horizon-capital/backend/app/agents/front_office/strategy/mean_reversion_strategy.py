"""Mean-reversion strategy -- active in BEAR and NEUTRAL regimes.

Primary: Cointegration test + Ornstein-Uhlenbeck process + s-score signal.
Fallback: Bollinger Bands + RSI when insufficient data for OU calibration.

References
----------
- Avellaneda & Lee (2010), "Statistical Arbitrage in the U.S. Equities Market",
  Quantitative Finance (PCA eigenportfolios + OU + s-score, Sharpe 1.44).
- Gatev, Goetzmann & Rouwenhorst (2006), "Pairs Trading: Performance of a
  Relative-Value Arbitrage Rule", Review of Financial Studies.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal
from app.core.logging import get_logger

logger = get_logger("strategy.mean_reversion")

# OU model parameters
_OU_MIN_SAMPLES = 30  # Minimum price history for OU calibration
_S_SCORE_ENTRY = 1.25  # Enter when s-score exceeds this (Avellaneda-Lee)
_S_SCORE_EXIT = 0.5  # Exit when s-score falls below this
_S_SCORE_EXTREME = 2.0  # Strong signal threshold


class MeanReversionStrategy(BaseStrategy):

    @property
    def llm_system_prompt(self) -> str:
        return (
            "You are a statistical arbitrage specialist focused on mean reversion. "
            "You use cointegration tests and Ornstein-Uhlenbeck process calibration "
            "to identify spreads that are likely to revert. You compute s-scores "
            "(standardised spread deviation) for entry/exit signals. "
            "Analyze the given indicators and return a JSON signal. "
            '{"direction": 1|-1|0, "strength": 0.0-1.0, "reasoning": "..."}'
        )

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
        # Try OU-based signal first if we have price history
        price_history = features.get("price_history")
        if price_history is not None and len(price_history) >= _OU_MIN_SAMPLES:
            return self._ou_signal(symbol, features, regime, price_history)

        # Fallback to Bollinger Bands + RSI
        return self._bollinger_signal(symbol, features, regime)

    # ------------------------------------------------------------------ #
    # Primary: Ornstein-Uhlenbeck s-score signal
    # ------------------------------------------------------------------ #

    def _ou_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
        prices: Any,
    ) -> Signal | None:
        """Generate signal using calibrated Ornstein-Uhlenbeck process.

        The s-score measures how far the current price is from the
        equilibrium level, in units of the process standard deviation.
        """
        prices_arr = np.array(prices, dtype=np.float64)
        close = features.get("close", prices_arr[-1])

        # Calibrate OU parameters from price history
        ou_params = self._calibrate_ou(prices_arr)
        if ou_params is None:
            return self._bollinger_signal(symbol, features, regime)

        mu, kappa, sigma, s_score = ou_params

        # Half-life of mean reversion (days)
        half_life = np.log(2) / kappa if kappa > 0 else float("inf")

        meta = {
            "close": close,
            "ou_mu": round(mu, 4),
            "ou_kappa": round(kappa, 6),
            "ou_sigma": round(sigma, 6),
            "s_score": round(s_score, 4),
            "half_life_days": round(half_life, 1),
            "method": "ornstein_uhlenbeck",
        }

        # BUY: price well below equilibrium (s-score very negative)
        if s_score < -_S_SCORE_ENTRY:
            intensity = min(abs(s_score) / _S_SCORE_EXTREME, 1.0)
            strength = round(0.5 + 0.5 * intensity, 4)

            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"OU BUY: s-score={s_score:.2f} (below -{_S_SCORE_ENTRY}), "
                    f"equilibrium={mu:.2f}, half-life={half_life:.1f}d"
                ),
                meta=meta,
                target_price=mu,
                stop_loss=close * 0.97,  # 3% stop
            )

        # SELL: price well above equilibrium (s-score very positive)
        if s_score > _S_SCORE_ENTRY:
            intensity = min(s_score / _S_SCORE_EXTREME, 1.0)
            strength = round(0.5 + 0.5 * intensity, 4)

            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"OU SELL: s-score={s_score:.2f} (above {_S_SCORE_ENTRY}), "
                    f"equilibrium={mu:.2f}, half-life={half_life:.1f}d"
                ),
                meta=meta,
                target_price=mu,
                stop_loss=close * 1.03,
            )

        return None

    @staticmethod
    def _calibrate_ou(prices: np.ndarray) -> tuple[float, float, float, float] | None:
        """Calibrate Ornstein-Uhlenbeck parameters from price series.

        The OU process is: dX = kappa * (mu - X) * dt + sigma * dW

        We estimate via OLS on the discretised form:
            X(t+1) - X(t) = a + b * X(t) + epsilon

        Where: kappa = -b, mu = -a/b, sigma = std(epsilon) * sqrt(-2*b)

        Returns
        -------
        tuple or None
            (mu, kappa, sigma, s_score) or None if not mean-reverting.
        """
        if len(prices) < 20:
            return None

        # Use log prices for better statistical properties
        log_prices = np.log(prices)
        dx = np.diff(log_prices)
        x = log_prices[:-1]

        # OLS: dx = a + b * x
        x_mean = np.mean(x)
        dx_mean = np.mean(dx)

        ss_xx = np.sum((x - x_mean) ** 2)
        if ss_xx == 0:
            return None

        ss_xy = np.sum((x - x_mean) * (dx - dx_mean))
        b = ss_xy / ss_xx
        a = dx_mean - b * x_mean

        # Must be mean-reverting (b < 0)
        if b >= 0:
            return None

        kappa = -b  # mean-reversion speed
        mu_log = -a / b  # equilibrium level (log)
        mu = np.exp(mu_log)  # equilibrium level (price)

        # Residuals for sigma estimation
        residuals = dx - (a + b * x)
        sigma = float(np.std(residuals)) * np.sqrt(2 * kappa)

        if sigma <= 0 or kappa <= 0:
            return None

        # s-score: standardised distance from equilibrium
        # s = (X_current - mu) / sigma_eq
        # where sigma_eq = sigma / sqrt(2 * kappa) is the process std dev
        sigma_eq = sigma / np.sqrt(2 * kappa)
        if sigma_eq <= 0:
            return None

        s_score = (log_prices[-1] - mu_log) / sigma_eq

        return mu, kappa, sigma, s_score

    # ------------------------------------------------------------------ #
    # Fallback: Bollinger Bands + RSI
    # ------------------------------------------------------------------ #

    def _bollinger_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        """Legacy Bollinger Band + RSI mean-reversion signal."""
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

        # BUY: price at/below lower band + RSI oversold
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
                regime=regime,
                reasoning=(
                    f"BB BUY: price {close:.2f} at lower BB {bb_lower:.2f}, RSI={rsi:.1f}"
                ),
                meta={"close": close, "rsi": rsi, "bb_lower": bb_lower,
                       "bb_upper": bb_upper, "method": "bollinger"},
                target_price=target,
                stop_loss=bb_lower * 0.98,
            )

        # SELL: price at/above upper band + RSI overbought
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
                regime=regime,
                reasoning=(
                    f"BB SELL: price {close:.2f} at upper BB {bb_upper:.2f}, RSI={rsi:.1f}"
                ),
                meta={"close": close, "rsi": rsi, "bb_lower": bb_lower,
                       "bb_upper": bb_upper, "method": "bollinger"},
                target_price=target,
                stop_loss=bb_upper * 1.02,
            )

        return None
