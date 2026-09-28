# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-0BF86C5050FF
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Per-agent LLM configuration -- maps roles to LLM provider instances."""

from __future__ import annotations

from dataclasses import dataclass

# Roles that actively use LLM reasoning (as opposed to rule-based execution)
_LLM_ROLES = {
    "front_office": {
        "regime_analyst", "sentiment_analyst", "strategy_selector", "investor_relations",
    },
    "middle_office": {"debate_agent", "risk_analyst"},
    "back_office": {"quant_researcher"},
    "executive": {"cio"},
}


@dataclass
class AgentInstanceConfig:
    """Configuration for a single agent instance.

    Each role can have multiple instances, each using a different LLM provider,
    to produce diverse perspectives that are then aggregated.
    """

    role: str               # "risk_analyst", "compliance_officer", etc.
    instance_id: str        # "risk-analyst-claude", "risk-analyst-gpt4"
    llm_provider: str       # "claude", "openai", "gemini", or "" for rule-based
    department: str         # "front_office", "middle_office", etc.
    enabled: bool = True


def get_agent_configs() -> list[AgentInstanceConfig]:
    """Build agent configs dynamically, respecting per-department AI routing."""
    from app.llm.provider_registry import provider_registry

    dept_providers: dict[str, str] = {}
    for dept in ("front_office", "middle_office", "back_office", "executive"):
        dept_providers[dept] = provider_registry.get_provider_name_for_department(dept)

    return [
        # Front Office
        AgentInstanceConfig(
            "regime_analyst", "regime-agent-1",
            dept_providers["front_office"], "front_office",
        ),
        AgentInstanceConfig(
            "sentiment_analyst", "sentiment-agent-1",
            dept_providers["front_office"], "front_office",
        ),
        AgentInstanceConfig(
            "strategy_selector", "ensemble-selector-1",
            dept_providers["front_office"], "front_office",
        ),
        AgentInstanceConfig("execution_trader", "execution-agent-1", "", "front_office"),
        AgentInstanceConfig("portfolio_manager", "portfolio-agent-1", "", "front_office"),
        AgentInstanceConfig(
            "investor_relations", "ir-agent-1",
            dept_providers["front_office"], "front_office",
        ),

        # Middle Office
        AgentInstanceConfig(
            "debate_agent", "debate-agent-1",
            dept_providers["middle_office"], "middle_office",
        ),
        AgentInstanceConfig("risk_analyst", "risk-agent-1", "", "middle_office"),
        AgentInstanceConfig("compliance_officer", "compliance-agent-1", "", "middle_office"),
        AgentInstanceConfig("operations_manager", "operations-agent-1", "", "middle_office"),
        AgentInstanceConfig("alpha_monitor", "alpha-monitor-1", "", "middle_office"),

        # Back Office
        AgentInstanceConfig("accountant", "accounting-agent-1", "", "back_office"),
        AgentInstanceConfig("it_engineer", "it-agent-1", "", "back_office"),
        AgentInstanceConfig(
            "quant_researcher", "quant-agent-1",
            dept_providers["back_office"], "back_office",
        ),

        # Executive
        AgentInstanceConfig(
            "cio", "cio-agent-1",
            dept_providers["executive"], "executive",
        ),
    ]


# Static fallback (used before provider_registry is initialized)
DEFAULT_AGENT_CONFIGS: list[AgentInstanceConfig] = [
    AgentInstanceConfig("regime_analyst", "regime-agent-1", "claude", "front_office"),
    AgentInstanceConfig("sentiment_analyst", "sentiment-agent-1", "claude", "front_office"),
    AgentInstanceConfig("strategy_selector", "ensemble-selector-1", "claude", "front_office"),
    AgentInstanceConfig("execution_trader", "execution-agent-1", "", "front_office"),
    AgentInstanceConfig("portfolio_manager", "portfolio-agent-1", "", "front_office"),
    AgentInstanceConfig("investor_relations", "ir-agent-1", "claude", "front_office"),
    AgentInstanceConfig("debate_agent", "debate-agent-1", "claude", "middle_office"),
    AgentInstanceConfig("risk_analyst", "risk-agent-1", "", "middle_office"),
    AgentInstanceConfig("compliance_officer", "compliance-agent-1", "", "middle_office"),
    AgentInstanceConfig("operations_manager", "operations-agent-1", "", "middle_office"),
    AgentInstanceConfig("alpha_monitor", "alpha-monitor-1", "", "middle_office"),
    AgentInstanceConfig("accountant", "accounting-agent-1", "", "back_office"),
    AgentInstanceConfig("it_engineer", "it-agent-1", "", "back_office"),
    AgentInstanceConfig("quant_researcher", "quant-agent-1", "", "back_office"),
    AgentInstanceConfig("cio", "cio-agent-1", "claude", "executive"),
]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 0BF86C5050FF - verify with scripts/authorship.py verify
