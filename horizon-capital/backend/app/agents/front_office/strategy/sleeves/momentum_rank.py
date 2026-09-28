# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-8A159BC7616E
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Cross-sectional momentum sleeve.

Ranks the investable US universe by 12-month return excluding the most recent
month (the canonical 12-1 momentum factor from Jegadeesh & Titman, 1993).
Goes long the top three names in equal weight, rebalances monthly.

Rationale: cross-sectional momentum is one of the few anomalies that has
survived publication and out-of-sample testing across decades and markets.
Holding 3 names keeps single-name risk in check while not fragmenting too
thin at $100k capital.
"""

from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_LOOKBACK_DAYS = 252
_SKIP_DAYS = 21
_TOP_N = 3
# Rebalance only when the month changes — prevents churn on intra-month
# rank flips that would cost slippage without edge.


class MomentumRankSleeve(BaseSleeve):
    name = "momentum_rank"
    target_weight = 0.10
    rebalance_days = 21  # true monthly rebalance — cross-sectional momentum
                         # is documented at this cadence; intra-month reranks
                         # are churn without meaningful edge

    # Universe excludes SPY/QQQ (held by other sleeves, broad index)
    _exclude = frozenset({"SPY.NYSE", "QQQ.NASDAQ"})

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        returns: dict[str, float] = {}
        for symbol, df in bars.items():
            if symbol in self._exclude:
                continue
            history = df.loc[:as_of]
            if len(history) < _LOOKBACK_DAYS + 1:
                continue
            close = history["close"]
            past = close.iloc[-_LOOKBACK_DAYS]
            recent = close.iloc[-_SKIP_DAYS]
            if past <= 0:
                continue
            returns[symbol] = (recent - past) / past

        if not returns:
            return []

        ranked = sorted(returns.items(), key=lambda kv: kv[1], reverse=True)
        winners = [s for s, r in ranked[:_TOP_N] if r > 0]  # only long positive momo
        if not winners:
            return []

        weight_per = 1.0 / len(winners)
        signals: list[SleeveSignal] = []
        for symbol in bars:
            if symbol in self._exclude:
                continue
            w = weight_per if symbol in winners else 0.0
            signals.append(
                SleeveSignal(
                    symbol=symbol,
                    target_weight=w,
                    reason=(
                        f"momo_rank top{_TOP_N}: ret={returns.get(symbol, 0):.1%}"
                    ),
                )
            )
        return signals
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 8A159BC7616E - verify with scripts/authorship.py verify
