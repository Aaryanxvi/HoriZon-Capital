"""Dual-momentum sleeve: Antonacci GEM over asset-class ETFs.

Reference: Antonacci, "Dual Momentum Investing" (2014) — GEM, canonical menu:
  1. Rank the two RISK assets (US equities SPY vs intl equities EFA) by
     12-month return (relative momentum).
  2. If the top one beats the cash proxy's (BIL) 12m return (absolute
     momentum), hold it at 100% of the sleeve.
  3. Otherwise hold the defensive bond asset (TLT).

Gold/commodities are deliberately NOT in the risk menu — a first cut included
GLD/DBC and promptly bought the 2008 commodity-bubble top in backtest (−55%
maxDD 2008-17 vs GEM's published crash-dodging record). Canonical menu only.

ETF prices carry no survivorship bias, so free data validates this sleeve
honestly (see scripts/validate_overlay.py). Monthly cadence — the documented
GEM rebalance frequency.
"""
from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_RISK_ASSETS = ["SPY.NYSE", "EFA.NYSE"]
_CASH_PROXY = "BIL.NYSE"
_DEFENSIVE = "TLT.NASDAQ"
_LOOKBACK = 252  # 12 months


class DualMomentumSleeve(BaseSleeve):
    name = "dual_momentum"
    target_weight = 0.30
    rebalance_days = 21  # monthly — GEM's documented cadence

    # StrategyAgent unions this into its fetch list so the ETFs always have bars
    # even when the trading universe (US_SYMBOLS / sp500) doesn't include them.
    # _DEFENSIVE must be in here: it's both a fetch requirement and the emission
    # set — without it the RISK_OFF branch decided "hold TLT" but never emitted
    # the TLT signal, leaving the sleeve's 30% in cash during crashes.
    UNIVERSE = frozenset(_RISK_ASSETS) | {_CASH_PROXY, _DEFENSIVE}

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        def ret_12m(sym: str) -> float | None:
            df = bars.get(sym)
            if df is None:
                return None
            close = df.loc[:as_of]["close"]
            if len(close) < _LOOKBACK + 1:
                return None
            past = float(close.iloc[-_LOOKBACK])
            return float(close.iloc[-1]) / past - 1.0 if past > 0 else None

        rets = {s: r for s in _RISK_ASSETS if (r := ret_12m(s)) is not None}
        if not rets:
            return []

        top, top_ret = max(rets.items(), key=lambda kv: kv[1])
        cash_ret = ret_12m(_CASH_PROXY) or 0.0
        winner = top if top_ret > cash_ret else _DEFENSIVE
        if winner not in bars:
            return []  # defensive asset has no data — keep previous targets
        reason = f"GEM: top={top} {top_ret:+.1%} vs cash {cash_ret:+.1%} -> hold {winner}"

        return [
            SleeveSignal(symbol=s, target_weight=1.0 if s == winner else 0.0, reason=reason)
            for s in sorted(self.UNIVERSE)
            if s in bars or s == winner
        ]


def _demo() -> None:
    """Self-check: risk-on holds top risk asset; risk-off actually emits TLT=1.0."""
    import numpy as np

    idx = pd.date_range("2020-01-01", periods=300, freq="B")

    def mk(mult: float) -> pd.DataFrame:
        px = np.linspace(100, 100 * mult, len(idx))
        return pd.DataFrame({"open": px, "high": px, "low": px,
                             "close": px, "volume": 1e6}, index=idx)

    sleeve = DualMomentumSleeve()
    # Risk-on: SPY strongest, beats cash -> SPY=1.0.
    bars = {"SPY.NYSE": mk(1.3), "EFA.NYSE": mk(1.1),
            "BIL.NYSE": mk(1.0), "TLT.NASDAQ": mk(1.05)}
    w = {s.symbol: s.target_weight for s in sleeve.compute(bars, idx[-1])}
    assert w.get("SPY.NYSE") == 1.0 and w.get("TLT.NASDAQ") == 0.0, w
    # Risk-off: both risk assets below cash -> defensive TLT=1.0 (the bug this
    # demo exists to catch: TLT missing from the emission set).
    bars = {"SPY.NYSE": mk(0.7), "EFA.NYSE": mk(0.65),
            "BIL.NYSE": mk(1.0), "TLT.NASDAQ": mk(1.1)}
    w = {s.symbol: s.target_weight for s in sleeve.compute(bars, idx[-1])}
    assert w.get("TLT.NASDAQ") == 1.0 and w.get("SPY.NYSE") == 0.0, w
    print("dual_momentum demo OK:", w)


if __name__ == "__main__":
    _demo()
