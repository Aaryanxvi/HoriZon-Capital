"""Portfolio snapshot model."""

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PortfolioSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "portfolio_snapshots"

    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash_inr: Mapped[float] = mapped_column(Float, default=0.0)
    cash_usd: Mapped[float] = mapped_column(Float, default=0.0)
    equity_value: Mapped[float] = mapped_column(Float, default=0.0)
    crypto_value: Mapped[float] = mapped_column(Float, default=0.0)
    fno_value: Mapped[float] = mapped_column(Float, default=0.0)
    gross_leverage: Mapped[float] = mapped_column(Float, default=0.0)
    net_leverage: Mapped[float] = mapped_column(Float, default=0.0)
    usd_inr_rate: Mapped[float] = mapped_column(Float, default=83.0)
