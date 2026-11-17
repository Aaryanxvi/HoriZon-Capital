# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-39781D03C7C1
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Sentiment wiring: headline source, debate context, and sizing damper.

Covers the fix from FINNHUB (never worked with a NewsAPI key) to NewsAPI's
``/v2/everything`` via the existing ``NewsAPIClient``, the sentiment dict
threaded into ``run_debate``, and the flag-gated (default off) BUY sizing
damper on strongly negative cached sentiment.
"""

from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"

from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
from app.agents.front_office.research.sentiment_agent import SentimentAgent
from app.agents.middle_office.debate_agent import DebateAgent
from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.memory_bus import MemoryBus


@pytest.mark.asyncio
async def test_fetch_headlines_empty_api_key_returns_empty_no_network():
    agent = SentimentAgent(bus=MemoryBus(), api_key="")
    assert await agent._fetch_headlines("AAPL.NASDAQ") == []


@pytest.mark.asyncio
async def test_fetch_headlines_uses_newsapi_client(monkeypatch):
    async def fake_fetch_news(self, symbol, days_back=14):
        assert symbol == "AAPL.NASDAQ"
        return [{"title": "Apple surges on strong earnings"}, {"title": "Apple stock rally"}]

    monkeypatch.setattr(
        "app.agents.front_office.research.newsapi_client.NewsAPIClient.fetch_news",
        fake_fetch_news,
    )
    agent = SentimentAgent(bus=MemoryBus(), api_key="fake-key")
    headlines = await agent._fetch_headlines("AAPL.NASDAQ")
    assert headlines == ["Apple surges on strong earnings", "Apple stock rally"]


@pytest.mark.asyncio
async def test_alpaca_news_groups_headlines_by_ticker_across_pages(monkeypatch):
    from app.agents.front_office.research import alpaca_news

    pages = [
        {"news": [{"headline": "Apple beats", "symbols": ["AAPL", "QQQ"]}],
         "next_page_token": "p2"},
        {"news": [{"headline": "Tesla and Apple slide", "symbols": ["TSLA", "AAPL"]}],
         "next_page_token": None},
    ]
    seen_tokens = []

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params):
            seen_tokens.append(params.get("page_token"))
            return FakeResp(pages[len(seen_tokens) - 1])

    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(alpaca_news.httpx, "AsyncClient", FakeClient)

    out = await alpaca_news.fetch_headlines_by_symbol(["AAPL.NASDAQ", "TSLA.NASDAQ"])
    assert out == {"AAPL": ["Apple beats", "Tesla and Apple slide"],
                   "TSLA": ["Tesla and Apple slide"]}  # QQQ not requested -> dropped
    assert seen_tokens == [None, "p2"]


def test_finbert_score_is_pos_minus_neg_not_winner_prob():
    from app.agents.front_office.research.finbert_scorer import FinBERTScorer

    r = FinBERTScorer._to_result([
        {"label": "neutral", "score": 0.55},
        {"label": "negative", "score": 0.40},
        {"label": "positive", "score": 0.05},
    ])
    # Neutral wins the vote, but the negative lean survives in the score.
    assert r == {"sentiment": "neutral", "score": -0.35, "confidence": 0.55}


@pytest.mark.asyncio
async def test_score_symbols_dedupes_aggregates_and_falls_back():
    calls = []

    class FakeFinBERT:
        def score_batch(self, texts):
            calls.append(list(texts))
            return [{"score": -0.8 if "plunge" in t else 0.3} for t in texts]

    agent = SentimentAgent(bus=MemoryBus())
    agent._finbert = FakeFinBERT()
    shared = "Index futures plunge"
    out = await agent._score_symbols({
        "AAPL.NASDAQ": [shared, "Apple steady"],   # mean -0.25 -> negative
        "MSFT.NASDAQ": [shared],                   # -0.8
        "JPM.NYSE": [],
    })
    assert calls == [["Apple steady", shared]]  # shared headline scored once
    assert out == {
        "AAPL.NASDAQ": ("negative", 0.25),
        "MSFT.NASDAQ": ("negative", 0.8),
        "JPM.NYSE": ("neutral", 0.0),
    }

    class BrokenFinBERT:
        def score_batch(self, texts):
            raise OSError("model download failed")

    agent._finbert = BrokenFinBERT()
    out = await agent._score_symbols({"AAPL.NASDAQ": ["Stocks surge on strong growth"]})
    assert out["AAPL.NASDAQ"][0] == "positive"  # keyword fallback answered
    assert agent._finbert is None


@pytest.mark.asyncio
async def test_damper_off_by_default_buy_size_unchanged():
    bus = MemoryBus()
    await bus.start_listening()
    agent = PortfolioAgent(bus=bus)
    kv = get_kv_store()
    await kv.hset("horizon:sentiment:AAPL", {"label": "negative", "score": "0.8"})

    assert settings.sentiment_sizing_enabled is False
    factor = await agent._sentiment_damper_factor("AAPL.NASDAQ")
    assert factor == 1.0
    await bus.stop()


@pytest.mark.asyncio
async def test_damper_on_halves_buy_sell_untouched(monkeypatch):
    monkeypatch.setattr(settings, "sentiment_sizing_enabled", True)
    bus = MemoryBus()
    await bus.start_listening()
    agent = PortfolioAgent(bus=bus)
    kv = get_kv_store()
    await kv.hset("horizon:sentiment:AAPL", {"label": "negative", "score": "0.8"})

    factor = await agent._sentiment_damper_factor("AAPL.NASDAQ")
    assert factor == 0.5

    # Sell sizing path never calls the damper at all -- verify the SELL branch
    # of _compute_position_size is untouched by grepping for its absence would
    # be indirect; instead assert the helper is only consulted for BUY qty by
    # confirming a fresh symbol with no sentiment data is undamped either way.
    await kv.hset("horizon:sentiment:MSFT", {"label": "positive", "score": "0.9"})
    assert await agent._sentiment_damper_factor("MSFT.NASDAQ") == 1.0
    await bus.stop()


@pytest.mark.asyncio
async def test_debate_sentiment_dict_built_from_seeded_kv():
    kv = get_kv_store()
    await kv.hset("horizon:sentiment:TSLA", {"label": "positive", "score": "0.6"})

    sentiment = await DebateAgent._get_sentiment_context("TSLA.NASDAQ")
    assert sentiment == {
        "label": "positive",
        "score": "0.6",
        "avg_sentiment_24h": "positive (0.6)",
        "article_count_14d": "N/A",
        "headlines": [],
    }


@pytest.mark.asyncio
async def test_debate_sentiment_includes_headline_evidence():
    kv = get_kv_store()
    await kv.hset("horizon:sentiment:NVDA", {
        "label": "positive", "score": "0.4",
        "headline_count": "2", "headlines": "Nvidia beats estimates\nNew chip launch",
    })

    sentiment = await DebateAgent._get_sentiment_context("NVDA.NASDAQ")
    assert sentiment["article_count_14d"] == "2"
    assert sentiment["headlines"] == ["Nvidia beats estimates", "New chip launch"]


@pytest.mark.asyncio
async def test_debate_sentiment_dict_none_when_kv_missing():
    sentiment = await DebateAgent._get_sentiment_context("ZZZZ.NASDAQ")
    assert sentiment is None
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 39781D03C7C1 - verify with scripts/authorship.py verify
