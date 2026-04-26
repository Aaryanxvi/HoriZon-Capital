"""Trend-filter sleeve: long SPY when regime is risk-on, cash otherwise.

Reference: Faber, "A Quantitative Approach to Tactical Asset Allocation" (2007).
Simple 200-day SMA rule captures most US-equity bull runs while sidestepping
the deepest drawdowns (2008, 2020, 2022). We add a realised-vol filter on top
so we also sit out vol-spike periods where trend whipsaws.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_INSTRUMENT = "SPY.NYSE"
_SMA_WINDOW = 200
_VOL_WINDOW = 20
_VOL_ANNUAL_CAP = 0.30  # cash when 20d annualised vol exceeds 30%


class TrendFilterSleeve(BaseSleeve):
    name = "trend_filter"
    target_weight = 0.20  # complements research_stack (0.60)
    rebalance_days = 5  # weekly check — trend doesn't flip intra-week

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        df = bars.get(_INSTRUMENT)
        if df is None or len(df) < _SMA_WINDOW + 1:
            return []

        history = df.loc[:as_of]
        if len(history) < _SMA_WINDOW + 1:
            return []

        close = history["close"]
        sma = close.rolling(_SMA_WINDOW).mean().iloc[-1]
        price = close.iloc[-1]
        rets = close.pct_change().dropna()
        vol = rets.tail(_VOL_WINDOW).std() * np.sqrt(252)

        in_trend = bool(price > sma)
        low_vol = bool(vol < _VOL_ANNUAL_CAP)

        if in_trend and low_vol:
            return [
                SleeveSignal(
                    symbol=_INSTRUMENT,
                    target_weight=1.0,
                    reason=f"SPY>{_SMA_WINDOW}d SMA ({price:.2f}>{sma:.2f}), vol {vol:.0%}",
                )
            ]
        return [
            SleeveSignal(
                symbol=_INSTRUMENT,
                target_weight=0.0,
                reason=f"regime_off (trend={in_trend}, low_vol={low_vol}, vol={vol:.0%})",
            )
        ]
