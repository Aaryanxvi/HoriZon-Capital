"""Performance analytics service.

Computes portfolio-level metrics, PnL curves, and per-strategy attribution.
Used by the dashboard API and the CIO overview.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import text

from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("services.performance")

# Mapping from period labels to calendar-day look-backs
_PERIOD_DAYS: dict[str, int | None] = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "YTD": None,   # computed dynamically
    "ALL": None,    # no filter
}


class PerformanceService:
    """Compute and serve portfolio performance analytics."""

    # ------------------------------------------------------------------
    # Snapshot: key ratios for a given period
    # ------------------------------------------------------------------

    @staticmethod
    async def compute_snapshot(period: str = "30d") -> dict:
        """Compute performance ratios for the requested period.

        Returns
        -------
        dict
            {sharpe, sortino, calmar, win_rate, profit_factor, alpha_india,
             alpha_us, max_drawdown, total_return, annualized_return, total_trades}
        """
        now = datetime.now(UTC)

        # Resolve start date
        if period == "YTD":
            start = datetime(now.year, 1, 1, tzinfo=UTC)
        elif period == "ALL":
            start = datetime(2000, 1, 1, tzinfo=UTC)
        else:
            days = _PERIOD_DAYS.get(period, 30)
            start = now - timedelta(days=days)

        async with _get_session_factory()() as session:
            # Equity curve from portfolio snapshots
            eq_rows = await session.execute(
                text(
                    """
                    SELECT created_at, total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :start
                    ORDER BY created_at ASC
                    """
                ),
                {"start": start},
            )
            equity_data = eq_rows.fetchall()

            # Trades in the period
            trade_rows = await session.execute(
                text(
                    """
                    SELECT f.fill_price, f.filled_qty, o.side,
                           f.commission, f.slippage
                    FROM fills f
                    JOIN orders o ON o.id = f.order_id
                    WHERE f.filled_at >= :start
                    ORDER BY f.filled_at
                    """
                ),
                {"start": start},
            )
            fills = trade_rows.fetchall()

        if len(equity_data) < 2:
            return {
                "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
                "win_rate": 0.0, "profit_factor": 0.0,
                "alpha_india": 0.0, "alpha_us": 0.0,
                "max_drawdown": 0.0, "total_return": 0.0,
                "annualized_return": 0.0, "total_trades": 0,
            }

        eq = np.array([float(r[1]) for r in equity_data])
        returns = np.diff(eq) / eq[:-1]
        returns = returns[~np.isnan(returns)]

        # Max drawdown
        running_max = np.maximum.accumulate(eq)
        dd = (eq - running_max) / np.where(running_max == 0, 1, running_max)
        max_dd = float(abs(np.min(dd)))

        n_days = max(len(eq), 1)
        total_ret = (eq[-1] - eq[0]) / eq[0] if eq[0] != 0 else 0.0
        annual_ret = (1 + total_ret) ** (252 / n_days) - 1

        # Sharpe
        daily_rf = (1.05) ** (1 / 252) - 1
        excess = returns - daily_rf
        std_excess = float(np.std(excess, ddof=1)) if len(excess) >= 2 else 0.0
        sharpe = float(np.mean(excess) / std_excess * np.sqrt(252)) if std_excess > 0 else 0.0

        # Sortino
        downside = excess[excess < 0]
        ds_std = float(np.std(downside, ddof=1)) if len(downside) >= 2 else 0.0
        sortino = (
            float(np.mean(excess) / ds_std * np.sqrt(252))
            if ds_std > 0
            else 0.0
        )

        # Calmar
        calmar = annual_ret / abs(max_dd) if max_dd > 0 else 0.0

        # Win rate / profit factor from fills (pair buys and sells naively)
        trade_pnls: list[float] = []
        buy_cost = 0.0
        buy_qty = 0.0
        for row in fills:
            price, qty, side = float(row[0]), float(row[1]), row[2]
            if side == "BUY":
                buy_cost += price * qty
                buy_qty += qty
            elif side == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                pnl = (price - avg_entry) * qty
                trade_pnls.append(pnl)
                buy_qty -= qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0

        total_trades = len(trade_pnls)
        win_rate = sum(1 for p in trade_pnls if p > 0) / total_trades if total_trades > 0 else 0.0
        gross_profit = sum(p for p in trade_pnls if p > 0)
        gross_loss = abs(sum(p for p in trade_pnls if p < 0))
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0
            else (float("inf") if gross_profit > 0 else 0.0)
        )

        # Read alpha from KV store (performance_worker computes this)
        try:
            from app.core.kv_store import get_kv_store
            kv = get_kv_store()
            alpha_india_str = await kv.get(
                "horizon:performance:alpha_india"
            )
            alpha_us_str = await kv.get(
                "horizon:performance:alpha_us"
            )
            alpha_india = (
                float(alpha_india_str) if alpha_india_str else 0.0
            )
            alpha_us = (
                float(alpha_us_str) if alpha_us_str else 0.0
            )
        except Exception:
            alpha_india = 0.0
            alpha_us = 0.0

        snapshot = {
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "alpha_india": round(alpha_india, 4),
            "alpha_us": round(alpha_us, 4),
            "max_drawdown": round(max_dd, 6),
            "total_return": round(total_ret, 6),
            "annualized_return": round(annual_ret, 6),
            "total_trades": total_trades,
        }

        logger.info("performance_snapshot", period=period, **snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # PnL curve: time series of portfolio values
    # ------------------------------------------------------------------

    @staticmethod
    async def get_pnl_curve(period: str = "30d") -> list[dict]:
        """Return the equity curve as a list of ``{timestamp, value}`` dicts.

        Suitable for charting on the frontend.
        """
        now = datetime.now(UTC)

        if period == "YTD":
            start = datetime(now.year, 1, 1, tzinfo=UTC)
        elif period == "ALL":
            start = datetime(2000, 1, 1, tzinfo=UTC)
        else:
            days = _PERIOD_DAYS.get(period, 30)
            start = now - timedelta(days=days)

        async with _get_session_factory()() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT created_at, total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :start
                    ORDER BY created_at ASC
                    """
                ),
                {"start": start},
            )
            data = rows.fetchall()

        return [
            {"timestamp": row[0].isoformat(), "value": float(row[1])}
            for row in data
        ]

    # ------------------------------------------------------------------
    # Attribution: per-strategy breakdown
    # ------------------------------------------------------------------

    @staticmethod
    async def get_attribution() -> dict:
        """Compute per-strategy percentage of total PnL.

        Groups realized PnL by the originating signal's ``strategy_name``.
        """
        async with _get_session_factory()() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT s.strategy_name,
                           SUM((f.fill_price - p.avg_entry_price) * f.filled_qty) AS realized_pnl
                    FROM fills f
                    JOIN orders o ON o.id = f.order_id
                    LEFT JOIN signals s ON s.id = o.signal_id
                    LEFT JOIN positions p ON p.symbol = o.symbol AND p.exchange = o.exchange
                    WHERE o.side = 'SELL'
                      AND s.strategy_name IS NOT NULL
                    GROUP BY s.strategy_name
                    """
                ),
            )
            data = rows.fetchall()

        attribution: dict[str, float] = {}
        total_pnl = 0.0
        for row in data:
            name = row[0] or "unknown"
            pnl = float(row[1]) if row[1] else 0.0
            attribution[name] = pnl
            total_pnl += abs(pnl)

        # Convert to percentages
        result: dict[str, float] = {}
        for name, pnl in attribution.items():
            pct = (pnl / total_pnl * 100) if total_pnl > 0 else 0.0
            result[name] = round(pct, 2)

        logger.info("attribution_computed", strategies=len(result))
        return result
