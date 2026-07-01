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
        # Reconciliation: symbol -> (latest sleeve target_weight, exchange).
        # The strategy agent marks a target as emitted the moment it fires the
        # signal, with no feedback — any order dropped downstream (cash guard,
        # debate veto, stale price) left the position off-target until the
        # target itself moved >=50bps. This dict + _reconcile() closes the loop.
        self._sleeve_targets: dict[str, tuple[float, str]] = {}
        self._last_reconcile = datetime.now(UTC)

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.approved.*", self.on_message)
        await self.bus.subscribe("horizon.debate.*", self.on_message)
        await self.bus.subscribe("horizon.execution.order.fill", self.on_message)
    # ------------------------------------------------------------------ #
    # Main loop -- snapshot every 60 seconds
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        while self._running:
            try:
                await self._update_snapshot()
            except Exception as exc:
                logger.error("snapshot_error", error=str(exc))
            try:
                await self._reconcile()
            except Exception as exc:
                logger.error("reconcile_error", error=str(exc))
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
        elif message.message_type == MessageType.ORDER_FILL:
            try:
                await self._update_snapshot()
            except Exception as exc:
                logger.error("snapshot_on_fill_error", error=str(exc))

    async def _handle_signal(self, payload: dict) -> None:
        """Buffer or immediately process a risk-approved signal depending on mode."""
        direction = payload.get("direction", 0)
        if direction == 0:
            return

        # Stop-loss is a risk-REDUCING exit, not a discretionary trade. It must
        # bypass the halt block, signal dedup, the 120s cooldown, and the debate
        # gate — none of those should ever delay or veto closing a losing
        # position. Size a full exit and emit straight to execution.
        if payload.get("strategy_name") == "stop_loss":
            await self._size_and_emit(payload, debate_id=None)
            return

        # Kill switch enforcement — hard stop, no new orders when halted
        halted = await self.redis.get("horizon:system:halted")
        if halted == "1":
            logger.warning("signal_blocked_system_halted",
                           symbol=payload.get("symbol"))
            return

        # Record the latest sleeve target for reconciliation, even if the
        # signal is later deduped or its order dropped downstream.
        symbol_key = payload.get("symbol", "")
        if symbol_key and "target_weight" in payload:
            self._sleeve_targets[symbol_key] = (
                float(payload.get("target_weight", 0.0) or 0.0),
                payload.get("exchange", ""),
            )

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
            # Keep only the LATEST signal per symbol. Appending let a burst of
            # in-window signals pile up and then flush all at once on the next
            # debate conclusion — sized against stale prices. One symbol, one
            # pending intent.
            self._pending_signals[symbol] = [payload]
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

        try:
            target_weight = float(payload.get("target_weight", 0.0) or 0.0)
            sizing = await self._compute_position_size(
                symbol, direction, exchange,
                target_weight=target_weight,
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

        try:
            target_weight = float(payload.get("target_weight", 0.0) or 0.0)
            sizing = await self._compute_position_size(
                symbol, direction, exchange,
                target_weight=target_weight,
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
    # Reconciliation
    # ------------------------------------------------------------------ #

    async def _reconcile(self) -> None:
        """Re-issue orders for positions that drifted from their sleeve target.

        Closes the strategy->execution feedback gap: the strategy agent never
        re-emits an unchanged target, so any dropped order (cash guard, debate
        veto, stale price, risk block) stranded the position off-target forever.
        Every 15 min, compare actual weights to the recorded targets and re-size
        the delta through the normal path (idempotent — an aligned position
        sizes to qty 0 and emits nothing).

        ponytail: PAPER_TRADING only — other modes route orders through human
        approval / the debate gate, which this would bypass.
        """
        if settings.system_mode.value != "PAPER_TRADING":
            return
        now = datetime.now(UTC)
        if (now - self._last_reconcile) < timedelta(minutes=15):
            return
        if not self._sleeve_targets:
            return
        halted = await self.redis.get("horizon:system:halted")
        if halted == "1":
            return
        self._last_reconcile = now

        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        nav = await self.currency.compute_unified_nav(cash_usd, cash_inr, positions)
        if nav <= 0:
            return
        held: dict[str, float] = {}
        for p in positions:
            val = abs(float(p.get("current_price", 0.0)) * float(p.get("quantity", 0.0)))
            if p.get("currency") == "INR":
                rate = await self.currency.get_usd_inr_rate()
                if rate > 0:
                    val /= rate
            held[p.get("symbol", "")] = held.get(p.get("symbol", ""), 0.0) + val

        # Clear qty dedup so a legitimately re-sized identical order isn't
        # blocked because a previous emit of the same qty was rejected downstream.
        self._last_emitted_qty.clear()

        for symbol, (target_w, exchange) in list(self._sleeve_targets.items()):
            actual_w = held.get(symbol, 0.0) / nav
            if target_w <= 0 and symbol not in held:
                self._sleeve_targets.pop(symbol, None)  # fully exited — done
                continue
            if abs(target_w - actual_w) < 0.005:  # aligned within 50bps
                continue
            logger.info("reconcile_drift", symbol=symbol,
                        target=round(target_w, 4), actual=round(actual_w, 4))
            await self._size_and_emit({
                "symbol": symbol,
                "exchange": exchange,
                "direction": 1 if target_w > actual_w else -1,
                "target_weight": target_w,
                "strategy_name": "reconcile",
                "signal_id": str(uuid.uuid4()),
            }, debate_id=None)

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    async def _compute_position_size(
        self,
        symbol: str,
        direction: int,
        exchange: str,
        target_weight: float = 0.0,
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
            # Fractional shares for US (paper broker + Alpaca both support them);
            # whole shares only where the venue requires it (NSE/BSE). int()
            # flooring stranded 2-5% of NAV on a $100k book of high-priced names.
            qty = float(int(qty)) if is_inr else round(qty, 4)
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
        qty = float(int(qty)) if is_inr else round(qty, 4)  # fractional for US
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

