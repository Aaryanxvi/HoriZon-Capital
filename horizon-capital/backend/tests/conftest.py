# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1D80CE46FB40
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Test-suite-wide fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_horizon_data_dir(tmp_path, monkeypatch):
    """Point HORIZON_DATA_DIR at a per-test tmp dir so the SQLite DB is isolated.

    Forces ``app.core.local_storage`` to be re-imported with the new path
    so the engine binds to the per-test DB. Without this, tests would share
    ``~/.horizon-capital/horizon.db`` and corrupt each other.
    """
    monkeypatch.setenv("HORIZON_DATA_DIR", str(tmp_path))

    # Force test-mode defaults so the suite is independent of the developer's
    # real .env (which may be FULLY_AUTONOMOUS / CIO=AI for live trading). Tests
    # that need another mode patch it themselves.
    from app.config import CIOMode, SystemMode, settings
    monkeypatch.setattr(settings, "system_mode", SystemMode.PAPER_TRADING, raising=False)
    monkeypatch.setattr(settings, "cio_mode", CIOMode.HUMAN, raising=False)
    monkeypatch.setattr(settings, "execution_broker", "PAPER", raising=False)
    # Provider default: a real DEBATE_MODEL in .env would re-wrap every fake
    # provider via with_model() and break identity assertions.
    monkeypatch.setattr(settings, "debate_model", "", raising=False)

    # Drop cached modules so they pick up the new env var.
    import sys
    for mod in list(sys.modules):
        if mod.startswith("app.core.local_storage") or mod.startswith("app.core.runtime"):
            del sys.modules[mod]

    yield

    # Belt-and-suspenders cleanup: nothing to do for tmp_path (pytest cleans),
    # but reset the env so the next session sees the user default.
    monkeypatch.delenv("HORIZON_DATA_DIR", raising=False)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1D80CE46FB40 - verify with scripts/authorship.py verify
