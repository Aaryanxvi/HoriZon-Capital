"""PaperCryptoBroker -- simulated crypto order execution.

Mirrors the PaperBroker interface but uses get_kv_store() so it works
in LOCAL mode (SQLite + MemoryKVStore) without Redis.

CoinGecko prices are cached under ``horizon:price:<SYMBOL>`` by the
data ingestion worker (crypto_feed.py). This broker reads those prices
and applies simplified Almgren-Chriss market impact (crypto markets are
far more liquid than equities for small orders, so we use conservative
defaults).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger

logger = get_logger("execution.paper_crypto_broker")

# Crypto-specific impact defaults (lower impact than equities)
_CRYPTO_DAILY_VOLUME = 50_000_000   # USD; conservative for BTC-class assets
_CRYPTO_VOLATILITY = 0.04           # 4% daily vol
_CRYPTO_SPREAD_BPS = 0.0010         # ~10 bps half-spread


class PaperCryptoBroker:
    """Simulated crypto broker using in-memory KV store for price lookup.

    Suitable for LOCAL mode (no Redis/Docker required). Prices are sourced
    from the CoinGecko feed cached in MemoryKVStore.
    """

    async def execute(self, order: dict) -> dict:
        """Simulate crypto order execution.

        Parameters
        ----------
        order :
            Dict with at least: ``symbol``, ``side``, ``quantity``.
            ``quantity`` should be in base currency units (e.g. BTC, not USD).

        Returns
        -------
        dict
            Fill record compatible with the fills table schema.
        """
        symbol = order["symbol"]
        side = order.get("side", "BUY")
        quantity = float(order.get("quantity", 0.0))
        order_id = order.get("id", "")

        if quantity <= 0:
            return self._rejection(order_id, f"Invalid quantity: {quantity}")

        last_price = await self._get_last_price(symbol)
        if last_price <= 0:
            logger.warning("paper_crypto.no_price", symbol=symbol)
            return self._rejection(order_id, f"No price available for {symbol}")

        # Apply simplified market impact
        spread = last_price * _CRYPTO_SPREAD_BPS
        direction = 1 if side == "BUY" else -1

        # Temporary impact: proportional to order size
        notional = quantity * last_price
        participation = notional / _CRYPTO_DAILY_VOLUME
        temp_impact = (
            last_price * _CRYPTO_SPREAD_BPS
            + last_price * _CRYPTO_VOLATILITY * 0.142 * (participation ** 0.6)
        )

        noise = random.gauss(0, last_price * _CRYPTO_VOLATILITY * 0.005)
        fill_price = last_price + direction * (spread + temp_impact) + noise
        fill_price = max(fill_price, 0.01)

        slippage_amount = abs(fill_price - last_price) * quantity

        fill = {
            "order_id": order_id,
            "filled_qty": quantity,
            "fill_price": round(fill_price, 8),
            "commission": round(notional * 0.001, 8),   # 10bps taker fee
            "slippage": round(slippage_amount, 8),
            "slippage_pct": round(abs(fill_price - last_price) / last_price, 8),
            "filled_at": datetime.now(UTC).isoformat(),
            "broker": "PAPER_CRYPTO",
            "impact_model": "simplified_almgren_chriss",
        }

        logger.info(
            "paper_crypto_fill",
            symbol=symbol,
            side=side,
            qty=quantity,
            price=fill["fill_price"],
            slippage_pct=f"{fill['slippage_pct'] * 100:.4f}%",
        )
        return fill

    async def _get_last_price(self, symbol: str) -> float:
        """Look up the last cached price from the KV store."""
        kv = get_kv_store()
        # Normalise symbol: BTC-USD -> BTC, bitcoin -> BTC
        raw = symbol.split("-")[0].split(".")[0]
        for key in (f"horizon:price:{symbol}", f"horizon:price:{raw}"):
            val = await kv.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.0

    @staticmethod
    def _rejection(order_id: str, reason: str) -> dict:
        return {
            "order_id": order_id,
            "filled_qty": 0.0,
            "fill_price": 0.0,
            "commission": 0.0,
            "slippage": 0.0,
            "filled_at": datetime.now(UTC).isoformat(),
            "broker": "PAPER_CRYPTO",
            "rejected": True,
            "rejection_reason": reason,
        }
