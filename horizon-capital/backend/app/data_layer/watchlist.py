# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-75E9E7E16A11
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Watchlist: a searchable catalog of everything addable, plus live add/remove.

The watchlist is what you monitor and can trade by hand -- ``US_SYMBOLS`` and
``CRYPTO_SYMBOLS`` in .env. It is NOT the strategy's universe: with
``UNIVERSE_SOURCE=sp500`` the strategy picks from the S&P 500 on its own
(``universe.py``), so nothing here changes what the validated strategy trades.

Catalog = Alpaca's active US equities/ETFs and USD crypto pairs, with GICS
sector for S&P 500 names. Cached to disk, refreshed daily, and the stale copy
is used when Alpaca is unreachable. India has no real feed or broker yet: a
Zerodha source would add ``india_equity`` rows and map them to INDIA_SYMBOLS
in ``_LIST_FOR`` -- until then the market is listed as unavailable.

Both front ends call ``add``/``remove`` here, so the terminal and the GUI share
one validation and persistence path. Changes reach running feeds through
``on_change`` listeners and the GUI through a bus event -- no restart.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("data.watchlist")

_TTL = 24 * 3600
_RETRY_AFTER_FAILURE = 300
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"  # backend/.env, as the REPL writes

# Alpaca listing venue -> the suffix the rest of the system uses. ARCA/AMEX/BATS
# map to NYSE because SPY, GLD and the XL* ETFs (all ARCA) are already ".NYSE".
_SUFFIX = {"NASDAQ": "NASDAQ", "OTC": "OTC"}
_KNOWN_SUFFIXES = {"NASDAQ", "NYSE", "OTC", "US", "ARCA", "AMEX", "BATS"}
# ponytail: Alpaca has no ETF flag. ARCA/BATS primary listings are ~all ETPs and
# the name catches the rest; a few oddly named funds slip through.
_ETF_RE = re.compile(r"\b(ETF|ETN)s?\b|Exchange[- ]Traded|^ProShares\b|^Direxion\b|QQQ Trust", re.I)

# env key per list, and which list each asset class lands in.
_LISTS = {"US_SYMBOLS": "us_symbols", "CRYPTO_SYMBOLS": "crypto_symbols",
          "INDIA_SYMBOLS": "india_symbols"}
_LIST_FOR = {"us_equity": "US_SYMBOLS", "crypto": "CRYPTO_SYMBOLS"}

INDIA_NOTE = "Indian stocks (NSE/BSE) arrive with the Zerodha integration"
MARKETS = [
    {"id": "us", "label": "US stocks & ETFs", "available": True},
    {"id": "crypto", "label": "Crypto (USD pairs)", "available": True},
    {"id": "india", "label": "India (NSE/BSE)", "available": False, "note": INDIA_NOTE},
]
GROUPS = {"sp500": "S&P 500", "etf": "ETFs", "crypto": "Crypto"}

_catalog: list[dict[str, Any]] = []
_by_symbol: dict[str, dict[str, Any]] = {}
_by_key: dict[str, dict[str, Any]] = {}
_index: list[tuple[str, str, dict[str, Any]]] = []  # (key lower, " name lower", row)
_meta: dict[str, Any] = {"updated_at": None, "source": None, "error": None}
_next_refresh = 0.0
_catalog_lock = asyncio.Lock()
_write_lock = asyncio.Lock()
_listeners: dict[str, Callable[[list[str], list[str]], Any]] = {}


# ---------------------------------------------------------------------------
# Symbol keys
# ---------------------------------------------------------------------------

def _key(ticker: str) -> str:
    """Exchange-free identity: ``BRK.B``/``BRK-B`` -> ``BRK-B``, ``BTC/USD`` -> ``BTC-USD``."""
    return ticker.strip().upper().replace("/", "-").replace(".", "-")


def entry_key(symbol: str) -> str:
    """Identity of a list entry or typed token: drops a known exchange suffix."""
    s = symbol.strip().upper()
    base, _, suffix = s.rpartition(".")
    return _key(base if base and suffix in _KNOWN_SUFFIXES else s)


def _split(csv: str) -> list[str]:
    return [s.strip() for s in csv.split(",") if s.strip()]


def current_symbols() -> list[str]:
    return list(settings.all_symbols)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def _cache_file() -> Path:
    base = os.getenv("HORIZON_DATA_DIR") or str(Path.home() / ".horizon-capital")
    return Path(base) / "symbol_catalog.json"


def _equity_row(asset: dict[str, Any], sp500: dict[str, dict[str, str]]) -> dict[str, Any]:
    ticker = asset["symbol"]
    key = _key(ticker)
    alpaca_name = (asset.get("name") or ticker).strip()
    info = sp500.get(key)
    exchange = asset.get("exchange") or ""
    return {
        "symbol": f"{key}.{_SUFFIX.get(exchange, 'NYSE')}",
        "ticker": ticker,
        "name": info["name"] if info else re.sub(r"\s+Common Stock$", "", alpaca_name),
        "exchange": exchange,
        "asset_class": "us_equity",
        "sector": info["sector"] if info else None,
        "sp500": bool(info),
        "etf": not info and (exchange in ("ARCA", "BATS") or bool(_ETF_RE.search(alpaca_name))),
        "tradable": bool(asset.get("tradable")),
        "fractionable": bool(asset.get("fractionable")),
    }


def _crypto_row(asset: dict[str, Any]) -> dict[str, Any] | None:
    base, _, quote = str(asset.get("symbol", "")).partition("/")
    if quote != "USD":  # USDT/USDC/BTC-quoted pairs have no place in a USD book
        return None
    return {
        "symbol": f"{base}-USD",
        "ticker": asset["symbol"],
        "name": (asset.get("name") or base).split(" / ")[0].strip(),
        "exchange": "CRYPTO",
        "asset_class": "crypto",
        "sector": None,
        "sp500": False,
        "etf": False,
        "tradable": bool(asset.get("tradable")),
        "fractionable": bool(asset.get("fractionable")),
    }


async def _fetch_catalog() -> list[dict[str, Any]]:
    """Alpaca assets (equities + crypto) enriched with S&P 500 sectors."""
    from app.data_layer import universe

    url = settings.alpaca_base_url.rstrip("/") + "/v2/assets"
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        equities, crypto = await asyncio.gather(
            client.get(url, params={"status": "active", "asset_class": "us_equity"}),
            client.get(url, params={"status": "active", "asset_class": "crypto"}),
        )
    equities.raise_for_status()
    crypto.raise_for_status()

    try:
        rows = await asyncio.to_thread(universe.fetch_sp500_rows)
        sp500 = {
            _key(r["Symbol"]): {"name": r.get("Security") or r["Symbol"],
                                "sector": r.get("GICS Sector") or None}
            for r in rows if r.get("Symbol")
        }
    except Exception as exc:  # sectors are enrichment; the catalog still works
        logger.warning("catalog_sp500_fetch_failed", error=str(exc))
        sp500 = {}

    out = [_equity_row(a, sp500) for a in equities.json()]
    out += [row for a in crypto.json() if (row := _crypto_row(a))]
    return out


def _install(rows: list[dict[str, Any]], saved_at: float, source: str) -> None:
    global _catalog, _by_symbol, _by_key, _index
    _catalog = rows
    _by_symbol = {r["symbol"]: r for r in rows}
    _by_key = {_key(r["ticker"]): r for r in rows}
    _index = [(_key(r["ticker"]).lower(), " " + r["name"].lower(), r) for r in rows]
    _meta.update(updated_at=saved_at, source=source)


def _read_cache() -> tuple[list[dict[str, Any]], float] | None:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        return data["rows"], float(data["saved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(rows: list[dict[str, Any]], saved_at: float) -> None:
    path = _cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"saved_at": saved_at, "rows": rows}), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("catalog_cache_write_failed", error=str(exc))


async def load_catalog(force: bool = False) -> list[dict[str, Any]]:
    """The catalog: memory, else a fresh disk cache, else Alpaca, else stale cache."""
    global _next_refresh
    async with _catalog_lock:
        now = time.time()
        if _catalog and not force and now < _next_refresh:
            return _catalog

        cached = None if force else _read_cache()
        if cached and now - cached[1] < _TTL:
            _install(cached[0], cached[1], "cache")
            _meta["error"] = None
            _next_refresh = cached[1] + _TTL
            return _catalog

        if settings.alpaca_api_key and settings.alpaca_api_secret:
            try:
                rows = await _fetch_catalog()
                _install(rows, now, "alpaca")
                _write_cache(rows, now)
                _meta["error"] = None
                _next_refresh = now + _TTL
                logger.info("catalog_refreshed", rows=len(rows))
                return _catalog
            except Exception as exc:
                logger.warning("catalog_fetch_failed", error=str(exc))
                _meta["error"] = f"Alpaca asset list unreachable ({type(exc).__name__})"
        else:
            _meta["error"] = "Add Alpaca API keys to load the symbol catalog"

        _next_refresh = now + _RETRY_AFTER_FAILURE
        if cached := (cached or _read_cache()):
            _install(cached[0], cached[1], "cache (stale)")
        return _catalog


def catalog_info() -> dict[str, Any]:
    return {"size": len(_catalog), **_meta}


def search(
    query: str = "",
    *,
    asset_class: str | None = None,
    exchange: str | None = None,
    sector: str | None = None,
    group: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Rank catalog rows for ``query`` after filters; returns (page, total).

    Exact ticker/name > ticker prefix > name starts with > name word-prefix >
    substring; ties go to S&P 500 members, tradable names, then shorter tickers. Empty query browses
    alphabetically. ponytail: linear scan -- ~10ms over the ~14k-row catalog;
    an index is only worth it if the catalog grows 10x.
    """
    q = query.strip().lower()
    qk = _key(q).lower() if q else ""
    on_list = {entry_key(s) for s in current_symbols()}

    hits: list[tuple[Any, ...]] = []
    for key, name, row in _index:
        if asset_class and row["asset_class"] != asset_class:
            continue
        if exchange and row["exchange"] != exchange:
            continue
        if sector and row["sector"] != sector:
            continue
        if group == "sp500" and not row["sp500"]:
            continue
        if group == "etf" and not row["etf"]:
            continue
        if group == "crypto" and row["asset_class"] != "crypto":
            continue
        if not q:
            hits.append((not row["tradable"], key, row))
            continue
        # Exact: the ticker, a coin's base ("btc" -> BTC-USD), or the whole name ("bitcoin").
        if key in (qk, qk + "-usd") or name == " " + q:
            score = 0
        elif key.startswith(qk):
            score = 1
        elif name.startswith(" " + q):
            score = 2
        elif " " + q in name:
            score = 3
        elif q in name or qk in key:
            score = 4
        else:
            continue
        hits.append((score, not row["sp500"], not row["tradable"], len(key), key, row))

    hits.sort(key=lambda h: h[:-1])
    page = [
        {**h[-1], "on_watchlist": _key(h[-1]["ticker"]) in on_list}
        for h in hits[offset:offset + limit]
    ]
    return page, len(hits)


def categories() -> dict[str, Any]:
    """Curated groups, sectors and venues with counts, for browsing."""
    counts = {
        "sp500": sum(r["sp500"] for r in _catalog),
        "etf": sum(r["etf"] for r in _catalog),
        "crypto": sum(r["asset_class"] == "crypto" for r in _catalog),
    }
    sectors = Counter(r["sector"] for r in _catalog if r["sector"])
    exchanges = Counter(r["exchange"] for r in _catalog)
    return {
        "groups": [{"id": k, "label": v, "count": counts[k]} for k, v in GROUPS.items()],
        "sectors": [{"name": k, "count": v} for k, v in sorted(sectors.items())],
        "exchanges": [{"name": k, "count": v} for k, v in exchanges.most_common()],
        "markets": MARKETS,
    }


def lookup(symbol: str) -> dict[str, Any] | None:
    """Catalog row for a symbol in any accepted spelling, tradable or not."""
    s = symbol.strip().upper()
    return _by_symbol.get(s) or _by_key.get(entry_key(s))


def resolve(token: str) -> tuple[dict[str, Any] | None, str | None]:
    """Typed symbol -> catalog row. Accepts bare (``AAPL``), suffixed
    (``AAPL.NASDAQ``), share class (``BRK.B``) and crypto (``BTC-USD``/``BTC/USD``).
    A bare ticker is the stock: ``BTC`` is Grayscale's mini trust, not bitcoin."""
    t = token.strip().upper()
    if not t:
        return None, "empty symbol"
    base, _, suffix = t.rpartition(".")
    if base and suffix in ("NSE", "BSE"):
        return None, INDIA_NOTE
    row = lookup(t)
    if row is None:
        return None, "not in the symbol catalog -- search by company name"
    if not row["tradable"]:
        return None, f"{row['ticker']} is listed but not tradable on Alpaca"
    return row, None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def on_change(name: str, callback: Callable[[list[str], list[str]], Any]) -> None:
    """Call ``callback(added, removed)`` after every change. Re-registering a
    name replaces it, so an engine restart doesn't stack stale listeners."""
    _listeners[name] = callback


def _current_lists() -> dict[str, list[str]]:
    return {key: _split(getattr(settings, attr)) for key, attr in _LISTS.items()}


def _persist(lists: dict[str, list[str]]) -> None:
    """Write changed lists through the REPL's .env writer and the live settings."""
    from app.tui.settings_panel import _write_env_key

    for key, symbols in lists.items():
        attr = _LISTS[key]
        if symbols != _split(getattr(settings, attr)):
            value = ",".join(symbols)
            _write_env_key(str(_ENV_PATH), key, value)
            setattr(settings, attr, value)


async def notify(added: list[str], removed: list[str]) -> None:
    """Tell feeds, agents and the GUI the list changed."""
    for name, callback in list(_listeners.items()):
        try:
            result = callback(added, removed)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # one broken consumer must not block the rest
            logger.warning("watchlist_listener_failed", listener=name, error=str(exc))

    # The GUI hears about terminal-side changes (and vice versa) via the bus.
    with contextlib.suppress(Exception):
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        await get_bus().publish(AgentMessage(
            sender_id="watchlist",
            channel="horizon.watchlist.updated",
            message_type=MessageType.SETTINGS_UPDATED,
            payload={"watchlist": len(current_symbols()), "added": added, "removed": removed},
        ))


async def add(tokens: list[str]) -> dict[str, Any]:
    """Validate against the catalog and append. No size cap."""
    await load_catalog()
    tokens = [t for t in dict.fromkeys(t.strip() for t in tokens) if t]
    if not _catalog:
        reason = _meta["error"] or "symbol catalog unavailable"
        return {"added": [], "already": [], "count": len(current_symbols()),
                "rejected": [{"symbol": t, "reason": reason} for t in tokens]}

    added: list[str] = []
    already: list[str] = []
    rejected: list[dict[str, str]] = []
    async with _write_lock:
        lists = _current_lists()
        on_list = {entry_key(s) for syms in lists.values() for s in syms}
        for token in tokens:
            row, error = resolve(token)
            if row is None:
                rejected.append({"symbol": token, "reason": error or "invalid"})
                continue
            key = _key(row["ticker"])
            if key in on_list:
                already.append(row["symbol"])
                continue
            lists[_LIST_FOR[row["asset_class"]]].append(row["symbol"])
            on_list.add(key)
            added.append(row["symbol"])
        if added:
            _persist(lists)

    if added:
        await notify(added, [])
    return {"added": added, "already": already, "rejected": rejected,
            "count": len(current_symbols())}


async def remove(tokens: list[str]) -> dict[str, Any]:
    """Drop entries matching each token (any suffix). Works without the catalog."""
    removed: list[str] = []
    missing: list[str] = []
    async with _write_lock:
        lists = _current_lists()
        for token in dict.fromkeys(t.strip() for t in tokens if t.strip()):
            key = entry_key(token)
            hit = False
            for list_key, symbols in lists.items():
                gone = [s for s in symbols if entry_key(s) == key]
                if gone:
                    lists[list_key] = [s for s in symbols if entry_key(s) != key]
                    removed += gone
                    hit = True
            if not hit:
                missing.append(token)
        if removed:
            _persist(lists)

    if removed:
        await notify([], removed)
    return {"removed": removed, "missing": missing, "count": len(current_symbols())}


# ---------------------------------------------------------------------------
# Quotes + context for both front ends
# ---------------------------------------------------------------------------

async def quotes(symbols: list[str]) -> dict[str, dict[str, float]]:
    """``{symbol: {price, prev_close, change_pct}}``: one batched Alpaca snapshot
    call, falling back to the prices the ingestion worker left in KV."""
    from app.core.kv_store import get_kv_store
    from app.data_layer import alpaca_quotes

    snaps = await alpaca_quotes.get_snapshots(symbols)
    kv = get_kv_store()
    out: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        quote = snaps.get(symbol)
        if quote is None:
            try:
                price = float(await kv.get(f"horizon:price:{symbol}") or 0)
                prev = float(await kv.get(f"horizon:price:prev_close:{symbol}") or 0)
            except (TypeError, ValueError):
                price = prev = 0.0
            quote = {"price": price, "prev_close": prev}
        price, prev = quote["price"], quote["prev_close"]
        out[symbol] = {
            "price": price,
            "prev_close": prev,
            "change_pct": ((price - prev) / prev * 100) if prev and price else 0.0,
        }
    return out


def strategy_note() -> str:
    if settings.universe_source == "config":
        return ("UNIVERSE_SOURCE=config: the strategy trades this list, so changes "
                "here change what it trades.")
    return ("Watchlist = what you monitor and can trade manually. The strategy picks "
            "from the S&P 500 on its own -- this list does not change what it trades.")


def stream_info() -> dict[str, Any]:
    """Live-tick coverage, so a plan limit is visible instead of silent."""
    from app.data_layer.alpaca_feed import FREE_PLAN_STREAM_LIMIT, stream_status

    us = len(_split(settings.us_symbols))
    return {
        **stream_status,
        "us_symbols": us,
        "free_plan_limit": FREE_PLAN_STREAM_LIMIT,
        "poll_seconds": 30,
    }
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 75E9E7E16A11 - verify with scripts/authorship.py verify
