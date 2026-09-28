# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A3CBCE960CD2
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""EOD report worker: markdown rendering, file export, and fire-dedup logic."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"


@pytest.mark.asyncio
async def test_to_markdown_empty():
    from app.core.local_storage import init_local_db
    from app.services.report_generator import ReportGenerator

    await init_local_db()

    report = await ReportGenerator().generate("daily")
    md = ReportGenerator().to_markdown(report)

    assert md.startswith("# Horizon Capital")
    assert "## Positions" in md


@pytest.mark.asyncio
async def test_eod_worker_generates_file(monkeypatch, tmp_path):
    from pathlib import Path

    from app.config import settings
    from app.core.local_storage import init_local_db
    from app.workers.eod_report_worker import EODReportWorker

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(settings, "alert_email_smtp_host", "")

    await init_local_db()

    worker = EODReportWorker(orchestrator=None)
    await worker._generate_and_send()

    reports_dir = tmp_path / ".horizon-capital" / "reports"
    files = list(reports_dir.glob("eod_*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "# Horizon Capital" in text


@pytest.mark.asyncio
async def test_maybe_fire_dedupes(monkeypatch, tmp_path):
    from pathlib import Path

    import app.workers.eod_report_worker as eod_module
    from app.core.kv_store import get_kv_store
    from app.core.local_storage import init_local_db

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    await init_local_db()

    worker = eod_module.EODReportWorker(orchestrator=None)

    counter = {"n": 0}

    async def _stub_generate_and_send():
        counter["n"] += 1

    monkeypatch.setattr(worker, "_generate_and_send", _stub_generate_and_send)

    wednesday_22utc = datetime(2026, 7, 22, 22, 0, tzinfo=UTC)
    monkeypatch.setattr(eod_module, "_utcnow", lambda: wednesday_22utc)

    kv = get_kv_store()
    await kv.set(eod_module.LAST_RUN_KEY, wednesday_22utc.strftime("%Y-%m-%d"))

    await worker._maybe_fire()
    assert counter["n"] == 0

    await kv.set(eod_module.LAST_RUN_KEY, "")
    monkeypatch.setattr(eod_module, "FIRE_AFTER_UTC", "00:00")

    await worker._maybe_fire()
    assert counter["n"] == 1
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A3CBCE960CD2 - verify with scripts/authorship.py verify
