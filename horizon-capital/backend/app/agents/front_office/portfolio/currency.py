"""Currency conversion utilities for multi-currency portfolios (INR / USD)."""

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger("portfolio.currency")

FOREX_KEY = "horizon:forex:USDINR"
DEFAULT_USDINR = 83.0  # fallback rate


class CurrencyConverter:
    """Async currency helper backed by a Redis-cached USD/INR rate.

    The rate is expected to be refreshed by the market-data pipeline and
    stored at ``horizon:forex:USDINR``.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # ------------------------------------------------------------------ #
    # Rate access
    # ------------------------------------------------------------------ #

    async def get_usd_inr_rate(self) -> float:
        """Return the current USD/INR exchange rate from Redis."""
        val = await self.redis.get(FOREX_KEY)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                logger.warning("invalid_forex_rate", raw=val)
        return DEFAULT_USDINR

    # ------------------------------------------------------------------ #
    # Conversion helpers
    # ------------------------------------------------------------------ #

    async def convert_to_usd(self, amount_inr: float) -> float:
        """Convert an INR amount to USD."""
        rate = await self.get_usd_inr_rate()
        if rate <= 0:
            return 0.0
        return amount_inr / rate

    async def convert_to_inr(self, amount_usd: float) -> float:
        """Convert a USD amount to INR."""
        rate = await self.get_usd_inr_rate()
        return amount_usd * rate

    # ------------------------------------------------------------------ #
    # Unified NAV
    # ------------------------------------------------------------------ #

    async def compute_unified_nav(
        self,
        cash_usd: float,
        cash_inr: float,
        positions: list[dict],
    ) -> float:
        """Compute total portfolio NAV in USD.

        Parameters
        ----------
        cash_usd:
            Cash balance denominated in USD.
        cash_inr:
            Cash balance denominated in INR.
        positions:
            List of position dicts, each expected to have:
              - ``current_price`` (float)
              - ``quantity`` (float)
              - ``currency`` (str, "USD" or "INR")

        Returns
        -------
        float
            Total NAV expressed in USD.
        """
        rate = await self.get_usd_inr_rate()
        if rate <= 0:
            rate = DEFAULT_USDINR

        # Cash component
        total_usd = cash_usd + (cash_inr / rate)

        # Positions component
        for pos in positions:
            price = pos.get("current_price", 0.0)
            qty = pos.get("quantity", 0.0)
            currency = pos.get("currency", "USD")
            value = abs(price * qty)
            if currency == "INR":
                value = value / rate
            total_usd += value

        return total_usd
