"""Debate agent -- subscribes to signals and runs multi-model debates.

When an LLM provider is available, uses ``MultiModelDebateEngine`` to run
a structured multi-round debate with perspective rotation.  When no LLM
providers are configured, operates in pass-through mode (auto-approves
all signals so the pipeline keeps flowing).
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger("debate.agent")

# Debounce: skip debate if we debated this symbol within this many seconds
DEBOUNCE_SECONDS = 120


class DebateAgent(BaseAgent):
    """Consumes trading signals and runs debates before forwarding to portfolio."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="debate-agent-1",
            agent_type="debate",
            bus=bus,
            department="middle_office",
        )
        self._pending_signals: asyncio.Queue[dict] = asyncio.Queue()
        self._last_debate: dict[str, float] = {}  # symbol -> timestamp
        # Cost gate: timestamps of debates run in the last 24h (rolling budget).
        self._debate_budget: deque[float] = deque()

    # ------------------------------------------------------------------
    # BaseAgent hooks
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.approved.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.SIGNAL:
            await self._pending_signals.put(message.payload)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        logger.info("debate_agent_started")

        while self._running:
            try:
                payload = await asyncio.wait_for(
                    self._pending_signals.get(), timeout=5.0
                )
            except TimeoutError:
                continue

            symbol = payload.get("symbol", "")
            now = datetime.now(UTC).timestamp()

            # Debounce: don't re-debate the same symbol within the window. But we
            # MUST still emit a conclusion — PortfolioAgent buffers every approved
            # signal awaiting a DEBATE_CONCLUSION, so a silent skip orphans that
            # buffered signal forever (and the buffer grows unbounded). Emit a
            # DEBOUNCED conclusion so the buffer is cleared (signal discarded; the
            # strategy re-emits next bar).
            if now - self._last_debate.get(symbol, 0) < DEBOUNCE_SECONDS:
                await self.emit(
                    channel=f"horizon.debate.{symbol}",
                    message_type=MessageType.DEBATE_CONCLUSION,
                    payload={
                        "session_id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "decision": "DEBOUNCED",
                        "consensus_score": 0.0,
                        "mode": "debounce",
                        "reason": f"Debounced — debated within {DEBOUNCE_SECONDS}s",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                continue
            self._last_debate[symbol] = now

            # Cost gate: a full debate is ~8 LLM calls. Only spend the budget on
            # strong signals, capped per rolling 24h. Gated signals pass through
            # APPROVED — they trade on the quant signal without an LLM (so nothing
            # orphans and trading never stalls; raise the cap for more AI coverage).
            strength = float(payload.get("strength", 0.0) or 0.0)
            if strength < settings.debate_min_strength or not self._within_budget(now):
                await self._emit_passthrough(symbol)
                continue
            self._debate_budget.append(now)

            try:
                await self._debate_signal(payload)
            except Exception as exc:
                logger.error("debate_error", symbol=symbol, error=str(exc))

    def _within_budget(self, now: float) -> bool:
        """True if we're under the rolling-24h debate cap (prunes old entries)."""
        cutoff = now - 86400
        while self._debate_budget and self._debate_budget[0] < cutoff:
            self._debate_budget.popleft()
        return len(self._debate_budget) < settings.debate_max_per_day

    async def _emit_passthrough(self, symbol: str) -> None:
        """Release a cost-gated signal without an LLM debate (trades on quant)."""
        await self.emit(
            channel=f"horizon.debate.{symbol}",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={
                "session_id": str(uuid.uuid4()),
                "symbol": symbol,
                "decision": "APPROVED",
                "consensus_score": 0.0,
                "mode": "gated_passthrough",
                "reason": "Cost-gate: daily debate budget reached / low strength",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        logger.debug("debate_gated_passthrough", symbol=symbol)

    # ------------------------------------------------------------------
    # Debate logic
    # ------------------------------------------------------------------

    async def _debate_signal(self, signal_payload: dict) -> None:
        """Run a debate on the signal, or auto-approve if no LLM available."""
        symbol = signal_payload.get("symbol", "")
        direction = signal_payload.get("direction", 0)
        action = "BUY" if direction > 0 else ("SELL" if direction < 0 else "HOLD")

        # Check for providers available to this department
        from app.llm.provider_registry import provider_registry
        dept_providers = provider_registry.get_providers_for_department("middle_office")

        if dept_providers:
            await self._run_llm_debate(symbol, action, signal_payload)
        else:
            await self._auto_approve(symbol, action, signal_payload)

    async def _run_llm_debate(
        self, symbol: str, action: str, signal_payload: dict
    ) -> None:
        """Run a full multi-model debate."""
        from app.agents.debate.multi_model_debate import MultiModelDebateEngine
        from app.llm.provider_registry import provider_registry

        # Get regime for context
        regime = signal_payload.get("regime")
        sentiment = await self._get_sentiment_context(symbol)
        signal_payload = {
            **signal_payload,
            **await self._get_market_context(symbol),
        }

        engine = MultiModelDebateEngine(
            registry=provider_registry,
            bus=self.bus,
            max_rounds=2,
        )

        # Get allowed provider names for middle_office routing
        from app.llm.provider_registry import provider_registry as _reg
        _dept_pvdrs = _reg.get_providers_for_department("middle_office")
        _allowed = [p.provider_name for p in _dept_pvdrs] if _dept_pvdrs else None

        try:
            result = await engine.run_debate(
                symbol=symbol,
                action=action,
                signal_data=signal_payload,
                regime=regime,
                sentiment=sentiment,
                allowed_providers=_allowed,
            )

            # Persist debate result
            await self._persist_debate(result)

            logger.info(
                "debate_completed",
                symbol=symbol,
                decision=result.decision,
                consensus=result.consensus_score,
                providers=result.providers_used,
            )
        except RuntimeError:
            # No providers available (race condition) -- fall back to auto-approve
            # (which will reject in FULLY_AUTONOMOUS mode)
            await self._auto_approve(symbol, action, signal_payload)

    async def _auto_approve(
        self, symbol: str, action: str, signal_payload: dict
    ) -> None:
        """Auto-approve signal when no LLM providers are configured.

        In FULLY_AUTONOMOUS mode, auto-approve is dangerous -- reject the
        signal instead so that real money orders are never placed without
        a proper debate.  In PAPER_TRADING mode, auto-approve is fine
        because no real capital is at risk.
        """
        # Safety check: reject in FULLY_AUTONOMOUS mode (real money)
        from app.core.kv_store import get_kv_store
        kv = get_kv_store()
        system_mode = await kv.get("horizon:system:mode") or "PAPER_TRADING"

        if system_mode == "FULLY_AUTONOMOUS":
            logger.warning(
                "debate_auto_approve_blocked",
                symbol=symbol,
                action=action,
                reason="FULLY_AUTONOMOUS mode requires LLM debate; "
                       "signal rejected (no providers available)",
            )
            session_id = str(uuid.uuid4())
            now = datetime.now(UTC)
            await self.emit(
                channel=f"horizon.debate.{symbol}",
                message_type=MessageType.DEBATE_CONCLUSION,
                payload={
                    "session_id": session_id,
                    "symbol": symbol,
                    "decision": "REJECTED",
                    "consensus_score": 0.0,
                    "mode": "auto_reject",
                    "reason": "FULLY_AUTONOMOUS mode requires LLM debate; "
                              "no providers available",
                    "for_count": 0,
                    "against_count": 1,
                    "timestamp": now.isoformat(),
                },
            )
            await self._persist_auto_rejection(session_id, symbol, action)
            return

        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Emit debate start
        await self.emit(
            channel=f"horizon.debate.{symbol}",
            message_type=MessageType.DEBATE_START,
            payload={
                "session_id": session_id,
                "symbol": symbol,
                "action": action,
                "mode": "auto_approve",
                "timestamp": now.isoformat(),
            },
        )

        # Emit auto-approval conclusion
        await self.emit(
            channel=f"horizon.debate.{symbol}",
            message_type=MessageType.DEBATE_CONCLUSION,
            payload={
                "session_id": session_id,
                "symbol": symbol,
                "decision": "APPROVED",
                "consensus_score": 1.0,
                "mode": "auto_approve",
                "reason": "No LLM providers configured; signal auto-approved",
                "for_count": 1,
                "against_count": 0,
                "timestamp": now.isoformat(),
            },
        )

        # Persist
        await self._persist_auto_approval(session_id, symbol, action, signal_payload)

        logger.info("signal_auto_approved", symbol=symbol, action=action)

    @staticmethod
    async def _get_sentiment_context(symbol: str) -> dict | None:
        """Read cached SentimentAgent output for the debate prompt.

        Never raises -- sentiment is a nice-to-have context field, not a
        gate; any KV failure just means the debate proceeds without it.
        """
        try:
            from app.core.kv_store import get_kv_store
            kv = get_kv_store()
            base = symbol.split(".")[0]
            data = await kv.hgetall(f"horizon:sentiment:{base}")
            if not data:
                return None
            return {
                "label": data.get("label"),
                "score": data.get("score"),
                "avg_sentiment_24h": f"{data.get('label')} ({data.get('score')})",
            }
        except Exception:
            return None

    @staticmethod
    async def _get_market_context(symbol: str) -> dict:
        """Extra prompt context for prediction markets.

        A ``.POLY`` ticker is an unreadable slug — without the question text and
        the implied probability the debaters argue about a symbol they cannot
        interpret. Never raises: missing context just means a thinner prompt.
        """
        if not symbol.endswith(".POLY"):
            return {}
        try:
            import json

            from app.core.kv_store import get_kv_store

            kv = get_kv_store()
            out: dict = {}
            meta_raw = await kv.get(f"horizon:pm:meta:{symbol}")
            if meta_raw:
                meta = json.loads(meta_raw)
                out["market_question"] = meta.get("question")
                out["market_end_date"] = meta.get("end_date")
            price = await kv.get(f"horizon:price:{symbol}")
            if price:
                out["market_probability"] = float(price)
            return out
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    async def _persist_debate(result) -> None:
        """Store debate result in the debate_sessions table."""
        try:
            # Build a one-line reason from the first argument of the majority vote
            reason = ""
            if result.arguments:
                majority = "FOR" if result.for_count >= result.against_count else "AGAINST"
                for arg in result.arguments:
                    if arg.vote == majority and arg.argument:
                        reason = arg.argument[:120]
                        break
            if not reason:
                reason = (
                    f"{result.for_count} for, {result.against_count} against, "
                    f"{result.abstain_count} abstain"
                )
            # Never let a provider outage read as a considered verdict.
            errors = getattr(result, "error_count", 0)
            if errors:
                reason = f"[{errors} debater(s) failed: provider error] {reason}"[:250]

            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO debate_sessions
                            (id, symbol, proposed_action, status,
                             total_rounds, final_decision, consensus_score,
                             reason, created_at)
                        VALUES
                            (:id, :symbol, :action, 'COMPLETED',
                             :rounds, :decision, :consensus, :reason, :now)
                        """
                    ),
                    {
                        "id": result.session_id,
                        "symbol": result.symbol,
                        "action": result.proposed_action,
                        "rounds": result.rounds,
                        "decision": result.decision,
                        "consensus": result.consensus_score,
                        "reason": reason,
                        "now": datetime.now(UTC),
                    },
                )
                await DebateAgent._persist_arguments(session, result)
                await session.commit()
        except Exception as exc:
            logger.warning("debate_persist_error", error=str(exc))

    @staticmethod
    async def _persist_arguments(session, result) -> None:
        """Store every debater's argument so the reasoning survives the process.

        Written in the caller's transaction: an orphaned argument row (or a
        session with its arguments silently dropped) is worse than neither.
        Multi-round results carry provider + round on each argument; the
        single-reasoner engine only has the flat list, so fall back to that.
        """
        rows: list[dict] = []
        round_args = getattr(result, "round_arguments", None) or {}
        if round_args:
            for round_number, args in sorted(round_args.items()):
                for arg in args:
                    rows.append({
                        "id": str(uuid.uuid4()),
                        "session_id": result.session_id,
                        "agent_id": getattr(arg, "provider", "") or "unknown",
                        "role": (
                            f"{arg.role} (as {arg.rotated_from})"
                            if getattr(arg, "rotated_from", "")
                            else arg.role
                        ),
                        "argument": arg.argument,
                        "vote": arg.vote,
                        "confidence": float(arg.confidence or 0.0),
                        "round_number": int(getattr(arg, "round_number", round_number)),
                        "now": datetime.now(UTC),
                    })
        else:
            for arg in getattr(result, "arguments", []) or []:
                rows.append({
                    "id": str(uuid.uuid4()),
                    "session_id": result.session_id,
                    "agent_id": getattr(arg, "provider", "") or "unknown",
                    "role": arg.role,
                    "argument": arg.argument,
                    "vote": arg.vote,
                    "confidence": float(arg.confidence or 0.0),
                    "round_number": 1,
                    "now": datetime.now(UTC),
                })

        if not rows:
            return

        await session.execute(
            text(
                """
                INSERT INTO debate_arguments
                    (id, session_id, agent_id, role, argument, vote,
                     confidence, round_number, created_at)
                VALUES
                    (:id, :session_id, :agent_id, :role, :argument, :vote,
                     :confidence, :round_number, :now)
                """
            ),
            rows,
        )

    @staticmethod
    async def _persist_auto_rejection(
        session_id: str, symbol: str, action: str
    ) -> None:
        """Store auto-rejection in the debate_sessions table."""
        try:
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO debate_sessions
                            (id, symbol, proposed_action, status,
                             total_rounds, final_decision, consensus_score,
                             reason, created_at)
                        VALUES
                            (:id, :symbol, :action, 'COMPLETED',
                             0, 'REJECTED', 0.0, :reason, :now)
                        """
                    ),
                    {
                        "id": session_id,
                        "symbol": symbol,
                        "action": action,
                        "reason": "FULLY_AUTONOMOUS mode requires LLM debate; no providers",
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("auto_rejection_persist_error", error=str(exc))

    @staticmethod
    async def _persist_auto_approval(
        session_id: str, symbol: str, action: str, signal_payload: dict
    ) -> None:
        """Store auto-approval in the debate_sessions table."""
        try:
            reason = (
                f"Auto-approved (no LLM); "
                f"strategy={signal_payload.get('strategy_name', '?')}, "
                f"strength={signal_payload.get('strength', '?')}"
            )
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO debate_sessions
                            (id, symbol, proposed_action, status,
                             total_rounds, final_decision, consensus_score,
                             reason, created_at)
                        VALUES
                            (:id, :symbol, :action, 'COMPLETED',
                             0, 'APPROVED', 1.0, :reason, :now)
                        """
                    ),
                    {
                        "id": session_id,
                        "symbol": symbol,
                        "action": action,
                        "reason": reason,
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("auto_approval_persist_error", error=str(exc))
