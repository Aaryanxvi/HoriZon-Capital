"""Org-chart endpoint: static answer + drift check against the agent sources."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.api.desktop_org import AGENTS, build_links


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _source(module: str) -> str:
    spec = importlib.util.find_spec(module)
    assert spec and spec.origin, module
    return Path(spec.origin).read_text(encoding="utf-8")


@pytest.mark.parametrize("agent", AGENTS, ids=lambda a: a["id"])
def test_table_matches_agent_source(agent):
    src = _source(agent["module"])
    assert f'agent_id="{agent["id"]}"' in src
    subscribes = set(re.findall(r'bus\.subscribe\(\s*"([^"]+)"', src))
    emits = {
        re.sub(r"\{[^}]*\}", "*", c) for c in re.findall(r'channel\s*=\s*f?"([^"]+)"', src)
    }
    assert subscribes == set(agent["subscribes"])
    assert emits == set(agent["emits"])


def test_every_agent_belongs_to_its_department_manager():
    for agent in AGENTS:
        dept = agent["department"]
        assert agent["module"] in _source(f"app.agents.{dept}.manager")


def test_links_follow_the_trade_pipeline():
    links = {(lk["from"], lk["to"]) for lk in build_links()}
    for hop in [
        ("strategy-agent-1", "risk-agent"),
        ("risk-agent", "debate-agent-1"),
        ("debate-agent-1", "portfolio-agent"),
        ("portfolio-agent", "execution-agent"),
        ("execution-agent", "portfolio-agent"),
        ("portfolio-agent", "accounting-agent-1"),
        ("cio-agent-1", "execution-agent"),
        ("risk-agent", "cio-agent-1"),
    ]:
        assert hop in links, hop
    assert all(a != b for a, b in links)


async def test_org_answers_without_engine(client):
    body = client.get("/api/desktop/org").json()
    assert [d["id"] for d in body["departments"]] == [
        "executive", "front_office", "middle_office", "back_office",
    ]
    assert len(body["agents"]) == len(AGENTS)
    assert "module" not in body["agents"][0]
    assert body["links"]
