"""Per-agent LLM model + provider overrides — runtime-mutable.

Persists user choices to disk so agents pick up new model/provider next call,
no restart needed. Keyed by agent_id.

Storage: simple JSON file in the local data dir (default ~/.horizon-capital/
agent_overrides.json). Lock-free — last writer wins (single-process desktop
agent, not multi-tenant).

Public API:
    get_override(agent_id) -> {provider, model} | None
    set_override(agent_id, provider, model)
    clear_override(agent_id)
    list_overrides() -> dict[str, dict[str, str]]
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

from app.core.logging import get_logger
from app.llm.models_registry import is_valid_model

logger = get_logger("llm.overrides")

_LOCK = Lock()
_OVERRIDES: dict[str, dict[str, str]] | None = None


def _store_path() -> Path:
    base = os.getenv("HORIZON_DATA_DIR", str(Path.home() / ".horizon-capital"))
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(base) / "agent_overrides.json"


def _load() -> dict[str, dict[str, str]]:
    global _OVERRIDES
    if _OVERRIDES is not None:
        return _OVERRIDES
    p = _store_path()
    if p.exists():
        try:
            _OVERRIDES = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(_OVERRIDES, dict):
                _OVERRIDES = {}
        except Exception as e:
            logger.warning("override_load_failed", error=str(e))
            _OVERRIDES = {}
    else:
        _OVERRIDES = {}
    return _OVERRIDES


def _save() -> None:
    p = _store_path()
    try:
        p.write_text(json.dumps(_OVERRIDES, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("override_save_failed", error=str(e))


def get_override(agent_id: str) -> dict[str, str] | None:
    """Return {'provider': ..., 'model': ...} for agent, or None."""
    with _LOCK:
        ov = _load().get(agent_id)
    return dict(ov) if ov else None


def set_override(agent_id: str, provider: str, model: str) -> bool:
    """Set provider+model for one agent. Returns True if accepted."""
    if not provider or not model:
        return False
    if not is_valid_model(provider, model):
        logger.warning(
            "override_invalid_model", agent=agent_id,
            provider=provider, model=model,
        )
        return False
    with _LOCK:
        d = _load()
        d[agent_id] = {"provider": provider, "model": model}
        _save()
    logger.info("agent_model_override_set", agent=agent_id,
                provider=provider, model=model)
    return True


def clear_override(agent_id: str) -> bool:
    with _LOCK:
        d = _load()
        existed = d.pop(agent_id, None) is not None
        if existed:
            _save()
    return existed


def list_overrides() -> dict[str, dict[str, str]]:
    with _LOCK:
        return dict(_load())


def reset_cache() -> None:
    """Drop in-memory cache so next read reloads from disk. For tests."""
    global _OVERRIDES
    with _LOCK:
        _OVERRIDES = None
