# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A02767154ED3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Basic sentiment analysis using free news headlines."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.agents.front_office.research.newsapi_client import NewsAPIClient
from app.core.messaging import AgentMessage, MessageType

logger = logging.getLogger(__name__)

POSITIVE_WORDS = frozenset({
    "surge", "soar", "rally", "gain", "profit", "growth", "beat", "upgrade",
    "bullish", "record", "high", "strong", "boom", "breakout", "outperform",
    "up", "rise", "positive", "optimistic", "buy", "upside", "recover",
})

NEGATIVE_WORDS = frozenset({
    "crash", "plunge", "drop", "loss", "decline", "downgrade", "bearish",
    "low", "weak", "bust", "sell", "miss", "warning", "risk", "fear",
    "down", "fall", "negative", "pessimistic", "recession", "default",
})


def score_headline(headline: str) -> tuple[str, float]:
    """Score a headline as positive/negative/neutral with magnitude 0-1."""
    words = set(headline.lower().split())
    pos_count = len(words & POSITIVE_WORDS)
    neg_count = len(words & NEGATIVE_WORDS)
    total = pos_count + neg_count
    if total == 0:
        return "neutral", 0.0
    if pos_count > neg_count:
        return "positive", min(pos_count / total, 1.0)
    elif neg_count > pos_count:
        return "negative", min(neg_count / total, 1.0)
    return "neutral", 0.0


class SentimentAgent:
    """Fetches news headlines and scores sentiment per symbol."""

    def __init__(self, bus, symbols: list[str] | None = None, api_key: str = ""):
        self.bus = bus
        self.symbols = symbols or []
        self.api_key = api_key
        self._running = False

    async def start(self):
        self._running = True
        logger.info("SentimentAgent started for %d symbols", len(self.symbols))
        while self._running:
            for symbol in self.symbols:
                try:
                    sentiment, score = await self._analyze_symbol(symbol)
                    # Persist to KV store so the sentiment REPL command can read it
                    try:
                        from app.core.kv_store import get_kv_store
                        kv = get_kv_store()
                        raw = symbol.split(".")[0] if "." in symbol else symbol
                        await kv.hset(f"horizon:sentiment:{raw}", {
                            "label": sentiment,
                            "score": str(round(score, 4)),
                            "timestamp": datetime.now(UTC).isoformat(),
                        })
                    except Exception:
                        pass
                    await self.bus.publish(AgentMessage(
                        sender_id="sentiment_agent",
                        channel="horizon.sentiment.update",
                        message_type=MessageType.SENTIMENT_UPDATE,
                        payload={
                            "symbol": symbol,
                            "sentiment": sentiment,
                            "score": score,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    ))
                except Exception:
                    logger.exception("Sentiment failed for %s", symbol)
            await asyncio.sleep(300)

    async def stop(self):
        self._running = False

    async def _analyze_symbol(self, symbol: str) -> tuple[str, float]:
        headlines = await self._fetch_headlines(symbol)
        if not headlines:
            return "neutral", 0.0
        pos_total = 0.0
        neg_total = 0.0
        for headline in headlines:
            sentiment, magnitude = score_headline(headline)
            if sentiment == "positive":
                pos_total += magnitude
            elif sentiment == "negative":
                neg_total += magnitude
        count = len(headlines)
        if pos_total > neg_total:
            return "positive", min(pos_total / count, 1.0)
        elif neg_total > pos_total:
            return "negative", min(neg_total / count, 1.0)
        return "neutral", 0.0

    async def _fetch_headlines(self, symbol: str) -> list[str]:
        if not self.api_key:
            return []
        client = NewsAPIClient(self.api_key)
        articles = await client.fetch_news(symbol, days_back=1)
        return [a["title"] for a in articles]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A02767154ED3 - verify with scripts/authorship.py verify
