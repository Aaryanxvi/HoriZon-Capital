"""Multi-asset portfolio backtest engine.

Extends the single-asset BacktestEngine to run a portfolio of symbols
simultaneously, tracking cross-asset positions, portfolio-level equity
curves, and correlation-aware metrics.

Research references
-------------------
- de Prado 2018, "Advances in Financial Machine Learning" (Cambridge Univ.
  Press) — event-driven backtesting best practices, triple barrier method,
  combinatorial purged cross-validation.
- DeMiguel, Garlappi & Uppal 2009, Review of Financial Studies (~6,000
  citations) — out-of-sample evaluation methodology for portfolio strategies.
- Almgren & Chriss 2000, J. Risk (~1,610 citations) — slippage model used
  by the BacktestBroker for realistic execution simulation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.backtest_broker import BacktestBroker, SimFill, SimOrder
from app.backtesting.backtest_metrics import BacktestMetrics
from app.core.logging import get_logger

logger = get_logger("backtesting.multi_asset")


@dataclass
class PortfolioBacktestResult:
    """Container for a multi-asset backtest run."""

    symbols: list[str]
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    per_symbol_trades: dict[str, list[dict]] = field(default_factory=dict)
    per_symbol_pnl: dict[str, float] = field(default_factory=dict)
    positions_history: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    bars_processed: int = 0


class MultiAssetEngine:
    """Event-driven backtest engine for multi-asset portfolios.

    Replays aligned OHLCV bars across multiple symbols. On each bar the
    strategy callback receives a dict of per-symbol history DataFrames
    plus portfolio context, and returns a list of SimOrders.

    Ref: de Prado 2018 — event-driven architecture ensures no look-ahead bias.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        broker: BacktestBroker | None = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.broker = broker or BacktestBroker()

    # ------------------------------------------------------------------
    # Data loading — from pre-built DataFrames (no DB dependency)
    # ------------------------------------------------------------------

    @staticmethod
    def align_bars(
        bars_by_symbol: dict[str, pd.DataFrame],
    ) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
        """Align bars across symbols to a common date index.

        Missing bars for a symbol on a given date are forward-filled.
        Returns the common index and aligned DataFrames.
        """
        if not bars_by_symbol:
            return pd.DatetimeIndex([]), {}

        # Build union index
        all_idx = pd.DatetimeIndex([])
        for df in bars_by_symbol.values():
            all_idx = all_idx.union(df.index)
        all_idx = all_idx.sort_values()

        aligned: dict[str, pd.DataFrame] = {}
        for sym, df in bars_by_symbol.items():
            df_reindexed = df.reindex(all_idx, method="ffill")
            aligned[sym] = df_reindexed

        return all_idx, aligned

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run_sync(
        self,
        bars_by_symbol: dict[str, pd.DataFrame],
        strategy: Callable[
            [dict[str, pd.DataFrame], dict[str, Any]], list[SimOrder]
        ],
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        benchmark_returns: np.ndarray | None = None,
    ) -> PortfolioBacktestResult:
        """Execute a multi-asset backtest (synchronous).

        Parameters
        ----------
        bars_by_symbol:
            Dict mapping symbol -> OHLCV DataFrame (index=DatetimeIndex,
            columns=[open, high, low, close, volume]).
        strategy:
            ``strategy(history_by_sym, context) -> list[SimOrder]``
            Called once per bar with all history up to current bar.
        start_date / end_date:
            Optional date filters.
        benchmark_returns:
            Daily benchmark returns for alpha/beta/IR calculation.
        """
        common_idx, aligned = self.align_bars(bars_by_symbol)
        symbols = list(aligned.keys())

        if len(common_idx) == 0:
            return PortfolioBacktestResult(
                symbols=symbols,
                start_date=start_date or datetime.now(UTC),
                end_date=end_date or datetime.now(UTC),
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
            )

        # Filter date range
        if start_date:
            common_idx = common_idx[common_idx >= pd.Timestamp(start_date)]
        if end_date:
            common_idx = common_idx[common_idx <= pd.Timestamp(end_date)]

        # State tracking
        cash = self.initial_capital
        positions: dict[str, float] = {s: 0.0 for s in symbols}  # qty
        avg_entries: dict[str, float] = {s: 0.0 for s in symbols}
        equity_curve: list[float] = []
        all_trades: list[dict] = []
        per_sym_trades: dict[str, list[dict]] = {s: [] for s in symbols}
        pending_orders: list[SimOrder] = []

        for i, ts in enumerate(common_idx):
            # Build current bars dict per symbol
            current_bars: dict[str, dict] = {}
            for sym in symbols:
                row = aligned[sym].loc[ts]
                if pd.isna(row.get("close")):
                    continue
                current_bars[sym] = {
                    "timestamp": ts,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0)),
                }

            # 1. Fill pending orders
            for order in pending_orders:
                sym = order.symbol
                if sym not in current_bars:
                    continue
                bar = current_bars[sym]
                fill: SimFill | None = self.broker.execute(order, bar)
                if fill is None:
                    continue

                notional = fill.fill_price * abs(fill.quantity)
                if fill.side == "BUY":
                    cost = notional + fill.commission
                    if cost <= cash:
                        total_qty = positions[sym] + fill.quantity
                        if total_qty != 0:
                            avg_entries[sym] = (
                                (avg_entries[sym] * positions[sym]
                                 + fill.fill_price * fill.quantity) / total_qty
                            )
                        positions[sym] = total_qty
                        cash -= cost
                        trade_rec = {
                            "symbol": sym, "side": "BUY",
                            "quantity": fill.quantity,
                            "price": fill.fill_price,
                            "commission": fill.commission,
                            "slippage": fill.slippage,
                            "timestamp": ts, "pnl": 0.0,
                        }
                        all_trades.append(trade_rec)
                        per_sym_trades[sym].append(trade_rec)

                elif fill.side == "SELL":
                    proceeds = notional - fill.commission
                    pnl = (fill.fill_price - avg_entries[sym]) * abs(fill.quantity)
                    positions[sym] -= abs(fill.quantity)
                    if positions[sym] <= 0:
                        positions[sym] = 0.0
                        avg_entries[sym] = 0.0
                    cash += proceeds
                    trade_rec = {
                        "symbol": sym, "side": "SELL",
                        "quantity": fill.quantity,
                        "price": fill.fill_price,
                        "commission": fill.commission,
                        "slippage": fill.slippage,
                        "timestamp": ts, "pnl": round(pnl, 4),
                    }
                    all_trades.append(trade_rec)
                    per_sym_trades[sym].append(trade_rec)

            pending_orders = []

            # 2. Mark-to-market
            port_value = cash
            for sym in symbols:
                if sym in current_bars:
                    port_value += positions[sym] * current_bars[sym]["close"]
            equity_curve.append(port_value)

            # 3. Call strategy
            history_by_sym = {
                sym: aligned[sym].iloc[: i + 1] for sym in symbols
            }
            context: dict[str, Any] = {
                "cash": cash,
                "positions": dict(positions),
                "avg_entries": dict(avg_entries),
                "portfolio_value": port_value,
                "bar_index": i,
                "timestamp": ts,
            }
            orders = strategy(history_by_sym, context)
            if orders:
                pending_orders = orders

        final_capital = equity_curve[-1] if equity_curve else self.initial_capital

        # Per-symbol PnL
        per_sym_pnl = {}
        for sym in symbols:
            per_sym_pnl[sym] = round(
                sum(t.get("pnl", 0) for t in per_sym_trades[sym]), 4
            )

        # Compute metrics
        metrics = BacktestMetrics.compute_all(
            equity_curve=np.array(equity_curve),
            trades=all_trades,
            benchmark_returns=benchmark_returns,
        )

        result = PortfolioBacktestResult(
            symbols=symbols,
            start_date=start_date or common_idx[0].to_pydatetime(),
            end_date=end_date or common_idx[-1].to_pydatetime(),
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 2),
            equity_curve=equity_curve,
            trades=all_trades,
            per_symbol_trades=per_sym_trades,
            per_symbol_pnl=per_sym_pnl,
            metrics=metrics,
            bars_processed=len(common_idx),
        )

        logger.info(
            "multi_asset_backtest_complete",
            symbols=symbols,
            bars=result.bars_processed,
            total_return=metrics.get("total_return", 0),
            sharpe=metrics.get("sharpe_ratio", 0),
            trades=len(all_trades),
        )

        return result
