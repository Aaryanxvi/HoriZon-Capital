# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-664E740F4717
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Alpaca Markets feed -- live WebSocket ticks with REST fallback."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedOHLCV, NormalizedTick

logger = get_logger(__name__)

# Market data is one host for paper and live accounts. The "sandbox" data hosts
# reject paper keys (REST 401, stream auth 402) -- they belong to Broker API.
_STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
_DATA_REST = "https://data.alpaca.markets"

_WS_MAX_RETRIES = 5          # attempts before permanently falling to REST
_WS_BACKOFF_BASE = 2         # seconds; doubles each retry (2, 4, 8, 16, 32)
_WS_BACKOFF_MAX = 60         # cap backoff at 60 seconds

# Alpaca's free (Basic) plan streams at most 30 symbols per connection, and a
# subscribe that would exceed it is rejected whole (error 405 "symbol limit
# exceeded" -- measured Oct 2026). Paid plans are unlimited, so ask for
# everything and trim to this only once the server refuses. Symbols past the
# limit still get prices from the ingestion worker's 30s snapshot poll.
FREE_PLAN_STREAM_LIMIT = 30
_REST_CHUNK = 500

# What the stream is actually delivering, for the watchlist screen. One feed
# per process, so module state is enough.
stream_status: dict[str, Any] = {"mode": "off", "streaming": 0, "requested": 0, "limit": None}


class AlpacaFeed(BaseFeed):
    """Live US-equity ticks from Alpaca via WebSocket, REST polling fallback."""

    def __init__(self) -> None:
        super().__init__(name="alpaca")
        self._symbols: list[str] = []
        self._ws: Any = None
        self._ws_task: asyncio.Task[None] | None = None
        self._rest_task: asyncio.Task[None] | None = None
        self._running = False
        self._use_websocket = True  # try WS first; fall back if it fails
        self._limit: int | None = None   # set once the server rejects a subscribe
        self._streaming: list[str] = []  # server-confirmed subscription

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def _stream_url(self) -> str:
        return _STREAM_URL

    @property
    def _rest_base(self) -> str:
        return _DATA_REST

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        }

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if not settings.alpaca_api_key:
            logger.warning("alpaca_feed.no_api_key -- feed disabled")
            return
        self._is_connected = True
        logger.info(
            "alpaca_feed.connect",
            paper=settings.alpaca_paper_mode,
        )

    async def disconnect(self) -> None:
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self._rest_task and not self._rest_task.done():
            self._rest_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._is_connected = False
        logger.info("alpaca_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        """Set the symbol list. On an open socket this re-syncs immediately, so a
        watchlist change takes effect without reconnecting."""
        self._symbols = [self._strip_exchange(s) for s in symbols]
        logger.info("alpaca_feed.subscribe", n=len(self._symbols))
        if self._ws is not None and self._use_websocket:
            try:
                await self._sync_subscription()
            except Exception as exc:  # socket mid-reconnect: the next connect syncs
                logger.warning("alpaca_feed.resubscribe_failed", error=str(exc))
        self._publish_status()

    def _wanted(self) -> list[str]:
        return self._symbols[: self._limit] if self._limit else list(self._symbols)

    async def _sync_subscription(self) -> None:
        """Diff wanted vs confirmed and send unsubscribe-then-subscribe, so the
        swap never momentarily exceeds the plan's symbol limit."""
        want = self._wanted()
        have = set(self._streaming)
        drop = [s for s in have if s not in want]
        add = [s for s in want if s not in have]
        if drop:
            await self._ws.send(json.dumps({"action": "unsubscribe", "trades": drop}))
        if add:
            await self._ws.send(json.dumps({"action": "subscribe", "trades": add}))

    def _publish_status(self) -> None:
        mode = "stream" if self._use_websocket else "rest"
        stream_status.update(
            mode=mode if self._is_connected else "off",
            streaming=len(self._streaming) if self._use_websocket else len(self._symbols),
            requested=len(self._symbols),
            limit=self._limit,
        )

    async def _handle_control(self, msg: dict[str, Any]) -> None:
        """Track the server's view of the subscription; trim on a limit error."""
        if msg.get("T") == "subscription":
            self._streaming = list(msg.get("trades") or [])
            self._publish_status()
        elif msg.get("T") == "error" and msg.get("code") == 405 and self._limit is None:
            self._limit = FREE_PLAN_STREAM_LIMIT
            logger.warning(
                "alpaca_feed.symbol_limit -- streaming the first symbols only",
                limit=self._limit,
                requested=len(self._symbols),
            )
            await self._sync_subscription()
        elif msg.get("T") == "error":
            logger.warning("alpaca_feed.ws_error_message", msg=msg)

    async def start(self) -> None:
        if not self._is_connected:
            return
        self._running = True
        if self._use_websocket:
            self._ws_task = asyncio.create_task(self._ws_loop())
        else:
            self._rest_task = asyncio.create_task(self._rest_poll_loop())

    # ------------------------------------------------------------------
    # WebSocket streaming
    # ------------------------------------------------------------------
    async def _ws_loop(self) -> None:
        try:
            import websockets  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("alpaca_feed.websockets_not_installed -- falling back to REST")
            self._use_websocket = False
            self._rest_task = asyncio.create_task(self._rest_poll_loop())
            return

        retry = 0
        while self._running:
            try:
                async with websockets.connect(self._stream_url) as ws:
                    self._ws = ws

                    # Server greets first ("connected"); the auth reply is the NEXT
                    # frame. Reading only one frame logged the greeting as the auth
                    # result, so a rejected key looked fine and reconnect-looped.
                    await ws.recv()
                    auth_msg = {
                        "action": "auth",
                        "key": settings.alpaca_api_key,
                        "secret": settings.alpaca_api_secret,
                    }
                    await ws.send(json.dumps(auth_msg))
                    resp = json.loads(await ws.recv())
                    logger.info("alpaca_feed.ws_auth_response", resp=resp)
                    replies = resp if isinstance(resp, list) else [resp]
                    if any(m.get("T") == "error" for m in replies):
                        raise ConnectionError(f"alpaca stream auth rejected: {resp}")

                    # Subscribe to trades (a fresh connection has no subscription)
                    self._streaming = []
                    await self._sync_subscription()
                    logger.info("alpaca_feed.ws_subscribed", n=len(self._wanted()))

                    # Connection succeeded -- reset retry counter
                    retry = 0

                    async for raw in ws:
                        if not self._running:
                            break
                        messages = json.loads(raw)
                        if not isinstance(messages, list):
                            messages = [messages]
                        for msg in messages:
                            if msg.get("T") == "t":  # trade message
                                tick = self._parse_ws_trade(msg)
                                if tick:
                                    await self._emit_tick(tick)
                            else:
                                await self._handle_control(msg)

            except asyncio.CancelledError:
                break
            except Exception:
                if retry >= _WS_MAX_RETRIES:
                    logger.exception(
                        "alpaca_feed.ws_max_retries_exhausted -- falling back to REST",
                        retries=retry,
                    )
                    self._use_websocket = False
                    self._rest_task = asyncio.create_task(self._rest_poll_loop())
                    break

                delay = min(_WS_BACKOFF_BASE ** (retry + 1), _WS_BACKOFF_MAX)
                logger.warning(
                    "alpaca_feed.ws_error -- retrying",
                    retry=retry + 1,
                    max_retries=_WS_MAX_RETRIES,
                    backoff_seconds=delay,
                )
                retry += 1
                await asyncio.sleep(delay)

    def _parse_ws_trade(self, msg: dict[str, Any]) -> NormalizedTick | None:
        try:
            return NormalizedTick(
                symbol=msg["S"],
                exchange="NASDAQ",
                timestamp=datetime.fromisoformat(msg["t"].replace("Z", "+00:00")),
                last_price=float(msg["p"]),
                volume=int(msg["s"]),
                currency="USD",
            )
        except (KeyError, ValueError):
            logger.warning("alpaca_feed.parse_error", msg=msg)
            return None

    # ------------------------------------------------------------------
    # REST fallback polling
    # ------------------------------------------------------------------
    async def _rest_poll_loop(self) -> None:
        """Poll latest trades every 10 seconds -- one request per 500 symbols,
        not one per symbol, so the fallback scales with the watchlist."""
        self._publish_status()
        async with httpx.AsyncClient(headers=self._auth_headers, timeout=15) as client:
            while self._running:
                symbols = list(self._symbols)
                for i in range(0, len(symbols), _REST_CHUNK):
                    try:
                        for tick in await self._rest_fetch_latest_trades(
                            client, symbols[i:i + _REST_CHUNK]
                        ):
                            await self._emit_tick(tick)
                    except Exception:
                        logger.exception("alpaca_feed.rest_poll_error", n=len(symbols))
                await asyncio.sleep(10)

    async def _rest_fetch_latest_trades(
        self, client: httpx.AsyncClient, symbols: list[str]
    ) -> list[NormalizedTick]:
        url = f"{self._rest_base}/v2/stocks/trades/latest"
        resp = await client.get(url, params={"symbols": ",".join(symbols)})
        if resp.status_code != 200:
            logger.warning("alpaca_feed.rest_error", status=resp.status_code, n=len(symbols))
            return []

        ticks: list[NormalizedTick] = []
        for symbol, trade in (resp.json().get("trades") or {}).items():
            ticks.append(NormalizedTick(
                symbol=symbol,
                exchange="NASDAQ",
                timestamp=datetime.fromisoformat(
                    trade["t"].replace("Z", "+00:00")
                ) if "t" in trade else datetime.now(UTC),
                last_price=float(trade["p"]),
                volume=int(trade.get("s", 0)),
                currency="USD",
            ))
        return ticks

    # ------------------------------------------------------------------
    # OHLCV helper (REST)
    # ------------------------------------------------------------------
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> list[NormalizedOHLCV]:
        """Fetch OHLCV bars from the Alpaca data API."""
        clean_symbol = self._strip_exchange(symbol)
        params: dict[str, Any] = {"timeframe": timeframe, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        async with httpx.AsyncClient(headers=self._auth_headers, timeout=15) as client:
            url = f"{self._rest_base}/v2/stocks/{clean_symbol}/bars"
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning("alpaca_feed.ohlcv_error", status=resp.status_code)
                return []
            data = resp.json()

        bars: list[NormalizedOHLCV] = []
        for bar in data.get("bars", []):
            bars.append(
                NormalizedOHLCV(
                    symbol=clean_symbol,
                    exchange="NASDAQ",
                    timestamp=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                    timeframe=timeframe,
                    open=float(bar["o"]),
                    high=float(bar["h"]),
                    low=float(bar["l"]),
                    close=float(bar["c"]),
                    volume=int(bar["v"]),
                    currency="USD",
                )
            )
        return bars

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_exchange(symbol: str) -> str:
        """Remove trailing exchange tag (``AAPL.NASDAQ`` -> ``AAPL``).

        Share classes are stored yfinance-style (``BRK-B.NYSE``); Alpaca wants
        ``BRK.B``.
        """
        return (symbol.rsplit(".", 1)[0] if "." in symbol else symbol).replace("-", ".")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 664E740F4717 - verify with scripts/authorship.py verify
