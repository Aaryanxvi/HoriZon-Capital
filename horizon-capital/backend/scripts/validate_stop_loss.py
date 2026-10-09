# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A58187311853
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Effect of the owner's 20% trailing stop on the validated live mix (PIT harness).

MEASUREMENT, not tuning. Same data, fill model and sleeve classes as
validate_sleeve_attribution.py / validate_holdout_gate.py; the only addition is a
per-position trailing stop that mirrors what the live system now does
(execution_agent/position_worker: HWM since entry, stop = HWM x (1 - trail)).

Stop model (intraday, like a broker-resting trailing stop):
  * HWM starts at the entry fill, ratchets on each day's high.
  * On day t the stop is checked against the day's LOW using HWM up to the
    previous close (plus today's open) -- no look-ahead into today's high.
  * A trigger fills the SAME day at min(open, stop) minus slippage (a gap below
    the stop fills at the open, otherwise at the stop).

Re-entry after a stop (the live PortfolioAgent `stopped_out` rule is A):
  A  stay out until the sleeve's target for the name rises >= 50 bps above the
     target it was stopped at, or the target goes to zero (a later non-zero
     target is then a fresh entry).
  B  re-enter at the next rebalance if the target still says hold (what a stop
     with no re-entry rule would do -- shown so the cost of rule A is visible).

Arms: no stop / stop + rule A / stop + rule B / SPY buy-hold.

Usage:
    python scripts/validate_stop_loss.py --start 2018-01-01 --end 2024-12-31
    python scripts/validate_stop_loss.py --start 2008-01-01 --end 2017-12-31 --period max
    python scripts/validate_stop_loss.py --selfcheck
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

from app.agents.front_office.strategy.sleeves import momentum_rank  # noqa: E402
from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS, get_universe  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402
from scripts.validate_sleeve_attribution import (  # noqa: E402
    COMMISSION_BPS,
    LIVE_CFG,
    MIN_TRADE_NAV,
    SLIPPAGE_BPS,
    _base,
    _make_sleeves,
    _targets,
    metrics,
)

# The live mix (strategy_agent.py base_mix) -- the no-breadth candidate that
# passed the 2008-17 holdout gate.
LIVE_WEIGHTS = {"research_stack": 0.500, "trend_filter": 0.333, "momentum_rank": 0.167}
TRAIL = 0.20          # owner's choice, not tuned here
REENTRY_BPS = 0.005   # StrategyAgent's MIN_WEIGHT_DELTA


def run(cfg, weights, bars, closes, opens, highs, lows, calendar, capital,
        config_universe, *, trail: float | None, reentry: str = "A"):
    """validate_sleeve_attribution.run() plus the trailing-stop overlay.

    Returns (equity series, avg gross, number of stop triggers).
    """
    sleeves = _make_sleeves(weights)
    cache: dict[str, list] = {}
    cash, shares = capital, {}
    hwm: dict[str, float] = {}
    stopped: dict[str, float] = {}       # symbol -> target weight when stopped
    pending: dict[str, float] | None = None
    targets: dict[str, float] = {}
    equity: dict[pd.Timestamp, float] = {}
    gross_samples: list[float] = []
    n_stops = 0

    for i, date in enumerate(calendar):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                deltas = []
                for s in set(list(shares) + list(pending)):
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    w = pending.get(s, 0.0)
                    if trail is not None and reentry == "A" and s in stopped:
                        if w <= 0 or w >= stopped[s] + REENTRY_BPS:
                            stopped.pop(s)       # fresh entry allowed
                        else:
                            w = 0.0              # stay out
                    tgt = nav_open * w / px
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
                        had = shares.get(s, 0.0) > 0
                        shares[s] = shares.get(s, 0.0) + qty
                        hwm[s] = max(hwm.get(s, 0.0), ex) if had else ex
                    else:
                        cash += qty * ex - comm
                        shares[s] = shares.get(s, 0.0) - qty
                        if shares[s] <= 1e-9:
                            shares.pop(s, None)
                            hwm.pop(s, None)
            pending = None

        # Intraday trailing stop on every held long.
        if trail is not None:
            for s in list(shares):
                if shares[s] <= 0 or s not in lows.columns or date not in lows.index:
                    continue
                lo, hi = lows[s].get(date, np.nan), highs[s].get(date, np.nan)
                op = opens[s].get(date, np.nan)
                if np.isnan(lo) or np.isnan(hi):
                    continue
                h = hwm.get(s, op if not np.isnan(op) else lo)
                if not np.isnan(op):
                    h = max(h, op)
                stop = h * (1 - trail)
                if lo <= stop:
                    fill = (min(op, stop) if not np.isnan(op) else stop) * (1 - SLIPPAGE_BPS / 1e4)
                    qty = shares.pop(s)
                    cash += qty * fill - qty * fill * COMMISSION_BPS / 1e4
                    hwm.pop(s, None)
                    stopped[s] = targets.get(s, 0.0)
                    n_stops += 1
                else:
                    hwm[s] = max(h, hi)

        nav = _mtm(closes, shares, date, cash)
        equity[date] = nav
        if not np.isnan(nav) and nav > 0:
            gross_samples.append((nav - cash) / nav)

        if i % 5 == 0 and i + 1 < len(calendar):
            if cfg["universe"] == "pit":
                elig = members_on(date)
                view = {s: df for s, df in bars.items() if s in _ANCHORS or _base(s) in elig}
            else:
                view = {s: df for s, df in bars.items() if s in config_universe}
            view = {s: df.loc[:date] for s, df in view.items()}
            view = {s: df for s, df in view.items() if len(df) > 2}
            targets = _targets(sleeves, cache, view, date, i // 5 * 5, cfg["cap"])
            pending = dict(targets)

    avg_gross = float(np.mean(gross_samples)) if gross_samples else 0.0
    return pd.Series(equity).dropna(), avg_gross, n_stops


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--period", default="10y", help="yfinance period; 'max' for 2008-17")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    momentum_rank._TOP_N = 3  # validated live top-3

    config_universe = get_universe("config")
    pit = union_members(args.start, args.end)
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), period={args.period} ...")
    bars = asyncio.run(fetch_batch(tickers, period=args.period))
    print(f"Coverage: {len(bars)}/{len(tickers)} (missing = mostly delisted; known gap)")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    highs = pd.DataFrame({s: df["high"] for s, df in bars.items()}).sort_index()
    lows = pd.DataFrame({s: df["low"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    start_ts = pd.Timestamp(args.start)
    first_spy = closes[spy_col].dropna().index.min()
    if first_spy > start_ts:
        print(f"ABORT: SPY data starts {first_spy.date()} > {start_ts.date()}; "
              "pass --period max for early windows.")
        sys.exit(2)
    win = (closes.index >= start_ts) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]
    print(f"Calendar: {cal[0].date()} -> {cal[-1].date()} ({len(cal)} days)")

    def _run(trail, reentry="A"):
        return run(LIVE_CFG, LIVE_WEIGHTS, bars, closes, opens, highs, lows, cal,
                   args.capital, config_universe, trail=trail, reentry=reentry)

    rows = []
    print("\nRunning live mix, no stop ...")
    eq, g, _ = _run(None)
    rows.append((metrics(eq, "live mix / no stop", g), 0))
    print(f"Running live mix, {TRAIL:.0%} trailing stop, re-entry A ...")
    eq, g, n = _run(TRAIL, "A")
    rows.append((metrics(eq, f"stop {TRAIL:.0%} / re-entry A", g), n))
    print(f"Running live mix, {TRAIL:.0%} trailing stop, re-entry B ...")
    eq, g, n = _run(TRAIL, "B")
    rows.append((metrics(eq, f"stop {TRAIL:.0%} / re-entry B", g), n))
    spx = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
    rows.append((metrics((spx / spx.iloc[0]) * args.capital, "SPY"), 0))

    print(f"\nWindow {args.start} -> {args.end}")
    print(f"{'variant':26s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} {'maxDD%':>7s} "
          f"{'avgGross%':>10s} {'stops':>6s}")
    for m, n in rows:
        print(f"{m['label']:26s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} "
              f"{m['maxDD%']:>7} {m['avgGross%']:>10} {n:>6}")
    print("\nCaveats: quality tilt stubbed (look-ahead), delisted prices missing, daily")
    print("bars (intraday HWM/low approximated by the day's high/low), stop fills at")
    print("min(open, stop) - slippage. Measurement only; the 20% level is the owner's.")


def _selfcheck() -> None:
    """Synthetic 3-symbol check of the stop overlay, no network."""
    idx = pd.bdate_range("2020-01-01", periods=70)
    # A: steady climb for 40 days, then a 2%/day slide for 30 days (-45% total).
    # The stop must fire once near 20% off the HWM and bound the loss; a gap
    # THROUGH the stop would not (fills at the open) -- that case is deliberate
    # not here, it is the known residual risk of any stop.
    a = pd.Series(100.0 + np.arange(70) * 1.0, index=idx)
    a.iloc[40:] = a.iloc[39] * (0.98 ** np.arange(1, 31))
    closes = pd.DataFrame({"A.NYSE": a, "SPY.NYSE": 300.0 + np.arange(70) * 0.1})
    opens, highs, lows = closes.copy(), closes * 1.005, closes * 0.995
    cal = closes.index
    weights = {"A.NYSE": 0.5}

    class _Sig:
        def __init__(self, s, w):
            self.symbol, self.target_weight = s, w

    class _Sleeve:
        name, rebalance_days, target_weight = "fake", 5, 1.0

        def compute(self, bars, as_of):
            return [_Sig(s, w) for s, w in weights.items()]

    import scripts.validate_stop_loss as me
    me._make_sleeves = lambda w: [_Sleeve()]  # type: ignore[assignment]
    me.members_on = lambda d: {"A", "SPY"}  # type: ignore[assignment]
    bars = {s: pd.DataFrame({"close": closes[s], "open": opens[s]}) for s in closes}
    cfg = {"cap": 0.20, "universe": "pit"}
    eq0, _, n0 = me.run(cfg, {"fake": 1.0}, bars, closes, opens, highs, lows, cal,
                        100_000.0, [], trail=None)
    eqa, _, na = me.run(cfg, {"fake": 1.0}, bars, closes, opens, highs, lows, cal,
                        100_000.0, [], trail=0.20, reentry="A")
    eqb, _, nb = me.run(cfg, {"fake": 1.0}, bars, closes, opens, highs, lows, cal,
                        100_000.0, [], trail=0.20, reentry="B")
    assert n0 == 0 and na == 1, (n0, na)
    # Rule A stays out (target unchanged at 20% cap), rule B re-buys and may stop again.
    assert nb >= 1
    # The crash day fills at the stop, so the stopped arm ends above the unstopped one.
    assert eqa.iloc[-1] > eq0.iloc[-1], (eqa.iloc[-1], eq0.iloc[-1])
    # A -20% loss on a 20% position with a 20% stop that fills ~ -20%: loss per NAV
    # is bounded by ~ cap * trail + a few bps of costs.
    worst = ((eqa - eqa.cummax()) / eqa.cummax()).min()
    assert worst > -(0.20 * 0.20 + 0.01), worst
    print("selfcheck OK", {"stops_A": na, "stops_B": nb, "maxDD_A": round(worst, 4)})


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A58187311853 - verify with scripts/authorship.py verify
