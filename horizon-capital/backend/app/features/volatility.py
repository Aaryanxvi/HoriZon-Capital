"""Volatility feature engineering: realized vol, GARCH(1,1), VIX proxy.

Dependencies: pandas, numpy, arch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from arch import arch_model

from app.core.logging import get_logger

logger = get_logger("features.volatility")


class VolatilityFeatures:
    """Volatility-specific features used by the risk and regime agents."""

    # ------------------------------------------------------------------
    # Realized volatility
    # ------------------------------------------------------------------

    @staticmethod
    def realized_vol(returns: pd.Series, window: int = 20) -> pd.Series:
        """Annualized rolling realized volatility.

        Parameters
        ----------
        returns : pd.Series
            Log or simple returns series (daily frequency assumed).
        window : int
            Rolling window in trading days.

        Returns
        -------
        pd.Series
            Annualized realized volatility (sqrt(252) scaling).
        """
        rolling_std = returns.rolling(window=window, min_periods=max(1, window // 2)).std()
        annualized = rolling_std * np.sqrt(252)
        return annualized.rename(f"realized_vol_{window}d")

    # ------------------------------------------------------------------
    # GARCH(1,1) forecast
    # ------------------------------------------------------------------

    @staticmethod
    def garch_forecast(returns: pd.Series) -> dict:
        """Fit a GARCH(1,1) model and produce a 1-day ahead volatility forecast.

        Parameters
        ----------
        returns : pd.Series
            Daily returns series (at least 100 observations recommended).

        Returns
        -------
        dict
            ``{omega, alpha, beta, forecast_1d}`` where ``forecast_1d`` is the
            annualized 1-day ahead volatility forecast.
        """
        # Scale returns to percentage for numerical stability in arch
        scaled = returns.dropna() * 100.0

        if len(scaled) < 30:
            logger.warning("garch_insufficient_data", n_obs=len(scaled))
            return {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "forecast_1d": 0.0}

        model = arch_model(
            scaled,
            vol="Garch",
            p=1,
            q=1,
            mean="Constant",
            dist="Normal",
            rescale=False,
        )
        try:
            result = model.fit(disp="off", show_warning=False)
        except Exception as exc:
            logger.error("garch_fit_failed", error=str(exc))
            return {"omega": 0.0, "alpha": 0.0, "beta": 0.0, "forecast_1d": 0.0}

        params = result.params
        omega = float(params.get("omega", 0.0))
        alpha = float(params.get("alpha[1]", 0.0))
        beta = float(params.get("beta[1]", 0.0))

        # 1-day ahead forecast (variance, in percentage^2)
        forecast = result.forecast(horizon=1)
        variance_1d = float(forecast.variance.values[-1, 0])
        # Convert back from pct^2 to decimal annualized vol
        forecast_1d = np.sqrt(variance_1d) / 100.0 * np.sqrt(252)

        logger.info(
            "garch_fitted",
            omega=round(omega, 6),
            alpha=round(alpha, 4),
            beta=round(beta, 4),
            forecast_1d_vol=round(forecast_1d, 4),
        )

        return {
            "omega": omega,
            "alpha": alpha,
            "beta": beta,
            "forecast_1d": forecast_1d,
        }

    # ------------------------------------------------------------------
    # VIX proxy (30-day annualized realized volatility)
    # ------------------------------------------------------------------

    @staticmethod
    def vix_proxy(df: pd.DataFrame) -> pd.Series:
        """Compute a VIX-like proxy from OHLCV data.

        Uses 30-day annualized realized volatility of log-returns as an
        approximation of the VIX (implied vol is not available for all
        markets, e.g. NSE).

        Parameters
        ----------
        df : pd.DataFrame
            Must contain a ``close`` column.

        Returns
        -------
        pd.Series
            Annualized 30-day realized vol, comparable to VIX levels.
        """
        log_returns = np.log(df["close"] / df["close"].shift(1))
        rolling_std = log_returns.rolling(window=30, min_periods=15).std()
        vix_proxy_series = rolling_std * np.sqrt(252) * 100  # express as percentage
        return vix_proxy_series.rename("vix_proxy")
