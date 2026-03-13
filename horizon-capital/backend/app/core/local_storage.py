"""SQLite-based local storage for running without PostgreSQL.

Provides the same async session interface as database.py but backed by
aiosqlite so the system can run on any machine with zero infrastructure.
"""

from __future__ import annotations

import os
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


def _create_tables(conn) -> None:  # noqa: ANN001
    """Create tables using raw SQL compatible with SQLite."""
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
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nav REAL NOT NULL,
            cash REAL NOT NULL,
            positions TEXT DEFAULT '{}',
            allocation TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS risk_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            var_95 REAL,
            var_99 REAL,
            max_drawdown REAL,
            current_drawdown REAL,
            sharpe_ratio REAL,
            sortino_ratio REAL,
            beta REAL,
            correlation_matrix TEXT DEFAULT '{}',
            kill_switch_active INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS debate_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            trigger_signal_id TEXT,
            status TEXT DEFAULT 'IN_PROGRESS',
            consensus TEXT,
            consensus_confidence REAL,
            rounds INTEGER DEFAULT 0,
            arguments TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS regime_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime TEXT NOT NULL,
            confidence REAL,
            transition_probs TEXT DEFAULT '{}',
            drift_detected INTEGER DEFAULT 0,
            features TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_return REAL,
            daily_return REAL,
            sharpe_ratio REAL,
            max_drawdown REAL,
            win_rate REAL,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS narratives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            narrative_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            sentiment_score REAL,
            source TEXT,
            symbols TEXT DEFAULT '[]',
            lifecycle_stage TEXT DEFAULT 'EMERGING',
            strength REAL DEFAULT 0.0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()
