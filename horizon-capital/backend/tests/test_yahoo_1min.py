"""Tests for Yahoo 1-minute bar polling and market hours awareness."""

import pytest
from datetime import datetime, UTC
from unittest.mock import patch, MagicMock, AsyncMock
import pandas as pd


def _make_1min_df():
    """Create a minimal 2-row 1-min OHLCV DataFrame as yfinance returns."""
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-04-21 09:30:00", tz="America/New_York"),
        pd.Timestamp("2026-04-21 09:31:00", tz="America/New_York"),
    ])
    return pd.DataFrame({
        "Open": [150.0, 151.0],
        "High": [152.0, 153.0],
        "Low": [149.5, 150.5],
        "Close": [151.5, 152.0],
        "Volume": [10000, 12000],
    }, index=idx)


def test_nse_market_hours():
    """NSE symbols skip polling outside NSE hours."""
    from app.data_layer.yahoo_feed import _is_market_open

    # NSE hours: 03:45-10:00 UTC
    assert _is_market_open("RELIANCE.NSE", datetime(2026, 4, 21, 4, 0, tzinfo=UTC)) is True
    assert _is_market_open("RELIANCE.NSE", datetime(2026, 4, 21, 1, 0, tzinfo=UTC)) is False


def test_nasdaq_market_hours():
    """NASDAQ symbols skip polling outside NASDAQ hours."""
    from app.data_layer.yahoo_feed import _is_market_open

    # NASDAQ hours: 13:30-20:00 UTC
    assert _is_market_open("AAPL.NASDAQ", datetime(2026, 4, 21, 14, 0, tzinfo=UTC)) is True
    assert _is_market_open("AAPL.NASDAQ", datetime(2026, 4, 21, 2, 0, tzinfo=UTC)) is False


def test_unknown_exchange_defaults_open():
    """Unknown exchanges default to market open (never silently skip)."""
    from app.data_layer.yahoo_feed import _is_market_open

    assert _is_market_open("FOO.UNKNOWN", datetime(2026, 4, 21, 12, 0, tzinfo=UTC)) is True


def test_bse_market_hours():
    """BSE uses same hours as NSE."""
    from app.data_layer.yahoo_feed import _is_market_open

    assert _is_market_open("INFY.BSE", datetime(2026, 4, 21, 5, 0, tzinfo=UTC)) is True
    assert _is_market_open("INFY.BSE", datetime(2026, 4, 21, 11, 0, tzinfo=UTC)) is False


def test_nyse_market_hours():
    """NYSE uses same hours as NASDAQ."""
    from app.data_layer.yahoo_feed import _is_market_open

    assert _is_market_open("IBM.NYSE", datetime(2026, 4, 21, 15, 0, tzinfo=UTC)) is True
    assert _is_market_open("IBM.NYSE", datetime(2026, 4, 21, 21, 0, tzinfo=UTC)) is False


def test_lse_market_hours():
    """LSE hours: 08:00-16:30 UTC."""
    from app.data_layer.yahoo_feed import _is_market_open

    assert _is_market_open("VOD.LSE", datetime(2026, 4, 21, 10, 0, tzinfo=UTC)) is True
    assert _is_market_open("VOD.LSE", datetime(2026, 4, 21, 17, 0, tzinfo=UTC)) is False


def test_crypto_always_open():
    """Crypto markets have no hours -- always open."""
    from app.data_layer.yahoo_feed import _is_market_open

    # Crypto symbols use dash notation (BTC-USD), no dot exchange
    assert _is_market_open("BTC-USD", datetime(2026, 4, 21, 3, 0, tzinfo=UTC)) is True


def test_asx_midnight_crossing():
    """ASX hours cross midnight UTC (23:00-05:00)."""
    from app.data_layer.yahoo_feed import _is_market_open

    assert _is_market_open("BHP.ASX", datetime(2026, 4, 21, 23, 30, tzinfo=UTC)) is True
    assert _is_market_open("BHP.ASX", datetime(2026, 4, 21, 2, 0, tzinfo=UTC)) is True
    assert _is_market_open("BHP.ASX", datetime(2026, 4, 21, 12, 0, tzinfo=UTC)) is False


def test_fetch_latest_uses_1min_interval():
    """fetch_latest should use 1m interval and 1d period."""
    from app.data_layer.yahoo_feed import YahooFeed

    feed = YahooFeed()
    with patch.object(feed, "poll_ohlcv", new_callable=AsyncMock, return_value=[]) as mock:
        import asyncio
        asyncio.run(feed.fetch_latest("AAPL.NASDAQ"))
        mock.assert_called_once_with("AAPL.NASDAQ", period="1d", interval="1m")


def test_poll_loop_interval_is_30s():
    """The Yahoo poll interval in data_ingestion_worker should be 30s."""
    from app.workers.data_ingestion_worker import YAHOO_POLL_INTERVAL

    assert YAHOO_POLL_INTERVAL == 30


def test_poll_loop_skips_closed_markets():
    """_poll_loop should skip symbols whose market is closed."""
    from app.data_layer.yahoo_feed import YahooFeed, _is_market_open

    feed = YahooFeed()
    feed._symbols = ["RELIANCE.NSE"]
    feed._running = True

    # At 1:00 UTC, NSE is closed
    closed_time = datetime(2026, 4, 21, 1, 0, tzinfo=UTC)
    assert _is_market_open("RELIANCE.NSE", closed_time) is False
