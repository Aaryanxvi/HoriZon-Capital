"""Multi-agent debate engine for trade approval.

Four AI debater roles argue for or against a proposed trade.  The engine
collects votes, calculates a consensus score, and decides whether to approve
or reject.  The full debate lifecycle is published on the agent bus and
persisted to the ``debate_sessions`` / ``debate_arguments`` tables.

Pipeline integration: signal -> debate -> risk check -> sizing -> execution.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.agents.debate.claude_reasoner import ClaudeReasoner
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("debate.engine")


# ------------------------------------------------------------------
# Debater role definitions
# ------------------------------------------------------------------

DEBATER_ROLES: dict[str, str] = {
    "STRATEGY": (
        "You are an aggressive growth-focused trader. Analyze the technical "
        "signals and market momentum. Focus on potential upside, trend "
        "strength, and entry/exit timing. Be decisive."
    ),
    "RISK": (
        "You are a conservative risk manager. Identify all potential downside "
        "risks and tail scenarios. Consider drawdown, volatility, liquidity "
        "risk, and correlation blow-ups. Err on the side of caution."
    ),
    "SENTIMENT": (
        "You are a market sentiment analyst. Evaluate news flow, social media "
        "mood, and narrative momentum. Assess whether the crowd is positioned "
        "correctly or is a contrary indicator."
    ),
    "PORTFOLIO": (
        "You are a portfolio construction expert. Consider diversification, "
        "correlation, and position sizing. Evaluate whether this trade "
        "improves or degrades the overall portfolio risk/return profile."
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
        f"## Proposed Trade",
        f"- Symbol: {symbol}",
        f"- Action: {action}",
        f"- Signal strength: {signal_data.get('strength', 'N/A')}",
        f"- Strategy: {signal_data.get('strategy_name', 'N/A')}",
        f"- Target price: {signal_data.get('target_price', 'N/A')}",
        f"- Stop loss: {signal_data.get('stop_loss', 'N/A')}",
        "",
        f"## Market Regime",
        f"- Current regime: {regime or 'UNKNOWN'}",
        "",
        f"## Sentiment",
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

    lines.extend(
        [
            "",
            "## Instructions",
            "Analyze the above from your role's perspective. Respond with ONLY a JSON object:",
            '{"argument": "<your reasoning>", "vote": "FOR|AGAINST|ABSTAIN", "confidence": <0.0-1.0>}',
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

    APPROVAL_THRESHOLD = 0.6
    MIN_FOR_VOTES = 3

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
        now = datetime.now(timezone.utc)

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

        # Collect arguments from all debaters
        arguments: list[DebateArgument] = []

        for role, personality in DEBATER_ROLES.items():
            try:
                result = await self.reasoner.reason(
                    system_prompt=personality,
                    user_prompt=user_prompt,
                )

                arg = DebateArgument(
                    role=role,
                    argument=result["argument"],
                    vote=result["vote"],
                    confidence=result["confidence"],
                )
                arguments.append(arg)

                # Publish each argument as it arrives
                await self.bus.publish(
                    AgentMessage(
                        sender_id="debate-engine",
                        channel=f"horizon.debate.{session_id}.argument",
                        message_type=MessageType.DEBATE_ARGUMENT,
                        payload={
                            "session_id": session_id,
                            "role": role,
                            "vote": arg.vote,
                            "confidence": arg.confidence,
                            "argument": arg.argument[:500],
                        },
                    )
                )

                # Persist argument
                await self._store_argument(session_id, role, arg)

                logger.info(
                    "debate_argument_received",
                    session_id=session_id,
                    role=role,
                    vote=arg.vote,
                    confidence=arg.confidence,
                )

            except Exception as exc:
                logger.error(
                    "debate_agent_error",
                    session_id=session_id,
                    role=role,
                    error=str(exc),
                )
                # Agent that fails to respond abstains with zero confidence
                arguments.append(
                    DebateArgument(
                        role=role,
                        argument=f"Error: {str(exc)[:200]}",
                        vote="ABSTAIN",
                        confidence=0.0,
                    )
                )

        # Tally votes
        for_votes = [a for a in arguments if a.vote == "FOR"]
        against_votes = [a for a in arguments if a.vote == "AGAINST"]
        abstain_votes = [a for a in arguments if a.vote == "ABSTAIN"]

        # Consensus score = weighted average of confidences for FOR votes
        if for_votes:
            total_confidence = sum(a.confidence for a in for_votes)
            consensus_score = round(total_confidence / len(arguments), 4)
        else:
            consensus_score = 0.0

        # Decision: APPROVED if consensus_score > 0.6 AND at least 3 FOR
        decision = (
            "APPROVED"
            if consensus_score > self.APPROVAL_THRESHOLD
            and len(for_votes) >= self.MIN_FOR_VOTES
            else "REJECTED"
        )

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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
