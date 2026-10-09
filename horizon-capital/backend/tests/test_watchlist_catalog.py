# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D229F85769D3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Watchlist catalog: build, search ranking, symbol resolution, bulk add/remove,
live feed re-subscription, and batched price ingestion. No live network."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio


def _eq(symbol, name, exchange="NASDAQ", tradable=True):
    return {"symbol": symbol, "name": name, "exchange": exchange,
            "tradable": tradable, "fractionable": True}


EQUITIES = [
    _eq("AAPL", "Apple Inc. Common Stock"),
    _eq("AAP", "Advance Auto Parts Inc"),
    _eq("APP", "AppLovin Corporation Class A Common Stock"),
    _eq("SPY", "State Street SPDR S&P 500 ETF Trust", "ARCA"),
    _eq("QQQ", "Invesco QQQ Trust, Series 1"),
    _eq("BRK.B", "BERKSHIRE HATHAWAY Class B", "NYSE"),
    _eq("XOM", "Exxon Mobil Corp", "NYSE"),
    _eq("BTC", "Grayscale Bitcoin Mini Trust ETF", "ARCA"),
    _eq("ZOMB", "Zombie Shell Corp Common Stock", "OTC", tradable=False),
]
CRYPTO = [
    {"symbol": "BTC/USD", "name": "Bitcoin / US Dollar", "tradable": True, "fractionable": True},
    {"symbol": "ETH/USD", "name": "Ethereum / US Dollar", "tradable": True, "fractionable": True},
    {"symbol": "BTC/USDT", "name": "Bitcoin / USD Tether", "tradable": True, "fractionable": True},
]
SP500 = [
    {"Symbol": "AAPL", "Security": "Apple Inc.", "GICS Sector": "Information Technology"},
    {"Symbol": "BRK.B", "Security": "Berkshire Hathaway", "GICS Sector": "Financials"},
    {"Symbol": "XOM", "Security": "ExxonMobil", "GICS Sector": "Energy"},
]


def _rows():
    from app.data_layer import watchlist as wl

    sp = {wl._key(r["Symbol"]): {"name": r["Security"], "sector": r["GICS Sector"]}
          for r in SP500}
    rows = [wl._equity_row(a, sp) for a in EQUITIES]
    return rows + [r for a in CRYPTO if (r := wl._crypto_row(a))]


@pytest.fixture
def wl(monkeypatch, tmp_path):
    """The watchlist module with a test catalog installed and a tmp .env."""
    from app.config import settings
    from app.data_layer import watchlist as module

    env = tmp_path / ".env"
    env.write_text("STORAGE_BACKEND=LOCAL\nUS_SYMBOLS=SPY.NYSE\nCRYPTO_SYMBOLS=\n",
                   encoding="utf-8")
    monkeypatch.setattr(module, "_ENV_PATH", env)
    monkeypatch.setattr(settings, "us_symbols", "SPY.NYSE")
    monkeypatch.setattr(settings, "crypto_symbols", "")
    monkeypatch.setattr(settings, "india_symbols", "")
    monkeypatch.setattr(module, "_listeners", {})
    module._install(_rows(), time.time(), "test")
    monkeypatch.setattr(module, "_next_refresh", time.time() + 3600)
    yield module
    module._install([], 0, None)
    module._meta.update(error=None)


def _mock_http(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------------
# Catalog build + cache
# ---------------------------------------------------------------------------

async def test_catalog_builds_from_alpaca_and_caches_to_disk(monkeypatch):
    from app.config import settings
    from app.data_layer import universe
    from app.data_layer import watchlist as wl

    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(universe, "fetch_sp500_rows", lambda: SP500)
    monkeypatch.setattr(wl, "_next_refresh", 0.0)
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        cls = request.url.params["asset_class"]
        return httpx.Response(200, json=EQUITIES if cls == "us_equity" else CRYPTO)

    _mock_http(monkeypatch, handler)
    try:
        rows = await wl.load_catalog(force=True)
        by = {r["symbol"]: r for r in rows}

        assert {c["asset_class"] for c in calls} == {"us_equity", "crypto"}
        assert by["AAPL.NASDAQ"]["name"] == "Apple Inc."  # S&P name wins
        assert by["AAPL.NASDAQ"]["sector"] == "Information Technology"
        assert by["SPY.NYSE"]["etf"] and by["QQQ.NASDAQ"]["etf"]  # ARCA -> .NYSE
        assert not by["AAPL.NASDAQ"]["etf"]
        assert "BRK-B.NYSE" in by and by["BRK-B.NYSE"]["ticker"] == "BRK.B"
        assert "BTC-USD" in by and by["BTC-USD"]["name"] == "Bitcoin"
        assert not any(r["ticker"] == "BTC/USDT" for r in rows)  # USD pairs only
        assert by["APP.NASDAQ"]["name"] == "AppLovin Corporation Class A"

        cached = json.loads(wl._cache_file().read_text(encoding="utf-8"))
        assert len(cached["rows"]) == len(rows)
    finally:
        wl._install([], 0, None)


async def test_catalog_falls_back_to_stale_cache_when_alpaca_is_down(monkeypatch):
    from app.config import settings
    from app.data_layer import watchlist as wl

    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(wl, "_next_refresh", 0.0)
    wl._write_cache(_rows(), time.time() - 3 * 86400)  # three days old

    def handler(request):
        raise httpx.ConnectError("offline")

    _mock_http(monkeypatch, handler)
    try:
        rows = await wl.load_catalog()
        assert len(rows) == len(_rows())
        info = wl.catalog_info()
        assert info["source"] == "cache (stale)"
        assert "unreachable" in info["error"]
    finally:
        wl._install([], 0, None)
        wl._meta.update(error=None)


# ---------------------------------------------------------------------------
# Search, filters, resolution
# ---------------------------------------------------------------------------

async def test_search_ranks_exact_then_prefix_then_name(wl):
    tickers = lambda rows: [r["ticker"] for r in rows]  # noqa: E731

    assert tickers(wl.search("btc")[0])[:2] == ["BTC", "BTC/USD"]  # both exact hits
    assert tickers(wl.search("apple")[0]) == ["AAPL"]              # name word-prefix
    # The coin named "Bitcoin" beats a fund that merely mentions bitcoin mid-name.
    assert tickers(wl.search("bitcoin")[0]) == ["BTC/USD", "BTC"]
    assert tickers(wl.search("xo")[0])[0] == "XOM"
    # Both prefix matches; the S&P 500 member wins the tie despite a longer ticker.
    assert tickers(wl.search("aa")[0])[:2] == ["AAPL", "AAP"]
    assert tickers(wl.search("brk.b")[0]) == ["BRK.B"]
    assert wl.search("zzzz")[1] == 0


async def test_search_filters_pagination_and_on_watchlist_flag(wl):
    energy, total = wl.search(sector="Energy")
    assert [r["ticker"] for r in energy] == ["XOM"] and total == 1

    etfs = {r["ticker"] for r in wl.search(group="etf")[0]}
    assert etfs == {"SPY", "QQQ", "BTC"}

    crypto = {r["symbol"] for r in wl.search(asset_class="crypto")[0]}
    assert crypto == {"BTC-USD", "ETH-USD"}

    page, total = wl.search(limit=3, offset=3)
    assert len(page) == 3 and total == len(_rows())

    spy = wl.search("spy")[0][0]
    assert spy["on_watchlist"] is True
    assert wl.search("aapl")[0][0]["on_watchlist"] is False

    cats = wl.categories()
    groups = {g["id"]: g["count"] for g in cats["groups"]}
    assert groups == {"sp500": 3, "etf": 3, "crypto": 2}
    assert {s["name"] for s in cats["sectors"]} == {
        "Information Technology", "Financials", "Energy"}
    assert any(m["id"] == "india" and not m["available"] for m in cats["markets"])


async def test_resolve_accepts_every_spelling_and_rejects_clearly(wl):
    def sym(token):
        row, err = wl.resolve(token)
        return row["symbol"] if row else err

    assert sym("aapl") == "AAPL.NASDAQ"
    assert sym("AAPL.NASDAQ") == "AAPL.NASDAQ"
    assert sym("AAPL.US") == "AAPL.NASDAQ"          # universe.py's suffix
    assert sym("brk.b") == "BRK-B.NYSE"
    assert sym("BRK-B") == "BRK-B.NYSE"
    assert sym("btc/usd") == "BTC-USD"
    assert sym("BTC-USD") == "BTC-USD"
    assert sym("BTC") == "BTC.NYSE"                 # bare ticker = the stock
    assert "Zerodha" in sym("RELIANCE.NSE")
    assert "not tradable" in sym("ZOMB")
    assert "not in the symbol catalog" in sym("NOPE")


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

async def test_bulk_add_and_remove_persist_to_env_and_notify(wl):
    from app.config import settings

    seen = []
    wl.on_change("test", lambda added, removed: seen.append((added, removed)))

    result = await wl.add(["aapl", "BRK.B", "btc-usd", "SPY", "NOPE", "RELIANCE.NSE", "aapl"])
    assert result["added"] == ["AAPL.NASDAQ", "BRK-B.NYSE", "BTC-USD"]
    assert result["already"] == ["SPY.NYSE"]
    assert {r["symbol"] for r in result["rejected"]} == {"NOPE", "RELIANCE.NSE"}
    assert settings.us_symbols == "SPY.NYSE,AAPL.NASDAQ,BRK-B.NYSE"
    assert settings.crypto_symbols == "BTC-USD"
    env = wl._ENV_PATH.read_text(encoding="utf-8")
    assert "US_SYMBOLS=SPY.NYSE,AAPL.NASDAQ,BRK-B.NYSE" in env
    assert "CRYPTO_SYMBOLS=BTC-USD" in env
    assert seen == [(["AAPL.NASDAQ", "BRK-B.NYSE", "BTC-USD"], [])]

    result = await wl.remove(["aapl", "BTC/USD", "MSFT"])
    assert result["removed"] == ["AAPL.NASDAQ", "BTC-USD"]
    assert result["missing"] == ["MSFT"]
    env = wl._ENV_PATH.read_text(encoding="utf-8")
    assert "US_SYMBOLS=SPY.NYSE,BRK-B.NYSE" in env
    assert "CRYPTO_SYMBOLS=\n" in env
    assert seen[-1] == ([], ["AAPL.NASDAQ", "BTC-USD"])


async def test_add_is_uncapped(wl, monkeypatch):
    from app.config import settings
    from app.data_layer import watchlist as module

    many = [module._equity_row(_eq(f"T{i:04d}", f"Test {i}"), {}) for i in range(1500)]
    module._install(_rows() + many, time.time(), "test")
    result = await wl.add([r["ticker"] for r in many])
    assert len(result["added"]) == 1500 and not result["rejected"]
    assert len(settings.us_symbols.split(",")) == 1501


async def test_add_without_catalog_rejects_and_leaves_env_alone(wl, monkeypatch):
    wl._install([], 0, None)
    monkeypatch.setattr(wl, "_next_refresh", 0.0)  # no keys, no cache -> empty catalog
    before = wl._ENV_PATH.read_text(encoding="utf-8")

    result = await wl.add(["AAPL"])

    assert result["added"] == []
    assert "Alpaca API keys" in result["rejected"][0]["reason"]
    assert wl._ENV_PATH.read_text(encoding="utf-8") == before


async def test_remove_works_offline_and_matches_any_suffix(wl, monkeypatch):
    from app.config import settings

    wl._install([], 0, None)
    monkeypatch.setattr(settings, "us_symbols", "SPY.NYSE,AMD.US,ORCL.NYSE")
    result = await wl.remove(["amd", "ORCL"])
    assert result["removed"] == ["AMD.US", "ORCL.NYSE"]
    assert settings.us_symbols == "SPY.NYSE"


# ---------------------------------------------------------------------------
# Live feeds + batched ingestion
# ---------------------------------------------------------------------------

class _FakeWs:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, data):
        self.sent.append(json.loads(data))


async def test_alpaca_stream_resubscribes_live_and_trims_on_plan_limit():
    from app.data_layer.alpaca_feed import FREE_PLAN_STREAM_LIMIT, AlpacaFeed, stream_status

    feed = AlpacaFeed()
    feed._is_connected = True
    feed._ws = _FakeWs()
    feed._streaming = ["AAPL", "MSFT"]

    await feed.subscribe(["AAPL.NASDAQ", "BRK-B.NYSE"])
    assert feed._ws.sent == [
        {"action": "unsubscribe", "trades": ["MSFT"]},
        {"action": "subscribe", "trades": ["BRK.B"]},  # Alpaca's share-class spelling
    ]

    # 40 symbols on a free plan: the server rejects the subscribe; trim to the limit.
    feed._ws.sent.clear()
    feed._streaming = ["AAPL", "BRK.B"]
    feed._symbols = [f"S{i}" for i in range(40)]
    await feed._handle_control({"T": "error", "code": 405, "msg": "symbol limit exceeded"})
    assert feed._limit == FREE_PLAN_STREAM_LIMIT
    unsub, sub = feed._ws.sent
    assert set(unsub["trades"]) == {"AAPL", "BRK.B"}
    assert sub["trades"] == [f"S{i}" for i in range(30)]

    await feed._handle_control({"T": "subscription", "trades": sub["trades"]})
    assert stream_status["streaming"] == 30 and stream_status["requested"] == 40


async def test_snapshots_batch_hundreds_of_symbols_into_few_requests(monkeypatch):
    from app.config import settings
    from app.data_layer import alpaca_quotes

    monkeypatch.setattr(settings, "alpaca_api_key", "k")
    monkeypatch.setattr(settings, "alpaca_api_secret", "s")
    monkeypatch.setattr(alpaca_quotes, "_snapshot_cache", {})
    paths = []

    def handler(request):
        paths.append(request.url.path)
        tickers = request.url.params["symbols"].split(",")
        snaps = {t: {"latestTrade": {"p": 10.0}, "prevDailyBar": {"c": 8.0}} for t in tickers}
        if "crypto" in request.url.path:
            return httpx.Response(200, json={"snapshots": snaps})
        return httpx.Response(200, json=snaps)

    _mock_http(monkeypatch, handler)
    symbols = [f"T{i}.NASDAQ" for i in range(1199)] + ["BRK-B.NYSE", "BTC-USD", "RELI.NSE"]
    quotes = await alpaca_quotes.get_snapshots(symbols)

    assert paths.count("/v2/stocks/snapshots") == 3          # 1,200 stocks / 500 per call
    assert paths.count("/v1beta3/crypto/us/snapshots") == 1
    assert quotes["BRK-B.NYSE"] == {"price": 10.0, "prev_close": 8.0}
    assert quotes["BTC-USD"]["price"] == 10.0
    assert "RELI.NSE" not in quotes                           # never sent to Alpaca

    await alpaca_quotes.get_snapshots(symbols)                # served from the 10s cache
    assert len(paths) == 4


async def test_ingestion_prices_300_symbols_without_a_per_symbol_loop(monkeypatch):
    from app.config import settings
    from app.core.kv_store import get_kv_store
    from app.data_layer import alpaca_quotes
    from app.workers.data_ingestion_worker import DataIngestionWorker

    symbols = [f"T{i}.NASDAQ" for i in range(300)]
    monkeypatch.setattr(settings, "us_symbols", ",".join(symbols))
    snaps = {s: {"price": 100.0, "prev_close": 99.0} for s in symbols[:290]}
    get_snapshots = AsyncMock(return_value=snaps)
    monkeypatch.setattr(alpaca_quotes, "get_snapshots", get_snapshots)

    worker = DataIngestionWorker()
    batch = AsyncMock(return_value={s: 50.0 for s in symbols[290:]})
    monkeypatch.setattr(worker.data_manager.yahoo_feed, "fetch_latest_batch", batch)
    with patch("app.data_layer.yahoo_feed.yf.Ticker", side_effect=AssertionError("per-symbol")):
        await worker._refresh_prices(settings.all_symbols)

    get_snapshots.assert_awaited_once()
    batch.assert_awaited_once_with(symbols[290:])  # one fallback call for the rest
    kv = get_kv_store()
    assert await kv.get("horizon:price:T0.NASDAQ") == "100.0"
    assert await kv.get("horizon:price:prev_close:T0.NASDAQ") == "99.0"
    assert await kv.get("horizon:price:T299.NASDAQ") == "50.0"


# ---------------------------------------------------------------------------
# Front ends
# ---------------------------------------------------------------------------

async def test_desktop_api_search_add_remove(wl):
    from fastapi.testclient import TestClient

    from app.main import app

    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as client:
        body = client.get("/api/desktop/watchlist/search", params={"q": "apple"}).json()
        assert body["total"] == 1 and body["results"][0]["symbol"] == "AAPL.NASDAQ"

        cats = client.get("/api/desktop/watchlist/categories").json()
        assert {g["id"] for g in cats["groups"]} == {"sp500", "etf", "crypto"}

        added = client.post("/api/desktop/watchlist/add",
                            json={"symbols": ["AAPL", "NOPE"]}).json()
        assert added["added"] == ["AAPL.NASDAQ"] and added["ok"] is False
        assert added["rejected"][0]["symbol"] == "NOPE"

        listing = client.get("/api/desktop/watchlist").json()
        assert [w["symbol"] for w in listing["watchlist"]] == ["SPY.NYSE", "AAPL.NASDAQ"]
        assert listing["watchlist"][1]["name"] == "Apple Inc."
        assert "S&P 500" in listing["note"]

        removed = client.post("/api/desktop/watchlist/remove", json={"symbols": "AAPL"}).json()
        assert removed["removed"] == ["AAPL.NASDAQ"]


async def test_repl_watchlist_search_add_remove(wl):
    from app.tui.commands import CommandHandler

    handler = CommandHandler()
    out = await handler.handle("watchlist search apple")
    assert "AAPL" in out and "Apple Inc." in out

    out = await handler.handle("watchlist add AAPL XOM NOPE")
    assert "Added 2" in out and "AAPL.NASDAQ" in out and "Rejected NOPE" in out

    out = await handler.handle("watchlist browse energy")
    assert "XOM" in out

    out = await handler.handle("watchlist remove AAPL XOM")
    assert "Removed 2" in out
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D229F85769D3 - verify with scripts/authorship.py verify
