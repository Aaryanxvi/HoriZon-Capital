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

    # Drop cached modules so they pick up the new env var.
    import sys
    for mod in list(sys.modules):
        if mod.startswith("app.core.local_storage") or mod.startswith("app.core.runtime"):
            del sys.modules[mod]

    yield

    # Belt-and-suspenders cleanup: nothing to do for tmp_path (pytest cleans),
    # but reset the env so the next session sees the user default.
    monkeypatch.delenv("HORIZON_DATA_DIR", raising=False)
