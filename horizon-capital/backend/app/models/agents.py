"""Agent state and message models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentState(Base, TimestampMixin):
    __tablename__ = "agent_states"

    agent_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="STOPPED")  # RUNNING, PAUSED, ERROR, STOPPED
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentMessageRecord(Base, TimestampMixin):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    sender_id: Mapped[str] = mapped_column(String(100), nullable=False)
    receiver_id: Mapped[str] = mapped_column(String(100), default="*")
    channel: Mapped[str] = mapped_column(String(200), nullable=False)
    message_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_agent_msg_sender", "sender_id"),
        Index("ix_agent_msg_channel", "channel"),
        Index("ix_agent_msg_type", "message_type"),
    )
