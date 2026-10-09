# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1D80CE46FB40
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Test-suite-wide fixtures."""
from __future__ import annotations

from functools import cache

import pytest


@cache
def _factory_settings():
    """Settings as the code defines them, ignoring ``.env``."""
    from app.config import Settings
    return Settings(_env_file=None)


@pytest.fixture(autouse=True)
def _isolated_horizon_data_dir(tmp_path, monkeypatch):
    """Point HORIZON_DATA_DIR at a per-test tmp dir so the SQLite DB is isolated.

    Forces ``app.core.local_storage`` to be re-imported with the new path
    so the engine binds to the per-test DB. Without this, tests would share
    ``~/.horizon-capital/horizon.db`` and corrupt each other.
    """
    monkeypatch.setenv("HORIZON_DATA_DIR", str(tmp_path))

    # Reset every setting to its factory default so the suite is independent of
    # the developer's real .env (live broker + Alpaca keys would hit the network
    # for fill prices, enabled optional sleeves change the strategy mix, a real
    # DEBATE_MODEL re-wraps fake providers...). Tests that need another value
    # patch it themselves.
    from app.config import settings
    defaults = _factory_settings()
    for name in type(settings).model_fields:
        default = getattr(defaults, name)
        if getattr(settings, name) != default:
            monkeypatch.setattr(settings, name, default)

    # The LOCAL KV store is a process-wide singleton: without this, a key one
    # test sets (e.g. the kill switch "horizon:system:halted") silently blocks
    # every later test's orders even though each test gets a fresh DB.
    from app.core.kv_store import get_kv_store
    kv = get_kv_store()
    kv._data.clear()
    kv._hashes.clear()
    kv._expiry.clear()

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
