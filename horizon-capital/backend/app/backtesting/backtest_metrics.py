"""Performance metrics for backtesting."""

from __future__ import annotations

import numpy as np

from app.core.logging import get_logger

logger = get_logger("backtesting.metrics")


class BacktestMetrics:
    """Basic performance metrics for a completed backtest."""

    @staticmethod
    def sharpe_ratio(
        returns: list[float] | np.ndarray,
        risk_free: float = 0.05,
    ) -> float:
        """Annualized Sharpe ratio (assumes daily returns)."""
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2 or np.std(ret, ddof=1) == 0:
            return 0.0
        daily_rf = (1 + risk_free) ** (1 / 252) - 1
        excess = ret - daily_rf
        return float(np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(252))

    @staticmethod
    def max_drawdown(equity_curve: list[float] | np.ndarray) -> float:
        """Maximum drawdown as a positive fraction (0.10 = 10%)."""
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
    def total_return(equity_curve: list[float] | np.ndarray) -> float:
        """Total return over the period as a fraction."""
        eq = np.asarray(equity_curve, dtype=np.float64)
        if len(eq) < 2 or eq[0] == 0:
            return 0.0
        return float((eq[-1] - eq[0]) / eq[0])

    @classmethod
    def compute_all(
        cls,
        equity_curve: list[float] | np.ndarray,
        trades: list[dict],
    ) -> dict:
        """Compute all performance metrics."""
        eq = np.asarray(equity_curve, dtype=np.float64)
        empty = {
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "win_rate": 0.0,
            "total_trades": len(trades),
        }
        if len(eq) < 2:
            return empty

        returns = np.diff(eq) / eq[:-1]
        returns = returns[~np.isnan(returns)]

        metrics = {
            "sharpe_ratio": round(cls.sharpe_ratio(returns), 4),
            "max_drawdown": round(cls.max_drawdown(eq), 6),
            "total_return": round(cls.total_return(eq), 6),
            "win_rate": round(cls.win_rate(trades), 4),
            "total_trades": len(trades),
        }

        logger.info("backtest_metrics_computed", **metrics)
        return metrics
