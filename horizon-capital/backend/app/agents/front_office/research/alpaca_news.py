# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-50F0294FC392
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Alpaca news client (Benzinga feed) — real-time headlines for many symbols per request.

Uses the same Alpaca keys as trading. Paper keys work against the main data host;
``data.sandbox.alpaca.markets`` rejects them (401).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("sentiment.alpaca_news")

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
_MAX_PAGES = 20  # 50 articles/page; ceiling keeps a news-storm sweep bounded


def alpaca_news_configured() -> bool:
    return bool(settings.alpaca_api_key and settings.alpaca_api_secret)


async def fetch_headlines_by_symbol(
    symbols: list[str], hours_back: int = 24
) -> dict[str, list[str]]:
    """Return ``{raw_ticker: [headline, ...]}`` for *symbols* over the last *hours_back*.

    One paginated request covers every symbol. Errors log and return what was
    fetched so far — sentiment is advisory, never worth crashing the sweep.
    """
    raw = sorted({s.split(".")[0] for s in symbols})
    if not raw or not alpaca_news_configured():
        return {}

    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    params: dict[str, str | int] = {
        "symbols": ",".join(raw),
        "start": (datetime.now(UTC) - timedelta(hours=hours_back)).isoformat(),
        "limit": 50,
        "sort": "desc",
    }
    wanted = set(raw)
    out: dict[str, list[str]] = defaultdict(list)
    articles = 0
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            for _ in range(_MAX_PAGES):
                resp = await client.get(NEWS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("news", []):
                    articles += 1
                    for sym in item.get("symbols", []):
                        if sym in wanted:
                            out[sym].append(item.get("headline", ""))
                token = data.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
    except httpx.HTTPStatusError as exc:
        logger.error(
            "alpaca_news_http_error",
            status=exc.response.status_code,
            detail=exc.response.text[:300],
        )
    except httpx.RequestError as exc:
        logger.error("alpaca_news_request_error", error=str(exc))

    logger.info("alpaca_news_fetched", articles=articles, symbols_with_news=len(out))
    return dict(out)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 50F0294FC392 - verify with scripts/authorship.py verify
