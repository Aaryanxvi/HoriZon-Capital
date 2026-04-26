"""PerformanceWorker -- periodically computes and stores performance snapshots."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import text

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

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
        now = datetime.now(UTC)
        if period == "1d":
            return now - timedelta(days=1)
        if period == "7d":
            return now - timedelta(days=7)
        if period == "30d":
            return now - timedelta(days=30)
        if period == "90d":
            return now - timedelta(days=90)
        if period == "YTD":
            return datetime(now.year, 1, 1, tzinfo=UTC)
        # ALL -- go back far enough
        return datetime(2000, 1, 1, tzinfo=UTC)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_equity_curve(
        since: datetime,
    ) -> tuple[np.ndarray, list[datetime]]:
        """Load portfolio total_value time series from portfolio_snapshots.

        Returns (values_array, timestamps_list).
        """
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT created_at, total_value
                    FROM portfolio_snapshots
                    WHERE created_at >= :since
                    ORDER BY created_at ASC
                    """
                ),
                {"since": since},
            )
            rows = result.fetchall()
        if not rows:
            return np.array([], dtype=np.float64), []
        values = np.array([float(r.total_value) for r in rows], dtype=np.float64)
        timestamps = [r.created_at for r in rows]
        return values, timestamps

    @staticmethod
    async def _load_trades(since: datetime) -> list[dict[str, Any]]:
        """Load closed trade PnL from fills + orders."""
        async with _get_session_factory()() as session:
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
    def _annualized_return(
        cls, equity: np.ndarray, timestamps: list | None = None,
    ) -> float:
        total = cls._total_return(equity)
        if len(equity) <= 1 or total <= -1.0:
            return 0.0
        if timestamps and len(timestamps) >= 2:
            from datetime import datetime
            first = (
                timestamps[0] if isinstance(timestamps[0], datetime)
                else datetime.fromisoformat(str(timestamps[0]))
            )
            last = (
                timestamps[-1] if isinstance(timestamps[-1], datetime)
                else datetime.fromisoformat(str(timestamps[-1]))
            )
            calendar_days = max((last - first).days, 1)
            trading_days = max(calendar_days * 252 / 365, 1)
        else:
            trading_days = max(len(equity) - 1, 1)
        years = trading_days / TRADING_DAYS_PER_YEAR
        if years == 0:
            return 0.0
        return float((1 + total) ** (1 / years) - 1)

    @classmethod
    def _sharpe_ratio(cls, equity: np.ndarray, risk_free_rate: float | None = None) -> float:
        from app.config import settings
        rf = settings.risk_free_rate if risk_free_rate is None else risk_free_rate
        returns = cls._compute_returns(equity)
        if len(returns) < 2:
            return 0.0
        daily_rf = (1.0 + rf) ** (1 / TRADING_DAYS_PER_YEAR) - 1
        excess = returns - daily_rf
        std = float(np.std(excess, ddof=1))
        if std == 0:
            return 0.0
        return float(np.mean(excess) / std * np.sqrt(TRADING_DAYS_PER_YEAR))

    @classmethod
    def _sortino_ratio(cls, equity: np.ndarray, risk_free_rate: float | None = None) -> float:
        from app.config import settings
        rf = settings.risk_free_rate if risk_free_rate is None else risk_free_rate
        returns = cls._compute_returns(equity)
        if len(returns) < 2:
            return 0.0
        daily_rf = (1.0 + rf) ** (1 / TRADING_DAYS_PER_YEAR) - 1
        excess = returns - daily_rf
        downside_diff = np.minimum(excess, 0.0)
        downside_std = float(np.sqrt(np.mean(downside_diff ** 2)))
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
    def _calmar_ratio(
        cls, equity: np.ndarray, timestamps: list | None = None,
    ) -> float:
        ann_ret = cls._annualized_return(equity, timestamps)
        max_dd = cls._max_drawdown(equity)
        if max_dd == 0:
            return 0.0
        return float(ann_ret / max_dd)

    @staticmethod
    def _win_rate(trades: list[dict[str, Any]]) -> float:
        """Fraction of round-trip trades with positive realized PnL."""
        if not trades:
            return 0.0
        buy_cost = 0.0
        buy_qty = 0.0
        round_trips = 0
        winners = 0
        for t in trades:
            if t["side"] == "BUY":
                buy_cost += t["fill_price"] * t["filled_qty"]
                buy_qty += t["filled_qty"]
            elif t["side"] == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                sell_qty = min(t["filled_qty"], buy_qty)
                realized_pnl = (t["fill_price"] - avg_entry) * sell_qty - t.get("commission", 0)
                round_trips += 1
                if realized_pnl > 0:
                    winners += 1
                buy_cost -= avg_entry * sell_qty
                buy_qty -= sell_qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0
        return float(winners / round_trips) if round_trips > 0 else 0.0

    @staticmethod
    def _profit_factor(trades: list[dict[str, Any]]) -> float:
        """Gross profit / gross loss from realized round-trip PnL."""
        buy_cost = 0.0
        buy_qty = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        for t in trades:
            if t["side"] == "BUY":
                buy_cost += t["fill_price"] * t["filled_qty"]
                buy_qty += t["filled_qty"]
            elif t["side"] == "SELL" and buy_qty > 0:
                avg_entry = buy_cost / buy_qty
                sell_qty = min(t["filled_qty"], buy_qty)
                realized_pnl = (t["fill_price"] - avg_entry) * sell_qty - t.get("commission", 0)
                if realized_pnl > 0:
                    gross_profit += realized_pnl
                else:
                    gross_loss += abs(realized_pnl)
                buy_cost -= avg_entry * sell_qty
                buy_qty -= sell_qty
                if buy_qty <= 0:
                    buy_cost = 0.0
                    buy_qty = 0.0
        if gross_loss == 0:
            return 0.0 if gross_profit == 0 else float("inf")
        return float(gross_profit / gross_loss)

    # ------------------------------------------------------------------
    # Alpha vs benchmark
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_benchmark_returns(
        benchmark_symbol: str,
        since: datetime,
    ) -> np.ndarray:
        """Load benchmark OHLCV and return daily close returns.

        Tries local DB first (symbol may exist from backfill), then
        falls back to yfinance for on-demand fetch.
        """
        # Try local DB
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT close
                    FROM ohlcv
                    WHERE symbol = :symbol AND timeframe = '1d'
                      AND timestamp >= :since
                    ORDER BY timestamp ASC
                    """
                ),
                {"symbol": benchmark_symbol, "since": since},
            )
            rows = result.fetchall()

        if len(rows) >= 10:
            closes = np.array([r.close for r in rows], dtype=np.float64)
            if len(closes) < 2:
                return np.array([], dtype=np.float64)
            return np.diff(closes) / np.where(closes[:-1] == 0, 1.0, closes[:-1])

        # Fallback: fetch from yfinance
        try:
            import yfinance as yf

            yf_map = {
                "NIFTY50": "^NSEI",
                "SPX": "^GSPC",
                "SP500": "^GSPC",
            }
            ticker_symbol = yf_map.get(benchmark_symbol, benchmark_symbol)
            ticker = yf.Ticker(ticker_symbol)

            days_back = (datetime.now(UTC) - since).days + 5
            period = f"{max(days_back, 30)}d"
            hist = ticker.history(period=period)

            if hist.empty or len(hist) < 2:
                return np.array([], dtype=np.float64)

            closes = hist["Close"].values.astype(np.float64)
            return np.diff(closes) / np.where(closes[:-1] == 0, 1.0, closes[:-1])
        except Exception:
            return np.array([], dtype=np.float64)

    @classmethod
    def _compute_alpha(
        cls,
        portfolio_returns: np.ndarray,
        benchmark_returns: np.ndarray,
    ) -> float:
        """Compute Jensen's alpha: annualized excess return vs benchmark.

        Alpha = annualized(portfolio_return - beta * benchmark_return)
        Uses simple excess return when there's insufficient data for regression.
        """
        if len(portfolio_returns) < 5 or len(benchmark_returns) < 5:
            return 0.0

        # Align lengths (use the shorter series)
        n = min(len(portfolio_returns), len(benchmark_returns))
        p_ret = portfolio_returns[-n:]
        b_ret = benchmark_returns[-n:]

        # Compute beta via OLS: beta = cov(p, b) / var(b)
        b_var = float(np.var(b_ret, ddof=1))
        if b_var == 0:
            return 0.0
        beta = float(np.cov(p_ret, b_ret)[0, 1] / b_var)

        # Jensen's alpha (daily)
        daily_alpha = float(np.mean(p_ret) - beta * np.mean(b_ret))

        # Annualize
        return float(daily_alpha * TRADING_DAYS_PER_YEAR)

    # ------------------------------------------------------------------
    # Full snapshot
    # ------------------------------------------------------------------

    async def compute_snapshot(self, period: str) -> dict[str, Any]:
        """Compute all metrics for a single period and return as a dict."""
        since = self._period_start(period)
        equity, timestamps = await self._load_equity_curve(since)
        trades = await self._load_trades(since)
        portfolio_returns = self._compute_returns(equity)

        # Compute alpha against NIFTY 50 and S&P 500
        alpha_india = 0.0
        alpha_us = 0.0
        if len(portfolio_returns) >= 5:
            try:
                nifty_returns = await self._load_benchmark_returns("NIFTY50", since)
                alpha_india = round(self._compute_alpha(portfolio_returns, nifty_returns), 6)
            except Exception:
                pass
            try:
                spx_returns = await self._load_benchmark_returns("SPX", since)
                alpha_us = round(self._compute_alpha(portfolio_returns, spx_returns), 6)
            except Exception:
                pass

        return {
            "period": period,
            "total_return": round(self._total_return(equity), 6),
            "annualized_return": round(self._annualized_return(equity, timestamps), 6),
            "sharpe_ratio": round(self._sharpe_ratio(equity), 4),
            "sortino_ratio": round(self._sortino_ratio(equity), 4),
            "calmar_ratio": round(self._calmar_ratio(equity, timestamps), 4),
            "max_drawdown": round(self._max_drawdown(equity), 6),
            "win_rate": round(self._win_rate(trades), 4),
            "profit_factor": round(self._profit_factor(trades), 4),
            "alpha_india": alpha_india,
            "alpha_us": alpha_us,
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

        try:
            while self._running:
                try:
                    await self._compute_and_store_all()
                except Exception as exc:
                    logger.error("performance_worker.snapshot_error", error=str(exc))

                await asyncio.sleep(SNAPSHOT_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("performance_worker.stopping")
        self._running = False

    async def _compute_and_store_all(self) -> None:
        """Compute snapshots for every period and persist to Postgres + Redis."""
        import orjson

        now = datetime.now(UTC)

        for period in PERIODS:
            try:
                snapshot = await self.service.compute_snapshot(period)

                # Persist to performance_snapshots table
                async with _get_session_factory()() as session:
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
                                (:id, :period, :total_return, :annualized_return,
                                 :sharpe_ratio, :sortino_ratio, :calmar_ratio,
                                 :max_drawdown, :win_rate, :profit_factor,
                                 :alpha_india, :alpha_us, :total_trades,
                                 :attribution, :now, :now)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
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
                kv = get_kv_store()
                await kv.hset(
                    redis_key,
                    mapping={k: str(v) for k, v in snapshot.items()},
                )
                await kv.expire(redis_key, 3600)

                # Service-layer alpha lookups read these top-level keys.
                # Worker is the single writer. Use the 30d period as canonical.
                if period == "30d":
                    await kv.set(
                        "horizon:performance:alpha_india",
                        str(snapshot["alpha_india"]),
                        ex=3600,
                    )
                    await kv.set(
                        "horizon:performance:alpha_us",
                        str(snapshot["alpha_us"]),
                        ex=3600,
                    )

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
