"""Honest Gate-0 validation of the sleeve stack.

Strips the three biases baked into the demo backtests:
  1. Survivorship — universe is ETF-only (sector SPDRs + SPY/QQQ/TLT/GLD), all
     long-lived and liquid. No cherry-picked single-name mega-cap winners.
  2. Look-ahead — the quality factor (yfinance CURRENT fundamentals applied to
     history) is neutralized to zero, so research_stack scores on price-only
     TSMOM. trend_filter and momentum_rank are already price-only.
  3. In-sample-only — reports a strict out-of-sample holdout in addition to the
     full sample, so you can see whether edge persists on data the (literature-
     fixed, untuned) parameters never "saw".

Runs the REAL sleeve classes (not a parallel re-implementation), with t+1 open
fills and the same costs as paper_broker. gap_fade is excluded — its thesis is
intraday and cannot be tested on daily bars.

Usage:
    python -m scripts.validate_sleeves_oos --start 2007-01-01 --oos-start 2018-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Neutralize the quality look-ahead BEFORE the sleeve uses it. research_stack
# bound `cross_section_quality` at import, so patch it in that module's namespace.
import app.agents.front_office.strategy.sleeves.research_stack as _rs  # noqa: E402
_rs.cross_section_quality = lambda symbols: {}  # -> every quality z-score = 0

from app.agents.front_office.strategy.sleeves import (  # noqa: E402
    MomentumRankSleeve,
    ResearchStackSleeve,
    TrendFilterSleeve,
)

# ETF-only, survivorship-free. These all map to tickers research_stack ranks
# (its _RISK_UNIVERSE already contains the sector SPDRs) so no single names leak.
UNIVERSE = [
    "SPY", "QQQ", "XLE", "XLK", "XLF", "XLV", "XLY", "XLI",  # risk
    "TLT", "GLD",                                            # defense
]
# Map plain tickers -> the suffixed notation the sleeves expect.
SUFFIX = {
    "SPY": "SPY.NYSE", "QQQ": "QQQ.NASDAQ", "XLE": "XLE.NYSE", "XLK": "XLK.NYSE",
    "XLF": "XLF.NYSE", "XLV": "XLV.NYSE", "XLY": "XLY.NYSE", "XLI": "XLI.NYSE",
    "TLT": "TLT.NASDAQ", "GLD": "GLD.NYSE",
}

SLEEVES = [ResearchStackSleeve(), TrendFilterSleeve(), MomentumRankSleeve()]

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
TRADING_DAYS = 252
RF = 0.04  # annual risk-free for Sharpe


def fetch(start: str) -> dict[str, pd.DataFrame]:
    warmup = (pd.Timestamp(start) - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
    raw = yf.download(" ".join(UNIVERSE), start=warmup, progress=False,
                      auto_adjust=True, group_by="ticker")
    bars: dict[str, pd.DataFrame] = {}
    for t in UNIVERSE:
        try:
            df = raw[t].dropna()
        except KeyError:
            continue
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        if len(df) > 300:
            bars[SUFFIX[t]] = df[["open", "high", "low", "close", "volume"]]
    return bars


def _targets_differ(a: list, b: list) -> bool:
    am = {s.symbol: round(s.target_weight, 4) for s in a}
    bm = {s.symbol: round(s.target_weight, 4) for s in b}
    return am != bm


def backtest(bars: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex,
             capital: float) -> pd.Series:
    cash = capital
    shares: dict[str, float] = {}
    cache: dict[str, list] = {}
    equity: dict[pd.Timestamp, float] = {}

    for i, date in enumerate(calendar):
        if i + 1 >= len(calendar):
            break
        fill_date = calendar[i + 1]

        combined: dict[str, float] = {}
        changed = False
        for sleeve in SLEEVES:
            if i % sleeve.rebalance_days == 0 or sleeve.name not in cache:
                sig = sleeve.compute(bars, date)
                if sleeve.name not in cache or _targets_differ(cache[sleeve.name], sig):
                    changed = True
                cache[sleeve.name] = sig
            for s in cache[sleeve.name]:
                combined[s.symbol] = combined.get(s.symbol, 0.0) + s.target_weight * sleeve.target_weight

        nav = cash + sum(
            q * bars[s].loc[date, "close"]
            for s, q in shares.items() if date in bars[s].index
        )
        equity[date] = nav
        if not changed:
            continue

        for sym in bars:
            if fill_date not in bars[sym].index:
                continue
            px = float(bars[sym].loc[fill_date, "open"])
            if px <= 0:
                continue
            tgt_sh = nav * combined.get(sym, 0.0) / px
            delta = tgt_sh - shares.get(sym, 0.0)
            if abs(delta * px) < nav * 0.002:
                continue
            buy = delta > 0
            qty = abs(delta)
            exec_px = px * (1 + SLIPPAGE_BPS / 1e4) if buy else px * (1 - SLIPPAGE_BPS / 1e4)
            comm = qty * exec_px * COMMISSION_BPS / 1e4
            if buy:
                cost = qty * exec_px + comm
                if cost > cash:
                    qty = max(0.0, (cash - comm) / exec_px)
                    if qty <= 0:
                        continue
                    cost = qty * exec_px + comm
                cash -= cost
                shares[sym] = shares.get(sym, 0.0) + qty
            else:
                cash += qty * exec_px - comm
                shares[sym] = shares.get(sym, 0.0) - qty
    return pd.Series(equity)


def metrics(eq: pd.Series, label: str) -> dict:
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sharpe = (r.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0
    downside = r[r < 0].std() * np.sqrt(TRADING_DAYS)
    sortino = (r.mean() * TRADING_DAYS - RF) / downside if downside > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    return {
        "label": label, "start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
        "CAGR%": round(cagr * 100, 2), "vol%": round(vol * 100, 2),
        "Sharpe": round(sharpe, 2), "Sortino": round(sortino, 2),
        "maxDD%": round(dd * 100, 2), "totalRet%": round((eq.iloc[-1] / eq.iloc[0] - 1) * 100, 2),
    }


def spy_bench(bars, calendar, capital, label) -> dict:
    spy = bars["SPY.NYSE"]
    px = spy.loc[calendar[0]:calendar[-1], "close"]
    return metrics((px / px.iloc[0]) * capital, label)


def report(bars, cal, capital, tag):
    eq = backtest(bars, cal, capital)
    eq = eq.reindex(cal).dropna()
    print(f"\n=== Sleeve stack [{tag}] ===")
    for k, v in metrics(eq, tag).items():
        print(f"  {k:10s}: {v}")
    print(f"--- SPY buy&hold [{tag}] ---")
    for k, v in spy_bench(bars, cal, capital, "SPY").items():
        print(f"  {k:10s}: {v}")
    return eq


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2007-01-01")
    p.add_argument("--oos-start", default="2018-01-01")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    print(f"Fetching {len(UNIVERSE)} ETFs from yfinance (warmup-padded)...")
    bars = fetch(args.start)
    print(f"  loaded {len(bars)}/{len(UNIVERSE)}: {sorted(bars)}")
    if "SPY.NYSE" not in bars:
        print("ERROR: SPY missing")
        return

    all_dates = sorted(set().union(*[set(df.index) for df in bars.values()]))
    full = pd.DatetimeIndex([d for d in all_dates if d >= pd.Timestamp(args.start)])
    oos = pd.DatetimeIndex([d for d in full if d >= pd.Timestamp(args.oos_start)])

    report(bars, full, args.capital, f"FULL {args.start[:4]}+")
    report(bars, oos, args.capital, f"OOS {args.oos_start[:4]}+")

    print("\n--- Caveats still present ---")
    print("  * ETF sector-rotation only; sector composition itself shifts over time.")
    print("  * Params are literature defaults (252/21, 200d SMA) — not tuned here, but")
    print("    they ARE the values the authors converged on across many prior studies.")
    print("  * Quality + sentiment + IV disabled (look-ahead/none-historical). Live system")
    print("    re-enables quality on point-in-time data, which this cannot validate.")


if __name__ == "__main__":
    main()
