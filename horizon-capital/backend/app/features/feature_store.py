# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D2BD90FE7175
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Feature store: persists computed features to PostgreSQL and caches in Redis.

The ``features`` table stores versioned, timestamped feature snapshots per
symbol.  Redis hashes provide low-latency reads for the live trading pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger

logger = get_logger("features.store")


class FeatureStore:
    """Read / write feature vectors to PostgreSQL and Redis."""

    # ------------------------------------------------------------------
    # PostgreSQL persistence
    # ------------------------------------------------------------------

    @staticmethod
    async def write_features(
        symbol: str,
        timestamp: datetime,
        features: dict,
        version: int = 1,
    ) -> None:
        """Upsert a feature snapshot for *symbol* at *timestamp*.

        The ``features`` table is expected to have columns:
        ``symbol, timestamp, features (JSONB), version, created_at, updated_at``.
        """
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO features
                        (symbol, timestamp, features, version, created_at, updated_at)
                    VALUES (:symbol, :ts, :features, :version, :now, :now)
                    ON CONFLICT (symbol, timestamp, version)
                    DO UPDATE SET features = EXCLUDED.features,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "symbol": symbol,
                    "ts": timestamp,
                    "features": json.dumps(features),
                    "version": version,
                    "now": now,
                },
            )
            await session.commit()
        logger.info("features_written", symbol=symbol, ts=str(timestamp), version=version)

    @staticmethod
    async def read_features(symbol: str, timestamp: datetime) -> dict:
        """Read the most recent feature snapshot for *symbol* at or before *timestamp*.

        Returns
        -------
        dict
            The feature dict, or empty dict if nothing found.
        """
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT features
                    FROM features
                    WHERE symbol = :symbol AND timestamp <= :ts
                    ORDER BY timestamp DESC, version DESC
                    LIMIT 1
                    """
                ),
                {"symbol": symbol, "ts": timestamp},
            )
            row = result.fetchone()

        if row is None:
            return {}

        raw = row[0]
        if isinstance(raw, str):
            return json.loads(raw)
        return dict(raw) if raw else {}

# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D2BD90FE7175 - verify with scripts/authorship.py verify
