"""Walk-forward optimization engine.

Implements anchored and rolling walk-forward analysis to evaluate strategy
robustness and prevent overfitting.

Research references
-------------------
- DeMiguel, Garlappi & Uppal 2009, Review of Financial Studies (~6,000
  citations) — "Optimal Versus Naive Diversification" — established that
  out-of-sample evaluation is essential; none of 14 optimization methods
  reliably beat 1/N in-sample. Walk-forward is the standard antidote.
- de Prado 2018, "Advances in Financial Machine Learning" — combinatorial
  purged cross-validation (CPCV) for backtest evaluation.
- Robert Pardo 2008, "The Evaluation and Optimization of Trading Strategies"
  (Wiley) — the definitive reference on walk-forward analysis methodology.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.backtest_broker import BacktestBroker, SimOrder
from app.backtesting.backtest_metrics import BacktestMetrics
from app.core.logging import get_logger

logger = get_logger("backtesting.walk_forward")


@dataclass
class WalkForwardFold:
    """Results for a single walk-forward fold."""

    fold_index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict = field(default_factory=dict)
    in_sample_sharpe: float = 0.0
    out_of_sample_sharpe: float = 0.0
    out_of_sample_return: float = 0.0
    out_of_sample_trades: int = 0
    equity_curve: list[float] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward analysis results."""

    folds: list[WalkForwardFold] = field(default_factory=list)
    combined_equity_curve: list[float] = field(default_factory=list)
    combined_metrics: dict = field(default_factory=dict)
    walk_forward_efficiency: float = 0.0  # OOS Sharpe / IS Sharpe


class WalkForwardOptimizer:
    """Walk-forward analysis engine.

    Splits data into sequential train/test windows, optimizes strategy
    parameters on the training set, evaluates on the test set, then
    rolls forward. This prevents look-ahead bias and measures true
    out-of-sample performance.

    Ref: Pardo 2008, "The Evaluation and Optimization of Trading Strategies"
    — the standard methodology. Walk-forward efficiency (OOS/IS Sharpe)
    > 0.5 indicates a robust strategy.
    """

    def __init__(
        self,
        n_folds: int = 5,
        train_ratio: float = 0.7,
        anchored: bool = False,
        broker: BacktestBroker | None = None,
    ) -> None:
        """
        Parameters
        ----------
        n_folds:
            Number of walk-forward folds.
        train_ratio:
            Fraction of each fold used for training (default 70%).
        anchored:
            If True, training window always starts at the beginning
            (expanding window). If False, uses a rolling window.
        broker:
            BacktestBroker instance for execution simulation.
        """
        self.n_folds = n_folds
        self.train_ratio = train_ratio
        self.anchored = anchored
        self.broker = broker or BacktestBroker()

    def run(
        self,
        bars: pd.DataFrame,
        param_grid: list[dict],
        strategy_factory: Callable[[dict], Callable[[pd.DataFrame, dict], SimOrder | None]],
        initial_capital: float = 1_000_000.0,
    ) -> WalkForwardResult:
        """Execute walk-forward optimization.

        Parameters
        ----------
        bars:
            OHLCV DataFrame (DatetimeIndex, columns: open/high/low/close/volume).
        param_grid:
            List of parameter dicts to evaluate in each training window.
        strategy_factory:
            ``strategy_factory(params) -> strategy_fn`` — creates a strategy
            callable from a parameter dict.
        initial_capital:
            Starting capital for each fold.

        Returns
        -------
        WalkForwardResult
        """
        n = len(bars)
        if n < 50 or not param_grid:
            logger.warning("walk_forward_insufficient_data", n_bars=n)
            return WalkForwardResult()

        fold_size = n // self.n_folds
        folds: list[WalkForwardFold] = []
        combined_eq: list[float] = []
        all_trades: list[dict] = []

        for fold_idx in range(self.n_folds):
            # Determine window boundaries
            if self.anchored:
                train_start = 0
            else:
                train_start = fold_idx * fold_size

            fold_end = min((fold_idx + 1) * fold_size + fold_size, n)
            split_point = train_start + int((fold_end - train_start) * self.train_ratio)

            if split_point >= fold_end or split_point - train_start < 20:
                continue

            train_bars = bars.iloc[train_start:split_point]
            test_bars = bars.iloc[split_point:fold_end]

            if len(test_bars) < 5:
                continue

            # Optimize on training set
            best_sharpe = -np.inf
            best_params: dict = param_grid[0]

            for params in param_grid:
                strategy_fn = strategy_factory(params)
                eq, trades = self._run_single(train_bars, strategy_fn, initial_capital)
                if len(eq) < 2:
                    continue
                returns = np.diff(eq) / eq[:-1]
                sharpe = BacktestMetrics.sharpe_ratio(returns)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params

            # Evaluate best params on test set
            strategy_fn = strategy_factory(best_params)
            test_eq, test_trades = self._run_single(test_bars, strategy_fn, initial_capital)

            oos_sharpe = 0.0
            oos_return = 0.0
            if len(test_eq) >= 2:
                test_returns = np.diff(test_eq) / test_eq[:-1]
                oos_sharpe = BacktestMetrics.sharpe_ratio(test_returns)
                oos_return = (test_eq[-1] - test_eq[0]) / test_eq[0] if test_eq[0] != 0 else 0.0
                combined_eq.extend(test_eq)
                all_trades.extend(test_trades)

            fold = WalkForwardFold(
                fold_index=fold_idx,
                train_start=str(train_bars.index[0]),
                train_end=str(train_bars.index[-1]),
                test_start=str(test_bars.index[0]),
                test_end=str(test_bars.index[-1]),
                best_params=best_params,
                in_sample_sharpe=round(best_sharpe, 4),
                out_of_sample_sharpe=round(oos_sharpe, 4),
                out_of_sample_return=round(oos_return, 6),
                out_of_sample_trades=len(test_trades),
                equity_curve=test_eq,
            )
            folds.append(fold)

            logger.info(
                "walk_forward_fold",
                fold=fold_idx,
                is_sharpe=round(best_sharpe, 4),
                oos_sharpe=round(oos_sharpe, 4),
                params=best_params,
            )

        # Aggregate
        combined_metrics = {}
        wf_efficiency = 0.0
        if combined_eq:
            combined_metrics = BacktestMetrics.compute_all(
                np.array(combined_eq), all_trades
            )
            avg_is = np.mean([f.in_sample_sharpe for f in folds]) if folds else 0
            avg_oos = np.mean([f.out_of_sample_sharpe for f in folds]) if folds else 0
            wf_efficiency = avg_oos / avg_is if avg_is != 0 else 0.0

        result = WalkForwardResult(
            folds=folds,
            combined_equity_curve=combined_eq,
            combined_metrics=combined_metrics,
            walk_forward_efficiency=round(wf_efficiency, 4),
        )

        logger.info(
            "walk_forward_complete",
            n_folds=len(folds),
            wf_efficiency=result.walk_forward_efficiency,
            combined_sharpe=combined_metrics.get("sharpe_ratio", 0),
        )

        return result

    # ------------------------------------------------------------------
    # Helper: run a single-asset backtest on a slice
    # ------------------------------------------------------------------

    def _run_single(
        self,
        bars: pd.DataFrame,
        strategy: Callable[[pd.DataFrame, dict], SimOrder | None],
        initial_capital: float,
    ) -> tuple[list[float], list[dict]]:
        """Run a simple backtest on a DataFrame slice. Returns (equity_curve, trades)."""
        cash = initial_capital
        position_qty = 0.0
        avg_entry = 0.0
        equity_curve: list[float] = []
        trades: list[dict] = []
        pending_order: SimOrder | None = None

        bar_list = []
        for ts, row in bars.iterrows():
            bar_list.append({
                "timestamp": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            })

        for i, bar in enumerate(bar_list):
            if pending_order is not None:
                fill = self.broker.execute(pending_order, bar)
                if fill is not None:
                    notional = fill.fill_price * abs(fill.quantity)
                    if fill.side == "BUY":
                        cost = notional + fill.commission
                        if cost <= cash:
                            total_qty = position_qty + fill.quantity
                            if total_qty != 0:
                                avg_entry = (
                                    (avg_entry * position_qty + fill.fill_price * fill.quantity)
                                    / total_qty
                                )
                            position_qty = total_qty
                            cash -= cost
                            trades.append({
                                "side": "BUY", "quantity": fill.quantity,
                                "price": fill.fill_price,
                                "commission": fill.commission,
                                "slippage": fill.slippage,
                                "timestamp": bar["timestamp"], "pnl": 0.0,
                            })
                    elif fill.side == "SELL":
                        proceeds = notional - fill.commission
                        pnl = (fill.fill_price - avg_entry) * abs(fill.quantity)
                        position_qty -= abs(fill.quantity)
                        if position_qty <= 0:
                            position_qty = 0.0
                            avg_entry = 0.0
                        cash += proceeds
                        trades.append({
                            "side": "SELL", "quantity": fill.quantity,
                            "price": fill.fill_price,
                            "commission": fill.commission,
                            "slippage": fill.slippage,
                            "timestamp": bar["timestamp"],
                            "pnl": round(pnl, 4),
                        })
                pending_order = None

            mark = bar["close"]
            portfolio_value = cash + position_qty * mark
            equity_curve.append(portfolio_value)

            history = bars.iloc[: i + 1]
            context = {
                "cash": cash, "position_qty": position_qty,
                "avg_entry": avg_entry, "portfolio_value": portfolio_value,
                "bar_index": i,
            }
            order = strategy(history, context)
            if order is not None:
                pending_order = order

        return equity_curve, trades
