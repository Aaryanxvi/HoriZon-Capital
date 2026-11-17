# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-7B1AE3AD5772
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Claude-based reasoning engine for the debate system.

Wraps the Anthropic async client and returns structured JSON responses from
the Claude model.  Includes exponential-backoff retry logic for transient
API errors.
"""

import asyncio
import json
import re
from typing import Any

import anthropic

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("debate.claude_reasoner")

# Default model for debate reasoning
MODEL_ID = "claude-sonnet-4-20250514"

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


class ClaudeReasoner:
    """Sends structured prompts to the Anthropic Claude API and parses the
    JSON response into ``{argument, vote, confidence}``.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.anthropic_api_key
        self._client: anthropic.AsyncAnthropic | None = None

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def reason(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        """Call Claude and return a structured debate response.

        Parameters
        ----------
        system_prompt:
            The agent personality / role instructions.
        user_prompt:
            The market context and signal information.

        Returns
        -------
        dict
            ``argument`` -- the textual reasoning (str).
            ``vote`` -- ``"FOR"`` / ``"AGAINST"`` / ``"ABSTAIN"``.
            ``confidence`` -- float between 0.0 and 1.0.

        Raises
        ------
        RuntimeError
            If all retries are exhausted.
        """
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self.client.messages.create(
                    model=MODEL_ID,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                raw_text = response.content[0].text.strip()
                parsed = self._parse_response(raw_text)

                logger.info(
                    "claude_reason_ok",
                    attempt=attempt,
                    vote=parsed["vote"],
                    confidence=parsed["confidence"],
                )
                return parsed

            except (
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                logger.warning(
                    "claude_api_error",
                    attempt=attempt,
                    error=str(exc),
                    backoff=backoff,
                )
                if attempt == MAX_RETRIES:
                    raise RuntimeError(
                        f"Claude API failed after {MAX_RETRIES} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER

            except anthropic.APIError as exc:
                # Non-transient errors (auth, bad request) -- do not retry
                logger.error("claude_api_fatal", error=str(exc))
                raise RuntimeError(f"Claude API fatal error: {exc}") from exc

        # Should be unreachable, but satisfy the type checker
        raise RuntimeError("Claude API failed: retries exhausted")

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Any]:
        """Extract structured fields from the Claude response.

        Attempts JSON parsing first.  If the response is not valid JSON,
        falls back to keyword extraction.
        """
        # Try to extract JSON from the response (Claude may wrap it in markdown)
        json_str = raw
        if "```json" in raw:
            json_str = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            json_str = raw.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
            return {
                "argument": str(data.get("argument", raw)),
                "vote": _normalise_vote(str(data.get("vote", "ABSTAIN"))),
                "confidence": _clamp(float(data.get("confidence", 0.5)), 0.0, 1.0),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        return salvage_fields(raw)


_ARGUMENT_RE = re.compile(r'"argument"\s*:\s*"(.*?)"\s*,\s*"(?:vote|confidence)"\s*:', re.DOTALL)
_VOTE_RE = re.compile(r'"vote"\s*:\s*"(FOR|AGAINST|ABSTAIN)"', re.IGNORECASE)
_CONFIDENCE_RE = re.compile(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)')


def salvage_fields(raw: str) -> dict[str, Any]:
    """Pull argument/vote/confidence out of a reply that is almost-JSON.

    LLMs often quote inside the argument without escaping ("too big to fail"),
    which breaks json.loads. Keying on the field names still recovers each one,
    so the UI shows the argument rather than the raw blob and the real
    confidence survives instead of defaulting to 0.5.
    """
    arg = _ARGUMENT_RE.search(raw)
    vote = _VOTE_RE.search(raw)
    if vote:
        verdict = vote.group(1).upper()
    else:
        upper = raw.upper()
        verdict = (
            "FOR" if "VOTE: FOR" in upper else "AGAINST" if "VOTE: AGAINST" in upper else "ABSTAIN"
        )
    conf = _CONFIDENCE_RE.search(raw)
    return {
        "argument": (arg.group(1).replace('\\"', '"') if arg else raw)[:2000],
        "vote": verdict,
        "confidence": _clamp(float(conf.group(1)), 0.0, 1.0) if conf else 0.5,
    }


def _normalise_vote(vote: str) -> str:
    """Ensure the vote string is one of the allowed values."""
    v = vote.upper().strip()
    if v in ("FOR", "AGAINST", "ABSTAIN"):
        return v
    return "ABSTAIN"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 7B1AE3AD5772 - verify with scripts/authorship.py verify
