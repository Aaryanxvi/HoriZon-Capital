# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-994820B1E063
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Base types for strategy sleeves.

A sleeve is a stateless object given {symbol -> history DataFrame} and asked
to produce target weights for its slice of the portfolio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class SleeveSignal:
    """A sleeve's opinion on where capital should sit for one symbol."""

    symbol: str
    target_weight: float  # fraction of THE SLEEVE'S capital, in [-1, 1]
    reason: str = ""


class BaseSleeve(ABC):
    """A portfolio sleeve with a fixed weight inside the overall portfolio."""

    name: str = "base"
    target_weight: float = 0.0  # fraction of total NAV allocated to this sleeve
    # Rebalance cadence in trading days. 1 = daily, 5 = weekly, 21 = monthly.
    # Controls how often the backtest / strategy agent consults this sleeve.
    rebalance_days: int = 5

    @abstractmethod
    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        """Return per-symbol target weights given history up to ``as_of``."""
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 994820B1E063 - verify with scripts/authorship.py verify
