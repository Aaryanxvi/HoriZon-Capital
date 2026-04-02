"""Benchmark comparison service.

Compares portfolio returns against standard benchmarks (Nifty 50, S&P 500,
BTC) and computes relative performance metrics.

Research references
-------------------
- Sharpe 1994, "The Sharpe Ratio", J. Portfolio Management — active return
  vs benchmark is the standard evaluation framework.
- DeMiguel, Garlappi & Uppal 2009, Review of Financial Studies (~6,000
  citations) — out-of-sample benchmark comparison methodology.
- Brinson, Hood & Beebower 1986, Financial Analysts Journal (~2,000
  citations) — performance attribution vs benchmark decomposition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.backtesting.backtest_metrics import BacktestMetrics
from app.core.logging import get_logger

logger = get_logger("backtesting.benchmark")

# Standard benchmark symbols
BENCHMARKS = {
    "NIFTY50": "^NSEI",      # Nifty 50 (India)
    "SP500": "^GSPC",        # S&P 500 (US)
    "BTC": "BTC-USD",        # Bitcoin
    "NASDAQ": "^IXIC",       # NASDAQ Composite
    "SENSEX": "^BSESN",      # BSE Sensex (India)
}


@dataclass
class BenchmarkComparison:
    """Comparison of portfolio vs a single benchmark."""

    benchmark_name: str
    benchmark_symbol: str

    # Portfolio metrics
    portfolio_return: float = 0.0
    portfolio_sharpe: float = 0.0
    portfolio_max_dd: float = 0.0
    portfolio_volatility: float = 0.0

    # Benchmark metrics
    benchmark_return: float = 0.0
    benchmark_sharpe: float = 0.0
    benchmark_max_dd: float = 0.0
    benchmark_volatility: float = 0.0

    # Relative metrics
    excess_return: float = 0.0  # portfolio - benchmark
    alpha: float = 0.0  # Jensen's alpha
    beta: float = 0.0
    information_ratio: float = 0.0
    tracking_error: float = 0.0
    up_capture: float = 0.0  # upside capture ratio
    down_capture: float = 0.0  # downside capture ratio
    correlation: float = 0.0


@dataclass
class BenchmarkReport:
    """Full benchmark comparison report."""

    comparisons: list[BenchmarkComparison] = field(default_factory=list)
    best_benchmark: str = ""
    portfolio_rank: int = 0  # 1 = beat all benchmarks


class BenchmarkComparer:
    """Compare portfolio performance against standard benchmarks.

    Ref: Brinson, Hood & Beebower 1986 — the BHB model decomposes
    active return into allocation effect, selection effect, and
    interaction effect. We compute a simplified version focused on
    total return, risk-adjusted metrics, and capture ratios.
    """

    @staticmethod
    def compare(
        portfolio_returns: np.ndarray,
        benchmark_returns: np.ndarray,
        benchmark_name: str = "SP500",
        benchmark_symbol: str = "^GSPC",
        risk_free: float = 0.05,
    ) -> BenchmarkComparison:
        """Compare portfolio returns against a single benchmark.

        Parameters
        ----------
        portfolio_returns:
            Daily portfolio returns.
        benchmark_returns:
            Daily benchmark returns (must be same length).
        benchmark_name:
            Human-readable benchmark name.
        benchmark_symbol:
            Ticker symbol for the benchmark.
        risk_free:
            Annual risk-free rate.
        """
        port = np.asarray(portfolio_returns, dtype=np.float64)
        bench = np.asarray(benchmark_returns, dtype=np.float64)

        # Align lengths
        n = min(len(port), len(bench))
        port, bench = port[:n], bench[:n]
        mask = ~(np.isnan(port) | np.isnan(bench))
        port, bench = port[mask], bench[mask]

        if len(port) < 10:
            return BenchmarkComparison(
                benchmark_name=benchmark_name,
                benchmark_symbol=benchmark_symbol,
            )

        # Portfolio metrics
        port_ret = float((1 + port).prod() - 1)
        port_sharpe = BacktestMetrics.sharpe_ratio(port, risk_free)
        port_eq = np.cumprod(1 + port)
        port_mdd = BacktestMetrics.max_drawdown(port_eq)
        port_vol = BacktestMetrics.volatility_annual(port)

        # Benchmark metrics
        bench_ret = float((1 + bench).prod() - 1)
        bench_sharpe = BacktestMetrics.sharpe_ratio(bench, risk_free)
        bench_eq = np.cumprod(1 + bench)
        bench_mdd = BacktestMetrics.max_drawdown(bench_eq)
        bench_vol = BacktestMetrics.volatility_annual(bench)

        # Alpha & beta
        ab = BacktestMetrics.alpha_beta(port, bench)

        # Information ratio
        ir = BacktestMetrics.information_ratio(port, bench)

        # Tracking error
        active = port - bench
        te = float(np.std(active, ddof=1) * np.sqrt(252))

        # Capture ratios (Ref: Bacon 2008)
        up_mask = bench > 0
        down_mask = bench < 0
        up_capture = 0.0
        down_capture = 0.0
        if np.sum(up_mask) > 0:
            up_capture = float(np.mean(port[up_mask]) / np.mean(bench[up_mask]))
        if np.sum(down_mask) > 0:
            down_capture = float(np.mean(port[down_mask]) / np.mean(bench[down_mask]))

        # Correlation
        corr = float(np.corrcoef(port, bench)[0, 1]) if len(port) > 2 else 0.0

        return BenchmarkComparison(
            benchmark_name=benchmark_name,
            benchmark_symbol=benchmark_symbol,
            portfolio_return=round(port_ret, 6),
            portfolio_sharpe=round(port_sharpe, 4),
            portfolio_max_dd=round(port_mdd, 6),
            portfolio_volatility=round(port_vol, 6),
            benchmark_return=round(bench_ret, 6),
            benchmark_sharpe=round(bench_sharpe, 4),
            benchmark_max_dd=round(bench_mdd, 6),
            benchmark_volatility=round(bench_vol, 6),
            excess_return=round(port_ret - bench_ret, 6),
            alpha=ab["alpha"],
            beta=ab["beta"],
            information_ratio=round(ir, 4),
            tracking_error=round(te, 6),
            up_capture=round(up_capture, 4),
            down_capture=round(down_capture, 4),
            correlation=round(corr, 4),
        )

    @classmethod
    def compare_all(
        cls,
        portfolio_returns: np.ndarray,
        benchmarks: dict[str, np.ndarray],
        risk_free: float = 0.05,
    ) -> BenchmarkReport:
        """Compare portfolio against multiple benchmarks.

        Parameters
        ----------
        portfolio_returns:
            Daily portfolio returns.
        benchmarks:
            Dict mapping benchmark_name -> daily returns array.
        risk_free:
            Annual risk-free rate.
        """
        comparisons: list[BenchmarkComparison] = []

        for name, bench_ret in benchmarks.items():
            symbol = BENCHMARKS.get(name, name)
            comp = cls.compare(
                portfolio_returns, bench_ret,
                benchmark_name=name,
                benchmark_symbol=symbol,
                risk_free=risk_free,
            )
            comparisons.append(comp)

        # Rank portfolio vs benchmarks
        all_returns = [(c.benchmark_name, c.benchmark_return) for c in comparisons]
        port_ret = comparisons[0].portfolio_return if comparisons else 0.0
        all_returns.append(("PORTFOLIO", port_ret))
        all_returns.sort(key=lambda x: x[1], reverse=True)

        rank = next(
            (i + 1 for i, (name, _) in enumerate(all_returns) if name == "PORTFOLIO"),
            len(all_returns),
        )
        best = all_returns[0][0] if all_returns else ""

        report = BenchmarkReport(
            comparisons=comparisons,
            best_benchmark=best,
            portfolio_rank=rank,
        )

        logger.info(
            "benchmark_comparison_complete",
            n_benchmarks=len(comparisons),
            portfolio_rank=rank,
            best=best,
        )

        return report
