"""Probabilistic & Deflated Sharpe Ratio (Lopez de Prado 2014, 2018).

PSR  — probability that observed Sharpe > benchmark, given skew/kurt of returns.
DSR  — deflates the *best* Sharpe across N trials to control selection bias.
       Required when you backtested many strategies and only show the winner.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy.stats import norm


def sharpe_ratio(
    returns: Sequence[float],
    periods_per_year: int = 252,
    risk_free: float | None = None,
) -> float:
    from app.config import settings

    rf = settings.risk_free_rate if risk_free is None else risk_free
    r = np.asarray(returns, dtype=float)
    if r.size < 2 or r.std(ddof=1) == 0:
        return 0.0
    daily_rf = (1 + rf) ** (1 / periods_per_year) - 1
    excess = r - daily_rf
    return float(excess.mean() / excess.std(ddof=1) * math.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(
    returns: Sequence[float],
    benchmark_sr: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Probability that the *true* SR exceeds benchmark_sr.

    Lopez de Prado 2014, eq. 1. Adjusts for skew + excess kurtosis.
    Returns probability in [0, 1].
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 4:
        return 0.0
    sr_hat = sharpe_ratio(r, periods_per_year)
    # Convert annualised benchmark to per-period
    sr_hat_p = sr_hat / math.sqrt(periods_per_year)
    bench_p = benchmark_sr / math.sqrt(periods_per_year)

    skew = float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12))
    kurt = float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12))  # raw kurt
    excess_kurt = kurt - 3.0

    num = (sr_hat_p - bench_p) * math.sqrt(n - 1)
    den = math.sqrt(
        max(1 - skew * sr_hat_p + (excess_kurt / 4) * sr_hat_p**2, 1e-12)
    )
    z = num / den
    return float(norm.cdf(z))


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int,
    sr_variance_across_trials: float | None = None,
    periods_per_year: int = 252,
) -> float:
    """DSR — deflates SR for multiple-testing bias.

    n_trials: number of independent strategies you backtested.
    sr_variance_across_trials: variance of SRs across those trials (if known).
                               If None, conservative assumption used.
    Returns probability that *true* SR > 0 after deflation.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 4 or n_trials < 1:
        return 0.0
    if sr_variance_across_trials is None:
        # Conservative: variance equal to SR / sqrt(n)
        sr_variance_across_trials = sharpe_ratio(r, 1) ** 2 / max(r.size, 1)

    # Expected max SR under null (Bailey-Lopez de Prado 2014)
    em_const = 0.5772156649  # Euler-Mascheroni
    expected_max = math.sqrt(sr_variance_across_trials) * (
        (1 - em_const) * norm.ppf(1 - 1.0 / n_trials)
        + em_const * norm.ppf(1 - 1.0 / (n_trials * math.e))
    )
    return probabilistic_sharpe_ratio(r, benchmark_sr=expected_max * math.sqrt(periods_per_year),
                                      periods_per_year=periods_per_year)


def max_drawdown(equity: Sequence[float]) -> float:
    e = np.asarray(equity, dtype=float)
    if e.size == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    dd = (e - peak) / peak
    return float(dd.min())


def calmar_ratio(returns: Sequence[float], equity: Sequence[float],
                 periods_per_year: int = 252) -> float:
    cagr = (equity[-1] / equity[0]) ** (periods_per_year / max(len(equity), 1)) - 1
    mdd = abs(max_drawdown(equity))
    return float(cagr / mdd) if mdd > 0 else 0.0


def sortino_ratio(returns: Sequence[float], periods_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    downside = r[r < 0]
    if downside.size == 0 or downside.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / downside.std(ddof=1) * math.sqrt(periods_per_year))
