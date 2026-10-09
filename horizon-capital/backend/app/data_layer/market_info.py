# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-86F326F8B525
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""On-demand market info for any symbol: price history, key stats, news,
sentiment, market movers, and what the strategy is currently targeting.

Everything here is fetched when a screen asks for it and cached briefly. Nothing
subscribes a browsed symbol to the background feeds -- only the watchlist does.

History: Alpaca daily bars (the free plan serves 5 years of consolidated SIP
daily bars, measured Oct 2026), adjusted for splits and dividends, falling back
to IEX bars and then to yfinance. Five years are fetched once and shorter ranges
are sliced from them, so switching 1M/6M/1Y/5Y costs nothing after the first load.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger
from app.data_layer import alpaca_quotes
from app.data_layer import watchlist as wl

logger = get_logger("data.market_info")

RANGES = {"1M": 31, "6M": 183, "1Y": 366, "5Y": 1830}
_HISTORY_TTL = 600
_NEWS_TTL = 300
_MOVERS_TTL = 60
_MOVER_MIN_PRICE = 1.0

_history_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_news_cache: dict[str, tuple[float, list[str]]] = {}
_movers_cache: tuple[float, dict[str, Any]] | None = None


def _internal(symbol: str) -> tuple[str, dict[str, Any] | None]:
    row = wl.lookup(symbol)
    return (row["symbol"] if row else symbol.strip().upper()), row


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

async def _alpaca_bars(symbol: str, start: str) -> list[dict[str, Any]]:
    mapped = alpaca_quotes._snapshot_ticker(symbol)
    if mapped is None or not alpaca_quotes.is_configured():
        return []
    ticker, is_crypto = mapped
    base = alpaca_quotes._rest_base()
    # ponytail: one page -- 5y of daily bars is ~1,260 rows (~1,830 for 24/7
    # crypto), well under the 10,000-row page limit.
    if is_crypto:
        url, params = f"{base}/v1beta3/crypto/us/bars", {"symbols": ticker}
        attempts: list[dict[str, str]] = [{}]
    else:
        url, params = f"{base}/v2/stocks/{ticker}/bars", {"adjustment": "all"}
        attempts = [{}, {"feed": "iex"}]  # SIP history first; IEX if the plan refuses
    params.update(timeframe="1Day", start=start, limit="10000")
    async with httpx.AsyncClient(headers=alpaca_quotes._auth_headers(), timeout=20) as client:
        for extra in attempts:
            try:
                resp = await client.get(url, params={**params, **extra})
            except httpx.HTTPError as exc:
                logger.warning("history_alpaca_error", symbol=symbol, error=str(exc))
                return []
            if resp.status_code == 200:
                data = resp.json()
                raw = (data.get("bars") or {}).get(ticker, []) if is_crypto else data.get("bars")
                return [
                    {"time": b["t"][:10], "open": b["o"], "high": b["h"], "low": b["l"],
                     "close": b["c"], "volume": b.get("v", 0)}
                    for b in raw or []
                ]
            logger.info("history_alpaca_refused", symbol=symbol, status=resp.status_code, **extra)
    return []


async def _yahoo_bars(symbol: str) -> list[dict[str, Any]]:
    from app.data_layer.yahoo_feed import YahooFeed

    try:
        bars = await YahooFeed().poll_ohlcv(symbol, period="5y", interval="1d")
    except Exception as exc:
        logger.warning("history_yahoo_error", symbol=symbol, error=str(exc))
        return []
    return [
        {"time": b.timestamp.date().isoformat(), "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ]


async def _five_years(symbol: str) -> dict[str, Any]:
    hit = _history_cache.get(symbol)
    if hit and hit[0] > time.time():
        return hit[1]
    start = (date.today() - timedelta(days=RANGES["5Y"])).isoformat()
    bars, source = await _alpaca_bars(symbol, start), "alpaca"
    if not bars:
        bars, source = await _yahoo_bars(symbol), "yahoo"
    full = {"bars": bars, "source": source if bars else None}
    if bars:  # never cache a miss -- the next click should try again
        _history_cache[symbol] = (time.time() + _HISTORY_TTL, full)
    return full


async def history(symbol: str, rng: str = "1Y") -> dict[str, Any]:
    """``{symbol, range, source, bars: [{time, open, high, low, close, volume}]}``."""
    rng = rng.upper() if rng.upper() in RANGES else "1Y"
    internal, _ = _internal(symbol)
    full = await _five_years(internal)
    cutoff = (date.today() - timedelta(days=RANGES[rng])).isoformat()
    return {
        "symbol": internal,
        "range": rng,
        "source": full["source"],
        "bars": [b for b in full["bars"] if b["time"] >= cutoff],
    }


def stats(bars: list[dict[str, Any]]) -> dict[str, float | None]:
    """52-week range and volume from daily bars (newest last)."""
    year = bars[-252:]
    if not year:
        return {"high_52w": None, "low_52w": None, "avg_volume_30d": None, "volume": None}
    month = year[-30:]
    return {
        "high_52w": max(b["high"] for b in year),
        "low_52w": min(b["low"] for b in year),
        "avg_volume_30d": sum(b["volume"] for b in month) / len(month),
        "volume": year[-1]["volume"],
    }


# ---------------------------------------------------------------------------
# Detail: quote + stats + news + sentiment
# ---------------------------------------------------------------------------

async def _news(row: dict[str, Any] | None, internal: str) -> list[str]:
    from app.agents.front_office.research.alpaca_news import (
        alpaca_news_configured,
        fetch_headlines_by_symbol,
    )

    if not alpaca_news_configured():
        return []
    # Alpaca news tags crypto as BTCUSD. Share classes (BRK.B) don't survive the
    # helper's split on "." -- they come back empty rather than wrong.
    tag = internal.replace("-USD", "USD") if row and row["asset_class"] == "crypto" \
        else (row["ticker"] if row else internal.split(".")[0])
    hit = _news_cache.get(tag)
    if hit and hit[0] > time.time():
        return hit[1]
    headlines = (await fetch_headlines_by_symbol([tag], hours_back=72)).get(tag, [])[:8]
    _news_cache[tag] = (time.time() + _NEWS_TTL, headlines)
    return headlines


async def _sentiment(internal: str) -> dict[str, Any] | None:
    from app.core.kv_store import get_kv_store

    data = await get_kv_store().hgetall(f"horizon:sentiment:{internal.split('.')[0]}")
    if not data:
        return None
    try:
        score = float(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    return {"label": data.get("label", "neutral"), "score": score,
            "timestamp": data.get("timestamp")}


async def detail(symbol: str) -> dict[str, Any]:
    """Everything the detail panel / `watchlist info` shows, for any symbol."""
    await wl.load_catalog()
    internal, row = _internal(symbol)
    quotes, full, news = await asyncio.gather(
        wl.quotes([internal]), _five_years(internal), _news(row, internal),
        return_exceptions=True,
    )
    if isinstance(quotes, BaseException):
        raise quotes
    if isinstance(full, BaseException):
        logger.warning("detail_history_error", symbol=internal, error=str(full))
        full = {"bars": [], "source": None}
    if isinstance(news, BaseException):  # headlines are garnish, never fail the panel
        logger.warning("detail_news_error", symbol=internal, error=str(news))
        news = []
    quote = quotes[internal]
    on_list = {wl.entry_key(s) for s in wl.current_symbols()}
    return {
        "symbol": internal,
        "ticker": row["ticker"] if row else internal.split(".")[0],
        "name": row["name"] if row else None,
        "exchange": row["exchange"] if row else None,
        "sector": row["sector"] if row else None,
        "asset_class": row["asset_class"] if row else None,
        "tradable": bool(row and row["tradable"]),
        "in_catalog": row is not None,
        "on_watchlist": wl.entry_key(internal) in on_list,
        "quote": quote,
        "stats": stats(full["bars"]),
        "history_source": full["source"],
        "sentiment": await _sentiment(internal),
        "news": news,
    }


# ---------------------------------------------------------------------------
# Recommended: strategy picks, market movers, news sentiment
# ---------------------------------------------------------------------------

def _row_view(symbol: str, quotes: dict[str, dict[str, float]], on_list: set[str]) -> dict:
    row = wl.lookup(symbol)
    internal = row["symbol"] if row else symbol
    return {
        "symbol": internal,
        "ticker": row["ticker"] if row else internal.split(".")[0],
        "name": row["name"] if row else None,
        "exchange": row["exchange"] if row else None,
        "tradable": bool(row and row["tradable"]),
        "on_watchlist": wl.entry_key(internal) in on_list,
        **quotes.get(internal, {"price": 0.0, "prev_close": 0.0, "change_pct": 0.0}),
    }


async def _held_symbols() -> set[str]:
    from sqlalchemy import text

    from app.core.runtime import get_session_factory

    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                text("SELECT symbol FROM positions WHERE quantity != 0")
            )
            return {wl.entry_key(r.symbol) for r in result.fetchall()}
    except Exception:
        return set()


async def strategy_picks(orchestrator: Any = None) -> dict[str, Any]:
    """What the validated strategy targets right now, with the sleeve and reason.

    Live: the running StrategyAgent's per-sleeve cache. Engine stopped: the
    latest persisted sleeve signal per symbol (no sleeve attribution there).
    """
    agent = None
    for slot in (getattr(orchestrator, "_slots", None) or {}).values():
        if slot.agent.agent_type == "strategy":
            agent = slot.agent
            break

    picks: list[dict[str, Any]] = []
    if agent is not None:
        source = "live"
        for sleeve in agent._sleeves:
            for sig in agent._sleeve_cache.get(sleeve.name, []):
                weight = sig.target_weight * sleeve.target_weight
                if abs(weight) > 1e-6:
                    picks.append({"symbol": sig.symbol, "weight": weight, "sleeve": sleeve.name,
                                  "reason": sig.reason, "as_of": None})
    else:
        source = "signals"
        from sqlalchemy import text

        from app.core.runtime import get_session_factory

        latest: dict[str, dict[str, Any]] = {}
        try:
            async with get_session_factory()() as session:
                result = await session.execute(text(
                    "SELECT symbol, metadata, created_at FROM signals "
                    "WHERE strategy_name = 'sleeve_system' ORDER BY created_at DESC LIMIT 2000"
                ))
                rows = result.fetchall()
        except Exception:
            rows = []
        for r in rows:
            if r.symbol in latest:
                continue
            try:
                meta = json.loads(r.metadata or "{}")
            except (TypeError, ValueError):
                meta = {}
            latest[r.symbol] = {"symbol": r.symbol, "weight": float(meta.get("target_weight") or 0),
                                "sleeve": None, "reason": meta.get("reasoning") or "",
                                "as_of": str(r.created_at)}
        picks = [p for p in latest.values() if abs(p["weight"]) > 1e-6]

    picks.sort(key=lambda p: -abs(p["weight"]))
    quotes = await wl.quotes([_internal(p["symbol"])[0] for p in picks])
    on_list = {wl.entry_key(s) for s in wl.current_symbols()}
    held = await _held_symbols()
    out = []
    for p in picks:
        view = _row_view(p["symbol"], quotes, on_list)
        out.append({**view, "weight": p["weight"], "sleeve": p["sleeve"],
                    "reason": p["reason"], "as_of": p["as_of"],
                    "held": wl.entry_key(p["symbol"]) in held})
    return {"source": source, "picks": out}


async def movers(top: int = 10) -> dict[str, Any]:
    """Alpaca screener: gainers, losers, most active. Market activity, not advice."""
    global _movers_cache
    if _movers_cache and _movers_cache[0] > time.time():
        return _movers_cache[1]
    empty: dict[str, Any] = {"gainers": [], "losers": [], "most_actives": [],
                             "last_updated": None, "error": None}
    if not alpaca_quotes.is_configured():
        return {**empty, "error": "Add Alpaca API keys to see market movers"}

    base = alpaca_quotes._rest_base() + "/v1beta1/screener/stocks"
    try:
        async with httpx.AsyncClient(headers=alpaca_quotes._auth_headers(), timeout=15) as c:
            mv = await c.get(f"{base}/movers", params={"top": 50})
            ac = await c.get(f"{base}/most-actives", params={"by": "volume", "top": 50})
        mv.raise_for_status()
        ac.raise_for_status()
        moved, active = mv.json(), ac.json()
    except Exception as exc:
        logger.warning("movers_error", error=str(exc))
        return {**empty, "error": f"Alpaca screener unavailable ({type(exc).__name__})"}

    await wl.load_catalog()
    lists = {
        "gainers": [m["symbol"] for m in moved.get("gainers", [])],
        "losers": [m["symbol"] for m in moved.get("losers", [])],
        "most_actives": [m["symbol"] for m in active.get("most_actives", [])],
    }
    # Gainers/losers carry the screener's own price and % change; a snapshot's
    # "previous close" can be days stale for thin names and contradict the list.
    screened = {m["symbol"]: m for k in ("gainers", "losers") for m in moved.get(k, [])}
    rows = {t: wl.lookup(t) for ts in lists.values() for t in ts}
    # Junk filter (said so in the UI): warrants/penny names dominate raw movers.
    keep = {
        t: r for t, r in rows.items()
        if r and r["tradable"] and r["asset_class"] == "us_equity"
    }
    quotes = await wl.quotes([r["symbol"] for r in keep.values()])
    on_list = {wl.entry_key(s) for s in wl.current_symbols()}
    out: dict[str, Any] = {"last_updated": moved.get("last_updated") or active.get("last_updated"),
                           "error": None,
                           "filter": f"Tradable on Alpaca, price at least ${_MOVER_MIN_PRICE:.0f}"}
    for name, tickers in lists.items():
        views = []
        for t in tickers:
            if t not in keep:
                continue
            view = _row_view(keep[t]["symbol"], quotes, on_list)
            if t in screened and name != "most_actives":
                m = screened[t]
                view.update(price=float(m["price"]), change_pct=float(m["percent_change"]),
                            prev_close=float(m["price"]) - float(m["change"]))
            views.append(view)
        out[name] = [v for v in views if v["price"] >= _MOVER_MIN_PRICE][:top]
    _movers_cache = (time.time() + _MOVERS_TTL, out)
    return out


async def sentiment_leaders(limit: int = 10) -> list[dict[str, Any]]:
    """Watchlisted names with a non-neutral news-sentiment reading in KV."""
    symbols = wl.current_symbols()
    readings = []
    for symbol in symbols:
        s = await _sentiment(symbol)
        if s and s["label"] != "neutral" and s["score"] > 0:
            readings.append((symbol, s))
    readings.sort(key=lambda x: -x[1]["score"])
    readings = readings[:limit]
    quotes = await wl.quotes([_internal(s)[0] for s, _ in readings])
    on_list = {wl.entry_key(s) for s in symbols}
    return [{**_row_view(sym, quotes, on_list), "sentiment": s} for sym, s in readings]


async def recommended(orchestrator: Any = None) -> dict[str, Any]:
    await wl.load_catalog()
    return {
        "strategy": await strategy_picks(orchestrator),
        "movers": await movers(),
        "sentiment": await sentiment_leaders(),
        "generated_at": datetime.now(UTC).isoformat(),
        "disclaimer": ("Strategy picks are what Horizon's strategy currently holds/targets -- "
                       "not personal advice. Movers are market activity, not recommendations."),
    }
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 86F326F8B525 - verify with scripts/authorship.py verify
