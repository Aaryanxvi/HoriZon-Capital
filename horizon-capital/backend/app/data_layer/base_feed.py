"""Abstract base class for all market-data feeds."""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable

from app.data_layer.data_normalizer import NormalizedOHLCV, NormalizedTick

TickCallback = Callable[[NormalizedTick], Awaitable[None]]
OHLCVCallback = Callable[[NormalizedOHLCV], Awaitable[None]]


class BaseFeed(abc.ABC):
    """Every feed must implement connect/disconnect/subscribe/start.

    Concrete helpers ``on_tick`` and ``on_ohlcv`` register callbacks that the
    feed fires whenever new data arrives.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._is_connected: bool = False
        self._tick_callbacks: list[TickCallback] = []
        self._ohlcv_callbacks: list[OHLCVCallback] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------
    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Gracefully tear down the connection."""

    @abc.abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to live updates for *symbols*."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin streaming / polling loop (runs until ``disconnect``)."""

    # ------------------------------------------------------------------
    # Callback registration (concrete)
    # ------------------------------------------------------------------
    def on_tick(self, callback: TickCallback) -> None:
        """Register a coroutine to be called on every incoming tick."""
        self._tick_callbacks.append(callback)

    def on_ohlcv(self, callback: OHLCVCallback) -> None:
        """Register a coroutine to be called on every incoming OHLCV bar."""
        self._ohlcv_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Internal helpers – subclasses call these to dispatch data
    # ------------------------------------------------------------------
    async def _emit_tick(self, tick: NormalizedTick) -> None:
        for cb in self._tick_callbacks:
            await cb(tick)

    async def _emit_ohlcv(self, bar: NormalizedOHLCV) -> None:
        for cb in self._ohlcv_callbacks:
            await cb(bar)
