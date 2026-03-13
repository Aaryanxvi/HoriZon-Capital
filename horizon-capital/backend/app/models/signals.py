"""Trading signal model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Signal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "signals"

    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 BUY, -1 SELL, 0 NEUTRAL
    strength: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    regime_at_signal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        Index("ix_signal_symbol", "symbol"),
        Index("ix_signal_active", "is_active"),
        Index("ix_signal_agent", "agent_id"),
    )
