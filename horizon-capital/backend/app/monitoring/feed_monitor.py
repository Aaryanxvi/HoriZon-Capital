"""Data feed staleness monitor.

Checks Redis keys that data feeds update on every tick / bar to detect when
a feed has gone silent.  Each feed is expected to set a Redis key
``horizon:feed:{feed_name}:last_update`` with a UTC ISO timestamp on every
successful ingest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.core.redis_client import redis_client

logger = get_logger("monitoring.feeds")

# A feed is considered stale if no new data arrives within this window.
STALENESS_THRESHOLD_SECONDS = 60

# Known feed names that should be actively publishing.
DEFAULT_FEEDS = [
    "yahoo",
    "alpaca",
    "zerodha",
    "crypto",
    "forex",
]


class FeedMonitor:
    """Monitor data feed liveness via Redis timestamps."""

    def __init__(self, feeds: list[str] | None = None) -> None:
        self.feeds = feeds or DEFAULT_FEEDS

    async def check_feed_staleness(self) -> list[dict]:
        """Check all registered feeds for staleness.

        Each feed is expected to maintain a Redis key:
        ``horizon:feed:{feed_name}:last_update`` containing an ISO-8601
        timestamp updated on every successful data ingestion.

        Returns
        -------
        list[dict]
            One entry per stale (or missing) feed:
            ``{feed, last_update, seconds_since, stale}``.
        """
        now = datetime.now(UTC)
        threshold = now - timedelta(seconds=STALENESS_THRESHOLD_SECONDS)
        stale_feeds: list[dict] = []

        for feed_name in self.feeds:
            key = f"horizon:feed:{feed_name}:last_update"
            raw_ts = await redis_client.get(key)

            if raw_ts is None:
                # Key does not exist -- feed may not have started yet
                stale_feeds.append({
                    "feed": feed_name,
                    "last_update": None,
                    "seconds_since": None,
                    "stale": True,
                    "reason": "no_key",
                })
                continue

            try:
                ts_str = raw_ts if isinstance(raw_ts, str) else raw_ts.decode("utf-8")
                last_update = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if last_update.tzinfo is None:
                    last_update = last_update.replace(tzinfo=UTC)
            except (ValueError, AttributeError) as exc:
                stale_feeds.append({
                    "feed": feed_name,
                    "last_update": str(raw_ts),
                    "seconds_since": None,
                    "stale": True,
                    "reason": f"parse_error: {exc}",
                })
                continue

            seconds_since = (now - last_update).total_seconds()

            if last_update < threshold:
                stale_feeds.append({
                    "feed": feed_name,
                    "last_update": last_update.isoformat(),
                    "seconds_since": round(seconds_since, 1),
                    "stale": True,
                    "reason": "threshold_exceeded",
                })

        if stale_feeds:
            logger.warning(
                "stale_feeds_detected",
                count=len(stale_feeds),
                feeds=[f["feed"] for f in stale_feeds],
            )

        return stale_feeds
