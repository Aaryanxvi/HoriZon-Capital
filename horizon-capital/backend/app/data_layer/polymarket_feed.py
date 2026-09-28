# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D4995A2F08EC
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Polymarket Gamma/CLOB REST feed -- polls YES-outcome mid prices every 60 seconds.

Markets come from two places: the hand-typed ``POLYMARKET_MARKETS`` slug list and
(when ``POLYMARKET_DISCOVERY_ENABLED``) an hourly Gamma sweep of the most-traded
open markets. ``active_slugs()`` is the union both the feed and the strategy
agent read, so a discovered market becomes tradable without an .env edit.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedTick

logger = get_logger(__name__)

_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
_CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"
_VOLUME_REFRESH_SECONDS = 3600  # re-fetch 24h volume at most once per hour
_DISCOVERY_TTL = 3600  # re-sweep Gamma for new markets at most once per hour
# Discovery price band, deliberately wider than the sleeve's own 0.10-0.90 tail
# filter so a market can drift into tradable range instead of being re-discovered
# from scratch. Below 0.05 the whole 24h volume can be noise against a 3-cent
# quote, and the sleeve would never take it anyway.
_DISCOVERY_MID_LO = 0.05
_DISCOVERY_MID_HI = 0.95

# Discovery state, shared by the feed and the strategy agent (both need the same
# slug list, and the meta the sweep already paid for).
_discovered_slugs: list[str] = []
_discovered_meta: dict[str, dict] = {}
_discovered_at: float = 0.0


def pm_symbol(slug: str) -> str:
    """Derive the internal symbol for a Polymarket slug, e.g.
    ``Fed-Cut-Sept! 2026`` -> ``PM-fed-cut-sept-2026.POLY``."""
    sanitized = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    sanitized = sanitized[:40]
    return f"PM-{sanitized}.POLY"


def configured_slugs() -> list[str]:
    """Slugs explicitly listed in POLYMARKET_MARKETS."""
    from app.config import settings

    return [s.strip() for s in settings.polymarket_markets.split(",") if s.strip()]


def discovered_slugs() -> list[str]:
    """Slugs found by the last Gamma sweep (empty until one runs)."""
    return list(_discovered_slugs)


def active_slugs() -> list[str]:
    """Configured slugs first, then discovered ones. Deduped, order stable."""
    slugs = configured_slugs()
    seen = set(slugs)
    for slug in _discovered_slugs:
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def _meta_from_market(market: dict[str, Any], slug: str | None = None) -> dict | None:
    """Extract the YES-token metadata the feed and broker need, or None."""
    outcomes = market.get("outcomes", [])
    token_ids = market.get("clobTokenIds", [])
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)

    yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
    if yes_idx >= len(token_ids):
        return None

    return {
        "token_id": token_ids[yes_idx],
        "condition_id": market.get("conditionId", ""),
        "slug": slug or market.get("slug", ""),
        "question": market.get("question", ""),
        "end_date": market.get("endDate", ""),
    }


def _yes_price(market: dict[str, Any]) -> float | None:
    """YES-outcome price from a Gamma row, or None when it isn't quoted."""
    outcomes = market.get("outcomes", [])
    prices = market.get("outcomePrices", [])
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except ValueError:
            outcomes = []
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except ValueError:
            prices = []

    yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0)
    if yes_idx < len(prices):
        try:
            return float(prices[yes_idx])
        except (TypeError, ValueError):
            pass
    try:
        last = market.get("lastTradePrice")
        return float(last) if last is not None else None
    except (TypeError, ValueError):
        return None


def _days_to_resolution(end_date: str, now: datetime) -> float | None:
    """Days until ``endDate`` (ISO-8601), or None if unparseable/absent."""
    if not end_date:
        return None
    try:
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return (end - now).total_seconds() / 86400.0


def _filter_gamma_markets(
    markets: list[dict[str, Any]],
    *,
    min_volume: float,
    min_days: int,
    max_days: int,
    top_n: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Rank Gamma markets by 24h volume and keep the tradable, in-window ones.

    Rejects: closed/inactive, no CLOB order book, no YES token, thin 24h volume,
    markets resolving too soon (no momentum left) or too far out, near-resolved
    tails the sleeve would refuse anyway, and slug-truncation collisions (two
    slugs mapping to one ``.POLY`` symbol would double the position and clobber
    each other's token metadata — the larger market wins).
    """
    kept: list[tuple[float, dict[str, Any]]] = []
    for market in markets:
        if market.get("closed") or market.get("active") is False:
            continue
        # No order book -> nothing to buy even if the signal fires.
        if market.get("enableOrderBook") is False:
            continue
        if not market.get("slug"):
            continue
        try:
            volume = float(market.get("volume24hr") or 0.0)
        except (TypeError, ValueError):
            continue
        if volume < min_volume:
            continue
        days = _days_to_resolution(str(market.get("endDate") or ""), now)
        if days is None or not (min_days <= days <= max_days):
            continue
        mid = _yes_price(market)
        # Fail-open on an unquoted market: the sleeve's own tail filter still
        # applies before any order is sized.
        if mid is not None and not (_DISCOVERY_MID_LO <= mid <= _DISCOVERY_MID_HI):
            continue
        if _meta_from_market(market) is None:
            continue
        kept.append((volume, market))

    kept.sort(key=lambda pair: pair[0], reverse=True)

    out: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for _, market in kept:
        symbol = pm_symbol(str(market["slug"]))
        if symbol in seen_symbols:
            logger.warning(
                "polymarket_symbol_collision",
                symbol=symbol,
                dropped=market["slug"],
            )
            continue
        seen_symbols.add(symbol)
        out.append(market)
        if len(out) >= top_n:
            break
    return out


async def refresh_discovery(*, force: bool = False) -> list[str]:
    """Sweep Gamma for the most-traded open markets. Cached ``_DISCOVERY_TTL``.

    Writes each keeper's meta + 24h volume to KV (so ``pm_bars`` and the broker
    can resolve token ids without a second fetch) and returns the slug list.
    Fail-open: any error keeps the previous list.
    """
    global _discovered_slugs, _discovered_at

    from app.config import settings

    if not settings.polymarket_discovery_enabled:
        return []

    now_mono = time.monotonic()
    if not force and _discovered_slugs and now_mono - _discovered_at < _DISCOVERY_TTL:
        return list(_discovered_slugs)

    top_n = max(int(settings.polymarket_discovery_top_n), 0)
    if top_n == 0:
        return []
    # Over-fetch: the volume/date/order-book filters drop a large share.
    limit = min(top_n * 10, 200)
    params = {
        "closed": "false",
        "active": "true",
        "order": "volume24hr",
        "ascending": "false",
        "limit": str(limit),
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_GAMMA_URL, params=params)
        if resp.status_code != 200:
            logger.warning("polymarket_discovery_http_error", status=resp.status_code)
            return list(_discovered_slugs)
        markets = resp.json()
    except Exception as exc:
        logger.warning("polymarket_discovery_error", error=str(exc))
        return list(_discovered_slugs)

    if not isinstance(markets, list):
        logger.warning("polymarket_discovery_bad_payload")
        return list(_discovered_slugs)

    keepers = _filter_gamma_markets(
        markets,
        min_volume=settings.polymarket_discovery_min_volume_24h,
        min_days=settings.polymarket_discovery_min_days,
        max_days=settings.polymarket_discovery_max_days,
        top_n=top_n,
        now=datetime.now(UTC),
    )

    slugs: list[str] = []
    fresh_meta: dict[str, dict] = {}
    configured = set(configured_slugs())
    configured_symbols = {pm_symbol(s) for s in configured}
    for market in keepers:
        slug = str(market["slug"])
        meta = _meta_from_market(market, slug)
        if meta is None:
            continue
        symbol = pm_symbol(slug)
        # A hand-configured market owns its symbol — never let a discovered slug
        # that truncates to the same symbol overwrite its token metadata.
        if slug not in configured and symbol in configured_symbols:
            logger.warning("polymarket_symbol_collision", symbol=symbol, dropped=slug)
            continue
        fresh_meta[symbol] = meta
        await _write_meta_kv(symbol, meta)
        await _write_volume_kv(symbol, market)
        if slug not in configured:
            slugs.append(slug)

    # Replace, don't accumulate — a market that closed or fell out of the
    # ranking must stop being polled and stop producing signals.
    _discovered_meta.clear()
    _discovered_meta.update(fresh_meta)

    _discovered_slugs = slugs
    _discovered_at = now_mono
    logger.info(
        "polymarket_discovery_refreshed", scanned=len(markets), kept=len(slugs)
    )
    return list(slugs)


async def _write_meta_kv(symbol: str, meta: dict) -> None:
    from app.core.kv_store import get_kv_store

    try:
        kv = get_kv_store()
        await kv.set(f"horizon:pm:meta:{symbol}", json.dumps(meta))
    except Exception:
        logger.warning("polymarket_meta_write_error", symbol=symbol)


async def _write_volume_kv(symbol: str, market: dict) -> None:
    from app.core.kv_store import get_kv_store

    try:
        kv = get_kv_store()
        volume = float(market.get("volume24hr") or 0)
        await kv.set(f"horizon:volume:{symbol}", str(volume))
    except Exception:
        logger.warning("polymarket_volume_write_error", symbol=symbol)


class PolymarketFeed(BaseFeed):
    """Free Gamma/CLOB REST polling feed for Polymarket YES-outcome prices."""

    def __init__(self) -> None:
        super().__init__(name="polymarket")
        self._symbols: list[str] = []
        self._running = False
        self._task = None  # type: ignore[var-annotated]
        self._poll_interval: int = 60  # seconds
        # symbol -> {"token_id", "condition_id", "slug", "question", "end_date"}
        self._meta: dict[str, dict] = {}
        # Meta for hand-configured slugs only — kept apart so a discovery sweep
        # can drop markets that closed without dropping the configured ones.
        self._configured_meta: dict[str, dict] = {}
        self._poll_count: int = 0
        self._auto_symbols: bool = True

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        await refresh_discovery()

        if not active_slugs():
            self._is_connected = False
            logger.info("polymarket_disabled")
            return

        async with httpx.AsyncClient(timeout=15.0) as client:
            for slug in configured_slugs():
                await self._resolve_market(client, slug)

        self._merge_discovered()
        self._is_connected = bool(self._meta)

    async def disconnect(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._is_connected = False
        logger.info("polymarket_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        # No explicit list -> track whatever is active, including markets a later
        # discovery sweep turns up.
        self._auto_symbols = not symbols
        self._symbols = symbols or list(self._meta.keys())
        logger.info("polymarket_feed.subscribe", symbols=self._symbols)

    async def start(self) -> None:
        if not self._is_connected:
            return
        self._running = True
        import asyncio

        self._task = asyncio.create_task(self._poll_loop())

    # ------------------------------------------------------------------
    # Resolution (connect-time)
    # ------------------------------------------------------------------
    async def _resolve_market(self, client: httpx.AsyncClient, slug: str) -> None:
        try:
            resp = await client.get(_GAMMA_URL, params={"slug": slug})
        except Exception:
            logger.exception("polymarket_poll_error", slug=slug)
            return

        if resp.status_code != 200:
            logger.warning("polymarket_market_unavailable", slug=slug, status=resp.status_code)
            return

        markets: list[dict[str, Any]] = resp.json()
        if not markets or markets[0].get("closed"):
            logger.warning("polymarket_market_unavailable", slug=slug)
            return

        market = markets[0]
        meta = _meta_from_market(market, slug)
        if meta is None:
            logger.warning("polymarket_market_unavailable", slug=slug)
            return

        symbol = pm_symbol(slug)
        self._configured_meta[symbol] = meta
        self._meta[symbol] = meta
        await _write_meta_kv(symbol, meta)
        await _write_volume_kv(symbol, market)

    # ------------------------------------------------------------------
    # Discovery merge
    # ------------------------------------------------------------------
    def _merge_discovered(self) -> None:
        """Rebuild the polled set as configured + currently-discovered markets.

        Rebuilt rather than accumulated so a market that closed (or fell out of
        the volume ranking) stops being polled.
        """
        from app.config import settings

        if not settings.polymarket_discovery_enabled:
            return
        self._meta = {**self._configured_meta, **_discovered_meta}
        if self._auto_symbols:
            self._symbols = list(self._meta)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        import asyncio

        logger.info("polymarket_feed.poll_loop_started", interval=self._poll_interval)
        async with httpx.AsyncClient(timeout=15.0) as client:
            while self._running:
                try:
                    # TTL-guarded: a real sweep runs at most hourly.
                    await refresh_discovery()
                    self._merge_discovered()
                    await self._poll_once(client)
                except Exception:
                    logger.exception("polymarket_poll_error")
                await asyncio.sleep(self._poll_interval)

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        """Poll every subscribed symbol's midpoint once and emit a tick."""
        self._poll_count += 1
        # One Gamma re-fetch per market per hour, not per minute.
        refresh_every = max(_VOLUME_REFRESH_SECONDS // self._poll_interval, 1)
        refresh_volume = self._poll_count % refresh_every == 0

        for symbol in self._symbols:
            meta = self._meta.get(symbol)
            if meta is None:
                continue
            try:
                resp = await client.get(
                    _CLOB_MIDPOINT_URL, params={"token_id": meta["token_id"]}
                )
                if resp.status_code != 200:
                    logger.warning("polymarket_poll_error", symbol=symbol, status=resp.status_code)
                    continue
                mid = resp.json().get("mid")
                if mid is None:
                    continue
                price = float(mid)
            except Exception:
                logger.exception("polymarket_poll_error", symbol=symbol)
                continue

            tick = NormalizedTick(
                symbol=symbol,
                exchange="POLY",
                timestamp=datetime.now(UTC),
                last_price=price,
                currency="USD",
            )
            await self._emit_tick(tick)

            if refresh_volume:
                await self._refresh_volume(client, symbol, meta)

    async def _refresh_volume(
        self, client: httpx.AsyncClient, symbol: str, meta: dict
    ) -> None:
        try:
            resp = await client.get(_GAMMA_URL, params={"slug": meta["slug"]})
            if resp.status_code != 200:
                return
            markets = resp.json()
            if markets:
                await _write_volume_kv(symbol, markets[0])
        except Exception:
            logger.exception("polymarket_poll_error", symbol=symbol)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D4995A2F08EC - verify with scripts/authorship.py verify
