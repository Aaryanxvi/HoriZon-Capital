"""AI CIO Agent -- strategic oversight, crisis response, and last-resort override.

Only active when CIO_MODE=AI. Three operating modes:
  Mode A: Strategic advisory every 15 min (continuous, passive)
  Mode B: Crisis response on RISK_ALERT HIGH/CRITICAL or kill-switch trigger
  Mode C: Override directive — only when kill switch + confidence >= threshold
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from datetime import UTC, datetime

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType
from app.llm.provider_registry import provider_registry

logger = get_logger("agent.cio")

CIO_ADVISORY_INTERVAL = 900  # 15 minutes
CIO_OVERRIDE_CONFIDENCE_THRESHOLD = 0.85
CIO_CIRCUIT_BREAKER_FAILURES = 3
CIO_CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes
CIO_LLM_TIMEOUT_S = 60  # seconds before LLM call is abandoned


def _get_session_factory():
    """Lazy session factory lookup -- avoids importing database at module level."""
    from app.core.runtime import get_session_factory

    return get_session_factory()


# ---------------------------------------------------------------------------
# LLM system prompts
# ---------------------------------------------------------------------------

MODE_A_SYSTEM_PROMPT = """\
You are the Chief Investment Officer (CIO) of Horizon Capital, an AI-driven hedge fund, \
giving your routine strategic advisory.

Base your assessment ONLY on the portfolio digest given below -- do not invent positions, \
prices, or events that are not in it. If the digest is empty or thin, say so in "summary" \
and keep "outlook" at "neutral" rather than guessing.

Respond with ONLY a JSON object, no markdown fences, no prose, with exactly these fields:
- "outlook": one of "bullish", "neutral", "bearish"
- "summary": 1-3 sentence assessment of current portfolio state
- "recommended_adjustments": list of objects with keys:
    "symbol" (string, e.g. "AAPL" or "PORTFOLIO"),
    "action" (string, e.g. "TRIM", "ADD", "EXIT", "HOLD"),
    "reason" (string, 1 sentence). Empty list if no changes are warranted.
- "risk_flags": list of strings (concerns to watch), empty list if none

Portfolio digest:
{digest}
"""

MODE_B_SYSTEM_PROMPT = """\
You are the Chief Investment Officer (CIO) of Horizon Capital responding to a live crisis \
alert. A risk event has been triggered -- read the trigger and payload below carefully, they \
are the ground truth for this incident. Do not invent details beyond what they state.

Respond with ONLY a JSON object, no markdown fences, no prose, with exactly these fields:
- "stance": one of "HOLD", "REDUCE", "HALT" -- choose HALT only when the payload shows \
severe, ongoing risk; choose HOLD when the situation does not warrant new action.
- "confidence": float between 0.0 and 1.0, calibrated to how clear-cut the evidence is. \
A HALT stance with confidence >= 0.85 during an active kill switch triggers an AUTOMATED \
firm-wide trading halt -- reserve that combination for unambiguous emergencies.
- "reasoning": 1-3 sentence explanation grounded in the trigger/payload/digest below
- "specific_actions": list of strings (concrete steps to take), empty list if none

Trigger: {trigger}
Alert payload: {payload}

Portfolio digest:
{digest}
"""


class CIOAgent(BaseAgent):
    """AI Chief Investment Officer -- strategic advisory, crisis response, override.

    Mode A runs on a 15-minute loop. Mode B fires on incoming risk alerts.
    Mode C fires only when kill switch is active AND LLM confidence >= threshold.
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="cio-agent-1",
            agent_type="cio",
            bus=bus,
        )
        self._alerts: deque[dict] = deque(maxlen=256)
        self._kill_switch_active: bool = False
        self._pending_halt_confirmation: bool = False
        self._last_override: dict | None = None

        # Circuit breaker state for LLM calls
        self._llm_failures: int = 0
        self._llm_circuit_open_until: float = 0

        # Tracked background persistence tasks (prevents GC before completion)
        self._persist_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.risk.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.RISK_ALERT:
            self._alerts.append(message.payload)
            severity = message.payload.get("severity", "")
            action = message.payload.get("action", "")

            if action == "KILL_SWITCH_CLEARED":
                self._kill_switch_active = False
                logger.info("cio_kill_switch_cleared")
                return
            elif action == "KILL_SWITCH_TRIGGERED":
                self._kill_switch_active = True
                logger.warning("cio_kill_switch_activated")
                trigger: str | None = "KILL_SWITCH"
            elif severity in ("HIGH", "CRITICAL", "EMERGENCY"):
                trigger = "RISK_ALERT"
            else:
                trigger = None

            if trigger is not None:
                task = asyncio.create_task(
                    self._run_mode_b(message.payload, trigger=trigger)
                )
                self._persist_tasks.add(task)
                task.add_done_callback(self._persist_tasks.discard)

    async def run(self) -> None:
        """Mode A loop: publish strategic advisory every CIO_ADVISORY_INTERVAL.

        Initial 30s delay gives data workers time to populate prices.
        """
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._run_mode_a()
            except Exception as exc:
                logger.error("cio_mode_a_error", error=str(exc))
            await asyncio.sleep(CIO_ADVISORY_INTERVAL)

    # ------------------------------------------------------------------
    # Mode A: Strategic Advisory
    # ------------------------------------------------------------------

    async def _run_mode_a(self) -> None:
        """Generate and publish a strategic advisory via LLM."""
        provider = self._get_provider()
        if provider is None:
            return

        digest = await self._build_portfolio_digest()

        try:
            raw = await asyncio.wait_for(
                provider.complete(
                    system_prompt=MODE_A_SYSTEM_PROMPT.format(
                        digest=json.dumps(digest, default=str),
                    ),
                    messages=[{"role": "user", "content": "Produce your advisory now."}],
                    temperature=0.4,
                ),
                timeout=CIO_LLM_TIMEOUT_S,
            )
            self._reset_circuit_breaker()
        except TimeoutError:
            logger.error("cio_mode_a_llm_timeout", timeout_s=CIO_LLM_TIMEOUT_S)
            self._record_failure()
            return
        except Exception as exc:
            logger.error("cio_mode_a_llm_error", error=str(exc))
            self._record_failure()
            return

        advisory = self._parse_advisory(raw)
        if advisory is None:
            return

        # Publish CIO_ADVISORY
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_ADVISORY,
            payload={
                "outlook": advisory.get("outlook", "neutral"),
                "summary": advisory.get("summary", ""),
                "recommended_adjustments": advisory.get("recommended_adjustments", []),
                "risk_flags": advisory.get("risk_flags", []),
                "is_crisis": False,
                "provider": provider.provider_name,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await self.bus.publish(msg)

        self._persist_advisory_sync(advisory, provider.provider_name, "scheduled")

        logger.info(
            "cio_advisory_published",
            outlook=advisory.get("outlook"),
            provider=provider.provider_name,
        )

    # ------------------------------------------------------------------
    # Mode B: Crisis Response
    # ------------------------------------------------------------------

    async def _run_mode_b(self, trigger_payload: dict, trigger: str) -> None:
        """Assess a crisis situation via LLM and publish crisis advisory."""
        provider = self._get_provider()
        if provider is None:
            return

        digest = await self._build_portfolio_digest()

        rendered_prompt = MODE_B_SYSTEM_PROMPT.format(
            trigger=trigger,
            payload=json.dumps(trigger_payload, default=str),
            digest=json.dumps(digest, default=str),
        )

        try:
            raw = await asyncio.wait_for(
                provider.complete(
                    system_prompt=rendered_prompt,
                    messages=[{"role": "user", "content": "Assess and respond now."}],
                    temperature=0.2,
                ),
                timeout=CIO_LLM_TIMEOUT_S,
            )
            self._reset_circuit_breaker()
        except TimeoutError:
            logger.error("cio_mode_b_llm_timeout", timeout_s=CIO_LLM_TIMEOUT_S)
            self._record_failure()
            return
        except Exception as exc:
            logger.error("cio_mode_b_llm_error", error=str(exc))
            self._record_failure()
            return

        crisis = self._parse_crisis_response(raw)
        if crisis is None:
            return

        stance = crisis.get("stance", "HOLD")
        confidence = float(crisis.get("confidence", 0.0))

        # Publish crisis advisory
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_ADVISORY,
            payload={
                "stance": stance,
                "confidence": confidence,
                "reasoning": crisis.get("reasoning", ""),
                "specific_actions": crisis.get("specific_actions", []),
                "is_crisis": True,
                "trigger": trigger,
                "provider": provider.provider_name,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await self.bus.publish(msg)

        self._persist_advisory_sync(
            {
                "outlook": stance.lower(),
                "summary": crisis.get("reasoning", ""),
                "recommended_adjustments": crisis.get("specific_actions", []),
                "risk_flags": [trigger],
            },
            provider.provider_name,
            trigger,
        )

        logger.warning(
            "cio_crisis_advisory",
            stance=stance,
            confidence=confidence,
            trigger=trigger,
        )

        # Mode C: Override if kill switch active + HALT + high confidence
        if (
            self._kill_switch_active
            and stance == "HALT"
            and confidence >= CIO_OVERRIDE_CONFIDENCE_THRESHOLD
        ):
            await self._run_mode_c(crisis, trigger_payload, provider,
                                   rendered_prompt=rendered_prompt, raw_response=raw)

    # ------------------------------------------------------------------
    # Mode C: Override Directive
    # ------------------------------------------------------------------

    async def _run_mode_c(
        self,
        crisis_result: dict,
        trigger_payload: dict,
        provider,
        rendered_prompt: str = "",
        raw_response: str = "",
    ) -> None:
        """Publish a CIO override directive — last-resort halt command."""
        override_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        audit = {
            "override_id": override_id,
            "timestamp": now.isoformat(),
            "trigger": "KILL_SWITCH",
            "confidence": crisis_result.get("confidence", 0.0),
            "actions": crisis_result.get("specific_actions", []),
            "reasoning": crisis_result.get("reasoning", ""),
            "provider": provider.provider_name,
        }

        self._last_override = audit
        self._pending_halt_confirmation = True

        # Publish CIO_OVERRIDE
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_OVERRIDE,
            payload=audit,
        )
        await self.bus.publish(msg)

        self._persist_override_sync(audit, crisis_result, trigger_payload, provider.provider_name,
                                    rendered_prompt=rendered_prompt, raw_response=raw_response)

        logger.critical(
            "cio_override_issued",
            override_id=override_id,
            confidence=audit["confidence"],
        )

    # ------------------------------------------------------------------
    # Provider selection + circuit breaker
    # ------------------------------------------------------------------

    def _get_provider(self):
        """Get the best available LLM provider, respecting circuit breaker."""
        # Check circuit breaker
        if self._llm_circuit_open_until > 0:
            if time.monotonic() < self._llm_circuit_open_until:
                logger.warning("cio_llm_circuit_open", until=self._llm_circuit_open_until)
                return None
            # Cooldown expired — half-open
            self._llm_circuit_open_until = 0

        # Per-agent override takes precedence over department default.
        providers = provider_registry.get_providers_for_department("executive")
        if not providers:
            return None

        # Prefer claude > openai > gemini for default
        priority = {"claude": 0, "openai": 1, "gemini": 2}
        providers.sort(key=lambda p: priority.get(p.provider_name, 99))
        default_name = providers[0].provider_name
        # Resolve final provider via per-agent override hook.
        return provider_registry.get_provider_for_agent(
            self.agent_id, default_provider=default_name,
        )

    def _record_failure(self) -> None:
        """Record an LLM failure; open circuit if threshold exceeded."""
        self._llm_failures += 1
        if self._llm_failures >= CIO_CIRCUIT_BREAKER_FAILURES:
            self._llm_circuit_open_until = time.monotonic() + CIO_CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                "cio_llm_circuit_opened",
                failures=self._llm_failures,
                cooldown=CIO_CIRCUIT_BREAKER_COOLDOWN,
            )

    def _reset_circuit_breaker(self) -> None:
        """Reset failure counter on successful LLM call."""
        self._llm_failures = 0
        self._llm_circuit_open_until = 0

    # ------------------------------------------------------------------
    # Portfolio digest
    # ------------------------------------------------------------------

    async def _build_portfolio_digest(self) -> dict:
        """Gather portfolio state from KV and DB for LLM context."""
        digest: dict = {}
        try:
            from app.core.kv_store import get_kv_store

            kv = get_kv_store()
            nav = await kv.get("horizon:portfolio:nav")
            if nav is not None:
                digest["nav"] = nav
        except Exception as exc:
            logger.debug("cio_digest_kv_error", error=str(exc))

        try:
            from sqlalchemy import text

            async with _get_session_factory()() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
                )
                row = result.scalar()
                digest["open_positions"] = row or 0
        except Exception as exc:
            logger.debug("cio_digest_db_error", error=str(exc))

        return digest

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _salvage_json(raw: str) -> dict | None:
        """Parse JSON from LLM output, tolerating fences and prose preambles."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            return None

    def _parse_advisory(self, raw: str) -> dict | None:
        """Parse Mode A advisory JSON from LLM response."""
        result = self._salvage_json(raw)
        if result is None:
            logger.error("cio_advisory_parse_error", raw=raw[:200])
        return result

    def _parse_crisis_response(self, raw: str) -> dict | None:
        """Parse Mode B crisis JSON from LLM response."""
        result = self._salvage_json(raw)
        if result is None:
            logger.error("cio_crisis_parse_error", raw=raw[:200])
        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_advisory_sync(self, data: dict, provider: str, trigger: str) -> None:
        """Schedule advisory persistence as a tracked background task."""
        try:
            task = asyncio.create_task(self._persist_advisory(data, provider, trigger))
        except RuntimeError:
            return
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)

    async def _persist_advisory(self, data: dict, provider: str, trigger: str) -> None:
        """Write advisory to the cio_advisories table."""
        try:
            from sqlalchemy import text

            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO cio_advisories
                            (id, timestamp, outlook, summary,
                             recommended_adjustments, risk_flags,
                             provider, trigger)
                        VALUES
                            (:id, :ts, :outlook, :summary,
                             :adjustments, :flags, :provider, :trigger)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "ts": datetime.now(UTC).isoformat(),
                        "outlook": data.get("outlook", "neutral"),
                        "summary": data.get("summary", ""),
                        "adjustments": json.dumps(
                            data.get("recommended_adjustments", [])
                        ),
                        "flags": json.dumps(data.get("risk_flags", [])),
                        "provider": provider,
                        "trigger": trigger,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error("cio_persist_advisory_error", error=str(exc))

    def _persist_override_sync(
        self,
        audit: dict,
        crisis: dict,
        trigger_payload: dict,
        provider: str,
        rendered_prompt: str = "",
        raw_response: str = "",
    ) -> None:
        """Schedule override persistence as a tracked background task."""
        try:
            task = asyncio.create_task(
                self._persist_override(audit, crisis, trigger_payload, provider,
                                       rendered_prompt, raw_response)
            )
        except RuntimeError:
            return
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)

    async def _persist_override(
        self,
        audit: dict,
        crisis: dict,
        trigger_payload: dict,
        provider: str,
        rendered_prompt: str = "",
        raw_response: str = "",
    ) -> None:
        """Write override to the cio_overrides table."""
        try:
            from sqlalchemy import text

            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO cio_overrides
                            (id, timestamp, trigger, confidence,
                             actions, full_prompt, full_response,
                             portfolio_snapshot, provider)
                        VALUES
                            (:id, :ts, :trigger, :confidence,
                             :actions, :prompt, :response,
                             :snapshot, :provider)
                        """
                    ),
                    {
                        "id": audit.get("override_id", str(uuid.uuid4())),
                        "ts": audit.get("timestamp", datetime.now(UTC).isoformat()),
                        "trigger": audit.get("trigger", "UNKNOWN"),
                        "confidence": audit.get("confidence", 0.0),
                        "actions": json.dumps(audit.get("actions", [])),
                        "prompt": rendered_prompt,
                        "response": raw_response,
                        "snapshot": json.dumps(
                            {"trigger_payload": trigger_payload, "parsed_response": crisis},
                            default=str,
                        ),
                        "provider": provider,
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error("cio_persist_override_error", error=str(exc))

    # ------------------------------------------------------------------
    # Public helpers (for REPL commands)
    # ------------------------------------------------------------------

    def get_last_override(self) -> dict | None:
        """Return the most recent override audit trail (for 'cio why' command)."""
        return self._last_override

    async def set_halt_confirmed(self) -> None:
        """Acknowledge pending halt; broadcast CIO_OVERRIDE HALT to ExecutionAgent."""
        self._pending_halt_confirmation = False

        override_id = str(uuid.uuid4())
        msg = AgentMessage(
            sender_id=self.agent_id,
            channel="horizon.executive.cio",
            message_type=MessageType.CIO_OVERRIDE,
            payload={
                "override_id": override_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "trigger": "MANUAL_CONFIRM",
                "actions": ["HALT"],
                "confidence": 1.0,
                "reasoning": "Manual confirmation by operator.",
            },
        )
        await self.bus.publish(msg)
        logger.info("cio_halt_confirmed", override_id=override_id)
