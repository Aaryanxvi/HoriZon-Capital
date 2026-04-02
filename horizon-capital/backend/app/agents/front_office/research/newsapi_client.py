"""NewsAPI client for fetching financial news articles."""

from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("sentiment.newsapi")

# Map ticker symbols to human-readable search queries for better article matching
SYMBOL_QUERY_MAP: dict[str, str] = {
    "AAPL": "Apple stock",
    "MSFT": "Microsoft stock",
    "GOOGL": "Google Alphabet stock",
    "AMZN": "Amazon stock",
    "TSLA": "Tesla stock",
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys stock",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "BTC-USD": "Bitcoin BTC crypto",
    "ETH-USD": "Ethereum ETH crypto",
}


def _symbol_to_query(symbol: str) -> str:
    """Convert a ticker symbol to a search-friendly query string.

    Strips exchange suffixes (e.g., ``RELIANCE.NSE`` -> ``RELIANCE``) before lookup.
    Falls back to the raw ticker if no mapping is defined.
    """
    base = symbol.split(".")[0]
    return SYMBOL_QUERY_MAP.get(base, f"{base} stock")


class NewsAPIClient:
    """Async client for the NewsAPI ``/v2/everything`` endpoint."""

    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.newsapi_api_key

    async def fetch_news(
        self,
        symbol: str,
        days_back: int = 14,
    ) -> list[dict]:
        """Fetch recent news articles for *symbol*.

        Parameters
        ----------
        symbol:
            Ticker symbol, optionally with exchange suffix.
        days_back:
            Number of days to look back from today (default 14 per paper-9
            optimal lookback window).

        Returns
        -------
        list[dict]
            Each dict contains ``title``, ``description``, ``url``,
            ``publishedAt``, and ``source``.
        """
        if not self.api_key:
            return []

        query = _symbol_to_query(symbol)
        from_date = (datetime.now(UTC) - timedelta(days=days_back)).strftime(
            "%Y-%m-%d"
        )

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 100,
            "apiKey": self.api_key,
        }

        articles: list[dict] = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") != "ok":
                    logger.warning(
                        "newsapi_error_response",
                        symbol=symbol,
                        message=data.get("message"),
                    )
                    return articles

                for article in data.get("articles", []):
                    articles.append(
                        {
                            "title": article.get("title", ""),
                            "description": article.get("description", ""),
                            "url": article.get("url", ""),
                            "publishedAt": article.get("publishedAt", ""),
                            "source": article.get("source", {}).get("name", "unknown"),
                        }
                    )

            logger.info(
                "newsapi_fetched",
                symbol=symbol,
                article_count=len(articles),
                days_back=days_back,
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "newsapi_http_error",
                symbol=symbol,
                status=exc.response.status_code,
                detail=exc.response.text[:500],
            )
        except httpx.RequestError as exc:
            logger.error("newsapi_request_error", symbol=symbol, error=str(exc))

        return articles
