"""Performance tracking model."""

from sqlalchemy import Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PerformanceSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "performance_snapshots"

    period: Mapped[str] = mapped_column(String(20), nullable=False)  # 1d, 7d, 30d, 90d, YTD, ALL
    total_return: Mapped[float] = mapped_column(Float, default=0.0)
    annualized_return: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    sortino_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    calmar_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    alpha_india: Mapped[float] = mapped_column(Float, default=0.0)  # vs NIFTY
    alpha_us: Mapped[float] = mapped_column(Float, default=0.0)  # vs SPX
    total_trades: Mapped[int] = mapped_column(default=0)
    attribution: Mapped[dict] = mapped_column(JSONB, default=dict)  # Per-strategy breakdown
