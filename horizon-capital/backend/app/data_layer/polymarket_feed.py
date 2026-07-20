"""Polymarket Gamma/CLOB REST feed -- polls YES-outcome mid prices every 60 seconds."""

from __future__ import annotations

import json
import re
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


def pm_symbol(slug: str) -> str:
    """Derive the internal symbol for a Polymarket slug, e.g.
    ``Fed-Cut-Sept! 2026`` -> ``PM-fed-cut-sept-2026.POLY``."""
    sanitized = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    sanitized = sanitized[:40]
    return f"PM-{sanitized}.POLY"


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
        self._poll_count: int = 0

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        from app.config import settings

        slugs = [s.strip() for s in settings.polymarket_markets.split(",") if s.strip()]
        if not slugs:
            self._is_connected = False
            logger.info("polymarket_disabled")
            return

        async with httpx.AsyncClient(timeout=15.0) as client:
            for slug in slugs:
                await self._resolve_market(client, slug)

        self._is_connected = bool(self._meta)

    async def disconnect(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._is_connected = False
        logger.info("polymarket_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
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
        outcomes = market.get("outcomes", [])
        token_ids = market.get("clobTokenIds", [])
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)

        yes_idx = next(
            (i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), 0
        )
        if yes_idx >= len(token_ids):
            logger.warning("polymarket_market_unavailable", slug=slug)
            return

        symbol = pm_symbol(slug)
        meta = {
            "token_id": token_ids[yes_idx],
            "condition_id": market.get("conditionId", ""),
            "slug": slug,
            "question": market.get("question", ""),
            "end_date": market.get("endDate", ""),
        }
        self._meta[symbol] = meta
        await self._write_meta_kv(symbol, meta)
        await self._write_volume_kv(symbol, market)

    async def _write_meta_kv(self, symbol: str, meta: dict) -> None:
        from app.core.kv_store import get_kv_store

        try:
            kv = get_kv_store()
            await kv.set(f"horizon:pm:meta:{symbol}", json.dumps(meta))
        except Exception:
            logger.warning("polymarket_meta_write_error", symbol=symbol)

    async def _write_volume_kv(self, symbol: str, market: dict) -> None:
        from app.core.kv_store import get_kv_store

        try:
            kv = get_kv_store()
            volume = float(market.get("volume24hr") or 0)
            await kv.set(f"horizon:volume:{symbol}", str(volume))
        except Exception:
            logger.warning("polymarket_volume_write_error", symbol=symbol)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        import asyncio

        logger.info("polymarket_feed.poll_loop_started", interval=self._poll_interval)
        async with httpx.AsyncClient(timeout=15.0) as client:
            while self._running:
                try:
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
                await self._write_volume_kv(symbol, markets[0])
        except Exception:
            logger.exception("polymarket_poll_error", symbol=symbol)
