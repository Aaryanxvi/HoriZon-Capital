# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-FB2192D6D787
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Debate engine models."""

import uuid

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DebateSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "debate_sessions"

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY, SELL
    proposed_quantity: Mapped[float] = mapped_column(Float, nullable=True)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # IN_PROGRESS, CONCLUDED
    status: Mapped[str] = mapped_column(String(20), default="IN_PROGRESS")
    # APPROVED, REJECTED
    final_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consensus_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0 - 1.0
    total_rounds: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_debate_symbol", "symbol"),
        Index("ix_debate_status", "status"),
    )


class DebateArgument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "debate_arguments"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # STRATEGY, RISK, SENTIMENT, PORTFOLIO
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    argument: Mapped[str] = mapped_column(Text, nullable=False)
    vote: Mapped[str] = mapped_column(String(10), nullable=False)  # FOR, AGAINST, ABSTAIN
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    round_number: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_debate_arg_session", "session_id"),
    )
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token FB2192D6D787 - verify with scripts/authorship.py verify
