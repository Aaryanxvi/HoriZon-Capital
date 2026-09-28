# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1100C536AD62
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Crypto trend sleeve: long BTC/ETH when regime is risk-on, cash otherwise.

UNVALIDATED — no pre-registered gate pass. Default-disabled; enable via
CRYPTO_SLEEVE_ENABLED. Do not enable in the validated live mix without a
fresh gate.

Universe is BTC/ETH by default, or the top-N by market cap (stablecoins and
wrapped/staked derivatives removed, broker-tradability enforced) when
CRYPTO_DISCOVERY_ENABLED is set — see ``data_layer/crypto_universe.py``.

Reference: Faber, "A Quantitative Approach to Tactical Asset Allocation" (2007).
Same 200-day SMA rule as ``trend_filter.py`` applied to crypto instead of SPY,
with a vol damper instead of a hard cash-out (crypto trend regimes stay intact
through vol spikes more often than equities do — halving the position rather
than exiting keeps some of the trend exposure).
"""

from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal

_UNIVERSE = ("BTC-USD", "ETH-USD")
_SMA_DAYS = 200
_VOL_LOOKBACK = 20
_VOL_CAP = 0.60  # annualized vol above this -> halve the position


class CryptoTrendSleeve(BaseSleeve):
    name = "crypto_trend"
    target_weight = 0.10  # class default; live weight set by _weighted()
    rebalance_days = 1  # daily check — crypto trades 24/7

    _UNIVERSE = _UNIVERSE
    _SMA_DAYS = _SMA_DAYS
    _VOL_LOOKBACK = _VOL_LOOKBACK
    _VOL_CAP = _VOL_CAP

    def universe(self) -> tuple[str, ...]:
        """BTC/ETH, or the market-cap-ranked list when discovery is on."""
        from app.data_layer.crypto_universe import crypto_universe

        return crypto_universe() or self._UNIVERSE

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        signals: list[SleeveSignal] = []
        universe = self.universe()
        for symbol in universe:
            df = bars.get(symbol)
            if df is None:
                continue
            history = df.loc[:as_of]
            if len(history) < self._SMA_DAYS + 1:
                continue

            close = history["close"]
            sma = close.rolling(self._SMA_DAYS).mean().iloc[-1]
            in_trend = bool(close.iloc[-1] > sma)
            if not in_trend:
                continue

            weight = 1.0 / len(universe)
            # 365 not 252 — crypto trades every day.
            ann_vol = close.pct_change().iloc[-self._VOL_LOOKBACK:].std() * (365 ** 0.5)
            if ann_vol > self._VOL_CAP:
                weight /= 2

            signals.append(
                SleeveSignal(
                    symbol=symbol,
                    target_weight=weight,
                    reason=f"200d trend up, ann_vol={ann_vol:.2f}",
                )
            )
        return signals
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1100C536AD62 - verify with scripts/authorship.py verify
