# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-BC9340D882B6
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Initial schema — all tables for Horizon Capital MVP.

Revision ID: 001
Revises: None
Create Date: 2026-03-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Market Instruments ---
    op.create_table(
        "market_instruments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("asset_class", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(5), nullable=False),
        sa.Column("lot_size", sa.Integer, server_default="1"),
        sa.Column("tick_size", sa.Float, server_default="0.01"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "exchange", name="uq_instrument_symbol_exchange"),
    )
    op.create_index("ix_instrument_symbol", "market_instruments", ["symbol"])

    # --- OHLCV ---
    op.create_table(
        "ohlcv",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.BigInteger, server_default="0"),
        sa.Column("open_interest", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "exchange", "timestamp", "timeframe", name="uq_ohlcv_symbol_ts_tf"),
    )
    op.create_index("ix_ohlcv_symbol_ts", "ohlcv", ["symbol", "timestamp"])
    op.create_index("ix_ohlcv_ts", "ohlcv", ["timestamp"])

    # --- Ticks ---
    op.create_table(
        "ticks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_price", sa.Float, nullable=False),
        sa.Column("bid", sa.Float, nullable=True),
        sa.Column("ask", sa.Float, nullable=True),
        sa.Column("volume", sa.BigInteger, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tick_symbol_ts", "ticks", ["symbol", "timestamp"])

    # --- Features ---
    op.create_table(
        "features",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "timestamp", "feature_name", "version", name="uq_feature"),
    )
    op.create_index("ix_feature_symbol_ts", "features", ["symbol", "timestamp"])

    # --- Regime States ---
    op.create_table(
        "regime_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("regime", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("market_scope", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_regime_scope", "regime_states", ["market_scope"])
    op.create_index("ix_regime_created", "regime_states", ["created_at"])

    # --- Signals ---
    op.create_table(
        "signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("direction", sa.Integer, nullable=False),
        sa.Column("strength", sa.Float, nullable=False),
        sa.Column("target_price", sa.Float, nullable=True),
        sa.Column("stop_loss", sa.Float, nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("strategy_name", sa.String(50), nullable=False),
        sa.Column("regime_at_signal", sa.String(20), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_signal_symbol", "signals", ["symbol"])
    op.create_index("ix_signal_active", "signals", ["is_active"])
    op.create_index("ix_signal_agent", "signals", ["agent_id"])

    # --- Debate Sessions ---
    op.create_table(
        "debate_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("proposed_action", sa.String(10), nullable=False),
        sa.Column("proposed_quantity", sa.Float, nullable=True),
        sa.Column("signal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="IN_PROGRESS"),
        sa.Column("final_decision", sa.String(20), nullable=True),
        sa.Column("consensus_score", sa.Float, nullable=True),
        sa.Column("total_rounds", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_debate_symbol", "debate_sessions", ["symbol"])
    op.create_index("ix_debate_status", "debate_sessions", ["status"])

    # --- Debate Arguments ---
    op.create_table(
        "debate_arguments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("argument", sa.Text, nullable=False),
        sa.Column("vote", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("round_number", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_debate_arg_session", "debate_arguments", ["session_id"])

    # --- Orders ---
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("limit_price", sa.Float, nullable=True),
        sa.Column("stop_price", sa.Float, nullable=True),
        sa.Column("status", sa.String(20), server_default="PENDING"),
        sa.Column("broker", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("signal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("debate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("broker_order_id", sa.String(100), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_order_symbol", "orders", ["symbol"])
    op.create_index("ix_order_status", "orders", ["status"])
    op.create_index("ix_order_signal", "orders", ["signal_id"])

    # --- Fills ---
    op.create_table(
        "fills",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filled_qty", sa.Float, nullable=False),
        sa.Column("fill_price", sa.Float, nullable=False),
        sa.Column("commission", sa.Float, server_default="0"),
        sa.Column("slippage", sa.Float, server_default="0"),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fill_order", "fills", ["order_id"])

    # --- Positions ---
    op.create_table(
        "positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Float, server_default="0"),
        sa.Column("avg_entry_price", sa.Float, server_default="0"),
        sa.Column("current_price", sa.Float, server_default="0"),
        sa.Column("unrealized_pnl", sa.Float, server_default="0"),
        sa.Column("realized_pnl", sa.Float, server_default="0"),
        sa.Column("weight_pct", sa.Float, server_default="0"),
        sa.Column("currency", sa.String(5), server_default="'USD'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_position_symbol", "positions", ["symbol", "exchange"], unique=True)

    # --- Portfolio Snapshots ---
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("total_value", sa.Float, nullable=False),
        sa.Column("cash_inr", sa.Float, server_default="0"),
        sa.Column("cash_usd", sa.Float, server_default="0"),
        sa.Column("equity_value", sa.Float, server_default="0"),
        sa.Column("crypto_value", sa.Float, server_default="0"),
        sa.Column("fno_value", sa.Float, server_default="0"),
        sa.Column("gross_leverage", sa.Float, server_default="0"),
        sa.Column("net_leverage", sa.Float, server_default="0"),
        sa.Column("usd_inr_rate", sa.Float, server_default="83.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Risk Metrics ---
    op.create_table(
        "risk_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("var_1d_95", sa.Float, server_default="0"),
        sa.Column("var_1d_99", sa.Float, server_default="0"),
        sa.Column("cvar_1d_95", sa.Float, server_default="0"),
        sa.Column("max_drawdown", sa.Float, server_default="0"),
        sa.Column("current_drawdown", sa.Float, server_default="0"),
        sa.Column("beta_india", sa.Float, server_default="0"),
        sa.Column("beta_us", sa.Float, server_default="0"),
        sa.Column("sharpe_30d", sa.Float, server_default="0"),
        sa.Column("kill_switch_active", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Risk Limits ---
    op.create_table(
        "risk_limits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("limit_name", sa.String(100), nullable=False, unique=True),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("action_on_breach", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Narratives ---
    op.create_table(
        "narratives",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("sentiment_score", sa.Float, nullable=False),
        sa.Column("relevance_score", sa.Float, server_default="1"),
        sa.Column("engagement_score", sa.Float, server_default="0"),
        sa.Column("lifecycle_stage", sa.String(20), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_narrative_symbol", "narratives", ["symbol"])
    op.create_index("ix_narrative_source", "narratives", ["source"])
    op.create_index("ix_narrative_published", "narratives", ["published_at"])

    # --- Sentiment Aggregates ---
    op.create_table(
        "sentiment_aggregates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("window", sa.String(10), nullable=False),
        sa.Column("avg_sentiment", sa.Float, server_default="0"),
        sa.Column("article_count", sa.Integer, server_default="0"),
        sa.Column("bull_pct", sa.Float, server_default="0"),
        sa.Column("bear_pct", sa.Float, server_default="0"),
        sa.Column("neutral_pct", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sentiment_agg_symbol_window", "sentiment_aggregates", ["symbol", "window"])

    # --- Agent States ---
    op.create_table(
        "agent_states",
        sa.Column("agent_id", sa.String(100), primary_key=True),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="STOPPED"),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config", JSONB, server_default="'{}'"),
        sa.Column("metrics", JSONB, server_default="'{}'"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Agent Messages ---
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.String(50), nullable=False, unique=True),
        sa.Column("sender_id", sa.String(100), nullable=False),
        sa.Column("receiver_id", sa.String(100), server_default="'*'"),
        sa.Column("channel", sa.String(200), nullable=False),
        sa.Column("message_type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB, server_default="'{}'"),
        sa.Column("correlation_id", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_msg_sender", "agent_messages", ["sender_id"])
    op.create_index("ix_agent_msg_channel", "agent_messages", ["channel"])
    op.create_index("ix_agent_msg_type", "agent_messages", ["message_type"])

    # --- Performance Snapshots ---
    op.create_table(
        "performance_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("total_return", sa.Float, server_default="0"),
        sa.Column("annualized_return", sa.Float, server_default="0"),
        sa.Column("sharpe_ratio", sa.Float, server_default="0"),
        sa.Column("sortino_ratio", sa.Float, server_default="0"),
        sa.Column("calmar_ratio", sa.Float, server_default="0"),
        sa.Column("max_drawdown", sa.Float, server_default="0"),
        sa.Column("win_rate", sa.Float, server_default="0"),
        sa.Column("profit_factor", sa.Float, server_default="0"),
        sa.Column("alpha_india", sa.Float, server_default="0"),
        sa.Column("alpha_us", sa.Float, server_default="0"),
        sa.Column("total_trades", sa.Integer, server_default="0"),
        sa.Column("attribution", JSONB, server_default="'{}'"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Seed default risk limits ---
    op.execute("""
        INSERT INTO risk_limits (id, limit_name, threshold, unit, action_on_breach) VALUES
        (uuid_generate_v4(), 'max_drawdown', 10.0, 'PCT', 'HALT'),
        (uuid_generate_v4(), 'max_position_size', 5.0, 'PCT', 'REDUCE'),
        (uuid_generate_v4(), 'max_leverage', 1.0, 'ABS', 'HALT'),
        (uuid_generate_v4(), 'var_1d_95_limit', 3.0, 'PCT', 'ALERT'),
        (uuid_generate_v4(), 'var_1d_99_limit', 5.0, 'PCT', 'REDUCE'),
        (uuid_generate_v4(), 'max_sector_concentration', 25.0, 'PCT', 'ALERT'),
        (uuid_generate_v4(), 'max_single_loss', 2.0, 'PCT', 'HALT');
    """)


def downgrade() -> None:
    tables = [
        "performance_snapshots", "agent_messages", "agent_states",
        "sentiment_aggregates", "narratives", "risk_limits", "risk_metrics",
        "portfolio_snapshots", "positions", "fills", "orders",
        "debate_arguments", "debate_sessions", "signals", "regime_states",
        "features", "ticks", "ohlcv", "market_instruments",
    ]
    for table in tables:
        op.drop_table(table)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token BC9340D882B6 - verify with scripts/authorship.py verify
