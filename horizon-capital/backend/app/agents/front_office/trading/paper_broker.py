"""Paper (simulated) broker with Almgren-Chriss market impact model.

Replaces simple random slippage with a market-impact model that separates
permanent and temporary price impact based on order size, daily volume,
and volatility.
"""

import random
from datetime import UTC, datetime

from app.core.logging import get_logger


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()


logger = get_logger("execution.paper_broker")

# Almgren-Chriss default parameters (calibrated for liquid US equities)
_DEFAULT_DAILY_VOLUME = 1_000_000  # shares; used when actual volume unknown
_DEFAULT_VOLATILITY = 0.02  # 2% daily volatility
_PERMANENT_IMPACT_GAMMA = 0.5  # permanent impact exponent (sqrt-law)
_PERMANENT_IMPACT_ETA = 0.01  # permanent impact coefficient
# Half-spread as FRACTION of price (1 bp = 0.0001). Liquid equities ~ 1-2 bps.
_TEMPORARY_IMPACT_EPSILON = 0.0001
_PRICE_MAX_AGE_SECONDS = 300  # 5 minutes — reject stale cached prices
_TEMPORARY_IMPACT_ETA = 0.01  # temporary impact coefficient
_TEMPORARY_IMPACT_GAMMA = 0.5  # temporary impact exponent


class AlmgrenChrissModel:
    """Almgren-Chriss market impact model (closed-form).

    Separates total market impact into:
    - Permanent impact: irreversible price move from information content
    - Temporary impact: transient cost from market microstructure

    Total slippage = permanent_impact + temporary_impact
    """

    @staticmethod
    def compute_impact(
        quantity: float,
        price: float,
        daily_volume: float = _DEFAULT_DAILY_VOLUME,
        volatility: float = _DEFAULT_VOLATILITY,
        side: str = "BUY",
    ) -> dict:
        """Compute Almgren-Chriss market impact.

        Parameters
        ----------
        quantity:
            Number of shares being traded.
        price:
            Current mid-price.
        daily_volume:
            Average daily volume in shares.
        volatility:
            Daily volatility as a decimal (e.g. 0.02 = 2%).
        side:
            "BUY" or "SELL".

        Returns
        -------
        dict
            Keys: permanent_impact, temporary_impact, total_impact_pct,
            fill_price, slippage_amount
        """
        if quantity <= 0 or price <= 0 or daily_volume <= 0:
            return {
                "permanent_impact": 0.0,
                "temporary_impact": 0.0,
                "total_impact_pct": 0.0,
                "fill_price": price,
                "slippage_amount": 0.0,
            }

        # Participation rate: fraction of daily volume
        participation = quantity / daily_volume

        # Permanent impact: g(v) = eta * sigma * (Q/V)^gamma
        # This is the irreversible price move
        permanent = (
            _PERMANENT_IMPACT_ETA
            * volatility
            * price
            * (participation ** _PERMANENT_IMPACT_GAMMA)
        )

        # Temporary impact: half-spread (as FRACTION of price) + size-dependent component.
        # epsilon is the half-spread fraction (e.g. 0.0001 = 1 bp).
        temporary = (
            _TEMPORARY_IMPACT_EPSILON * price
            + _TEMPORARY_IMPACT_ETA
            * volatility
            * price
            * (participation ** _TEMPORARY_IMPACT_GAMMA)
        )

        total_impact = permanent + temporary
        total_impact_pct = total_impact / price if price > 0 else 0.0

        # Apply direction
        direction = 1 if side == "BUY" else -1
        fill_price = price + direction * total_impact

        # Add small random noise (microstructure), clamped so it never favours the trader
        raw_noise = random.gauss(0, volatility * price * 0.01)
        noise = max(0.0, raw_noise) if side == "BUY" else min(0.0, raw_noise)
        fill_price += noise

        slippage_amount = abs(fill_price - price) * quantity

        return {
            "permanent_impact": round(permanent, 6),
            "temporary_impact": round(temporary, 6),
            "total_impact_pct": round(total_impact_pct, 6),
            "fill_price": round(fill_price, 6),
            "slippage_amount": round(slippage_amount, 6),
        }


class PaperBroker:
    """Simulated broker using Almgren-Chriss market impact model.

    Uses the last price cached in Redis (``horizon:price:<symbol>``) as the
    mid-price and applies the Almgren-Chriss model for realistic slippage.
    """

    def __init__(self) -> None:
        self._impact_model = AlmgrenChrissModel()

    async def execute(self, order: dict) -> dict:
        """Simulate order execution with Almgren-Chriss impact.

        Parameters
        ----------
        order:
            Dict with at least: ``symbol``, ``side``, ``quantity``.
            Optional: ``limit_price``, ``daily_volume``, ``volatility``.

        Returns
        -------
        dict
            Fill record with market impact breakdown.
        """
        symbol = order["symbol"]
        side = order.get("side", "BUY")
        quantity = order["quantity"]
        order_id = order.get("id", "")

        if side not in ("BUY", "SELL"):
            return self._rejection(order_id, f"Unknown order side: {side!r}")

        # Get last price from Redis
        last_price = await self._get_last_price(symbol)
        if last_price <= 0:
            logger.warning("no_price_for_paper_fill", symbol=symbol)
            return self._rejection(order_id, "No price available for paper fill")

        # Get optional market data
        daily_volume = order.get("daily_volume", _DEFAULT_DAILY_VOLUME)
        volatility = order.get("volatility", _DEFAULT_VOLATILITY)

        # Try to read cached volume from KV store
        cached_vol = await _get_kv().get(f"horizon:volume:{symbol}")
        if cached_vol is not None:
            try:
                daily_volume = float(cached_vol)
            except (ValueError, TypeError):
                pass

        # Compute Almgren-Chriss market impact
        impact = self._impact_model.compute_impact(
            quantity=quantity,
            price=last_price,
            daily_volume=daily_volume,
            volatility=volatility,
            side=side,
        )

        limit_price = order.get("limit_price")
        if limit_price is not None:
            lp = float(limit_price)
            fill_px = impact["fill_price"]
            if side == "BUY" and fill_px > lp:
                reason = f"Limit price {lp} not reachable (fill {fill_px:.4f})"
                return self._rejection(order_id, reason)
            if side == "SELL" and fill_px < lp:
                reason = f"Limit price {lp} not reachable (fill {fill_px:.4f})"
                return self._rejection(order_id, reason)

        # Commission model by exchange (round-trip cost retail pays).
        exchange = order.get("exchange", "")
        notional = impact["fill_price"] * quantity
        if exchange in ("NSE", "BSE"):
            commission_bps = 10.0  # ~0.1% (STT + brokerage + GST + exchange + SEBI)
        elif exchange == "CRYPTO":
            commission_bps = 10.0  # ~0.1% taker fee typical crypto exchanges
        elif exchange == "POLY":
            commission_bps = 0.0  # Polymarket charges no trading fee
        else:
            commission_bps = 1.0  # US equities: near-zero + SEC fees, use ~1 bp
        commission = abs(notional) * commission_bps / 10_000.0

        fill = {
            "order_id": order_id,
            "filled_qty": quantity,
            "fill_price": impact["fill_price"],
            "commission": round(commission, 4),
            "slippage": impact["slippage_amount"],
            "slippage_pct": impact["total_impact_pct"],
            "permanent_impact": impact["permanent_impact"],
            "temporary_impact": impact["temporary_impact"],
            "filled_at": datetime.now(UTC).isoformat(),
            "broker": "PAPER",
            "impact_model": "almgren_chriss",
        }

        logger.info(
            "paper_fill",
            symbol=symbol,
            side=side,
            qty=quantity,
            price=fill["fill_price"],
            slippage_pct=f"{impact['total_impact_pct'] * 100:.4f}%",
            permanent=impact["permanent_impact"],
            temporary=impact["temporary_impact"],
        )

        return fill

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _get_last_price(self, symbol: str) -> float:
        """Return the current mark price for ``symbol``.

        Priority order:
        1. Alpaca latest trade (realtime IEX), when configured and symbol is US.
        2. KV-cached last price (written by the data ingestion worker or the
           strategy agent's daily-bar poll).
        """
        from app.data_layer import alpaca_quotes

        is_us = not (".NSE" in symbol or ".BSE" in symbol or "-USD" in symbol or ".POLY" in symbol)
        if is_us and alpaca_quotes.is_configured():
            live = await alpaca_quotes.get_latest_price(symbol)
            if live and live > 0:
                return live

        kv = _get_kv()
        val = await kv.get(f"horizon:price:{symbol}")
        if val is not None:
            try:
                price = float(val)
            except (ValueError, TypeError):
                return 0.0
            ts_str = await kv.get(f"horizon:price:{symbol}:ts")
            if ts_str is not None:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    age = (datetime.now(UTC) - ts).total_seconds()
                    if age > _PRICE_MAX_AGE_SECONDS:
                        logger.warning(
                            "stale_price_rejected",
                            symbol=symbol,
                            age_seconds=int(age),
                        )
                        return 0.0
                except (ValueError, TypeError):
                    pass  # No valid timestamp — treat price as fresh (backward compat)
            return price
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
            "broker": "PAPER",
            "rejected": True,
            "rejection_reason": reason,
        }
