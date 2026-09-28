# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-7108991CEB7D
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Does BREADTH lift risk-adjusted return? (Fundamental Law: IR = IC*sqrt(N))

Runs the deterministic multi-signal scorer (app.quant.multi_signal) over a wide
liquid universe and backtests a long-only top-K portfolio, weekly rebalanced,
net of costs, t+1 open fills. Compares narrow (K=5) vs broad (K=25, K=50) vs SPY,
with a strict out-of-sample slice.

The point isn't the absolute number (current-constituent universe => survivorship
bias, noted below). It's the DELTA across K: if broad beats narrow on Sharpe,
breadth is the real lever and it lives in the $0 quant layer — the LLM never sees
more than top-K regardless of universe size.

Usage:
    python -m scripts.validate_breadth --start 2012-01-01 --oos-start 2019-01-01
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

from app.quant.multi_signal import score_universe, select_for_llm  # noqa: E402

# ~90 liquid US large-caps across sectors. CURRENT constituents => survivorship
# bias in absolute terms; the across-K comparison controls for it (same universe).
UNIVERSE = (
    "AAPL MSFT NVDA GOOGL AMZN META TSLA AVGO ORCL CRM ADBE AMD INTC CSCO QCOM "
    "TXN IBM NOW INTU MU AMAT "
    "JPM BAC WFC GS MS C BLK SCHW AXP SPGI CB PGR "
    "UNH LLY JNJ PFE MRK ABBV TMO ABT DHR BMY AMGN GILD CVS ISRG "
    "PG KO PEP WMT COST HD MCD NKE SBUX LOW TGT EL CL MDLZ "
    "CAT BA HON UNP GE LMT RTX DE EMR ETN "
    "XOM CVX COP SLB EOG PSX "
    "DIS NFLX CMCSA T VZ TMUS "
    "LIN NEE DUK SO PLD AMT"
).split()

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
GROSS = 0.95          # long-only deployment (rest cash)
REBAL = 5             # weekly
MIN_CONVICTION = 0.5  # the LLM-gate floor (also filters weak longs in the sim)
TRADING_DAYS = 252
RF = 0.04


def fetch() -> tuple[pd.DataFrame, pd.DataFrame]:
    warmup = "2010-06-01"  # >1y pad before any --start for the 252d lookbacks
    raw = yf.download(" ".join(UNIVERSE + ["SPY"]), start=warmup, progress=False,
                      auto_adjust=True, group_by="ticker")
    closes, opens = {}, {}
    for t in UNIVERSE + ["SPY"]:
        try:
            df = raw[t]
        except KeyError:
            continue
        cl = df["Close"].dropna()
        op = df["Open"].dropna()
        if len(cl) > 300:
            closes[t] = cl
            opens[t] = op
    cdf = pd.DataFrame(closes)
    odf = pd.DataFrame(opens)
    cdf.index = pd.DatetimeIndex(cdf.index).tz_localize(None).normalize()
    odf.index = pd.DatetimeIndex(odf.index).tz_localize(None).normalize()
    return cdf, odf


def _mtm(prices: pd.DataFrame, shares: dict, date, cash: float) -> float:
    """Cash + mark-to-market value of held shares at ``date`` (NaN-safe)."""
    val = cash
    for s, q in shares.items():
        px = prices[s].get(date, np.nan) if s in prices.columns else np.nan
        if not np.isnan(px):
            val += q * px
    return val


def backtest(closes, opens, calendar, k, capital) -> pd.Series:
    universe_cols = [c for c in closes.columns if c != "SPY"]
    uni = closes[universe_cols]
    cash = capital
    shares: dict[str, float] = {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}

    for i, date in enumerate(calendar):
        # Apply pending rebalance at today's open.
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

        # Decide a new target on rebalance days (filled next open).
        if i % REBAL == 0 and i + 1 < len(calendar):
            mkt = closes["SPY"] if "SPY" in closes.columns else None
            cands = score_universe(uni, date, market=mkt)
            picks = select_for_llm(cands, k=k, min_conviction=MIN_CONVICTION)
            if picks:
                w = GROSS / len(picks)
                pending = {c.symbol: w for c in picks}
            else:
                pending = {}  # nothing convincing -> go to cash
    return pd.Series(equity)


def metrics(eq: pd.Series, label: str) -> dict:
    eq = eq.dropna()
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sharpe = (r.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    return {"label": label, "CAGR%": round(cagr * 100, 1), "vol%": round(vol * 100, 1),
            "Sharpe": round(sharpe, 2), "maxDD%": round(dd * 100, 1),
            "totalRet%": round((eq.iloc[-1] / eq.iloc[0] - 1) * 100, 1)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--oos-start", default="2019-01-01")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    print(f"Fetching {len(UNIVERSE)} names + SPY...")
    closes, opens = fetch()
    print(f"  loaded {len(closes.columns)-1} names "
          f"({closes.index[0].date()} -> {closes.index[-1].date()})")

    spy_dates = closes["SPY"].dropna().index
    full = spy_dates[spy_dates >= pd.Timestamp(args.start)]
    oos = full[full >= pd.Timestamp(args.oos_start)]

    for tag, cal in [(f"FULL {args.start[:4]}+", full), (f"OOS {args.oos_start[:4]}+", oos)]:
        print(f"\n================ {tag} ================")
        rows = []
        for k in (5, 25, 50):
            eq = backtest(closes, opens, cal, k, args.capital).reindex(cal).dropna()
            rows.append(metrics(eq, f"top-{k}"))
        spx = closes["SPY"].loc[cal[0]:cal[-1]]
        rows.append(metrics((spx / spx.iloc[0]) * args.capital, "SPY"))
        print(f"{'strategy':10s} {'CAGR%':>7s} {'vol%':>6s} "
              f"{'Sharpe':>7s} {'maxDD%':>7s} {'totRet%':>8s}")
        for m in rows:
            print(f"{m['label']:10s} {m['CAGR%']:>7} {m['vol%']:>6} "
                  f"{m['Sharpe']:>7} {m['maxDD%']:>7} {m['totalRet%']:>8}")

    print("\nRead: if Sharpe rises from top-5 -> top-25 -> top-50, breadth is the lever.")
    print("Caveat: current-constituent universe = survivorship bias in ABSOLUTE numbers;")
    print("the across-K delta is the honest signal. Quant layer scored all 90 names for $0;")
    print("the LLM gate (select_for_llm) only ever emits <=K names => cost O(K), not O(universe).")


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 7108991CEB7D - verify with scripts/authorship.py verify
