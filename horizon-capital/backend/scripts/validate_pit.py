# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1D9BEA82CE68
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Breadth engine on POINT-IN-TIME S&P 500 membership (the bias fix, free tier).

At each rebalance we rank ONLY the names that were actually in the index on that
date (free PIT membership from app.data_layer.pit_universe), instead of today's
winners. This removes the look-ahead universe selection that inflated every prior
backtest.

HONEST residual gap: yfinance has no prices for names that later delisted, so they
drop out (reported as coverage below). That's why this is a PARTIAL fix — the full
one needs a paid survivorship-free price vendor. But it's a real step: compare the
Sharpe here to the survivorship-biased ~1.0 we kept getting.

Usage:
    python -m scripts.validate_pit --start 2018-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.quant.multi_signal import score_universe, select_for_llm  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
REBAL = 5
K = 25
MIN_CONVICTION = 0.5
GROSS = 0.95
TRADING_DAYS = 252
RF = 0.04


def metrics(eq: pd.Series, label: str) -> dict:
    eq = eq.dropna()
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sh = (r.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    return {"label": label, "CAGR%": round(cagr * 100, 1), "vol%": round(vol * 100, 1),
            "Sharpe": round(sh, 2), "maxDD%": round(dd * 100, 1)}


def run_backtest(closes, opens, calendar, capital):
    cash = capital
    shares: dict[str, float] = {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}
    have = set(closes.columns)

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                for s in set(list(shares) + list(pending)):
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    tgt = nav_open * pending.get(s, 0.0) / px
                    delta = tgt - shares.get(s, 0.0)
                    if abs(delta * px) < nav_open * 0.002:
                        continue
                    buy = delta > 0
                    qty = abs(delta)
                    ex = px * (1 + SLIPPAGE_BPS / 1e4) if buy else px * (1 - SLIPPAGE_BPS / 1e4)
                    comm = qty * ex * COMMISSION_BPS / 1e4
                    if buy:
                        cost = qty * ex + comm
                        if cost > cash:
                            qty = max(0.0, (cash - comm) / ex)
                            if qty <= 0:
                                continue
                            cost = qty * ex + comm
                        cash -= cost
                        shares[s] = shares.get(s, 0.0) + qty
                    else:
                        cash += qty * ex - comm
                        shares[s] = shares.get(s, 0.0) - qty
            pending = None

        equity[date] = _mtm(closes, shares, date, cash)

        if i % REBAL == 0 and i + 1 < len(calendar):
            # Eligible = members on THIS date that we actually have prices for.
            elig = sorted(members_on(date) & have)
            if len(elig) >= 10:
                sub = closes[elig]
                cands = score_universe(sub, date, market=closes.get("SPY"))
                picks = select_for_llm(cands, k=K, min_conviction=MIN_CONVICTION)
                if picks:
                    w = GROSS / len(picks)
                    pending = {c.symbol: w for c in picks}
                else:
                    pending = {}
    return pd.Series(equity)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    members = union_members(args.start, args.end)
    tickers = sorted(members | {"SPY"})
    print(f"PIT union {args.start[:4]}-{args.end[:4]}: {len(members)} historical members")
    print(f"Fetching prices for {len(tickers)} tickers (delisted ones will drop out)...")

    import asyncio
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    have = [t for t in tickers if t in bars]
    coverage = len(have) / len(tickers) * 100
    print(f"Price coverage: {len(have)}/{len(tickers)} ({coverage:.0f}%) — "
          f"the missing {len(tickers)-len(have)} are mostly delisted (the residual gap).")

    closes = pd.DataFrame({t: bars[t]["close"] for t in have}).sort_index()
    opens = pd.DataFrame({t: bars[t]["open"] for t in have}).sort_index()
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]
    if "SPY" not in closes.columns:
        print("ERROR: SPY price missing")
        return

    eq = run_backtest(closes, opens, cal, args.capital).reindex(cal).dropna()
    spx = closes["SPY"].loc[cal[0]:cal[-1]]

    print(f"\n{'variant':14s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s}")
    for m in (metrics(eq, "breadth (PIT)"), metrics((spx / spx.iloc[0]) * args.capital, "SPY")):
        print(f"{m['label']:14s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} {m['maxDD%']:>7}")

    print("\nCompare this Sharpe to the survivorship-biased ~1.0 we kept getting.")
    print("Lower here = the bias was inflating the old number. Still partial:")
    print(f"delisted names ({len(tickers)-len(have)}) lack prices; paid vendor closes that gap.")


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1D9BEA82CE68 - verify with scripts/authorship.py verify
