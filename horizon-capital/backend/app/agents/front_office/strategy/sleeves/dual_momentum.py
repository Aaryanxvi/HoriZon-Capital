"""Dual-momentum sleeve: Antonacci GEM over asset-class ETFs.

Reference: Antonacci, "Dual Momentum Investing" (2014). Rule, verbatim, no
tuning:
  1. Rank risk assets (SPY, EFA, TLT, GLD, DBC) by 12-month return.
  2. If the top asset's 12m return beats the cash proxy's (BIL), hold it at
     100% of the sleeve.
  3. Otherwise hold the defensive asset (TLT).

ETF prices carry no survivorship bias, so free data validates this sleeve
honestly (see scripts/validate_overlay.py). Monthly cadence — the documented
GEM rebalance frequency.
"""
from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_RISK_ASSETS = ["SPY.NYSE", "EFA.NYSE", "TLT.NASDAQ", "GLD.NYSE", "DBC.NYSE"]
_CASH_PROXY = "BIL.NYSE"
_DEFENSIVE = "TLT.NASDAQ"
_LOOKBACK = 252  # 12 months


class DualMomentumSleeve(BaseSleeve):
    name = "dual_momentum"
    target_weight = 0.30
    rebalance_days = 21  # monthly — GEM's documented cadence

    # StrategyAgent unions this into its fetch list so the ETFs always have bars
    # even when the trading universe (US_SYMBOLS / sp500) doesn't include them.
    UNIVERSE = frozenset(_RISK_ASSETS) | {_CASH_PROXY}

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
