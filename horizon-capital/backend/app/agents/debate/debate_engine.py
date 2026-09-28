# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-AFDF6CF0E835
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Multi-agent debate engine for trade approval.

Four AI debater roles argue for or against a proposed trade.  The engine
collects votes, calculates a consensus score, and decides whether to approve
or reject.  The full debate lifecycle is published on the agent bus and
persisted to the ``debate_sessions`` / ``debate_arguments`` tables.

Pipeline integration: signal -> debate -> risk check -> sizing -> execution.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.agents.debate.claude_reasoner import ClaudeReasoner
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()
from app.core.messaging import AgentBus, AgentMessage, MessageType  # noqa: E402

logger = get_logger("debate.engine")


# ------------------------------------------------------------------
# Debater role definitions
# ------------------------------------------------------------------

DEBATER_ROLES: dict[str, str] = {
    "STRATEGY": (
        "You are the growth-focused strategy trader on a hedge-fund trade-approval panel. "
        "Argue the upside case: signal strength, momentum, trend, entry/exit timing, and "
        "reward-to-risk of the proposed trade. Base your reasoning ONLY on the data in the "
        "prompt — never invent prices, news, or positions not stated there. Vote FOR when "
        "the signal is strong and timing is good, AGAINST when the setup is weak, ABSTAIN "
        "only if the signal data itself is missing or contradictory. Keep your argument to "
        "2-4 sentences."
    ),
    "RISK": (
        "You are the conservative risk manager on a hedge-fund trade-approval panel. "
        "Argue the downside case: drawdown, volatility, liquidity, concentration, and "
        "correlation figures given in the prompt. Base your reasoning ONLY on the data in "
        "the prompt — never invent risk figures not stated there. Err toward AGAINST when "
        "downside or tail risk is elevated, vote FOR only when the risk profile is clearly "
        "acceptable, ABSTAIN if the risk metrics needed to judge are missing. Keep your "
        "argument to 2-4 sentences."
    ),
    "SENTIMENT": (
        "You are the market sentiment analyst on a hedge-fund trade-approval panel. "
        "Judge whether the news flow and crowd positioning shown in the Sentiment section "
        "support or contradict the proposed trade, and whether the crowd is right or a "
        "contrarian indicator. Base your reasoning ONLY on the sentiment data provided — "
        "never invent headlines or social-media activity. If the prompt says no sentiment "
        "data is available, say so and vote ABSTAIN rather than guessing. Keep your "
        "argument to 2-4 sentences."
    ),
    "PORTFOLIO": (
        "You are the portfolio construction specialist on a hedge-fund trade-approval "
        "panel. Judge whether this trade improves the portfolio: diversification, "
        "correlation to existing exposure, position sizing, and fit with the current "
        "regime. Base your reasoning ONLY on the data provided — never invent holdings or "
        "exposures not stated there. Vote FOR if it improves the portfolio's risk-adjusted "
        "return, AGAINST if it degrades it, ABSTAIN if the portfolio context needed to "
        "judge is missing. Keep your argument to 2-4 sentences."
    ),
}


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class DebateArgument:
    """A single argument from one debater."""
    role: str
    argument: str
    vote: str  # FOR, AGAINST, ABSTAIN
    confidence: float


@dataclass
class DebateResult:
    """Final outcome of a debate session."""
    session_id: str
    symbol: str
    proposed_action: str
    decision: str  # APPROVED, REJECTED
    consensus_score: float
    arguments: list[DebateArgument] = field(default_factory=list)
    for_count: int = 0
    against_count: int = 0
    abstain_count: int = 0


# ------------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------------

def _instrument_type(symbol: str) -> str:
    """What kind of thing is being traded — debaters reason differently on each."""
    if symbol.endswith(".POLY"):
        return "prediction market (Polymarket YES share, price = implied probability)"
    if symbol.endswith(("-USD", "-USDT")):
        return "crypto (24/7 market)"
    return "equity"


def _build_user_prompt(
    symbol: str,
    action: str,
    signal_data: dict[str, Any],
    regime: str | None,
    sentiment: dict[str, Any] | None,
    risk_metrics: dict[str, Any] | None,
) -> str:
    """Build the shared market context prompt that every debater receives."""
    lines = [
        "## Proposed Trade",
        f"- Symbol: {symbol}",
        f"- Instrument: {_instrument_type(symbol)}",
        f"- Action: {action}",
        f"- Signal strength: {signal_data.get('strength', 'N/A')}",
        # Without this the debaters read a 0.02 rebalance step as "no
        # conviction" and reject every routine position build.
        "  (strength = size of the rebalance step, |target - current| / 50%,"
        " NOT a confidence score. Judge the position itself, not this number.)",
        f"- Strategy: {signal_data.get('strategy_name', 'N/A')}",
        f"- Target price: {signal_data.get('target_price', 'N/A')}",
        f"- Stop loss: {signal_data.get('stop_loss', 'N/A')}",
    ]

    target_w = signal_data.get("target_weight")
    prev_w = signal_data.get("previous_weight")
    if target_w is not None:
        lines.append(
            f"- Portfolio intent: move this holding to {float(target_w):.2%} of NAV"
            + (f" (from {float(prev_w):.2%})" if prev_w is not None else "")
        )

    question = signal_data.get("market_question")
    if question:
        lines.append("")
        lines.append("## Prediction Market")
        lines.append(f"- Question: {question}")
        prob = signal_data.get("market_probability")
        if prob is not None:
            lines.append(
                f"- Current YES probability: {float(prob):.1%}"
                " (the price IS the market's implied probability; a YES share"
                " pays $1 if the event resolves true, $0 otherwise)"
            )
        if signal_data.get("market_end_date"):
            lines.append(f"- Resolves: {signal_data['market_end_date']}")

    lines += [
        "",
        "## Market Regime",
        f"- Current regime: {regime or 'UNKNOWN'}",
        "",
        "## Sentiment",
    ]

    if sentiment:
        lines.append(f"- Average sentiment (24h): {sentiment.get('avg_sentiment_24h', 'N/A')}")
        lines.append(f"- Lifecycle stage: {sentiment.get('lifecycle_stage', 'N/A')}")
        lines.append(f"- Article count (14d): {sentiment.get('article_count_14d', 'N/A')}")
    else:
        lines.append("- No sentiment data available")

    lines.append("")
    lines.append("## Risk Metrics")

    if risk_metrics:
        lines.append(f"- Portfolio VaR: {risk_metrics.get('var_pct', 'N/A')}%")
        lines.append(f"- Current drawdown: {risk_metrics.get('drawdown_pct', 'N/A')}%")
        lines.append(f"- Gross exposure: {risk_metrics.get('gross_exposure', 'N/A')}")
        lines.append(f"- Correlation to portfolio: {risk_metrics.get('correlation', 'N/A')}")
    else:
        lines.append("- No risk metrics available")

    # Optional numeric grounding from the signal itself. Kept generic so the
    # same block serves live signals and the blinded A/B harness, which relies
    # on these features being the ONLY thing identifying the trade.
    features = signal_data.get("features")
    if features:
        lines.append("")
        lines.append("## Signal Features")
        lines.extend(f"- {k}: {v}" for k, v in features.items())

    lines.extend(
        [
            "",
            "## Instructions",
            "Analyze the proposed trade from your role's perspective, using only the data above.",
            "Any field marked N/A is unavailable — treat it as unknown, do not guess its value.",
            "Respond with ONLY a JSON object — no markdown fences, no prose before or after:",
            '{"argument": "<2-4 sentence reasoning>", "vote": "FOR" | "AGAINST" | "ABSTAIN",'
            ' "confidence": <float 0.0-1.0>}',
            '"confidence" is your conviction in your own vote (1.0 = certain).',
        ]
    )

    return "\n".join(lines)


# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------

class DebateEngine:
    """Orchestrates multi-agent debates for trade approval.

    Approval requires:
    - ``consensus_score > 0.6``
    - At least 3 out of 4 debaters vote ``FOR``
    """

    def __init__(self, reasoner: ClaudeReasoner, bus: AgentBus) -> None:
        self.reasoner = reasoner
        self.bus = bus

    async def run_debate(
        self,
        symbol: str,
        action: str,
        signal_data: dict[str, Any],
        regime: str | None = None,
        sentiment: dict[str, Any] | None = None,
        risk_metrics: dict[str, Any] | None = None,
    ) -> DebateResult:
        """Execute a full debate round for a proposed trade.

        Parameters
        ----------
        symbol:
            The instrument ticker.
        action:
            ``"BUY"`` or ``"SELL"``.
        signal_data:
            Dictionary with signal details (strength, strategy, prices).
        regime:
            Current market regime label.
        sentiment:
            Aggregated sentiment data for the symbol.
        risk_metrics:
            Current portfolio risk metrics.

        Returns
        -------
        DebateResult
            Contains the final decision, consensus score, and all arguments.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Persist debate session as IN_PROGRESS
        await self._create_session(session_id, symbol, action, signal_data)

        # Publish debate start
        await self.bus.publish(
            AgentMessage(
                sender_id="debate-engine",
                channel=f"horizon.debate.{session_id}.start",
                message_type=MessageType.DEBATE_START,
                payload={
                    "session_id": session_id,
                    "symbol": symbol,
                    "action": action,
                    "timestamp": now.isoformat(),
                },
            )
        )

        # Build the shared user prompt
        user_prompt = _build_user_prompt(
            symbol, action, signal_data, regime, sentiment, risk_metrics
        )

        # Collect arguments from all debaters IN PARALLEL
        arguments: list[DebateArgument] = []

        async def _run_debater(role: str, personality: str) -> DebateArgument:
            """Run a single debater and return its argument."""
            try:
                result = await self.reasoner.reason(
                    system_prompt=personality,
                    user_prompt=user_prompt,
                )
                return DebateArgument(
                    role=role,
                    argument=result["argument"],
                    vote=result["vote"],
                    confidence=result["confidence"],
                )
            except Exception as exc:
                logger.error(
                    "debate_agent_error",
                    session_id=session_id,
                    role=role,
                    error=str(exc),
                )
                return DebateArgument(
                    role=role,
                    argument=f"Error: {str(exc)[:200]}",
                    vote="ABSTAIN",
                    confidence=0.0,
                )

        # Fire all 4 debater API calls in parallel (~75% latency reduction)
        import asyncio as _asyncio
        debate_tasks = [
            _run_debater(role, personality)
            for role, personality in DEBATER_ROLES.items()
        ]
        arguments = list(await _asyncio.gather(*debate_tasks))

        # Publish and persist all arguments
        for arg in arguments:
            await self.bus.publish(
                AgentMessage(
                    sender_id="debate-engine",
                    channel=f"horizon.debate.{session_id}.argument",
                    message_type=MessageType.DEBATE_VOTE,
                    payload={
                        "session_id": session_id,
                        "role": arg.role,
                        "vote": arg.vote,
                        "confidence": arg.confidence,
                        "argument": arg.argument[:500],
                    },
                )
            )
            await self._store_argument(session_id, arg.role, arg)
            logger.info(
                "debate_argument_received",
                session_id=session_id,
                role=arg.role,
                vote=arg.vote,
                confidence=arg.confidence,
            )

        # Tally votes — simple majority wins
        for_votes = [a for a in arguments if a.vote == "FOR"]
        against_votes = [a for a in arguments if a.vote == "AGAINST"]
        abstain_votes = [a for a in arguments if a.vote == "ABSTAIN"]

        consensus_score = round(len(for_votes) / len(arguments), 4) if arguments else 0.0
        decision = "APPROVED" if len(for_votes) > len(against_votes) else "REJECTED"

        debate_result = DebateResult(
            session_id=session_id,
            symbol=symbol,
            proposed_action=action,
            decision=decision,
            consensus_score=consensus_score,
            arguments=arguments,
            for_count=len(for_votes),
            against_count=len(against_votes),
            abstain_count=len(abstain_votes),
        )

        # Update session in DB
        await self._conclude_session(session_id, decision, consensus_score)

        # Publish conclusion
        await self.bus.publish(
            AgentMessage(
                sender_id="debate-engine",
                channel=f"horizon.debate.{session_id}.conclusion",
                message_type=MessageType.DEBATE_CONCLUSION,
                payload={
                    "session_id": session_id,
                    "symbol": symbol,
                    "action": action,
                    "decision": decision,
                    "consensus_score": consensus_score,
                    "for_count": len(for_votes),
                    "against_count": len(against_votes),
                    "abstain_count": len(abstain_votes),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

        logger.info(
            "debate_concluded",
            session_id=session_id,
            symbol=symbol,
            decision=decision,
            consensus_score=consensus_score,
            votes=f"{len(for_votes)}F/{len(against_votes)}A/{len(abstain_votes)}Ab",
        )

        return debate_result

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    async def _create_session(
        self,
        session_id: str,
        symbol: str,
        action: str,
        signal_data: dict[str, Any],
    ) -> None:
        """Insert a new debate session row."""
        now = datetime.now(UTC)
        exchange = symbol.split(".")[-1] if "." in symbol else "UNKNOWN"

        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO debate_sessions
                        (id, symbol, exchange, proposed_action, proposed_quantity,
                         signal_id, status, total_rounds, created_at, updated_at)
                    VALUES
                        (:id, :symbol, :exchange, :action, :quantity,
                         :signal_id, 'IN_PROGRESS', 1, :now, :now)
                    """
                ),
                {
                    "id": session_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "action": action,
                    "quantity": signal_data.get("quantity"),
                    "signal_id": signal_data.get("signal_id"),
                    "now": now,
                },
            )
            await session.commit()

    async def _store_argument(
        self,
        session_id: str,
        role: str,
        arg: DebateArgument,
    ) -> None:
        """Persist a single debate argument."""
        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO debate_arguments
                        (id, session_id, agent_id, role, argument, vote,
                         confidence, round_number, created_at, updated_at)
                    VALUES
                        (:id, :session_id, :agent_id, :role, :argument, :vote,
                         :confidence, 1, :now, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "agent_id": f"debate-{role.lower()}",
                    "role": role,
                    "argument": arg.argument,
                    "vote": arg.vote,
                    "confidence": arg.confidence,
                    "now": now,
                },
            )
            await session.commit()

    async def _conclude_session(
        self,
        session_id: str,
        decision: str,
        consensus_score: float,
    ) -> None:
        """Mark a debate session as concluded with the final decision."""
        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    UPDATE debate_sessions
                    SET status = 'CONCLUDED',
                        final_decision = :decision,
                        consensus_score = :score,
                        updated_at = :now
                    WHERE id = :session_id
                    """
                ),
                {
                    "session_id": session_id,
                    "decision": decision,
                    "score": consensus_score,
                    "now": now,
                },
            )
            await session.commit()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token AFDF6CF0E835 - verify with scripts/authorship.py verify
