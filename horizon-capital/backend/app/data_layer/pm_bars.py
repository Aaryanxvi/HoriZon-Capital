"""Daily OHLCV-shaped bars for Polymarket ``.POLY`` symbols.

fetch_batch (yfinance) can't resolve these — this hits the CLOB prices-history
endpoint instead, keyed off the token_id written to KV by polymarket_feed.
Probability is not a price, but the sleeve API expects OHLCV columns, so
open=high=low=close=p and volume=0.0.

ponytail: in-memory cache, same TTL pattern as batch_bars.py.
"""
from __future__ import annotations

import json
import time

import httpx
import pandas as pd

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger

logger = get_logger("data.pm_bars")

_HISTORY_URL = "https://clob.polymarket.com/prices-history"
_TTL = 6 * 3600
_cache: dict[str, tuple[pd.DataFrame, float]] = {}


async def _token_id(symbol: str) -> str | None:
    kv = get_kv_store()
    raw = await kv.get(f"horizon:pm:meta:{symbol}")
    if not raw:
        logger.debug("pm_bars_no_meta", symbol=symbol)
        return None
    try:
        return json.loads(raw).get("token_id")
    except Exception:
        logger.debug("pm_bars_meta_parse_error", symbol=symbol)
        return None


def _to_bars(history: list[dict]) -> pd.DataFrame | None:
    if not history:
        return None
    idx = pd.to_datetime([h["t"] for h in history], unit="s").normalize()
    close = pd.Series([float(h["p"]) for h in history], index=idx)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 0.0}
    )


async def fetch_pm_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Return {symbol -> daily OHLCV df} for Polymarket symbols, cached 6h."""
    now = time.monotonic()
    out: dict[str, pd.DataFrame] = {
        s: _cache[s][0] for s in symbols if s in _cache and now - _cache[s][1] < _TTL
    }
    stale = [s for s in symbols if s not in out]
    if not stale:
        return out

    async with httpx.AsyncClient(timeout=20.0) as client:
        for symbol in stale:
            token_id = await _token_id(symbol)
            if not token_id:
                continue
            try:
                resp = await client.get(
                    _HISTORY_URL,
                    params={"market": token_id, "interval": "max", "fidelity": 1440},
                )
                if resp.status_code != 200:
                    logger.warning("pm_bars_http_error", symbol=symbol, status=resp.status_code)
                    continue
                df = _to_bars(resp.json().get("history", []))
                if df is not None:
                    _cache[symbol] = (df, now)
                    out[symbol] = df
            except Exception as exc:
                logger.warning("pm_bars_fetch_error", symbol=symbol, error=str(exc))

    return out
