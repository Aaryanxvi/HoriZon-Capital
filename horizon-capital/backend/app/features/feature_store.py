"""Feature store: persists computed features to PostgreSQL and caches in Redis.

The ``features`` table stores versioned, timestamped feature snapshots per
symbol.  Redis hashes provide low-latency reads for the live trading pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis_client import redis_client

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
        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO features (symbol, timestamp, features, version, created_at, updated_at)
                    VALUES (:symbol, :ts, :features::jsonb, :version, :now, :now)
                    ON CONFLICT (symbol, timestamp, version)
                    DO UPDATE SET features = EXCLUDED.features, updated_at = EXCLUDED.updated_at
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

    # ------------------------------------------------------------------
    # Redis cache (low-latency access for live pipeline)
    # ------------------------------------------------------------------

    @staticmethod
    async def cache_features(symbol: str, features: dict) -> None:
        """Write the latest features into a Redis hash ``horizon:features:{symbol}``.

        Each feature key is stored as a separate hash field so individual
        look-ups are O(1).
        """
        key = f"horizon:features:{symbol}"
        # Flatten nested values to JSON strings for Redis storage
        mapping: dict[str, str] = {}
        for k, v in features.items():
            if isinstance(v, (dict, list)):
                mapping[k] = json.dumps(v)
            else:
                mapping[k] = str(v)

        if mapping:
            await redis_client.hset(key, mapping=mapping)
            # Expire after 1 hour to avoid stale data accumulation
            await redis_client.expire(key, 3600)
        logger.debug("features_cached", symbol=symbol, n_fields=len(mapping))

    @staticmethod
    async def get_cached_features(symbol: str) -> dict:
        """Read all cached features for *symbol* from Redis.

        Returns
        -------
        dict
            Feature dict with string values (caller should cast as needed).
            Returns empty dict if the key does not exist.
        """
        key = f"horizon:features:{symbol}"
        raw = await redis_client.hgetall(key)

        if not raw:
            return {}

        # Attempt to parse JSON-encoded values back to Python objects
        result: dict = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v

        return result
