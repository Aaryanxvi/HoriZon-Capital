"""Performance metrics for backtesting.

Computes standard quant-finance metrics from an equity curve and trade list.
All ratios assume daily frequency unless stated otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger("backtesting.metrics")


class BacktestMetrics:
    """Suite of performance metrics for a completed backtest."""

    # ------------------------------------------------------------------
    # Individual metrics
    # ------------------------------------------------------------------

    @staticmethod
    def sharpe_ratio(
        returns: pd.Series | np.ndarray,
        risk_free: float = 0.05,
    ) -> float:
        """Annualized Sharpe ratio (assumes daily returns).

        Parameters
        ----------
        returns : array-like
            Daily simple or log returns.
        risk_free : float
            Annual risk-free rate (default 5 %).
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2 or np.std(ret, ddof=1) == 0:
            return 0.0
        daily_rf = (1 + risk_free) ** (1 / 252) - 1
        excess = ret - daily_rf
        return float(np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(252))

    @staticmethod
    def sortino_ratio(
        returns: pd.Series | np.ndarray,
        risk_free: float = 0.05,
    ) -> float:
        """Annualized Sortino ratio (downside deviation only)."""
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2:
            return 0.0
        daily_rf = (1 + risk_free) ** (1 / 252) - 1
        excess = ret - daily_rf
        downside = excess[excess < 0]
        if len(downside) == 0 or np.std(downside, ddof=1) == 0:
            return float("inf") if np.mean(excess) > 0 else 0.0
        return float(np.mean(excess) / np.std(downside, ddof=1) * np.sqrt(252))

    @staticmethod
    def calmar_ratio(
        returns: pd.Series | np.ndarray,
        max_dd: float,
    ) -> float:
        """Calmar ratio = annualized return / max drawdown."""
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2 or max_dd == 0:
            return 0.0
        annual_ret = float(np.mean(ret) * 252)
        return annual_ret / abs(max_dd)

    @staticmethod
    def max_drawdown(equity_curve: pd.Series | np.ndarray) -> float:
        """Maximum drawdown as a positive fraction (0.10 = 10 %).

        Parameters
        ----------
        equity_curve : array-like
            Cumulative portfolio value series.
        """
        eq = np.asarray(equity_curve, dtype=np.float64)
        if len(eq) < 2:
            return 0.0
        running_max = np.maximum.accumulate(eq)
        drawdowns = (eq - running_max) / np.where(running_max == 0, 1, running_max)
        return float(abs(np.min(drawdowns)))

    @staticmethod
    def win_rate(trades: list[dict]) -> float:
        """Fraction of trades with positive PnL."""
        if not trades:
            return 0.0
        winners = sum(1 for t in trades if t.get("pnl", 0) > 0)
        return winners / len(trades)

    @staticmethod
    def profit_factor(trades: list[dict]) -> float:
        """Gross profit / gross loss.  Returns inf if no losses."""
        gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def alpha_beta(
        returns: pd.Series | np.ndarray,
        benchmark_returns: pd.Series | np.ndarray,
    ) -> dict:
        """Compute Jensen's alpha and beta via OLS regression.

        Returns
        -------
        dict
            ``{alpha, beta}`` annualized.
        """
        ret = np.asarray(returns, dtype=np.float64)
        bench = np.asarray(benchmark_returns, dtype=np.float64)

        # Align lengths
        n = min(len(ret), len(bench))
        ret = ret[:n]
        bench = bench[:n]

        # Remove NaNs pairwise
        mask = ~(np.isnan(ret) | np.isnan(bench))
        ret = ret[mask]
        bench = bench[mask]

        if len(ret) < 10:
            return {"alpha": 0.0, "beta": 0.0}

        # OLS: ret = alpha + beta * bench + epsilon
        cov_matrix = np.cov(ret, bench)
        beta = float(cov_matrix[0, 1] / cov_matrix[1, 1]) if cov_matrix[1, 1] != 0 else 0.0
        alpha_daily = float(np.mean(ret) - beta * np.mean(bench))
        alpha_annual = alpha_daily * 252

        return {"alpha": round(alpha_annual, 6), "beta": round(beta, 4)}

    # ------------------------------------------------------------------
    # Master computation
    # ------------------------------------------------------------------

    @classmethod
    def compute_all(
        cls,
        equity_curve: pd.Series | np.ndarray,
        trades: list[dict],
        benchmark_returns: np.ndarray | pd.Series | None = None,
    ) -> dict:
        """Compute all performance metrics.

        Parameters
        ----------
        equity_curve : array-like
            Daily portfolio value series.
        trades : list[dict]
            Each dict must contain at least ``pnl`` (float).
        benchmark_returns : array-like, optional
            Daily benchmark returns for alpha/beta calculation.

        Returns
        -------
        dict
            Full metrics dictionary.
        """
        eq = np.asarray(equity_curve, dtype=np.float64)
        if len(eq) < 2:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "annualized_return": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_trades": len(trades),
                "alpha": 0.0,
                "beta": 0.0,
            }

        # Daily returns from equity curve
        returns = np.diff(eq) / eq[:-1]
        returns = returns[~np.isnan(returns)]

        mdd = cls.max_drawdown(eq)
        total_ret = (eq[-1] - eq[0]) / eq[0] if eq[0] != 0 else 0.0
        n_days = len(eq)
        annual_ret = (1 + total_ret) ** (252 / max(n_days, 1)) - 1

        ab = {"alpha": 0.0, "beta": 0.0}
        if benchmark_returns is not None:
            ab = cls.alpha_beta(returns, benchmark_returns)

        metrics = {
            "sharpe_ratio": round(cls.sharpe_ratio(returns), 4),
            "sortino_ratio": round(cls.sortino_ratio(returns), 4),
            "calmar_ratio": round(cls.calmar_ratio(returns, mdd), 4),
            "max_drawdown": round(mdd, 6),
            "total_return": round(total_ret, 6),
            "annualized_return": round(annual_ret, 6),
            "win_rate": round(cls.win_rate(trades), 4),
            "profit_factor": round(cls.profit_factor(trades), 4),
            "total_trades": len(trades),
            "alpha": ab["alpha"],
            "beta": ab["beta"],
        }

        logger.info("backtest_metrics_computed", **metrics)
        return metrics
