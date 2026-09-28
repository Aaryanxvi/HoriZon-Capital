# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-34107CA25F13
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Market data models: instruments, OHLCV, ticks."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class MarketInstrument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "market_instruments"

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)  # NSE, BSE, NASDAQ, NYSE
    asset_class: Mapped[str] = mapped_column(String(20), nullable=False)  # EQUITY, F&O, CRYPTO
    currency: Mapped[str] = mapped_column(String(5), nullable=False)  # INR, USD
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[float] = mapped_column(Float, default=0.01)
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        UniqueConstraint("symbol", "exchange", name="uq_instrument_symbol_exchange"),
        Index("ix_instrument_symbol", "symbol"),
    )


class OHLCV(Base, TimestampMixin):
    __tablename__ = "ohlcv"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(5), nullable=False)  # 1m, 5m, 1h, 1d
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "exchange", "timestamp", "timeframe",
            name="uq_ohlcv_symbol_ts_tf",
        ),
        Index("ix_ohlcv_symbol_ts", "symbol", "timestamp"),
        Index("ix_ohlcv_ts", "timestamp"),
    )


class Tick(Base, TimestampMixin):
    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_price: Mapped[float] = mapped_column(Float, nullable=False)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)

    __table_args__ = (
        Index("ix_tick_symbol_ts", "symbol", "timestamp"),
    )
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 34107CA25F13 - verify with scripts/authorship.py verify
