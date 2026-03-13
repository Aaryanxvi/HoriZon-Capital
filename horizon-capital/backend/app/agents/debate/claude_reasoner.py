"""Claude-based reasoning engine for the debate system.

Wraps the Anthropic async client and returns structured JSON responses from
the Claude model.  Includes exponential-backoff retry logic for transient
API errors.
"""

import asyncio
import json
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

        # Fallback: heuristic extraction
        vote = "ABSTAIN"
        upper = raw.upper()
        if "\"FOR\"" in upper or "VOTE: FOR" in upper or "VOTE\":\"FOR" in upper:
            vote = "FOR"
        elif "\"AGAINST\"" in upper or "VOTE: AGAINST" in upper:
            vote = "AGAINST"

        return {
            "argument": raw[:2000],
            "vote": vote,
            "confidence": 0.5,
        }


def _normalise_vote(vote: str) -> str:
    """Ensure the vote string is one of the allowed values."""
    v = vote.upper().strip()
    if v in ("FOR", "AGAINST", "ABSTAIN"):
        return v
    return "ABSTAIN"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
