# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-5B2C9DEB97A1
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Currency conversion utilities for multi-currency portfolios (INR / USD)."""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("portfolio.currency")

FOREX_KEY = "horizon:forex:usdinr"
DEFAULT_USDINR = 83.0  # fallback rate


class CurrencyConverter:
    """Async currency helper backed by a Redis-cached USD/INR rate.

    Falls back to DEFAULT_USDINR (83.0) when Redis is unavailable (LOCAL mode).
    The rate is refreshed by the market-data pipeline and stored at
    ``horizon:forex:usdinr``.
    """

    def __init__(self, redis=None) -> None:  # noqa: ANN001
        self._redis = redis

    # ------------------------------------------------------------------ #
    # Rate access
    # ------------------------------------------------------------------ #

    async def get_usd_inr_rate(self) -> float:
        """Return the current USD/INR exchange rate from Redis (or default)."""
        if self._redis is None:
            return DEFAULT_USDINR
        try:
            val = await self._redis.get(FOREX_KEY)
            if val is not None:
                return float(val)
        except Exception:
            logger.warning("forex_redis_error", fallback=DEFAULT_USDINR)
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
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 5B2C9DEB97A1 - verify with scripts/authorship.py verify
