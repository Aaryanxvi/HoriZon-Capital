"""A/B gate test: MomentumRankSleeve _TOP_N=3 (baseline) vs _TOP_N=10 (variant).

Runs the REAL sleeve classes (breadth_alpha, research_stack, trend_filter,
momentum_rank at the live 40/30/20/10 weights) through a t+1-open, cost-charged
replay, twice — once per _TOP_N arm — using the same "NEW" (PIT universe,
K=25/conviction 0.5/full history/20% cap) config from validate_fix_ab.py that
matches the validated live mix. Nothing else about the sleeve or config
changes between arms; only `momentum_rank._TOP_N` is monkeypatched (it's read
as a module global at compute()-call time, not baked in at import/construction,
so this is the smallest-diff way to parameterize it without touching the
sleeve source).

For each arm this computes:
  * full 4-sleeve mix equity + metrics
  * MomentumRankSleeve STANDALONE equity (weight=1.0, nothing else) + metrics
SPY buy-hold is computed once (same window, doesn't vary by arm).

Fetch ordering is preserved exactly as in validate_fix_ab.py: one single
fetch_batch call for the full PIT-union+anchors ticker set at period="10y",
BEFORE any run() calls — the per-symbol cache in fetch_batch ignores the
requested period, so fetching a shorter/different period for any symbol
first would poison the cache for that symbol on later, longer-period calls.
This script issues exactly the same one fetch_batch call and nothing else.

Usage:
    python scripts/validate_momrank_topn.py --start 2018-01-01 --end 2024-12-31
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

from app.agents.front_office.strategy.sleeves import breadth_alpha  # noqa: E402
from app.agents.front_office.strategy.sleeves import momentum_rank  # noqa: E402
from app.agents.front_office.strategy.sleeves.breadth_alpha import BreadthAlphaSleeve  # noqa: E402
from app.agents.front_office.strategy.sleeves.momentum_rank import MomentumRankSleeve  # noqa: E402
from app.agents.front_office.strategy.sleeves.research_stack import (  # noqa: E402
    ResearchStackSleeve,
)
from app.agents.front_office.strategy.sleeves.trend_filter import TrendFilterSleeve  # noqa: E402
from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS, get_universe  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
TRADING_DAYS = 252
RF = 0.04
MIN_TRADE_NAV = 0.002  # skip rebalances below 20 bps of NAV (mirrors live 50bps-ish)

# The validated live config (PIT universe, K=25/conviction 0.5/full history/20% cap)
# — "NEW" in validate_fix_ab.py's CONFIGS. Held fixed; only _TOP_N varies by arm.
LIVE_CFG = {"cap": 0.20, "k": 25, "conv": 0.5, "hist": None, "universe": "pit"}

# Pre-registered gate test arms.
TOP_N_ARMS = {"top-3": 3, "top-10": 10}


def _base(sym: str) -> str:
    return sym.split(".")[0] if "." in sym else sym


def _make_sleeves(standalone: bool) -> list:
    """The live mix from strategy_agent.py, quality tilt stubbed (look-ahead).

    standalone=True returns only MomentumRankSleeve at weight 1.0.
    """
    if standalone:
        m = MomentumRankSleeve()
        m.target_weight = 1.0
        return [m]
    rs = ResearchStackSleeve()
    rs._get_quality = lambda symbols, as_of: {s: 0.0 for s in symbols}  # type: ignore
    pairs = [(BreadthAlphaSleeve(), 0.40), (rs, 0.30),
             (TrendFilterSleeve(), 0.20), (MomentumRankSleeve(), 0.10)]
    for s, w in pairs:
        s.target_weight = w
    return [s for s, _ in pairs]


def _targets(sleeves, cache, bars_view, as_of, i, cap) -> dict[str, float]:
    combined: dict[str, float] = {}
    for sleeve in sleeves:
        if i % sleeve.rebalance_days == 0 or sleeve.name not in cache:
            try:
                cache[sleeve.name] = sleeve.compute(bars_view, as_of)
            except Exception:
                pass  # keep serving cache (mirrors patched live behavior)
        for sig in cache.get(sleeve.name, []):
            share = sig.target_weight * sleeve.target_weight
            combined[sig.symbol] = combined.get(sig.symbol, 0.0) + share
    # Per-name cap, clipped weight DISCARDED — exactly what live sizing does.
    return {s: min(w, cap) for s, w in combined.items() if w > 0}


def run(cfg: dict, bars: dict[str, pd.DataFrame], closes: pd.DataFrame,
        opens: pd.DataFrame, calendar: pd.DatetimeIndex, capital: float,
        config_universe: list[str], standalone: bool = False) -> tuple[pd.Series, float]:
    sleeves = _make_sleeves(standalone)
    cache: dict[str, list] = {}
    cash, shares = capital, {}
    pending: dict[str, float] | None = None
    equity: dict[pd.Timestamp, float] = {}
    gross_samples: list[float] = []

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                # Sells first so proceeds fund the buys (patched live ordering).
                deltas = []
                for s in set(list(shares) + list(pending)):
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    tgt = nav_open * pending.get(s, 0.0) / px
                    d = tgt - shares.get(s, 0.0)
                    if abs(d * px) >= nav_open * MIN_TRADE_NAV:
                        deltas.append((s, px, d))
                for s, px, d in sorted(deltas, key=lambda t: t[2]):
                    buy, qty = d > 0, abs(d)
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

        nav = _mtm(closes, shares, date, cash)
        equity[date] = nav
        if not np.isnan(nav) and nav > 0:
            gross_samples.append((nav - cash) / nav)

        if i % 5 == 0 and i + 1 < len(calendar):
            # Universe view for this decision date.
            if cfg["universe"] == "pit":
                elig = members_on(date)
                view = {s: df for s, df in bars.items()
                        if s in _ANCHORS or _base(s) in elig}
            else:
                view = {s: df for s, df in bars.items() if s in config_universe}
            # Truncate history to emulate the old 400d fetch, if configured.
            h = cfg["hist"]
            view = {s: df.loc[:date].tail(h) if h else df.loc[:date]
                    for s, df in view.items()}
            view = {s: df for s, df in view.items() if len(df) > 2}
            breadth_alpha._TOP_K = cfg["k"]
            breadth_alpha._MIN_CONVICTION = cfg["conv"]
            pending = _targets(sleeves, cache, view, date, i // 5 * 5, cfg["cap"])

    avg_gross = float(np.mean(gross_samples)) if gross_samples else 0.0
    return pd.Series(equity).dropna(), avg_gross


def metrics(eq: pd.Series, label: str, gross: float | None = None) -> dict:
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sh = (r.mean() * TRADING_DAYS - RF) / vol if vol > 0 else 0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    return {"label": label, "CAGR%": round(cagr * 100, 1), "vol%": round(vol * 100, 1),
            "Sharpe": round(sh, 2), "maxDD%": round(dd * 100, 1),
            "avgGross%": round(gross * 100, 1) if gross is not None else "-"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    config_universe = get_universe("config")
    pit = union_members(args.start, args.end)
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), 10y daily...")
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    print(f"Coverage: {len(bars)}/{len(tickers)} (missing = mostly delisted; known gap)")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]

    rows = []
    for arm_name, top_n in TOP_N_ARMS.items():
        momentum_rank._TOP_N = top_n
        print(f"\n=== Arm {arm_name} (_TOP_N={momentum_rank._TOP_N}) ===")

        print(f"Running {arm_name} full-mix ...")
        eq_mix, gross_mix = run(LIVE_CFG, bars, closes, opens, cal, args.capital,
                                 config_universe, standalone=False)
        rows.append(metrics(eq_mix, f"{arm_name}-mix", gross_mix))

        print(f"Running {arm_name} momrank-standalone ...")
        eq_solo, gross_solo = run(LIVE_CFG, bars, closes, opens, cal, args.capital,
                                   config_universe, standalone=True)
        rows.append(metrics(eq_solo, f"{arm_name}-solo", gross_solo))

    spx = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
    rows.append(metrics((spx / spx.iloc[0]) * args.capital, "SPY"))

    print(f"\n{'variant':14s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} "
          f"{'maxDD%':>7s} {'avgGross%':>10s}")
    for m in rows:
        print(f"{m['label']:14s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} "
              f"{m['maxDD%']:>7} {m['avgGross%']:>10}")

    by_label = {m["label"]: m for m in rows}
    sh3 = by_label["top-3-mix"]["Sharpe"]
    sh10 = by_label["top-10-mix"]["Sharpe"]
    dd10_solo = by_label["top-10-solo"]["maxDD%"]
    g1 = sh10 >= sh3 - 0.02
    g2 = dd10_solo > -49.0
    print(f"\nG1 (full-mix Sharpe top-10 >= top-3 - 0.02): {sh10} >= {sh3} - 0.02 "
          f"({sh3 - 0.02:.2f}) -> {'PASS' if g1 else 'FAIL'}")
    print(f"G2 (momrank-solo maxDD top-10 > -49%): {dd10_solo} > -49.0 -> "
          f"{'PASS' if g2 else 'FAIL'}")
    verdict = "SHIP _TOP_N=10" if (g1 and g2) else "KEEP _TOP_N=3"
    print(f"\nVerdict: {verdict}")
    print("\nCaveats: quality tilt stubbed (look-ahead), delisted prices missing,")
    print("no kill-switch simulation (that fix is about live behavior, not alpha).")


if __name__ == "__main__":
    main()
