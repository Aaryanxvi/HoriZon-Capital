"""SQLite-based local storage for running without PostgreSQL.

Provides the same async session interface as database.py but backed by
aiosqlite so the system can run on any machine with zero infrastructure.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Store database in user data directory
_DATA_DIR = Path(os.getenv("HORIZON_DATA_DIR", Path.home() / ".horizon-capital"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "horizon.db"

_SQLITE_URL = f"sqlite+aiosqlite:///{_DB_PATH}"

local_engine = create_async_engine(
    _SQLITE_URL,
    echo=settings.app_debug,
    connect_args={"check_same_thread": False},
)


@event.listens_for(local_engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
    """busy_timeout is per-connection — set it on every connection the pool opens,
    not just the one used by init_local_db's PRAGMA/CREATE TABLE pass."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

local_session_factory = async_sessionmaker(
    local_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_local_db() -> AsyncGenerator[AsyncSession, None]:
    async with local_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_local_db() -> None:
    """Create all tables for local SQLite mode."""
    async with local_engine.begin() as conn:
        await conn.run_sync(_create_tables)


_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _migrate_table(conn, table: str, required_col: str) -> None:  # noqa: ANN001
    """Add a missing column to an existing table (non-destructive migration)."""
    if not _SAFE_IDENTIFIER.match(table) or not _SAFE_IDENTIFIER.match(required_col):
        return
    try:
        cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()  # noqa: S608
        col_names = {row[1] for row in cols}
        if cols and required_col not in col_names:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {required_col} TEXT DEFAULT NULL")  # noqa: S608
            )
    except Exception:
        pass


def _create_tables(conn) -> None:  # noqa: ANN001
    """Create all tables using raw SQL compatible with SQLite."""
    # Enable WAL mode for better concurrent read/write performance
    conn.execute(text("PRAGMA journal_mode=WAL"))

    # --- KV cache (persistent key-value store for crash recovery) ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS kv_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Cash balances (source of truth; KV is mirror only) ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cash_balances (
            currency TEXT PRIMARY KEY,
            amount REAL NOT NULL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Core agent infrastructure ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_states (
            agent_id TEXT PRIMARY KEY,
            agent_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'INIT',
            last_heartbeat TIMESTAMP,
            config TEXT DEFAULT '{}',
            metrics TEXT DEFAULT '{}',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL UNIQUE,
            sender_id TEXT NOT NULL,
            receiver_id TEXT DEFAULT '*',
            channel TEXT NOT NULL,
            message_type TEXT NOT NULL,
            payload TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Signals ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL UNIQUE,
            agent_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            strength REAL DEFAULT 0.0,
            confidence REAL DEFAULT 0.0,
            strategy_name TEXT,
            regime TEXT,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Orders, fills, positions (matches ORM in trades.py) ---
    _migrate_table(conn, "positions", "stop_loss_price")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            order_type TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            limit_price REAL,
            stop_price REAL,
            status TEXT DEFAULT 'PENDING',
            broker TEXT NOT NULL,
            mode TEXT NOT NULL,
            signal_id TEXT,
            debate_id TEXT,
            broker_order_id TEXT,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_symbol ON orders (symbol)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_status ON orders (status)"))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            filled_qty REAL NOT NULL,
            fill_price REAL NOT NULL,
            commission REAL DEFAULT 0.0,
            slippage REAL DEFAULT 0.0,
            filled_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fill_order ON fills (order_id)"))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL DEFAULT 0.0,
            avg_entry_price REAL DEFAULT 0.0,
            current_price REAL DEFAULT 0.0,
            unrealized_pnl REAL DEFAULT 0.0,
            realized_pnl REAL DEFAULT 0.0,
            weight_pct REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            stop_loss_price REAL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (symbol, exchange)
        )
    """))

    # Legacy trades table (kept for backward compatibility)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL UNIQUE,
            signal_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL,
            status TEXT DEFAULT 'PENDING',
            broker TEXT,
            order_type TEXT DEFAULT 'MARKET',
            filled_price REAL,
            filled_quantity REAL,
            pnl REAL,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Portfolio snapshots (matches ORM in portfolio.py) ---
    _migrate_table(conn, "portfolio_snapshots", "total_value")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id TEXT PRIMARY KEY,
            total_value REAL NOT NULL DEFAULT 0.0,
            cash_inr REAL DEFAULT 0.0,
            cash_usd REAL DEFAULT 0.0,
            equity_value REAL DEFAULT 0.0,
            crypto_value REAL DEFAULT 0.0,
            fno_value REAL DEFAULT 0.0,
            gross_leverage REAL DEFAULT 0.0,
            net_leverage REAL DEFAULT 0.0,
            usd_inr_rate REAL DEFAULT 83.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Risk metrics ---
    _migrate_table(conn, "risk_metrics", "var_1d_95")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS risk_metrics (
            id TEXT PRIMARY KEY,
            var_1d_95 REAL DEFAULT 0.0,
            var_1d_99 REAL DEFAULT 0.0,
            cvar_1d_95 REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            current_drawdown REAL DEFAULT 0.0,
            kill_switch_active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Debate sessions and arguments ---
    _migrate_table(conn, "debate_sessions", "proposed_action")
    _migrate_table(conn, "debate_sessions", "reason")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS debate_sessions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL DEFAULT 'UNKNOWN',
            proposed_action TEXT,
            proposed_quantity REAL,
            signal_id TEXT,
            status TEXT DEFAULT 'IN_PROGRESS',
            total_rounds INTEGER DEFAULT 1,
            final_decision TEXT,
            consensus_score REAL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS debate_arguments (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT NOT NULL,
            argument TEXT,
            vote TEXT,
            confidence REAL DEFAULT 0.0,
            round_number INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_debate_arg_session "
        "ON debate_arguments (session_id)"
    ))

    # --- Regime states ---
    _migrate_table(conn, "regime_states", "method")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS regime_states (
            id TEXT PRIMARY KEY,
            regime TEXT NOT NULL,
            confidence REAL DEFAULT 0.0,
            method TEXT,
            market_scope TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Performance snapshots ---
    _migrate_table(conn, "performance_snapshots", "period")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS performance_snapshots (
            id TEXT PRIMARY KEY,
            period TEXT NOT NULL DEFAULT 'ALL',
            total_return REAL DEFAULT 0.0,
            annualized_return REAL DEFAULT 0.0,
            sharpe_ratio REAL DEFAULT 0.0,
            sortino_ratio REAL DEFAULT 0.0,
            calmar_ratio REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            win_rate REAL DEFAULT 0.0,
            profit_factor REAL DEFAULT 0.0,
            alpha_india REAL DEFAULT 0.0,
            alpha_us REAL DEFAULT 0.0,
            total_trades INTEGER DEFAULT 0,
            attribution TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Narratives (news/sentiment articles) ---
    _migrate_table(conn, "narratives", "headline")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS narratives (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            source TEXT,
            headline TEXT NOT NULL,
            url TEXT,
            sentiment_score REAL DEFAULT 0.0,
            relevance_score REAL DEFAULT 1.0,
            engagement_score REAL DEFAULT 0.0,
            lifecycle_stage TEXT DEFAULT 'EMERGING',
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_narrative_symbol ON narratives (symbol)"))

    # --- Sentiment aggregates ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sentiment_aggregates (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            window TEXT NOT NULL,
            avg_sentiment REAL DEFAULT 0.0,
            article_count INTEGER DEFAULT 0,
            bull_pct REAL DEFAULT 0.0,
            bear_pct REAL DEFAULT 0.0,
            neutral_pct REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (symbol, window)
        )
    """))

    # --- OHLCV price data ---
    _migrate_table(conn, "ohlcv", "exchange")
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            exchange TEXT DEFAULT 'UNKNOWN',
            timeframe TEXT DEFAULT '1d',
            timestamp TIMESTAMP NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            open_interest REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (symbol, exchange, timeframe, timestamp)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ohlcv_symbol_ts ON ohlcv (symbol, timestamp)"))

    # --- Feature snapshots ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS feature_snapshots (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '1d',
            features TEXT DEFAULT '{}',
            computed_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (symbol, exchange, timeframe)
        )
    """))

    # --- Alert history ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id TEXT PRIMARY KEY,
            rule_name TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT,
            channels TEXT DEFAULT '[]',
            acknowledged INTEGER DEFAULT 0,
            payload TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_alert_severity ON alert_history (severity)"))

    # --- Model registry ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS model_versions (
            id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            version INTEGER NOT NULL,
            model_type TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            parameters TEXT DEFAULT '{}',
            metrics TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_model_name ON model_versions (model_name)"))

    # --- Strategy rotation history ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS strategy_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            reward REAL,
            posterior_mean REAL,
            n_observations INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Stress test results ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS stress_test_results (
            id TEXT PRIMARY KEY,
            scenario_key TEXT NOT NULL,
            portfolio_value REAL,
            impact_pct REAL,
            impact_abs REAL,
            risk_score REAL,
            details TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Reports ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            report_type TEXT NOT NULL,
            period_start TIMESTAMP,
            period_end TIMESTAMP,
            total_return REAL DEFAULT 0.0,
            sharpe_ratio REAL DEFAULT 0.0,
            portfolio_value REAL DEFAULT 0.0,
            content TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Health snapshots ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agents_running INTEGER DEFAULT 0,
            agents_total INTEGER DEFAULT 0,
            messages_per_minute REAL DEFAULT 0.0,
            memory_mb REAL DEFAULT 0.0,
            cpu_percent REAL DEFAULT 0.0,
            uptime_hours REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # --- Backtest runs ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL,
            start_date TIMESTAMP NOT NULL,
            end_date TIMESTAMP NOT NULL,
            bars_processed INTEGER DEFAULT 0,
            initial_capital REAL DEFAULT 0.0,
            final_capital REAL DEFAULT 0.0,
            total_return REAL DEFAULT 0.0,
            sharpe_ratio REAL DEFAULT 0.0,
            max_drawdown REAL DEFAULT 0.0,
            win_rate REAL DEFAULT 0.0,
            total_trades INTEGER DEFAULT 0,
            metrics TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_backtest_symbol ON backtest_runs (symbol)"
    ))

    # --- CIO Advisories ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cio_advisories (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            outlook TEXT NOT NULL,
            summary TEXT NOT NULL,
            recommended_adjustments TEXT NOT NULL,
            risk_flags TEXT NOT NULL,
            provider TEXT NOT NULL,
            trigger TEXT NOT NULL
        )
    """))

    # --- CIO Overrides ---
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cio_overrides (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            trigger TEXT NOT NULL,
            confidence REAL NOT NULL,
            actions TEXT NOT NULL,
            full_prompt TEXT NOT NULL,
            full_response TEXT NOT NULL,
            portfolio_snapshot TEXT NOT NULL,
            provider TEXT NOT NULL
        )
    """))

    conn.commit()
