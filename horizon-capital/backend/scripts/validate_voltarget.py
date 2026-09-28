# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-3F5C24D6C9C9
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Vol-targeting overlay — the highest-evidence return lever.

Finding from validate_sleeves_oos / validate_breadth: the engine runs at ~10-15%
vol vs SPY's ~20% at similar return. That vol headroom is unused return. Vol-
targeting scales gross exposure inversely to the strategy's own recent realized
vol (Moreira-Muir, "Volatility-Managed Portfolios", JF 2017), levering up when
calm and cutting when stormy. Same signals, more of them when it's safe to.

This backtest allows margin (gross up to MAX_LEV) and charges a realistic
financing rate on the borrowed balance, so the levered numbers are net of the
cost of leverage — not a free lunch.

HONESTY: the universe is current large-caps (survivorship bias), so absolute
levels are inflated, AND leverage amplifies that inflation. The PRINCIPLE is
sound and literature-backed; the magnitude needs the point-in-time universe to
trust. Read the unlevered-vs-levered DELTA, not the level.

Usage:
    python -m scripts.validate_voltarget --start 2012-01-01 --oos-start 2019-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.quant.multi_signal import score_universe, select_for_llm  # noqa: E402
from scripts.validate_breadth import _mtm, fetch  # noqa: E402

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
REBAL = 5
K = 25
MIN_CONVICTION = 0.5
VOL_WIN = 63           # trailing window for realized-vol estimate
MAX_LEV = 2.0          # leverage cap
MARGIN_RATE = 0.06     # annual financing on borrowed cash
TRADING_DAYS = 252
RF = 0.04


def backtest_vt(closes, opens, calendar, capital, target_vol):
    """Top-K breadth backtest with optional vol-targeting (target_vol=None -> 1x)."""
    uni = closes[[c for c in closes.columns if c != "SPY"]]
    cash = capital
    shares: dict[str, float] = {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}
    ret_hist: list[float] = []
    prev_nav = None

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                for s in set(list(shares) + list(pending)):
                    if s not in opens or date not in opens[s].index:
                        continue
                    px = float(opens[s].loc[date])
                    if px <= 0:
                        continue
                    tgt = nav_open * pending.get(s, 0.0) / px
                    delta = tgt - shares.get(s, 0.0)
                    if abs(delta * px) < nav_open * 0.002:
                        continue
                    buy = delta > 0
                    qty = abs(delta)
                    ex = px * (1 + SLIPPAGE_BPS / 1e4) if buy else px * (1 - SLIPPAGE_BPS / 1e4)
                    comm = qty * ex * COMMISSION_BPS / 1e4
                    # Margin allowed — vol-target controls gross via the weights.
                    if buy:
                        cash -= qty * ex + comm
                        shares[s] = shares.get(s, 0.0) + qty
                    else:
                        cash += qty * ex - comm
                        shares[s] = shares.get(s, 0.0) - qty
            pending = None

        nav = _mtm(closes, shares, date, cash)
        # Financing cost on any borrowed (negative) cash balance.
        if cash < 0:
            fin = -cash * MARGIN_RATE / TRADING_DAYS
            cash -= fin
            nav -= fin
        equity[date] = nav
        if prev_nav and prev_nav > 0:
            ret_hist.append(nav / prev_nav - 1)
        prev_nav = nav

        if i % REBAL == 0 and i + 1 < len(calendar):
            mkt = closes["SPY"] if "SPY" in closes.columns else None
            cands = score_universe(uni, date, market=mkt)
            picks = select_for_llm(cands, k=K, min_conviction=MIN_CONVICTION)
            lev = 1.0
            if target_vol and len(ret_hist) >= VOL_WIN:
                rv = float(np.std(ret_hist[-VOL_WIN:]) * np.sqrt(TRADING_DAYS))
                if rv > 0:
                    lev = float(np.clip(target_vol / rv, 0.5, MAX_LEV))
            if picks:
                w = lev / len(picks)
                pending = {c.symbol: w for c in picks}
            else:
                pending = {}
    return pd.Series(equity)


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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--oos-start", default="2019-01-01")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    print("Fetching universe...")
    closes, opens = fetch()
    spy_dates = closes["SPY"].dropna().index
    full = spy_dates[spy_dates >= pd.Timestamp(args.start)]
    oos = full[full >= pd.Timestamp(args.oos_start)]

    for tag, cal in [(f"FULL {args.start[:4]}+", full), (f"OOS {args.oos_start[:4]}+", oos)]:
        print(f"\n================ {tag} ================")
        rows = [
            metrics(backtest_vt(closes, opens, cal, args.capital, None).reindex(cal), "unlevered"),
            metrics(backtest_vt(closes, opens, cal, args.capital, 0.15).reindex(cal), "voltgt 15%"),
            metrics(backtest_vt(closes, opens, cal, args.capital, 0.20).reindex(cal), "voltgt 20%"),
        ]
        spx = closes["SPY"].loc[cal[0]:cal[-1]]
        rows.append(metrics((spx / spx.iloc[0]) * args.capital, "SPY"))
        print(f"{'variant':12s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s}")
        for m in rows:
            print(f"{m['label']:12s} {m['CAGR%']:>7} {m['vol%']:>6} "
                  f"{m['Sharpe']:>7} {m['maxDD%']:>7}")

    print("\nRead the DELTA (unlevered -> voltgt), not the level (survivorship-inflated).")
    print("Financing charged at 6%/yr on borrowed balance; leverage capped 2x.")


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 3F5C24D6C9C9 - verify with scripts/authorship.py verify
