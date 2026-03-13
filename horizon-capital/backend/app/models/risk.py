"""Risk models: metrics and limits."""

from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class RiskMetric(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "risk_metrics"

    var_1d_95: Mapped[float] = mapped_column(Float, default=0.0)
    var_1d_99: Mapped[float] = mapped_column(Float, default=0.0)
    cvar_1d_95: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    current_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    beta_india: Mapped[float] = mapped_column(Float, default=0.0)
    beta_us: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe_30d: Mapped[float] = mapped_column(Float, default=0.0)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, default=False)


class RiskLimit(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "risk_limits"

    limit_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)  # PCT, ABS
    action_on_breach: Mapped[str] = mapped_column(String(20), nullable=False)  # ALERT, REDUCE, HALT
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
