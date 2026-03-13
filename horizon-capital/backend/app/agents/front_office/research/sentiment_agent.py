"""Sentiment agent -- orchestrates news/Reddit fetching, FinBERT scoring,
narrative tracking, and cross-asset spillover detection.

Runs every 15 minutes, processes all tracked symbols, and publishes
aggregated sentiment on ``horizon.features.{symbol}.sentiment``.
"""

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dateutil import parser as dtparser
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.research.finbert_scorer import FinBERTScorer
from app.agents.front_office.research.narrative_tracker import NarrativeTracker
from app.agents.front_office.research.newsapi_client import NewsAPIClient
from app.agents.front_office.research.reddit_client import RedditClient
from app.config import settings
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("agent.sentiment")

# Time windows (in hours) for aggregation
AGGREGATION_WINDOWS: dict[str, int] = {
    "1h": 1,
    "4h": 4,
    "24h": 24,
    "14d": 14 * 24,
}

# Interval between runs in seconds (15 minutes)
RUN_INTERVAL_SECONDS = 15 * 60

# Related-symbol groups for spillover detection
RELATED_GROUPS: list[list[str]] = [
    ["AAPL.NASDAQ", "MSFT.NASDAQ", "GOOGL.NASDAQ", "AMZN.NASDAQ", "TSLA.NASDAQ"],
    ["RELIANCE.NSE", "TCS.NSE", "INFY.NSE", "HDFCBANK.NSE", "ICICIBANK.NSE"],
    ["BTC-USD", "ETH-USD"],
]


def _related_symbols(symbol: str) -> list[str]:
    """Return the symbols in the same group as *symbol*, excluding itself."""
    for group in RELATED_GROUPS:
        if symbol in group:
            return [s for s in group if s != symbol]
    return []


class SentimentAgent(BaseAgent):
    """Periodically fetches news and Reddit, scores with FinBERT, aggregates,
    tracks narratives, and publishes results to the agent bus."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="sentiment-agent-01",
            agent_type="SENTIMENT",
            bus=bus,
        )
        self.news_client = NewsAPIClient()
        self.reddit_client = RedditClient()
        self.scorer = FinBERTScorer()
        self.tracker = NarrativeTracker()

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    async def on_message(self, message: AgentMessage) -> None:
        """Handle inbound messages (currently a no-op; sentiment is polling-based)."""
        pass

    async def run(self) -> None:
        """Main loop: fetch, score, aggregate, publish -- every 15 minutes."""
        symbols = settings.all_symbols
        logger.info("sentiment_agent_starting", symbols=symbols)

        while self._running:
            try:
                await self._process_all_symbols(symbols)
            except Exception as exc:
                logger.error("sentiment_run_error", error=str(exc))

            # Sleep for 15 minutes, checking the running flag every second
            for _ in range(RUN_INTERVAL_SECONDS):
                if not self._running:
                    return
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    async def _process_all_symbols(self, symbols: list[str]) -> None:
        """Run the full sentiment pipeline for every tracked symbol."""
        for symbol in symbols:
            if not self._running:
                return
            try:
                await self._process_symbol(symbol)
            except Exception as exc:
                logger.error(
                    "sentiment_symbol_error", symbol=symbol, error=str(exc)
                )

    async def _process_symbol(self, symbol: str) -> None:
        """Fetch -> Score -> Store -> Aggregate -> Spillover -> Publish."""
        # 1. Fetch news and Reddit in parallel
        news_task = asyncio.create_task(self.news_client.fetch_news(symbol, days_back=14))
        reddit_task = asyncio.create_task(self.reddit_client.fetch_posts(symbol))
        news_articles, reddit_posts = await asyncio.gather(news_task, reddit_task)

        # 2. Prepare texts and score with FinBERT
        items: list[dict] = []

        for article in news_articles:
            combined_text = f"{article['title']} {article.get('description', '')}"
            items.append(
                {
                    "text": combined_text,
                    "source": "NEWSAPI",
                    "headline": article["title"],
                    "url": article.get("url"),
                    "engagement": 0,
                    "publishedAt": article.get("publishedAt"),
                }
            )

        for post in reddit_posts:
            combined_text = f"{post['title']} {post.get('body', '')}"
            items.append(
                {
                    "text": combined_text,
                    "source": "REDDIT",
                    "headline": post["title"],
                    "url": None,
                    "engagement": post.get("score", 0) + post.get("num_comments", 0),
                    "publishedAt": datetime.fromtimestamp(
                        post.get("created_utc", 0), tz=timezone.utc
                    ).isoformat()
                    if post.get("created_utc")
                    else None,
                }
            )

        if not items:
            logger.info("sentiment_no_items", symbol=symbol)
            return

        texts = [it["text"] for it in items]
        scores = self.scorer.score_batch(texts)

        # 3. Store each narrative in the database
        now = datetime.now(timezone.utc)
        narrative_ids: list[str] = []

        async with _get_session_factory()() as session:
            for item, sc in zip(items, scores):
                nid = str(uuid.uuid4())
                narrative_ids.append(nid)

                engagement_weighted = FinBERTScorer.engagement_weighted_score(
                    sc["score"], item["engagement"]
                )

                published_at = None
                if item.get("publishedAt"):
                    try:
                        published_at = dtparser.parse(item["publishedAt"])
                    except (ValueError, TypeError):
                        published_at = now

                await session.execute(
                    text(
                        """
                        INSERT INTO narratives
                            (id, symbol, source, headline, url, sentiment_score,
                             relevance_score, engagement_score, published_at,
                             created_at, updated_at)
                        VALUES
                            (:id, :symbol, :source, :headline, :url, :sentiment,
                             1.0, :engagement, :published_at, :now, :now)
                        """
                    ),
                    {
                        "id": nid,
                        "symbol": symbol,
                        "source": item["source"],
                        "headline": item["headline"],
                        "url": item.get("url"),
                        "sentiment": sc["score"],
                        "engagement": engagement_weighted,
                        "published_at": published_at,
                        "now": now,
                    },
                )
            await session.commit()

        # 4. Update narrative lifecycle stages
        article_counts = await self.tracker.get_article_counts_by_day(symbol, days=14)
        sentiment_trend = await self.tracker.get_sentiment_trend_by_day(symbol, days=14)
        stage = NarrativeTracker.classify_stage(article_counts, sentiment_trend)

        for nid in narrative_ids:
            await self.tracker.update_lifecycle_stage(nid, stage)

        # 5. Compute and store aggregates per window
        aggregates = await self._compute_aggregates(symbol)

        # 6. Cross-asset spillover detection
        related = _related_symbols(symbol)
        if related:
            all_narratives = await self._fetch_recent_narratives(symbol, related)
            spillovers = NarrativeTracker.detect_spillover(
                symbol, related, all_narratives
            )
            if spillovers:
                logger.info(
                    "spillover_detected",
                    symbol=symbol,
                    spillover_count=len(spillovers),
                )

        # 7. Publish to bus
        await self.emit(
            channel=f"horizon.features.{symbol}.sentiment",
            message_type=MessageType.FEATURE_UPDATE,
            payload={
                "symbol": symbol,
                "lifecycle_stage": stage,
                "aggregates": aggregates,
                "article_count": len(items),
                "timestamp": now.isoformat(),
            },
        )

        logger.info(
            "sentiment_published",
            symbol=symbol,
            stage=stage,
            article_count=len(items),
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    async def _compute_aggregates(self, symbol: str) -> dict[str, dict]:
        """Compute and persist sentiment aggregates for each time window."""
        now = datetime.now(timezone.utc)
        result: dict[str, dict] = {}

        async with _get_session_factory()() as session:
            for window_label, hours in AGGREGATION_WINDOWS.items():
                cutoff = now - timedelta(hours=hours)

                rows = await session.execute(
                    text(
                        """
                        SELECT sentiment_score
                        FROM narratives
                        WHERE symbol = :symbol
                          AND published_at >= :cutoff
                        """
                    ),
                    {"symbol": symbol, "cutoff": cutoff},
                )
                sentiment_values = [float(r[0]) for r in rows.fetchall()]

                if not sentiment_values:
                    result[window_label] = {
                        "avg_sentiment": 0.0,
                        "article_count": 0,
                        "bull_pct": 0.0,
                        "bear_pct": 0.0,
                        "neutral_pct": 0.0,
                    }
                    continue

                total = len(sentiment_values)
                bull = sum(1 for s in sentiment_values if s > 0.05)
                bear = sum(1 for s in sentiment_values if s < -0.05)
                neutral = total - bull - bear
                avg_sent = sum(sentiment_values) / total

                agg = {
                    "avg_sentiment": round(avg_sent, 4),
                    "article_count": total,
                    "bull_pct": round(bull / total * 100, 1),
                    "bear_pct": round(bear / total * 100, 1),
                    "neutral_pct": round(neutral / total * 100, 1),
                }
                result[window_label] = agg

                # Upsert aggregate into DB
                agg_id = str(uuid.uuid4())
                await session.execute(
                    text(
                        """
                        INSERT INTO sentiment_aggregates
                            (id, symbol, window, avg_sentiment, article_count,
                             bull_pct, bear_pct, neutral_pct, created_at, updated_at)
                        VALUES
                            (:id, :symbol, :window, :avg_sent, :count,
                             :bull, :bear, :neutral, :now, :now)
                        ON CONFLICT ON CONSTRAINT uq_sentiment_agg_symbol_window
                        DO UPDATE SET
                            avg_sentiment = :avg_sent,
                            article_count = :count,
                            bull_pct = :bull,
                            bear_pct = :bear,
                            neutral_pct = :neutral,
                            updated_at = :now
                        """
                    ),
                    {
                        "id": agg_id,
                        "symbol": symbol,
                        "window": window_label,
                        "avg_sent": agg["avg_sentiment"],
                        "count": agg["article_count"],
                        "bull": agg["bull_pct"],
                        "bear": agg["bear_pct"],
                        "neutral": agg["neutral_pct"],
                        "now": now,
                    },
                )

            await session.commit()

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_recent_narratives(
        self,
        symbol: str,
        related: list[str],
    ) -> list[dict]:
        """Fetch narratives for *symbol* and its related symbols from the DB."""
        all_symbols = [symbol] + related
        placeholders = ", ".join(f":s{i}" for i in range(len(all_symbols)))
        params = {f"s{i}": s for i, s in enumerate(all_symbols)}

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT id, symbol, headline, sentiment_score, published_at
                    FROM narratives
                    WHERE symbol IN ({placeholders})
                      AND published_at >= NOW() - INTERVAL '14 days'
                    ORDER BY published_at DESC
                    """
                ),
                params,
            )
            rows = result.mappings().all()
            return [
                {
                    "id": str(r["id"]),
                    "symbol": r["symbol"],
                    "headline": r["headline"],
                    "sentiment_score": float(r["sentiment_score"]),
                    "publishedAt": r["published_at"].isoformat()
                    if r["published_at"]
                    else None,
                }
                for r in rows
            ]
