"""Strategy agent — runs the sleeve-based portfolio on a timer.

The live system uses three documented-edge sleeves (trend filter on SPY,
overnight gap fade on QQQ, cross-sectional momentum across the US universe).
Each sleeve is consulted at its own cadence; between refreshes the cached
target weights are reused. The agent:

1. Fetches daily bars for every symbol (Alpaca primary, yfinance fallback).
2. Publishes TICK messages so the dashboard stays live.
3. During market hours, refreshes sleeve targets + emits SIGNAL messages
   when a sleeve's desired weight for a symbol has changed vs the last
   published target. The portfolio agent turns signals into sized orders.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.strategy.sleeves import (
    BreadthAlphaSleeve,
    MomentumRankSleeve,
    ResearchStackSleeve,
    TrendFilterSleeve,
)
from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger("strategy.agent")

POLL_INTERVAL = 60  # seconds

# Skip emit when weight delta is below this threshold (50 bps). Replaces
# precision-fragile `round(..., 4)` dedup that allowed jitter-driven re-emits.
MIN_WEIGHT_DELTA = 0.005


def _is_us_market_open(now_utc: datetime | None = None) -> bool:
    """Return True if US equity regular session is open.

    9:30–16:00 ET, Mon–Fri. Approximates DST between second Sunday of March
    and first Sunday of November.
    """
    now = now_utc or datetime.now(UTC)
    if now.weekday() >= 5:
        return False
    m, d = now.month, now.day
    is_dst = (3, 8) <= (m, d) < (11, 1)
    et_offset = -4 if is_dst else -5
    et_hour = (now.hour + et_offset) % 24
    cur_minutes = et_hour * 60 + now.minute
    return 9 * 60 + 30 <= cur_minutes < 16 * 60


def _exchange_from_symbol(symbol: str) -> str:
    if "-" in symbol and symbol.endswith(("-USD", "-USDT")):
        return "CRYPTO"
    if "." in symbol:
        return symbol.split(".", 1)[1]
    return ""


def _weighted(sleeve, weight: float):
    """Set a sleeve instance's portfolio weight (overrides the class default).

    The class-level target_weight is the sleeve's documented standalone weight;
    the live agent allocates its own mix without mutating those defaults (the
    validation scripts rely on them).
    """
    sleeve.target_weight = weight
    return sleeve


class StrategyAgent(BaseAgent):
    """Sleeve-driven strategy agent — replaces RSI/MACD/BB indicators."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="strategy-agent-1",
            agent_type="strategy",
            bus=bus,
            department="front_office",
        )
        # Live sleeve allocation — the configuration validated by the 4-way
        # attribution run (validate_fix_ab: Sharpe 0.67 on PIT 2018-24 with the
        # patched params). DualMomentumSleeve and the risk overlay FAILED their
        # pre-registered ship gate on this window (validate_overlay 2026-07-02:
        # blend 0.16 vs baseline 0.28) and are kept as research artifacts only —
        # do not re-wire without a fresh gate pass. Weights sum to 1.0.
        self._sleeves = [
            _weighted(BreadthAlphaSleeve(), 0.40),   # multi-signal top-K breadth
            _weighted(ResearchStackSleeve(), 0.30),  # HRP + Kelly + regime + quality
            _weighted(TrendFilterSleeve(), 0.20),    # Faber 200d SMA gate on SPY
            _weighted(MomentumRankSleeve(), 0.10),   # 12-1 cross-sectional momentum
        ]
        # Universe resolved lazily on first tick — "sp500" hits the network, so
        # we don't want it firing at construction time (tests, --setup, etc.).
        self._universe_source = settings.universe_source
        self._symbols: list[str] = []
        # sleeve name -> last signal list cached until next cadence refresh
        self._sleeve_cache: dict[str, list] = {}
        # sleeve name -> last bar timestamp when sleeve was refreshed
        self._sleeve_last_refresh: dict[str, pd.Timestamp | None] = {
            s.name: None for s in self._sleeves
        }
        # (symbol) -> last emitted target weight. Prevents re-emitting
        # identical targets every 60s.
        self._last_emitted_weight: dict[str, float] = {}
        self._bar_count = 0  # increments per completed poll

    def _ensure_symbols(self) -> list[str]:
        """Resolve the trading universe once (lazy — may hit the network)."""
        if not self._symbols:
            from app.data_layer.universe import get_universe
            self._symbols = get_universe(self._universe_source)
            logger.info(
                "universe_loaded", source=self._universe_source, n=len(self._symbols)
            )
        return self._symbols

    # ------------------------------------------------------------------
    # BaseAgent hooks
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.features.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.FEATURE_UPDATE:
            logger.debug("feature_update_received", channel=message.channel)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await asyncio.sleep(15)
        logger.info("strategy_agent_starting", universe_source=self._universe_source)

        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("strategy_tick_error", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # One poll cycle
    # ------------------------------------------------------------------

    async def _tick(self, *, force: bool = False) -> None:
        """Fetch bars for all symbols, push TICKs, compute + emit sleeve signals.

        ``force=True`` bypasses the market-hours gate (used by the REPL's
        ``strategy tick`` diagnostic).
        """
        bars = await self._fetch_all_bars()
        if not bars:
            return

        await self._publish_ticks(bars)

        # Signal generation gated to market hours — TICKs always flow.
        if not force and not _is_us_market_open():
            return

        targets = self._compute_target_weights(bars)
        await self._emit_signals_from_targets(targets)
        self._bar_count += 1

    async def _fetch_all_bars(self) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV for the whole universe in one batched, cached call."""
        from app.data_layer.batch_bars import fetch_batch

        symbols = self._ensure_symbols()
        try:
            return await fetch_batch(symbols)
        except Exception as exc:
            logger.error("batch_fetch_error", error=str(exc))
            return {}

    async def _publish_ticks(self, bars: dict[str, pd.DataFrame]) -> None:
        """Write latest price to KV and emit TICK per symbol for the dashboard."""
        kv = get_kv_store()
        for symbol, df in bars.items():
            try:
                latest = float(df["close"].iloc[-1])
                prev = float(df["close"].iloc[-2]) if len(df) >= 2 else 0.0
                if latest <= 0:
                    continue
                await kv.set(f"horizon:price:{symbol}", str(latest))
                await kv.set(f"horizon:price:{symbol}:ts", datetime.now(UTC).isoformat())
                avg_vol = float(df["volume"].mean())
                if avg_vol > 0:
                    await kv.set(f"horizon:volume:{symbol}", str(avg_vol))
                chg_pct = ((latest - prev) / prev * 100.0) if prev > 0 else 0.0
                await self.emit(
                    channel=f"horizon.tick.{symbol}",
                    message_type=MessageType.TICK,
                    payload={
                        "symbol": symbol,
                        "exchange": _exchange_from_symbol(symbol),
                        "price": latest,
                        "change_pct": chg_pct,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception as exc:
                logger.debug("tick_publish_error", symbol=symbol, error=str(exc))

    # ------------------------------------------------------------------
    # Sleeve refresh + target aggregation
    # ------------------------------------------------------------------

    def _compute_target_weights(
        self, bars: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        """Return aggregated portfolio-weight targets across all sleeves."""
        as_of = max((df.index[-1] for df in bars.values()), default=None)
        if as_of is None:
            return {}

        combined: dict[str, float] = {}
        for sleeve in self._sleeves:
            if self._should_refresh(sleeve, as_of):
                try:
                    self._sleeve_cache[sleeve.name] = sleeve.compute(bars, as_of)
                    self._sleeve_last_refresh[sleeve.name] = as_of
                    logger.info(
                        "sleeve_refreshed",
                        sleeve=sleeve.name,
                        weight=sleeve.target_weight,
                        n_signals=len(self._sleeve_cache[sleeve.name]),
                    )
                except Exception as exc:
                    # Fall through to the cached signals below — `continue` here
                    # zeroed the sleeve's targets for a tick, emitting exits for
                    # the whole sleeve (then rebuying) on any transient error.
                    logger.warning(
                        "sleeve_compute_error", sleeve=sleeve.name, error=str(exc)
                    )
            for sig in self._sleeve_cache.get(sleeve.name, []):
                share = sig.target_weight * sleeve.target_weight
                combined[sig.symbol] = combined.get(sig.symbol, 0.0) + share
        return self._apply_overlay(combined, bars)

    def _apply_overlay(
        self, targets: dict[str, float], bars: dict[str, pd.DataFrame]
    ) -> dict[str, float]:
        """Scale aggregated weights by the risk-overlay exposure multiplier.

        Fail-open: overlay disabled, no targets, or no SPY bars -> unchanged.
        Freed weight is implicit cash; the drift check downstream turns overlay
        moves into normal rebalance signals.
        """
        if not settings.overlay_enabled or not targets:
            return targets
        spy = bars.get("SPY.NYSE")
        if spy is None:
            spy = bars.get("SPY")
        if spy is None:
            return targets

        from app.quant.risk_overlay import overlay_scalar

        closes = pd.DataFrame({s: df["close"] for s, df in bars.items()})
        scalar = overlay_scalar(
            closes, targets, spy["close"], target=settings.overlay_vol_target
        )
        if scalar >= 0.999:
            return targets
        logger.info("overlay_applied", scalar=round(scalar, 3))
        return {s: w * scalar for s, w in targets.items()}

    def _should_refresh(self, sleeve, as_of: pd.Timestamp) -> bool:
        """Per-sleeve cadence gate based on business-day delta since last refresh."""
        last = self._sleeve_last_refresh.get(sleeve.name)
        if last is None:
            return True
        delta_days = (as_of - last).days
        return delta_days >= sleeve.rebalance_days

    # ------------------------------------------------------------------
    # Signal emission
    # ------------------------------------------------------------------

    async def _emit_signals_from_targets(
        self, targets: dict[str, float]
    ) -> None:
        """Emit SIGNAL messages when a symbol's target weight has changed.

        The portfolio agent interprets direction/strength and sizes orders
        against current cash + positions.
        """
        # Include symbols that previously had a non-zero target but are now
        # absent so we emit exits. Sells first (most-negative delta first) so
        # their proceeds fund the buys — buys emitted before funding sells hit
        # the execution cash guard and were silently dropped. Within each side,
        # biggest deltas first so the debate cost-budget goes to the strongest.
        union = set(targets) | set(self._last_emitted_weight)
        ordered = sorted(
            union,
            key=lambda s: (
                (d := targets.get(s, 0.0) - self._last_emitted_weight.get(s, 0.0)) >= 0,
                -abs(d),
            ),
        )

        for symbol in ordered:
            new_w = targets.get(symbol, 0.0)
            old_w = self._last_emitted_weight.get(symbol, 0.0)
            if abs(new_w - old_w) < MIN_WEIGHT_DELTA:
                continue  # below threshold — treat as unchanged

            direction = 1 if new_w > old_w else -1
            strength = min(abs(new_w - old_w) / 0.5, 1.0)  # scale 0–1
            reasoning = (
                f"sleeve_target {old_w:.2%} -> {new_w:.2%}"
            )

            signal_id = str(uuid.uuid4())
            payload = {
                "signal_id": signal_id,
                "symbol": symbol,
                "exchange": _exchange_from_symbol(symbol),
                "direction": direction,
                "strength": strength,
                "strategy_name": "sleeve_system",
                "reasoning": reasoning,
                "target_weight": new_w,
                "previous_weight": old_w,
                "target_price": None,
                "stop_loss": None,
                "bar_timestamp": datetime.now(UTC).isoformat(),
            }
            await self.emit(
                channel=f"horizon.signal.{symbol}",
                message_type=MessageType.SIGNAL,
                payload=payload,
            )
            await self._persist_signal(payload)
            self._last_emitted_weight[symbol] = new_w

            logger.info(
                "signal_emitted",
                symbol=symbol, direction=direction,
                strength=round(strength, 3),
                target_weight=round(new_w, 4),
            )

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_ohlcv(symbol: str) -> pd.DataFrame | None:
        """Fetch daily OHLCV. Alpaca preferred for US; yfinance fallback."""
        from app.data_layer import alpaca_quotes

        is_us = not (".NSE" in symbol or ".BSE" in symbol or "-USD" in symbol)
        if is_us and alpaca_quotes.is_configured():
            df = await alpaca_quotes.get_bars(
                symbol, timeframe="1Day", lookback_days=300
            )
            if df is not None and not df.empty:
                return df
            logger.warning("alpaca_bars_empty_falling_back", symbol=symbol)

        raw = symbol.split(".")[0] if "." in symbol else symbol
        if ".NSE" in symbol:
            yf_ticker = raw + ".NS"
        elif ".BSE" in symbol:
            yf_ticker = raw + ".BO"
        else:
            yf_ticker = raw

        try:
            import yfinance as yf

            ticker = yf.Ticker(yf_ticker)
            df = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ticker.history(period="300d", interval="1d"),
            )
            if df is None or df.empty:
                return None
            df.columns = [c.lower() for c in df.columns]
            for col in ("open", "high", "low", "close", "volume"):
                if col not in df.columns:
                    return None
            return df[["open", "high", "low", "close", "volume"]].copy()
        except Exception as exc:
            logger.warning("yfinance_fetch_error", symbol=symbol, error=str(exc))
            return None

    @staticmethod
    async def _persist_signal(payload: dict) -> None:
        """Insert a sleeve signal into the signals table for audit."""
        try:
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO signals
                            (signal_id, agent_id, symbol, direction, strength,
                             confidence, strategy_name, regime, metadata, created_at)
                        VALUES
                            (:signal_id, :agent_id, :symbol, :direction, :strength,
                             :confidence, :strategy_name, :regime, :metadata, :now)
                        """
                    ),
                    {
                        "signal_id": payload["signal_id"],
                        "agent_id": "strategy-agent-1",
                        "symbol": payload["symbol"],
                        "direction": "BUY" if payload["direction"] > 0 else (
                            "SELL" if payload["direction"] < 0 else "HOLD"
                        ),
                        "strength": payload["strength"],
                        "confidence": payload["strength"],
                        "strategy_name": payload["strategy_name"],
                        "regime": "",
                        "metadata": json.dumps({
                            "target_weight": payload.get("target_weight"),
                            "previous_weight": payload.get("previous_weight"),
                            "reasoning": payload.get("reasoning"),
                        }),
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("signal_persist_error", error=str(exc))
