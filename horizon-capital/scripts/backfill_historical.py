#!/usr/bin/env python3
# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-E65197E694E0
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""backfill_historical.py -- Pull 5 years of daily OHLCV for all tracked symbols.

Usage:
    python scripts/backfill_historical.py

Requires:
    pip install yfinance sqlalchemy psycopg2-binary tqdm
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import yfinance as yf
from sqlalchemy import create_engine, text
from tqdm import tqdm

from app.config import settings

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

SYMBOLS_CONFIG: list[tuple[str, str, str]] = [
    # (canonical_symbol, yfinance_symbol, exchange)
    # NIFTY 50 top 5
    ("RELIANCE", "RELIANCE.NS", "NSE"),
    ("TCS", "TCS.NS", "NSE"),
    ("INFY", "INFY.NS", "NSE"),
    ("HDFCBANK", "HDFCBANK.NS", "NSE"),
    ("ICICIBANK", "ICICIBANK.NS", "NSE"),
    # S&P 500 top 5
    ("AAPL", "AAPL", "NASDAQ"),
    ("MSFT", "MSFT", "NASDAQ"),
    ("GOOGL", "GOOGL", "NASDAQ"),
    ("AMZN", "AMZN", "NASDAQ"),
    ("TSLA", "TSLA", "NASDAQ"),
    # Crypto
    ("BTC-USD", "BTC-USD", "CRYPTO"),
    ("ETH-USD", "ETH-USD", "CRYPTO"),
]

PERIOD = "5y"
INTERVAL = "1d"

INSERT_SQL = text("""
    INSERT INTO ohlcv
        (symbol, exchange, timestamp, timeframe, open, high, low, close, volume)
    VALUES
        (:symbol, :exchange, :timestamp, :timeframe, :open, :high, :low, :close, :volume)
    ON CONFLICT (symbol, exchange, timestamp, timeframe) DO NOTHING
""")


def main() -> None:
    engine = create_engine(settings.database_url_sync)

    total_inserted = 0

    print("=" * 60)
    print("  Horizon Capital -- Historical OHLCV Backfill")
    print("=" * 60)
    print(f"  Period  : {PERIOD}")
    print(f"  Interval: {INTERVAL}")
    print(f"  Symbols : {len(SYMBOLS_CONFIG)}")
    print()

    for canonical, yf_symbol, exchange in SYMBOLS_CONFIG:
        print(f"  Fetching {canonical} ({yf_symbol}) from Yahoo Finance ...")

        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period=PERIOD, interval=INTERVAL)
        except Exception as exc:
            print(f"    ERROR fetching {yf_symbol}: {exc}")
            continue

        if hist.empty:
            print(f"    WARNING: No data returned for {yf_symbol}")
            continue

        rows_inserted = 0
        with engine.begin() as conn:
            for ts, row in tqdm(
                hist.iterrows(),
                total=len(hist),
                desc=f"    {canonical}",
                unit="bars",
            ):
                try:
                    ts_utc = ts.to_pydatetime()
                    if ts_utc.tzinfo is None:
                        ts_utc = ts_utc.replace(tzinfo=timezone.utc)

                    conn.execute(
                        INSERT_SQL,
                        {
                            "symbol": canonical,
                            "exchange": exchange,
                            "timestamp": ts_utc,
                            "timeframe": "1d",
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "volume": int(row["Volume"]),
                        },
                    )
                    rows_inserted += 1
                except Exception as exc:
                    # Silently skip duplicates / errors per row
                    pass

        total_inserted += rows_inserted
        print(f"    Inserted {rows_inserted} bars for {canonical}")

    engine.dispose()
    print()
    print(f"  Backfill complete. Total rows inserted: {total_inserted}")
    print("=" * 60)


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token E65197E694E0 - verify with scripts/authorship.py verify
