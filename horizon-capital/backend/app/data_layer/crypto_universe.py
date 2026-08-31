"""Auto-discovered crypto universe for the crypto trend sleeve.

The sleeve's static BTC/ETH pair is the fallback. With
``CRYPTO_DISCOVERY_ENABLED`` the universe becomes the top-N coins by market cap
from CoinGecko, minus the things that are not independent return sources
(stablecoins) or are duplicates of a coin already in the list (wrapped, staked,
and bridged derivatives track their underlying almost exactly — holding both
doubles the exposure while looking like diversification).

The result is intersected with what the execution broker can actually fill, so
discovery cannot produce a signal that dies as a broker rejection.

ponytail: in-memory cache with a 24h TTL, same pattern as batch_bars.py — market
cap rank moves on the scale of weeks, not minutes.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger("data.crypto_universe")

_COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
_ALPACA_ASSETS_PATH = "/v2/assets"
_TTL = 24 * 3600
# Daily bars a coin needs before the sleeve's 200d SMA rule can look at it.
_MIN_BARS = 210

DEFAULT_UNIVERSE: tuple[str, ...] = ("BTC-USD", "ETH-USD")

# Pegged to a dollar — no trend to follow.
_STABLE_SYMBOLS = frozenset(
    {
        "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDE", "USDS", "FDUSD", "PYUSD",
        "USDD", "FRAX", "GUSD", "LUSD", "USD1", "RLUSD", "EURC", "USDP",
    }
)
# Derivative wrappers that track a coin already eligible above.
_DERIVATIVE_MARKERS = (
    "wrapped", "staked", "bridged", "peg", "liquid-stak", "restaked", "-token-pool",
)

_universe: tuple[str, ...] = DEFAULT_UNIVERSE
_universe_at: float = 0.0
_tradable: frozenset[str] | None = None
_tradable_at: float = 0.0
# Base symbol -> CoinGecko id, harvested from the discovery payload so the tick
# feed can price a discovered coin that isn't in its static map.
_cg_ids: dict[str, str] = {}


def crypto_universe() -> tuple[str, ...]:
    """Current universe. ``DEFAULT_UNIVERSE`` until a refresh succeeds."""
    from app.config import settings

    if not settings.crypto_discovery_enabled:
        return DEFAULT_UNIVERSE
    return _universe


def coingecko_id(base: str) -> str | None:
    """CoinGecko id for a base symbol (``SOL``), if discovery has seen it."""
    return _cg_ids.get(base.upper())


def _is_derivative(coin: dict[str, Any]) -> bool:
    blob = f"{coin.get('id', '')} {coin.get('name', '')}".lower()
    return any(marker in blob for marker in _DERIVATIVE_MARKERS)


def _filter_coins(
    coins: list[dict[str, Any]],
    *,
    top_n: int,
    tradable: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Rank CoinGecko ``/coins/markets`` rows into ``BTC-USD``-style symbols.

    ``tradable`` (bases the broker supports) filters the result when supplied.
    Input is assumed market-cap ordered; ties are left in payload order.
    """
    out: list[str] = []
    seen: set[str] = set()
    for coin in coins:
        raw = str(coin.get("symbol") or "").upper()
        if not raw or raw in seen:
            continue
        if raw in _STABLE_SYMBOLS or _is_derivative(coin):
            continue
        if tradable is not None and raw not in tradable:
            continue
        seen.add(raw)
        out.append(f"{raw}-USD")
        if len(out) >= top_n:
            break
    return tuple(out)


async def _with_bars(candidates: tuple[str, ...], top_n: int) -> tuple[str, ...]:
    """Keep candidates the bar source can actually price, capped at ``top_n``.

    Alpaca lists coins yfinance has never heard of (recent listings). The sleeve
    sizes 1/N over its universe and leaves the rest in cash, so an unpriceable
    coin would permanently strand its share — drop it here rather than at
    compute time, where a transient fetch failure must NOT concentrate the book.
    Fail-open: if the check itself fails, keep the ranking as-is.
    """
    from app.data_layer.batch_bars import fetch_batch

    try:
        bars = await fetch_batch(list(candidates), period="400d")
    except Exception as exc:
        logger.warning("crypto_bar_check_error", error=str(exc))
        return candidates[:top_n]
    if not bars:
        return candidates[:top_n]

    priced = tuple(s for s in candidates if len(bars.get(s, ())) >= _MIN_BARS)
    dropped = [s for s in candidates[:top_n] if s not in priced]
    if dropped:
        logger.info("crypto_discovery_unpriceable", dropped=dropped)
    return priced[:top_n] or candidates[:top_n]


async def _alpaca_tradable_bases() -> frozenset[str] | None:
    """Crypto bases Alpaca will accept, or None when the check can't run.

    None means "don't filter" — a discovery list that silently empties itself
    because the assets endpoint blipped is worse than an occasional reject.
    """
    global _tradable, _tradable_at

    from app.config import settings

    if settings.execution_broker.upper() != "ALPACA":
        return None
    if not (settings.alpaca_api_key and settings.alpaca_api_secret):
        return None

    now = time.monotonic()
    if _tradable is not None and now - _tradable_at < _TTL:
        return _tradable

    url = settings.alpaca_base_url.rstrip("/") + _ALPACA_ASSETS_PATH
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                params={"asset_class": "crypto", "status": "active"},
                headers=headers,
            )
        if resp.status_code != 200:
            logger.warning("alpaca_assets_http_error", status=resp.status_code)
            return _tradable
        assets = resp.json()
    except Exception as exc:
        logger.warning("alpaca_assets_error", error=str(exc))
        return _tradable

    bases = {
        str(a.get("symbol", "")).split("/")[0].upper()
        for a in assets
        if a.get("tradable", True) and str(a.get("symbol", "")).endswith("/USD")
    }
    if not bases:
        return _tradable

    _tradable = frozenset(bases)
    _tradable_at = now
    logger.info("alpaca_crypto_assets_loaded", n=len(_tradable))
    return _tradable


async def refresh_crypto_universe(*, force: bool = False) -> tuple[str, ...]:
    """Rebuild the universe from CoinGecko market caps. Cached 24h, fail-open."""
    global _universe, _universe_at

    from app.config import settings

    if not settings.crypto_discovery_enabled:
        return DEFAULT_UNIVERSE

    now = time.monotonic()
    if not force and _universe_at and now - _universe_at < _TTL:
        return _universe

    top_n = max(int(settings.crypto_discovery_top_n), 0)
    if top_n == 0:
        return DEFAULT_UNIVERSE

    # Over-fetch: stablecoins and wrappers occupy much of the top of the table.
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": str(min(top_n * 6, 250)),
        "page": "1",
        "sparkline": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_COINGECKO_MARKETS_URL, params=params)
        if resp.status_code != 200:
            logger.warning("crypto_discovery_http_error", status=resp.status_code)
            return _universe
        coins = resp.json()
    except Exception as exc:
        logger.warning("crypto_discovery_error", error=str(exc))
        return _universe

    if not isinstance(coins, list) or not coins:
        logger.warning("crypto_discovery_bad_payload")
        return _universe

    tradable = await _alpaca_tradable_bases()
    # Over-select, then let the bar check pick the first top_n that are priceable.
    candidates = _filter_coins(coins, top_n=top_n * 3, tradable=tradable)
    if not candidates:
        logger.warning("crypto_discovery_empty_after_filter")
        return _universe
    universe = await _with_bars(candidates, top_n)
    if not universe:
        logger.warning("crypto_discovery_empty_after_filter")
        return _universe

    for coin in coins:
        base = str(coin.get("symbol") or "").upper()
        cg_id = str(coin.get("id") or "")
        if base and cg_id:
            _cg_ids.setdefault(base, cg_id)

    _universe = universe
    _universe_at = now
    logger.info("crypto_discovery_refreshed", universe=list(universe))
    return _universe


def _demo() -> None:
    coins = [
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"},
        {"id": "tether", "symbol": "usdt", "name": "Tether"},
        {"id": "ethereum", "symbol": "eth", "name": "Ethereum"},
        {"id": "wrapped-steth", "symbol": "wsteth", "name": "Wrapped stETH"},
        {"id": "solana", "symbol": "sol", "name": "Solana"},
    ]
    assert _filter_coins(coins, top_n=5) == ("BTC-USD", "ETH-USD", "SOL-USD")
    assert _filter_coins(coins, top_n=2) == ("BTC-USD", "ETH-USD")
    assert _filter_coins(coins, top_n=5, tradable=frozenset({"BTC", "ETH"})) == (
        "BTC-USD",
        "ETH-USD",
    )
    print("crypto_universe demo OK")


if __name__ == "__main__":
    _demo()
