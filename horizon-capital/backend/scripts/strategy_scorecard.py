# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-7F34C2B1FBDE
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Honest scorecard for the breadth engine — "where does this actually stand?"

Runs the robustness/significance battery that separates real edge from overfit
luck. Operates on the deterministic multi_signal scorer (the go-forward strategy),
reusing the backtest from validate_breadth. Market-agnostic: today it runs on free
US data via yfinance, but the same harness will run on NSE data unchanged once a
market is chosen.

Tests:
  1. Cost sensitivity   — Sharpe at 1x / 3x / 5x / 10x modeled costs
  2. Parameter robustness — Sharpe across top-K and momentum-lookback variations
  3. Regime / subperiod  — per-calendar-year return vs SPY
  4. Bootstrap Sharpe CI — block-bootstrap 5/50/95th pct + prob(Sharpe>0)
  5. Alpha significance  — OLS vs SPY: annualized alpha, beta, t-stat
  6. Deflated Sharpe     — honest trial count (this battery itself is many trials)

NOTE ON ABSOLUTE NUMBERS: the universe is current large-caps => survivorship bias.
Levels are inflated. These tests judge STRUCTURE (survives costs? overfit? one-regime?
statistically real?), which is informative despite the bias. Only the PIT-universe
backtest (blocked on data) fixes the levels.

Usage:
    python -m scripts.strategy_scorecard --start 2012-01-01 --oos-start 2019-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app.quant.multi_signal as ms  # noqa: E402
import scripts.validate_breadth as vb  # noqa: E402
from scripts.validate_breadth import backtest, fetch  # noqa: E402

TRADING_DAYS = 252
RF = 0.04
K_BASE = 25
np.random.seed(7)  # reproducible bootstrap


def sharpe(eq: pd.Series) -> float:
    r = eq.pct_change().dropna()
    vol = r.std() * np.sqrt(TRADING_DAYS)
    return (r.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0.0


def run_eq(closes, opens, cal, k=K_BASE, capital=100_000.0) -> pd.Series:
    return backtest(closes, opens, cal, k, capital).reindex(cal).dropna()


# 1. ---------------------------------------------------------------- cost
def test_cost(closes, opens, cal) -> list[tuple[str, float]]:
    base_c, base_s = vb.COMMISSION_BPS, vb.SLIPPAGE_BPS
    out = []
    try:
        for mult in (1, 3, 5, 10):
            vb.COMMISSION_BPS, vb.SLIPPAGE_BPS = base_c * mult, base_s * mult
            out.append((f"{mult}x cost", round(sharpe(run_eq(closes, opens, cal)), 2)))
    finally:
        vb.COMMISSION_BPS, vb.SLIPPAGE_BPS = base_c, base_s
    return out


# 2. -------------------------------------------------------- param robustness
def test_params(closes, opens, cal) -> tuple[list, list]:
    k_rows = [(f"top-{k}", round(sharpe(run_eq(closes, opens, cal, k=k)), 2))
              for k in (10, 15, 20, 25, 30, 40)]

    lb_rows = []
    base_long, base_min = ms._MOM_LONG, ms._MIN_HISTORY
    try:
        for lb in (189, 210, 252, 294):  # ~9m to ~14m momentum lookback
            ms._MOM_LONG = lb
            ms._MIN_HISTORY = lb + 1
            lb_rows.append((f"mom={lb}d", round(sharpe(run_eq(closes, opens, cal)), 2)))
    finally:
        ms._MOM_LONG, ms._MIN_HISTORY = base_long, base_min
    return k_rows, lb_rows


# 3. ------------------------------------------------------------- regime/year
def test_regime(eq: pd.Series, spy: pd.Series) -> list[tuple]:
    s_yr = eq.groupby(eq.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1)
    b_yr = spy.groupby(spy.index.year).apply(lambda x: x.iloc[-1] / x.iloc[0] - 1)
    rows = []
    for y in s_yr.index:
        sv, bv = s_yr[y] * 100, b_yr.get(y, np.nan) * 100
        rows.append((y, round(sv, 1), round(bv, 1), "win" if sv > bv else ""))
    return rows


# 4. --------------------------------------------------------------- bootstrap
def test_bootstrap(eq: pd.Series, iters=2000, block=21) -> dict:
    r = eq.pct_change().dropna().values
    n = len(r)
    if n < block * 3:
        return {}
    nb = int(np.ceil(n / block))
    sharpes = []
    for _ in range(iters):
        starts = np.random.randint(0, n - block, size=nb)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        vol = sample.std() * np.sqrt(TRADING_DAYS)
        sharpes.append((sample.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0.0)
    sharpes = np.array(sharpes)
    return {
        "p5": round(float(np.percentile(sharpes, 5)), 2),
        "p50": round(float(np.percentile(sharpes, 50)), 2),
        "p95": round(float(np.percentile(sharpes, 95)), 2),
        "prob_pos": round(float((sharpes > 0).mean()), 3),
    }


# 5. ------------------------------------------------------------- alpha t-stat
def test_alpha(eq: pd.Series, spy: pd.Series) -> dict:
    sr = eq.pct_change().dropna()
    br = spy.pct_change().dropna()
    df = pd.DataFrame({"s": sr, "b": br}).dropna()
    x, y = df["b"].values, df["s"].values
    beta, alpha = np.polyfit(x, y, 1)
    resid = y - (beta * x + alpha)
    n = len(x)
    sxx = np.sum((x - x.mean()) ** 2)
    se = resid.std(ddof=2) * np.sqrt(1.0 / n + x.mean() ** 2 / sxx) if sxx > 0 else np.nan
    t = alpha / se if se and not np.isnan(se) else np.nan
    return {
        "ann_alpha%": round(alpha * TRADING_DAYS * 100, 2),
        "beta": round(float(beta), 2),
        "t_stat": round(float(t), 2) if not np.isnan(t) else None,
    }


# 6. -------------------------------------------------------------------- DSR
def test_dsr(eq: pd.Series, n_trials: int) -> float:
    from app.quant.metrics_advanced import deflated_sharpe_ratio
    r = eq.pct_change().dropna().values
    return round(float(deflated_sharpe_ratio(r, n_trials=n_trials)), 3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--oos-start", default="2019-01-01")
    args = p.parse_args()

    print("Fetching universe (once)...")
    closes, opens = fetch()
    spy_dates = closes["SPY"].dropna().index
    full = spy_dates[spy_dates >= pd.Timestamp(args.start)]
    oos = full[full >= pd.Timestamp(args.oos_start)]
    spy_full = closes["SPY"].loc[full[0]:full[-1]]

    base = run_eq(closes, opens, full)
    base_oos = run_eq(closes, opens, oos)

    print("\n" + "=" * 60)
    print(f"  STRATEGY SCORECARD  (breadth engine, top-{K_BASE})")
    print("=" * 60)
    print(f"Baseline Sharpe: FULL {sharpe(base):.2f} | OOS {sharpe(base_oos):.2f}")

    print("\n[1] COST SENSITIVITY (Sharpe; pass = survives ~3-5x)")
    for lbl, sh in test_cost(closes, opens, full):
        print(f"    {lbl:10s} {sh}")

    print("\n[2] PARAMETER ROBUSTNESS (pass = Sharpe stable, no knife-edge)")
    k_rows, lb_rows = test_params(closes, opens, full)
    print("    top-K:     " + "  ".join(f"{k}={s}" for k, s in k_rows))
    print("    mom-lb:    " + "  ".join(f"{k}={s}" for k, s in lb_rows))

    print("\n[3] REGIME / YEAR  (strat% vs SPY%; pass = positive across regimes)")
    for y, sv, bv, w in test_regime(base, spy_full):
        print(f"    {y}  strat {sv:+6}  spy {bv:+6}  {w}")

    print("\n[4] BOOTSTRAP SHARPE CI (block, full sample)")
    bs = test_bootstrap(base)
    if bs:
        print(f"    5th={bs['p5']}  median={bs['p50']}  95th={bs['p95']}  "
              f"prob(Sharpe>0)={bs['prob_pos']}")

    print("\n[5] ALPHA vs SPY (pass = t_stat > 2)")
    a = test_alpha(base, spy_full)
    print(f"    ann_alpha={a['ann_alpha%']}%  beta={a['beta']}  t_stat={a['t_stat']}")

    # Honest trial count: K-sweep(6) + lookback-sweep(4) + cost(4) + prior demos(4) ~ 18
    n_trials = 18
    print(f"\n[6] DEFLATED SHARPE (honest n_trials={n_trials}; pass = >0.95)")
    print(f"    DSR (prob true Sharpe>0 after deflation) = {test_dsr(base, n_trials)}")

    print("\n" + "-" * 60)
    print("VERDICT GUIDE: structurally sound if cost-robust, param-stable,")
    print("multi-regime positive, bootstrap prob>0.9, t_stat>2, DSR>0.95.")
    print("Levels remain survivorship-inflated until the PIT-universe test.")


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 7F34C2B1FBDE - verify with scripts/authorship.py verify
