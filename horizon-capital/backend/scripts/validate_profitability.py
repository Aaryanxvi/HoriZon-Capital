# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-742B3F10ED02
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""After-tax, after-cost profitability of the live mix for an Indian LRS investor.

PRE-REGISTERED in docs/plans/2026-10-10-profitability-gate.md -- read that first. This
script only produces the numbers that document asks for; every arm, rate, rule and
gate below is defined there, and nothing here was tuned after a result was seen.

What it does, per window (design 2018-24 / holdout 2008-17):
  * replays the live mix through the same t+1-open, cost-charged loop as
    validate_sleeve_attribution.run, with FIFO lot tracking so every sale has a buy
    date and an INR cost basis;
  * runs the pre-registered arms (reference, bias checks, candidates C1-C4) and the
    two benchmarks (SPY buy-and-hold, 60/40 SPY/TLT annual rebalance);
  * applies Indian tax to each arm: 24-month long-term line, slab-rate STCG, 12.5%
    LTCG, surcharge + cess, STCL/LTCL set-off with carry-forward, dividends at slab,
    gains in INR (spot USDINR), tax paid out of the portfolio each 31 March, and a
    terminal liquidation so buy-and-hold pays its LTCG once at the end;
  * prints pre-tax and after-tax metrics, turnover, the short-term share of gains,
    and rate / FX-cost sensitivities.

`--report` loads both windows and evaluates the gates (deflated margin, DSR).

Harness corrections (disclosed, see gate doc section 3):
  * cadence: the old harness tested `i % rebalance_days` on multiples of 5, so a
    21-day sleeve refreshed every 105 trading days; live uses a calendar-day delta.
  * trading rule: the old harness re-traded any price drift >= 0.2% NAV weekly; live
    (StrategyAgent) trades only when a target weight CHANGES by >= 0.5%.
  * universe: the old harness showed every anchor (today's mega-caps) to the sleeves
    on every date, including years before they joined the index. Strict mode shows a
    single name only while it is a point-in-time member; ETF anchors are always shown.
  B_harness keeps all three as they were (it must reproduce the published numbers);
  every other arm runs with them fixed.

Usage:
    python scripts/validate_profitability.py --window design
    python scripts/validate_profitability.py --window holdout
    python scripts/validate_profitability.py --report
    python scripts/validate_profitability.py --selfcheck
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.front_office.strategy.sleeves import momentum_rank, research_stack  # noqa: E402
from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import members_on, union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS  # noqa: E402
from scripts.pit_quality import PITQuality  # noqa: E402
from scripts.validate_breadth import _mtm  # noqa: E402
from scripts.validate_riskfree import load_riskfree, sharpe_realized  # noqa: E402
from scripts.validate_sleeve_attribution import (  # noqa: E402
    _base,
    _loo_weights,
    _new_sleeve,
    metrics,
)

PAPER_DIR = ROOT.parent / "own research paper"
BARS_CACHE = PAPER_DIR / "debate_ab_bars_max.pkl"       # same file validate_deflated_sharpe uses
AUX_CACHE = PAPER_DIR / "profitability_aux.pkl"          # fx, dividends (small)
OUT_JSON = PAPER_DIR / "profitability_{window}.json"
OUT_CURVES = PAPER_DIR / "profitability_{window}_curves.pkl"

COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
TRADING_DAYS = 252
MIN_TRADE_NAV = 0.002        # existing harness dust threshold
MIN_WEIGHT_DELTA = 0.005     # StrategyAgent.MIN_WEIGHT_DELTA -- live target-change rule
CAP = 0.20
LT_MONTHS = 24
FX_COSTS = (0.0, 0.0025, 0.005, 0.01)
FX_BASE = 0.005
# (short-term, long-term, dividend) effective rates, gate doc section 1.
RATES = {
    "base 30%+10%sc": (0.3432, 0.1430, 0.3432),
    "no surcharge": (0.3120, 0.1300, 0.3120),
    "15% surcharge": (0.3588, 0.1495, 0.3588),
    "20% slab": (0.2080, 0.1300, 0.2080),
}
BASE_RATE = "base 30%+10%sc"

LIVE_WEIGHTS = _loo_weights("breadth_alpha")   # research .500 / trend .333 / momrank .167
WINDOWS = {"design": ("2018-01-01", "2024-12-31"), "holdout": ("2008-01-01", "2017-12-31")}
# B_harness must reproduce these (flat 4% RF). 2018-24: the live 3-sleeve mix is the
# "LOO-breadth" arm of validate_sleeve_attribution (0.77); 0.67 was the OLD 4-sleeve
# mix. 2008-17: the holdout-gate candidate (0.70).
REPRO = {"design": 0.77, "holdout": 0.70}

ETF_KEYS = {"SPY.NYSE", "QQQ.NASDAQ", "TLT.NASDAQ", "GLD.NYSE", "XLE.NYSE", "XLK.NYSE",
            "XLF.NYSE", "XLV.NYSE", "XLY.NYSE", "XLI.NYSE"}
ETF_ANCHORS = [a for a in _ANCHORS if a in ETF_KEYS]
# Ticker changes the PIT change-log records under the old symbol.
PIT_ALIASES = {"META": "FB", "GOOGL": "GOOG"}
_ORIG_RISK_UNIVERSE = list(research_stack._RISK_UNIVERSE)
_N_SINGLE = sum(1 for s in _ORIG_RISK_UNIVERSE if s not in ETF_KEYS)   # 17

# arm name -> replay options (gate doc section 3 + addendum A). Order = print order.
# raw=True runs on uncleaned prices; strict=False keeps the old anchor leak.
ARMS: dict[str, dict] = {
    "B_harness": dict(cadence="quirk", trade_rule="drift", strict=False, raw=True),
    "B_live_leak": dict(cadence="live", trade_rule="target", strict=False, raw=True),
    "B_live_raw": dict(cadence="live", trade_rule="target", raw=True),
    "B_live": dict(cadence="live", trade_rule="target"),
    "B_live_whole": dict(cadence="live", trade_rule="target", whole_shares=True),
    "B0_mech_univ": dict(cadence="live", trade_rule="target", universe_rule="mechanical"),
    "C1_rs21": dict(cadence="live", trade_rule="target", rs_days=21),
    "C2_rs21_taxaware": dict(cadence="live", trade_rule="target", rs_days=21, tax_aware=True),
    "C3_pit_qmj": dict(cadence="live", trade_rule="target", quality="pit"),
    "C5_regime_hyst": dict(cadence="live", trade_rule="target", hysteresis=(0.35, 0.65)),
    # Addendum B: C2's rules on the mechanical (no-hindsight) universe, gated against B0.
    "B0C2_mech_rs21_tax": dict(cadence="live", trade_rule="target", universe_rule="mechanical",
                               rs_days=21, tax_aware=True),
}
CANDIDATES = ("C1_rs21", "C2_rs21_taxaware", "C3_pit_qmj", "C5_regime_hyst")
DISPERSION_SET = ("B0_mech_univ",) + CANDIDATES    # sigma_delta set, gate doc section 5
MARGIN_FROZEN = 0.112                               # addendum B: margin from the main run
N_PROJECT_PRIOR = 12   # validate_deflated_sharpe.OBSERVED_TRIAL_SHARPES
SPIKE_MOVE, SPIKE_REVERT, SPIKE_BARS = 0.40, 0.10, 3  # addendum A1(a)
OPEN_VS_PREV, OPEN_VS_CLOSE = 0.10, 0.05              # addendum A1(b)
_REAL_DETECT_REGIME = research_stack.detect_regime


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_bars(rebuild: bool) -> dict[str, pd.DataFrame]:
    if not BARS_CACHE.exists() and not rebuild:
        # ponytail: a git worktree has no gitignored caches; reuse the main checkout's
        # copy of the same file (identical universe/period) rather than refetching.
        import shutil
        for anc in ROOT.parents:
            cand = anc / "horizon-capital" / "own research paper" / BARS_CACHE.name
            if cand.exists() and cand != BARS_CACHE:
                PAPER_DIR.mkdir(exist_ok=True)
                shutil.copy(cand, BARS_CACHE)
                print(f"Copied bars cache from {cand}")
                break
    if BARS_CACHE.exists() and not rebuild:
        bars = pd.read_pickle(BARS_CACHE)
        print(f"Loaded {len(bars)} cached series from {BARS_CACHE.name}")
        return bars
    pit = union_members("2008-01-01", "2024-12-31")
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    print(f"Fetching {len(tickers)} tickers (PIT union 2008-24 + anchors), period=max ...")
    bars = asyncio.run(fetch_batch(tickers, period="max"))
    PAPER_DIR.mkdir(exist_ok=True)
    pd.to_pickle(bars, BARS_CACHE)
    print(f"Coverage: {len(bars)}/{len(tickers)} -> cached")
    return bars


def load_aux(rebuild: bool) -> dict:
    """USDINR spot and SPY/TLT dividend histories (one small yfinance call each)."""
    if AUX_CACHE.exists() and not rebuild:
        return pd.read_pickle(AUX_CACHE)
    import yfinance as yf

    def _naive(idx):
        idx = pd.DatetimeIndex(idx)
        return (idx.tz_localize(None) if idx.tz is not None else idx).normalize()

    fx = yf.download("INR=X", period="max", interval="1d", progress=False,
                     auto_adjust=True)["Close"].squeeze().dropna()
    fx.index = _naive(fx.index)
    divs = {}
    for t in ("SPY", "TLT"):
        d = yf.Ticker(t).dividends
        d.index = _naive(d.index)
        divs[t] = d
    aux = {"fx": fx, "div": divs}
    pd.to_pickle(aux, AUX_CACHE)
    return aux


def clean_bars(bars: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    """Addendum A1: revert-within-3-bars close spikes, and opens far from both the
    prior and the same-day close. Applied to every series, identically for all arms."""
    out, n_close, n_open, touched = {}, 0, 0, set()
    for s, df in bars.items():
        c = df["close"].to_numpy(dtype=float, copy=True)
        o = df["open"].to_numpy(dtype=float, copy=True)
        n, i = len(c), 1
        while i < n:
            prev = c[i - 1]
            if prev > 0 and abs(c[i] / prev - 1) > SPIKE_MOVE:
                for k in range(1, SPIKE_BARS + 1):
                    j = i + k
                    if j < n and abs(c[j] / prev - 1) < SPIKE_REVERT:
                        for t in range(i, j):
                            c[t] = prev + (t - i + 1) / (j - i + 1) * (c[j] - prev)
                            o[t] = c[t]
                        n_close += j - i
                        touched.add(s)
                        i = j
                        break
                else:
                    i += 1
                continue
            i += 1
        prevc = np.roll(c, 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            bad = (np.abs(o / prevc - 1) > OPEN_VS_PREV) & (np.abs(o / c - 1) > OPEN_VS_CLOSE)
        bad[0] = False
        if bad.any():
            touched.add(s)
            n_open += int(bad.sum())
            o[bad] = c[bad]
        d = df.copy()
        d["close"], d["open"] = c, o
        out[s] = d
    return out, {"close_bars": n_close, "open_bars": n_open, "series": len(touched)}


class _RegimeWrapper:
    """Stands in for research_stack.detect_regime: counts flips and, for C5, applies
    the hysteresis band so the sleeve only leaves a state on a decisive reading."""

    def __init__(self, band: tuple[float, float] | None):
        self.band, self.last, self.flips = band, None, 0

    def __call__(self, close: pd.Series) -> tuple[str, float]:
        state, conf = _REAL_DETECT_REGIME(close)
        if self.band and self.last is not None:
            lo, hi = self.band
            if self.last == "RISK_ON":
                state = "RISK_OFF" if conf < lo else "RISK_ON"
            else:
                state = "RISK_ON" if conf > hi else "RISK_OFF"
        if self.last is not None and state != self.last:
            self.flips += 1
        self.last = state
        return state, conf


def fy_of(ts: pd.Timestamp) -> int:
    """Indian fiscal year label = calendar year in which it ends (31 March)."""
    return ts.year if ts.month <= 3 else ts.year + 1


def fy_yields(div: pd.Series, close: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    """Daily series: that FY's dividends / that FY's mean price (trailing-year yield)."""
    fy = pd.Series([fy_of(d) for d in cal], index=cal)
    out = pd.Series(0.0, index=cal)
    for label, days in fy.groupby(fy).groups.items():
        lo, hi = pd.Timestamp(f"{label - 1}-04-01"), pd.Timestamp(f"{label}-03-31")
        paid = float(div.loc[lo:hi].sum())
        px = close.reindex(days).dropna()
        if paid > 0 and len(px):
            out.loc[days] = paid / float(px.mean())
    return out


# ---------------------------------------------------------------------------
# Replay with FIFO lots
# ---------------------------------------------------------------------------

def _consume(lots_s: deque, qty: float, px: float, date, sym: str, realized: list) -> None:
    rem = qty
    while rem > 1e-12 and lots_s:
        lot = lots_s[0]
        take = min(rem, lot[1])
        realized.append((date, lot[0], take, lot[2], px, sym))
        lot[1] -= take
        rem -= take
        if lot[1] <= 1e-12:
            lots_s.popleft()


def _fifo_gain(lots_s: deque, qty: float | None, px: float) -> float:
    """Gain (USD) realized by selling `qty` FIFO at px; qty=None -> whole position."""
    g, rem = 0.0, (math.inf if qty is None else qty)
    for lot in lots_s:
        take = min(rem, lot[1])
        g += take * (px - lot[2])
        rem -= take
        if rem <= 1e-12:
            break
    return g


def _fill(s, px, d, date, cash, shares, lots, fills, realized, whole) -> float:
    buy, qty = d > 0, abs(d)
    held = shares.get(s, 0.0)
    if whole:
        qty = held if (not buy and qty >= held - 1e-9) else math.floor(qty)
        if qty <= 0:
            return cash
    ex = px * (1 + SLIPPAGE_BPS / 1e4) if buy else px * (1 - SLIPPAGE_BPS / 1e4)
    comm = qty * ex * COMMISSION_BPS / 1e4
    if buy:
        cost = qty * ex + comm
        if cost > cash:
            qty = max(0.0, (cash - comm) / ex)
            if whole:
                qty = math.floor(qty)
            if qty <= 0:
                return cash
            cost = qty * ex + comm
        cash -= cost
        shares[s] = held + qty
        lots[s].append([date, qty, ex])
    else:
        qty = min(qty, held)
        if qty <= 0:
            return cash
        cash += qty * ex - comm
        shares[s] = held - qty
        _consume(lots[s], qty, ex, date, s, realized)
        if shares[s] <= 1e-9:
            shares.pop(s)
            lots.pop(s, None)
    fills.append((date, s, qty if buy else -qty, ex))
    return cash


def _view(bars, date, strict: bool) -> dict[str, pd.DataFrame]:
    elig = members_on(date)
    elig |= {k for k, v in PIT_ALIASES.items() if v in elig}
    out = {}
    for s, df in bars.items():
        base = _base(s)
        ok = (s in ETF_ANCHORS or base in elig) if strict else (s in _ANCHORS or base in elig)
        if ok:
            d = df.loc[:date]
            if len(d) > 2:
                out[s] = d
    return out


def _mechanical_universe(view: dict[str, pd.DataFrame], elig: set[str]) -> list[str]:
    """ETFs of the original list + top-N PIT members by trailing-252d median $ volume."""
    etfs = [s for s in _ORIG_RISK_UNIVERSE if s in ETF_KEYS]
    dv = {}
    for s, df in view.items():
        if s in ETF_KEYS or _base(s) not in elig or len(df) < 252:
            continue
        t = df.tail(252)
        dv[s] = float((t["close"] * t["volume"]).median())
    return etfs + sorted(dv, key=dv.get, reverse=True)[:_N_SINGLE]


def _betas(view, symbols, n=252) -> dict[str, float]:
    spy = view.get("SPY.NYSE")
    if spy is None:
        return {}
    m = spy["close"].pct_change().tail(n)
    out = {}
    for s in symbols:
        df = view.get(s)
        if df is None:
            continue
        j = pd.concat([df["close"].pct_change().tail(n), m], axis=1).dropna()
        if len(j) >= 120 and j.iloc[:, 1].var() > 0:
            out[_base(s)] = float(np.cov(j.iloc[:, 0], j.iloc[:, 1])[0, 1] / j.iloc[:, 1].var())
    return out


def make_sleeves(opts: dict, pitq: PITQuality | None, ctx: dict) -> list:
    sleeves = []
    for name, w in LIVE_WEIGHTS.items():
        s = _new_sleeve(name)
        s.target_weight = w
        if name == "research_stack":
            if opts.get("rs_days"):
                s.rebalance_days = opts["rs_days"]
            if opts.get("quality") == "pit":
                assert pitq is not None

                def _pit_quality(symbols, as_of, _q=pitq):
                    bases = [_base(x) for x in symbols]
                    sc = _q.scores(bases, as_of, _betas(ctx["view"], symbols))
                    ctx["qmj_nonzero"] += sum(1 for v in sc.values() if v != 0.0)
                    ctx["qmj_total"] += len(sc)
                    return {x: sc.get(_base(x), 0.0) for x in symbols}

                s._get_quality = _pit_quality  # type: ignore[method-assign]
        sleeves.append(s)
    return sleeves


def replay(opts: dict, bars, closes, opens, cal, capital, pitq=None) -> dict:
    cadence = opts.get("cadence", "live")
    rule = opts.get("trade_rule", "target")
    strict = opts.get("strict", True)
    whole = opts.get("whole_shares", False)
    tax_aware = opts.get("tax_aware", False)
    ctx = {"view": {}, "qmj_nonzero": 0, "qmj_total": 0}
    sleeves = make_sleeves(opts, pitq, ctx)
    regime = _RegimeWrapper(opts.get("hysteresis"))
    research_stack.detect_regime = regime
    cache: dict[str, list] = {}
    last_refresh: dict[str, pd.Timestamp] = {}
    last_target: dict[str, float] = {}
    cash, shares = capital, {}
    lots: dict[str, deque] = defaultdict(deque)
    fills: list = []
    realized: list = []
    pending: dict[str, float] | None = None
    equity, cash_s, mv_tlt, mv_gld = {}, {}, {}, {}
    gross = []
    deferred = 0

    for i, date in enumerate(cal):
        if pending is not None:
            nav_open = _mtm(opens, shares, date, cash)
            if not np.isnan(nav_open):
                syms = set(shares) | set(pending)
                if rule == "target":
                    syms |= set(last_target)
                deltas = []
                for s in syms:
                    if s not in opens.columns or date not in opens.index:
                        continue
                    px = opens[s].get(date, np.nan)
                    if np.isnan(px) or px <= 0:
                        continue
                    new_w = pending.get(s, 0.0)
                    if rule == "target":
                        old_w = last_target.get(s, 0.0)
                        if abs(new_w - old_w) < MIN_WEIGHT_DELTA:
                            # Live never re-trades drift. Exception (C2 only): a
                            # reduction whose lots sit at a loss is harvested anyway.
                            harvest = (tax_aware and new_w < old_w and s in shares
                                       and _fifo_gain(lots[s], None, px) < 0)
                            if not harvest:
                                continue
                    d = nav_open * new_w / px - shares.get(s, 0.0)
                    if abs(d * px) < nav_open * MIN_TRADE_NAV:
                        if rule == "target":
                            last_target[s] = new_w
                        continue
                    if tax_aware and d < 0 and new_w > 0 and _fifo_gain(lots[s], -d, px) > 0:
                        deferred += 1          # partial trim of a winner: wait
                        continue
                    deltas.append((s, px, d, new_w))
                for s, px, d, new_w in sorted(deltas, key=lambda t: t[2]):
                    cash = _fill(s, px, d, date, cash, shares, lots, fills, realized, whole)
                    if rule == "target":
                        last_target[s] = new_w
            pending = None

        nav = _mtm(closes, shares, date, cash)
        equity[date] = nav
        cash_s[date] = cash
        mv_tlt[date] = shares.get("TLT.NASDAQ", 0.0) * closes["TLT.NASDAQ"].get(date, np.nan) \
            if "TLT.NASDAQ" in shares else 0.0
        mv_gld[date] = shares.get("GLD.NYSE", 0.0) * closes["GLD.NYSE"].get(date, np.nan) \
            if "GLD.NYSE" in shares else 0.0
        if not np.isnan(nav) and nav > 0:
            gross.append((nav - cash) / nav)

        if i % 5 == 0 and i + 1 < len(cal):
            view = _view(bars, date, strict)
            ctx["view"] = view
            combined: dict[str, float] = {}
            for sl in sleeves:
                if cadence == "quirk":
                    due = (i % sl.rebalance_days == 0) or sl.name not in cache
                else:
                    due = sl.name not in last_refresh or \
                        (date - last_refresh[sl.name]).days >= sl.rebalance_days
                if due:
                    if sl.name == "research_stack":
                        research_stack._RISK_UNIVERSE = (
                            _mechanical_universe(view, members_on(date))
                            if opts.get("universe_rule") == "mechanical"
                            else list(_ORIG_RISK_UNIVERSE))
                    try:
                        cache[sl.name] = sl.compute(view, date)
                        last_refresh[sl.name] = date
                    except Exception:
                        pass   # keep serving the cache (live behaviour)
                for sig in cache.get(sl.name, []):
                    combined[sig.symbol] = combined.get(sig.symbol, 0.0) \
                        + sig.target_weight * sl.target_weight
            pending = {s: min(w, CAP) for s, w in combined.items() if w > 0}

    research_stack._RISK_UNIVERSE = list(_ORIG_RISK_UNIVERSE)
    research_stack.detect_regime = _REAL_DETECT_REGIME
    return {
        "equity": pd.Series(equity).dropna(), "cash": pd.Series(cash_s),
        "mv_tlt": pd.Series(mv_tlt).fillna(0.0), "mv_gld": pd.Series(mv_gld).fillna(0.0),
        "fills": fills, "realized": realized, "lots": {s: list(q) for s, q in lots.items()},
        "gross": float(np.mean(gross)) if gross else 0.0, "deferred": deferred,
        "qmj_cov": (ctx["qmj_nonzero"] / ctx["qmj_total"]) if ctx["qmj_total"] else None,
        "flips": regime.flips,
    }


def static_replay(weights: dict[str, float], closes, opens, cal, capital, annual: bool) -> dict:
    """Benchmarks through the same fill/lot bookkeeping. First fill at cal[1] open
    (the strategy's first decision is at i=0, filled at i=1) -- same start."""
    cash, shares = capital, {}
    lots: dict[str, deque] = defaultdict(deque)
    fills, realized = [], []
    equity, cash_s, mv_tlt, mv_gld = {}, {}, {}, {}
    for i, date in enumerate(cal):
        trade = i == 1 or (annual and i > 1 and date.year != cal[i - 1].year)
        if trade:
            nav_open = _mtm(opens, shares, date, cash)
            deltas = []
            for s, w in weights.items():
                px = opens[s].get(date, np.nan)
                if np.isnan(px) or px <= 0:
                    continue
                d = nav_open * w / px - shares.get(s, 0.0)
                if abs(d * px) >= nav_open * MIN_TRADE_NAV:
                    deltas.append((s, px, d))
            for s, px, d in sorted(deltas, key=lambda t: t[2]):
                cash = _fill(s, px, d, date, cash, shares, lots, fills, realized, False)
        nav = _mtm(closes, shares, date, cash)
        equity[date] = nav
        cash_s[date] = cash
        mv_tlt[date] = shares.get("TLT.NASDAQ", 0.0) * closes["TLT.NASDAQ"].get(date, np.nan) \
            if "TLT.NASDAQ" in shares else 0.0
        mv_gld[date] = 0.0
    return {
        "equity": pd.Series(equity).dropna(), "cash": pd.Series(cash_s),
        "mv_tlt": pd.Series(mv_tlt).fillna(0.0), "mv_gld": pd.Series(mv_gld),
        "fills": fills, "realized": realized, "lots": {s: list(q) for s, q in lots.items()},
        "gross": 1.0, "deferred": 0, "qmj_cov": None, "flips": 0,
    }


# ---------------------------------------------------------------------------
# Indian tax engine
# ---------------------------------------------------------------------------

def net_gains(st: float, lt: float, cf_st: float,
              cf_lt: float) -> tuple[float, float, float, float]:
    """s.70/s.74: current-year set-off first, then brought-forward pools.
    STCL offsets STCG then LTCG; LTCL offsets LTCG only. Returns taxable (st, lt)
    and the updated carry-forward pools."""
    if lt < 0:
        cf_lt += -lt
        lt = 0.0
    if st < 0:
        use = min(-st, lt)
        lt -= use
        st += use
        if st < 0:
            cf_st += -st
            st = 0.0
    use = min(cf_st, st)
    st -= use
    cf_st -= use
    use = min(cf_st, lt)
    lt -= use
    cf_st -= use
    use = min(cf_lt, lt)
    lt -= use
    cf_lt -= use
    return st, lt, cf_st, cf_lt


def _gain_rows(records, fx: pd.Series) -> pd.DataFrame:
    rows = []
    for sell_d, buy_d, qty, bpx, spx, _s in records:
        g = qty * (spx * fx[sell_d] - bpx * fx[buy_d])          # INR, spot on trade dates
        rows.append((sell_d, g, bool(sell_d > buy_d + pd.DateOffset(months=LT_MONTHS))))
    df = pd.DataFrame(rows, columns=["date", "gain", "lt"])
    return df.astype({"gain": float, "lt": bool})


def tax_engine(res: dict, cal: pd.DatetimeIndex, closes: pd.DataFrame, fx: pd.Series,
               y_spy: pd.Series, y_tlt: pd.Series, rates: tuple[float, float, float]) -> dict:
    st_rate, lt_rate, div_rate = rates
    nav = res["equity"].reindex(cal).ffill()
    cash = res["cash"].reindex(cal).ffill()
    end = cal[-1]

    # Terminal liquidation of whatever is still held (slippage charged, no commission).
    term = []
    for s, lots_s in res["lots"].items():
        px = closes[s].loc[:end].dropna()
        if px.empty:
            continue
        ex = float(px.iloc[-1]) * (1 - SLIPPAGE_BPS / 1e4)
        for lot in lots_s:
            term.append((end, lot[0], lot[1], lot[2], ex, s))

    g_real = _gain_rows(res["realized"], fx)
    g_term = _gain_rows(term, fx)
    fy = pd.Series([fy_of(d) for d in cal], index=cal)

    def _fytd(g: pd.DataFrame, lt: bool) -> pd.Series:
        sub = g[g["lt"] == lt]
        daily = sub.groupby("date")["gain"].sum().reindex(cal, fill_value=0.0).astype(float)
        return daily.groupby(fy.values).cumsum()

    st_c, lt_c = _fytd(g_real, False), _fytd(g_real, True)

    mv_eq = (nav - cash - res["mv_tlt"].reindex(cal).fillna(0.0)
             - res["mv_gld"].reindex(cal).fillna(0.0)).clip(lower=0.0)
    mv_tlt = res["mv_tlt"].reindex(cal).fillna(0.0)
    div_usd = (mv_eq * y_spy.reindex(cal).fillna(0.0)
               + mv_tlt * y_tlt.reindex(cal).fillna(0.0)) / TRADING_DAYS
    div_c = (div_usd * fx.reindex(cal)).groupby(fy.values).cumsum()

    fxc = fx.reindex(cal)
    cf_st = cf_lt = 0.0
    scale = 1.0                      # cumulative shrink from taxes paid out of the book
    wealth = np.empty(len(cal))
    tax_usd = 0.0        # total paid, in the scaled (after-tax) portfolio's USD
    st_tax_tot = lt_tax_tot = 0.0
    fyv = fy.values
    liab_last = 0.0
    for k, d in enumerate(cal):
        st_tx, lt_tx, _, _ = net_gains(float(st_c.iloc[k]), float(lt_c.iloc[k]), cf_st, cf_lt)
        liab = st_tx * st_rate + lt_tx * lt_rate + float(div_c.iloc[k]) * div_rate   # INR
        wealth[k] = scale * (nav.iloc[k] - liab / fxc.iloc[k])
        liab_last = liab
        if k == len(cal) - 1:
            break
        if fyv[k + 1] != fyv[k]:     # 31 March: pay out of the portfolio, roll the pools
            st_tx, lt_tx, cf_st, cf_lt = net_gains(float(st_c.iloc[k]), float(lt_c.iloc[k]),
                                                   cf_st, cf_lt)
            st_tax_tot += st_tx
            lt_tax_tot += lt_tx
            pay_usd = liab / fxc.iloc[k]
            tax_usd += scale * pay_usd
            scale *= max(1.0 - pay_usd / nav.iloc[k], 0.0)

    # Terminal: last FY's running totals + liquidation, netted against the pools.
    st_fin = float(st_c.iloc[-1]) + float(g_term[~g_term["lt"]]["gain"].sum())
    lt_fin = float(lt_c.iloc[-1]) + float(g_term[g_term["lt"]]["gain"].sum())
    st_tx, lt_tx, _, _ = net_gains(st_fin, lt_fin, cf_st, cf_lt)
    liab_post = st_tx * st_rate + lt_tx * lt_rate + float(div_c.iloc[-1]) * div_rate
    st_tax_tot += st_tx
    lt_tax_tot += lt_tx
    w_pre = float(wealth[-1])
    w_post = scale * (nav.iloc[-1] - liab_post / fxc.iloc[-1])
    tax_usd_post = tax_usd + scale * liab_post / fxc.iloc[-1]

    allg = pd.concat([g_real, g_term])
    pos = allg[allg["gain"] > 0]
    pct_st = float(pos[~pos["lt"]]["gain"].sum() / pos["gain"].sum()) if len(pos) else float("nan")
    return {
        "curve": pd.Series(wealth, index=cal), "w_pre": w_pre, "w_post": w_post,
        "tax_usd_post": tax_usd_post, "pct_st_gains": pct_st,
        "st_taxable_inr": st_tax_tot, "lt_taxable_inr": lt_tax_tot,
        "n_realized": len(g_real), "liab_pre_end_inr": liab_last,
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _cagr(w_end: float, w_start: float, yrs: float) -> float:
    return (w_end / w_start) ** (1 / yrs) - 1 if yrs > 0 and w_end > 0 else float("nan")


def _maxdd(eq: pd.Series) -> float:
    return float(((eq - eq.cummax()) / eq.cummax()).min())


def _turnover(fills, nav: pd.Series, yrs: float) -> float:
    notional = sum(abs(q) * px for _, _, q, px in fills)
    return notional / 2.0 / float(nav.mean()) / yrs if yrs > 0 else 0.0


def evaluate(name, res, cal, closes, fx, y_spy, y_tlt, rf, capital) -> tuple[dict, dict]:
    eq = res["equity"].reindex(cal).ffill()
    yrs = len(eq) / TRADING_DAYS
    r = eq.pct_change().dropna()
    m = metrics(eq, name, res["gross"])
    row = {
        "arm": name, "cagr": m["CAGR%"], "vol": m["vol%"], "sharpe_flat4": m["Sharpe"],
        "sharpe_rf": round(sharpe_realized(r, rf), 2), "maxdd": m["maxDD%"],
        "turnover": round(_turnover(res["fills"], eq, yrs), 2), "fills": len(res["fills"]),
        "gross": m["avgGross%"], "deferred": res["deferred"], "qmj_cov": res["qmj_cov"],
        "flips": res["flips"],
    }
    fx_end, fx0 = float(fx[cal[-1]]), float(fx[cal[0]])
    curves = {"pre": eq}
    sens = {}
    for rname, rates in RATES.items():
        t = tax_engine(res, cal, closes, fx, y_spy, y_tlt, rates)
        for c in FX_COSTS:
            # Owner starts with INR K = capital*fx0/(1-c); ends with w_post*fx_end*(1-c).
            usd_eq = _cagr(t["w_post"] * (1 - c) ** 2, capital, yrs)
            sens[(rname, c)] = round(usd_eq * 100, 2)
        if rname == BASE_RATE:
            ac = t["curve"]
            ar = ac.pct_change().dropna()
            row.update({
                "pct_st": round(t["pct_st_gains"] * 100, 1),
                "tax_pct_nav_yr": round(t["tax_usd_post"] / float(eq.mean()) / yrs * 100, 2),
                "at_cagr_pre": round(_cagr(t["w_pre"] * (1 - FX_BASE) ** 2, capital, yrs) * 100, 2),
                "at_cagr_post": round(_cagr(t["w_post"] * (1 - FX_BASE) ** 2, capital, yrs)
                                      * 100, 2),
                "at_cagr_post_inr": round(_cagr(t["w_post"] * fx_end / fx0 * (1 - FX_BASE) ** 2,
                                                capital, yrs) * 100, 2),
                "at_sharpe_rf": round(sharpe_realized(ar, rf), 2),
                "at_maxdd": round(_maxdd(ac) * 100, 1),
                "n_realized": t["n_realized"],
            })
            row["drag"] = round(row["cagr"] - row["at_cagr_post"], 2)
            curves["post"] = ac
    row["sens"] = {f"{k[0]}|{k[1]}": v for k, v in sens.items()}
    return row, curves


def print_tables(rows: list[dict], window: str, start: str, end: str) -> None:
    print(f"\n=== {window} {start}..{end} -- pre-tax (USD) ===")
    print(f"{'arm':18s} {'CAGR%':>6s} {'vol%':>6s} {'Sh4%':>5s} {'ShRF':>5s} {'maxDD':>6s} "
          f"{'turn':>5s} {'fills':>5s} {'gross':>6s} {'flips':>5s} {'defer':>5s} {'qmjcov':>6s}")
    for r in rows:
        qc = f"{r['qmj_cov'] * 100:.0f}%" if r["qmj_cov"] is not None else "-"
        print(f"{r['arm']:18s} {r['cagr']:>6} {r['vol']:>6} {r['sharpe_flat4']:>5} "
              f"{r['sharpe_rf']:>5} {r['maxdd']:>6} {r['turnover']:>5} {r['fills']:>5} "
              f"{r['gross']:>6} {r['flips']:>5} {r['deferred']:>5} {qc:>6s}")
    print(f"\n=== {window} -- after Indian tax ({BASE_RATE}, FX {FX_BASE:.2%} each way) ===")
    print(f"{'arm':18s} {'%ST':>5s} {'tax/yr':>6s} {'ATpre':>6s} {'ATpost':>6s} "
          f"{'ATinr':>6s} {'ATsh':>5s} {'ATdd':>6s} {'drag':>5s} {'nreal':>5s}")
    for r in rows:
        print(f"{r['arm']:18s} {r['pct_st']:>5} {r['tax_pct_nav_yr']:>6} {r['at_cagr_pre']:>6} "
              f"{r['at_cagr_post']:>6} {r['at_cagr_post_inr']:>6} {r['at_sharpe_rf']:>5} "
              f"{r['at_maxdd']:>6} {r['drag']:>5} {r['n_realized']:>5}")
    print(f"\n=== {window} -- after-tax post-liquidation CAGR% (USD-eq) sensitivity ===")
    hdr = [f"{k[:12]:>12s}" for k in RATES] + [f"fx{c:.2%}" for c in FX_COSTS]
    print(f"{'arm':18s} " + " ".join(hdr) + "   (rates at fx 0.50%; fx cols at base rate)")
    for r in rows:
        vals = [f"{r['sens'][f'{k}|{FX_BASE}']:>12}" for k in RATES]
        vals += [f"{r['sens'][f'{BASE_RATE}|{c}']:>7}" for c in FX_COSTS]
        print(f"{r['arm']:18s} " + " ".join(vals))
    print("\nColumns: Sh4% = Sharpe vs flat 4% (handoff basis); ShRF = vs realized 13-week bill;")
    print("turn = one-way turnover x NAV/yr; %ST = share of realized gains that were short-term;")
    print("tax/yr = tax paid as % of avg NAV per year; ATpre/ATpost = after-tax CAGR before/after")
    print("terminal liquidation (USD-eq); ATinr = post-liq CAGR in INR; ATsh/ATdd on the accrual")
    print("after-tax curve; drag = pre-tax CAGR - ATpost; flips = research_stack regime flips;")
    print("defer = C2 deferred trims.")


def run_window(args) -> None:
    start, end = WINDOWS[args.window]
    bars_raw = load_bars(args.rebuild_bars)
    aux = load_aux(args.rebuild_bars)
    momentum_rank._TOP_N = 3
    bars_clean, fixed = clean_bars(bars_raw)
    print(f"Cleaning (addendum A1): {fixed['close_bars']} spike close bars, "
          f"{fixed['open_bars']} opens replaced, across {fixed['series']} series")

    def _frames(b):
        return (pd.DataFrame({s: df["close"] for s, df in b.items()}).sort_index(),
                pd.DataFrame({s: df["open"] for s, df in b.items()}).sort_index())

    closes_raw, opens_raw = _frames(bars_raw)
    closes, opens = _frames(bars_clean)
    spy_col = "SPY.NYSE"
    win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
    cal = closes.index[win]
    assert len(cal) > 500, f"only {len(cal)} bars -- fetch does not span {start}"
    first = closes[spy_col].dropna().index.min()
    assert first <= pd.Timestamp(start), f"SPY starts {first.date()}, after {start}"
    print(f"Window {args.window}: {cal[0].date()} -> {cal[-1].date()} ({len(cal)} days), "
          f"{len(bars_raw)} series")

    fx = aux["fx"].reindex(closes.index.union(aux["fx"].index)).ffill().bfill()
    rf = load_riskfree()
    # Addendum A3: the realized bill rate must really be there, not a flat fallback.
    rf_w = rf.reindex(cal).ffill().bfill()
    assert len(rf) > 2000 and rf.index.min() <= cal[0] and rf.index.max() >= cal[-1], \
        f"risk-free series does not span the window ({rf.index.min()}..{rf.index.max()})"
    assert float(rf_w.std()) > 0.001, "risk-free series is flat -- fetch/cache problem"
    print(f"Risk-free (^IRX) over window: mean {rf_w.mean():.2%}, min {rf_w.min():.2%}, "
          f"max {rf_w.max():.2%}")
    y_spy = fy_yields(aux["div"]["SPY"], closes[spy_col], cal)
    y_tlt = fy_yields(aux["div"]["TLT"], closes["TLT.NASDAQ"], cal)
    y_by_fy = y_spy.groupby([fy_of(d) for d in cal]).first().round(4).to_dict()
    print(f"FY dividend yields SPY {y_by_fy}")

    arms = args.arms.split(",") if args.arms else list(ARMS)
    pitq = None
    if any(ARMS[a].get("quality") == "pit" for a in arms):
        singles = [_base(s) for s in _ORIG_RISK_UNIVERSE if s not in ETF_KEYS]
        pitq = PITQuality(singles)
        missing = sorted(set(singles) - set(pitq.covered))
        print(f"SEC companyfacts coverage: {len(pitq.covered)}/{len(singles)} names"
              + (f" (missing: {', '.join(missing)})" if missing else ""))

    rows, curves = [], {}
    if not args.arms:
        for name, w, annual in (("SPY_bh", {spy_col: 1.0}, False),
                                ("6040_annual", {spy_col: 0.6, "TLT.NASDAQ": 0.4}, True)):
            res = static_replay(w, closes, opens, cal, args.capital, annual)
            row, cv = evaluate(name, res, cal, closes, fx, y_spy, y_tlt, rf, args.capital)
            rows.append(row)
            curves[name] = cv
    for name in arms:
        print(f"Running {name} {ARMS[name]} ...", flush=True)
        raw = ARMS[name].get("raw", False)
        b, c, o = (bars_raw, closes_raw, opens_raw) if raw else (bars_clean, closes, opens)
        res = replay(ARMS[name], b, c, o, cal, args.capital, pitq)
        row, cv = evaluate(name, res, cal, c, fx, y_spy, y_tlt, rf, args.capital)
        rows.append(row)
        curves[name] = cv
        if name == "B_harness":
            ok = abs(row["sharpe_flat4"] - REPRO[args.window]) <= 0.02
            print(f"  reproduction: Sh4% {row['sharpe_flat4']} vs {REPRO[args.window]} -> "
                  f"{'OK' if ok else 'DISCREPANCY -- STOP'}")
            if not ok and not args.force:
                sys.exit(2)

    # Merge with any earlier partial run of this window (arms are keyed by name).
    out_json = Path(str(OUT_JSON).format(window=args.window))
    out_pkl = Path(str(OUT_CURVES).format(window=args.window))
    prev = json.loads(out_json.read_text()) if out_json.exists() else {"rows": []}
    merged = {r["arm"]: r for r in prev["rows"]}
    merged.update({r["arm"]: r for r in rows})
    order = ["SPY_bh", "6040_annual"] + list(ARMS)
    rows_all = [merged[a] for a in order if a in merged]
    out_json.write_text(json.dumps({"window": args.window, "start": start, "end": end,
                                    "rows": rows_all}, indent=1))
    prev_c = pd.read_pickle(out_pkl) if out_pkl.exists() else {}
    prev_c.update(curves)
    pd.to_pickle(prev_c, out_pkl)
    print_tables(rows_all, args.window, start, end)
    print(f"\nSaved {out_json.name}, {out_pkl.name}")


# ---------------------------------------------------------------------------
# Report: gates + deflation (both windows)
# ---------------------------------------------------------------------------

def expected_max(sigma: float, n: int) -> float:
    g = 0.5772156649
    from scipy.stats import norm
    return sigma * ((1 - g) * norm.ppf(1 - 1.0 / n) + g * norm.ppf(1 - 1.0 / (n * math.e)))


def report() -> None:
    from app.config import settings
    from app.quant.metrics_advanced import deflated_sharpe_ratio, probabilistic_sharpe_ratio
    settings.risk_free_rate = 0.0    # we pass excess returns; the helper reads this field
    rf = load_riskfree()
    data, curves = {}, {}
    for w in WINDOWS:
        p = Path(str(OUT_JSON).format(window=w))
        if not p.exists():
            print(f"missing {p.name}; run --window {w} first")
            return
        data[w] = {r["arm"]: r for r in json.loads(p.read_text())["rows"]}
        curves[w] = pd.read_pickle(Path(str(OUT_CURVES).format(window=w)))

    def _excess(eq: pd.Series) -> np.ndarray:
        r = eq.pct_change().dropna()
        rfd = (1 + rf.reindex(r.index).ffill().bfill()) ** (1 / TRADING_DAYS) - 1
        return (r - rfd).to_numpy()

    d, h = data["design"], data["holdout"]
    print("\n=== Baseline question: does the live mix beat an index fund after tax? ===")
    for w, t in (("design", d), ("holdout", h)):
        b, s, m = t["B_live"], t["SPY_bh"], t["6040_annual"]
        print(f"{w:8s} after-tax post-liq CAGR: live {b['at_cagr_post']}%  "
              f"SPY {s['at_cagr_post']}%  "
              f"60/40 {m['at_cagr_post']}%  | after-tax Sharpe: live {b['at_sharpe_rf']} "
              f"SPY {s['at_sharpe_rf']} 60/40 {m['at_sharpe_rf']} | AT maxDD: live {b['at_maxdd']} "
              f"SPY {s['at_maxdd']}")
        verdict = "INDEX FUND BETTER AFTER TAX" if s["at_cagr_post"] > b["at_cagr_post"] \
            else "live mix better after tax"
        print(f"         -> {verdict} (CAGR); Sharpe "
              f"{'live' if b['at_sharpe_rf'] > s['at_sharpe_rf'] else 'SPY'} higher")

    print("\n=== Harness corrections (pre-tax ShRF / after-tax Sharpe / AT post CAGR) ===")
    for w, t in (("design", d), ("holdout", h)):
        for a in ("B_harness", "B_live_leak", "B_live_raw", "B_live", "B_live_whole",
                  "B0_mech_univ"):
            if a in t:
                print(f"{w:8s} {a:14s} {t[a]['sharpe_rf']:>5} {t[a]['at_sharpe_rf']:>5} "
                      f"{t[a]['at_cagr_post']:>6}  turnover {t[a]['turnover']}  "
                      f"flips {t[a]['flips']}")
        if "B0_mech_univ" in t:
            b0, bl = t["B0_mech_univ"], t["B_live"]
            print(f"{w:8s} look-ahead cost of the hard-coded research universe: "
                  f"dSharpe(B0-B_live) = {round(b0['sharpe_rf'] - bl['sharpe_rf'], 2)} "
                  f"pre-tax, {round(b0['at_sharpe_rf'] - bl['at_sharpe_rf'], 2)} after-tax")

    deltas = [d[a]["at_sharpe_rf"] - d["B_live"]["at_sharpe_rf"] for a in DISPERSION_SET if a in d]
    sigma = float(np.std(deltas, ddof=1)) if len(deltas) > 1 else 0.0
    emax = expected_max(sigma, len(deltas)) if sigma > 0 else 0.0
    margin = max(0.05, emax)
    print(f"\n=== Deflated margin: sigma_delta {sigma:.3f} over {len(deltas)} variants, "
          f"E[max] {emax:.3f}, margin {margin:.3f} ===")

    def _gates(label, arms, ref, m):
        print(f"\n=== {label} (after-tax, base rates; margin {m:.3f}, reference {ref}) ===")
        b_h, b_d = h[ref], d[ref]
        for a in arms:
            if a not in h or a not in d:
                print(f"{a}: NOT RUN")
                continue
            c_h, c_d = h[a], d[a]
            dsh = round(c_h["at_sharpe_rf"] - b_h["at_sharpe_rf"], 3)
            g1 = dsh >= m
            g2 = c_h["at_maxdd"] >= b_h["at_maxdd"] - 2.0
            g3 = c_h["at_cagr_post"] >= b_h["at_cagr_post"]
            dd_design = c_d["at_sharpe_rf"] - b_d["at_sharpe_rf"]
            g4 = dd_design * dsh > 0 or (dsh == 0 and dd_design == 0)
            res = "SHIP" if all((g1, g2, g3, g4)) else "KEEP CURRENT"
            pf = ["P" if g else "F" for g in (g1, g2, g3, g4)]
            print(f"{a:18s} dATsharpe {dsh:+.3f} (G1 {pf[0]}) | ATdd {c_h['at_maxdd']} "
                  f"vs {b_h['at_maxdd']} (G2 {pf[1]}) | ATpost {c_h['at_cagr_post']} vs "
                  f"{b_h['at_cagr_post']} (G3 {pf[2]}) | design d {dd_design:+.2f} "
                  f"(G4 {pf[3]}) -> {res}")

    _gates("Gates on the holdout", CANDIDATES, "B_live", margin)
    if "B0C2_mech_rs21_tax" in h:
        _gates("Addendum B confirmation on the holdout", ("B0C2_mech_rs21_tax",),
               "B0_mech_univ", MARGIN_FROZEN)
        for w, t in (("design", d), ("holdout", h)):
            if "B0C2_mech_rs21_tax" in t:
                c, s = t["B0C2_mech_rs21_tax"], t["SPY_bh"]
                print(f"{w:8s} B0C2 vs SPY after tax: CAGR {c['at_cagr_post']} vs "
                      f"{s['at_cagr_post']}, Sharpe {c['at_sharpe_rf']} vs {s['at_sharpe_rf']}, "
                      f"maxDD {c['at_maxdd']} vs {s['at_maxdd']}")

    # Data-coverage diagnostic for C3: share of the 17 research names with an SEC
    # point-in-time ROE available at the start of each year (XBRL begins mid-2009).
    singles = [_base(s) for s in _ORIG_RISK_UNIVERSE if s not in ETF_KEYS]
    try:
        pitq = PITQuality(singles)
        cov = {y: sum(1 for t in singles
                      if pitq.raw(t, pd.Timestamp(f"{y}-01-02"))["roe"] is not None)
               for y in range(2008, 2025)}
        print("\n=== C3 data coverage: names (of 17) with SEC point-in-time ROE on 2 Jan ===")
        print(" ".join(f"{y}:{n}" for y, n in cov.items()))
    except Exception as exc:  # offline: the gate numbers above do not depend on this
        print(f"\n(C3 coverage diagnostic unavailable: {exc})")

    n_prog = len(ARMS)
    n_proj = n_prog + N_PROJECT_PRIOR
    print(f"\n=== PSR / DSR (pre-tax excess returns; N_program={n_prog}, N_project={n_proj}) ===")
    for w in WINDOWS:
        srs = [data[w][a]["sharpe_rf"] for a in ARMS if a in data[w]]
        var_p = float(np.var(srs, ddof=1)) / TRADING_DAYS if len(srs) > 1 else None
        spy_sr = data[w]["SPY_bh"]["sharpe_rf"]
        print(f"{w}: program Sharpe range {min(srs)}..{max(srs)}, SPY {spy_sr}")
        for a in ("B_live", "B0_mech_univ") + CANDIDATES + ("B0C2_mech_rs21_tax",):
            if a not in curves[w]:
                continue
            for tag, key in (("pre", "pre"), ("post", "post")):
                x = _excess(curves[w][a][key])
                psr0 = probabilistic_sharpe_ratio(x, 0.0)
                psrs = probabilistic_sharpe_ratio(x, spy_sr)
                dsr_p = deflated_sharpe_ratio(x, n_prog, var_p)
                dsr_j = deflated_sharpe_ratio(x, n_proj, var_p)
                print(f"  {a:18s} {tag:4s} PSR>0 {psr0:.3f}  PSR>SPY {psrs:.3f}  "
                      f"DSR(N={n_prog}) {dsr_p:.3f}  DSR(N={n_proj}) {dsr_j:.3f}")


# ---------------------------------------------------------------------------
# Self-check: tax engine on constructed trades (no data, no network)
# ---------------------------------------------------------------------------

def _selfcheck() -> None:
    # net_gains: STCL offsets LTCG; LTCL does not offset STCG; pools roll.
    assert net_gains(100, 50, 0, 0) == (100, 50, 0, 0)
    assert net_gains(-30, 50, 0, 0) == (0, 20, 0, 0)
    assert net_gains(-80, 50, 0, 0) == (0, 0, 30, 0)
    assert net_gains(40, -20, 0, 0) == (40, 0, 0, 20)
    assert net_gains(40, 30, 10, 50) == (30, 0, 0, 20)   # cf_st hits st, cf_lt hits lt

    cal = pd.bdate_range("2019-01-01", "2021-12-31")
    cal = cal[cal.dayofweek < 5]
    px = pd.Series(np.linspace(100.0, 160.0, len(cal)), index=cal)      # steady rise
    closes = pd.DataFrame({"X": px, "TLT.NASDAQ": 100.0, "GLD.NYSE": 100.0})
    fx = pd.Series(np.linspace(70.0, 75.0, len(cal)), index=cal)        # INR weakens
    zero = pd.Series(0.0, index=cal)
    rates = (0.30, 0.10, 0.30)

    # Case A: buy 1000 sh day 0, hold -> terminal sale is LONG-term (36 months > 24).
    buy_d = cal[0]
    nav = px * 1000.0
    res = {"equity": nav, "cash": pd.Series(0.0, index=cal), "mv_tlt": zero, "mv_gld": zero,
           "fills": [], "realized": [], "lots": {"X": [[buy_d, 1000.0, 100.0]]}}
    t = tax_engine(res, cal, closes, fx, zero, zero, rates)
    gain_inr = 1000 * (160.0 * (1 - SLIPPAGE_BPS / 1e4) * fx.iloc[-1] - 100.0 * fx.iloc[0])
    assert abs(t["lt_taxable_inr"] - gain_inr) < 1e-6 and t["st_taxable_inr"] == 0, t
    assert abs(t["w_post"] - (nav.iloc[-1] - 0.10 * gain_inr / fx.iloc[-1])) < 1e-6, t
    assert t["w_pre"] == nav.iloc[-1] and t["pct_st_gains"] == 0.0

    # Case B: same lot sold after 12 months at a gain -> SHORT-term, tax paid at FY end,
    # the after-tax curve scales down by exactly that payment and stays flat (cash) after.
    sell_d = cal[cal.get_indexer([buy_d + pd.DateOffset(months=12)], method="bfill")[0]]
    k = cal.get_loc(sell_d)
    sell_px = float(px.iloc[k])
    cash = pd.Series(0.0, index=cal)
    cash.iloc[k:] = 1000.0 * sell_px
    nav_b = pd.concat([nav.iloc[:k], cash.iloc[k:]])
    res_b = {"equity": nav_b, "cash": cash, "mv_tlt": zero, "mv_gld": zero,
             "fills": [(buy_d, "X", 1000.0, 100.0), (sell_d, "X", -1000.0, sell_px)],
             "realized": [(sell_d, buy_d, 1000.0, 100.0, sell_px, "X")], "lots": {}}
    t = tax_engine(res_b, cal, closes, fx, zero, zero, rates)
    g_inr = 1000 * (sell_px * fx[sell_d] - 100.0 * fx[buy_d])
    assert abs(t["st_taxable_inr"] - g_inr) < 1e-6 and t["lt_taxable_inr"] == 0, t
    assert t["pct_st_gains"] == 1.0
    fy_end = max(dd for dd in cal if fy_of(dd) == fy_of(sell_d))
    j = cal.get_loc(fy_end)
    expect = nav_b.iloc[j] - 0.30 * g_inr / fx.iloc[j]
    assert abs(t["curve"].iloc[j] - expect) < 1e-6, (t["curve"].iloc[j], expect)
    assert abs(t["curve"].iloc[-1] - expect) < 1e-6                   # cash, no further tax
    assert abs(t["w_post"] - t["w_pre"]) < 1e-9                        # nothing left to liquidate

    # Case C: a loss realized first shelters a later gain (carry-forward across FYs).
    res_c = dict(res_b)
    res_c["realized"] = [(cal[5], cal[1], 10.0, 200.0, 100.0, "X"),      # FY2019 loss -1000*fx
                         (sell_d, buy_d, 1000.0, 100.0, sell_px, "X")]
    t_c = tax_engine(res_c, cal, closes, fx, zero, zero, rates)
    assert t_c["st_taxable_inr"] < t["st_taxable_inr"], (t_c["st_taxable_inr"], t["st_taxable_inr"])

    # Dividend accrual: 2% yield on 100% equity taxed at 30% -> ~0.6%/yr of NAV.
    res_d = {"equity": pd.Series(100000.0, index=cal), "cash": pd.Series(0.0, index=cal),
             "mv_tlt": zero, "mv_gld": zero, "fills": [], "realized": [], "lots": {}}
    t_d = tax_engine(res_d, cal, closes, fx, pd.Series(0.02, index=cal), zero, rates)
    yrs = len(cal) / TRADING_DAYS
    assert abs(t_d["tax_usd_post"] / 100000.0 / yrs - 0.006) < 0.0007, t_d["tax_usd_post"]

    # FIFO lot bookkeeping through _fill.
    lots, fills, realized, shares = defaultdict(deque), [], [], {}
    c = _fill("X", 100.0, 10.0, cal[0], 10_000.0, shares, lots, fills, realized, False)
    c = _fill("X", 110.0, 5.0, cal[1], c, shares, lots, fills, realized, False)
    c = _fill("X", 120.0, -12.0, cal[2], c, shares, lots, fills, realized, False)
    assert abs(shares["X"] - 3.0) < 1e-9 and len(realized) == 2
    assert realized[0][1] == cal[0] and abs(realized[0][2] - 10.0) < 1e-9     # oldest lot first
    assert realized[1][1] == cal[1] and abs(realized[1][2] - 2.0) < 1e-9
    expect_gain = 3.0 * (130.0 - 110.0 * (1 + SLIPPAGE_BPS / 1e4))
    assert abs(_fifo_gain(lots["X"], None, 130.0) - expect_gain) < 1e-6
    # Whole shares: 7.9 -> 7; a full exit sells the fractional remainder too.
    lots2, sh2 = defaultdict(deque), {}
    c2 = _fill("Y", 10.0, 7.9, cal[0], 1000.0, sh2, lots2, [], [], True)
    assert sh2["Y"] == 7
    _fill("Y", 10.0, -7.0, cal[1], c2, sh2, lots2, [], [], True)
    assert "Y" not in sh2

    assert fy_of(pd.Timestamp("2020-03-31")) == 2020 and fy_of(pd.Timestamp("2020-04-01")) == 2021
    assert expected_max(0.1, 5) > expected_max(0.1, 2) > 0

    # Cleaning rule (addendum A1): a 1/10 print that reverts in 2 bars is interpolated;
    # a genuine 50% crash that does not revert is left alone; a junk open is replaced.
    idx = pd.bdate_range("2020-01-01", periods=12)
    close = np.array([100, 101, 10.2, 10.1, 102, 103, 50, 49, 48, 47, 46, 45], dtype=float)
    opn = close.copy()
    opn[5] = 130.0        # +26% vs prior close, +26% vs same-day close -> junk
    opn[7] = 49.5         # normal
    df = pd.DataFrame({"open": opn, "high": close, "low": close, "close": close, "volume": 1},
                      index=idx)
    cleaned, info = clean_bars({"Z": df})
    cz = cleaned["Z"]["close"].to_numpy()
    assert abs(cz[2] - (101 + 1 / 3)) < 1e-9 and abs(cz[3] - (101 + 2 / 3)) < 1e-9, cz
    assert cz[6] == 50 and cz[11] == 45, cz                    # the crash is kept
    assert cleaned["Z"]["open"].iloc[5] == 103.0 and cleaned["Z"]["open"].iloc[7] == 49.5
    assert info == {"close_bars": 2, "open_bars": 1, "series": 1}, info

    # Hysteresis wrapper: flips only on decisive readings; the plain wrapper counts flips.
    seq = iter([("RISK_ON", 0.9), ("RISK_OFF", 0.45), ("RISK_OFF", 0.3), ("RISK_ON", 0.6),
                ("RISK_ON", 0.7)])
    g = globals()                      # patch THIS module (it may be running as __main__)
    saved = g["_REAL_DETECT_REGIME"]
    g["_REAL_DETECT_REGIME"] = lambda _c: next(seq)
    try:
        hy = _RegimeWrapper((0.35, 0.65))
        states = [hy(None)[0] for _ in range(5)]
        assert states == ["RISK_ON", "RISK_ON", "RISK_OFF", "RISK_OFF", "RISK_ON"], states
        assert hy.flips == 2, hy.flips
    finally:
        g["_REAL_DETECT_REGIME"] = saved
    print("selfcheck OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--window", choices=list(WINDOWS))
    p.add_argument("--arms", default=None, help="comma-separated subset of arms to (re)run")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--rebuild-bars", action="store_true")
    p.add_argument("--force", action="store_true", help="continue past a failed reproduction")
    p.add_argument("--report", action="store_true")
    p.add_argument("--selfcheck", action="store_true")
    args = p.parse_args()
    if args.selfcheck:
        _selfcheck()
    elif args.report:
        report()
    elif args.window:
        run_window(args)
    else:
        p.print_help()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 742B3F10ED02 - verify with scripts/authorship.py verify
