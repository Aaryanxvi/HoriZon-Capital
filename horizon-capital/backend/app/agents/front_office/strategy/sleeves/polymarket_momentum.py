# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-719B9C05F475
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Polymarket probability-momentum sleeve.

UNVALIDATED — no pre-registered gate pass. Default-disabled; enable via
POLYMARKET_SLEEVE_ENABLED. Run scripts/backtest_polymarket.py and pass a gate
before enabling in the live mix.

Thesis: documented drift in event probabilities — informed flow moves the
price before resolution; ride 7-day probability momentum away from the tails.
"""

from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal


class PolymarketMomentumSleeve(BaseSleeve):
    name = "polymarket_momentum"
    target_weight = 0.05  # class default; live weight set by _weighted()
    rebalance_days = 1

    _MOM_DAYS = 7
    _MOM_MIN = 0.05        # min +5pp 7-day probability change
    _MID_LO = 0.10         # skip near-certain-NO tails
    _MID_HI = 0.90         # skip near-certain-YES tails (resolution risk)
    _MAX_PER_MARKET = 0.25  # cap: one market <= 25% of sleeve capital

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        qualified: list[tuple[str, float, float]] = []  # (symbol, mid, mom)
        for symbol, df in bars.items():
            if not symbol.endswith(".POLY"):
                continue
            history = df.loc[:as_of]["close"]
            if len(history) < self._MOM_DAYS + 1:
                continue

            mid = history.iloc[-1]
            if not (self._MID_LO <= mid <= self._MID_HI):
                continue

            mom = mid - history.iloc[-(self._MOM_DAYS + 1)]
            if mom >= self._MOM_MIN:
                qualified.append((symbol, mid, mom))

        if not qualified:
            return []

        weight = min(1.0 / len(qualified), self._MAX_PER_MARKET)
        return [
            SleeveSignal(
                symbol=symbol,
                target_weight=weight,
                reason=f"7d prob mom +{mom:.2f}, mid={mid:.2f}",
            )
            for symbol, mid, mom in qualified
        ]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 719B9C05F475 - verify with scripts/authorship.py verify
