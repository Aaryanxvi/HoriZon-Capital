# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-9BFD31303B46
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Demo v2 — research-backed multi-sleeve backtest with full audit log.

Composition (every choice tied to a published paper):

  1. Faber 200-day SMA trend regime gate         (Faber 2007, "TAA")
  2. Time-series momentum (TSMOM) on each name   (Moskowitz, Ooi & Pedersen 2012)
  3. Cross-sectional momentum 12-1               (Jegadeesh & Titman 1993)
  4. Volatility targeting overlay @ 15% annual   (Hurst, Ooi & Pedersen 2017)
  5. Equal-vol weighting across selected names   (Asness, Frazzini, Pedersen 2014)

Universe:
  SPY, QQQ + 8 large-cap US single names. Liquid enough for $100k notional.

Output:
  demo_v2_audit.csv     — every signal & decision per bar
  demo_v2_trades.csv    — every executed trade with reasoning chain
  demo_v2_equity.csv    — daily NAV
  demo_v2_summary.txt   — final metrics with benchmark comparisons

CLI:
  python scripts/demo_backtest_v2_research.py            # default 2024
  python scripts/demo_backtest_v2_research.py 2019 2024  # multi-year
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# -------------------- Config --------------------
UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM"]
INITIAL_CAPITAL = 100_000.0
COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
TARGET_ANNUAL_VOL = 0.15           # 15% target portfolio vol
MAX_GROSS_LEVERAGE = 1.5            # cap leverage
SMA_WINDOW = 200                    # Faber regime
TSMOM_LOOKBACK = 252                # 12 months
TSMOM_SKIP = 21                     # skip last month
VOL_WINDOW = 60                     # 60d realised vol for sizing
TOP_N = 5                           # hold top-N momentum names
REBALANCE_EVERY = 5                 # weekly rebalance

# -------------------- Data --------------------

def fetch_universe(start: str, end: str) -> dict[str, pd.DataFrame]:
    print(f"[data] fetching {len(UNIVERSE)} symbols {start}->{end}")
    raw = yf.download(
        " ".join(UNIVERSE), start=start, end=end,
        progress=False, auto_adjust=True, group_by="ticker",
    )
    out: dict[str, pd.DataFrame] = {}
    for sym in UNIVERSE:
        try:
            df = raw[sym].dropna()
        except KeyError:
            continue
        df.columns = [c.lower() for c in df.columns]
        if len(df) > 50:
            out[sym] = df[["open", "high", "low", "close", "volume"]]
    print(f"[data] {len(out)} symbols loaded, "
          f"{min(len(d) for d in out.values())}-{max(len(d) for d in out.values())} bars")
    return out


def fetch_history_for_warmup(start: str, end: str) -> dict[str, pd.DataFrame]:
    """Fetch with extra leading history so signals are usable from day 1."""
    warmup_start = (pd.Timestamp(start) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    return fetch_universe(warmup_start, end)


# -------------------- Signals --------------------

def faber_regime_on(spy_close: pd.Series) -> bool:
    """Faber 2007: long if price > 200d SMA, else cash."""
    if len(spy_close) < SMA_WINDOW + 1:
        return False
    sma = spy_close.rolling(SMA_WINDOW).mean().iloc[-1]
    return bool(spy_close.iloc[-1] > sma)


def tsmom_score(close: pd.Series) -> float | None:
    """Moskowitz et al 2012: sign of 12-1 month return."""
    if len(close) < TSMOM_LOOKBACK + 1:
        return None
    past = close.iloc[-TSMOM_LOOKBACK]
    recent = close.iloc[-TSMOM_SKIP] if TSMOM_SKIP > 0 else close.iloc[-1]
    if past <= 0:
        return None
    return float((recent - past) / past)


def realised_vol(close: pd.Series, window: int = VOL_WINDOW) -> float | None:
    rets = close.pct_change().dropna()
    if len(rets) < window:
        return None
    return float(rets.tail(window).std() * math.sqrt(252))


# -------------------- Portfolio sizing --------------------

def compute_target_weights(
    bars: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
) -> tuple[dict[str, float], list[dict]]:
    """Return (weights_by_symbol, audit_rows)."""
    audit_rows: list[dict] = []

    spy = bars["SPY"].loc[:as_of]
    regime = faber_regime_on(spy["close"])
    audit_rows.append({
        "date": str(as_of.date()), "agent": "faber_regime", "symbol": "SPY",
        "signal": 1 if regime else 0, "strength": 1.0 if regime else 0.0,
        "reason": f"SPY {'>' if regime else '<='} 200d SMA",
    })

    if not regime:
        # Cash regime — Faber says go flat
        return {s: 0.0 for s in bars}, audit_rows

    # Score every name with TSMOM
    scores: dict[str, float] = {}
    vols: dict[str, float] = {}
    for sym, df in bars.items():
        hist = df.loc[:as_of]
        score = tsmom_score(hist["close"])
        vol = realised_vol(hist["close"])
        if score is None or vol is None or vol <= 0:
            continue
        scores[sym] = score
        vols[sym] = vol
        audit_rows.append({
            "date": str(as_of.date()), "agent": "tsmom", "symbol": sym,
            "signal": 1 if score > 0 else -1,
            "strength": min(abs(score), 1.0),
            "reason": f"12-1 ret {score*100:+.1f}%, 60d vol {vol*100:.1f}%",
        })

    # Cross-sectional rank: top-N positive momentum
    positive = {s: r for s, r in scores.items() if r > 0}
    if not positive:
        return {s: 0.0 for s in bars}, audit_rows
    ranked = sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
    winners = [s for s, _ in ranked[:TOP_N]]

    # Equal-vol weighting (AFP 2014): w_i ∝ 1/vol_i
    inv_vol = {s: 1.0 / vols[s] for s in winners}
    s_inv = sum(inv_vol.values())
    raw_weights = {s: inv_vol[s] / s_inv for s in winners}

    # Vol-target overlay (Hurst et al 2017): scale book to target vol
    # Estimate portfolio vol (assume ~0.5 avg corr → conservative)
    weighted_vol = sum(raw_weights[s] * vols[s] for s in winners)
    avg_corr = 0.5
    n = len(winners)
    port_vol = math.sqrt(
        weighted_vol**2 * (1/n + (n-1)/n * avg_corr)
    ) if n > 0 else weighted_vol
    scale = TARGET_ANNUAL_VOL / port_vol if port_vol > 0 else 1.0
    scale = min(scale, MAX_GROSS_LEVERAGE)

    final = {s: raw_weights[s] * scale for s in winners}
    # Cap total gross leverage
    gross = sum(final.values())
    if gross > MAX_GROSS_LEVERAGE:
        final = {s: w * MAX_GROSS_LEVERAGE / gross for s, w in final.items()}

    audit_rows.append({
        "date": str(as_of.date()), "agent": "vol_target", "symbol": "PORTFOLIO",
        "signal": 1, "strength": round(scale, 3),
        "reason": f"port_vol={port_vol*100:.1f}%, target=15%, scale={scale:.2f}",
    })

    out = {s: 0.0 for s in bars}
    for s, w in final.items():
        out[s] = w
    return out, audit_rows


# -------------------- Backtest loop --------------------

def run(start: str, end: str, tag: str = "v2") -> dict:
    bars = fetch_history_for_warmup(start, end)

    # Build trading calendar from SPY
    spy_idx = bars["SPY"].index
    trading_dates = spy_idx[(spy_idx >= pd.Timestamp(start, tz=spy_idx.tz)) &
                            (spy_idx <= pd.Timestamp(end, tz=spy_idx.tz))]

    cash = INITIAL_CAPITAL
    positions: dict[str, float] = {s: 0.0 for s in bars}
    avg_entry: dict[str, float] = {s: 0.0 for s in bars}
    equity_curve: list[tuple[str, float]] = []

    audit_all: list[dict] = []
    trades: list[dict] = []
    pending_targets: dict[str, float] | None = None

    days_since_rebalance = REBALANCE_EVERY  # force first rebalance

    for i, dt in enumerate(trading_dates):
        # Mark NAV at close
        nav_at_close = cash
        for sym, qty in positions.items():
            if qty == 0: continue
            try:
                price = float(bars[sym].loc[dt, "close"])
            except KeyError:
                continue
            nav_at_close += qty * price

        # 1. Execute pending targets at THIS bar's open
        if pending_targets is not None:
            for sym, target_w in pending_targets.items():
                df = bars[sym]
                if dt not in df.index: continue
                open_p = float(df.loc[dt, "open"])
                target_notional = nav_at_close * target_w
                target_qty = target_notional / open_p if open_p > 0 else 0
                delta_qty = target_qty - positions[sym]
                if abs(delta_qty * open_p) < nav_at_close * 0.005:
                    continue  # ignore tiny rebalances <0.5% NAV
                side = "BUY" if delta_qty > 0 else "SELL"
                slip = 1.0 + (SLIPPAGE_BPS / 1e4) * (1 if side == "BUY" else -1)
                fill_p = open_p * slip
                qty_abs = abs(delta_qty)
                notional = qty_abs * fill_p
                comm = notional * COMMISSION_BPS / 1e4
                pnl = 0.0
                if side == "BUY":
                    cost = notional + comm
                    if cost > cash:
                        # scale down to available cash
                        qty_abs = max(0, (cash - comm) / fill_p)
                        if qty_abs <= 0: continue
                        notional = qty_abs * fill_p
                        comm = notional * COMMISSION_BPS / 1e4
                    new_total = positions[sym] + qty_abs
                    if new_total > 0:
                        avg_entry[sym] = (
                            (avg_entry[sym] * positions[sym] + fill_p * qty_abs) / new_total
                        )
                    positions[sym] = new_total
                    cash -= (notional + comm)
                else:
                    qty_abs = min(qty_abs, positions[sym])
                    if qty_abs <= 0: continue
                    pnl = (fill_p - avg_entry[sym]) * qty_abs
                    proceeds = qty_abs * fill_p - comm
                    positions[sym] -= qty_abs
                    cash += proceeds
                    if positions[sym] <= 1e-6:
                        positions[sym] = 0.0; avg_entry[sym] = 0.0

                trades.append({
                    "date": str(dt.date()), "symbol": sym, "side": side,
                    "qty": round(qty_abs, 4), "fill_price": round(fill_p, 4),
                    "target_weight": round(target_w, 4),
                    "pnl": round(pnl, 2), "cash_after": round(cash, 2),
                })
            pending_targets = None

        # 2. Mark NAV at close (after fills)
        nav = cash
        for sym, qty in positions.items():
            if qty == 0: continue
            try:
                price = float(bars[sym].loc[dt, "close"])
            except KeyError:
                continue
            nav += qty * price
        equity_curve.append((str(dt.date()), nav))

        # 3. Decide if rebalance day
        days_since_rebalance += 1
        if days_since_rebalance >= REBALANCE_EVERY:
            targets, audit_rows = compute_target_weights(bars, dt)
            for r in audit_rows:
                r["nav"] = round(nav, 2)
                audit_all.append(r)
            pending_targets = targets
            days_since_rebalance = 0

    # ---- Persist
    audit_path = ROOT / f"demo_{tag}_audit.csv"
    trades_path = ROOT / f"demo_{tag}_trades.csv"
    eq_path = ROOT / f"demo_{tag}_equity.csv"
    summary_path = ROOT / f"demo_{tag}_summary.txt"

    if audit_all:
        with open(audit_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(audit_all[0].keys()))
            w.writeheader(); w.writerows(audit_all)
    if trades:
        with open(trades_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            w.writeheader(); w.writerows(trades)
    with open(eq_path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "nav"]); w.writerows(equity_curve)

    # Metrics
    navs = [v for _, v in equity_curve]
    total_ret = navs[-1] / navs[0] - 1
    days = len(navs)
    years = days / 252
    cagr = (navs[-1] / navs[0]) ** (1/years) - 1 if years > 0 else 0
    rets = [navs[i]/navs[i-1] - 1 for i in range(1, len(navs)) if navs[i-1] > 0]
    mu = statistics.mean(rets); sd = statistics.pstdev(rets)
    sharpe = (mu/sd) * math.sqrt(252) if sd > 0 else 0
    peak = navs[0]; mdd = 0.0
    for v in navs:
        peak = max(peak, v); dd = (v-peak)/peak; mdd = min(mdd, dd)

    spy = bars["SPY"]
    spy_window = spy.loc[trading_dates[0]:trading_dates[-1]]["close"]
    spy_total = float(spy_window.iloc[-1]) / float(spy_window.iloc[0]) - 1
    spy_cagr = (1 + spy_total) ** (1/years) - 1 if years > 0 else 0
    spy_rets = spy_window.pct_change().dropna()
    spy_sharpe = (spy_rets.mean()/spy_rets.std()) * math.sqrt(252) if spy_rets.std() > 0 else 0

    summary = (
        f"DEMO v2 — research-backed multi-sleeve ({start} -> {end})\n"
        f"=========================================================\n"
        f"Universe             : {', '.join(UNIVERSE)}\n"
        f"Sleeves              : Faber regime + TSMOM + 12-1 momo + vol-target\n"
        f"Initial capital      : ${INITIAL_CAPITAL:,.2f}\n"
        f"Final NAV            : ${navs[-1]:,.2f}\n"
        f"Total return         : {total_ret*100:+.2f}%\n"
        f"CAGR                 : {cagr*100:+.2f}%\n"
        f"Sharpe (rf=0)        : {sharpe:.2f}\n"
        f"Max drawdown         : {mdd*100:.2f}%\n"
        f"Trades executed      : {len(trades)}\n"
        f"Audit rows           : {len(audit_all)}\n"
        f"\n--- Benchmark: SPY buy-and-hold ---\n"
        f"SPY total return     : {spy_total*100:+.2f}%\n"
        f"SPY CAGR             : {spy_cagr*100:+.2f}%\n"
        f"SPY Sharpe           : {spy_sharpe:.2f}\n"
        f"Alpha vs SPY         : {(total_ret - spy_total)*100:+.2f}%\n"
    )
    summary_path.write_text(summary)
    print("\n" + summary)
    return {
        "total_ret": total_ret, "cagr": cagr, "sharpe": sharpe, "mdd": mdd,
        "trades": len(trades), "spy_total": spy_total,
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 2:
        run(f"{args[0]}-01-01", f"{args[1]}-12-31", tag=f"v2_{args[0]}_{args[1]}")
    else:
        run("2024-01-01", "2024-12-31", tag="v2")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 9BFD31303B46 - verify with scripts/authorship.py verify
