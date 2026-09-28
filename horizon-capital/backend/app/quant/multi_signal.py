# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-EE10AD1E7E72
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Cross-sectional multi-signal scorer — the breadth engine.

Purpose: rank a LARGE universe (hundreds of names) cheaply and deterministically
so the expensive LLM gate only ever sees the top-K. All signals are price-only,
vectorized, and computed point-in-time (closes up to ``as_of`` only). Scoring 500
names is a sub-second pandas op costing $0 — breadth belongs here, NOT in the LLM.

Signals (weakly correlated on purpose — the Fundamental Law rewards independent
bets, so we stack several rather than bet the farm on one momentum number):
  mom_12_1 : 12m return skipping last month   (Jegadeesh-Titman trend persistence)
  mom_6_1  : 6m return skipping last month    (faster trend)
  reversal : -(last 21d return)    (short-term mean reversion, decorrelated from momentum)
  low_vol  : -(trailing 60d vol)              (low-volatility anomaly)
  trend    : price/200d SMA - 1               (Faber absolute-trend overlay)
  beta     : -(beta vs market)     (betting-against-beta; Frazzini-Pedersen 2014 — needs `market`)
  ltr      : -(return from 3y ago to 1y ago)  (De Bondt-Thaler long-term reversal;
                                               price-based VALUE proxy, no look-ahead)

True fundamental value (P/E, P/B) is intentionally NOT here: yfinance gives only a
CURRENT fundamentals snapshot, which is look-ahead in a backtest. ltr is the clean,
point-in-time value proxy. ``beta`` and ``ltr`` are decorrelated from the momentum
family — that decorrelation is the whole point (raises Sharpe more than a stronger
momentum signal would).

Composite = mean of the available per-signal cross-sectional z-scores (clipped to
+-3 so one outlier can't hijack the rank). Higher composite = stronger long.

The LLM contract (see ``select_for_llm`` / ``build_llm_brief``): we escalate only
the top-K names above a conviction floor, as a COMPACT numeric brief (a few z-scores
per name, never raw price history). Top-10 names x ~6 numbers ~= a few hundred
tokens, one batched call per weekly rebalance ~= ~52 calls/yr. That is the whole
point: the deterministic layer earns the breadth; the LLM only adjudicates a short
list it can no longer afford to get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Lookbacks in trading days.
_MOM_LONG = 252
_MOM_MED = 126
_SKIP = 21
_VOL_WIN = 60
_SMA_WIN = 200
_BETA_WIN = 252          # window for market-beta estimate (BAB)
_LTR_LONG = 756          # ~3y: long-term-reversal lookback start
_LTR_SHORT = 252         # ~1y: long-term-reversal lookback end (skip last year)
_MIN_HISTORY = _MOM_LONG + 1
_CLIP = 3.0

# Canonical signal order for the LLM brief.
_SIGNAL_ORDER = ["mom_12_1", "mom_6_1", "reversal", "low_vol", "trend", "beta", "ltr"]


@dataclass
class Candidate:
    """One name's standing after cross-sectional scoring."""

    symbol: str
    score: float                 # composite cross-sectional z (higher = stronger long)
    conviction: float            # abs(score) — used by the LLM-escalation gate
    signals: dict[str, float]    # per-signal z-scores, for explainability + LLM brief


def _xs_z(vec: pd.Series) -> pd.Series:
    """Cross-sectional z-score across symbols, clipped to +-_CLIP."""
    vec = vec.replace([np.inf, -np.inf], np.nan).dropna()
    if len(vec) < 2:
        return pd.Series(dtype=float)
    sd = vec.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return pd.Series(0.0, index=vec.index)
    return ((vec - vec.mean()) / sd).clip(-_CLIP, _CLIP)


def score_universe(
    closes: pd.DataFrame,
    as_of: pd.Timestamp,
    market: pd.Series | None = None,
) -> list[Candidate]:
    """Rank every symbol in ``closes`` (wide: index=dates, cols=symbols) as of a date.

    ``market`` (e.g. SPY close series) enables the beta signal; if None, beta is
    skipped. Returns candidates sorted by composite score descending. Pure function.
    """
    hist = closes.loc[:as_of]
    if len(hist) < _MIN_HISTORY:
        return []
    # Forward-fill holidays/missing; require a real last price per name.
    c = hist.ffill()
    last = c.iloc[-1]
    valid = last.dropna().index
    valid = [s for s in valid if c[s].notna().sum() >= _MIN_HISTORY]
    if len(valid) < 2:
        return []
    c = c[valid]

    rets = c.pct_change()
    raw: dict[str, pd.Series] = {
        "mom_12_1": c.iloc[-_SKIP] / c.iloc[-_MOM_LONG] - 1,
        "mom_6_1": c.iloc[-_SKIP] / c.iloc[-_MOM_MED] - 1,
        "reversal": -(c.iloc[-1] / c.iloc[-_SKIP] - 1),
        "low_vol": -(rets.iloc[-_VOL_WIN:].std()),
        "trend": c.iloc[-1] / c.iloc[-_SMA_WIN:].mean() - 1,
    }

    # Long-term reversal (value proxy): past 3y-to-1y losers tend to mean-revert.
    # Degrades gracefully — names with <3y history get NaN here, not dropped.
    if len(c) >= _LTR_LONG:
        raw["ltr"] = -(c.iloc[-_LTR_SHORT] / c.iloc[-_LTR_LONG] - 1)

    # Betting-against-beta: low-beta names earn higher risk-adjusted returns.
    if market is not None:
        mr = market.reindex(c.index).ffill().pct_change().iloc[-_BETA_WIN:]
        mvar = float(mr.var())
        if mvar > 0:
            rwin = rets.iloc[-_BETA_WIN:]
            beta = rwin.apply(lambda col: col.cov(mr)) / mvar
            raw["beta"] = -beta

    z = pd.DataFrame({k: _xs_z(v) for k, v in raw.items()})
    composite = z.mean(axis=1, skipna=True).dropna()

    out: list[Candidate] = []
    for sym in composite.index:
        sc = float(composite[sym])
        out.append(Candidate(
            symbol=sym,
            score=sc,
            conviction=abs(sc),
            signals={k: float(z.loc[sym, k]) for k in z.columns if not np.isnan(z.loc[sym, k])},
        ))
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def select_for_llm(
    candidates: list[Candidate],
    k: int = 10,
    min_conviction: float = 1.0,
) -> list[Candidate]:
    """The narrow gate: only the top-K positive names above a conviction floor.

    This is the entire token/credit-control mechanism. With a 500-name universe
    this returns at most ``k`` names (default 10), so the LLM never scales with
    universe size. ``min_conviction`` lets you skip the LLM entirely on weeks
    where nothing is convincing.
    """
    longs = [c for c in candidates if c.score > 0 and c.conviction >= min_conviction]
    return longs[:k]


def build_llm_brief(selected: list[Candidate]) -> str:
    """Compact numeric brief for ONE batched LLM call — never raw price history.

    A handful of z-scores per name keeps a 10-name brief to a few hundred tokens.
    """
    keys = [k for k in _SIGNAL_ORDER if any(k in c.signals for c in selected)]
    lines = ["symbol | composite | " + " | ".join(keys)]
    for c in selected:
        vals = " | ".join(f"{c.signals.get(k, 0.0):+.2f}" for k in keys)
        lines.append(f"{c.symbol} | {c.score:+.2f} | {vals}")
    return "\n".join(lines)


def _demo() -> None:
    """Self-check: uptrend tops; beta + ltr signals activate with enough data."""
    n = 800  # > _LTR_LONG so long-term reversal is exercised
    idx = pd.RangeIndex(n)
    up = pd.Series(np.linspace(100, 200, n), index=idx)        # strong uptrend
    flat = pd.Series(100.0, index=idx) + np.sin(idx / 5)       # noise, no trend
    down = pd.Series(np.linspace(200, 100, n), index=idx)      # downtrend
    closes = pd.DataFrame({"UP": up, "FLAT": flat, "DOWN": down})
    market = (up + flat + down) / 3                            # synthetic index for beta
    cands = score_universe(closes, as_of=idx[-1], market=market)
    by_sym = {c.symbol: c for c in cands}
    assert cands[0].symbol == "UP", f"expected UP top, got {cands[0].symbol}"
    # Momentum/trend dominate direction: uptrend must out-score the downtrend.
    # (A smooth downtrend still scores on low-vol + reversal, so it need not be
    # dead last — that disagreement is the point of stacking decorrelated signals.)
    assert by_sym["UP"].score > by_sym["DOWN"].score
    # New decorrelated signals must be present.
    assert "beta" in by_sym["UP"].signals, "beta signal missing"
    assert "ltr" in by_sym["UP"].signals, "ltr signal missing"
    # Gate returns at most k and only positives.
    sel = select_for_llm(cands, k=2, min_conviction=0.0)
    assert len(sel) <= 2 and all(c.score > 0 for c in sel)
    assert "beta" in build_llm_brief(sel) and "ltr" in build_llm_brief(sel)
    print("multi_signal demo OK:", [(c.symbol, round(c.score, 2)) for c in cands])
    print("signals:", sorted(by_sym["UP"].signals))


if __name__ == "__main__":
    _demo()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token EE10AD1E7E72 - verify with scripts/authorship.py verify
