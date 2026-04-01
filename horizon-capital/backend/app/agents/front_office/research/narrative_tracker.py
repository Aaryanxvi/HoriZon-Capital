"""Narrative lifecycle tracker -- monitors how stories evolve around symbols.

Tracks narratives through four lifecycle stages:
    BIRTH -> ACCELERATION -> PEAK -> DECAY

Also detects cross-asset narrative spillover (e.g., an AAPL narrative driving
MSFT price action).
"""

from datetime import UTC, datetime

import numpy as np
from sqlalchemy import text

from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("sentiment.narrative_tracker")


class NarrativeTracker:
    """Classifies narrative lifecycle stages and detects cross-asset spillover."""

    # ------------------------------------------------------------------
    # Stage classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_stage(
        article_counts_over_time: list[int],
        sentiment_trend: list[float],
    ) -> str:
        """Classify the lifecycle stage of a narrative.

        Parameters
        ----------
        article_counts_over_time:
            Daily article counts, oldest-first.
        sentiment_trend:
            Daily average sentiment scores (``-1`` to ``1``), oldest-first.

        Returns
        -------
        str
            One of ``BIRTH``, ``ACCELERATION``, ``PEAK``, ``DECAY``.
        """
        if len(article_counts_over_time) < 2:
            return "BIRTH"

        counts = np.array(article_counts_over_time, dtype=float)
        sentiments = np.array(sentiment_trend, dtype=float)

        # Trends over the most recent half of the window
        mid = max(len(counts) // 2, 1)
        recent_counts = counts[mid:]
        early_counts = counts[:mid]

        recent_sent = sentiments[mid:] if len(sentiments) > mid else sentiments
        early_sent = sentiments[:mid] if len(sentiments) > mid else sentiments

        avg_recent_count = float(np.mean(recent_counts)) if len(recent_counts) else 0.0
        avg_early_count = float(np.mean(early_counts)) if len(early_counts) else 0.0
        count_trend = avg_recent_count - avg_early_count

        avg_recent_sent = float(np.mean(np.abs(recent_sent))) if len(recent_sent) else 0.0
        avg_early_sent = float(np.mean(np.abs(early_sent))) if len(early_sent) else 0.0
        sent_trend = avg_recent_sent - avg_early_sent

        max_count = float(np.max(counts))
        is_high_count = avg_recent_count > 0.6 * max_count if max_count > 0 else False

        # BIRTH: low article count (first mentions)
        if avg_recent_count <= 2 and max_count <= 5:
            return "BIRTH"

        # ACCELERATION: rising count + strengthening sentiment
        if count_trend > 0 and sent_trend > 0:
            return "ACCELERATION"

        # PEAK: high count + sentiment starting to flatten/plateau
        if is_high_count and abs(sent_trend) < 0.05:
            return "PEAK"

        # DECAY: declining count + weakening sentiment
        if count_trend < 0 and sent_trend <= 0:
            return "DECAY"

        # Fallback heuristics
        if count_trend > 0:
            return "ACCELERATION"
        if is_high_count:
            return "PEAK"
        return "DECAY"

    # ------------------------------------------------------------------
    # Cross-asset spillover detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_spillover(
        symbol: str,
        related_symbols: list[str],
        narratives: list[dict],
    ) -> list[dict]:
        """Detect whether narratives for *symbol* are spilling over into *related_symbols*.

        A spillover is flagged when the same narrative keywords appear in
        articles for related symbols within a short time window.

        Parameters
        ----------
        symbol:
            The primary symbol whose narratives we are tracking.
        related_symbols:
            A list of symbols that may be affected.
        narratives:
            A list of narrative dicts, each containing at least ``symbol``,
            ``headline``, ``sentiment_score``, and ``publishedAt``.

        Returns
        -------
        list[dict]
            Detected spillover events with ``source_symbol``,
            ``target_symbol``, ``headline``, ``sentiment_score``, and
            ``match_keywords``.
        """
        # Build keyword set from primary symbol narratives
        primary_headlines = [
            n["headline"].lower()
            for n in narratives
            if n.get("symbol", "").split(".")[0] == symbol.split(".")[0]
        ]

        # Extract significant words (length > 4 to skip noise)
        keyword_counts: dict[str, int] = {}
        for headline in primary_headlines:
            for word in headline.split():
                cleaned = word.strip(".,!?;:'\"()[]")
                if len(cleaned) > 4:
                    keyword_counts[cleaned] = keyword_counts.get(cleaned, 0) + 1

        # Keep top keywords that appear in multiple headlines
        significant_keywords = {
            kw for kw, count in keyword_counts.items() if count >= 2
        }

        if not significant_keywords:
            return []

        spillovers: list[dict] = []

        for narrative in narratives:
            n_symbol = narrative.get("symbol", "")
            n_base = n_symbol.split(".")[0]

            # Skip narratives from the primary symbol itself
            if n_base == symbol.split(".")[0]:
                continue

            # Only check related symbols
            if not any(
                n_base == rs.split(".")[0] for rs in related_symbols
            ):
                continue

            headline_lower = narrative.get("headline", "").lower()
            matched = {
                kw for kw in significant_keywords if kw in headline_lower
            }

            if len(matched) >= 2:
                spillovers.append(
                    {
                        "source_symbol": symbol,
                        "target_symbol": n_symbol,
                        "headline": narrative.get("headline", ""),
                        "sentiment_score": narrative.get("sentiment_score", 0.0),
                        "match_keywords": list(matched),
                    }
                )

        logger.info(
            "spillover_detection_complete",
            symbol=symbol,
            related_count=len(related_symbols),
            spillover_count=len(spillovers),
        )
        return spillovers

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def update_lifecycle_stage(
        self,
        narrative_id: str,
        stage: str,
    ) -> None:
        """Persist the lifecycle stage for a narrative row in the database."""
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    UPDATE narratives
                    SET lifecycle_stage = :stage, updated_at = :now
                    WHERE id = :narrative_id
                    """
                ),
                {
                    "narrative_id": narrative_id,
                    "stage": stage,
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()

    async def get_article_counts_by_day(
        self,
        symbol: str,
        days: int = 14,
    ) -> list[int]:
        """Query daily article counts for *symbol* over the last *days* days."""
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT DATE(published_at) AS day, COUNT(*) AS cnt
                    FROM narratives
                    WHERE symbol = :symbol
                      AND published_at >= :cutoff
                    GROUP BY DATE(published_at)
                    ORDER BY day
                    """
                ),
                {"symbol": symbol, "cutoff": cutoff},
            )
            rows = result.fetchall()
            return [int(r[1]) for r in rows]

    async def get_sentiment_trend_by_day(
        self,
        symbol: str,
        days: int = 14,
    ) -> list[float]:
        """Query daily average sentiment for *symbol* over the last *days* days."""
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT DATE(published_at) AS day, AVG(sentiment_score) AS avg_sent
                    FROM narratives
                    WHERE symbol = :symbol
                      AND published_at >= :cutoff
                    GROUP BY DATE(published_at)
                    ORDER BY day
                    """
                ),
                {"symbol": symbol, "cutoff": cutoff},
            )
            rows = result.fetchall()
            return [float(r[1]) for r in rows]
