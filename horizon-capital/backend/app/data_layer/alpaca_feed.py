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

_STREAM_URL_PAPER = "wss://stream.data.sandbox.alpaca.markets/v2/iex"
_STREAM_URL_LIVE = "wss://stream.data.alpaca.markets/v2/iex"
_DATA_REST_PAPER = "https://data.sandbox.alpaca.markets"
_DATA_REST_LIVE = "https://data.alpaca.markets"

_WS_MAX_RETRIES = 5          # attempts before permanently falling to REST
_WS_BACKOFF_BASE = 2         # seconds; doubles each retry (2, 4, 8, 16, 32)
_WS_BACKOFF_MAX = 60         # cap backoff at 60 seconds


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

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def _stream_url(self) -> str:
        return _STREAM_URL_PAPER if settings.alpaca_paper_mode else _STREAM_URL_LIVE

    @property
    def _rest_base(self) -> str:
        return _DATA_REST_PAPER if settings.alpaca_paper_mode else _DATA_REST_LIVE

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
        self._symbols = [self._strip_exchange(s) for s in symbols]
        logger.info("alpaca_feed.subscribe", symbols=self._symbols)

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

                    # Authenticate
                    auth_msg = {
                        "action": "auth",
                        "key": settings.alpaca_api_key,
                        "secret": settings.alpaca_api_secret,
                    }
                    await ws.send(json.dumps(auth_msg))
                    resp = json.loads(await ws.recv())
                    logger.info("alpaca_feed.ws_auth_response", resp=resp)

                    # Subscribe to trades
                    sub_msg = {"action": "subscribe", "trades": self._symbols}
                    await ws.send(json.dumps(sub_msg))
                    logger.info("alpaca_feed.ws_subscribed", symbols=self._symbols)

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
        """Poll latest trade for each symbol every 10 seconds."""
        async with httpx.AsyncClient(headers=self._auth_headers, timeout=15) as client:
            while self._running:
                for symbol in self._symbols:
                    try:
                        tick = await self._rest_fetch_latest_trade(client, symbol)
                        if tick:
                            await self._emit_tick(tick)
                    except Exception:
                        logger.exception("alpaca_feed.rest_poll_error", symbol=symbol)
                await asyncio.sleep(10)

    async def _rest_fetch_latest_trade(
        self, client: httpx.AsyncClient, symbol: str
    ) -> NormalizedTick | None:
        url = f"{self._rest_base}/v2/stocks/{symbol}/trades/latest"
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("alpaca_feed.rest_error", status=resp.status_code, symbol=symbol)
            return None

        data = resp.json()
        trade = data.get("trade", {})
        return NormalizedTick(
            symbol=symbol,
            exchange="NASDAQ",
            timestamp=datetime.fromisoformat(
                trade["t"].replace("Z", "+00:00")
            ) if "t" in trade else datetime.now(UTC),
            last_price=float(trade["p"]),
            volume=int(trade.get("s", 0)),
            currency="USD",
        )

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
        """Remove trailing exchange tag (e.g. ``AAPL.NASDAQ`` -> ``AAPL``)."""
        return symbol.rsplit(".", 1)[0] if "." in symbol else symbol
