"""Monte Carlo forward simulation of the validated strategy config.

Answers: "IF the strategy keeps behaving like it did in the validation window,
what is the RANGE of outcomes over the next year?" It does NOT predict the
future — it resamples the past. Regime change invalidates it. Anyone promising
more than a distribution is selling fantasy.

Method: stationary block bootstrap (Politis-Romano) over the daily returns of
the NEW-config backtest (the validate_fix_ab 0.67-Sharpe configuration).
Blocks preserve volatility clustering that iid resampling destroys.

Usage:
    python -m scripts.monte_carlo_forward                      # backtest NEW config, then MC
    python -m scripts.monte_carlo_forward --equity-csv eq.csv  # skip backtest, MC a saved curve
    python -m scripts.monte_carlo_forward --demo               # self-check on synthetic returns

First run backtests NEW config (PIT fetch, minutes) and caches the equity curve
to scripts/.mc_equity_new.csv; later runs reuse it unless --refresh.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.quant.metrics_advanced import (  # noqa: E402
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)

CACHE = Path(__file__).parent / ".mc_equity_new.csv"
TRADING_DAYS = 252
# validate_fix_ab tested 4 config variants; DSR deflates for that selection.
N_TRIALS = 4


def block_bootstrap(
    returns: np.ndarray,
    horizon: int = TRADING_DAYS,
    n_paths: int = 10_000,
    mean_block: float = 20.0,
    seed: int = 42,
) -> np.ndarray:
    """(n_paths, horizon) resampled return paths, stationary bootstrap."""
    rng = np.random.default_rng(seed)
    n = len(returns)
    out = np.empty((n_paths, horizon))
    p = 1.0 / mean_block
    for i in range(n_paths):
        pos, filled = rng.integers(n), 0
        while filled < horizon:
            # geometric block length, wraps around the sample (stationary)
            blk = min(rng.geometric(p), horizon - filled)
            idx = (pos + np.arange(blk)) % n
            out[i, filled:filled + blk] = returns[idx]
            filled += blk
            pos = rng.integers(n)
    return out


def path_stats(paths: np.ndarray, dd_limits: tuple[float, ...] = (-0.15, -0.25)) -> dict:
    equity = np.cumprod(1.0 + paths, axis=1)
    terminal = equity[:, -1] - 1.0
    peaks = np.maximum.accumulate(equity, axis=1)
    max_dd = ((equity - peaks) / peaks).min(axis=1)
    pct = lambda a, q: float(np.percentile(a, q))  # noqa: E731
    return {
        "ret_p5": pct(terminal, 5), "ret_p25": pct(terminal, 25),
        "ret_p50": pct(terminal, 50), "ret_p75": pct(terminal, 75),
        "ret_p95": pct(terminal, 95),
        "p_loss": float((terminal < 0).mean()),
        "dd_p50": pct(max_dd, 50), "dd_p95": pct(max_dd, 5),  # 5th pctile = bad tail
        **{f"p_dd_le_{int(abs(lim) * 100)}": float((max_dd <= lim).mean())
           for lim in dd_limits},
    }


def report(returns: pd.Series, horizon: int, n_paths: int, label: str) -> None:
    r = returns.to_numpy()
    hist_sr = sharpe_ratio(r, risk_free=0.04)
    psr = probabilistic_sharpe_ratio(r)
    dsr = deflated_sharpe_ratio(r, n_trials=N_TRIALS)
    s = path_stats(block_bootstrap(r, horizon=horizon, n_paths=n_paths))

    print(f"\n=== Monte Carlo forward: {label} ===")
    print(f"source: {len(r)} daily returns | hist Sharpe {hist_sr:.2f} "
          f"| PSR(>0) {psr:.0%} | DSR({N_TRIALS} trials) {dsr:.0%}")
    print(f"paths: {n_paths} x {horizon}d stationary block bootstrap (mean block 20d)\n")
    print(f"1y return   p5 {s['ret_p5']:+7.1%}   p25 {s['ret_p25']:+7.1%}   "
          f"median {s['ret_p50']:+7.1%}   p75 {s['ret_p75']:+7.1%}   p95 {s['ret_p95']:+7.1%}")
    print(f"P(losing year)            {s['p_loss']:.0%}")
    print(f"max drawdown   median {s['dd_p50']:.1%}   bad-tail(5%) {s['dd_p95']:.1%}")
    print(f"P(hit -15% DD, old .env limit)   {s['p_dd_le_15']:.0%}")
    print(f"P(hit -25% DD, kill switch)      {s['p_dd_le_25']:.0%}")
    print("\nCaveats: resamples the validation window — assumes that regime persists;")
    print("delisted-price gap inflates source returns; quality tilt stubbed in source.")


def _backtest_new_config(start: str, end: str) -> pd.Series:
    """Run validate_fix_ab's NEW config once, return the equity curve."""
    from app.data_layer.batch_bars import fetch_batch
    from app.data_layer.pit_universe import union_members
    from app.data_layer.universe import _ANCHORS, get_universe
    from scripts.validate_fix_ab import CONFIGS, run

    config_universe = get_universe("config")
    pit = union_members(start, end)
    anchor_bases = {a.split(".")[0] for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), 10y daily...")
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    print(f"Coverage: {len(bars)}/{len(tickers)}")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
    eq, _ = run(CONFIGS["NEW"], bars, closes, opens, closes.index[win],
                100_000.0, config_universe)
    return eq


def demo() -> None:
    """Self-check: known-distribution synthetic returns through the MC engine."""
    rng = np.random.default_rng(0)
    mu, sigma = 0.10 / TRADING_DAYS, 0.15 / np.sqrt(TRADING_DAYS)  # 10% drift, 15% vol
    r = rng.normal(mu, sigma, 1500)
    paths = block_bootstrap(r, n_paths=2000, seed=1)
    assert paths.shape == (2000, TRADING_DAYS)
    s = path_stats(paths)
    assert 0.00 < s["ret_p50"] < 0.25, s["ret_p50"]      # median near the 10% drift
    assert 0.05 < s["p_loss"] < 0.45, s["p_loss"]        # losing years exist but minority
    assert s["ret_p5"] < s["ret_p50"] < s["ret_p95"]     # percentiles ordered
    assert -0.60 < s["dd_p50"] < -0.02, s["dd_p50"]      # sane DD for 15% vol
    # reproducibility
    assert np.array_equal(paths, block_bootstrap(r, n_paths=2000, seed=1))
    print("demo OK:", {k: round(v, 3) for k, v in s.items()})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--equity-csv", help="CSV with date,equity columns (skips backtest)")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--horizon", type=int, default=TRADING_DAYS)
    p.add_argument("--paths", type=int, default=10_000)
    p.add_argument("--refresh", action="store_true", help="ignore cached equity curve")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()

    if args.demo:
        demo()
        return

    if args.equity_csv:
        eq = pd.read_csv(args.equity_csv, index_col=0, parse_dates=True).iloc[:, 0]
        label = Path(args.equity_csv).name
    elif CACHE.exists() and not args.refresh:
        eq = pd.read_csv(CACHE, index_col=0, parse_dates=True).iloc[:, 0]
        label = f"NEW config (cached {CACHE.name})"
    else:
        eq = _backtest_new_config(args.start, args.end)
        eq.to_csv(CACHE)
        label = f"NEW config {args.start}..{args.end}"

    report(eq.pct_change().dropna(), args.horizon, args.paths, label)


if __name__ == "__main__":
    main()
