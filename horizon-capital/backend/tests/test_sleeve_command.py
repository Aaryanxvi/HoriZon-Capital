"""Tests for the `sleeve` and `pm add/remove` REPL commands."""
from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"

pytestmark = pytest.mark.asyncio


@pytest.fixture
def handler(monkeypatch, tmp_path):
    """CommandHandler whose .env writes land in a temp file."""
    from app.config import settings
    from app.tui.commands import CommandHandler

    written: dict[str, str] = {}
    monkeypatch.setattr(
        CommandHandler, "_update_env", staticmethod(lambda k, v: written.update({k: v}))
    )
    for attr, value in (
        ("crypto_sleeve_enabled", False),
        ("crypto_sleeve_weight", 0.10),
        ("polymarket_sleeve_enabled", False),
        ("polymarket_sleeve_weight", 0.05),
        ("polymarket_markets", ""),
        # Pinned: discovery on in the developer's .env would satisfy the
        # "needs markets" guard and the test would pass for the wrong reason.
        ("polymarket_discovery_enabled", False),
    ):
        monkeypatch.setattr(settings, attr, value)

    h = CommandHandler()
    h.written = written
    return h


async def test_sleeve_on_off_round_trip(handler):
    from app.config import settings

    out = await handler.handle("sleeve on crypto")
    assert "enabled" in out
    assert settings.crypto_sleeve_enabled is True
    assert handler.written["CRYPTO_SLEEVE_ENABLED"] == "true"

    out = await handler.handle("sleeve off crypto")
    assert "disabled" in out
    assert settings.crypto_sleeve_enabled is False
    assert handler.written["CRYPTO_SLEEVE_ENABLED"] == "false"


async def test_polymarket_sleeve_needs_markets(handler):
    from app.config import settings

    out = await handler.handle("sleeve on polymarket")
    assert "No markets configured" in out
    assert settings.polymarket_sleeve_enabled is False

    # pm add accepts a pasted URL, not just a bare slug.
    await handler.handle("pm add https://polymarket.com/event/fed-cut-sept?tid=1")
    assert settings.polymarket_markets == "fed-cut-sept"

    out = await handler.handle("sleeve on polymarket")
    assert "enabled" in out
    assert settings.polymarket_sleeve_enabled is True

    await handler.handle("pm remove fed-cut-sept")
    assert settings.polymarket_markets == ""


async def test_weight_bounds_rejected(handler):
    from app.config import settings

    assert "between 0 and 1" in await handler.handle("sleeve weight crypto 1.5")
    assert settings.crypto_sleeve_weight == 0.10

    # Combined optional weight must stay under 100% of the book.
    await handler.handle("sleeve on crypto")
    await handler.handle("sleeve weight crypto 0.9")
    await handler.handle("pm add fed-cut-sept")
    await handler.handle("sleeve weight polymarket 0.5")
    out = await handler.handle("sleeve on polymarket")
    assert "must stay under" in out or "lower a weight" in out
    assert settings.polymarket_sleeve_enabled is False


async def test_update_env_targets_the_env_pydantic_reads(tmp_path, monkeypatch):
    """Regression: _update_env wrote to app/.env, which nothing ever loads."""
    from pathlib import Path

    import app.config as config_mod
    from app.tui.commands import CommandHandler

    written: dict[str, str] = {}
    monkeypatch.setattr(
        "app.tui.settings_panel._write_env_key",
        lambda path, k, v: written.update({"path": path, k: v}),
    )
    CommandHandler._update_env("POLYMARKET_MARKETS", "some-slug")

    # Settings loads env_file=".env" relative to the backend package root.
    backend_root = Path(config_mod.__file__).resolve().parents[1]
    assert Path(written["path"]) == backend_root / ".env"
    assert written["POLYMARKET_MARKETS"] == "some-slug"


async def test_sleeve_list_shows_state(handler):
    await handler.handle("sleeve on crypto")
    out = await handler.handle("sleeve")
    assert "crypto" in out and "ON" in out
    assert "90%" in out  # equity mix scaled to 1 - 0.10
