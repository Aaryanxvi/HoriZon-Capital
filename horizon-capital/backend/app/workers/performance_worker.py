"""PerformanceWorker -- periodically computes and stores performance snapshots."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis_client import redis_client

logger = get_logger("worker.performance")

# Snapshot periods to compute
PERIODS = ["1d", "7d", "30d", "90d", "YTD", "ALL"]

# How often to run (seconds)
SNAPSHOT_INTERVAL = 900  # 15 minutes

# Trading days per year for annualisation
TRADING_DAYS_PER_YEAR = 252


class PerformanceService:
    """Stateless helper that computes performance metrics from portfolio data."""

    # ------------------------------------------------------------------
    # Period boundaries
    # ------------------------------------------------------------------

    @staticmethod
    def _period_start(period: str) -> datetime:
        """Return the UTC datetime that marks the start of the given period."""
        now = datetime.now(timezone.utc)
        if period == "1d":
            return now - timedelta(days=1)
        if period == "7d":
            return now - timedelta(days=7)
        if period == "30d":
            return now - timedelta(days=30)
        if period == "90d":
            return now - timedelta(days=90)
        if period == "YTD":
            return datetime(now.year, 1, 1, tzinfo=timezone.utc)
        # ALL -- go back far enough
        return datetime(2000, 1, 1, tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_equity_curve(since: datetime) -> np.ndarray:
        """Load portfolio total_value time series from portfolio_snapshots."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :since
                    ORDER BY created_at ASC
                    """
                ),
                {"since": since},
            )
            rows = result.fetchall()
        if not rows:
            return np.array([], dtype=np.float64)
        return np.array([r.total_value for r in rows], dtype=np.float64)

    @staticmethod
    async def _load_trades(since: datetime) -> list[dict[str, Any]]:
        """Load closed trade PnL from fills + orders."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT f.fill_price, f.filled_qty, f.commission, o.side
                    FROM fills f
                    JOIN orders o ON o.id = f.order_id
                    WHERE f.filled_at >= :since
                    ORDER BY f.filled_at ASC
                    """
                ),
                {"since": since},
            )
            rows = result.fetchall()
        return [
            {
                "fill_price": r.fill_price,
                "filled_qty": r.filled_qty,
                "commission": r.commission,
                "side": r.side,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Metric calculations
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_returns(equity: np.ndarray) -> np.ndarray:
        """Simple daily returns from an equity curve."""
        if len(equity) < 2:
            return np.array([], dtype=np.float64)
        returns = np.diff(equity) / np.where(equity[:-1] == 0, 1.0, equity[:-1])
        return returns

    @classmethod
    def _total_return(cls, equity: np.ndarray) -> float:
        if len(equity) < 2 or equity[0] == 0:
            return 0.0
        return float((equity[-1] - equity[0]) / equity[0])

    @classmethod
    def _annualized_return(cls, equity: np.ndarray) -> float:
        total = cls._total_return(equity)
        n_days = len(equity)
        if n_days <= 1 or total <= -1.0:
            return 0.0
        years = n_days / TRADING_DAYS_PER_YEAR
        if years == 0:
            return 0.0
        return float((1 + total) ** (1 / years) - 1)

    @classmethod
    def _sharpe_ratio(cls, equity: np.ndarray, risk_free_rate: float = 0.0) -> float:
        returns = cls._compute_returns(equity)
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / TRADING_DAYS_PER_YEAR
        std = float(np.std(excess, ddof=1))
        if std == 0:
            return 0.0
        return float(np.mean(excess) / std * np.sqrt(TRADING_DAYS_PER_YEAR))

    @classmethod
    def _sortino_ratio(cls, equity: np.ndarray, risk_free_rate: float = 0.0) -> float:
        returns = cls._compute_returns(equity)
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / TRADING_DAYS_PER_YEAR
        downside = excess[excess < 0]
        if len(downside) == 0:
            return 0.0
        downside_std = float(np.std(downside, ddof=1))
        if downside_std == 0:
            return 0.0
        return float(np.mean(excess) / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))

    @staticmethod
    def _max_drawdown(equity: np.ndarray) -> float:
        if len(equity) < 2:
            return 0.0
        running_max = np.maximum.accumulate(equity)
        drawdowns = (running_max - equity) / np.where(running_max == 0, 1.0, running_max)
        return float(np.max(drawdowns))

    @classmethod
    def _calmar_ratio(cls, equity: np.ndarray) -> float:
        ann_ret = cls._annualized_return(equity)
        max_dd = cls._max_drawdown(equity)
        if max_dd == 0:
            return 0.0
        return float(ann_ret / max_dd)

    @staticmethod
    def _win_rate(trades: list[dict[str, Any]]) -> float:
        """Fraction of profitable fills (simplified: BUY fills with fill_price > 0)."""
        if not trades:
            return 0.0
        # A trade "wins" when it was a SELL that realised positive PnL.
        # Simplified: count SELL fills as trades, and use fill_price * qty - commission.
        sell_trades = [t for t in trades if t["side"] == "SELL"]
        if not sell_trades:
            return 0.0
        winners = sum(
            1
            for t in sell_trades
            if t["fill_price"] * t["filled_qty"] - t["commission"] > 0
        )
        return float(winners / len(sell_trades))

    @staticmethod
    def _profit_factor(trades: list[dict[str, Any]]) -> float:
        gross_profit = 0.0
        gross_loss = 0.0
        for t in trades:
            pnl = t["fill_price"] * t["filled_qty"] - t["commission"]
            if t["side"] == "SELL":
                if pnl > 0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
        if gross_loss == 0:
            return 0.0 if gross_profit == 0 else float("inf")
        return float(gross_profit / gross_loss)

    # ------------------------------------------------------------------
    # Full snapshot
    # ------------------------------------------------------------------

    async def compute_snapshot(self, period: str) -> dict[str, Any]:
        """Compute all metrics for a single period and return as a dict."""
        since = self._period_start(period)
        equity = await self._load_equity_curve(since)
        trades = await self._load_trades(since)

        return {
            "period": period,
            "total_return": round(self._total_return(equity), 6),
            "annualized_return": round(self._annualized_return(equity), 6),
            "sharpe_ratio": round(self._sharpe_ratio(equity), 4),
            "sortino_ratio": round(self._sortino_ratio(equity), 4),
            "calmar_ratio": round(self._calmar_ratio(equity), 4),
            "max_drawdown": round(self._max_drawdown(equity), 6),
            "win_rate": round(self._win_rate(trades), 4),
            "profit_factor": round(self._profit_factor(trades), 4),
            "alpha_india": 0.0,  # TODO: benchmark against NIFTY
            "alpha_us": 0.0,  # TODO: benchmark against SPX
            "total_trades": len([t for t in trades if t["side"] == "SELL"]),
            "attribution": {},
        }


class PerformanceWorker:
    """Every 15 minutes, compute performance snapshots for all periods and persist."""

    def __init__(self) -> None:
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self.service = PerformanceService()

    async def run(self) -> None:
        """Start the periodic snapshot loop."""
        self._running = True
        logger.info("performance_worker.starting")

        while self._running:
            try:
                await self._compute_and_store_all()
            except Exception as exc:
                logger.error("performance_worker.snapshot_error", error=str(exc))

            await asyncio.sleep(SNAPSHOT_INTERVAL)

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("performance_worker.stopping")
        self._running = False

    async def _compute_and_store_all(self) -> None:
        """Compute snapshots for every period and persist to Postgres + Redis."""
        import orjson

        now = datetime.now(timezone.utc)

        for period in PERIODS:
            try:
                snapshot = await self.service.compute_snapshot(period)

                # Persist to performance_snapshots table
                async with async_session_factory() as session:
                    await session.execute(
                        text(
                            """
                            INSERT INTO performance_snapshots
                                (id, period, total_return, annualized_return,
                                 sharpe_ratio, sortino_ratio, calmar_ratio,
                                 max_drawdown, win_rate, profit_factor,
                                 alpha_india, alpha_us, total_trades,
                                 attribution, created_at, updated_at)
                            VALUES
                                (gen_random_uuid(), :period, :total_return, :annualized_return,
                                 :sharpe_ratio, :sortino_ratio, :calmar_ratio,
                                 :max_drawdown, :win_rate, :profit_factor,
                                 :alpha_india, :alpha_us, :total_trades,
                                 :attribution::jsonb, :now, :now)
                            """
                        ),
                        {
                            "period": snapshot["period"],
                            "total_return": snapshot["total_return"],
                            "annualized_return": snapshot["annualized_return"],
                            "sharpe_ratio": snapshot["sharpe_ratio"],
                            "sortino_ratio": snapshot["sortino_ratio"],
                            "calmar_ratio": snapshot["calmar_ratio"],
                            "max_drawdown": snapshot["max_drawdown"],
                            "win_rate": snapshot["win_rate"],
                            "profit_factor": snapshot["profit_factor"],
                            "alpha_india": snapshot["alpha_india"],
                            "alpha_us": snapshot["alpha_us"],
                            "total_trades": snapshot["total_trades"],
                            "attribution": orjson.dumps(snapshot["attribution"]).decode(),
                            "now": now,
                        },
                    )
                    await session.commit()

                # Cache latest for each period in Redis
                redis_key = f"horizon:performance:{period}"
                await redis_client.hset(
                    redis_key,
                    mapping={k: str(v) for k, v in snapshot.items()},
                )
                await redis_client.expire(redis_key, 3600)

                logger.debug(
                    "performance_snapshot_stored",
                    period=period,
                    sharpe=snapshot["sharpe_ratio"],
                    total_return=snapshot["total_return"],
                )

            except Exception as exc:
                logger.error(
                    "performance_snapshot_period_error",
                    period=period,
                    error=str(exc),
                )

        logger.info("performance_worker.snapshots_complete", periods=len(PERIODS))
