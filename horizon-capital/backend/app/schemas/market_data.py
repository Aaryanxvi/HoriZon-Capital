# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-FC09DF367357
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Market data schemas for quotes, OHLCV bars, and regime classification."""

from datetime import datetime

from pydantic import BaseModel, Field


class NormalizedTick(BaseModel):
    """A single normalized price tick."""

    symbol: str
    price: float
    volume: float
    timestamp: datetime
    source: str = Field(..., description="Originating data feed")

    model_config = {"from_attributes": True}


class NormalizedOHLCV(BaseModel):
    """A single normalized OHLCV bar."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime
    interval: str = Field(..., description="Bar interval, e.g. '1m', '5m', '1d'")

    model_config = {"from_attributes": True}


class QuoteResponse(BaseModel):
    """Real-time quote snapshot for a single instrument."""

    symbol: str
    bid: float
    ask: float
    last: float
    volume: float
    timestamp: datetime
    source: str | None = None

    model_config = {"from_attributes": True}


class OHLCVResponse(BaseModel):
    """Response wrapper for a series of OHLCV bars."""

    symbol: str
    interval: str
    bars: list[NormalizedOHLCV]
    count: int


class RegimeResponse(BaseModel):
    """Current market regime classification."""

    regime: str = Field(
        ..., description="Detected regime label, e.g. 'trending', 'mean_reverting', 'volatile'"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    features: dict[str, float] = Field(
        default_factory=dict, description="Feature values that drove the classification"
    )
    timestamp: datetime
    model_version: str | None = None

    model_config = {"from_attributes": True}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token FC09DF367357 - verify with scripts/authorship.py verify
