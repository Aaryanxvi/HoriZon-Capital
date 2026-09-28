# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B1AE49039B4D
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Brief push worker: markup stripping, config gating, and fire-dedup logic."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"


def test_strip_markup():
    from app.workers.brief_push_worker import _to_plain

    assert _to_plain("[bold cyan]HELLO[/bold cyan] [green]ok[/green]") == "HELLO ok"

    long_text = "x" * 5000
    result = _to_plain(long_text)
    assert result.endswith("\n… (truncated)")
    assert len(result) < 5000


@pytest.mark.asyncio
async def test_push_skips_when_unconfigured(monkeypatch):
    from app.config import settings
    from app.workers.brief_push_worker import BriefPushWorker

    monkeypatch.setattr(settings, "telegram_bot_token", "")

    worker = BriefPushWorker(orchestrator=None)
    await asyncio.wait_for(worker.run(), timeout=2)


@pytest.mark.asyncio
async def test_maybe_fire_dedupe_and_schedule(monkeypatch):
    import app.workers.brief_push_worker as brief_module
    from app.config import settings
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db

    await init_local_db()

    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "dummy-chat")

    worker = brief_module.BriefPushWorker(orchestrator=None)

    counter = {"n": 0}

    async def _stub_push_brief():
        counter["n"] += 1

    monkeypatch.setattr(worker, "_push_brief", _stub_push_brief)

    wednesday_13utc = datetime(2026, 7, 22, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(brief_module, "_utcnow", lambda: wednesday_13utc)

    kv = get_kv_store()

    await worker._maybe_fire()
    assert counter["n"] == 1
    assert await kv.get(brief_module.LAST_RUN_KEY) == "2026-07-22"

    await worker._maybe_fire()
    assert counter["n"] == 1

    saturday = datetime(2026, 7, 25, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(brief_module, "_utcnow", lambda: saturday)
    await kv.set(brief_module.LAST_RUN_KEY, "")

    await worker._maybe_fire()
    assert counter["n"] == 1
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B1AE49039B4D - verify with scripts/authorship.py verify
