"""Portfolio Agent -- capital allocation, position sizing, and NAV tracking."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.portfolio.currency import CurrencyConverter
from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()

logger = get_logger("agent.portfolio")


class PortfolioAgent(BaseAgent):
    """Manages capital allocation, position sizing, and portfolio snapshots.

    In PAPER_TRADING mode (no LLM): signals are auto-approved and forwarded
    directly to execution.

    In FULLY_AUTONOMOUS mode: signals are buffered until a DEBATE_CONCLUSION
    arrives — only APPROVED signals proceed to execution.

    In HUMAN_APPROVAL mode: signals are buffered and forwarded as
    PENDING_APPROVAL orders for the CIO to approve/reject via the REPL.

    Subscribes to:
      - ``horizon.risk.approved.*``  -- risk-gated signals
      - ``horizon.debate.*``         -- debate conclusions

    Publishes:
      - ``horizon.portfolio.update``  -- after each snapshot refresh
      - ``horizon.execution.order.*`` -- sized orders
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="portfolio-agent",
            agent_type="portfolio",
            bus=bus,
        )
        self.optimizer = PortfolioOptimizer()
        self.currency = CurrencyConverter(redis=_get_kv())
        self.redis = _get_kv()
        # Buffer: symbol -> list of pending signal payloads awaiting debate
        self._pending_signals: dict[str, list[dict]] = {}
        # Cooldown: symbol -> last order timestamp (fallback if no bar_timestamp)
        self._last_order_time: dict[str, datetime] = {}
        # Bar-level dedup: symbol -> last bar_timestamp an order was placed for
        self._last_order_bar: dict[str, str] = {}
        # Signal-id dedup: bounded set of signal_ids already processed.
        # Prevents duplicate parent orders if the same signal is re-delivered.
        self._processed_signal_ids: set[str] = set()
        self._processed_signal_order: list[str] = []
        self._processed_signal_max = 5000
        # Last-emitted sizing per (symbol, side): qty actually sent downstream.
        # Skip emit if next sizing matches — kills 60s-loop spam.
        self._last_emitted_qty: dict[tuple[str, str], float] = {}
        self._order_cooldown = timedelta(seconds=120)  # fallback cooldown

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.approved.*", self.on_message)
        await self.bus.subscribe("horizon.debate.*", self.on_message)

    # ------------------------------------------------------------------ #
    # Main loop -- snapshot every 60 seconds
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        while self._running:
            try:
                await self._update_snapshot()
            except Exception as exc:
                logger.error("snapshot_error", error=str(exc))
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ #
    # Message handler
    # ------------------------------------------------------------------ #

    async def on_message(self, message: AgentMessage) -> None:
        """Handle risk-approved signals and debate conclusions."""
        if message.message_type == MessageType.SIGNAL:
            await self._handle_signal(message.payload)
        elif message.message_type == MessageType.DEBATE_CONCLUSION:
            await self._handle_debate_conclusion(message.payload)

    async def _handle_signal(self, payload: dict) -> None:
        """Buffer or immediately process a risk-approved signal depending on mode."""
        # Kill switch enforcement — hard stop, no orders when halted
        halted = await self.redis.get("horizon:system:halted")
        if halted == "1":
            logger.warning("signal_blocked_system_halted",
                           symbol=payload.get("symbol"))
            return

        direction = payload.get("direction", 0)
        if direction == 0:
            return

        # Signal-id dedup (idempotency): if upstream re-delivers the same
        # signal_id, drop it. This prevents duplicate parent orders.
        signal_id = payload.get("signal_id") or ""
        if signal_id and signal_id in self._processed_signal_ids:
            logger.debug("signal_deduped_signal_id", signal_id=signal_id)
            return

        # Dedup: one order per symbol per bar. Strategy agent now stamps
        # bar_timestamp; fall back to 120s cooldown if unavailable.
        symbol = payload.get("symbol", "")
        bar_ts = payload.get("bar_timestamp") or ""
        now = datetime.now(UTC)
        last_bar = self._last_order_bar.get(symbol)
        last = self._last_order_time.get(symbol)
        if bar_ts and last_bar == bar_ts:
            logger.debug("signal_deduped_bar", symbol=symbol, bar=bar_ts)
            return
        if not bar_ts and last and (now - last) < self._order_cooldown:
            logger.debug("signal_deduped_cooldown", symbol=symbol)
            return

        mode = settings.system_mode.value
        emitted = False

        if mode == "PAPER_TRADING":
            emitted = await self._size_and_emit(payload, debate_id=None)
        elif mode == "HUMAN_APPROVAL":
            emitted = await self._size_and_emit_pending(payload)
        else:
            if symbol not in self._pending_signals:
                self._pending_signals[symbol] = []
            self._pending_signals[symbol].append(payload)
            logger.info("signal_buffered_for_debate", symbol=symbol)
            emitted = True

        # Lock only AFTER successful emit, so qty=0 rejects don't block retries.
        if emitted:
            self._last_order_time[symbol] = now
            if bar_ts:
                self._last_order_bar[symbol] = bar_ts
            if signal_id:
                self._processed_signal_ids.add(signal_id)
                self._processed_signal_order.append(signal_id)
                if len(self._processed_signal_order) > self._processed_signal_max:
                    old = self._processed_signal_order.pop(0)
                    self._processed_signal_ids.discard(old)

    async def _handle_debate_conclusion(self, payload: dict) -> None:
        """Process a debate conclusion — release or discard buffered signals."""
        symbol = payload.get("symbol", "")
        decision = payload.get("decision", "")
        debate_id = payload.get("session_id", "")

        buffered = self._pending_signals.pop(symbol, [])
        if not buffered:
            return

        if decision == "APPROVED":
            for sig in buffered:
                await self._size_and_emit(sig, debate_id=debate_id)
            logger.info("debate_approved_orders_released",
                        symbol=symbol, count=len(buffered))
        else:
            logger.info("debate_rejected_orders_discarded",
                        symbol=symbol, count=len(buffered), decision=decision)

    async def _size_and_emit_pending(self, payload: dict) -> bool:
        """Size an order and emit it as PENDING_APPROVAL for human CIO review."""
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)
        exchange = payload.get("exchange", "")
        strength = float(payload.get("strength", 1.0) or 1.0)

        try:
            target_weight = float(payload.get("target_weight", 0.0) or 0.0)
            sizing = await self._compute_position_size(
                symbol, direction, exchange,
                target_weight=target_weight, strength=strength,
            )
        except Exception as exc:
            logger.error("sizing_error", symbol=symbol, error=str(exc))
            return False

        if sizing["quantity"] <= 0:
            return False

        side = "BUY" if direction > 0 else "SELL"
        if self._is_duplicate_sizing(symbol, side, sizing["quantity"]):
            logger.debug("sizing_deduped_qty_unchanged",
                         symbol=symbol, side=side, qty=sizing["quantity"])
            return False

        await self.emit(
            channel="horizon.execution.order.pending",
            message_type=MessageType.ORDER_NEW,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "side": side,
                "quantity": sizing["quantity"],
                "order_type": "MARKET",
                "signal_id": payload.get("signal_id"),
                "stop_loss": payload.get("stop_loss"),
                "allocation_usd": sizing["allocation_usd"],
                "requires_approval": True,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        self._last_emitted_qty[(symbol, side)] = sizing["quantity"]
        return True

    async def _size_and_emit(self, payload: dict, debate_id: str | None) -> bool:
        """Compute position size and emit ORDER_NEW."""
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)
        exchange = payload.get("exchange", "")
        strength = float(payload.get("strength", 1.0) or 1.0)

        try:
            target_weight = float(payload.get("target_weight", 0.0) or 0.0)
            sizing = await self._compute_position_size(
                symbol, direction, exchange,
                target_weight=target_weight, strength=strength,
            )
        except Exception as exc:
            logger.error("sizing_error", symbol=symbol, error=str(exc))
            return False

        if sizing["quantity"] <= 0:
            logger.info("zero_size", symbol=symbol)
            return False

        side = "BUY" if direction > 0 else "SELL"
        if self._is_duplicate_sizing(symbol, side, sizing["quantity"]):
            logger.debug("sizing_deduped_qty_unchanged",
                         symbol=symbol, side=side, qty=sizing["quantity"])
            return False

        await self.emit(
            channel="horizon.execution.order.new",
            message_type=MessageType.ORDER_NEW,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "side": side,
                "quantity": sizing["quantity"],
                "order_type": "MARKET",
                "signal_id": payload.get("signal_id"),
                "debate_id": debate_id,
                "stop_loss": payload.get("stop_loss"),
                "allocation_usd": sizing["allocation_usd"],
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        self._last_emitted_qty[(symbol, side)] = sizing["quantity"]

        logger.info(
            "order_sized",
            symbol=symbol,
            side=side,
            qty=sizing["quantity"],
            allocation=sizing["allocation_usd"],
        )
        return True

    def _is_duplicate_sizing(self, symbol: str, side: str, qty: float) -> bool:
        """Skip emit when (symbol, side) qty matches last emitted within 1 share."""
        prev = self._last_emitted_qty.get((symbol, side))
        if prev is None:
            return False
        return abs(prev - qty) < 1.0

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    async def _compute_position_size(
        self,
        symbol: str,
        direction: int,
        exchange: str,
        target_weight: float = 0.0,
        strength: float = 1.0,  # kept in signature for back-compat; ignored
    ) -> dict:
        """Size to reach the sleeve's target portfolio weight.

        Reads current holding for the symbol. Computes the dollar delta
        required to bring weight to `target_weight * NAV`. Translates to
        native-currency quantity. Always emits the delta order; the strategy
        layer is responsible for not re-emitting if drift is below threshold.
        """
        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        nav_usd = await self.currency.compute_unified_nav(
            cash_usd, cash_inr, positions,
        )
        if nav_usd <= 0:
            return {"quantity": 0.0, "allocation_usd": 0.0}

        price = await self._get_price(symbol)
        if price <= 0:
            return {"quantity": 0.0, "allocation_usd": 0.0}

        is_inr = exchange in ("NSE", "BSE")
        is_crypto = exchange == "CRYPTO"

        # Cap target weight by configured per-position limit
        pct_cap = settings.risk_max_position_pct / 100.0
        target_weight = min(max(target_weight, 0.0), pct_cap, 0.25)

        target_value_usd = nav_usd * target_weight

        # Find current position value in USD
        held_qty = 0.0
        held_value_usd = 0.0
        for p in positions:
            if p.get("symbol") == symbol:
                held_qty = float(p.get("quantity", 0.0))
                mark = float(p.get("current_price", 0.0)) or price
                val = abs(mark * held_qty)
                if p.get("currency") == "INR":
                    rate = await self.currency.get_usd_inr_rate()
                    if rate > 0:
                        val = val / rate
                held_value_usd = val
                break

        delta_usd = target_value_usd - held_value_usd
        if direction < 0:
            # SELL: only honor if delta_usd is negative (we want less). Compute
            # quantity to sell to reach target.
            if delta_usd >= 0 or held_qty <= 0:
                return {"quantity": 0.0, "allocation_usd": 0.0}
            qty_to_sell_usd = -delta_usd
            # Translate USD to native
            if is_inr:
                rate = await self.currency.get_usd_inr_rate()
                if rate <= 0:
                    return {"quantity": 0.0, "allocation_usd": 0.0}
                native_value = qty_to_sell_usd * rate
            else:
                native_value = qty_to_sell_usd
            qty = native_value / price
            if not is_crypto:
                qty = float(int(qty))
            qty = min(qty, held_qty)
            if qty <= 0:
                return {"quantity": 0.0, "allocation_usd": 0.0}
            return {"quantity": qty, "allocation_usd": qty * price if not is_inr
                    else qty * price / await self.currency.get_usd_inr_rate()}

        # BUY: only if delta_usd > 0
        if delta_usd <= 0:
            return {"quantity": 0.0, "allocation_usd": 0.0}

        if is_inr:
            rate = await self.currency.get_usd_inr_rate()
            if rate <= 0:
                return {"quantity": 0.0, "allocation_usd": 0.0}
            native_target = delta_usd * rate
            native_cash = cash_inr
        else:
            native_target = delta_usd
            native_cash = cash_usd

        if native_cash <= 0:
            logger.info("insufficient_cash", symbol=symbol, cash=native_cash)
            return {"quantity": 0.0, "allocation_usd": 0.0}

        native_alloc = min(native_target, native_cash * 0.9)
        qty = native_alloc / price
        if not is_crypto:
            qty = float(int(qty))
        if qty <= 0:
            return {"quantity": 0.0, "allocation_usd": 0.0}
        if is_inr:
            rate = await self.currency.get_usd_inr_rate()
            alloc_usd = qty * price / rate if rate > 0 else 0.0
        else:
            alloc_usd = qty * price
        return {"quantity": qty, "allocation_usd": alloc_usd}

    # ------------------------------------------------------------------ #
    # Snapshot persistence
    # ------------------------------------------------------------------ #

    async def _update_snapshot(self) -> None:
        """Compute and persist a portfolio snapshot."""
        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        usd_inr = await self.currency.get_usd_inr_rate()
        nav = await self.currency.compute_unified_nav(cash_usd, cash_inr, positions)

        # Classify position values
        equity_value = 0.0
        crypto_value = 0.0
        fno_value = 0.0
        long_value = 0.0
        short_value = 0.0

        for pos in positions:
            val = abs(pos.get("current_price", 0.0) * pos.get("quantity", 0.0))
            currency = pos.get("currency", "USD")
            if currency == "INR":
                val = val / usd_inr if usd_inr > 0 else val
            exchange = pos.get("exchange", "")
            symbol = pos.get("symbol", "")

            if "BTC" in symbol or "ETH" in symbol or exchange == "CRYPTO":
                crypto_value += val
            elif exchange in ("NSE", "BSE"):
                equity_value += val
            else:
                equity_value += val

            side = pos.get("side", "LONG")
            if side == "LONG":
                long_value += val
            elif side == "SHORT":
                short_value += val

        gross_leverage = (long_value + short_value) / nav if nav > 0 else 0.0
        net_leverage = (long_value - short_value) / nav if nav > 0 else 0.0

        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO portfolio_snapshots
                        (id, total_value, cash_inr, cash_usd, equity_value,
                         crypto_value, fno_value, gross_leverage, net_leverage,
                         usd_inr_rate, created_at, updated_at)
                    VALUES
                        (:id, :total, :cash_inr, :cash_usd, :equity,
                         :crypto, :fno, :gross_lev, :net_lev,
                         :rate, :now, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "total": nav,
                    "cash_inr": cash_inr,
                    "cash_usd": cash_usd,
                    "equity": equity_value,
                    "crypto": crypto_value,
                    "fno": fno_value,
                    "gross_lev": gross_leverage,
                    "net_lev": net_leverage,
                    "rate": usd_inr,
                    "now": now,
                },
            )
            await session.commit()

        # Cache latest snapshot in Redis
        await self.redis.hset(
            "horizon:portfolio:latest",
            mapping={
                "total_value": str(nav),
                "cash_usd": str(cash_usd),
                "cash_inr": str(cash_inr),
                "gross_leverage": str(gross_leverage),
                "net_leverage": str(net_leverage),
                "updated_at": now.isoformat(),
            },
        )
        await self.redis.set("horizon:portfolio:nav", str(nav))

        # Build position summaries for dashboard
        pos_summaries = [
            {
                "symbol": p.get("symbol", ""),
                "exchange": p.get("exchange", ""),
                "side": p.get("side", "LONG"),
                "qty": p.get("quantity", 0),
                "avg_entry_price": p.get("avg_entry_price", 0.0),
                "current_price": p.get("current_price", 0.0),
                "unrealized_pnl": p.get("unrealized_pnl", 0.0),
                "currency": p.get("currency", "USD"),
            }
            for p in positions
        ]

        # Publish update
        await self.emit(
            channel="horizon.portfolio.update",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload={
                "total_value": nav,
                "cash_usd": cash_usd,
                "cash_inr": cash_inr,
                "positions": pos_summaries,
                "gross_leverage": gross_leverage,
                "net_leverage": net_leverage,
                "timestamp": now.isoformat(),
            },
        )

        logger.info("snapshot_updated", nav=f"{nav:.2f}", leverage=f"{gross_leverage:.2f}")

    # ------------------------------------------------------------------ #
    # Data helpers
    # ------------------------------------------------------------------ #

    async def _load_positions(self) -> list[dict]:
        """Load all open positions from the database."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT symbol, exchange, side, quantity, avg_entry_price,
                           current_price, unrealized_pnl, realized_pnl,
                           weight_pct, currency
                    FROM positions
                    WHERE quantity != 0
                    """
                )
            )
            rows = result.fetchall()

        return [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "side": r.side,
                "quantity": r.quantity,
                "avg_entry_price": r.avg_entry_price,
                "current_price": r.current_price,
                "unrealized_pnl": r.unrealized_pnl,
                "realized_pnl": r.realized_pnl,
                "weight_pct": r.weight_pct,
                "currency": r.currency,
            }
            for r in rows
        ]

    async def _load_cash(self) -> tuple[float, float]:
        """Load cash balances from Redis."""
        usd = await self.redis.get("horizon:cash:usd")
        inr = await self.redis.get("horizon:cash:inr")
        return float(usd or 0.0), float(inr or 0.0)

    async def _get_price(self, symbol: str) -> float:
        """Get latest price from Redis."""
        price = await self.redis.get(f"horizon:price:{symbol}")
        if price is not None:
            try:
                return float(price)
            except (ValueError, TypeError):
                pass
        return 0.0

