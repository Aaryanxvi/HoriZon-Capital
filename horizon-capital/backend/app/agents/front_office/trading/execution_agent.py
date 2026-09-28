# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-5317C09E12D4
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Execution Agent -- routes orders to the paper broker.

Handles the full trade lifecycle:
  1. Receives ORDER_NEW from PortfolioAgent
  2. In HUMAN_APPROVAL mode, buffers orders marked ``requires_approval``
  3. Executes via PaperBroker (with Almgren-Chriss market impact)
  4. Updates cash balances after fills (deduct on BUY, add on SELL)
  5. Updates positions and publishes ORDER_FILL
"""

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
from app.agents.front_office.trading.order_manager import OrderManager
from app.agents.front_office.trading.paper_broker import PaperBroker
from app.agents.front_office.trading.polymarket_broker import PolymarketBroker
from app.config import settings
from app.core.cash import adjust_cash, mirror_to_kv
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()


logger = get_logger("agent.execution")


def _alpaca_guard_ok() -> bool:
    """Hard safety guard: ALPACA routing requires paper-mode + a paper-api URL.

    Independent of ``execution_broker`` — this must hold even if someone sets
    EXECUTION_BROKER=ALPACA against a misconfigured live-money URL.
    """
    return bool(
        settings.alpaca_api_key
        and settings.alpaca_api_secret
        and settings.alpaca_paper_mode
        and "paper-api" in settings.alpaca_base_url
    )


def _polymarket_guard_ok() -> bool:
    """Real Polymarket routing requires the explicit flag + wallet creds + client lib."""
    from app.agents.front_office.trading.polymarket_broker import clob_client_available

    return bool(
        settings.polymarket_real_trading
        and settings.polymarket_private_key
        and settings.polymarket_funder_address
        and clob_client_available()
    )


class ExecutionAgent(BaseAgent):
    """Routes orders to the paper broker and tracks state.

    All orders are executed through the paper broker for simulation.

    Subscribes to:
      - ``horizon.execution.order.*``

    Publishes:
      - ``horizon.execution.order.fill``  -- after a successful fill
      - ``horizon.execution.order.update`` -- status changes
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="execution-agent",
            agent_type="execution",
            bus=bus,
        )
        self.order_manager = OrderManager()
        self.paper_broker = PaperBroker()
        self.alpaca_broker = AlpacaBroker()
        self.polymarket_broker = PolymarketBroker()
        self.broker, self.broker_name = self._resolve_broker()
        # Orders awaiting human CIO approval: order_id -> order dict
        self._pending_approval: dict[str, dict] = {}
        self._cio_halt_active: bool = False
        # Per-symbol locks. update_position does a read-modify-write across its
        # own session; two overlapping fills on the same symbol would otherwise
        # both read the old qty and the second UPDATE would clobber the first.
        self._symbol_locks: dict[str, asyncio.Lock] = {}

    def _resolve_broker(self) -> tuple[object, str]:
        """Pick the live broker for this session (called once at startup).

        ALPACA is only selected if the safety guard passes; any other
        misconfiguration falls back to PAPER without raising.
        """
        if settings.execution_broker.upper() == "ALPACA":
            if _alpaca_guard_ok():
                return self.alpaca_broker, "ALPACA"
            logger.error(
                "alpaca_guard_failed_falling_back_paper",
                has_key=bool(settings.alpaca_api_key),
                has_secret=bool(settings.alpaca_api_secret),
                paper_mode=settings.alpaca_paper_mode,
                base_url=settings.alpaca_base_url,
            )
        return self.paper_broker, "PAPER"

    def _broker_for(self, symbol: str) -> tuple:
        """Per-order broker routing. .POLY symbols never touch Alpaca."""
        if symbol.endswith(".POLY"):
            if _polymarket_guard_ok():
                return self.polymarket_broker, "POLYMARKET"
            return self.paper_broker, "PAPER"
        return self.broker, self.broker_name

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.new", self.on_message)
        await self.bus.subscribe("horizon.execution.order.pending", self.on_message)
        await self.bus.subscribe("horizon.execution.order.cancel", self.on_message)
        await self.bus.subscribe("horizon.executive.cio", self.on_message)

    async def run(self) -> None:
        """Reconcile against the broker once at startup, then poll for stale orders."""
        await self._rehydrate_pending()

        if self.broker_name == "ALPACA":
            await self._reconcile_alpaca_startup()

        while self._running:
            try:
                await self._poll_open_orders()
            except Exception as exc:
                logger.error("execution_loop_error", error=str(exc))
            await asyncio.sleep(5)

    async def _reconcile_alpaca_startup(self) -> None:
        """One-time startup check when routing through ALPACA.

        Reports mismatches (broker unreachable, position drift) via
        RISK_ALERT — never mutates local state. Local orders left OPEN with
        a broker_order_id from a previous run are polled once immediately so
        they don't sit stale until the next 5s loop.
        """
        account = await self.alpaca_broker.get_account()
        if account is None:
            logger.error("alpaca_unreachable_at_startup")
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "alpaca_unreachable",
                    "action": "falling back to PAPER for this session",
                    "severity": "HIGH",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            self.broker, self.broker_name = self.paper_broker, "PAPER"
            return

        equity = float(account.get("equity", 0))
        local_nav_raw = await _get_kv().get("horizon:portfolio:nav")
        local_nav = float(local_nav_raw) if local_nav_raw else settings.initial_capital_usd
        pct = abs(local_nav - equity) / max(equity, 1)
        if pct > 0.02:
            logger.error(
                "alpaca_equity_mismatch", local=local_nav, broker=equity, pct=pct,
            )
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "alpaca_equity_mismatch",
                    "local_nav": local_nav,
                    "broker_equity": equity,
                    "pct": pct,
                    "action": "falling back to PAPER for this session",
                    "severity": "CRITICAL",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            self.broker, self.broker_name = self.paper_broker, "PAPER"
            return
        logger.info("alpaca_equity_ok", local=local_nav, broker=equity)

        broker_positions = await self.alpaca_broker.get_positions()
        # Alpaca symbols have no exchange suffix; local symbols do (AAPL.NASDAQ).
        broker_qty = {p["symbol"]: p["qty"] for p in broker_positions}

        async with _get_session_factory()() as session:
            result = await session.execute(
                text("SELECT symbol, quantity FROM positions WHERE side = 'LONG' AND quantity > 0")
            )
            local_positions = result.fetchall()

        mismatches = []
        for row in local_positions:
            local_symbol = row.symbol.split(".")[0] if "." in row.symbol else row.symbol
            broker_side_qty = broker_qty.get(local_symbol, 0.0)
            if abs(broker_side_qty - row.quantity) > 1e-6:
                mismatches.append(
                    {"symbol": row.symbol, "local_qty": row.quantity, "broker_qty": broker_side_qty}
                )
                logger.warning(
                    "alpaca_position_mismatch",
                    symbol=row.symbol, local_qty=row.quantity, broker_qty=broker_side_qty,
                )

        if mismatches:
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "alpaca_position_mismatch",
                    "mismatches": mismatches,
                    "severity": "HIGH",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity, stop_price,
                           broker_order_id, created_at
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker = 'ALPACA'
                      AND broker_order_id IS NOT NULL
                """)
            )
            stuck_rows = result.fetchall()

        for row in stuck_rows:
            await self._poll_alpaca_order(row)

    async def on_message(self, message: AgentMessage) -> None:
        """Handle new order requests and approval/rejection."""
        if message.message_type == MessageType.CIO_OVERRIDE:
            actions = message.payload.get("actions", []) or []
            if "HALT" in actions:
                self._cio_halt_active = True
                logger.warning("execution_cio_halt_active",
                               override_id=message.payload.get("override_id"))
            elif "RESUME" in actions:
                self._cio_halt_active = False
                logger.info("execution_cio_halt_cleared",
                            override_id=message.payload.get("override_id"))
            return

        if self._cio_halt_active and message.message_type == MessageType.ORDER_NEW:
            order_id = message.payload.get("order_id", "")
            logger.warning("execution_order_blocked_by_cio_halt", order_id=order_id)
            return

        if message.message_type == MessageType.ORDER_NEW:
            await self._handle_new_order(message)
        elif message.message_type == MessageType.ORDER_CANCEL:
            # Handle rejection of pending orders
            order_id = message.payload.get("order_id", "")
            if order_id in self._pending_approval:
                del self._pending_approval[order_id]
                await self._delete_pending(order_id)
                await self.order_manager.update_status(order_id, "REJECTED",
                                                       rejection_reason="CIO rejected")
                logger.info("order_rejected_by_cio", order_id=order_id)

    async def _handle_new_order(self, message: AgentMessage) -> None:
        """Receive a new order request and execute via paper broker."""
        payload = message.payload
        _, broker_name = self._broker_for(payload["symbol"])

        order_data = {
            "symbol": payload["symbol"],
            "exchange": payload.get("exchange", ""),
            "order_type": payload.get("order_type", "MARKET"),
            "side": payload["side"],
            "quantity": payload["quantity"],
            "limit_price": payload.get("limit_price"),
            "stop_price": payload.get("stop_price"),
            "signal_id": payload.get("signal_id"),
            "debate_id": payload.get("debate_id"),
            "stop_loss": payload.get("stop_loss"),
            "broker": broker_name,
            "mode": settings.system_mode.value,
        }

        order = await self.order_manager.create_order(order_data)

        # Emit tracked order with real order_id for dashboard
        await self.emit(
            channel="horizon.execution.order.tracked",
            message_type=MessageType.ORDER_NEW,
            payload={
                "order_id": order["id"],
                "symbol": order["symbol"],
                "exchange": order.get("exchange", ""),
                "side": order["side"],
                "quantity": order["quantity"],
                "status": "OPEN",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # In HUMAN_APPROVAL mode, buffer orders that need approval
        if payload.get("requires_approval"):
            self._pending_approval[order["id"]] = order
            await self._persist_pending(order)
            await self.order_manager.update_status(order["id"], "OPEN")
            logger.info("order_pending_approval", order_id=order["id"],
                        symbol=order["symbol"])
            return

        try:
            await self._execute_order(order)
        except Exception as exc:
            await self.order_manager.update_status(
                order["id"], "REJECTED",
                rejection_reason=f"Atomic fill rollback: {type(exc).__name__}",
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order["id"],
                    "status": "REJECTED",
                    "reason": f"Atomic fill rollback: {type(exc).__name__}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.error(
                "execute_order_failed",
                order_id=order["id"],
                error=str(exc),
            )

    async def approve_order(self, order_id: str) -> bool:
        """Approve a pending order (called from REPL 'approve' command)."""
        order = self._pending_approval.pop(order_id, None)
        if order is None:
            # Try partial match
            for oid, o in list(self._pending_approval.items()):
                if oid.startswith(order_id):
                    order = self._pending_approval.pop(oid)
                    order_id = oid
                    break
        if order is None:
            return False
        await self._delete_pending(order_id)
        try:
            await self._execute_order(order)
        except Exception as exc:
            await self.order_manager.update_status(
                order["id"], "REJECTED",
                rejection_reason=f"Atomic fill rollback: {type(exc).__name__}",
            )
            logger.error(
                "approve_order_failed",
                order_id=order["id"], error=str(exc),
            )
            return False
        return True

    async def reject_order(self, order_id: str) -> bool:
        """Reject a pending order (called from REPL 'reject' command)."""
        order = self._pending_approval.pop(order_id, None)
        if order is None:
            for oid in list(self._pending_approval.keys()):
                if oid.startswith(order_id):
                    order = self._pending_approval.pop(oid)
                    order_id = oid
                    break
        if order is None:
            return False
        await self._delete_pending(order_id)
        await self.order_manager.update_status(order_id, "REJECTED",
                                               rejection_reason="CIO rejected")
        return True

    def get_pending_approvals(self) -> list[dict]:
        """Return list of orders awaiting CIO approval."""
        return list(self._pending_approval.values())

    async def _persist_pending(self, order: dict) -> None:
        """Durably record a pending-approval order so a restart can recover it."""
        try:
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        "INSERT OR REPLACE INTO pending_approvals (id, payload, created_at)"
                        " VALUES (:id, :payload, :ts)"
                    ),
                    {
                        "id": order["id"],
                        "payload": json.dumps(order, default=str),
                        "ts": datetime.now(UTC).isoformat(),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("persist_pending_failed", order_id=order.get("id"), error=str(exc))

    async def _delete_pending(self, order_id: str) -> None:
        """Remove a persisted pending-approval row once it's resolved."""
        try:
            async with _get_session_factory()() as session:
                await session.execute(
                    text("DELETE FROM pending_approvals WHERE id = :id"),
                    {"id": order_id},
                )
                await session.commit()
        except Exception as exc:
            logger.warning("delete_pending_failed", order_id=order_id, error=str(exc))

    async def _rehydrate_pending(self) -> None:
        """Reload pending-approval orders persisted before a restart."""
        try:
            async with _get_session_factory()() as session:
                result = await session.execute(
                    text("SELECT id, payload FROM pending_approvals")
                )
                rows = result.fetchall()
        except Exception as exc:
            logger.warning("rehydrate_pending_failed", error=str(exc))
            return

        count = 0
        for row in rows:
            try:
                self._pending_approval[row.id] = json.loads(row.payload)
                count += 1
            except Exception as exc:
                logger.warning("rehydrate_pending_row_skipped", order_id=row.id, error=str(exc))

        if count:
            logger.info("pending_approvals_rehydrated", count=count)

    async def _execute_order(self, order: dict) -> None:
        """Execute the order via the paper broker."""
        order_id = order["id"]

        # Kill switch enforcement — second layer of defense
        kv = _get_kv()
        halted = await kv.get("horizon:system:halted")
        if halted == "1" and order.get("side") == "BUY":
            await self.order_manager.update_status(
                order_id, "REJECTED",
                rejection_reason="System halted — kill switch active",
            )
            logger.warning("order_blocked_system_halted",
                           order_id=order_id, symbol=order["symbol"])
            return

        # Hard cash guard — reject BUY if it would push USD cash negative.
        # Prevents runaway over-trading regardless of upstream sizing bugs.
        if order.get("side") == "BUY" and order.get("exchange", "") not in ("NSE", "BSE"):
            from app.core.cash import get_cash
            from app.core.runtime import get_session_factory
            try:
                price = await kv.get(f"horizon:price:{order['symbol']}")
                px = float(price) if price else 0.0
                notional = px * float(order["quantity"])
                async with get_session_factory()() as s:
                    cash_usd = await get_cash(s, "USD")
                if notional > max(cash_usd, 0.0):
                    await self.order_manager.update_status(
                        order_id, "REJECTED",
                        rejection_reason=(
                            f"Insufficient cash: need ${notional:,.0f}, "
                            f"have ${cash_usd:,.0f}"
                        ),
                    )
                    logger.warning(
                        "order_blocked_cash_guard",
                        order_id=order_id, symbol=order["symbol"],
                        notional=notional, cash=cash_usd,
                    )
                    return
            except Exception as exc:
                logger.error("cash_guard_error", order_id=order_id, error=str(exc))

        # Block naked shorts: reject SELL if no open position exists
        if order.get("side") == "SELL":
            has_position = await self._has_open_position(
                order["symbol"], order.get("exchange", "")
            )
            if not has_position:
                await self.order_manager.update_status(
                    order_id, "REJECTED",
                    rejection_reason="No open position to sell (naked short blocked)",
                )
                await self.emit(
                    channel="horizon.execution.order.update",
                    message_type=MessageType.ORDER_CANCEL,
                    payload={
                        "order_id": order_id,
                        "status": "REJECTED",
                        "reason": "Naked short blocked",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                logger.info("naked_short_blocked", order_id=order_id,
                            symbol=order["symbol"])
                return

        await self.order_manager.update_status(order_id, "OPEN")

        broker, _broker_name = self._broker_for(order.get("symbol", ""))

        fill = None
        for attempt in range(3):
            fill = await broker.execute(order)
            if fill is not None:
                break
            # Only retry the paper broker. A live order that returned None may
            # have already been accepted by the broker before the connection
            # dropped — a blind re-POST would double-fire. Live retries must go
            # through an idempotency key + status check, not this loop.
            if order.get("broker") != "PAPER":
                break
            if attempt < 2:
                logger.warning("broker_retry", order_id=order_id, attempt=attempt + 1)
                await asyncio.sleep(2 ** attempt)

        if fill is None or fill.get("rejected"):
            reason = (fill or {}).get("rejection_reason", "Broker returned no fill")
            await self.order_manager.update_status(
                order_id, "REJECTED", rejection_reason=reason
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order_id,
                    "status": "REJECTED",
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return

        # Alpaca orders aren't filled instantly. If the broker accepted the
        # order but hasn't returned a COMPLETE fill (filled_qty < quantity —
        # this covers 0 and any partial), persist the broker_order_id and
        # leave it OPEN for _poll_open_orders to settle from Alpaca's final
        # cumulative fill — settling a partial here too would double-count
        # once the poll later reports the completed cumulative qty.
        if order.get("broker") == "ALPACA" and float(fill.get("filled_qty") or 0) < order.get(
            "quantity", 0
        ):
            broker_order_id = fill.get("broker_order_id", "")
            order["broker_order_id"] = broker_order_id
            await self.order_manager.set_broker_order_id(order_id, broker_order_id)
            logger.info(
                "alpaca_order_accepted_pending_fill",
                order_id=order_id, broker_order_id=broker_order_id,
                symbol=order["symbol"],
            )
            return

        await self._settle_fill(order, fill)

    async def _settle_fill(self, order: dict, fill: dict) -> None:
        """Atomically record a real fill: fill row + status + position + cash.

        Shared by the instant-fill path (PAPER, or an Alpaca order filled on
        the initial POST) and the polling path (Alpaca fills discovered via
        ``get_order_status``). Re-checks the order's DB status inside the
        per-symbol lock so a race between the two paths cannot double-settle
        the same order.
        """
        order_id = order["id"]
        side = order["side"]
        qty = float(fill["filled_qty"])
        price = float(fill["fill_price"])
        commission = float(fill.get("commission", 0.0))
        slippage = float(fill.get("slippage", 0.0))
        exchange = order.get("exchange", "")
        currency = "INR" if exchange in ("NSE", "BSE") else "USD"
        cost = qty * price
        delta = -(cost + commission) if side == "BUY" else (cost - commission)

        if qty >= order.get("quantity", 0):
            new_status = "FILLED"
        else:
            new_status = "PARTIAL"

        lock = self._symbol_locks.setdefault(order["symbol"], asyncio.Lock())
        try:
            async with lock:
                async with _get_session_factory()() as session:
                    current_status = await self.order_manager._get_status(
                        order_id, session=session
                    )
                    if current_status in ("FILLED", "CANCELLED", "REJECTED"):
                        logger.info(
                            "settle_fill_noop_already_terminal",
                            order_id=order_id, status=current_status,
                        )
                        return
                    await self.order_manager.record_fill(
                        order_id=order_id,
                        qty=qty,
                        price=price,
                        commission=commission,
                        slippage=slippage,
                        session=session,
                    )
                    await self.order_manager.update_status(
                        order_id, new_status, session=session,
                    )
                    await self.order_manager.update_position(
                        symbol=order["symbol"],
                        exchange=exchange,
                        side=side,
                        qty=qty,
                        price=price,
                        stop_loss_price=order.get("stop_loss"),
                        commission=commission,
                        session=session,
                    )
                    new_cash = await adjust_cash(session, currency, delta)
                    await session.commit()
        except Exception:
            logger.exception("atomic_fill_rollback", order_id=order_id)
            raise

        await mirror_to_kv(currency, new_cash)

        await self.emit(
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": order_id,
                "symbol": order["symbol"],
                "side": side,
                "filled_qty": qty,
                "fill_price": price,
                "commission": commission,
                "slippage": slippage,
                "broker": order.get("broker", self.broker_name),
                "status": new_status,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "order_executed",
            order_id=order_id,
            symbol=order["symbol"],
            side=side,
            qty=qty,
            price=price,
            new_cash=f"{new_cash:.2f}",
        )

    async def _poll_open_orders(self) -> None:
        """Cancel stale PAPER orders; poll and settle open ALPACA orders.

        Paper broker fills are instant, so any PAPER order still OPEN after
        60s is stuck due to an error — cancel it (re-executing without
        position/cash updates would cause infinite fills). Alpaca orders can
        legitimately sit OPEN for hours (market closed, limit not touched),
        so those are only force-cancelled after 24h; otherwise we just poll
        their live status.
        """
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, side, created_at
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker = 'PAPER'
                      AND created_at < datetime('now', '-60 seconds')
                    ORDER BY created_at ASC
                    LIMIT 20
                """)
            )
            paper_rows = result.fetchall()

            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity, stop_price,
                           broker_order_id, created_at
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL')
                      AND broker = 'ALPACA'
                      AND broker_order_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 20
                """)
            )
            alpaca_rows = result.fetchall()

        for row in paper_rows:
            try:
                await self.order_manager.update_status(
                    str(row.id), "CANCELLED",
                    rejection_reason="Stale order — not filled within 60s",
                )
                logger.warning(
                    "stale_order_cancelled",
                    order_id=str(row.id), symbol=row.symbol,
                )
            except Exception as exc:
                logger.error(
                    "poll_order_error",
                    order_id=str(row.id), error=str(exc),
                )

        for row in alpaca_rows:
            await self._poll_alpaca_order(row)

    async def _poll_alpaca_order(self, row) -> None:  # noqa: ANN001
        """Poll one Alpaca order's status and settle/cancel as appropriate."""
        order_id = str(row.id)
        try:
            status = await self.alpaca_broker.get_order_status(row.broker_order_id)
        except Exception as exc:
            logger.error("alpaca_poll_error", order_id=order_id, error=str(exc))
            return

        if status is None:
            return

        alpaca_status = status.get("status")
        filled_qty = float(status.get("filled_qty") or 0)
        fill_price = float(status.get("filled_avg_price") or 0)

        if alpaca_status == "filled" and filled_qty > 0 and fill_price <= 0:
            # API edge case: reported filled but no price yet. Never settle
            # at price 0 — wait for the next poll cycle to see a real price.
            logger.error(
                "alpaca_filled_without_price", order_id=order_id, filled_qty=filled_qty,
            )
            return
        elif alpaca_status == "filled" and filled_qty > 0:
            order = {
                "id": order_id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "side": row.side,
                "quantity": row.quantity,
                "stop_loss": None,
                "broker": "ALPACA",
            }
            fill = {
                "filled_qty": filled_qty,
                "fill_price": fill_price,
                "commission": 0.0,
                "slippage": 0.0,
            }
            await self._settle_fill(order, fill)
        elif alpaca_status in ("canceled", "rejected", "expired"):
            await self.order_manager.update_status(
                order_id, "CANCELLED",
                rejection_reason=f"Alpaca reported status={alpaca_status}",
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order_id,
                    "status": "CANCELLED",
                    "reason": f"Alpaca reported status={alpaca_status}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning(
                "alpaca_order_cancelled", order_id=order_id, alpaca_status=alpaca_status,
            )
        elif alpaca_status not in ("new", "accepted", "pending_new", "partially_filled"):
            # Unknown/terminal-ish state we don't specifically handle — leave
            # OPEN and let the 24h staleness check below sweep it eventually.
            logger.warning(
                "alpaca_order_unhandled_status",
                order_id=order_id, alpaca_status=alpaca_status,
            )

        # Force-cancel Alpaca orders stuck OPEN for >24h (market orders queue
        # while the market is closed; 60s staleness does not apply here).
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT status FROM orders
                    WHERE id = :id AND created_at < datetime('now', '-24 hours')
                """),
                {"id": order_id},
            )
            stale = result.fetchone()
        if stale and stale.status in ("OPEN", "PARTIAL"):
            try:
                await self.alpaca_broker.cancel_order(row.broker_order_id)
            except Exception as exc:
                logger.error("alpaca_cancel_error", order_id=order_id, error=str(exc))
            await self.order_manager.update_status(
                order_id, "CANCELLED",
                rejection_reason="Stale Alpaca order — not filled within 24h",
            )
            logger.warning("stale_alpaca_order_cancelled", order_id=order_id)

    async def _has_open_position(self, symbol: str, exchange: str) -> bool:
        """Check if there is an open position for this symbol."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT quantity FROM positions"
                    " WHERE symbol = :sym AND exchange = :exch AND quantity > 0"
                    " LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            row = result.fetchone()
        return row is not None

    async def _get_total_filled(self, order_id: str) -> float:
        """Sum filled_qty from all fills for an order."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT COALESCE(SUM(filled_qty), 0) AS total"
                    " FROM fills WHERE order_id = :oid"
                ),
                {"oid": order_id},
            )
            row = result.fetchone()
        return float(row.total) if row else 0.0

# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 5317C09E12D4 - verify with scripts/authorship.py verify
