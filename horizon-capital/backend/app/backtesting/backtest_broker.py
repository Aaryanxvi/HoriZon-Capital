"""Simulated broker for backtesting.

Fills orders at the open of the next bar with a realistic slippage model
that accounts for base spread and volume impact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger("backtesting.broker")


@dataclass
class SimOrder:
    """Lightweight order representation for the backtest engine."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    side: str = "BUY"        # BUY | SELL
    quantity: float = 0.0
    order_type: str = "MARKET"  # MARKET | LIMIT
    limit_price: float | None = None


@dataclass
class SimFill:
    """Represents a filled order in the backtest."""
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    slippage: float = 0.0
    commission: float = 0.0
    filled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestBroker:
    """Simulated broker that fills orders with a slippage + commission model.

    Slippage model
    --------------
    Total slippage = base_slippage_pct + volume_impact_pct
      - base_slippage_pct  = 0.05 % (half-spread estimate)
      - volume_impact_pct  = order_qty / bar_volume * impact_coeff
      - impact_coeff       = 0.10 (10 bps per 100 % of bar volume)

    Commission
    ----------
    Flat rate per trade: ``commission_bps`` basis points of notional.
    """

    def __init__(
        self,
        base_slippage_pct: float = 0.0005,
        impact_coeff: float = 0.10,
        commission_bps: float = 5.0,
    ) -> None:
        self.base_slippage_pct = base_slippage_pct
        self.impact_coeff = impact_coeff
        self.commission_bps = commission_bps

    # ------------------------------------------------------------------
    # Slippage model
    # ------------------------------------------------------------------

    def slippage_model(
        self,
        price: float,
        volume: float,
        order_qty: float,
    ) -> float:
        """Compute total slippage in absolute price terms.

        Parameters
        ----------
        price : float
            Reference price (typically next bar's open).
        volume : float
            Bar volume for the fill bar.
        order_qty : float
            Signed order quantity (absolute value used internally).

        Returns
        -------
        float
            Absolute slippage to be added to (BUY) or subtracted from (SELL) the price.
        """
        qty = abs(order_qty)
        # Base half-spread slippage
        base = price * self.base_slippage_pct
        # Volume impact: larger orders relative to bar volume get worse fills
        if volume > 0:
            participation = qty / volume
            impact = price * participation * self.impact_coeff
        else:
            impact = price * self.base_slippage_pct  # fallback to base if no volume
        return base + impact

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, order: SimOrder, current_bar: dict) -> SimFill | None:
        """Fill an order against the current bar.

        For MARKET orders the fill price is the bar's ``open`` adjusted for
        slippage.  For LIMIT orders, the fill only occurs if the limit is
        achievable within the bar's range.

        Parameters
        ----------
        order : SimOrder
            The order to execute.
        current_bar : dict
            OHLCV bar dict with keys: open, high, low, close, volume, timestamp.

        Returns
        -------
        SimFill | None
            A fill object, or ``None`` if a limit order could not be filled.
        """
        bar_open = current_bar["open"]
        bar_high = current_bar["high"]
        bar_low = current_bar["low"]
        bar_volume = current_bar.get("volume", 0)
        bar_ts = current_bar.get("timestamp", datetime.now(timezone.utc))

        slippage_abs = self.slippage_model(bar_open, bar_volume, order.quantity)

        if order.order_type == "MARKET":
            if order.side == "BUY":
                fill_price = bar_open + slippage_abs
            else:
                fill_price = bar_open - slippage_abs
        elif order.order_type == "LIMIT":
            limit_px = order.limit_price or bar_open
            if order.side == "BUY":
                # Limit buy: only fill if bar low <= limit price
                if bar_low > limit_px:
                    return None
                fill_price = min(limit_px, bar_open) + slippage_abs
            else:
                # Limit sell: only fill if bar high >= limit price
                if bar_high < limit_px:
                    return None
                fill_price = max(limit_px, bar_open) - slippage_abs
        else:
            fill_price = bar_open  # fallback

        # Commission
        notional = fill_price * abs(order.quantity)
        commission = notional * self.commission_bps / 10_000

        fill = SimFill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=round(fill_price, 4),
            slippage=round(slippage_abs, 4),
            commission=round(commission, 4),
            filled_at=bar_ts if isinstance(bar_ts, datetime) else datetime.now(timezone.utc),
        )

        logger.debug(
            "backtest_fill",
            order_id=order.order_id,
            side=order.side,
            qty=order.quantity,
            fill_price=fill.fill_price,
            slippage=fill.slippage,
        )

        return fill
