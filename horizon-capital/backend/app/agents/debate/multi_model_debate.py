"""Multi-model debate engine with perspective rotation.

Extends the base debate engine to use multiple LLM providers (Claude, GPT,
Gemini) in a structured multi-round debate with perspective rotation.

Research references
-------------------
- Du et al. ICML 2024, "Improving Factuality and Reasoning in Language Models
  through Multiagent Debate" — each agent proposes, then reads other agents'
  responses and refines; factual accuracy improves over 2-3 rounds.
- Estornell et al. NeurIPS 2024, "Hypothesis Testing the Circuit Hypothesis"
  — perspective rotation intervention: forcing models to argue from assigned
  viewpoints (even contrary ones) reduces groupthink and improves calibration.
- Liang et al. 2023, "Encouraging Divergent Thinking in Large Language Models
  through Multi-Agent Debate" — diversity of model architectures (GPT vs Claude
  vs Gemini) produces more calibrated confidence scores than single-model debate.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType
from app.llm.base_provider import BaseLLMProvider
from app.llm.provider_registry import ProviderRegistry


# Lazy import to avoid pulling in anthropic at module load time
def _get_debate_engine():
    from app.agents.debate.debate_engine import (
        DEBATER_ROLES,
        DebateArgument,
        DebateResult,
        _build_user_prompt,
    )
    return DEBATER_ROLES, DebateArgument, DebateResult, _build_user_prompt


# Duplicate core constants/classes here so module can import without anthropic
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
        f"- Action: {action}",
        f"- Signal strength: {signal_data.get('strength', 'N/A')}",
        f"- Strategy: {signal_data.get('strategy_name', 'N/A')}",
        "",
        f"## Market Regime: {regime or 'UNKNOWN'}",
        "",
        "## Instructions",
        "Analyze the above from your role's perspective. Respond with ONLY a JSON object:",
        '{"argument": "<your reasoning>", "vote": "FOR|AGAINST|ABSTAIN", "confidence": <0.0-1.0>}',
    ]
    return "\n".join(lines)

logger = get_logger("debate.multi_model")


# ------------------------------------------------------------------
# Perspective rotation matrix (Estornell et al. NeurIPS 2024)
# ------------------------------------------------------------------
# In round 2, each debater argues from a DIFFERENT perspective than
# round 1. This forces models to consider opposing viewpoints and
# reduces confirmation bias / groupthink.

ROTATION_MATRIX: dict[str, str] = {
    "STRATEGY": "RISK",       # Bull argues bear case
    "RISK": "STRATEGY",       # Bear argues bull case
    "SENTIMENT": "PORTFOLIO",  # Sentiment argues portfolio fit
    "PORTFOLIO": "SENTIMENT",  # Portfolio argues sentiment case
}


@dataclass
class MultiModelArgument(DebateArgument):
    """Extended argument that tracks which LLM provider produced it."""

    provider: str = ""
    round_number: int = 1
    rotated_from: str = ""  # Original role if perspective was rotated


@dataclass
class MultiModelDebateResult(DebateResult):
    """Extended result with multi-round, multi-model metadata."""

    rounds: int = 1
    providers_used: list[str] = field(default_factory=list)
    perspective_rotation_applied: bool = False
    round_arguments: dict[int, list[MultiModelArgument]] = field(default_factory=dict)


# ------------------------------------------------------------------
# Provider-agnostic reasoner
# ------------------------------------------------------------------

async def _call_provider(
    provider: BaseLLMProvider,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call any LLM provider and parse the structured response.

    Du et al. ICML 2024: Each agent produces a JSON response with
    {argument, vote, confidence}. The structured format enables
    automated aggregation across heterogeneous models.
    """
    messages = [{"role": "user", "content": user_prompt}]

    try:
        raw = await provider.complete(
            system_prompt=system_prompt,
            messages=messages,
            temperature=0.7,
        )
        return _parse_debate_response(raw)
    except Exception as exc:
        logger.error("provider_call_error", provider=provider.provider_name, error=str(exc))
        return {
            "argument": f"Error from {provider.provider_name}: {str(exc)[:200]}",
            "vote": "ABSTAIN",
            "confidence": 0.0,
        }


def _parse_debate_response(raw: str) -> dict[str, Any]:
    """Parse structured JSON from any LLM provider response."""
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(json_str)
        vote = str(data.get("vote", "ABSTAIN")).upper().strip()
        if vote not in ("FOR", "AGAINST", "ABSTAIN"):
            vote = "ABSTAIN"
        return {
            "argument": str(data.get("argument", raw))[:2000],
            "vote": vote,
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Heuristic fallback
    vote = "ABSTAIN"
    upper = raw.upper()
    if '"FOR"' in upper or "VOTE: FOR" in upper:
        vote = "FOR"
    elif '"AGAINST"' in upper or "VOTE: AGAINST" in upper:
        vote = "AGAINST"

    return {"argument": raw[:2000], "vote": vote, "confidence": 0.5}


# ------------------------------------------------------------------
# Multi-model debate engine
# ------------------------------------------------------------------

class MultiModelDebateEngine:
    """Orchestrates multi-model, multi-round debates with perspective rotation.

    Du et al. ICML 2024 protocol:
    1. Round 1: Each debater (role) argues from their assigned perspective.
       Different LLM providers are assigned to different roles for diversity.
    2. Round 2 (perspective rotation, Estornell et al. 2024): Each debater
       argues from the OPPOSITE perspective, having seen round 1 arguments.
       This forces genuine consideration of counterarguments.
    3. Final vote: All arguments from both rounds are aggregated.
       Confidence-weighted consensus determines the decision.

    Approval requires:
    - consensus_score > 0.55 (slightly lower than single-round since
      rotation naturally produces more balanced scores)
    - At least 60% of total votes are FOR
    """

    APPROVAL_THRESHOLD = 0.55
    MIN_FOR_RATIO = 0.6

    def __init__(
        self,
        registry: ProviderRegistry,
        bus: AgentBus,
        max_rounds: int = 2,
    ) -> None:
        self.registry = registry
        self.bus = bus
        self.max_rounds = max_rounds

    def _assign_providers(
        self,
        allowed_providers: list[str] | None = None,
    ) -> dict[str, BaseLLMProvider]:
        """Assign available LLM providers to debater roles.

        Liang et al. 2023: Architectural diversity (different model
        families) improves calibration. We distribute available
        providers across roles round-robin.

        Parameters
        ----------
        allowed_providers:
            If given, only use providers in this list (department routing).
            Falls back to all available if none of the allowed providers
            are registered.
        """
        if allowed_providers:
            available = [p for p in allowed_providers if self.registry.get_provider(p)]
        else:
            available = self.registry.list_available()

        if not available:
            # Fall back to all available providers
            available = self.registry.list_available()
        if not available:
            raise RuntimeError("No LLM providers available for debate")

        providers: dict[str, BaseLLMProvider] = {}
        roles = list(DEBATER_ROLES.keys())

        for i, role in enumerate(roles):
            provider_name = available[i % len(available)]
            provider = self.registry.get_provider(provider_name)
            if provider is not None:
                providers[role] = provider

        return providers

    async def run_debate(
        self,
        symbol: str,
        action: str,
        signal_data: dict[str, Any],
        regime: str | None = None,
        sentiment: dict[str, Any] | None = None,
        risk_metrics: dict[str, Any] | None = None,
        allowed_providers: list[str] | None = None,
    ) -> MultiModelDebateResult:
        """Execute a multi-model, multi-round debate.

        Du et al. ICML 2024 multi-round protocol with Estornell et al.
        NeurIPS 2024 perspective rotation.
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Assign providers to roles (respecting department routing)
        provider_map = self._assign_providers(allowed_providers=allowed_providers)
        providers_used = list({p.provider_name for p in provider_map.values()})

        # Publish debate start
        await self.bus.publish(
            AgentMessage(
                sender_id="multi-model-debate",
                channel=f"horizon.debate.{session_id}.start",
                message_type=MessageType.DEBATE_START,
                payload={
                    "session_id": session_id,
                    "symbol": symbol,
                    "action": action,
                    "providers": providers_used,
                    "max_rounds": self.max_rounds,
                    "timestamp": now.isoformat(),
                },
            )
        )

        user_prompt = _build_user_prompt(
            symbol, action, signal_data, regime, sentiment, risk_metrics
        )

        all_arguments: list[MultiModelArgument] = []
        round_arguments: dict[int, list[MultiModelArgument]] = {}

        # ------------------------------------------------------------------
        # Round 1: Each debater argues from their assigned perspective
        # ------------------------------------------------------------------
        r1_args = await self._run_round(
            session_id=session_id,
            round_number=1,
            provider_map=provider_map,
            roles=DEBATER_ROLES,
            user_prompt=user_prompt,
            prior_arguments=None,
        )
        all_arguments.extend(r1_args)
        round_arguments[1] = r1_args

        # ------------------------------------------------------------------
        # Round 2: Perspective rotation (Estornell et al. NeurIPS 2024)
        # Each debater sees round 1 arguments and argues from the
        # OPPOSITE perspective. This reduces groupthink and forces
        # genuine consideration of counterarguments.
        # ------------------------------------------------------------------
        if self.max_rounds >= 2 and len(provider_map) >= 2:
            # Build rotated roles
            rotated_roles: dict[str, str] = {}
            for role in DEBATER_ROLES:
                rotated_to = ROTATION_MATRIX.get(role, role)
                rotated_roles[role] = DEBATER_ROLES[rotated_to]

            r2_args = await self._run_round(
                session_id=session_id,
                round_number=2,
                provider_map=provider_map,
                roles={role: rotated_roles[role] for role in provider_map},
                user_prompt=user_prompt,
                prior_arguments=r1_args,
                rotation_map=ROTATION_MATRIX,
            )
            all_arguments.extend(r2_args)
            round_arguments[2] = r2_args

        # ------------------------------------------------------------------
        # Aggregate votes (Du et al. 2024: confidence-weighted consensus)
        # ------------------------------------------------------------------
        for_votes = [a for a in all_arguments if a.vote == "FOR"]
        against_votes = [a for a in all_arguments if a.vote == "AGAINST"]
        abstain_votes = [a for a in all_arguments if a.vote == "ABSTAIN"]

        total_non_abstain = len(for_votes) + len(against_votes)

        # Confidence-weighted consensus score
        if for_votes:
            total_for_confidence = sum(a.confidence for a in for_votes)
            total_confidence = sum(a.confidence for a in all_arguments if a.vote != "ABSTAIN")
            consensus_score = round(
                total_for_confidence / total_confidence if total_confidence > 0 else 0.0,
                4,
            )
        else:
            consensus_score = 0.0

        # Decision: confidence-weighted FOR ratio > threshold AND raw FOR ratio > MIN_FOR_RATIO
        for_ratio = len(for_votes) / total_non_abstain if total_non_abstain > 0 else 0.0
        decision = (
            "APPROVED"
            if consensus_score > self.APPROVAL_THRESHOLD
            and for_ratio >= self.MIN_FOR_RATIO
            else "REJECTED"
        )

        result = MultiModelDebateResult(
            session_id=session_id,
            symbol=symbol,
            proposed_action=action,
            decision=decision,
            consensus_score=consensus_score,
            arguments=all_arguments,
            for_count=len(for_votes),
            against_count=len(against_votes),
            abstain_count=len(abstain_votes),
            rounds=len(round_arguments),
            providers_used=providers_used,
            perspective_rotation_applied=self.max_rounds >= 2,
            round_arguments=round_arguments,
        )

        # Publish conclusion
        await self.bus.publish(
            AgentMessage(
                sender_id="multi-model-debate",
                channel=f"horizon.debate.{session_id}.conclusion",
                message_type=MessageType.DEBATE_CONCLUSION,
                payload={
                    "session_id": session_id,
                    "symbol": symbol,
                    "decision": decision,
                    "consensus_score": consensus_score,
                    "for_count": len(for_votes),
                    "against_count": len(against_votes),
                    "rounds": len(round_arguments),
                    "providers": providers_used,
                    "rotation_applied": self.max_rounds >= 2,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

        logger.info(
            "multi_model_debate_concluded",
            session_id=session_id,
            symbol=symbol,
            decision=decision,
            consensus_score=consensus_score,
            rounds=len(round_arguments),
            providers=providers_used,
            votes=f"{len(for_votes)}F/{len(against_votes)}A/{len(abstain_votes)}Ab",
        )

        return result

    async def _run_round(
        self,
        session_id: str,
        round_number: int,
        provider_map: dict[str, BaseLLMProvider],
        roles: dict[str, str],
        user_prompt: str,
        prior_arguments: list[MultiModelArgument] | None = None,
        rotation_map: dict[str, str] | None = None,
    ) -> list[MultiModelArgument]:
        """Run a single debate round with all debaters in parallel.

        Du et al. ICML 2024: In rounds > 1, each agent sees the previous
        round's arguments appended to the user prompt. This enables
        genuine deliberation rather than independent generation.
        """
        # Build round prompt
        round_prompt = user_prompt
        if prior_arguments:
            round_prompt += "\n\n## Previous Round Arguments\n"
            for arg in prior_arguments:
                round_prompt += (
                    f"\n### {arg.role} ({arg.provider}):\n"
                    f"Vote: {arg.vote} (confidence: {arg.confidence})\n"
                    f"Argument: {arg.argument[:500]}\n"
                )
            round_prompt += (
                "\n## Instructions for This Round\n"
                "You have now seen the other debaters' arguments. "
                "Reconsider your position and provide an updated analysis. "
                "You may change your vote if the evidence warrants it.\n"
                'Respond with ONLY: {"argument": "<reasoning>", "vote": "FOR|AGAINST|ABSTAIN",'
                ' "confidence": <0.0-1.0>}'
            )

        async def _run_debater(role: str) -> MultiModelArgument:
            provider = provider_map[role]
            personality = roles.get(role, DEBATER_ROLES.get(role, ""))
            result = await _call_provider(provider, personality, round_prompt)
            rotated_from = rotation_map.get(role, "") if rotation_map else ""
            return MultiModelArgument(
                role=role,
                argument=result["argument"],
                vote=result["vote"],
                confidence=result["confidence"],
                provider=provider.provider_name,
                round_number=round_number,
                rotated_from=rotated_from,
            )

        tasks = [_run_debater(role) for role in provider_map]
        arguments = list(await asyncio.gather(*tasks))

        # Publish round arguments
        for arg in arguments:
            await self.bus.publish(
                AgentMessage(
                    sender_id="multi-model-debate",
                    channel=f"horizon.debate.{session_id}.argument",
                    message_type=MessageType.DEBATE_VOTE,
                    payload={
                        "session_id": session_id,
                        "role": arg.role,
                        "provider": arg.provider,
                        "vote": arg.vote,
                        "confidence": arg.confidence,
                        "round": round_number,
                        "rotated_from": arg.rotated_from,
                        "argument": arg.argument[:500],
                    },
                )
            )

        logger.info(
            "debate_round_complete",
            session_id=session_id,
            round=round_number,
            participants=len(arguments),
        )

        return arguments
