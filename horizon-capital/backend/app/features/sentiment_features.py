# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-6B2B9B999B7C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Sentiment feature aggregation.

Consumes raw narrative / article dicts (from the sentiment agent's data
sources) and produces aggregate metrics over a configurable look-back window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger

logger = get_logger("features.sentiment")


class SentimentFeatures:
    """Aggregate raw narrative records into sentiment features."""

    @staticmethod
    def aggregate_sentiment(
        narratives: list[dict],
        window_days: int = 14,
    ) -> dict:
        """Compute aggregate sentiment metrics over a time window.

        Parameters
        ----------
        narratives : list[dict]
            Each dict should contain at least:
            - ``sentiment_score`` (float, -1.0 to 1.0)
            - ``published_at`` (ISO 8601 string or ``datetime``)
            Optional fields used if present:
            - ``relevance_score`` (float, 0-1, defaults to 1.0)
        window_days : int
            Look-back window in calendar days from *now*.

        Returns
        -------
        dict
            ``{avg_sentiment, bull_pct, bear_pct, article_count, momentum}``
            - ``avg_sentiment``: relevance-weighted mean sentiment in [-1, 1]
            - ``bull_pct``: fraction of articles with sentiment > 0.1
            - ``bear_pct``: fraction of articles with sentiment < -0.1
            - ``article_count``: number of articles in window
            - ``momentum``: sentiment acceleration (recent half vs older half)
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=window_days)

        # Filter to window
        in_window: list[dict] = []
        for n in narratives:
            pub = n.get("published_at")
            if pub is None:
                continue
            if isinstance(pub, str):
                # Accept ISO format with or without timezone
                try:
                    pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if pub >= cutoff:
                in_window.append({**n, "_pub_dt": pub})

        article_count = len(in_window)

        if article_count == 0:
            return {
                "avg_sentiment": 0.0,
                "bull_pct": 0.0,
                "bear_pct": 0.0,
                "article_count": 0,
                "momentum": 0.0,
            }

        # Weighted average sentiment
        total_weight = 0.0
        weighted_sum = 0.0
        bull_count = 0
        bear_count = 0

        for n in in_window:
            score = float(n.get("sentiment_score", 0.0))
            relevance = float(n.get("relevance_score", 1.0))
            weighted_sum += score * relevance
            total_weight += relevance
            if score > 0.1:
                bull_count += 1
            elif score < -0.1:
                bear_count += 1

        avg_sentiment = weighted_sum / total_weight if total_weight > 0 else 0.0
        bull_pct = bull_count / article_count
        bear_pct = bear_count / article_count

        # Momentum: compare recent half to older half
        midpoint = cutoff + timedelta(days=window_days / 2)
        recent_scores: list[float] = []
        older_scores: list[float] = []
        for n in in_window:
            score = float(n.get("sentiment_score", 0.0))
            if n["_pub_dt"] >= midpoint:
                recent_scores.append(score)
            else:
                older_scores.append(score)

        recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0.0
        older_avg = sum(older_scores) / len(older_scores) if older_scores else 0.0
        momentum = recent_avg - older_avg  # positive = accelerating bullishness

        logger.info(
            "sentiment_aggregated",
            article_count=article_count,
            avg_sentiment=round(avg_sentiment, 4),
            momentum=round(momentum, 4),
        )

        return {
            "avg_sentiment": round(avg_sentiment, 6),
            "bull_pct": round(bull_pct, 4),
            "bear_pct": round(bear_pct, 4),
            "article_count": article_count,
            "momentum": round(momentum, 6),
        }
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 6B2B9B999B7C - verify with scripts/authorship.py verify
