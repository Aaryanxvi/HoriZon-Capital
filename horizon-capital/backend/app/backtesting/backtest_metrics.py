"""Performance metrics for backtesting.

Computes standard quant-finance metrics from an equity curve and trade list.
All ratios assume daily frequency unless stated otherwise.

Research references
-------------------
- Sharpe 1994, "The Sharpe Ratio", J. Portfolio Management — the standard
  risk-adjusted return metric.
- Sortino & Price 1994 — downside-only deviation for asymmetric return dists.
- Keating & Shadwick 2002, "A Universal Performance Measure", J. Performance
  Measurement — Omega ratio (gain/loss probability ratio at threshold).
- Bacon 2008, "Practical Portfolio Performance Measurement and Attribution"
  (Wiley) — information ratio, tail ratio, recovery factor definitions.
- Brinson, Hood & Beebower 1986, Financial Analysts Journal (~2,000 citations)
  — performance attribution framework.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger("backtesting.metrics")


class BacktestMetrics:
    """Suite of performance metrics for a completed backtest."""

    # ------------------------------------------------------------------
    # Core ratios (existing)
    # ------------------------------------------------------------------

    @staticmethod
    def sharpe_ratio(
        returns: pd.Series | np.ndarray,
        risk_free: float = 0.05,
    ) -> float:
        """Annualized Sharpe ratio (assumes daily returns).

        Ref: Sharpe 1994, "The Sharpe Ratio", J. Portfolio Management.
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
        """Annualized Sortino ratio (downside deviation only).

        Ref: Sortino & Price 1994 — penalizes only downside volatility.
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2:
            return 0.0
        daily_rf = (1 + risk_free) ** (1 / 252) - 1
        excess = ret - daily_rf
        downside = excess[excess < 0]
        if len(downside) < 2:
            return float("inf") if np.mean(excess) > 0 else 0.0
        ds_std = float(np.std(downside, ddof=1))
        if ds_std == 0:
            return float("inf") if np.mean(excess) > 0 else 0.0
        return float(np.mean(excess) / ds_std * np.sqrt(252))

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
        """Maximum drawdown as a positive fraction (0.10 = 10 %)."""
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
        """Compute Jensen's alpha and beta via OLS regression."""
        ret = np.asarray(returns, dtype=np.float64)
        bench = np.asarray(benchmark_returns, dtype=np.float64)

        n = min(len(ret), len(bench))
        ret = ret[:n]
        bench = bench[:n]

        mask = ~(np.isnan(ret) | np.isnan(bench))
        ret = ret[mask]
        bench = bench[mask]

        if len(ret) < 10:
            return {"alpha": 0.0, "beta": 0.0}

        cov_matrix = np.cov(ret, bench)
        beta = float(cov_matrix[0, 1] / cov_matrix[1, 1]) if cov_matrix[1, 1] != 0 else 0.0
        alpha_daily = float(np.mean(ret) - beta * np.mean(bench))
        alpha_annual = alpha_daily * 252

        return {"alpha": round(alpha_annual, 6), "beta": round(beta, 4)}

    # ------------------------------------------------------------------
    # Advanced ratios (Phase 3)
    # ------------------------------------------------------------------

    @staticmethod
    def information_ratio(
        returns: pd.Series | np.ndarray,
        benchmark_returns: pd.Series | np.ndarray,
    ) -> float:
        """Information ratio = annualized active return / tracking error.

        Ref: Bacon 2008, "Practical Portfolio Performance Measurement and
        Attribution" (Wiley) — measures manager skill vs benchmark.
        """
        ret = np.asarray(returns, dtype=np.float64)
        bench = np.asarray(benchmark_returns, dtype=np.float64)
        n = min(len(ret), len(bench))
        ret, bench = ret[:n], bench[:n]
        mask = ~(np.isnan(ret) | np.isnan(bench))
        ret, bench = ret[mask], bench[mask]

        if len(ret) < 10:
            return 0.0
        active = ret - bench
        te = float(np.std(active, ddof=1))
        if te == 0:
            return 0.0
        return float(np.mean(active) / te * np.sqrt(252))

    @staticmethod
    def omega_ratio(
        returns: pd.Series | np.ndarray,
        threshold: float = 0.0,
    ) -> float:
        """Omega ratio: probability-weighted gains / losses above threshold.

        Ref: Keating & Shadwick 2002, "A Universal Performance Measure",
        J. Performance Measurement — captures full return distribution,
        not just first two moments like Sharpe.
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2:
            return 0.0
        gains = ret[ret > threshold] - threshold
        losses = threshold - ret[ret <= threshold]
        sum_losses = float(np.sum(losses))
        if sum_losses == 0:
            return float("inf") if np.sum(gains) > 0 else 0.0
        return float(np.sum(gains) / sum_losses)

    @staticmethod
    def tail_ratio(
        returns: pd.Series | np.ndarray,
        percentile: float = 95.0,
    ) -> float:
        """Tail ratio = |right tail| / |left tail| at given percentile.

        Values > 1 mean larger gains than losses in the tails.
        Ref: Bacon 2008 — measures tail asymmetry of returns.
        """
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 20:
            return 0.0
        right = float(np.percentile(ret, percentile))
        left = float(np.percentile(ret, 100 - percentile))
        if left == 0:
            return float("inf") if right > 0 else 0.0
        return float(abs(right / left))

    @staticmethod
    def recovery_factor(
        equity_curve: pd.Series | np.ndarray,
    ) -> float:
        """Recovery factor = total return / max drawdown.

        Higher values mean faster recovery from drawdowns.
        """
        eq = np.asarray(equity_curve, dtype=np.float64)
        if len(eq) < 2 or eq[0] == 0:
            return 0.0
        total_ret = (eq[-1] - eq[0]) / eq[0]
        mdd = BacktestMetrics.max_drawdown(eq)
        if mdd == 0:
            return float("inf") if total_ret > 0 else 0.0
        return float(total_ret / mdd)

    @staticmethod
    def avg_win_loss(trades: list[dict]) -> dict:
        """Average winning trade, average losing trade, and their ratio.

        Returns {avg_win, avg_loss, win_loss_ratio}.
        """
        wins = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
        losses = [t["pnl"] for t in trades if t.get("pnl", 0) < 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        ratio = abs(avg_win / avg_loss) if avg_loss != 0 else (float("inf") if avg_win > 0 else 0.0)
        return {
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "win_loss_ratio": round(ratio, 4),
        }

    @staticmethod
    def max_consecutive_losses(trades: list[dict]) -> int:
        """Longest streak of consecutive losing trades."""
        if not trades:
            return 0
        max_streak = 0
        current = 0
        for t in trades:
            if t.get("pnl", 0) < 0:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def drawdown_duration(equity_curve: pd.Series | np.ndarray) -> dict:
        """Max drawdown duration (bars) and average drawdown duration.

        Returns {max_dd_duration, avg_dd_duration}.
        """
        eq = np.asarray(equity_curve, dtype=np.float64)
        if len(eq) < 2:
            return {"max_dd_duration": 0, "avg_dd_duration": 0.0}

        running_max = np.maximum.accumulate(eq)
        in_dd = eq < running_max

        durations: list[int] = []
        current = 0
        for is_dd in in_dd:
            if is_dd:
                current += 1
            elif current > 0:
                durations.append(current)
                current = 0
        if current > 0:
            durations.append(current)

        if not durations:
            return {"max_dd_duration": 0, "avg_dd_duration": 0.0}
        return {
            "max_dd_duration": max(durations),
            "avg_dd_duration": round(float(np.mean(durations)), 1),
        }

    @staticmethod
    def volatility_annual(returns: pd.Series | np.ndarray) -> float:
        """Annualized volatility from daily returns."""
        ret = np.asarray(returns, dtype=np.float64)
        ret = ret[~np.isnan(ret)]
        if len(ret) < 2:
            return 0.0
        return float(np.std(ret, ddof=1) * np.sqrt(252))

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
            Daily benchmark returns for alpha/beta/IR calculation.
        """
        eq = np.asarray(equity_curve, dtype=np.float64)
        empty = {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": len(trades),
            "alpha": 0.0,
            "beta": 0.0,
            "information_ratio": 0.0,
            "omega_ratio": 0.0,
            "tail_ratio": 0.0,
            "recovery_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "win_loss_ratio": 0.0,
            "max_consecutive_losses": 0,
            "max_dd_duration": 0,
            "avg_dd_duration": 0.0,
        }
        if len(eq) < 2:
            return empty

        # Daily returns from equity curve
        returns = np.diff(eq) / eq[:-1]
        returns = returns[~np.isnan(returns)]

        mdd = cls.max_drawdown(eq)
        total_ret = (eq[-1] - eq[0]) / eq[0] if eq[0] != 0 else 0.0
        n_days = len(eq)
        annual_ret = (1 + total_ret) ** (252 / max(n_days, 1)) - 1

        ab = {"alpha": 0.0, "beta": 0.0}
        ir = 0.0
        if benchmark_returns is not None:
            ab = cls.alpha_beta(returns, benchmark_returns)
            ir = cls.information_ratio(returns, benchmark_returns)

        wl = cls.avg_win_loss(trades)
        dd_dur = cls.drawdown_duration(eq)

        metrics = {
            "sharpe_ratio": round(cls.sharpe_ratio(returns), 4),
            "sortino_ratio": round(cls.sortino_ratio(returns), 4),
            "calmar_ratio": round(cls.calmar_ratio(returns, mdd), 4),
            "max_drawdown": round(mdd, 6),
            "total_return": round(total_ret, 6),
            "annualized_return": round(annual_ret, 6),
            "annualized_volatility": round(cls.volatility_annual(returns), 6),
            "win_rate": round(cls.win_rate(trades), 4),
            "profit_factor": round(cls.profit_factor(trades), 4),
            "total_trades": len(trades),
            "alpha": ab["alpha"],
            "beta": ab["beta"],
            "information_ratio": round(ir, 4),
            "omega_ratio": round(cls.omega_ratio(returns), 4),
            "tail_ratio": round(cls.tail_ratio(returns), 4),
            "recovery_factor": round(cls.recovery_factor(eq), 4),
            "avg_win": wl["avg_win"],
            "avg_loss": wl["avg_loss"],
            "win_loss_ratio": wl["win_loss_ratio"],
            "max_consecutive_losses": cls.max_consecutive_losses(trades),
            "max_dd_duration": dd_dur["max_dd_duration"],
            "avg_dd_duration": dd_dur["avg_dd_duration"],
        }

        logger.info("backtest_metrics_computed", **metrics)
        return metrics
