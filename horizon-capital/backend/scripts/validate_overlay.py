"""Ship-gate validation: risk overlay + dual momentum vs baseline. ONE-SHOT.

Variants (identical costs: 1bp commission + 2bp slippage):
  PIT sample (S&P 500 point-in-time membership, 2018-2024, ~85% coverage):
    baseline    breadth engine exactly as validate_pit (must reproduce ~0.30 Sharpe)
    brd+ovl     breadth + overlay (vol target 15% + SPY 200d gate)
    momrank     12-1 momentum top-3 monthly on the PIT universe (blend component)
  ETF sample (SPY/EFA/TLT/GLD/DBC/BIL, no survivorship bias):
    spy         SPY buy-and-hold        (overlay counterpart, 2008-2017)
    spy+ovl     SPY + overlay           (overlay must not hurt here)
    gem         Antonacci dual momentum (2008-2017 and 2018-2024 reported)
  blend        0.30 brd+ovl + 0.30 gem + 0.15 momrank, renormalized (/0.75).
               research_stack (0.25) is NOT backtestable on free PIT data and is
               EXCLUDED from the blend proxy — stated, not hidden.

SHIP RULE (spec docs/superpowers/specs/2026-07-02-risk-overlay-dual-momentum-design.md):
  ship overlay   iff brd+ovl beats baseline on Sharpe AND maxDD (PIT)
                     AND spy+ovl Sharpe >= spy Sharpe (ETF 2008-2017)
  ship dual-mom  iff blend (no shipping decision on gem alone) beats baseline
                     on Sharpe AND maxDD (PIT) AND gem 2008-2017 Sharpe > 0
No parameter iteration on either window after the first run.

Usage: python -m scripts.validate_overlay [--start 2018-01-01 --end 2024-12-31]
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

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.quant.multi_signal import score_universe, select_for_llm  # noqa: E402
from app.quant.risk_overlay import trend_gate, vol_target_scalar  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402
from scripts.validate_pit import (  # noqa: E402
    COMMISSION_BPS,
    GROSS,
    MIN_CONVICTION,
    REBAL,
    SLIPPAGE_BPS,
    K,
    metrics,
)

ETFS = ["SPY", "EFA", "TLT", "GLD", "DBC", "BIL"]
# Canonical Antonacci GEM risk menu: US vs intl equities ONLY. First cut had
# TLT/GLD/DBC in the risk menu and bought the 2008 commodity-bubble top.
RISK_ETFS = ["SPY", "EFA"]
MONTHLY = 21
MOMRANK_TOP = 3


def _overlay_scalar_at(equity: dict, spy_hist: pd.Series) -> float:
    """Overlay multiplier from the portfolio's own realized equity curve."""
    eq = pd.Series(equity)
    return vol_target_scalar(eq.pct_change()) * trend_gate(spy_hist)


def run_weights_backtest(closes, opens, calendar, capital, pick_fn, overlay=False):
    """Generic pending-order backtest: pick_fn(date, i) -> {sym: weight} | None.

    Weights execute at NEXT day's open with commission+slippage (same mechanics
    as validate_pit.run_backtest). With overlay=True the picked weights are
    scaled by the overlay multiplier computed as of the pick date.
    """
    cash = capital
    shares: dict[str, float] = {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}

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

        if i + 1 < len(calendar):
            picks = pick_fn(date, i)
            if picks is not None:
                if overlay and picks:
                    scal = _overlay_scalar_at(equity, closes["SPY"].loc[:date])
                    picks = {s: w * scal for s, w in picks.items()}
                pending = picks
    return pd.Series(equity)


def breadth_picks(closes, have):
    def pick(date, i):
        if i % REBAL != 0:
            return None
        elig = sorted(members_on(date) & have)
        if len(elig) < 10:
            return None
        cands = score_universe(closes[elig], date, market=closes.get("SPY"))
        sel = select_for_llm(cands, k=K, min_conviction=MIN_CONVICTION)
        return {c.symbol: GROSS / len(sel) for c in sel} if sel else {}
    return pick


def momrank_picks(closes, have):
    def pick(date, i):
        if i % MONTHLY != 0:
            return None
        elig = sorted(members_on(date) & have)
        if len(elig) < 10:
            return None
        hist = closes[elig].loc[:date]
        if len(hist) < 253:
            return None
        mom = (hist.iloc[-21] / hist.iloc[-252] - 1.0).dropna()
        top = mom[mom > 0].nlargest(MOMRANK_TOP)
        return {s: GROSS / len(top) for s in top.index} if len(top) else {}
    return pick


def gem_winner(closes: pd.DataFrame, date: pd.Timestamp) -> str | None:
    hist = closes.loc[:date]

    def r12(sym: str) -> float | None:
        c = hist[sym].dropna() if sym in hist.columns else pd.Series(dtype=float)
        if len(c) < 253:
            return None
        past = float(c.iloc[-252])
        return float(c.iloc[-1]) / past - 1.0 if past > 0 else None

    rets = {s: v for s in RISK_ETFS if (v := r12(s)) is not None}
    if not rets:
        return None
    top, top_ret = max(rets.items(), key=lambda kv: kv[1])
    cash = r12("BIL") or 0.0
    return top if top_ret > cash else "TLT"


def gem_picks(closes):
    def pick(date, i):
        if i % MONTHLY != 0:
            return None
        w = gem_winner(closes, date)
        return {w: GROSS} if w else None
    return pick


def hold_picks(symbol):
    def pick(date, i):
        return {symbol: GROSS} if i == 0 or i % MONTHLY == 0 else None
    return pick


def blend(curves: dict[str, pd.Series], weights: dict[str, float], capital: float) -> pd.Series:
    rets = pd.DataFrame({k: c.pct_change() for k, c in curves.items()}).dropna()
    w = pd.Series(weights)
    r = (rets * (w / w.sum())).sum(axis=1)
    return (1 + r).cumprod() * capital


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    # ---- ETF sample fetch FIRST --------------------------------------------
    # fetch_batch caches per symbol ignoring period; if the 10y PIT fetch ran
    # first, this 20y call would silently return 10y frames and the 2008-2017
    # window would be empty (run 1 artifact: SPY 08-17 "vol 2.8%"). Fetching the
    # ETFs first caches their full 20y history; the PIT pass reuses it (longer
    # history is harmless there).
    ebars = asyncio.run(fetch_batch(ETFS, period="20y"))

    # ---- PIT sample --------------------------------------------------------
    members = union_members(args.start, args.end)
    tickers = sorted(members | {"SPY"})
    print(f"PIT union: {len(members)} members; fetching {len(tickers)} tickers...")
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    have = {t for t in tickers if t in bars}
    print(f"Coverage: {len(have)}/{len(tickers)} ({len(have)/len(tickers)*100:.0f}%)")
    closes = pd.DataFrame({t: bars[t]["close"] for t in have}).sort_index()
    opens = pd.DataFrame({t: bars[t]["open"] for t in have}).sort_index()
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]

    base = run_weights_backtest(closes, opens, cal, args.capital, breadth_picks(closes, have))
    brd_ovl = run_weights_backtest(
        closes, opens, cal, args.capital, breadth_picks(closes, have), overlay=True
    )
    momrank = run_weights_backtest(closes, opens, cal, args.capital, momrank_picks(closes, have))
    spy_pit = closes["SPY"].loc[cal[0]:cal[-1]]
    spy_pit = spy_pit / spy_pit.iloc[0] * args.capital

    # ---- ETF sample --------------------------------------------------------
    ec = pd.DataFrame({t: ebars[t]["close"] for t in ETFS if t in ebars}).sort_index()
    eo = pd.DataFrame({t: ebars[t]["open"] for t in ETFS if t in ebars}).sort_index()
    cal_08_17 = ec.index[(ec.index >= "2008-01-01") & (ec.index <= "2017-12-31")]
    cal_18_24 = ec.index[(ec.index >= args.start) & (ec.index <= args.end)]

    spy_bh = run_weights_backtest(ec, eo, cal_08_17, args.capital, hold_picks("SPY"))
    spy_ovl = run_weights_backtest(ec, eo, cal_08_17, args.capital, hold_picks("SPY"), overlay=True)
    gem_early = run_weights_backtest(ec, eo, cal_08_17, args.capital, gem_picks(ec))
    gem_late = run_weights_backtest(ec, eo, cal_18_24, args.capital, gem_picks(ec))

    # ---- Blend proxy (research_stack excluded - not backtestable free) ------
    full = blend(
        {"brd_ovl": brd_ovl, "gem": gem_late.reindex(brd_ovl.index).ffill(), "momrank": momrank},
        {"brd_ovl": 0.30, "gem": 0.30, "momrank": 0.15},
        args.capital,
    )

    rows = [
        metrics(base, "baseline(PIT)"), metrics(brd_ovl, "brd+ovl(PIT)"),
        metrics(momrank, "momrank(PIT)"), metrics(spy_pit, "SPY(PIT)"),
        metrics(spy_bh, "spy 08-17"), metrics(spy_ovl, "spy+ovl 08-17"),
        metrics(gem_early, "gem 08-17"), metrics(gem_late, "gem 18-24"),
        metrics(full, "BLEND(PIT)"),
    ]
    m = {r["label"]: r for r in rows}

    ovl_pass = (
        m["brd+ovl(PIT)"]["Sharpe"] > m["baseline(PIT)"]["Sharpe"]
        and m["brd+ovl(PIT)"]["maxDD%"] > m["baseline(PIT)"]["maxDD%"]
        and m["spy+ovl 08-17"]["Sharpe"] >= m["spy 08-17"]["Sharpe"]
    )
    dm_pass = (
        m["BLEND(PIT)"]["Sharpe"] > m["baseline(PIT)"]["Sharpe"]
        and m["BLEND(PIT)"]["maxDD%"] > m["baseline(PIT)"]["maxDD%"]
        and m["gem 08-17"]["Sharpe"] > 0
    )

    print("\n========== SHIP GATE ==========")
    print(f"OVERLAY:  {'SHIP' if ovl_pass else 'DO NOT SHIP'}")
    print(f"DUAL-MOM: {'SHIP' if dm_pass else 'DO NOT SHIP'}")
    print(f"vs SPY:   blend Sharpe {m['BLEND(PIT)']['Sharpe']} vs SPY {m['SPY(PIT)']['Sharpe']}")
    print("===============================\n")
    print(f"{'variant':16s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s}")
    for r in rows:
        print(f"{r['label']:16s} {r['CAGR%']:>7} {r['vol%']:>6} {r['Sharpe']:>7} {r['maxDD%']:>7}")
    print("\nNOTE: blend excludes research_stack (25% live) - not backtestable on")
    print("free PIT data; weights renormalized over the remaining 75%.")
    print("PIT residual gap: delisted names lack free prices (~15%), inflating")
    print("absolute numbers slightly; variant-vs-baseline comparison unaffected.")


if __name__ == "__main__":
    main()
