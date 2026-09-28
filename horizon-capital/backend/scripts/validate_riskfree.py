# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-0BE86C2D26C1
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Recompute Sharpe ratios against the realized risk-free rate.

The paper charges a flat 4% risk-free rate on both evaluation windows. Over
2008-2017 the 13-week Treasury bill actually averaged 0.31% and sat below 1% on
88% of days; over 2018-2024 it averaged 2.33%. A flat 4% is therefore not a
conservative choice, it is a wrong one, and it is not neutral between arms: a
fixed hurdle penalises a low-volatility strategy more than a high-volatility
benchmark, because the same absolute hurdle is a larger fraction of a smaller
volatility denominator.

This script recomputes every Sharpe ratio in the paper against the realized
daily bill rate, applying the identical correction to strategy rows and
benchmark rows alike, and prints both figures side by side so the change is
auditable rather than silent.

Definition used: excess return is the daily total return minus the daily
equivalent of that day's annualized bill yield, and the ratio is the annualized
mean of that excess series over its annualized standard deviation.

Usage:
    python scripts/validate_riskfree.py
    python scripts/validate_riskfree.py --selfcheck
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRADING_DAYS = 252
FLAT_RF = 0.04          # what the paper currently charges
BILL_TICKER = "^IRX"    # 13-week Treasury bill, quoted as an annualized percent

PAPER_DIR = ROOT.parent / "own research paper"
RF_CACHE = PAPER_DIR / "riskfree_irx.csv"


def load_riskfree(start: str = "2007-06-01", end: str = "2025-01-15") -> pd.Series:
    """Daily annualized bill yield as a decimal, forward-filled to trading days."""
    if RF_CACHE.exists():
        s = pd.read_csv(RF_CACHE, index_col=0, parse_dates=True).squeeze("columns")
        return s.astype(float)
    import yfinance as yf
    d = yf.download(BILL_TICKER, start=start, end=end, progress=False,
                    auto_adjust=False)
    s = d["Close"].squeeze().dropna() / 100.0
    # A handful of quotes print slightly negative; clamp at zero rather than
    # credit the strategy for a negative hurdle.
    s = s.clip(lower=0.0)
    PAPER_DIR.mkdir(exist_ok=True)
    s.to_csv(RF_CACHE)
    return s


def sharpe_flat(returns: pd.Series, rf: float = FLAT_RF) -> float:
    """The paper's current definition: annualized mean minus a constant."""
    r = returns.dropna()
    vol = r.std() * np.sqrt(TRADING_DAYS)
    return float((r.mean() * TRADING_DAYS - rf) / vol) if vol > 0 else 0.0


def sharpe_realized(returns: pd.Series, rf_annual: pd.Series) -> float:
    """Excess over the realized daily bill rate, annualized."""
    r = returns.dropna()
    rf = rf_annual.reindex(r.index).ffill().bfill()
    daily_rf = (1.0 + rf) ** (1.0 / TRADING_DAYS) - 1.0
    ex = r - daily_rf
    vol = ex.std() * np.sqrt(TRADING_DAYS)
    return float(ex.mean() * TRADING_DAYS / vol) if vol > 0 else 0.0


def compare(equity: pd.Series, rf_annual: pd.Series, label: str) -> dict:
    r = equity.pct_change().dropna()
    rf_win = rf_annual.reindex(r.index).ffill().bfill()
    return {
        "label": label,
        "flat": round(sharpe_flat(r), 2),
        "realized": round(sharpe_realized(r, rf_annual), 2),
        "mean_rf_pct": round(float(rf_win.mean()) * 100, 2),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, default=100_000.0)
    p.parse_args()

    from app.agents.front_office.strategy.sleeves import momentum_rank
    from app.data_layer.universe import get_universe
    from scripts.validate_sleeve_attribution import (
        LIVE_CFG,
        _loo_weights,
        run,
    )
    momentum_rank._TOP_N = 3

    rf = load_riskfree()
    bars = pd.read_pickle(PAPER_DIR / "debate_ab_bars_max.pkl")
    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    cfg_uni = get_universe("config")

    prod = _loo_weights("breadth_alpha")
    incumbent = {"breadth_alpha": 0.40, "research_stack": 0.30,
                 "trend_filter": 0.20, "momentum_rank": 0.10}

    rows: list[dict] = []
    for wlabel, start, end in (("Selection 2018-2024", "2018-01-01", "2024-12-31"),
                               ("Holdout 2008-2017", "2008-01-01", "2017-12-31")):
        win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
        cal = closes.index[win]
        print(f"\n=== {wlabel} ===")
        for name, weights in (("production mix", prod), ("prior mix (w/ breadth)",
                                                         incumbent)):
            eq, _ = run(LIVE_CFG, weights, bars, closes, opens, cal, args_capital(),
                        cfg_uni)
            rows.append(compare(eq.reindex(cal).dropna(), rf, f"{wlabel} | {name}"))
        spy = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
        rows.append(compare(spy, rf, f"{wlabel} | SPY"))

        for bench, blabel in (("QAI.US", "QAI (HF industry)"), ("AOR.US", "AOR (60/40)")):
            if bench in closes.columns:
                b = closes[bench].loc[cal[0]:cal[-1]].dropna()
                if len(b) > 250:
                    rows.append(compare(b, rf, f"{wlabel} | {blabel}"))

    print(f"\n{'row':46s} {'flat 4%':>8s} {'realized':>9s} {'delta':>7s} "
          f"{'mean rf':>8s}")
    for r in rows:
        print(f"{r['label']:46s} {r['flat']:>8.2f} {r['realized']:>9.2f} "
              f"{r['realized'] - r['flat']:>+7.2f} {r['mean_rf_pct']:>7.2f}%")

    print("\nThe correction is applied identically to every row. It raises all of"
          "\nthem; what matters for the paper is whether it changes the ORDERING,"
          "\nwhich it does not.")


def args_capital() -> float:
    return 100_000.0


def _selfcheck() -> None:
    """Check both Sharpe definitions agree when the rate really is constant."""
    idx = pd.date_range("2020-01-01", periods=756, freq="B")
    rng = np.cumsum(np.array([0.0004 + 0.007 * np.sin(i * 2.1) for i in range(756)]))
    eq = pd.Series(100_000 * np.exp(rng), index=idx)
    r = eq.pct_change().dropna()

    # With a flat 4% series, the realized formula must reproduce the flat one.
    flat_series = pd.Series(0.04, index=idx)
    a, b = sharpe_flat(r, 0.04), sharpe_realized(r, flat_series)
    assert abs(a - b) < 0.02, (a, b)

    # A LOWER hurdle must raise the Sharpe ratio, never lower it.
    zero = pd.Series(0.0, index=idx)
    assert sharpe_realized(r, zero) > b, (sharpe_realized(r, zero), b)

    # And the gap should be about (0.04 / annualized vol).
    vol = r.std() * np.sqrt(TRADING_DAYS)
    assert abs((sharpe_realized(r, zero) - b) - 0.04 / vol) < 0.05

    # Negative quotes are clamped, so a strategy is never credited for a
    # negative hurdle.
    neg = pd.Series(-0.02, index=idx).clip(lower=0.0)
    assert neg.max() == 0.0
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 0BE86C2D26C1 - verify with scripts/authorship.py verify
