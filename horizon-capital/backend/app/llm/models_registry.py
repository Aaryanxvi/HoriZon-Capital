# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1A155AB2A307
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Available LLM models per provider.

Source of truth for the agent-config UI / REPL / API to populate model
dropdowns. Keep tier-ordered — UI shows cheapest first by default so users
can pick a low-cost model for an agent without reading docs.

Pricing (per 1M tokens, in/out USD, public list 2026-04):
  claude-haiku-4-5             $0.80 / $4
  claude-sonnet-4-6            $3 / $15
  claude-opus-4-7              $15 / $75
  gpt-4o-mini                  $0.15 / $0.60
  gpt-4o                       $2.50 / $10
  o3-mini                      $1.10 / $4.40
  gemini-2.0-flash-lite        $0.075 / $0.30
  gemini-2.0-flash             $0.10 / $0.40
  gemini-2.5-pro               $1.25 / $5
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model_id: str
    label: str
    tier: str  # 'cheap' | 'mid' | 'premium'
    input_cost_per_1m: float
    output_cost_per_1m: float


# Ordered cheap -> premium per provider
CLAUDE_MODELS: list[ModelSpec] = [
    ModelSpec("claude", "claude-haiku-4-5-20251001", "Claude Haiku 4.5",
              "cheap", 0.80, 4.0),
    ModelSpec("claude", "claude-sonnet-4-20250514", "Claude Sonnet 4",
              "mid", 3.0, 15.0),
    ModelSpec("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6",
              "mid", 3.0, 15.0),
    ModelSpec("claude", "claude-opus-4-7", "Claude Opus 4.7",
              "premium", 15.0, 75.0),
]

OPENAI_MODELS: list[ModelSpec] = [
    ModelSpec("openai", "gpt-4o-mini", "GPT-4o mini",
              "cheap", 0.15, 0.60),
    ModelSpec("openai", "o3-mini", "o3-mini (reasoning)",
              "mid", 1.10, 4.40),
    ModelSpec("openai", "gpt-4o", "GPT-4o",
              "mid", 2.50, 10.0),
    ModelSpec("openai", "gpt-4-turbo", "GPT-4 Turbo",
              "premium", 10.0, 30.0),
]

GEMINI_MODELS: list[ModelSpec] = [
    ModelSpec("gemini", "gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite",
              "cheap", 0.075, 0.30),
    ModelSpec("gemini", "gemini-2.0-flash", "Gemini 2.0 Flash",
              "cheap", 0.10, 0.40),
    ModelSpec("gemini", "gemini-2.5-pro", "Gemini 2.5 Pro",
              "premium", 1.25, 5.0),
]

_BY_PROVIDER: dict[str, list[ModelSpec]] = {
    "claude": CLAUDE_MODELS,
    "openai": OPENAI_MODELS,
    "gemini": GEMINI_MODELS,
}


def list_models(provider: str) -> list[ModelSpec]:
    return list(_BY_PROVIDER.get(provider.lower(), []))


def all_models() -> list[ModelSpec]:
    return [m for ms in _BY_PROVIDER.values() for m in ms]


def default_model_for(provider: str) -> str:
    """Return the recommended (mid-tier) model for a provider."""
    models = list_models(provider)
    if not models:
        return ""
    mids = [m for m in models if m.tier == "mid"]
    return (mids[0] if mids else models[0]).model_id


def is_valid_model(provider: str, model_id: str) -> bool:
    return any(m.model_id == model_id for m in list_models(provider))
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1A155AB2A307 - verify with scripts/authorship.py verify
