"""System doctor self-check: fault-tolerant checks, empty and populated state."""

from __future__ import annotations

import os

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"


@pytest.mark.asyncio
async def test_doctor_runs_empty():
    from app.core.local_storage import init_local_db
    from app.services.doctor import run_doctor

    await init_local_db()

    out = await run_doctor(orchestrator=None)

    assert "SYSTEM DOCTOR" in out
    assert "✓" in out
    assert "orchestrator not attached" in out


@pytest.mark.asyncio
async def test_doctor_halt_flag():
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db
    from app.services.doctor import run_doctor

    await init_local_db()

    kv = get_kv_store()
    await kv.set("horizon:system:halted", "1")

    out = await run_doctor(orchestrator=None)

    assert "SYSTEM HALTED" in out


@pytest.mark.asyncio
async def test_doctor_llm_warn(monkeypatch):
    from app.config import settings
    from app.core.local_storage import init_local_db
    from app.services.doctor import run_doctor

    await init_local_db()

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "google_api_key", "")

    out = await run_doctor(orchestrator=None)

    assert "no LLM keys" in out
