"""Portfolio Agent -- capital allocation, position sizing, and NAV tracking."""

import asyncio
import time
import uuid
from datetime import UTC, datetime

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

    Subscribes to:
      - ``horizon.risk.approved.*``  -- risk-gated signals to compute position sizes
      - ``horizon.debate.*``         -- debate conclusions (FULLY_AUTONOMOUS mode)

    Publishes:
      - ``horizon.portfolio.update``  -- after each snapshot refresh
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
        # Buffer for FULLY_AUTONOMOUS: symbol -> (signal_payload, buffered_at)
        self._pending_signals: dict[str, tuple[dict, float]] = {}

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
        if message.message_type == MessageType.RISK_APPROVED:
            await self._handle_signal(message.payload)
        elif message.message_type == MessageType.DEBATE_CONCLUSION:
            await self._handle_debate_conclusion(message.payload)

    async def _handle_signal(self, payload: dict) -> None:
        """Process a risk-approved signal.

        Immediate in PAPER/HUMAN mode, buffered in FULLY_AUTONOMOUS (awaits debate).
        """
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)

        if direction == 0:
            return

        mode = await self._get_mode()
        if mode == "FULLY_AUTONOMOUS":
            # Buffer signal; wait for debate conclusion before sizing
            self._pending_signals[symbol] = (payload, time.monotonic())
            # Prune stale signals (older than 5 minutes)
            now = time.monotonic()
            stale = [s for s, (_, ts) in self._pending_signals.items() if now - ts > 300]
            for s in stale:
                del self._pending_signals[s]
            logger.info("signal_buffered_awaiting_debate", symbol=symbol)
            return

        # PAPER_TRADING or HUMAN_APPROVAL: process immediately
        await self._size_and_emit(payload, debate_id=None)

    async def _handle_debate_conclusion(self, payload: dict) -> None:
        """When debate approves a signal in FULLY_AUTONOMOUS mode, emit ORDER_NEW."""
        decision = payload.get("decision", "").upper()
        symbol = payload.get("symbol", "")
        debate_id = payload.get("session_id")

        if decision != "APPROVED":
            # Discard buffered signal
            self._pending_signals.pop(symbol, None)
            logger.info("signal_rejected_by_debate", symbol=symbol)
            return

        entry = self._pending_signals.pop(symbol, None)
        if entry is None:
            logger.debug("no_buffered_signal_for_debate", symbol=symbol)
            return

        signal_payload, buffered_at = entry
        if time.monotonic() - buffered_at > 300:
            logger.warning("stale_signal_discarded", symbol=symbol)
            return

        await self._size_and_emit(signal_payload, debate_id=debate_id)

    async def _size_and_emit(self, payload: dict, debate_id: str | None) -> None:
        """Compute Kelly sizing and emit ORDER_NEW."""
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)
        strength = payload.get("strength", 0.0)
        exchange = payload.get("exchange", "")

        try:
            sizing = await self._compute_position_size(symbol, direction, strength, exchange)
        except Exception as exc:
            logger.error("sizing_error", symbol=symbol, error=str(exc))
            return

        if sizing["quantity"] <= 0:
            logger.info("zero_size", symbol=symbol)
            return

        await self.emit(
            channel="horizon.execution.order.new",
            message_type=MessageType.ORDER_NEW,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "side": "BUY" if direction > 0 else "SELL",
                "quantity": sizing["quantity"],
                "order_type": "MARKET",
                "signal_id": payload.get("signal_id"),
                "debate_id": debate_id,
                "stop_loss": payload.get("stop_loss"),
                "kelly_fraction": sizing["kelly_f"],
                "allocation_usd": sizing["allocation_usd"],
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "order_sized",
            symbol=symbol,
            side="BUY" if direction > 0 else "SELL",
            qty=sizing["quantity"],
            allocation=sizing["allocation_usd"],
        )

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    async def _compute_position_size(
        self, symbol: str, direction: int, strength: float, exchange: str
    ) -> dict:
        """Determine how many shares/units to trade."""
        # Load current portfolio NAV
        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        nav = await self.currency.compute_unified_nav(cash_usd, cash_inr, positions)

        if nav <= 0:
            return {"quantity": 0.0, "kelly_f": 0.0, "allocation_usd": 0.0}

        # Use strength as a proxy for win-rate (clamped)
        win_rate = max(0.51, min(strength, 0.85))
        # Compute win/loss ratio from recent trades
        try:
            async with _get_session_factory()() as session:
                result = await session.execute(
                    text(
                        "SELECT realized_pnl FROM fills "
                        "WHERE realized_pnl IS NOT NULL "
                        "ORDER BY created_at DESC LIMIT 100"
                    )
                )
                pnls = [float(r[0]) for r in result.fetchall()]
            if pnls:
                wins = [p for p in pnls if p > 0]
                losses = [abs(p) for p in pnls if p < 0]
                avg_win = (
                    sum(wins) / len(wins) if wins else 1.0
                )
                avg_loss = (
                    sum(losses) / len(losses) if losses
                    else 1.0
                )
                win_loss_ratio = max(
                    0.5, min(avg_win / avg_loss, 5.0)
                )
            else:
                win_loss_ratio = 1.5  # default when no history
        except Exception:
            win_loss_ratio = 1.5  # fallback

        kelly_f = self.optimizer.kelly_fraction(win_rate, win_loss_ratio)

        # Get current price from Redis
        price = await self._get_price(symbol)
        if price <= 0:
            return {"quantity": 0.0, "kelly_f": kelly_f, "allocation_usd": 0.0}

        # Compute raw quantity
        qty = self.optimizer.position_size(
            kelly_f=kelly_f,
            portfolio_value=nav,
            price=price,
            max_pct=settings.risk_max_position_pct / 100.0,
        )

        # Apply correlation penalty if we have existing positions
        held_symbols = [p.get("symbol", "") for p in positions if p.get("quantity", 0) != 0]
        if held_symbols:
            # Simplified: use a flat penalty based on number of correlated holdings
            # Full implementation would load a precomputed correlation matrix
            import json as _json

            import numpy as np

            n = len(held_symbols) + 1
            all_symbols = held_symbols + [symbol]

            # Estimate correlation from recent returns data
            try:
                kv = _get_kv()
                returns_data = []
                for sym in all_symbols:
                    hist_str = await kv.get(
                        f"horizon:returns:{sym}"
                    )
                    if hist_str:
                        returns_data.append(
                            _json.loads(hist_str)
                        )
                if (
                    len(returns_data) == n
                    and all(len(r) >= 10 for r in returns_data)
                ):
                    arr = np.array(returns_data)
                    corr = np.corrcoef(arr)
                    # Ensure valid correlation matrix
                    if np.isnan(corr).any():
                        corr = np.eye(n)
                else:
                    corr = np.eye(n)  # insufficient data
            except Exception:
                corr = np.eye(n)  # fallback to no-correlation
            penalty = self.optimizer.correlation_penalty(
                symbol=symbol,
                positions=held_symbols,
                correlation_matrix=corr,
                symbols_index=all_symbols,
            )
            qty *= penalty

        # For equities, round down to whole shares
        if exchange not in ("CRYPTO",):
            qty = float(int(qty))

        allocation_usd = qty * price

        return {
            "quantity": qty,
            "kelly_f": kelly_f,
            "allocation_usd": allocation_usd,
        }

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

        # Publish update
        await self.emit(
            channel="horizon.portfolio.update",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload={
                "total_value": nav,
                "cash_usd": cash_usd,
                "cash_inr": cash_inr,
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

    async def _get_mode(self) -> str:
        """Read current system mode from KV store, falling back to settings."""
        mode = await self.redis.get("horizon:system:mode")
        if mode and mode in ("PAPER_TRADING", "HUMAN_APPROVAL", "FULLY_AUTONOMOUS"):
            return mode
        return settings.system_mode.value
