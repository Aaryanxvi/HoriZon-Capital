# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-061F4F208FC0
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Narrative and sentiment analysis schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class SentimentResponse(BaseModel):
    """Sentiment score for a symbol or topic."""

    symbol: str | None = None
    topic: str | None = None
    score: float = Field(..., ge=-1.0, le=1.0, description="Negative = bearish, positive = bullish")
    magnitude: float = Field(
        ..., ge=0.0, description="Strength of sentiment regardless of direction"
    )
    source_count: int = Field(..., ge=0, description="Number of sources analysed")
    sources: list[str] = Field(default_factory=list, description="Feed names that contributed")
    timestamp: datetime

    model_config = {"from_attributes": True}


class NarrativeResponse(BaseModel):
    """A market narrative detected by the sentiment agent."""

    id: str
    title: str
    summary: str
    sentiment: float = Field(..., ge=-1.0, le=1.0)
    symbols: list[str] = Field(
        default_factory=list, description="Tickers related to this narrative"
    )
    themes: list[str] = Field(
        default_factory=list, description="Thematic tags, e.g. 'inflation', 'earnings'"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    source_urls: list[str] = Field(default_factory=list)
    detected_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 061F4F208FC0 - verify with scripts/authorship.py verify
