# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-339D2CC1F942
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""On-demand market info: history (Alpaca -> IEX -> yfinance), stats, detail,
movers filtering, strategy picks, and the quotes endpoint. No live network."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio


def _eq(symbol, name, exchange="NASDAQ", tradable=True):
    return {"symbol": symbol, "name": name, "exchange": exchange,
            "tradable": tradable, "fractionable": True}


@pytest.fixture
def mi(monkeypatch):
    """market_info with a small catalog, Alpaca keys set, and empty caches."""
    from app.config import settings
    from app.data_layer import alpaca_quotes, market_info
    from app.data_layer import watchlist as wl

    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(settings, "us_symbols", "AAPL.NASDAQ")
    monkeypatch.setattr(settings, "crypto_symbols", "")
    monkeypatch.setattr(settings, "india_symbols", "")
    monkeypatch.setattr(wl, "_listeners", {})
    rows = [wl._equity_row(a, {}) for a in (
        _eq("AAPL", "Apple Inc. Common Stock"), _eq("WFF", "Wolf Corp"),
        _eq("PENY", "Penny Co"), _eq("JUNKW", "Junk Warrant", tradable=False),
        _eq("BRK.B", "Berkshire Class B", "NYSE"),
    )]
    rows.append(wl._crypto_row({"symbol": "BTC/USD", "name": "Bitcoin / US Dollar",
                                "tradable": True}))
    wl._install(rows, time.time(), "test")
    monkeypatch.setattr(wl, "_next_refresh", time.time() + 3600)
    monkeypatch.setattr(market_info, "_history_cache", {})
    monkeypatch.setattr(market_info, "_news_cache", {})
    monkeypatch.setattr(market_info, "_movers_cache", None)
    monkeypatch.setattr(alpaca_quotes, "_snapshot_cache", {})
    yield market_info
    wl._install([], 0, None)


def _mock_http(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _bars(days: int, start_price: float = 100.0) -> list[dict]:
    today = date.today()
    return [
        {"t": f"{(today - timedelta(days=days - i)).isoformat()}T04:00:00Z",
         "o": start_price + i, "h": start_price + i + 2, "l": start_price + i - 2,
         "c": start_price + i + 1, "v": 1000 + i}
        for i in range(days)
    ]


async def test_history_fetches_five_years_once_and_slices_ranges(mi, monkeypatch):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"bars": _bars(1800)})

    _mock_http(monkeypatch, handler)
    one_month = await mi.history("aapl", "1M")
    five = await mi.history("AAPL.NASDAQ", "5Y")
    one_year = await mi.history("AAPL", "1y")

    assert len(calls) == 1                              # cached; ranges are slices
    assert calls[0]["adjustment"] == "all" and calls[0]["timeframe"] == "1Day"
    assert one_month["source"] == "alpaca" and one_month["symbol"] == "AAPL.NASDAQ"
    assert 28 <= len(one_month["bars"]) <= 32
    assert 360 <= len(one_year["bars"]) <= 367
    assert len(five["bars"]) == 1800
    assert set(five["bars"][0]) == {"time", "open", "high", "low", "close", "volume"}


async def test_history_falls_back_to_iex_then_yahoo(mi, monkeypatch):
    from app.data_layer.data_normalizer import NormalizedOHLCV
    from app.data_layer.yahoo_feed import YahooFeed

    feeds = []

    def handler(request):
        feeds.append(request.url.params.get("feed"))
        return httpx.Response(403, json={"message": "subscription does not permit"})

    _mock_http(monkeypatch, handler)
    ts = datetime.now(UTC) - timedelta(days=3)
    bar = NormalizedOHLCV(symbol="AAPL", exchange="NASDAQ", timestamp=ts, timeframe="1d",
                          open=1, high=2, low=0.5, close=1.5, volume=10)
    monkeypatch.setattr(YahooFeed, "poll_ohlcv", AsyncMock(return_value=[bar]))

    out = await mi.history("AAPL", "1M")
    assert feeds == [None, "iex"]                       # SIP refused -> IEX refused
    assert out["source"] == "yahoo" and out["bars"][0]["close"] == 1.5


async def test_history_crypto_uses_crypto_bars_endpoint(mi, monkeypatch):
    paths = []

    def handler(request):
        paths.append((request.url.path, request.url.params.get("symbols")))
        return httpx.Response(200, json={"bars": {"BTC/USD": _bars(40, 60000)}})

    _mock_http(monkeypatch, handler)
    out = await mi.history("BTC-USD", "1M")
    assert paths == [("/v1beta3/crypto/us/bars", "BTC/USD")]
    assert out["bars"] and out["bars"][-1]["close"] > 60000


async def test_history_miss_is_not_cached(mi, monkeypatch):
    from app.data_layer.yahoo_feed import YahooFeed

    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={"bars": []}))
    monkeypatch.setattr(YahooFeed, "poll_ohlcv", AsyncMock(return_value=[]))
    out = await mi.history("AAPL", "1Y")
    assert out["bars"] == [] and out["source"] is None
    assert mi._history_cache == {}


async def test_stats_52w_range_and_volume(mi):
    bars = [{"time": str(i), "open": 1, "high": 10 + i, "low": 5 - i * 0.01, "close": 8,
             "volume": 100} for i in range(400)]
    s = mi.stats(bars)
    assert s["high_52w"] == 10 + 399
    assert s["low_52w"] == pytest.approx(5 - 399 * 0.01)  # only the last 252 bars count
    assert s["avg_volume_30d"] == 100 and s["volume"] == 100
    assert mi.stats([])["high_52w"] is None


async def test_detail_combines_quote_stats_news_and_sentiment(mi, monkeypatch):
    from app.agents.front_office.research import alpaca_news
    from app.core.kv_store import get_kv_store

    def handler(request):
        if "snapshots" in request.url.path:
            return httpx.Response(200, json={"AAPL": {"latestTrade": {"p": 110.0},
                                                       "prevDailyBar": {"c": 100.0}}})
        return httpx.Response(200, json={"bars": _bars(300)})

    _mock_http(monkeypatch, handler)
    monkeypatch.setattr(alpaca_news, "alpaca_news_configured", lambda: True)
    news = AsyncMock(return_value={"AAPL": ["Apple ships thing", "Apple beats"]})
    monkeypatch.setattr(alpaca_news, "fetch_headlines_by_symbol", news)
    await get_kv_store().hset("horizon:sentiment:AAPL",
                              {"label": "positive", "score": "0.42", "timestamp": "t"})

    d = await mi.detail("aapl")
    assert d["name"] == "Apple Inc." and d["on_watchlist"] is True
    assert d["quote"]["price"] == 110.0 and d["quote"]["change_pct"] == pytest.approx(10.0)
    assert d["stats"]["high_52w"] is not None and d["history_source"] == "alpaca"
    assert d["news"] == ["Apple ships thing", "Apple beats"]
    assert d["sentiment"] == {"label": "positive", "score": 0.42, "timestamp": "t"}
    news.assert_awaited_once_with(["AAPL"], hours_back=72)

    await mi.detail("AAPL")                              # news cached for 5 minutes
    news.assert_awaited_once()


async def test_movers_filter_junk_and_use_screener_numbers(mi, monkeypatch):
    def handler(request):
        p = request.url.path
        if p.endswith("/movers"):
            return httpx.Response(200, json={
                "gainers": [
                    {"symbol": "WFF", "price": 11.0, "change": 9.0, "percent_change": 450.0},
                    {"symbol": "JUNKW", "price": 0.08, "change": 0.03, "percent_change": 64.0},
                    {"symbol": "PENY", "price": 0.5, "change": 0.2, "percent_change": 66.0},
                    {"symbol": "NOTLISTED", "price": 5, "change": 1, "percent_change": 25.0},
                ],
                "losers": [{"symbol": "AAPL", "price": 90.0, "change": -10.0,
                            "percent_change": -10.0}],
                "last_updated": "2026-10-09T19:33:00Z"})
        if p.endswith("/most-actives"):
            return httpx.Response(200, json={"most_actives": [{"symbol": "AAPL", "volume": 9}]})
        # snapshot says AAPL is UP -- the losers list must keep the screener's -10%
        return httpx.Response(200, json={
            t: {"latestTrade": {"p": 120.0 if t == "AAPL" else 0.5},
                "prevDailyBar": {"c": 100.0}}
            for t in request.url.params["symbols"].split(",")})

    _mock_http(monkeypatch, handler)
    mv = await mi.movers()
    assert [r["ticker"] for r in mv["gainers"]] == ["WFF"]   # untradable, <$1, unknown dropped
    assert mv["gainers"][0]["change_pct"] == 450.0
    assert mv["losers"][0]["change_pct"] == -10.0 and mv["losers"][0]["price"] == 90.0
    assert mv["most_actives"][0]["price"] == 120.0          # no screener price -> snapshot
    assert mv["losers"][0]["on_watchlist"] is True
    assert "price at least" in mv["filter"]


async def test_strategy_picks_live_agent_carries_sleeve_and_reason(mi, monkeypatch):
    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={}))
    sleeve = SimpleNamespace(name="research_stack", target_weight=0.6)
    agent = SimpleNamespace(
        agent_type="strategy", _sleeves=[sleeve],
        _sleeve_cache={"research_stack": [
            SimpleNamespace(symbol="AAPL.NASDAQ", target_weight=0.5,
                            reason="RISK_ON tsmom rank 1"),
            SimpleNamespace(symbol="WFF.NASDAQ", target_weight=0.0, reason="dropped"),
        ]},
    )
    orch = SimpleNamespace(_slots={"s": SimpleNamespace(agent=agent)})

    out = await mi.strategy_picks(orch)
    assert out["source"] == "live"
    assert len(out["picks"]) == 1
    pick = out["picks"][0]
    assert pick["ticker"] == "AAPL" and pick["weight"] == pytest.approx(0.3)
    assert pick["sleeve"] == "research_stack" and "RISK_ON" in pick["reason"]


@pytest_asyncio.fixture
async def runtime():
    from app.core.runtime import shutdown, startup
    await startup()
    yield
    await shutdown()


async def test_strategy_picks_fall_back_to_latest_persisted_signal(mi, runtime, monkeypatch):
    from sqlalchemy import text

    from app.core.runtime import get_session_factory

    _mock_http(monkeypatch, lambda r: httpx.Response(200, json={}))
    now = datetime.now(UTC)
    rows = [("AAPL.NASDAQ", 0.10, now - timedelta(hours=2)),
            ("AAPL.NASDAQ", 0.25, now),                     # newest wins
            ("WFF.US", 0.0, now)]                           # exited -> not a pick
    async with get_session_factory()() as session:
        for sym, w, ts in rows:
            await session.execute(text(
                "INSERT INTO signals (signal_id, agent_id, symbol, direction, strength, "
                "confidence, strategy_name, regime, metadata, created_at) VALUES "
                "(:id, 'strategy-agent-1', :sym, 'BUY', 0.5, 0.5, 'sleeve_system', '', :md, :ts)"
            ), {"id": str(uuid.uuid4()), "sym": sym, "ts": ts,
                "md": json.dumps({"target_weight": w, "reasoning": f"sleeve_target -> {w:.0%}"})})
        await session.commit()

    out = await mi.strategy_picks(None)
    assert out["source"] == "signals"
    assert [(p["ticker"], p["weight"]) for p in out["picks"]] == [("AAPL", 0.25)]
    assert out["picks"][0]["sleeve"] is None


async def test_quotes_endpoint_is_on_demand_only(mi, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    seen = []

    def handler(request):
        seen.append(request.url.params["symbols"])
        return httpx.Response(200, json={"WFF": {"latestTrade": {"p": 11.0},
                                                 "prevDailyBar": {"c": 10.0}}})

    _mock_http(monkeypatch, handler)
    notified = []
    from app.data_layer import watchlist as wl
    wl.on_change("spy", lambda a, r: notified.append((a, r)))
    before = settings.us_symbols

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as client:
        body = client.get("/api/desktop/quotes", params={"symbols": "WFF.NASDAQ"}).json()
    assert body["quotes"]["WFF.NASDAQ"]["change_pct"] == pytest.approx(10.0)
    assert seen == ["WFF"]
    assert notified == [] and settings.us_symbols == before  # browsing never subscribes
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 339D2CC1F942 - verify with scripts/authorship.py verify
