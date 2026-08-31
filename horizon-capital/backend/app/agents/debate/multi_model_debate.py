"""Multi-model debate engine with perspective rotation.

Extends the base debate engine to use multiple LLM providers (Claude, GPT,
Gemini) in a structured multi-round debate. Each provider is assigned a
distinct debater role (bull, bear, risk, neutral) to reduce groupthink
and produce more balanced trade decisions.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Role prompts + user-prompt builder single-sourced from debate_engine so the two
# engines can never drift apart. (Also brings in the Risk Metrics and target/stop
# sections this file's old duplicated builder silently lacked.)
from app.agents.debate.debate_engine import DEBATER_ROLES, _build_user_prompt
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType
from app.llm.base_provider import BaseLLMProvider
from app.llm.provider_registry import ProviderRegistry


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
    decision: str  # APPROVED, REJECTED, INCONCLUSIVE
    consensus_score: float
    arguments: list[DebateArgument] = field(default_factory=list)
    for_count: int = 0
    against_count: int = 0
    abstain_count: int = 0
    error_count: int = 0  # debaters whose provider call failed outright


logger = get_logger("debate.multi_model")

# Rate-limit retry policy for debater calls.
_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_BASE_DELAY = 2.0
_RATE_LIMIT_MAX_DELAY = 20.0


# ------------------------------------------------------------------
# Perspective rotation matrix
# ------------------------------------------------------------------
# In round 2, each debater argues from a DIFFERENT perspective than
# round 1. This forces models to consider opposing viewpoints and
# reduces confirmation bias.

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

def _apply_debate_model(provider: BaseLLMProvider) -> BaseLLMProvider:
    """Swap in ``settings.debate_model`` when one is configured.

    A debate is ~8 calls per signal, so the flagship model burns an org's
    tokens-per-minute allowance fast; a small model keeps every debater
    answering. Empty setting = provider default. The name must belong to the
    provider actually serving the debate.
    """
    model = (settings.debate_model or "").strip()
    if not model:
        return provider
    try:
        return provider.with_model(model)
    except Exception as exc:
        logger.warning(
            "debate_model_override_failed",
            provider=provider.provider_name, model=model, error=str(exc),
        )
        return provider


def _rate_limit_delay(exc: Exception, attempt: int) -> float:
    """Seconds to wait before retrying a rate-limited call.

    Providers state the wait in the error ("try again in 1.235s"); honour it
    when present, otherwise back off exponentially.
    """
    match = re.search(r"try again in (\d+(?:\.\d+)?)(m?s)", str(exc), re.IGNORECASE)
    if match:
        value = float(match.group(1))
        seconds = value / 1000.0 if match.group(2).lower() == "ms" else value
        return min(max(seconds + 0.25, 0.5), _RATE_LIMIT_MAX_DELAY)
    return min(_RATE_LIMIT_BASE_DELAY * (2 ** attempt), _RATE_LIMIT_MAX_DELAY)


def _is_rate_limited(exc: Exception) -> bool:
    blob = str(exc).lower()
    return "429" in blob or "rate limit" in blob or "rate_limit" in blob


async def _call_provider(
    provider: BaseLLMProvider,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Call any LLM provider and parse the structured response.

    Each agent produces a JSON response with {argument, vote, confidence}.
    The structured format enables automated aggregation across providers.

    A failed call returns vote ``ERROR``, NOT ``ABSTAIN``: an abstention is a
    debater's considered position and counts toward consensus, while a 429 is
    the debater never having spoken. Conflating them let rate-limit noise vote
    trades down.
    """
    messages = [{"role": "user", "content": user_prompt}]

    last_exc: Exception | None = None
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            raw = await provider.complete(
                system_prompt=system_prompt,
                messages=messages,
                temperature=0.7,
            )
            return _parse_debate_response(raw)
        except Exception as exc:
            last_exc = exc
            if attempt < _RATE_LIMIT_RETRIES and _is_rate_limited(exc):
                delay = _rate_limit_delay(exc, attempt)
                logger.warning(
                    "provider_rate_limited_retrying",
                    provider=provider.provider_name,
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                )
                await asyncio.sleep(delay)
                continue
            break

    logger.error(
        "provider_call_error",
        provider=provider.provider_name, error=str(last_exc),
    )
    return {
        "argument": f"Error from {provider.provider_name}: {str(last_exc)[:200]}",
        "vote": "ERROR",
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

    Round 1: Each debater (role) argues from their assigned perspective.
    Different LLM providers are assigned to different roles for diversity.

    Round 2 (perspective rotation): Each debater argues from the OPPOSITE
    perspective, having seen round 1 arguments. This forces genuine
    consideration of counterarguments and reduces groupthink.

    Final vote: All arguments from both rounds are aggregated.
    Confidence-weighted consensus determines the decision.

    Approval requires:
    - consensus_score > 0.55
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

    # Role-to-config-field mapping for pinning lookups
    _ROLE_PIN_FIELDS: dict[str, str] = {
        "STRATEGY": "debate_role_strategy",
        "RISK": "debate_role_risk",
        "SENTIMENT": "debate_role_sentiment",
        "PORTFOLIO": "debate_role_portfolio",
    }

    def _assign_providers(
        self,
        allowed_providers: list[str] | None = None,
    ) -> dict[str, BaseLLMProvider]:
        """Assign available LLM providers to debater roles.

        Supports two assignment modes:

        1. **Pinned** -- When ``settings.debate_role_<role>`` is set to a
           specific provider name (e.g. ``"claude"``), that role always uses
           the named provider.  If the pinned provider is not available, falls
           back to round-robin.
        2. **Auto (round-robin)** -- Distributes available providers across
           unpinned roles so different model families argue different
           perspectives.  With a single provider, all roles get that provider.

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

        # First pass: honour pinned roles from config
        rr_index = 0
        for role in roles:
            pin_field = self._ROLE_PIN_FIELDS.get(role, "")
            pinned_name = getattr(settings, pin_field, "auto") if pin_field else "auto"

            if pinned_name and pinned_name != "auto":
                pinned_provider = self.registry.get_provider(pinned_name)
                if pinned_provider is not None:
                    providers[role] = pinned_provider
                    continue
                # Pinned provider unavailable -- fall through to round-robin
                logger.warning(
                    "pinned_provider_unavailable",
                    role=role,
                    pinned=pinned_name,
                    available=available,
                )

            # Round-robin assignment
            provider_name = available[rr_index % len(available)]
            provider = self.registry.get_provider(provider_name)
            if provider is not None:
                providers[role] = provider
            rr_index += 1

        return {role: _apply_debate_model(p) for role, p in providers.items()}

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
        """Execute a multi-model, multi-round debate."""
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
        # Round 2: Perspective rotation
        # Each debater sees round 1 arguments and argues from the
        # OPPOSITE perspective. This reduces groupthink.
        # ------------------------------------------------------------------
        if self.max_rounds >= 2:
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
        # Aggregate votes (confidence-weighted consensus)
        # ------------------------------------------------------------------
        # A failed provider call is not a vote. Counting errors as abstentions
        # let one rate-limited minute reject every trade in the queue.
        error_votes = [a for a in all_arguments if a.vote == "ERROR"]
        spoke = [a for a in all_arguments if a.vote != "ERROR"]
        for_votes = [a for a in spoke if a.vote == "FOR"]
        against_votes = [a for a in spoke if a.vote == "AGAINST"]
        abstain_votes = [a for a in spoke if a.vote == "ABSTAIN"]

        total_non_abstain = len(for_votes) + len(against_votes)

        # Confidence-weighted consensus score
        if for_votes:
            total_for_confidence = sum(a.confidence for a in for_votes)
            total_confidence = sum(a.confidence for a in spoke if a.vote != "ABSTAIN")
            consensus_score = round(
                total_for_confidence / total_confidence if total_confidence > 0 else 0.0,
                4,
            )
        else:
            consensus_score = 0.0

        # Decision: confidence-weighted FOR ratio > threshold AND raw FOR ratio > MIN_FOR_RATIO
        for_ratio = len(for_votes) / total_non_abstain if total_non_abstain > 0 else 0.0
        if not spoke:
            # Nobody actually debated — say so rather than reporting a verdict
            # nobody reached. Callers treat anything != APPROVED as "don't act".
            decision = "INCONCLUSIVE"
            logger.warning(
                "debate_inconclusive_all_providers_failed",
                symbol=symbol, errors=len(error_votes),
            )
        else:
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
            error_count=len(error_votes),
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

        In rounds > 1, each agent sees the previous round's arguments
        appended to the user prompt, enabling genuine deliberation.
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
                "You have now seen the other debaters' arguments, and you have been "
                "assigned a NEW role for this round (see your role instructions). Argue "
                "from that new perspective, engaging with the strongest opposing argument "
                "above. Change your vote if the evidence warrants it — do not repeat your "
                "previous round.\n"
                "Respond with ONLY a JSON object — no markdown fences, no prose:\n"
                '{"argument": "<2-4 sentence reasoning>", "vote": "FOR" | "AGAINST" |'
                ' "ABSTAIN", "confidence": <float 0.0-1.0>}'
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
