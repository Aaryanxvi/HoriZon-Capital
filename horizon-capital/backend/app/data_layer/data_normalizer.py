# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-650E926F352C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Pydantic models that every feed normalizes data into."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class NormalizedTick(BaseModel):
    """A single price tick from any exchange / feed."""

    symbol: str = Field(..., description="Canonical symbol, e.g. RELIANCE")
    exchange: str = Field(..., description="Exchange code, e.g. NSE, NASDAQ")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_price: float
    bid: float | None = None
    ask: float | None = None
    volume: int = 0
    currency: str = "USD"

    def to_redis_dict(self) -> dict[str, str]:
        """Flat string dict suitable for ``HSET``."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timestamp": self.timestamp.isoformat(),
            "last_price": str(self.last_price),
            "bid": str(self.bid) if self.bid is not None else "",
            "ask": str(self.ask) if self.ask is not None else "",
            "volume": str(self.volume),
            "currency": self.currency,
        }

    @classmethod
    def from_redis_dict(cls, data: dict[str, str]) -> NormalizedTick:
        """Reconstruct from the flat dict stored in Redis."""
        return cls(
            symbol=data["symbol"],
            exchange=data["exchange"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            last_price=float(data["last_price"]),
            bid=float(data["bid"]) if data.get("bid") else None,
            ask=float(data["ask"]) if data.get("ask") else None,
            volume=int(data.get("volume", 0)),
            currency=data.get("currency", "USD"),
        )


class NormalizedOHLCV(BaseModel):
    """One OHLCV bar from any feed / timeframe."""

    symbol: str
    exchange: str
    timestamp: datetime
    timeframe: str = "1d"  # 1m, 5m, 15m, 1h, 1d, 1w
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    open_interest: float | None = None
    currency: str = "USD"

    def to_redis_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "open_interest": str(self.open_interest) if self.open_interest is not None else "",
            "currency": self.currency,
        }

    @classmethod
    def from_redis_dict(cls, data: dict[str, str]) -> NormalizedOHLCV:
        return cls(
            symbol=data["symbol"],
            exchange=data["exchange"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            timeframe=data.get("timeframe", "1d"),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data.get("volume", 0)),
            open_interest=float(data["open_interest"]) if data.get("open_interest") else None,
            currency=data.get("currency", "USD"),
        )
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 650E926F352C - verify with scripts/authorship.py verify
