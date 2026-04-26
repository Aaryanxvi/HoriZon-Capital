"""Lightweight Alpaca REST client for live quotes + historical bars.

Used by the strategy agent (for daily bars) and the paper broker (for the
latest trade price at fill time). Separate from ``AlpacaFeed`` which drives
the tick stream — this helper is stateless, async, and keeps an in-memory
micro-cache so repeated calls within a few seconds don't re-hit the API.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
import pandas as pd

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("data.alpaca_quotes")

# Alpaca market data API is a single endpoint regardless of paper/live.
# (The "sandbox" data host returns 401.)
_DATA_REST = "https://data.alpaca.markets"

# Latest-trade cache lifetime. Strategy polls every 60s, paper broker fires
# per-fill; 2s is short enough to stay "live" but absorbs bursts.
_LATEST_TRADE_CACHE_TTL = 2.0
# Daily-bar cache lifetime — bars only change once per trading day.
_BARS_CACHE_TTL = 300.0


@dataclass
class _CacheEntry:
    value: object
    expires_at: float


_price_cache: dict[str, _CacheEntry] = {}
_bars_cache: dict[tuple[str, str, int], _CacheEntry] = {}
_cache_lock = asyncio.Lock()


def _rest_base() -> str:
    return _DATA_REST


def _auth_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }


def _strip_exchange(symbol: str) -> str:
    return symbol.rsplit(".", 1)[0] if "." in symbol else symbol


def is_configured() -> bool:
    """True if Alpaca credentials are present in settings."""
    return bool(settings.alpaca_api_key and settings.alpaca_api_secret)


async def get_latest_price(symbol: str) -> float | None:
    """Return the latest trade price for ``symbol`` from Alpaca, or None.

    Uses a 2-second in-memory cache. Returns None on network failure, missing
    credentials, or non-US instruments.
    """
    if not is_configured():
        return None

    clean = _strip_exchange(symbol)
    now = time.time()

    async with _cache_lock:
        cached = _price_cache.get(clean)
        if cached and cached.expires_at > now:
            return float(cached.value)  # type: ignore[arg-type]

    url = f"{_rest_base()}/v2/stocks/{clean}/trades/latest"
    try:
        async with httpx.AsyncClient(headers=_auth_headers(), timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(
                    "alpaca_quotes.latest_price_error",
                    status=resp.status_code,
                    symbol=clean,
                )
                return None
            price = float(resp.json().get("trade", {}).get("p", 0.0))
            if price <= 0:
                return None
    except Exception as exc:
        logger.warning("alpaca_quotes.latest_price_exc", symbol=clean, error=str(exc))
        return None

    async with _cache_lock:
        _price_cache[clean] = _CacheEntry(
            value=price, expires_at=now + _LATEST_TRADE_CACHE_TTL
        )
    return price


async def get_bars(
    symbol: str, timeframe: str = "1Day", lookback_days: int = 60
) -> pd.DataFrame | None:
    """Return a DataFrame of OHLCV bars indexed by timestamp, or None.

    DataFrame columns: open, high, low, close, volume.
    """
    if not is_configured():
        return None

    clean = _strip_exchange(symbol)
    cache_key = (clean, timeframe, lookback_days)
    now = time.time()

    async with _cache_lock:
        cached = _bars_cache.get(cache_key)
        if cached and cached.expires_at > now:
            return cached.value  # type: ignore[return-value]

    start_iso = (
        pd.Timestamp.utcnow() - pd.Timedelta(days=lookback_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{_rest_base()}/v2/stocks/{clean}/bars"
    params = {"timeframe": timeframe, "start": start_iso, "limit": 10_000}

    try:
        async with httpx.AsyncClient(headers=_auth_headers(), timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "alpaca_quotes.bars_error",
                    status=resp.status_code,
                    symbol=clean,
                    body=resp.text[:200],
                )
                return None
            bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning("alpaca_quotes.bars_exc", symbol=clean, error=str(exc))
        return None

    if not bars:
        return None

    df = pd.DataFrame(bars)
    df = df.rename(
        columns={
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)

    async with _cache_lock:
        _bars_cache[cache_key] = _CacheEntry(
            value=df, expires_at=now + _BARS_CACHE_TTL
        )
    return df
