# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D80BA301187F
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Tests for the desktop API — reads, controls, and REPL bridging."""
from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    """TestClient over the real app; lifespan seeds the per-test SQLite DB."""
    from fastapi.testclient import TestClient

    from app.main import app

    # No agents in tests: the desktop entry sets this, plain uvicorn does not.
    os.environ.pop("HORIZON_RUN_AGENTS", None)
    with TestClient(app) as test_client:
        yield test_client


async def test_overview_answers_without_agents(client):
    """The UI must render off storage alone — agents may be stopped."""
    body = client.get("/api/desktop/overview").json()

    assert body["storage"] == "LOCAL"
    assert body["agents_live"] is False
    assert body["agents_running"] == 0
    assert body["nav"] >= 0
    for key in ("cash_usd", "positions_count", "system_mode", "halted", "kill_switch"):
        assert key in body


async def test_read_endpoints_return_lists(client):
    for path, key in (
        ("/api/desktop/positions", "positions"),
        ("/api/desktop/orders", "orders"),
        ("/api/desktop/fills", "fills"),
        ("/api/desktop/signals", "signals"),
        ("/api/desktop/debates", "debates"),
        ("/api/desktop/pending", "pending"),
        ("/api/desktop/alerts", "alerts"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert isinstance(response.json()[key], list), path


async def test_command_output_carries_text_and_html(client):
    """Regression: export_text() used to consume the buffer, leaving html empty."""
    body = client.post("/api/desktop/command", json={"command": "help"}).json()

    assert body["text"].strip()
    assert body["html"].strip()
    assert "<pre" in body["html"]


async def test_terminal_only_commands_map_to_screens(client):
    """`dashboard` and `quit` are TUI affordances; the app answers with its own."""
    dashboard = client.post("/api/desktop/command", json={"command": "dashboard"}).json()
    assert dashboard["action"] == "open_dashboard"

    quit_result = client.post("/api/desktop/command", json={"command": "quit"}).json()
    assert "action" not in quit_result
    assert "quit" in quit_result["text"].lower() or "close" in quit_result["text"].lower()


async def test_unknown_command_does_not_500(client):
    body = client.post("/api/desktop/command", json={"command": "definitely-not-a-command"}).json()
    assert "Unknown command" in body["text"]


async def test_settings_rejects_unlisted_keys_and_bad_values(client, monkeypatch):
    """A rejected write must not touch .env."""
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.tui.settings_panel._write_env_key",
        lambda path, key, value: written.append((key, value)),
    )

    body = client.post(
        "/api/desktop/control/settings",
        json={
            "updates": {
                "STORAGE_BACKEND": "POSTGRES",  # not editable from the app
                "RISK_MAX_DRAWDOWN_PCT": "not-a-number",
            }
        },
    ).json()

    assert body["ok"] is False
    assert len(body["errors"]) == 2
    assert body["applied"] == []
    assert written == []


async def test_settings_applies_valid_value_to_live_settings(client, monkeypatch):
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.tui.settings_panel._write_env_key",
        lambda path, key, value: written.append((key, value)),
    )

    from app.config import settings

    # Register the attribute with monkeypatch before the endpoint mutates it, so
    # teardown restores it — the Settings object is a process-wide singleton and
    # a leaked position limit changes sizing in every later test.
    monkeypatch.setattr(settings, "risk_max_position_pct", settings.risk_max_position_pct)

    body = client.post(
        "/api/desktop/control/settings",
        json={"updates": {"RISK_MAX_POSITION_PCT": "7.5"}},
    ).json()

    assert body["ok"] is True
    assert body["applied"] == ["RISK_MAX_POSITION_PCT"]
    assert written == [("RISK_MAX_POSITION_PCT", "7.5")]
    assert settings.risk_max_position_pct == 7.5


async def test_halt_round_trip_sets_and_clears_the_flag(client):
    """Halting is what the execution agent reads before every order."""
    from app.core.kv_store import get_kv_store

    client.post("/api/desktop/control/halt", json={"halted": True, "reason": "test"})
    kv = get_kv_store()
    assert await kv.get("horizon:system:halted") == "1"
    assert await kv.get("horizon:system:halt_reason") == "test"
    assert client.get("/api/desktop/overview").json()["kill_switch"] is True

    client.post("/api/desktop/control/halt", json={"halted": False})
    assert await kv.get("horizon:system:halted") == "0"
    assert client.get("/api/desktop/overview").json()["halted"] is False


async def test_engine_control_rejects_unknown_action(client):
    body = client.post("/api/desktop/control/engine", json={"action": "explode"}).json()
    assert body["ok"] is False


async def test_render_markup_keeps_colour_and_text():
    from app.api.desktop import render_markup

    rendered = render_markup("[green]ok[/green] and plain")
    assert "ok and plain" in rendered["text"]
    assert "ok" in rendered["html"]
    assert "color" in rendered["html"]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D80BA301187F - verify with scripts/authorship.py verify
