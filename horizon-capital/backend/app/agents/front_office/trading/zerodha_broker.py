"""Zerodha (Kite Connect) broker adapter -- placeholder with mock mode."""

from app.agents.front_office.trading.paper_broker import PaperBroker
from app.config import settings
from app.core.logging import get_logger
from app.core.redis_client import redis_client

logger = get_logger("execution.zerodha_broker")


class ZerodhaBroker:
    """Broker adapter for Zerodha's Kite Connect API.

    When ``settings.zerodha_mock_mode`` is ``True`` (the default), all orders
    are delegated to :class:`PaperBroker` for simulated fills.

    The real Kite Connect integration structure is in place but marked with
    TODO comments for future implementation once API credentials and
    regulatory requirements are finalised.
    """

    def __init__(self) -> None:
        self.mock_mode = settings.zerodha_mock_mode
        self._paper = PaperBroker(redis=redis_client)

        # Kite Connect credentials (used when mock_mode is False)
        self.api_key = settings.zerodha_api_key
        self.api_secret = settings.zerodha_api_secret
        self.access_token = settings.zerodha_access_token

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def execute(self, order: dict) -> dict | None:
        """Execute an order on Zerodha / NSE / BSE.

        Parameters
        ----------
        order:
            Dict with: ``symbol``, ``side``, ``quantity``, ``order_type``.
            For LIMIT orders, include ``limit_price``.

        Returns
        -------
        dict | None
            Fill record, or ``None`` on failure.
        """
        if self.mock_mode:
            logger.info("zerodha_mock_mode", symbol=order.get("symbol"))
            fill = await self._paper.execute(order)
            if fill:
                fill["broker"] = "ZERODHA_MOCK"
            return fill

        # ----- Real Kite Connect implementation (TODO) ----- #
        return await self._place_kite_order(order)

    # ------------------------------------------------------------------ #
    # Kite Connect (future implementation)
    # ------------------------------------------------------------------ #

    async def _place_kite_order(self, order: dict) -> dict | None:
        """Place an order via Kite Connect REST API.

        TODO: Implement once Zerodha API access is available.

        Steps:
        1. Authenticate using ``self.access_token`` (refresh via ``kite.login_url()``).
        2. Map ``order['symbol']`` to Kite instrument token.
        3. Call ``POST /orders/regular`` with:
           - tradingsymbol
           - exchange (NSE / BSE)
           - transaction_type (BUY / SELL)
           - order_type (MARKET / LIMIT / SL / SL-M)
           - quantity
           - price (for LIMIT orders)
           - product (CNC for delivery, MIS for intraday)
        4. Parse response for order_id.
        5. Poll ``GET /orders/<order_id>`` for fill status.
        """
        logger.error(
            "zerodha_not_implemented",
            symbol=order.get("symbol"),
            message="Real Zerodha trading is not yet implemented. "
                    "Set ZERODHA_MOCK_MODE=true to use paper trading.",
        )
        return None

    async def get_order_status(self, broker_order_id: str) -> dict | None:
        """Check the status of a Zerodha order.

        TODO: Implement ``GET /orders/<order_id>`` via Kite Connect.
        """
        if self.mock_mode:
            return {"broker_order_id": broker_order_id, "status": "COMPLETE"}

        logger.warning("zerodha_status_not_implemented", broker_order_id=broker_order_id)
        return None
