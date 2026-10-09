# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A8BE947E38D2
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""India (NSE) version of the live mix — pre-registered ship gate, free-tier PIT data.

Everything about universe, mapping, costs, tax, windows and gates is fixed in
docs/plans/2026-10-10-india-strategy-gate.md (committed before this ran). This
script only executes it. Window A (2014-19) is the harness-debug window; window
B (2020-26) is the HOLDOUT and is run once after the harness is frozen.

The real sleeve classes run unmodified; like the US validation scripts we only
patch module-level universe constants. Sleeve signals are computed once per
decision date and shared across arms (weights/costs/tax never change a signal).

Usage:
    python scripts/validate_india_gate.py --window A        # design/debug
    python scripts/validate_india_gate.py --window B        # holdout (once)
    python scripts/validate_india_gate.py --selfcheck       # no network
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.front_office.strategy.sleeves import momentum_rank  # noqa: E402
from app.agents.front_office.strategy.sleeves import research_stack  # noqa: E402
from app.agents.front_office.strategy.sleeves import trend_filter  # noqa: E402
from app.agents.front_office.strategy.sleeves.momentum_rank import MomentumRankSleeve  # noqa: E402
from app.agents.front_office.strategy.sleeves.research_stack import (  # noqa: E402
    ResearchStackSleeve,
)
from app.agents.front_office.strategy.sleeves.trend_filter import TrendFilterSleeve  # noqa: E402
from scripts.india_data import (  # noqa: E402
    CACHE,
    build_universe,
    coverage_table,
    load_rf_monthly,
    members_on,
)

# --- instruments -------------------------------------------------------------
REGIME_KEY = "SPY-PROXY.^NSEI"   # ResearchStack finds its regime series by startswith("SPY")
NIFTY_ETF = "NIFTYBEES.NS"
GOLD, GILT = "GOLDBEES.NS", "LTGILTBEES.NS"
RISK_ETFS = ["NIFTYBEES.NS", "JUNIORBEES.NS", "BANKBEES.NS"]
NON_STOCK = frozenset(RISK_ETFS + [GOLD, GILT, REGIME_KEY])
DEBT_LIKE = frozenset({GOLD, GILT})

WINDOWS = {"A": ("2014-01-01", "2019-12-31"), "B": ("2020-01-01", "2026-09-30"),
           "full": ("2014-01-01", "2026-09-30")}
DATA_RANGE = ("2014-01-01", "2026-09-30")  # membership union / cache range, window-independent

LIVE_WEIGHTS = {"research_stack": 0.500, "trend_filter": 1 / 3, "momentum_rank": 1 / 6}
CAP = 0.20
DECISION_EVERY = 5
MIN_TRADE_NAV = 0.002
TRADING_DAYS = 252

# --- Zerodha CNC (zerodha.com/charges, 2026-10) ------------------------------
STT, NSE_TXN, SEBI, STAMP, GST, DP_CHARGE = 0.001, 0.0000307, 0.000001, 0.00015, 0.18, 15.34
CASH_SPREAD = 0.005  # cash earns RF - 50 bps

# --- tax ----------------------------------------------------------------------
CESS = 1.04
STCG_EQ, LTCG, SLAB = 0.20 * CESS, 0.125 * CESS, 0.30 * CESS
LTCG_EXEMPT = 125_000.0
LT_DAYS = 365


# =============================================================================
# price cleaning (rules pre-registered in §1.2)
# =============================================================================
def mark_bad_prints(close: pd.Series) -> pd.Series:
    vals = close.to_numpy(dtype=float)
    n = len(vals)
    bad = np.zeros(n, dtype=bool)
    if n < 3 or not (np.abs(np.diff(vals) / vals[:-1]) > 0.5).any():
        return pd.Series(bad, index=close.index)
    last_good = vals[0]
    for i in range(1, n):
        v = vals[i]
        if abs(v / last_good - 1) > 0.5:
            revert = any(abs(vals[j] / last_good - 1) < 0.25 for j in range(i + 1, min(n, i + 4)))
            if revert:
                bad[i] = True
                continue
        last_good = v
    return pd.Series(bad, index=close.index)


def clean_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    bad = mark_bad_prints(df["close"])
    if bad.any():
        df.loc[bad.to_numpy(), :] = np.nan
        df = df.ffill()
    c, o = df["close"], df["open"]
    gap_prev = (o / c.shift(1) - 1).abs()
    gap_same = (o / c - 1).abs()
    fix = (gap_prev > 0.10) & (gap_same > 0.05)
    df.loc[fix, "open"] = c[fix]
    return df


# =============================================================================
# costs & tax
# =============================================================================
def buy_charges(value: float) -> dict[str, float]:
    txn, sebi = value * NSE_TXN, value * SEBI
    return {"stt": value * STT, "txn": txn, "sebi": sebi, "stamp": value * STAMP,
            "gst": GST * (txn + sebi), "dp": 0.0}


def sell_charges(value: float) -> dict[str, float]:
    txn, sebi = value * NSE_TXN, value * SEBI
    return {"stt": value * STT, "txn": txn, "sebi": sebi, "stamp": 0.0,
            "gst": GST * (txn + sebi), "dp": DP_CHARGE}


def tax_due(st_eq: float, st_debt: float, lt_eq: float, lt_debt: float, interest: float,
            cf_st: float = 0.0, cf_lt: float = 0.0) -> tuple[float, float, float]:
    """Return (tax, carry_st, carry_lt). Carries are <= 0 (losses).

    ST gains/losses net together (equity + debt-like); a net ST loss offsets LT
    gains; an LT loss offsets LT only; residual losses carry forward.
    Blended ST rate = weighted by the positive components.
    """
    st_net = st_eq + st_debt + cf_st
    lt_net = lt_eq + lt_debt + cf_lt
    carry_st = carry_lt = 0.0
    if st_net < 0:
        lt_net += st_net          # ST loss offsets LT gains
        st_net = 0.0
        if lt_net < 0:
            carry_st = lt_net     # whatever is left is carried (as ST, offsets anything)
            lt_net = 0.0
    if lt_net < 0:
        carry_lt = lt_net
        lt_net = 0.0
    pos_eq, pos_debt = max(st_eq, 0.0), max(st_debt, 0.0)
    st_rate = ((pos_eq * STCG_EQ + pos_debt * SLAB) / (pos_eq + pos_debt)
               if pos_eq + pos_debt > 0 else STCG_EQ)
    # 112A exemption applies to the equity share of the LT gain only.
    eq_share = (max(lt_eq, 0.0) / (max(lt_eq, 0.0) + max(lt_debt, 0.0))
                if max(lt_eq, 0.0) + max(lt_debt, 0.0) > 0 else 1.0)
    lt_taxable = lt_net - min(lt_net * eq_share, LTCG_EXEMPT)
    tax = st_net * st_rate + max(lt_taxable, 0.0) * LTCG + max(interest, 0.0) * SLAB
    return float(tax), float(carry_st), float(carry_lt)


def fy_of(ts: pd.Timestamp) -> int:
    return ts.year if ts.month >= 4 else ts.year - 1


# =============================================================================
# metrics & gates
# =============================================================================
def metrics(eq: pd.Series, rf_daily: pd.Series, label: str, extra: dict | None = None) -> dict:
    eq = eq.dropna()
    r = eq.pct_change().dropna()
    yrs = len(eq) / TRADING_DAYS
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 and eq.iloc[0] > 0 else 0.0
    vol = r.std() * math.sqrt(TRADING_DAYS)
    ex = r - rf_daily.reindex(r.index).ffill().fillna(0.0) / TRADING_DAYS
    sh = ex.mean() / r.std() * math.sqrt(TRADING_DAYS) if r.std() > 0 else 0.0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    out = {"label": label, "CAGR%": round(cagr * 100, 1), "vol%": round(vol * 100, 1),
           "Sharpe": round(float(sh), 2), "maxDD%": round(dd * 100, 1),
           "final": round(float(eq.iloc[-1]))}
    out.update(extra or {})
    return out


def gates(m_main: dict, m_bench: dict, m_posttax: dict, m_bench_posttax: dict,
          m_slip20: dict, cov_min: float, sharpe_a: float | None) -> dict[str, tuple[bool, str]]:
    g = {
        "G1 net Sharpe >= 0.50": (m_main["Sharpe"] >= 0.50, f"{m_main['Sharpe']}"),
        "G2 maxDD >= -35%": (m_main["maxDD%"] >= -35.0, f"{m_main['maxDD%']}%"),
        "G3 Sharpe > NIFTYBEES B&H": (m_main["Sharpe"] > m_bench["Sharpe"],
                                      f"{m_main['Sharpe']} vs {m_bench['Sharpe']}"),
        "G4 PIT coverage >= 70%/yr": (cov_min >= 70.0, f"min {cov_min}%"),
        "G5 post-tax Sharpe > B&H post-tax": (m_posttax["Sharpe"] > m_bench_posttax["Sharpe"],
                                              f"{m_posttax['Sharpe']} vs {m_bench_posttax['Sharpe']}"),
        "G6 G1&G3 hold at 20bps slip": (m_slip20["Sharpe"] >= 0.50 and m_slip20["Sharpe"] > m_bench["Sharpe"],
                                        f"{m_slip20['Sharpe']} (bench {m_bench['Sharpe']})"),
    }
    if sharpe_a is not None:
        g["G7 window-A Sharpe >= 0.30"] = (sharpe_a >= 0.30, f"{sharpe_a}")
    return g


# =============================================================================
# data assembly
# =============================================================================
class Data:
    def __init__(self, start: str, end: str):
        mem, symmap, prices = build_universe(*DATA_RANGE)
        self.mem, self.symmap = mem, symmap
        self.bars: dict[str, pd.DataFrame] = {}
        for t, df in prices.items():
            key = REGIME_KEY if t == "^NSEI" else t
            self.bars[key] = clean_prices(df)
        assert REGIME_KEY in self.bars and NIFTY_ETF in self.bars and GOLD in self.bars
        idx = self.bars[REGIME_KEY].index
        self.cal = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
        assert len(self.cal) > 400, f"only {len(self.cal)} bars in window"
        all_idx = idx
        self.closes = pd.DataFrame({k: v["close"] for k, v in self.bars.items()}).reindex(all_idx).ffill(limit=5)
        self.opens = pd.DataFrame({k: v["open"] for k, v in self.bars.items()}).reindex(all_idx)
        rf = load_rf_monthly()
        if rf is None:
            print("WARN: FRED RF unavailable, using flat 6.5%")
            rf = pd.Series(0.065, index=all_idx)
        self.rf_daily = rf.reindex(all_idx.union(rf.index)).ffill().bfill().reindex(all_idx)

    def tickers_of(self, symbols: set[str]) -> set[str]:
        return {self.symmap[s] for s in symbols if s in self.symmap and self.symmap[s] in self.bars}

    def coverage(self, start, end) -> pd.DataFrame:
        prices = {k: v for k, v in self.bars.items()}
        return coverage_table(self.mem, self.symmap, prices, start, end, indices=("NIFTY 50", "NIFTY 500"))


# =============================================================================
# signals (shared across arms)
# =============================================================================
def _new_sleeves() -> dict:
    rs = ResearchStackSleeve()
    rs._get_quality = lambda symbols, as_of: {s: 0.0 for s in symbols}  # type: ignore  # QMJ stub, as US
    return {"research_stack": rs, "trend_filter": TrendFilterSleeve(), "momentum_rank": MomentumRankSleeve()}


def compute_signals(d: Data) -> dict[str, dict[int, list]]:
    """{sleeve -> {decision index i -> signals}} using live refresh semantics
    (refresh when >= rebalance_days trading days since the last refresh)."""
    research_stack._DEFENSE_UNIVERSE = [GILT, GOLD]
    trend_filter._INSTRUMENT = NIFTY_ETF
    MomentumRankSleeve._exclude = NON_STOCK
    momentum_rank._TOP_N = 3
    sleeves = _new_sleeves()
    last: dict[str, int | None] = {k: None for k in sleeves}
    out: dict[str, dict[int, list]] = {k: {} for k in sleeves}
    gilt_idx = d.bars[GILT].index if GILT in d.bars else pd.DatetimeIndex([])
    n_dec = 0
    for i, date in enumerate(d.cal):
        if i % DECISION_EVERY or i + 1 >= len(d.cal):
            continue
        n_dec += 1
        due = [k for k, s in sleeves.items() if last[k] is None or i - last[k] >= s.rebalance_days]
        if not due:
            continue
        n50 = d.tickers_of(members_on(d.mem, "NIFTY 50", date))
        n500 = d.tickers_of(members_on(d.mem, "NIFTY 500", date))
        keys = n500 | n50 | set(RISK_ETFS) | {GOLD, REGIME_KEY}
        gilt_ok = gilt_idx.searchsorted(date, side="right") >= 31
        if gilt_ok:
            keys.add(GILT)
        view = {k: d.bars[k].loc[:date] for k in keys if k in d.bars}
        view = {k: v for k, v in view.items() if len(v) > 2}
        research_stack._RISK_UNIVERSE = sorted(n50) + RISK_ETFS
        for k in due:
            try:
                sigs = sleeves[k].compute(view, date)
            except Exception as exc:  # mirrors live: keep serving the cache
                print(f"  sleeve {k} error at {date.date()}: {exc!r}")
                continue
            if k == "research_stack" and not gilt_ok:
                # pre-registered fallback: no gilt ETF yet -> 50% gold + 50% cash
                if len(sigs) == 1 and sigs[0].symbol == GOLD and sigs[0].target_weight > 0.99:
                    sigs[0].target_weight = 0.5
            # Universe invariants (a silent breach here would be a harness bug).
            picked = {s.symbol for s in sigs if s.target_weight > 0}
            if k == "momentum_rank":
                assert not (picked & NON_STOCK), f"momentum picked non-stock {picked & NON_STOCK}"
                assert picked <= n500, f"momentum picked outside PIT Nifty 500: {picked - n500}"
            if k == "research_stack":
                allowed = n50 | set(RISK_ETFS) | DEBT_LIKE
                assert picked <= allowed, f"research picked outside allowed set: {picked - allowed}"
            if k == "trend_filter":
                assert picked <= {NIFTY_ETF}, f"trend picked {picked}"
            out[k][i] = sigs
            last[k] = i
        if n_dec % 50 == 0:
            print(f"  signals: {date.date()} ({n_dec} decisions)")
    return out


def targets_at(signals: dict[str, dict[int, list]], weights: dict[str, float], i: int) -> dict[str, float]:
    combined: dict[str, float] = {}
    for name, w in weights.items():
        if w <= 0 or not signals[name]:
            continue
        ks = [k for k in signals[name] if k <= i]
        if not ks:
            continue
        for sig in signals[name][max(ks)]:
            combined[sig.symbol] = combined.get(sig.symbol, 0.0) + sig.target_weight * w
    return {s: min(v, CAP) for s, v in combined.items() if v > 0}


# =============================================================================
# replay
# =============================================================================
def run(d: Data, signals, weights: dict[str, float], capital: float, slip_bps: float,
        apply_tax: bool, zero_cost: bool = False) -> tuple[pd.Series, pd.Series, dict]:
    """Return (pre-tax NAV, after-tax liquidation value, stats)."""
    slip = slip_bps / 1e4
    cash, units = capital, {}
    lots: dict[str, deque] = {}
    pending: dict[str, float] | None = None
    nav_s, liq_s = {}, {}
    charges = {"stt": 0.0, "txn": 0.0, "sebi": 0.0, "stamp": 0.0, "gst": 0.0, "dp": 0.0, "slip": 0.0}
    fy_b = {"st_eq": 0.0, "st_debt": 0.0, "lt_eq": 0.0, "lt_debt": 0.0, "interest": 0.0}
    cf_st = cf_lt = 0.0
    tax_by_fy: dict[int, float] = {}
    traded, n_trades, gross_samples = 0.0, 0, []
    cal = d.cal
    rf = d.rf_daily

    def charge(value: float, side: str) -> float:
        if zero_cost:
            return 0.0
        c = buy_charges(value) if side == "buy" else sell_charges(value)
        for k, v in c.items():
            charges[k] += v
        return sum(c.values())

    def realize(sym: str, qty: float, net_px: float, date: pd.Timestamp) -> None:
        q = qty
        dq = lots[sym]
        while q > 1e-9 and dq:
            lq, lcost, ldate = dq[0]
            take = min(q, lq)
            gain = take * (net_px - lcost)
            lt = (date - ldate).days >= LT_DAYS
            key = ("lt_" if lt else "st_") + ("debt" if sym in DEBT_LIKE else "eq")
            fy_b[key] += gain
            if take >= lq - 1e-9:
                dq.popleft()
            else:
                dq[0] = (lq - take, lcost, ldate)
            q -= take

    def unrealized_buckets(date: pd.Timestamp) -> dict[str, float]:
        b = {"st_eq": 0.0, "st_debt": 0.0, "lt_eq": 0.0, "lt_debt": 0.0}
        for sym, dq in lots.items():
            px = d.closes.at[date, sym] if sym in d.closes.columns else np.nan
            if np.isnan(px):
                continue
            # liquidation would pay sell charges too
            net_px = px * (1 - slip) * (1 - (0 if zero_cost else (STT + NSE_TXN + SEBI + GST * (NSE_TXN + SEBI))))
            for lq, lcost, ldate in dq:
                key = ("lt_" if (date - ldate).days >= LT_DAYS else "st_") + ("debt" if sym in DEBT_LIKE else "eq")
                b[key] += lq * (net_px - lcost)
        return b

    for i, date in enumerate(cal):
        # 1. cash interest
        r_cash = max(float(rf.at[date]) - CASH_SPREAD, 0.0) / TRADING_DAYS
        if cash > 0:
            interest = cash * r_cash
            cash += interest
            fy_b["interest"] += interest

        # 2. execute pending at today's (cleaned) open — sells first
        if pending is not None:
            nav_open = cash
            ref: dict[str, float] = {}
            for s, q in units.items():
                px = d.opens.at[date, s] if s in d.opens.columns else np.nan
                if np.isnan(px):
                    px = d.closes.at[cal[i - 1], s] if i > 0 else np.nan
                if not np.isnan(px):
                    ref[s] = px
                    nav_open += q * px
            deltas = []
            for s in set(list(units) + list(pending)):
                px = d.opens.at[date, s] if s in d.opens.columns else np.nan
                if np.isnan(px) or px <= 0:
                    continue
                tgt_val = nav_open * pending.get(s, 0.0)
                cur_val = units.get(s, 0.0) * px
                dv = tgt_val - cur_val
                if abs(dv) >= nav_open * MIN_TRADE_NAV or (pending.get(s, 0.0) == 0 and units.get(s, 0)):
                    deltas.append((s, px, dv))
            for s, px, dv in sorted(deltas, key=lambda t: t[2]):
                if dv < 0:
                    held = units.get(s, 0.0)
                    qty = held if pending.get(s, 0.0) == 0 else min(held, math.floor(-dv / px))
                    if qty <= 0:
                        continue
                    ex = px * (1 - slip)
                    value = qty * ex
                    c = charge(value, "sell")
                    charges["slip"] += qty * px * slip
                    cash += value - c
                    realize(s, qty, (value - c) / qty, date)
                    units[s] = held - qty
                    if units[s] <= 0:
                        units.pop(s, None)
                        lots.pop(s, None)
                    traded += value
                    n_trades += 1
                else:
                    ex = px * (1 + slip)
                    rate = 0.0 if zero_cost else (STT + NSE_TXN + SEBI + STAMP + GST * (NSE_TXN + SEBI))
                    qty = math.floor(min(dv, max(cash, 0.0) / (1 + rate)) / ex)
                    if qty <= 0:
                        continue
                    value = qty * ex
                    c = charge(value, "buy")
                    charges["slip"] += qty * px * slip
                    cash -= value + c
                    units[s] = units.get(s, 0.0) + qty
                    lots.setdefault(s, deque()).append((qty, (value + c) / qty, date))
                    traded += value
                    n_trades += 1
            pending = None

        # 3. mark to market
        nav = cash + sum(q * d.closes.at[date, s] for s, q in units.items()
                         if not np.isnan(d.closes.at[date, s]))
        nav_s[date] = nav
        if nav > 0:
            gross_samples.append((nav - cash) / nav)

        # 4. FY-end tax (or window end)
        last_day = i + 1 >= len(cal) or fy_of(cal[i + 1]) != fy_of(date)
        unreal = unrealized_buckets(date)
        acc_tax, _, _ = tax_due(fy_b["st_eq"] + unreal["st_eq"], fy_b["st_debt"] + unreal["st_debt"],
                                fy_b["lt_eq"] + unreal["lt_eq"], fy_b["lt_debt"] + unreal["lt_debt"],
                                fy_b["interest"], cf_st, cf_lt)
        liq_s[date] = nav - acc_tax
        if last_day:
            t, cf_st, cf_lt = tax_due(fy_b["st_eq"], fy_b["st_debt"], fy_b["lt_eq"], fy_b["lt_debt"],
                                      fy_b["interest"], cf_st, cf_lt)
            tax_by_fy[fy_of(date)] = round(t)
            if apply_tax:
                cash -= t
                nav_s[date] = nav - t
            fy_b = {k: 0.0 for k in fy_b}

        # 5. decision
        if i % DECISION_EVERY == 0 and i + 1 < len(cal):
            pending = targets_at(signals, weights, i)

    nav_series = pd.Series(nav_s)
    yrs = len(cal) / TRADING_DAYS
    avg_nav = float(nav_series.mean())
    stats = {
        "avgGross%": round(100 * float(np.mean(gross_samples)) if gross_samples else 0.0, 1),
        "turnover/yr": round(traded / avg_nav / yrs, 2) if avg_nav > 0 else 0.0,
        "charges%/yr": round(100 * sum(charges.values()) / avg_nav / yrs, 2) if avg_nav > 0 else 0.0,
        "charges": {k: round(v) for k, v in charges.items()},
        "n_trades": n_trades,
        "tax_by_fy": tax_by_fy,
        "tax_total": round(sum(tax_by_fy.values())),
    }
    return nav_series, pd.Series(liq_s), stats


def buy_and_hold(d: Data, capital: float, slip_bps: float) -> tuple[pd.Series, pd.Series]:
    slip = slip_bps / 1e4
    cal = d.cal
    px0 = d.opens.at[cal[0], NIFTY_ETF]
    if np.isnan(px0):
        px0 = d.closes.at[cal[0], NIFTY_ETF]
    ex = px0 * (1 + slip)
    rate = STT + NSE_TXN + SEBI + STAMP + GST * (NSE_TXN + SEBI)
    q = math.floor(capital / (ex * (1 + rate)))
    cost = q * ex * (1 + rate)
    cash = capital - cost
    nav, liq = {}, {}
    for i, date in enumerate(cal):
        cash *= 1 + max(float(d.rf_daily.at[date]) - CASH_SPREAD, 0.0) / TRADING_DAYS
        v = q * d.closes.at[date, NIFTY_ETF] + cash
        nav[date] = v
        gain = q * d.closes.at[date, NIFTY_ETF] * (1 - slip) * (1 - (STT + NSE_TXN + SEBI + GST * (NSE_TXN + SEBI))) - cost
        lt = (date - cal[0]).days >= LT_DAYS
        t, _, _ = tax_due(0 if lt else gain, 0, gain if lt else 0, 0, 0)
        liq[date] = v - t
    return pd.Series(nav), pd.Series(liq)


# =============================================================================
# main
# =============================================================================
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--window", choices=list(WINDOWS), default="A")
    p.add_argument("--capital", type=float, default=2_500_000.0)
    p.add_argument("--slip", type=float, default=10.0)
    p.add_argument("--arms", choices=["core", "all"], default="all")
    args = p.parse_args()
    start, end = WINDOWS[args.window]
    print(f"Window {args.window}: {start} -> {end}  capital=Rs{args.capital:,.0f} slip={args.slip}bps")

    d = Data(start, end)
    print(f"bars: {len(d.bars)} instruments; calendar {d.cal[0].date()} -> {d.cal[-1].date()} ({len(d.cal)} days)")
    cov = d.coverage(start, end)
    piv = cov.pivot(index="year", columns="index", values="coverage%")
    print("\nPIT coverage % (Jun-30 members with a Yahoo close):")
    print(piv.to_string())
    cov_min = float(piv.min().min())

    print("\nComputing sleeve signals (shared across arms)...")
    signals = compute_signals(d)
    for k, v in signals.items():
        print(f"  {k}: {len(v)} refreshes")
    # Regime diagnostics: a research refresh whose symbols are all defense = RISK_OFF.
    rs = signals["research_stack"]
    off = [all(s.symbol in DEBT_LIKE for s in sigs) if sigs else True for _, sigs in sorted(rs.items())]
    flips = sum(1 for a, b in zip(off, off[1:]) if a != b)
    print(f"  regime: RISK_OFF on {sum(off)}/{len(off)} research refreshes "
          f"({100 * sum(off) / max(len(off), 1):.0f}%), {flips} flips")
    tf = signals["trend_filter"]
    long_ = [bool(sigs) and sigs[0].target_weight > 0 for _, sigs in sorted(tf.items())]
    print(f"  trend: long NIFTYBEES on {sum(long_)}/{len(long_)} weekly checks")

    rows, curves = [], {}

    def arm(label, weights, capital=args.capital, slip=args.slip, tax=False, zero=False):
        nav, liq, st = run(d, signals, weights, capital, slip, tax, zero)
        extra = {k: st[k] for k in ("avgGross%", "turnover/yr", "charges%/yr", "n_trades", "tax_total")}
        m = metrics(liq if tax else nav, d.rf_daily, label, extra)
        m["charges"] = st["charges"]
        m["tax_by_fy"] = st["tax_by_fy"]
        rows.append(m)
        curves[label] = (nav, liq)
        print(f"  {label:34s} CAGR {m['CAGR%']:>6}%  vol {m['vol%']:>5}%  Sharpe {m['Sharpe']:>5}  "
              f"maxDD {m['maxDD%']:>6}%  gross {m['avgGross%']:>5}%  turnover {m['turnover/yr']:>5}x  "
              f"charges {m['charges%/yr']}%/yr  tax Rs{m['tax_total']:,}")
        return m

    print("\nArms:")
    m_main = arm("full-mix (pre-tax)", LIVE_WEIGHTS)
    m_post = arm("full-mix (POST-TAX liquidation)", LIVE_WEIGHTS, tax=True)
    m_s20 = arm("full-mix 20bps", LIVE_WEIGHTS, slip=20.0)
    bh_nav, bh_liq = buy_and_hold(d, args.capital, args.slip)
    m_bh = metrics(bh_nav, d.rf_daily, "NIFTYBEES B&H (pre-tax)")
    m_bh_post = metrics(bh_liq, d.rf_daily, "NIFTYBEES B&H (post-tax liq.)")
    rows += [m_bh, m_bh_post]
    for m in (m_bh, m_bh_post):
        print(f"  {m['label']:34s} CAGR {m['CAGR%']:>6}%  vol {m['vol%']:>5}%  Sharpe {m['Sharpe']:>5}  maxDD {m['maxDD%']:>6}%")

    standalone = {}
    if args.arms == "all":
        arm("full-mix 5bps", LIVE_WEIGHTS, slip=5.0)
        arm("full-mix ZERO cost", LIVE_WEIGHTS, zero=True, slip=0.0)
        arm("full-mix Rs5L", LIVE_WEIGHTS, capital=500_000.0)
        arm("full-mix Rs1Cr", LIVE_WEIGHTS, capital=10_000_000.0)
        arm("full-mix 20bps POST-TAX", LIVE_WEIGHTS, slip=20.0, tax=True)
        for name in LIVE_WEIGHTS:
            m = arm(f"solo:{name}", {name: 1.0})
            standalone[name] = curves[m["label"]][0]
        for name in LIVE_WEIGHTS:
            kept = {k: v for k, v in LIVE_WEIGHTS.items() if k != name}
            tot = sum(kept.values())
            arm(f"LOO-{name}", {k: v / tot for k, v in kept.items()})
        ret = pd.DataFrame({n: s.pct_change() for n, s in standalone.items()}).dropna()
        print("\nCorrelation (standalone daily returns):")
        print(ret.corr().round(3).to_string())
        full_sh = m_main["Sharpe"]
        print("\nPer-sleeve attribution (US rules: DRAGS if LOO >= full+0.03, CARRIES if LOO <= full-0.05):")
        for name in LIVE_WEIGHTS:
            loo = next(r["Sharpe"] for r in rows if r["label"] == f"LOO-{name}")
            v = "DRAGS" if loo >= full_sh + 0.03 else "CARRIES" if loo <= full_sh - 0.05 else "NEUTRAL"
            print(f"  {name:16s} LOO={loo:>5}  d={loo - full_sh:+.2f} -> {v}")

    sharpe_a = None
    if args.window == "B":
        fa = CACHE / "results_A.json"
        if fa.exists():
            sharpe_a = json.loads(fa.read_text())["gates_input"]["main_sharpe"]
    g = gates(m_main, m_bh, m_post, m_bh_post, m_s20, cov_min, sharpe_a)
    print(f"\nGATES (window {args.window}):")
    for k, (ok, detail) in g.items():
        print(f"  {k:36s} {'PASS' if ok else 'FAIL':4s}  {detail}")
    verdict = "PASS" if all(ok for ok, _ in g.values()) else "FAIL"
    print(f"\nVERDICT (window {args.window}): {verdict}")

    out = {"window": args.window, "start": start, "end": end, "capital": args.capital,
           "slip_bps": args.slip, "coverage": cov.to_dict(orient="records"), "rows": rows,
           "gates": {k: {"pass": ok, "detail": det} for k, (ok, det) in g.items()},
           "verdict": verdict, "gates_input": {"main_sharpe": m_main["Sharpe"]}}
    f = CACHE / f"results_{args.window}.json"
    f.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nwrote {f}")


# =============================================================================
# self-check (no network)
# =============================================================================
def _selfcheck() -> None:
    # charges arithmetic on a Rs10,000 trade
    b = buy_charges(10_000)
    assert abs(sum(b.values()) - (10 + 0.307 + 0.01 + 1.5 + 0.18 * 0.317)) < 1e-6, b
    s = sell_charges(10_000)
    assert abs(sum(s.values()) - (10 + 0.307 + 0.01 + 0.18 * 0.317 + 15.34)) < 1e-6, s
    # bad-print detection: 2-day 1/10 glitch flagged, genuine crash not
    c = pd.Series([100, 101, 10, 10.1, 102, 103.0])
    assert mark_bad_prints(c).tolist() == [False, False, True, True, False, False]
    assert not mark_bad_prints(pd.Series([100, 40, 41, 42.0])).any()
    # bad-open fix
    df = pd.DataFrame({"open": [100, 80, 101.0], "high": 0, "low": 0, "close": [100, 100, 101.0], "volume": 1},
                      index=pd.date_range("2020-01-01", periods=3))
    assert clean_prices(df)["open"].tolist() == [100, 100, 101.0]
    # tax: ST equity, LT exemption, loss offset, carry-forward
    t, cs, cl = tax_due(100_000, 0, 0, 0, 0)
    assert abs(t - 20_800) < 1e-6
    t, _, _ = tax_due(0, 0, 200_000, 0, 0)
    assert abs(t - 75_000 * 0.13) < 1e-6
    t, _, _ = tax_due(-50_000, 0, 200_000, 0, 0)
    assert abs(t - 25_000 * 0.13) < 1e-6          # ST loss offsets LT, exemption still applies
    t, cs, cl = tax_due(-50_000, 0, -10_000, 0, 0)
    assert t == 0 and cs < 0 and cl == 0            # all carried as ST
    t, _, _ = tax_due(0, 10_000, 0, 0, 1_000)
    assert abs(t - (10_000 * SLAB + 1_000 * SLAB)) < 1e-6
    # FY boundary
    assert fy_of(pd.Timestamp("2024-03-31")) == 2023 and fy_of(pd.Timestamp("2024-04-01")) == 2024
    # gates
    base = {"Sharpe": 0.6, "maxDD%": -20.0}
    g = gates(base, {"Sharpe": 0.5}, {"Sharpe": 0.55}, {"Sharpe": 0.5}, {"Sharpe": 0.52}, 80.0, 0.4)
    assert all(ok for ok, _ in g.values()), g
    g = gates({"Sharpe": 0.6, "maxDD%": -36.0}, {"Sharpe": 0.5}, {"Sharpe": 0.55}, {"Sharpe": 0.5},
              {"Sharpe": 0.49}, 69.0, 0.2)
    assert [ok for ok, _ in g.values()] == [True, False, True, False, True, False, False]
    # targets: cap + latest-refresh lookup
    from app.agents.front_office.strategy.sleeves.base import SleeveSignal
    sig = {"a": {0: [SleeveSignal("X", 1.0)], 10: [SleeveSignal("Y", 1.0)]}, "b": {0: [SleeveSignal("X", 1.0)]}}
    assert targets_at(sig, {"a": 0.5, "b": 0.5}, 5) == {"X": 0.2}       # 1.0 capped at 0.20
    assert targets_at(sig, {"a": 0.1, "b": 0.1}, 12) == {"Y": 0.1, "X": 0.1}
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A8BE947E38D2 - verify with scripts/authorship.py verify
