"""Backtest engine: replays historical OHLCV data through a strategy pipeline.

Usage
-----
    engine = BacktestEngine(initial_capital=1_000_000)
    result = await engine.run("RELIANCE.NSE", start, end, strategy_fn)

The engine fetches historical bars from the database, iterates bar-by-bar,
feeds each bar to the strategy callable, and fills any resulting orders via
``BacktestBroker``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.backtesting.backtest_broker import BacktestBroker, SimFill, SimOrder
from app.backtesting.backtest_metrics import BacktestMetrics
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("backtesting.engine")


@dataclass
class BacktestResult:
    """Container for a completed backtest run."""
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    positions: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    bars_processed: int = 0


class BacktestEngine:
    """Event-driven backtest engine.

    Replays historical bars and feeds them to a strategy function.  The strategy
    returns an optional ``SimOrder`` (or ``None``) per bar.  Orders are filled
    on the *next* bar via ``BacktestBroker``.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        broker: BacktestBroker | None = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.broker = broker or BacktestBroker()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_bars(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str,
    ) -> pd.DataFrame:
        """Load OHLCV bars from the database."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT timestamp, open, high, low, close, volume
                    FROM ohlcv
                    WHERE symbol = :symbol
                      AND timeframe = :tf
                      AND timestamp >= :start
                      AND timestamp <= :end
                    ORDER BY timestamp ASC
                    """
                ),
                {
                    "symbol": symbol,
                    "tf": timeframe,
                    "start": start_date,
                    "end": end_date,
                },
            )
            rows = result.fetchall()

        if not rows:
            logger.warning("backtest_no_data", symbol=symbol, start=str(start_date))
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df.set_index("timestamp", inplace=True)
        return df

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        strategy: Callable[[pd.DataFrame, dict], SimOrder | None],
        timeframe: str = "1d",
    ) -> BacktestResult:
        """Execute a backtest.

        Parameters
        ----------
        symbol : str
            Instrument symbol (e.g. ``"RELIANCE.NSE"``).
        start_date / end_date : datetime
            Date range for the backtest.
        strategy : callable
            ``strategy(history_df, context) -> SimOrder | None``
            Called once per bar with all bars up to the current one and a
            context dict containing position and account info.
        timeframe : str
            OHLCV timeframe (default ``"1d"``).

        Returns
        -------
        BacktestResult
            Full result with equity curve, trades, and performance metrics.
        """
        bars_df = await self._load_bars(symbol, start_date, end_date, timeframe)
        if bars_df.empty:
            return BacktestResult(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
            )

        # State tracking
        cash = self.initial_capital
        position_qty: float = 0.0
        avg_entry: float = 0.0
        equity_curve: list[float] = []
        trades: list[dict] = []
        pending_order: SimOrder | None = None

        bar_dicts = []
        for ts, row in bars_df.iterrows():
            bar_dicts.append({
                "timestamp": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })

        for i, bar in enumerate(bar_dicts):
            # 1. Fill any pending order at this bar's open
            if pending_order is not None:
                fill: SimFill | None = self.broker.execute(pending_order, bar)
                if fill is not None:
                    notional = fill.fill_price * abs(fill.quantity)
                    if fill.side == "BUY":
                        cost = notional + fill.commission
                        if cost <= cash:
                            # Update position
                            total_qty = position_qty + fill.quantity
                            if total_qty != 0:
                                avg_entry = (
                                    (avg_entry * position_qty + fill.fill_price * fill.quantity)
                                    / total_qty
                                )
                            position_qty = total_qty
                            cash -= cost
                            trades.append({
                                "side": "BUY",
                                "quantity": fill.quantity,
                                "price": fill.fill_price,
                                "commission": fill.commission,
                                "slippage": fill.slippage,
                                "timestamp": bar["timestamp"],
                                "pnl": 0.0,  # realized PnL computed on close
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
                            "side": "SELL",
                            "quantity": fill.quantity,
                            "price": fill.fill_price,
                            "commission": fill.commission,
                            "slippage": fill.slippage,
                            "timestamp": bar["timestamp"],
                            "pnl": round(pnl, 4),
                        })
                pending_order = None

            # 2. Mark-to-market equity
            mark = bar["close"]
            portfolio_value = cash + position_qty * mark
            equity_curve.append(portfolio_value)

            # 3. Ask the strategy for a signal
            history = bars_df.iloc[: i + 1]
            context: dict[str, Any] = {
                "cash": cash,
                "position_qty": position_qty,
                "avg_entry": avg_entry,
                "portfolio_value": portfolio_value,
                "bar_index": i,
            }
            order = strategy(history, context)
            if order is not None:
                order.symbol = symbol
                pending_order = order

        final_capital = equity_curve[-1] if equity_curve else self.initial_capital

        # Compute metrics
        metrics = BacktestMetrics.compute_all(
            equity_curve=np.array(equity_curve),
            trades=trades,
        )

        result = BacktestResult(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 2),
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            bars_processed=len(bar_dicts),
        )

        logger.info(
            "backtest_complete",
            symbol=symbol,
            bars=result.bars_processed,
            total_return=metrics.get("total_return", 0),
            sharpe=metrics.get("sharpe_ratio", 0),
            trades=len(trades),
        )

        return result
