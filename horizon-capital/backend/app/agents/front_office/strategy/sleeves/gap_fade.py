"""Overnight gap-fade sleeve on QQQ.

Thesis: large-cap US equity indices exhibit a small but persistent reversal
of overnight gaps during the regular session. A gap-down open tends to drift
back toward the prior close by end of day. One trade per day, at most.

Implementation detail: this sleeve is designed for a daily-bar universe. For
backtest purposes we treat the 'open' as the fill reference and the 'close'
as the exit reference. In live trading the portfolio agent should route a
MARKET BUY at the 9:30 open and a MARKET SELL near 15:55 ET.
"""

from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_INSTRUMENT = "QQQ.NASDAQ"
# Keep threshold relatively low — tightening it removed most of the sleeve's
# contribution in backtest. Real edge lives in all gap-downs above noise.
_GAP_THRESHOLD = 0.003


class GapFadeSleeve(BaseSleeve):
    name = "gap_fade"
    target_weight = 0.10
    rebalance_days = 1  # inspects every day; only trades when a gap triggers

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        df = bars.get(_INSTRUMENT)
        if df is None or len(df) < 2:
            return []

        history = df.loc[:as_of]
        if len(history) < 2:
            return []

        prev_close = history["close"].iloc[-2]
        today_open = history["open"].iloc[-1]
        if prev_close <= 0:
            return []

        gap = (today_open - prev_close) / prev_close

        if gap <= -_GAP_THRESHOLD:
            return [
                SleeveSignal(
                    symbol=_INSTRUMENT,
                    target_weight=1.0,
                    reason=f"gap_down {gap:.2%} — fade",
                )
            ]
        return [
            SleeveSignal(
                symbol=_INSTRUMENT,
                target_weight=0.0,
                reason=f"no_gap ({gap:.2%})",
            )
        ]
