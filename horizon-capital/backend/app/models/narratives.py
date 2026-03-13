"""Sentiment and narrative models."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Narrative(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "narratives"

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # NEWSAPI, REDDIT, TWITTER
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)  # -1.0 to 1.0
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)  # BIRTH, ACCELERATION, PEAK, DECAY
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_narrative_symbol", "symbol"),
        Index("ix_narrative_source", "source"),
        Index("ix_narrative_published", "published_at"),
    )


class SentimentAggregate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sentiment_aggregates"

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    window: Mapped[str] = mapped_column(String(10), nullable=False)  # 1h, 4h, 24h, 14d
    avg_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    bull_pct: Mapped[float] = mapped_column(Float, default=0.0)
    bear_pct: Mapped[float] = mapped_column(Float, default=0.0)
    neutral_pct: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (
        Index("ix_sentiment_agg_symbol_window", "symbol", "window"),
    )
