# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-5317C09E12D4
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Execution Agent -- the last gate before the broker, and the broker's mirror.

Handles the full trade lifecycle:
  1. Receives ORDER_NEW from PortfolioAgent (or the REPL)
  2. In HUMAN_APPROVAL mode, buffers orders marked ``requires_approval``
  3. Applies the pre-trade guards (every producer, no exceptions):
       BUY : kill switch / CIO halt, broker reachable, price band, per-order
             notional cap, post-trade position cap, cash
       SELL: reduce-only (never more than held; broker-verified on ALPACA)
  4. Executes via PaperBroker (Almgren-Chriss impact) or Alpaca
  5. Books fills atomically (fill row + status + position + cash)
  6. Arms the trailing stop: broker-side GTC trailing_stop on ALPACA, and the
     position row's stop_loss_price/high_water_mark for PositionMonitorWorker

Principle (owner decision 2026-10-10): a reduce-only exit is never blocked by
the kill switch, a CIO halt, the daily-loss limit or a dead RiskAgent. Only
the oversell guard and an explicit limit-price sanity band can stop a SELL.

ALPACA is the source of truth: on startup and every ``broker_sync_interval_sec``
the local ledger is overwritten from the broker's positions/cash/equity and every
difference is written to ``alert_history`` + raised as a CRITICAL RISK_ALERT.
There is no fallback to the simulator: unreachable broker => BUYs refused.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.trading.alpaca_broker import (
    TERMINAL_STATUSES,
    AlpacaBroker,
    is_us_equity,
)
from app.agents.front_office.trading.order_manager import OrderManager
from app.agents.front_office.trading.paper_broker import PaperBroker
from app.agents.front_office.trading.polymarket_broker import PolymarketBroker
from app.config import settings
from app.core.cash import adjust_cash, get_cash, mirror_to_kv, set_cash
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()


logger = get_logger("agent.execution")

_INDIAN = ("NSE", "BSE")
# Alpaca lists most ETFs on ARCA; the local symbol convention is SPY.NYSE.
_ALPACA_EXCHANGE_TO_LOCAL = {"ARCA": "NYSE", "AMEX": "NYSE", "BATS": "NYSE", "NYSEARCA": "NYSE"}


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


def _is_indian(symbol: str, exchange: str) -> bool:
    return exchange.upper() in _INDIAN or symbol.endswith((".NSE", ".BSE", ".NS", ".BO"))


class ExecutionAgent(BaseAgent):
    """Routes orders to the configured broker and keeps the local book honest.

    Subscribes to:
      - ``horizon.execution.order.*``
      - ``horizon.executive.cio``

    Publishes:
      - ``horizon.execution.order.fill``   -- after a booked fill
      - ``horizon.execution.order.update`` -- rejections / cancellations
      - ``horizon.risk.alert``             -- broker sync / stop lifecycle events
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
        # ALPACA: did the broker answer the last sync? False refuses BUYs.
        # Exits are still attempted (the broker may be back by then).
        self._broker_ok: bool = self.broker_name != "ALPACA"
        self._last_broker_sync: float = 0.0
        # symbol -> monotonic time of the last broker-stop placement attempt
        # (throttles re-tries when Alpaca keeps rejecting the stop).
        self._stop_attempt_at: dict[str, float] = {}

    def _resolve_broker(self) -> tuple[object | None, str]:
        """Pick the session broker once at startup.

        PAPER only when EXECUTION_BROKER=PAPER. With ALPACA configured but the
        safety guard failing (live URL, missing keys, paper_mode=false) there
        is NO broker: every order is refused. The simulator is never a silent
        stand-in for a real-broker configuration.
        """
        wanted = settings.execution_broker.upper()
        if wanted == "ALPACA":
            if _alpaca_guard_ok():
                return self.alpaca_broker, "ALPACA"
            logger.error(
                "alpaca_guard_failed_no_broker",
                has_key=bool(settings.alpaca_api_key),
                has_secret=bool(settings.alpaca_api_secret),
                paper_mode=settings.alpaca_paper_mode,
                base_url=settings.alpaca_base_url,
                action="all orders refused until the configuration is fixed",
            )
            return None, "NONE"
        if wanted != "PAPER":
            logger.error("unknown_execution_broker", value=settings.execution_broker)
            return None, "NONE"
        return self.paper_broker, "PAPER"

    def _broker_for(self, symbol: str, exchange: str = "") -> tuple:
        """Per-order broker routing.

        .POLY never touches Alpaca. NSE/BSE never touch Alpaca either: the
        bare ticker would be the NYSE ADR in USD (``INFY.NSE`` -> ``INFY``)
        while the book records INR. No Indian adapter exists yet, so those
        orders are refused outright under ALPACA.
        """
        if symbol.endswith(".POLY"):
            if _polymarket_guard_ok():
                return self.polymarket_broker, "POLYMARKET"
            if self.broker_name == "ALPACA":
                # Never book a simulated fill next to real ones (audit B6).
                return None, "UNROUTABLE_SIM"
            return self.paper_broker, "PAPER"
        if self.broker_name == "ALPACA" and _is_indian(symbol, exchange):
            return None, "UNROUTABLE"
        return self.broker, self.broker_name

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.order.new", self.on_message)
        await self.bus.subscribe("horizon.execution.order.pending", self.on_message)
        await self.bus.subscribe("horizon.execution.order.cancel", self.on_message)
        await self.bus.subscribe("horizon.executive.cio", self.on_message)

    async def run(self) -> None:
        """Sync from the broker at startup, then poll orders / stops / sync."""
        await self._rehydrate_pending()

        if self.broker_name == "ALPACA":
            try:
                await self._sync_from_broker()
            except Exception as exc:
                logger.error("broker_sync_error", error=str(exc))

        while self._running:
            try:
                await self._poll_open_orders()
                if self.broker_name == "ALPACA":
                    await self._poll_broker_stops()
                    elapsed = asyncio.get_event_loop().time() - self._last_broker_sync
                    if elapsed >= settings.broker_sync_interval_sec:
                        await self._sync_from_broker()
            except Exception as exc:
                logger.error("execution_loop_error", error=str(exc))
            await asyncio.sleep(5)

    # ------------------------------------------------------------------ #
    # Broker = source of truth
    # ------------------------------------------------------------------ #

    async def _sync_from_broker(self) -> bool:
        """Overwrite local positions / USD cash / NAV from Alpaca.

        Returns True when the broker answered. Every difference is written to
        ``alert_history`` (durable, never pruned) and raised as one CRITICAL
        RISK_ALERT. Skips the ledger overwrite while local ALPACA orders are
        still in flight -- a fill the poller has not booked yet would otherwise
        be counted twice (once by the sync, once by the poll).
        """
        self._last_broker_sync = asyncio.get_event_loop().time()
        account = await self.alpaca_broker.get_account()
        broker_positions = None if account is None else await self.alpaca_broker.get_positions()
        if account is None or broker_positions is None:
            was_ok = self._broker_ok
            self._broker_ok = False
            logger.error("alpaca_unreachable", action="BUYs refused; exits still attempted")
            if was_ok:
                await self.emit(
                    channel="horizon.risk.alert",
                    message_type=MessageType.RISK_ALERT,
                    payload={
                        "reason": "alpaca_unreachable",
                        "action": "BUYs refused until the broker answers; "
                                  "exits still attempted; retrying",
                        "severity": "CRITICAL",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            return False
        if not self._broker_ok:
            logger.info("alpaca_reachable_again")
        self._broker_ok = True

        equity = float(account.get("equity", 0) or 0)
        broker_cash = float(account.get("cash", 0) or 0)
        if equity > 0:
            kv = _get_kv()
            # Broker equity is the NAV of a real session: PortfolioAgent's
            # snapshots (and with them daily-loss + the drawdown kill switch)
            # read it from here instead of the local mark-to-market. Written
            # before the in-flight check below -- equity cannot double-count.
            await kv.set("horizon:portfolio:nav", str(equity))
            await kv.set("horizon:broker:equity", str(equity))
            await kv.set("horizon:broker:equity:ts", datetime.now(UTC).isoformat())

        # Settle anything we already know about before comparing books.
        stuck_rows = await self._open_alpaca_rows()
        for row in stuck_rows:
            await self._poll_alpaca_order(row)
        if await self._open_alpaca_rows():
            logger.info("broker_sync_deferred_orders_in_flight")
            return True

        diffs: list[dict] = []
        broker_by_key = {self._broker_key(p): p for p in broker_positions}

        async with _get_session_factory()() as session:
            result = await session.execute(text(
                "SELECT id, symbol, exchange, quantity, avg_entry_price, currency"
                " FROM positions WHERE quantity != 0"
            ))
            local_rows = result.fetchall()
            seen: set[str] = set()
            now = datetime.now(UTC)
            for row in local_rows:
                if row.symbol.endswith(".POLY") or _is_indian(row.symbol, row.exchange):
                    continue  # never routed to Alpaca -> not the broker's to know
                key = self._broker_key({"symbol": row.symbol.split(".")[0]
                                        if not row.symbol.endswith(("-USD", "-USDT"))
                                        else row.symbol})
                seen.add(key)
                bp = broker_by_key.get(key)
                bq = float(bp["qty"]) if bp else 0.0
                if abs(bq - float(row.quantity)) <= 1e-6:
                    continue
                diffs.append({"kind": "position", "symbol": row.symbol,
                              "local_qty": float(row.quantity), "broker_qty": bq})
                if bp:
                    await session.execute(text(
                        "UPDATE positions SET quantity = :q, avg_entry_price = :avg,"
                        " current_price = :px, side = 'LONG',"
                        " high_water_mark = COALESCE(high_water_mark, :px),"
                        " updated_at = :now WHERE id = :id"
                    ), {"q": bq, "avg": bp["avg_entry"], "px": bp["current_price"],
                        "now": now, "id": row.id})
                else:
                    await session.execute(text(
                        "UPDATE positions SET quantity = 0, side = 'FLAT',"
                        " stop_loss_price = NULL, high_water_mark = NULL,"
                        " stop_order_id = NULL, updated_at = :now WHERE id = :id"
                    ), {"now": now, "id": row.id})
            for key, bp in broker_by_key.items():
                if key in seen or float(bp["qty"]) <= 0:
                    continue
                symbol, exchange = self._local_symbol(bp)
                diffs.append({"kind": "position", "symbol": symbol,
                              "local_qty": 0.0, "broker_qty": float(bp["qty"])})
                # A flat row for this symbol may exist (UNIQUE symbol/exchange).
                existing = (await session.execute(text(
                    "SELECT id FROM positions WHERE symbol = :s AND exchange = :e"
                ), {"s": symbol, "e": exchange})).fetchone()
                if existing:
                    await session.execute(text(
                        "UPDATE positions SET quantity = :q, avg_entry_price = :avg,"
                        " current_price = :px, side = 'LONG', high_water_mark = :px,"
                        " stopped_out = NULL, updated_at = :now WHERE id = :id"
                    ), {"q": bp["qty"], "avg": bp["avg_entry"], "px": bp["current_price"],
                        "now": now, "id": existing.id})
                else:
                    await session.execute(text(
                        "INSERT INTO positions (id, symbol, exchange, side, quantity,"
                        " avg_entry_price, current_price, currency, high_water_mark,"
                        " created_at, updated_at) VALUES (:id, :s, :e, 'LONG', :q, :avg,"
                        " :px, 'USD', :px, :now, :now)"
                    ), {"id": str(uuid.uuid4()), "s": symbol, "e": exchange,
                        "q": bp["qty"], "avg": bp["avg_entry"],
                        "px": bp["current_price"], "now": now})
            local_cash = await get_cash(session, "USD")
            if abs(local_cash - broker_cash) > 0.01:
                diffs.append({"kind": "cash", "currency": "USD",
                              "local": local_cash, "broker": broker_cash})
                await set_cash(session, "USD", broker_cash)
            if diffs:
                await session.execute(text(
                    "INSERT INTO alert_history (id, rule_name, severity, title, message,"
                    " channels, payload, created_at) VALUES (:id, 'broker_sync', 'CRITICAL',"
                    " :title, :msg, '[]', :payload, :now)"
                ), {"id": str(uuid.uuid4()),
                    "title": f"Broker sync overwrote {len(diffs)} local value(s)",
                    "msg": json.dumps(diffs, default=str)[:2000],
                    "payload": json.dumps({"diffs": diffs, "equity": equity}, default=str),
                    "now": now})
            await session.commit()

        await mirror_to_kv("USD", broker_cash)

        if diffs:
            logger.error("broker_sync_overwrote_local", diffs=diffs, equity=equity)
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "broker_sync_overwrote_local",
                    "diffs": diffs,
                    "broker_equity": equity,
                    "broker_cash": broker_cash,
                    "action": "local ledger replaced by the broker's; review alert_history",
                    "severity": "CRITICAL",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        else:
            logger.info("alpaca_sync_ok", equity=equity, cash=broker_cash,
                        positions=len(broker_positions))
        return True

    @staticmethod
    def _broker_key(p: dict) -> str:
        return str(p["symbol"]).upper()

    @staticmethod
    def _local_symbol(bp: dict) -> tuple[str, str]:
        """Map a broker-only position onto the local ``BASE.EXCHANGE`` convention."""
        base = str(bp["symbol"]).upper()
        if bp.get("asset_class") == "crypto" or base.endswith(("-USD", "-USDT")):
            return base, "CRYPTO"
        from app.data_layer.universe import _ANCHORS
        known = list(_ANCHORS) + [s.strip() for s in settings.us_symbols.split(",") if s.strip()]
        for s in known:
            if s.split(".")[0].upper() == base:
                return s, s.split(".", 1)[1]
        exch = str(bp.get("exchange") or "NASDAQ").upper()
        exch = _ALPACA_EXCHANGE_TO_LOCAL.get(exch, exch)
        return f"{base}.{exch}", exch

    async def _open_alpaca_rows(self) -> list:
        async with _get_session_factory()() as session:
            result = await session.execute(
                text("""
                    SELECT id, symbol, exchange, side, quantity, stop_price,
                           broker_order_id, strategy_name, created_at
                    FROM orders
                    WHERE status IN ('OPEN', 'PARTIAL') AND broker = 'ALPACA'
                    ORDER BY created_at ASC
                    LIMIT 50
                """)
            )
            return result.fetchall()

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #

    async def on_message(self, message: AgentMessage) -> None:
        """Handle new order requests, approval/rejection and CIO overrides."""
        if message.message_type == MessageType.CIO_OVERRIDE:
            actions = message.payload.get("actions", []) or []
            kv = _get_kv()
            if "HALT" in actions:
                # Persisted in the same key the kill switch uses, so a restart
                # comes back halted and the UI shows it. Blocks BUYs only.
                self._cio_halt_active = True
                await kv.set("horizon:system:halted", "1")
                await kv.set("horizon:system:halt_reason",
                             f"CIO HALT {message.payload.get('override_id', '')}")
                logger.warning("execution_cio_halt_active",
                               override_id=message.payload.get("override_id"))
            elif "RESUME" in actions:
                self._cio_halt_active = False
                await kv.set("horizon:system:halted", "0")
                await kv.set("horizon:system:halt_reason", "")
                logger.info("execution_cio_halt_cleared",
                            override_id=message.payload.get("override_id"))
            return

        if (
            self._cio_halt_active
            and message.message_type == MessageType.ORDER_NEW
            and str(message.payload.get("side", "BUY")).upper() != "SELL"
        ):
            order_id = message.payload.get("order_id", "")
            logger.warning("execution_buy_blocked_by_cio_halt", order_id=order_id,
                           symbol=message.payload.get("symbol"))
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
        """Turn an ORDER_NEW into an order row and execute (or buffer) it."""
        payload = message.payload
        symbol = payload["symbol"]
        exchange = payload.get("exchange", "")
        side = str(payload["side"]).upper()
        broker, broker_name = self._broker_for(symbol, exchange)

        qty_requested = float(payload["quantity"])
        qty = qty_requested
        if broker_name == "ALPACA" and side == "BUY" and is_us_equity(symbol, exchange):
            # Whole shares so the protective stop can rest at the broker
            # (Alpaca: fractional qty is market/limit DAY only).
            qty = float(int(qty))

        alloc = float(payload.get("allocation_usd") or 0.0)
        order_data = {
            "symbol": symbol,
            "exchange": exchange,
            "order_type": payload.get("order_type", "MARKET"),
            "side": side,
            "quantity": qty,
            "limit_price": payload.get("limit_price"),
            "stop_price": payload.get("stop_price"),
            "signal_id": payload.get("signal_id"),
            "debate_id": payload.get("debate_id"),
            "strategy_name": payload.get("strategy_name"),
            "stop_loss": payload.get("stop_loss"),
            # Price the producer sized at -- the fat-finger band compares it
            # with the last trade before a BUY goes out.
            "ref_price": (alloc / qty_requested) if alloc > 0 and qty_requested > 0 else None,
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

        if broker is None:
            if broker_name == "UNROUTABLE":
                reason = (f"No broker adapter for exchange {exchange or '?'} "
                          f"({symbol}): Alpaca is US-only")
            elif broker_name == "UNROUTABLE_SIM":
                reason = (f"Simulator fills are not allowed in a real-broker session "
                          f"({symbol} needs POLYMARKET_REAL_TRADING + wallet)")
                await self.emit(
                    channel="horizon.risk.alert",
                    message_type=MessageType.RISK_ALERT,
                    payload={"reason": "simulator_order_refused", "symbol": symbol,
                             "side": side, "quantity": qty, "severity": "HIGH",
                             "timestamp": datetime.now(UTC).isoformat()},
                )
            else:
                reason = (f"No execution broker: EXECUTION_BROKER={settings.execution_broker}"
                          " failed the safety guard")
            await self._reject(order, reason)
            return
        if qty <= 0:
            await self._reject(order, f"Quantity {qty_requested} rounds to 0 whole shares")
            return

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
            await self._reject(order, f"Atomic fill rollback: {type(exc).__name__}")
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

    # ------------------------------------------------------------------ #
    # Pre-trade guards + execution
    # ------------------------------------------------------------------ #

    async def _reject(self, order: dict, reason: str) -> None:
        """Mark REJECTED and tell the bus (symbol/side included so the
        portfolio agent can clear its qty de-dup for this (symbol, side))."""
        await self.order_manager.update_status(
            order["id"], "REJECTED", rejection_reason=reason,
        )
        await self.emit(
            channel="horizon.execution.order.update",
            message_type=MessageType.ORDER_CANCEL,
            payload={
                "order_id": order["id"],
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "status": "REJECTED",
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        logger.warning("order_rejected", order_id=order["id"], symbol=order.get("symbol"),
                       side=order.get("side"), reason=reason)

    async def _last_price(self, symbol: str) -> float:
        kv = _get_kv()
        base = symbol.split(".")[0] if "." in symbol else symbol
        for key in (f"horizon:price:{symbol}", f"horizon:price:{base}"):
            raw = await kv.get(key)
            if raw:
                try:
                    px = float(raw)
                    if px > 0:
                        return px
                except (TypeError, ValueError):
                    pass
        return 0.0

    async def _check_buy_guards(self, order: dict, broker_name: str) -> str | None:
        """Every BUY gate in one place. Returns a rejection reason or None."""
        symbol, exchange = order["symbol"], order.get("exchange", "")
        qty = float(order["quantity"])
        kv = _get_kv()

        if await kv.get("horizon:system:halted") == "1":
            return "System halted — kill switch active"
        if broker_name == "ALPACA" and not self._broker_ok:
            return "Alpaca unreachable — BUY refused until the broker sync succeeds"

        last = await self._last_price(symbol)
        band = float(settings.risk_price_band_pct or 0.0)
        ref = order.get("ref_price") or order.get("limit_price")
        if band > 0 and last > 0 and ref:
            dev = abs(float(ref) - last) / last * 100.0
            if dev > band:
                return (f"Price band: sized at {float(ref):.4f}, last {last:.4f} "
                        f"({dev:.1f}% > {band:.1f}%)")

        px = last or (float(ref) if ref else 0.0)
        notional = px * qty
        nav_raw = await kv.get("horizon:portfolio:nav")
        nav = float(nav_raw) if nav_raw else 0.0
        if nav > 0 and notional > 0:
            cap = float(settings.risk_max_order_notional_pct or 0.0)
            if cap > 0 and notional > nav * cap / 100.0:
                return (f"Notional cap: ${notional:,.0f} > {cap:.0f}% of NAV "
                        f"(${nav:,.0f})")
            held = await self._held_qty(symbol, exchange)
            post_pct = (held * px + notional) / nav * 100.0
            # 50 bps tolerance: sizing targets the cap exactly and prices move
            # between sizing and execution.
            if post_pct > settings.risk_max_position_pct + 0.5:
                return (f"Position cap: {post_pct:.1f}% of NAV after fill > "
                        f"{settings.risk_max_position_pct:.0f}%")
            # Gross leverage after the order (audit M8): the broker's margin
            # buying power must never be used by accident.
            max_lev = float(settings.risk_max_leverage or 0.0)
            if max_lev > 0:
                gross = await self._gross_exposure_usd()
                lev = (gross + notional) / nav
                if lev > max_lev + 0.005:
                    return (f"Leverage cap: gross {lev:.2f}x NAV after fill > "
                            f"{max_lev:.2f}x")

        # Hard cash guard in the instrument's currency -- INR for NSE/BSE too.
        if notional > 0:
            currency = "INR" if exchange in _INDIAN else "USD"
            try:
                async with _get_session_factory()() as s:
                    cash = await get_cash(s, currency)
            except Exception as exc:
                logger.error("cash_guard_error", order_id=order["id"], error=str(exc))
                return None
            if notional > max(cash, 0.0):
                sym = "₹" if currency == "INR" else "$"
                return f"Insufficient cash: need {sym}{notional:,.0f}, have {sym}{cash:,.0f}"
        return None

    async def _execute_order(self, order: dict) -> None:
        """Run the guards, send to the broker, book the result."""
        order_id = order["id"]
        side = str(order.get("side", "")).upper()
        symbol, exchange = order["symbol"], order.get("exchange", "")
        broker, broker_name = self._broker_for(symbol, exchange)

        if broker is None:
            await self._reject(order, f"No broker for {symbol} ({broker_name})")
            return

        if side == "BUY":
            reason = await self._check_buy_guards(order, broker_name)
            if reason:
                await self._reject(order, reason)
                return
        elif side == "SELL":
            # Reduce-only: never more than the long we hold. This is the ONLY
            # gate on an exit (plus an explicit limit price sanity check).
            qty = float(order["quantity"])
            held = await self._held_qty(symbol, exchange)
            if held <= 0:
                await self._reject(order, "No open position to sell (naked short blocked)")
                return
            if qty > held + 1e-9:
                await self._reject(order, f"SELL {qty:g} exceeds held {held:g} (reduce-only)")
                return
            band = float(settings.risk_price_band_pct or 0.0)
            if band > 0 and order.get("limit_price"):
                last = await self._last_price(symbol)
                lp = float(order["limit_price"])
                if last > 0 and abs(lp - last) / last * 100.0 > band:
                    await self._reject(
                        order, f"Price band: limit {lp:.4f} vs last {last:.4f} > {band:.1f}%",
                    )
                    return
            if broker_name == "ALPACA":
                # Free the shares: a resting trailing stop reserves them and the
                # SELL would come back "insufficient qty". If the stop fired
                # meanwhile, book it and re-check what is left.
                await self._release_broker_stop(symbol, exchange)
                held = await self._held_qty(symbol, exchange)
                if held <= 0:
                    await self._reject(order, "Position already closed by the broker stop")
                    return
                if qty > held + 1e-9:
                    await self._reject(order, f"SELL {qty:g} exceeds held {held:g} after stop fill")
                    return
                broker_qty = await self.alpaca_broker.get_position_qty(symbol)
                if broker_qty is not None and qty > broker_qty + 1e-9:
                    await self._reject(
                        order, f"SELL {qty:g} exceeds broker position {broker_qty:g}",
                    )
                    # The local row is a phantom (or stale): resync from the
                    # broker now so the next 30s stop re-fire sees the truth
                    # instead of rejecting forever (audit B6).
                    await self._sync_from_broker()
                    await self._sync_broker_stop(symbol, exchange)
                    return

        await self.order_manager.update_status(order_id, "OPEN")

        fill = None
        for attempt in range(3):
            fill = await broker.execute(order)
            if fill is not None:
                break
            # Only retry the paper broker. A live order that returned None may
            # have already been accepted by the broker before the connection
            # dropped — a blind re-POST would double-fire. Live retries go
            # through the client_order_id lookup below instead.
            if broker_name != "PAPER":
                break
            if attempt < 2:
                logger.warning("broker_retry", order_id=order_id, attempt=attempt + 1)
                await asyncio.sleep(2 ** attempt)

        if fill is None and broker_name == "ALPACA":
            # Ambiguous POST (timeout after acceptance?): ask by our id.
            found = await self.alpaca_broker.get_order_by_client_id(order_id)
            if found is None:
                logger.error("alpaca_order_outcome_unknown", order_id=order_id,
                             action="left OPEN; poller resolves by client_order_id")
                await self.emit(
                    channel="horizon.risk.alert",
                    message_type=MessageType.RISK_ALERT,
                    payload={
                        "reason": "alpaca_order_outcome_unknown",
                        "order_id": order_id, "symbol": symbol, "side": side,
                        "severity": "HIGH",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                return
            if found.get("found"):
                logger.warning("alpaca_order_recovered_by_client_id", order_id=order_id,
                               broker_order_id=found["broker_order_id"],
                               status=found["status"])
                fill = {
                    "broker_order_id": found["broker_order_id"],
                    "filled_qty": found["filled_qty"],
                    "fill_price": found["filled_avg_price"],
                    "commission": 0.0, "slippage": 0.0,
                    "alpaca_status": found["status"],
                    "rejected": found["status"] == "rejected",
                    "rejection_reason": "Alpaca rejected the order",
                }

        if fill is None or fill.get("rejected"):
            reason = (fill or {}).get("rejection_reason", "Broker returned no fill")
            await self._reject(order, reason)
            if side == "SELL" and broker_name == "ALPACA":
                await self._sync_broker_stop(symbol, exchange)  # re-arm
            return

        # Alpaca orders aren't filled instantly. If the broker accepted the
        # order but hasn't returned a COMPLETE fill (filled_qty < quantity —
        # this covers 0 and any partial), persist the broker_order_id and
        # leave it OPEN for _poll_open_orders to settle from Alpaca's final
        # cumulative fill.
        if broker_name == "ALPACA" and float(fill.get("filled_qty") or 0) < float(
            order.get("quantity", 0)
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
        """Atomically book a fill: fill row + status + position + cash.

        ``fill["filled_qty"]`` is CUMULATIVE for the order (Alpaca reports it
        that way; PaperBroker fills in one shot). Only the delta over what is
        already booked is recorded, so a partial followed by the final report,
        or a partial followed by a cancel, books every share exactly once.
        Re-checks the order's DB status inside the per-symbol lock so a race
        between the instant and polling paths cannot double-settle.
        """
        order_id = order["id"]
        side = order["side"]
        cumulative = float(fill["filled_qty"])
        price = float(fill["fill_price"])
        commission = float(fill.get("commission", 0.0))
        slippage = float(fill.get("slippage", 0.0))
        exchange = order.get("exchange", "")
        currency = "INR" if exchange in _INDIAN else "USD"
        order_qty = float(order.get("quantity", 0))
        is_stop = order.get("strategy_name") == "stop_loss"

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
                    booked = (await session.execute(
                        text("SELECT COALESCE(SUM(filled_qty), 0) FROM fills"
                             " WHERE order_id = :oid"), {"oid": order_id},
                    )).scalar()
                    qty = cumulative - float(booked or 0.0)
                    if qty <= 1e-9:
                        logger.info("settle_fill_noop_nothing_new", order_id=order_id,
                                    cumulative=cumulative)
                        return
                    new_status = "FILLED" if cumulative >= order_qty - 1e-9 else "PARTIAL"
                    cost = qty * price
                    delta = -(cost + commission) if side == "BUY" else (cost - commission)
                    await self.order_manager.record_fill(
                        order_id=order_id,
                        qty=qty,
                        price=price,
                        commission=commission,
                        slippage=slippage,
                        broker=order.get("broker"),
                        session=session,
                    )
                    if current_status != new_status:
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
                        stopped_out=is_stop,
                        broker=order.get("broker"),
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
                "exchange": exchange,
                "side": side,
                "filled_qty": qty,
                "fill_price": price,
                "commission": commission,
                "slippage": slippage,
                "broker": order.get("broker", self.broker_name),
                "strategy_name": order.get("strategy_name"),
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

        if order.get("broker") == "ALPACA":
            await self._sync_broker_stop(order["symbol"], exchange)

    # ------------------------------------------------------------------ #
    # Broker-side trailing stop lifecycle (ALPACA, US equities, whole shares)
    # ------------------------------------------------------------------ #

    def _stop_enabled(self, symbol: str, exchange: str) -> bool:
        return (
            self.broker_name == "ALPACA"
            and float(settings.stop_loss_trail_pct or 0.0) > 0
            and is_us_equity(symbol, exchange)
        )

    async def _sync_broker_stop(self, symbol: str, exchange: str) -> None:
        """Make the resting stop match the position: cancel/replace for the
        current whole-share qty, or nothing when flat. Alerts when a position
        is left without a broker stop (the worker is then the only layer)."""
        if not self._stop_enabled(symbol, exchange):
            return
        pos = await self.order_manager.get_position(symbol, exchange)
        qty = float(pos.quantity) if pos else 0.0
        if pos and pos.stop_order_id:
            final = await self.alpaca_broker.cancel_and_wait(pos.stop_order_id)
            if final and final.get("status") == "filled":
                await self._book_broker_stop_fill(symbol, exchange, final)
                return  # the booking re-enters here with the new qty
            await self.order_manager.set_stop_order_id(symbol, exchange, None)
        whole = int(qty)
        if whole < 1:
            return
        self._stop_attempt_at[symbol] = asyncio.get_event_loop().time()
        placed = await self.alpaca_broker.place_trailing_stop(
            symbol, whole, settings.stop_loss_trail_pct,
            client_order_id=f"stop-{uuid.uuid4().hex[:24]}",
        )
        if placed is None:
            logger.error("broker_stop_missing", symbol=symbol, qty=whole)
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "broker_stop_missing",
                    "symbol": symbol, "qty": whole,
                    "action": "PositionMonitorWorker is the only stop layer; retrying",
                    "severity": "HIGH",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            return
        await self.order_manager.set_stop_order_id(symbol, exchange, placed["broker_order_id"])
        logger.info("broker_stop_armed", symbol=symbol, qty=whole,
                    broker_order_id=placed["broker_order_id"],
                    trail_pct=settings.stop_loss_trail_pct)

    async def _release_broker_stop(self, symbol: str, exchange: str) -> None:
        """Cancel the resting stop before a strategy/manual SELL on the symbol."""
        pos = await self.order_manager.get_position(symbol, exchange)
        if not pos or not pos.stop_order_id:
            return
        final = await self.alpaca_broker.cancel_and_wait(pos.stop_order_id)
        if final and final.get("status") == "filled":
            await self._book_broker_stop_fill(symbol, exchange, final)
            return
        if final and float(final.get("filled_qty") or 0) > 0:
            await self._book_broker_stop_fill(symbol, exchange, final)
        await self.order_manager.set_stop_order_id(symbol, exchange, None)

    async def _book_broker_stop_fill(self, symbol: str, exchange: str, status: dict) -> None:
        """Book a broker-side stop execution locally exactly once.

        The local order row is keyed by the stop's broker_order_id, so repeated
        polls (or a restart between poll and booking) find the same row and
        ``_settle_fill``'s cumulative-delta logic books nothing twice.
        """
        boid = status.get("broker_order_id")
        if not boid:
            return
        async with _get_session_factory()() as session:
            row = (await session.execute(
                text("SELECT id, quantity, status FROM orders WHERE broker_order_id = :b"),
                {"b": boid},
            )).fetchone()
        if row is None:
            qty = float(status.get("qty") or status.get("filled_qty") or 0)
            order = await self.order_manager.create_order({
                "symbol": symbol, "exchange": exchange, "order_type": "TRAILING_STOP",
                "side": "SELL", "quantity": qty, "broker": "ALPACA",
                "mode": settings.system_mode.value, "strategy_name": "stop_loss",
            })
            await self.order_manager.update_status(order["id"], "OPEN")
            await self.order_manager.set_broker_order_id(order["id"], boid)
        else:
            order = {"id": row.id, "symbol": symbol, "exchange": exchange, "side": "SELL",
                     "quantity": float(row.quantity), "broker": "ALPACA",
                     "strategy_name": "stop_loss"}
        filled_qty = float(status.get("filled_qty") or 0)
        price = float(status.get("filled_avg_price") or 0)
        if filled_qty > 0 and price > 0:
            logger.warning("broker_stop_filled", symbol=symbol, qty=filled_qty, price=price,
                           broker_order_id=boid)
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "reason": "broker_stop_filled", "symbol": symbol,
                    "qty": filled_qty, "price": price, "broker_order_id": boid,
                    "severity": "HIGH", "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            # Clear first: _settle_fill -> _sync_broker_stop must not cancel
            # the already-filled stop again.
            await self.order_manager.set_stop_order_id(symbol, exchange, None)
            await self._settle_fill(order, {
                "filled_qty": filled_qty, "fill_price": price,
                "commission": 0.0, "slippage": 0.0,
            })
        if status.get("status") in TERMINAL_STATUSES:
            await self.order_manager.set_stop_order_id(symbol, exchange, None)
            if status.get("status") != "filled":
                await self.order_manager.update_status(
                    order["id"], "CANCELLED",
                    rejection_reason=f"Alpaca reported status={status.get('status')}",
                )

    async def _poll_broker_stops(self) -> None:
        """Detect broker-side stop fills/cancels; arm stops that are missing."""
        async with _get_session_factory()() as session:
            rows = (await session.execute(text(
                "SELECT symbol, exchange, quantity, stop_order_id FROM positions"
                " WHERE quantity > 0 AND side = 'LONG'"
            ))).fetchall()
        now = asyncio.get_event_loop().time()
        for row in rows:
            if not self._stop_enabled(row.symbol, row.exchange):
                continue
            if row.stop_order_id:
                try:
                    st = await self.alpaca_broker.get_order_status(row.stop_order_id)
                except Exception as exc:
                    logger.error("broker_stop_poll_error", symbol=row.symbol, error=str(exc))
                    continue
                if st is None:
                    continue
                s = st.get("status")
                if s == "filled" or (s == "partially_filled" and st.get("filled_qty")):
                    await self._book_broker_stop_fill(row.symbol, row.exchange, st)
                elif s in TERMINAL_STATUSES:
                    logger.error("broker_stop_gone", symbol=row.symbol, status=s)
                    await self.order_manager.set_stop_order_id(row.symbol, row.exchange, None)
                    await self._sync_broker_stop(row.symbol, row.exchange)
            elif now - self._stop_attempt_at.get(row.symbol, 0.0) >= 60:
                await self._sync_broker_stop(row.symbol, row.exchange)

    # ------------------------------------------------------------------ #
    # Order polling
    # ------------------------------------------------------------------ #

    async def _poll_open_orders(self) -> None:
        """Cancel stale PAPER orders; poll and settle open ALPACA orders.

        Paper broker fills are instant, so any PAPER order still OPEN after
        60s is stuck due to an error — cancel it (re-executing without
        position/cash updates would cause infinite fills). Alpaca orders can
        legitimately sit OPEN for hours (market closed, limit not touched),
        so those are only force-cancelled after 24h; otherwise we just poll
        their live status. ALPACA orders with no broker_order_id yet (the POST
        timed out) are resolved by client_order_id first.
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

        for row in await self._open_alpaca_rows():
            await self._poll_alpaca_order(row)

    async def _poll_alpaca_order(self, row) -> None:  # noqa: ANN001
        """Poll one Alpaca order's status and settle/cancel as appropriate."""
        order_id = str(row.id)
        broker_order_id = row.broker_order_id
        strategy_name = getattr(row, "strategy_name", None)
        order = {
            "id": order_id,
            "symbol": row.symbol,
            "exchange": row.exchange,
            "side": row.side,
            "quantity": float(row.quantity),
            "stop_loss": None,
            "strategy_name": strategy_name,
            "broker": "ALPACA",
        }
        try:
            if not broker_order_id:
                found = await self.alpaca_broker.get_order_by_client_id(order_id)
                if found is None:
                    return  # unreachable; try again next cycle
                if not found.get("found"):
                    await self._reject(order, "Not found at Alpaca after an ambiguous POST")
                    if row.side == "SELL":
                        await self._sync_broker_stop(row.symbol, row.exchange)
                    return
                broker_order_id = found["broker_order_id"]
                await self.order_manager.set_broker_order_id(order_id, broker_order_id)
                status = found
            else:
                status = await self.alpaca_broker.get_order_status(broker_order_id)
        except Exception as exc:
            logger.error("alpaca_poll_error", order_id=order_id, error=str(exc))
            return

        if status is None:
            return

        alpaca_status = status.get("status")
        filled_qty = float(status.get("filled_qty") or 0)
        fill_price = float(status.get("filled_avg_price") or 0)
        fill = {"filled_qty": filled_qty, "fill_price": fill_price,
                "commission": 0.0, "slippage": 0.0}

        if filled_qty > 0 and fill_price <= 0:
            # API edge case: reported filled but no price yet. Never settle
            # at price 0 — wait for the next poll cycle to see a real price.
            logger.error(
                "alpaca_filled_without_price", order_id=order_id, filled_qty=filled_qty,
            )
            return
        if alpaca_status == "filled" and filled_qty > 0:
            await self._settle_fill(order, fill)
        elif alpaca_status == "partially_filled" and filled_qty > 0:
            await self._settle_fill(order, fill)  # books the delta, stays PARTIAL
        elif alpaca_status in ("canceled", "rejected", "expired", "replaced"):
            if filled_qty > 0:
                # Partial fill then cancel/expiry: the shares exist. Book them,
                # THEN close the order.
                await self._settle_fill(order, fill)
            await self.order_manager.update_status(
                order_id, "CANCELLED",
                rejection_reason=f"Alpaca reported status={alpaca_status}",
            )
            await self.emit(
                channel="horizon.execution.order.update",
                message_type=MessageType.ORDER_CANCEL,
                payload={
                    "order_id": order_id,
                    "symbol": row.symbol,
                    "side": row.side,
                    "status": "CANCELLED",
                    "filled_qty": filled_qty,
                    "reason": f"Alpaca reported status={alpaca_status}",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning(
                "alpaca_order_cancelled", order_id=order_id, alpaca_status=alpaca_status,
                filled_qty=filled_qty,
            )
            if row.side == "SELL" and filled_qty <= 0:
                await self._sync_broker_stop(row.symbol, row.exchange)  # re-arm
        elif alpaca_status not in ("new", "accepted", "pending_new", "partially_filled",
                                   "pending_cancel", "pending_replace", "done_for_day",
                                   "accepted_for_bidding", "calculated", "held"):
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
        if stale and stale.status in ("OPEN", "PARTIAL") and broker_order_id:
            try:
                await self.alpaca_broker.cancel_order(broker_order_id)
            except Exception as exc:
                logger.error("alpaca_cancel_error", order_id=order_id, error=str(exc))
            await self.order_manager.update_status(
                order_id, "CANCELLED",
                rejection_reason="Stale Alpaca order — not filled within 24h",
            )
            logger.warning("stale_alpaca_order_cancelled", order_id=order_id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _held_qty(self, symbol: str, exchange: str) -> float:
        """Long quantity held locally for (symbol, exchange); 0 if none."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT quantity FROM positions"
                    " WHERE symbol = :sym AND exchange = :exch AND side = 'LONG'"
                    " AND quantity > 0 LIMIT 1"
                ),
                {"sym": symbol, "exch": exchange},
            )
            row = result.fetchone()
        return float(row.quantity) if row else 0.0

    async def _has_open_position(self, symbol: str, exchange: str) -> bool:
        """Check if there is an open position for this symbol."""
        return await self._held_qty(symbol, exchange) > 0

    async def _gross_exposure_usd(self) -> float:
        """Sum |qty x mark| over USD positions (INR names are not routed here)."""
        async with _get_session_factory()() as session:
            v = (await session.execute(text(
                "SELECT COALESCE(SUM(ABS(quantity * current_price)), 0) FROM positions"
                " WHERE quantity != 0 AND currency = 'USD'"
            ))).scalar()
        return float(v or 0.0)

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
