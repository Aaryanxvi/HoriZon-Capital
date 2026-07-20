"""DataIngestionWorker writes the USD/INR forex rate to KV."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.agents.front_office.portfolio.currency import FOREX_KEY
from app.core.kv_store import get_kv_store
from app.workers.data_ingestion_worker import DataIngestionWorker


@pytest.mark.asyncio
async def test_forex_poll_writes_kv():
    """One fetch cycle writes the latest USDINR close to KV."""
    worker = DataIngestionWorker()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame({"Close": [88.5]})

    with patch("yfinance.Ticker", return_value=mock_ticker):
        await worker._fetch_forex_once()

    assert await get_kv_store().get(FOREX_KEY) == "88.5"


@pytest.mark.asyncio
async def test_forex_poll_bad_data_no_write():
    """Empty history means no KV write and no exception."""
    worker = DataIngestionWorker()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    kv = get_kv_store()
    await kv.delete(FOREX_KEY)  # ensure a clean baseline

    with patch("yfinance.Ticker", return_value=mock_ticker):
        await worker._fetch_forex_once()

    assert await kv.get(FOREX_KEY) is None
