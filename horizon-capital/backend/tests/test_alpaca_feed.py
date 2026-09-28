# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-925A3A880A6B
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Tests for AlpacaFeed WebSocket reconnect behaviour."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_alpaca_feed_disabled_without_key():
    """AlpacaFeed.connect() does nothing when no API key is set."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    with patch("app.data_layer.alpaca_feed.settings") as mock_settings:
        mock_settings.alpaca_api_key = ""
        mock_settings.alpaca_paper_mode = True
        await feed.connect()

    assert not feed._is_connected


@pytest.mark.asyncio
async def test_alpaca_feed_connect_sets_connected():
    """AlpacaFeed.connect() marks feed as connected when key is present."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    with patch("app.data_layer.alpaca_feed.settings") as mock_settings:
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True
        await feed.connect()

    assert feed._is_connected


@pytest.mark.asyncio
async def test_ws_loop_retries_before_falling_to_rest():
    """_ws_loop retries up to _WS_MAX_RETRIES before falling to REST."""
    from app.data_layer.alpaca_feed import AlpacaFeed, _WS_MAX_RETRIES

    feed = AlpacaFeed()
    feed._running = True
    feed._is_connected = True
    feed._symbols = ["AAPL"]

    call_count = 0

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("ws refused")
        yield  # noqa: unreachable — needed to make this a generator

    fake_ws_module = MagicMock()
    fake_ws_module.connect = fake_connect

    with (
        patch("app.data_layer.alpaca_feed.settings") as mock_settings,
        patch.dict("sys.modules", {"websockets": fake_ws_module}),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True

        await feed._ws_loop()

    # Should have tried _WS_MAX_RETRIES + 1 times (initial + retries)
    assert call_count == _WS_MAX_RETRIES + 1
    assert feed._use_websocket is False
    # Verify exponential backoff was used
    assert mock_sleep.call_count == _WS_MAX_RETRIES


@pytest.mark.asyncio
async def test_ws_loop_resets_retries_on_success():
    """Successful WS connection resets the retry counter."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    feed._running = True
    feed._is_connected = True
    feed._symbols = ["AAPL"]

    connect_count = 0

    class FakeWs:
        async def send(self, data):
            pass

        async def recv(self):
            return '{"T": "success"}'

        def __aiter__(self):
            return self

        async def __anext__(self):
            nonlocal connect_count
            # Stop after second connection attempt
            if connect_count >= 2:
                feed._running = False
            raise ConnectionError("dropped mid-stream")

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        yield FakeWs()

    fake_ws_module = MagicMock()
    fake_ws_module.connect = fake_connect

    with (
        patch("app.data_layer.alpaca_feed.settings") as mock_settings,
        patch.dict("sys.modules", {"websockets": fake_ws_module}),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True

        await feed._ws_loop()

    # Each successful connect resets retry counter. The __anext__ raises
    # ConnectionError which bumps retry, but on reconnect the retry resets.
    # Eventually _running=False exits the outer loop.
    assert feed._use_websocket is True


@pytest.mark.asyncio
async def test_ws_loop_backoff_capped():
    """Backoff delay should be capped at _WS_BACKOFF_MAX."""
    from app.data_layer.alpaca_feed import (
        AlpacaFeed,
        _WS_BACKOFF_BASE,
        _WS_BACKOFF_MAX,
    )

    feed = AlpacaFeed()
    feed._running = True
    feed._is_connected = True
    feed._symbols = ["AAPL"]

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        raise ConnectionError("ws refused")
        yield  # noqa

    fake_ws_module = MagicMock()
    fake_ws_module.connect = fake_connect

    with (
        patch("app.data_layer.alpaca_feed.settings") as mock_settings,
        patch.dict("sys.modules", {"websockets": fake_ws_module}),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True

        await feed._ws_loop()

    # Every sleep call's delay should be <= _WS_BACKOFF_MAX
    for call in mock_sleep.call_args_list:
        delay = call[0][0]
        assert delay <= _WS_BACKOFF_MAX
        assert delay >= _WS_BACKOFF_BASE


@pytest.mark.asyncio
async def test_ws_loop_cancelled_error_breaks_cleanly():
    """CancelledError should break out of _ws_loop without falling to REST."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    feed._running = True
    feed._is_connected = True
    feed._symbols = ["AAPL"]

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        raise asyncio.CancelledError()
        yield  # noqa

    fake_ws_module = MagicMock()
    fake_ws_module.connect = fake_connect

    with (
        patch("app.data_layer.alpaca_feed.settings") as mock_settings,
        patch.dict("sys.modules", {"websockets": fake_ws_module}),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_settings.alpaca_api_key = "test-key"
        mock_settings.alpaca_api_secret = "test-secret"
        mock_settings.alpaca_paper_mode = True

        await feed._ws_loop()

    # Should NOT have fallen back to REST
    assert feed._use_websocket is True


@pytest.mark.asyncio
async def test_ws_loop_no_websockets_module():
    """When websockets is not installed, falls to REST immediately."""
    from app.data_layer.alpaca_feed import AlpacaFeed

    feed = AlpacaFeed()
    feed._running = True
    feed._is_connected = True
    feed._symbols = ["AAPL"]

    import sys
    saved = sys.modules.get("websockets")
    sys.modules["websockets"] = None  # type: ignore

    try:
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fail_import(name, *args, **kwargs):
            if name == "websockets":
                raise ImportError("no websockets")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            await feed._ws_loop()

        assert feed._use_websocket is False
    finally:
        if saved is not None:
            sys.modules["websockets"] = saved
        elif "websockets" in sys.modules:
            del sys.modules["websockets"]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 925A3A880A6B - verify with scripts/authorship.py verify
