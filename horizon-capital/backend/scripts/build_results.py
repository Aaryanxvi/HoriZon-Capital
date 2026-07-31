"""Build every performance number in the paper, once, from cached equity curves.

Two problems this solves.

First, correctness. The paper charged a flat 4% risk-free rate on both windows.
The realized 13-week Treasury bill averaged 0.31% over 2008-2017 (below 1% on
88% of days) and 2.33% over 2018-2024. A fixed hurdle is not merely imprecise,
it is biased between arms: the same absolute hurdle is a larger fraction of a
smaller volatility denominator, so it penalises a low-volatility strategy more
than a high-volatility benchmark. Every ratio here is computed against the
realized daily bill rate, applied identically to strategy and benchmark rows.

Second, completeness. Sharpe alone is the metric that says least about a
strategy whose edge is in drawdown rather than in return. The standard
reporting suite -- Sortino, Calmar, capture ratios, terminal wealth -- is
reported in full. Reporting the whole conventional set is not selection;
reporting only the one that happens to flatter would be, which is why every
metric below is emitted for every row whether it helps or not.

Equity curves are computed once and cached, because each is a full replay.

Usage:
    python scripts/build_results.py            # compute + cache + print
    python scripts/build_results.py --rebuild  # force recompute of curves
    python scripts/build_results.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.validate_riskfree import load_riskfree  # noqa: E402

TRADING_DAYS = 252
PAPER_DIR = ROOT.parent / "own research paper"
CURVES = PAPER_DIR / "equity_curves.pkl"

WINDOWS = {
    "selection": ("2018-01-01", "2024-12-31"),
    "holdout": ("2008-01-01", "2017-12-31"),
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _excess(returns: pd.Series, rf_annual: pd.Series) -> pd.Series:
    rf = rf_annual.reindex(returns.index).ffill().bfill()
    daily = (1.0 + rf) ** (1.0 / TRADING_DAYS) - 1.0
    return returns - daily


def metric_suite(equity: pd.Series, rf_annual: pd.Series,
                 bench: pd.Series | None = None) -> dict:
    """Full standard reporting suite for one equity curve."""
    eq = equity.dropna()
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    vol = r.std() * np.sqrt(TRADING_DAYS)
    ex = _excess(r, rf_annual)
    sharpe = ex.mean() * TRADING_DAYS / (ex.std() * np.sqrt(TRADING_DAYS)) \
        if ex.std() > 0 else 0.0

    # Sortino: only downside deviation is penalised, which is the right
    # denominator for a strategy that deliberately sits in cash in bad regimes.
    downside = ex[ex < 0]
    dd_dev = downside.std() * np.sqrt(TRADING_DAYS) if len(downside) > 1 else np.nan
    sortino = ex.mean() * TRADING_DAYS / dd_dev if dd_dev and dd_dev > 0 else np.nan

    dd = ((eq - eq.cummax()) / eq.cummax())
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else np.nan

    # Longest stretch below a prior peak, in trading days -- the number an
    # investor actually experiences.
    under = dd < -1e-9
    longest, cur = 0, 0
    for flag in under:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)

    out = {
        "cagr_pct": cagr * 100,
        "vol_pct": vol * 100,
        "sharpe": float(sharpe),
        "sortino": float(sortino) if sortino == sortino else None,
        "calmar": float(calmar) if calmar == calmar else None,
        "max_dd_pct": max_dd * 100,
        "longest_dd_days": int(longest),
        "total_return_pct": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
        "terminal": float(eq.iloc[-1]),
        "best_year_pct": None,
        "worst_year_pct": None,
        "up_capture": None,
        "down_capture": None,
        "n_days": len(r),
    }

    yearly = eq.resample("YE").last().pct_change().dropna()
    if len(yearly):
        out["best_year_pct"] = float(yearly.max() * 100)
        out["worst_year_pct"] = float(yearly.min() * 100)

    if bench is not None:
        br = bench.dropna().pct_change().dropna()
        joined = pd.concat([r, br], axis=1, keys=["s", "b"]).dropna()
        up, down = joined[joined["b"] > 0], joined[joined["b"] < 0]
        if len(up) > 5 and up["b"].mean() != 0:
            out["up_capture"] = float(up["s"].mean() / up["b"].mean() * 100)
        if len(down) > 5 and down["b"].mean() != 0:
            out["down_capture"] = float(down["s"].mean() / down["b"].mean() * 100)
    return out


# ---------------------------------------------------------------------------
# Equity curves (expensive; cached)
# ---------------------------------------------------------------------------

def build_curves(rebuild: bool) -> dict[str, pd.Series]:
    if CURVES.exists() and not rebuild:
        curves = pd.read_pickle(CURVES)
        print(f"Loaded {len(curves)} cached equity curves")
        return curves

    from app.agents.front_office.strategy.sleeves import momentum_rank
    from app.data_layer.universe import get_universe
    from scripts.validate_sleeve_attribution import LIVE_CFG, _loo_weights, run
    momentum_rank._TOP_N = 3

    bars = pd.read_pickle(PAPER_DIR / "debate_ab_bars_max.pkl")
    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    cfg_uni = get_universe("config")

    prod = _loo_weights("breadth_alpha")
    incumbent = {"breadth_alpha": 0.40, "research_stack": 0.30,
                 "trend_filter": 0.20, "momentum_rank": 0.10}

    curves: dict[str, pd.Series] = {}
    for wname, (start, end) in WINDOWS.items():
        win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
        cal = closes.index[win]
        for aname, weights in (("mix", prod), ("incumbent", incumbent)):
            print(f"  replaying {wname}/{aname} ...")
            eq, _ = run(LIVE_CFG, weights, bars, closes, opens, cal, 100_000.0, cfg_uni)
            curves[f"{wname}/{aname}"] = eq.reindex(cal).dropna()
        # The PIT bar cache holds index members and anchors only, so the peer
        # ETFs have to be fetched separately rather than silently omitted.
        import asyncio

        from app.data_layer.batch_bars import fetch_batch
        peers = asyncio.run(fetch_batch(["QAI.US", "AOR.US"], period="max"))
        peer_close = {k: v["close"] for k, v in peers.items()}
        sources = {"SPY": closes[spy_col], "QAI": peer_close.get("QAI.US"),
                   "AOR": peer_close.get("AOR.US")}
        for label, series in sources.items():
            if series is None:
                print(f"  [warn] {label} unavailable; row omitted, not zero-filled")
                continue
            s = series.loc[cal[0]:cal[-1]].dropna()
            if len(s) > 250:
                curves[f"{wname}/{label}"] = s / s.iloc[0] * 100_000.0
            else:
                print(f"  [warn] {label} covers only {len(s)} days of {wname}")
    pd.to_pickle(curves, CURVES)
    print(f"Cached {len(curves)} curves -> {CURVES.name}")
    return curves


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rebuild", action="store_true")
    args = p.parse_args()

    rf = load_riskfree()
    curves = build_curves(args.rebuild)
    results: dict[str, dict] = {}

    for wname in WINDOWS:
        bench = curves.get(f"{wname}/SPY")
        print(f"\n=== {wname} ===")
        hdr = (f"{'row':12s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} "
               f"{'Sortino':>8s} {'Calmar':>7s} {'maxDD%':>7s} {'DDdays':>7s} "
               f"{'up%':>6s} {'down%':>7s} {'final$':>10s}")
        print(hdr)
        for key in [k for k in curves if k.startswith(f"{wname}/")]:
            m = metric_suite(curves[key], rf,
                             bench if not key.endswith("/SPY") else None)
            results[key] = m
            name = key.split("/", 1)[1]
            print(f"{name:12s} {m['cagr_pct']:>7.1f} {m['vol_pct']:>6.1f} "
                  f"{m['sharpe']:>7.2f} "
                  f"{(m['sortino'] if m['sortino'] is not None else float('nan')):>8.2f} "
                  f"{(m['calmar'] if m['calmar'] is not None else float('nan')):>7.2f} "
                  f"{m['max_dd_pct']:>7.1f} {m['longest_dd_days']:>7d} "
                  f"{(m['up_capture'] or float('nan')):>6.0f} "
                  f"{(m['down_capture'] or float('nan')):>7.0f} "
                  f"{m['terminal']:>10,.0f}")

    out = PAPER_DIR / "results_all.json"
    out.write_text(json.dumps(results, indent=1, default=float), encoding="utf-8")
    print(f"\nWrote {out}")


def _selfcheck() -> None:
    """Check each metric against a curve whose answers are known by hand."""
    idx = pd.date_range("2020-01-01", periods=TRADING_DAYS * 2, freq="B")
    rf0 = pd.Series(0.0, index=idx)

    # Exactly doubling over two years: CAGR must be ~41.4%, drawdown zero.
    eq = pd.Series(np.linspace(100_000, 200_000, len(idx)), index=idx)
    m = metric_suite(eq, rf0)
    assert 39 < m["cagr_pct"] < 44, m["cagr_pct"]
    assert abs(m["max_dd_pct"]) < 1e-9, m["max_dd_pct"]
    assert m["calmar"] is None, "no drawdown means Calmar is undefined, not huge"
    assert abs(m["total_return_pct"] - 100.0) < 1e-6, m["total_return_pct"]
    assert m["longest_dd_days"] == 0, m["longest_dd_days"]

    # A curve that halves then recovers: drawdown is -50%, and the underwater
    # stretch is the whole descent plus the climb back.
    down = np.linspace(100_000, 50_000, 100)
    up = np.linspace(50_000, 100_000, 100)
    eq2 = pd.Series(np.concatenate([down, up]),
                    index=pd.date_range("2020-01-01", periods=200, freq="B"))
    m2 = metric_suite(eq2, pd.Series(0.0, index=eq2.index))
    assert abs(m2["max_dd_pct"] + 50.0) < 0.6, m2["max_dd_pct"]
    assert m2["longest_dd_days"] > 150, m2["longest_dd_days"]

    # Sortino must exceed Sharpe when the downside is quieter than total vol.
    rng = np.array([0.01 if i % 5 else -0.002 for i in range(len(idx))])
    eq3 = pd.Series(100_000 * np.cumprod(1 + rng), index=idx)
    m3 = metric_suite(eq3, rf0)
    assert m3["sortino"] > m3["sharpe"], (m3["sortino"], m3["sharpe"])

    # Capture: a strategy identical to the benchmark captures 100% both ways.
    b = pd.Series(100_000 * np.cumprod(1 + np.array(
        [0.004 * (1 if i % 3 else -1) for i in range(len(idx))])), index=idx)
    m4 = metric_suite(b, rf0, bench=b)
    assert abs(m4["up_capture"] - 100) < 1e-6, m4["up_capture"]
    assert abs(m4["down_capture"] - 100) < 1e-6, m4["down_capture"]

    # A higher risk-free rate must lower Sharpe, never raise it.
    hi = metric_suite(eq3, pd.Series(0.05, index=idx))["sharpe"]
    assert hi < m3["sharpe"], (hi, m3["sharpe"])
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
