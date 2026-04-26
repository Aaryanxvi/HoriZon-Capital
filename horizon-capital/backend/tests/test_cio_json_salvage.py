"""CIO JSON parsers salvage prose-wrapped LLM output."""
from unittest.mock import AsyncMock, MagicMock


def _agent():
    from app.agents.executive.cio.cio_agent import CIOAgent
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    return CIOAgent(bus=bus)


def test_parses_prose_preamble():
    agent = _agent()
    raw = (
        "Sure, here's the advisory:\n"
        '{"outlook":"bullish","summary":"x","recommended_adjustments":[],"risk_flags":[]}'
    )
    out = agent._parse_advisory(raw)
    assert out["outlook"] == "bullish"


def test_parses_fenced_json():
    agent = _agent()
    raw = (
        "```json\n"
        '{"outlook":"neutral","summary":"x","recommended_adjustments":[],"risk_flags":[]}\n'
        "```"
    )
    out = agent._parse_advisory(raw)
    assert out["outlook"] == "neutral"


def test_returns_none_on_unsalvageable():
    agent = _agent()
    assert agent._parse_advisory("hello world no json here") is None
