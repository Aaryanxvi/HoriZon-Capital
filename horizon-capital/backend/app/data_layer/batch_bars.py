"""Batched, cached daily-bar fetch for a large universe.

One download for the whole universe instead of N sequential per-symbol calls —
the thing that lets the live system scale from a handful of names to hundreds.
Daily bars only change at the close, so results are cached in memory with a
multi-hour TTL: the first poll of a session fetches everything once; subsequent
60s polls read the cache for free.

ponytail: in-memory cache, not the ohlcv DB table. Upgrade to DB-backed caching
if a single process's memory or a restart-cost becomes a real constraint.
"""
from __future__ import annotations

import asyncio
import time

import pandas as pd

from app.core.logging import get_logger

logger = get_logger("data.batch_bars")

_TTL = 6 * 3600  # daily bars refresh a few times/day at most
_OHLCV = ["open", "high", "low", "close", "volume"]
_cache: dict[str, tuple[pd.DataFrame, float]] = {}


def _base(symbol: str) -> str:
    return symbol.split(".")[0] if "." in symbol else symbol


def _download(bases: list[str], period: str):
    import yfinance as yf

    return yf.download(
        " ".join(bases), period=period, interval="1d",
        auto_adjust=True, group_by="ticker", progress=False, threads=True,
    )


def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
    df = df.dropna()
    df.columns = [str(c).lower() for c in df.columns]
    if not set(_OHLCV) <= set(df.columns) or len(df) < 2:
        return None
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = df[_OHLCV].copy()
    out.index = idx.normalize()
    return out


async def fetch_batch(symbols: list[str], period: str = "1200d") -> dict[str, pd.DataFrame]:
    """Return {suffixed_symbol -> OHLCV df} for ``symbols``, batched + cached.

    1200d ≈ 820 trading days: covers multi_signal's 756-bar ltr lookback and
    regime_hmm's 277-bar minimum ("400d" left both silently dead in live).
    """
    now = time.monotonic()
    fresh: dict[str, pd.DataFrame] = {
        s: _cache[s][0] for s in symbols if s in _cache and now - _cache[s][1] < _TTL
    }
    stale = [s for s in symbols if s not in fresh]
    if not stale:
        return fresh

    # base ticker -> one representative suffixed symbol (dedup same underlying)
    base_map: dict[str, str] = {}
    for s in stale:
        base_map.setdefault(_base(s), s)
    bases = list(base_map)

    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, _download, bases, period)
    except Exception as exc:
        logger.warning("batch_download_failed", error=str(exc), n=len(bases))
        return fresh

    if raw is None or raw.empty:
        logger.warning("batch_download_empty", n=len(bases))
        return fresh

    single = len(bases) == 1
    for base, sym in base_map.items():
        try:
            sub = raw if single else raw[base]
            norm = _normalize(sub)
            if norm is not None:
                _cache[sym] = (norm, now)
                fresh[sym] = norm
        except Exception:
            continue  # delisted / missing in batch — skip

    logger.info(
        "batch_bars_fetched",
        requested=len(stale), got=sum(1 for s in stale if s in fresh),
    )
    return fresh


def _demo() -> None:
    syms = ["AAPL.NASDAQ", "MSFT.NASDAQ", "SPY.NYSE"]
    out = asyncio.run(fetch_batch(syms, period="60d"))
    assert out, "expected bars for at least some symbols"
    for s, df in out.items():
        assert set(_OHLCV) <= set(df.columns), f"{s} missing OHLCV cols"
        assert len(df) > 5, f"{s} too few rows"
    print(f"batch_bars demo OK: {len(out)}/{len(syms)} symbols, "
          f"{[(s, len(d)) for s, d in out.items()]}")


if __name__ == "__main__":
    _demo()
