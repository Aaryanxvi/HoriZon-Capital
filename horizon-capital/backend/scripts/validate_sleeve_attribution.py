"""Per-sleeve attribution of the validated live 4-sleeve mix.

MEASUREMENT, not tuning. Adapted from validate_momrank_topn.py (same data,
same params, same fill model) — nothing about the sleeve config changes; this
just runs the live mix under different sleeve-weight vectors to attribute
performance. No config change is recommended by this script; even a "drag"
verdict does not ship.

Runs the REAL sleeve classes through a t+1-open, cost-charged replay under 11
arms, all sharing ONE fetch_batch call (fetch ordering preserved exactly as in
validate_momrank_topn.py: single full-universe 10y fetch BEFORE any run()):

  1.  Full mix        breadth .40 / research .30 / trend .20 / momrank .10
                      (reference — must reproduce ~0.67 within +/-0.02 or STOP)
  2-5 Standalone      each sleeve at weight 1.0
  6-9 Leave-one-out   full mix minus one sleeve, remaining weights renormalized
                      proportionally (e.g. minus momrank -> .444/.333/.222)
  10  SPY             buy-hold, same window
  11  Correlation     4x4 Pearson matrix on the 4 standalone daily returns

momentum_rank._TOP_N is pinned to 3 (the live/validated top-3, the KEEP verdict
from the gate run) for every arm.

PRE-REGISTERED interpretation rules (decided before running):
  * DRAGS   if LOO-mix Sharpe >= full-mix Sharpe + 0.03  (removing it helps)
  * CARRIES if LOO-mix Sharpe <= full-mix Sharpe - 0.05  (removing it hurts)
  * else NEUTRAL. A low-standalone-Sharpe sleeve that CARRIES is flagged as a
    diversifier where the correlation matrix supports it.

Usage:
    python scripts/validate_sleeve_attribution.py --start 2018-01-01 --end 2024-12-31
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
# — "NEW" in validate_fix_ab.py's CONFIGS. Held fixed for every arm.
LIVE_CFG = {"cap": 0.20, "k": 25, "conv": 0.5, "hist": None, "universe": "pit"}

# The validated live sleeve weights (from strategy_agent.py).
LIVE_WEIGHTS = {
    "breadth_alpha": 0.40,
    "research_stack": 0.30,
    "trend_filter": 0.20,
    "momentum_rank": 0.10,
}


def _base(sym: str) -> str:
    return sym.split(".")[0] if "." in sym else sym


def _new_sleeve(name: str):
    """Construct one sleeve by name, quality tilt stubbed for research_stack
    (its CURRENT-snapshot yfinance fundamentals are look-ahead in a backtest —
    same stub as validate_fix_ab / validate_momrank_topn)."""
    if name == "breadth_alpha":
        return BreadthAlphaSleeve()
    if name == "research_stack":
        rs = ResearchStackSleeve()
        rs._get_quality = lambda symbols, as_of: {s: 0.0 for s in symbols}  # type: ignore
        return rs
    if name == "trend_filter":
        return TrendFilterSleeve()
    if name == "momentum_rank":
        return MomentumRankSleeve()
    raise ValueError(f"unknown sleeve {name!r}")


def _make_sleeves(weights: dict[str, float]) -> list:
    """Build the sleeves named in `weights`, each with its target_weight set.

    Only sleeves with weight > 0 are constructed and run. This one function
    covers every arm: full mix, single-sleeve standalone (one entry at 1.0),
    and leave-one-out (three entries, renormalized).
    """
    sleeves = []
    for name, w in weights.items():
        if w <= 0:
            continue
        s = _new_sleeve(name)
        s.target_weight = w
        sleeves.append(s)
    return sleeves


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


def run(cfg: dict, weights: dict[str, float], bars: dict[str, pd.DataFrame],
        closes: pd.DataFrame, opens: pd.DataFrame, calendar: pd.DatetimeIndex,
        capital: float, config_universe: list[str]) -> tuple[pd.Series, float]:
    sleeves = _make_sleeves(weights)
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


def _loo_weights(drop: str) -> dict[str, float]:
    """Full mix minus `drop`, remaining weights renormalized proportionally."""
    kept = {k: v for k, v in LIVE_WEIGHTS.items() if k != drop}
    tot = sum(kept.values())
    return {k: v / tot for k, v in kept.items()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    # Pin momentum_rank to the validated top-3 for every arm.
    momentum_rank._TOP_N = 3

    config_universe = get_universe("config")
    pit = union_members(args.start, args.end)
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), 10y daily...")
    # SINGLE fetch_batch call, before any run(). fetch_batch's per-symbol cache
    # ignores `period`, so this one full-universe 10y fetch must come first.
    bars = asyncio.run(fetch_batch(tickers, period="10y"))
    print(f"Coverage: {len(bars)}/{len(tickers)} (missing = mostly delisted; known gap)")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    win = (closes.index >= pd.Timestamp(args.start)) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]

    def _run(weights):
        return run(LIVE_CFG, weights, bars, closes, opens, cal, args.capital, config_universe)

    rows = []
    standalone_eq: dict[str, pd.Series] = {}

    # 1. Full mix (reference).
    print("\nRunning full-mix (reference) ...")
    eq_full, g_full = _run(LIVE_WEIGHTS)
    rows.append(metrics(eq_full, "full-mix", g_full))
    full_sharpe = rows[-1]["Sharpe"]

    # 2-5. Standalone sleeves at weight 1.0.
    for name in LIVE_WEIGHTS:
        print(f"Running standalone {name} ...")
        eq, g = _run({name: 1.0})
        standalone_eq[name] = eq
        rows.append(metrics(eq, f"solo:{name}", g))

    # 6-9. Leave-one-out mixes (remaining weights renormalized).
    loo_sharpe: dict[str, float] = {}
    for name in LIVE_WEIGHTS:
        w = _loo_weights(name)
        print(f"Running LOO minus {name}  weights={ {k: round(v,3) for k,v in w.items()} } ...")
        eq, g = _run(w)
        m = metrics(eq, f"LOO-{name}", g)
        rows.append(m)
        loo_sharpe[name] = m["Sharpe"]

    # 10. SPY buy-hold.
    spx = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
    rows.append(metrics((spx / spx.iloc[0]) * args.capital, "SPY"))

    # --- Metric table ---------------------------------------------------------
    print(f"\n{'variant':22s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} "
          f"{'maxDD%':>7s} {'avgGross%':>10s}")
    for m in rows:
        print(f"{m['label']:22s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} "
              f"{m['maxDD%']:>7} {m['avgGross%']:>10}")

    # 11. Correlation matrix across the 4 standalone daily returns.
    ret = pd.DataFrame({n: eq.pct_change() for n, eq in standalone_eq.items()}).dropna()
    corr = ret.corr()
    print("\nCorrelation matrix (Pearson, standalone daily returns):")
    print(corr.round(3).to_string())

    # --- Sanity check ---------------------------------------------------------
    print(f"\nSanity: full-mix Sharpe = {full_sharpe} "
          f"(expected ~0.67 +/- 0.02 -> "
          f"{'OK' if abs(full_sharpe - 0.67) <= 0.02 else 'DISCREPANCY'})")

    # --- Pre-registered per-sleeve verdicts ----------------------------------
    print("\nPer-sleeve attribution (pre-registered rules, LOO is decisive):")
    print(f"  full-mix Sharpe = {full_sharpe}")
    for name in LIVE_WEIGHTS:
        loo = loo_sharpe[name]
        delta = round(loo - full_sharpe, 3)  # + means removing it helped
        if loo >= full_sharpe + 0.03:
            v = "DRAGS"
        elif loo <= full_sharpe - 0.05:
            v = "CARRIES"
        else:
            v = "NEUTRAL"
        print(f"  {name:16s} LOO={loo:>5}  d(LOO-full)={delta:+.3f}  -> {v}")

    print("\nCaveats: quality tilt stubbed (look-ahead), delisted prices missing,")
    print("no kill-switch simulation (live-behavior fix, not alpha). MEASUREMENT")
    print("only — no config change recommended, no arm ships from this run.")


def _selfcheck() -> None:
    """Runnable check of the weight logic that this harness depends on
    (renormalization + build), no data/network. `python ... --selfcheck`."""
    # LOO renormalizes to 1.0 and drops the named sleeve.
    w = _loo_weights("momentum_rank")
    assert "momentum_rank" not in w
    assert abs(sum(w.values()) - 1.0) < 1e-9, w
    assert abs(w["breadth_alpha"] - 0.40 / 0.90) < 1e-9, w  # .444...
    assert abs(w["research_stack"] - 0.30 / 0.90) < 1e-9, w
    # Full weights already sum to 1.0.
    assert abs(sum(LIVE_WEIGHTS.values()) - 1.0) < 1e-9
    # Standalone build makes exactly one sleeve at weight 1.0.
    solo = _make_sleeves({"trend_filter": 1.0})
    assert len(solo) == 1 and solo[0].name == "trend_filter"
    assert solo[0].target_weight == 1.0
    # Zero-weight sleeves are dropped.
    assert len(_make_sleeves({"breadth_alpha": 0.0, "trend_filter": 0.5})) == 1
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
