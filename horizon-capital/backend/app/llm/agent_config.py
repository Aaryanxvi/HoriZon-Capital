"""Per-agent LLM configuration -- maps roles to LLM provider instances."""

from __future__ import annotations

from dataclasses import dataclass, field


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


# Default configuration -- one instance per role using Claude
DEFAULT_AGENT_CONFIGS: list[AgentInstanceConfig] = [
    # Front Office
    AgentInstanceConfig("regime_analyst", "regime-agent-1", "claude", "front_office"),
    AgentInstanceConfig("sentiment_analyst", "sentiment-agent-1", "claude", "front_office"),
    AgentInstanceConfig("strategy_selector", "ensemble-selector-1", "", "front_office"),
    AgentInstanceConfig("execution_trader", "execution-agent-1", "", "front_office"),
    AgentInstanceConfig("portfolio_manager", "portfolio-agent-1", "", "front_office"),
    AgentInstanceConfig("investor_relations", "ir-agent-1", "claude", "front_office"),

    # Middle Office
    AgentInstanceConfig("risk_analyst", "risk-agent-1", "", "middle_office"),
    AgentInstanceConfig("compliance_officer", "compliance-agent-1", "", "middle_office"),
    AgentInstanceConfig("operations_manager", "operations-agent-1", "", "middle_office"),

    # Back Office
    AgentInstanceConfig("accountant", "accounting-agent-1", "", "back_office"),
    AgentInstanceConfig("it_engineer", "it-agent-1", "", "back_office"),
    AgentInstanceConfig("quant_researcher", "quant-agent-1", "", "back_office"),

    # Executive
    AgentInstanceConfig("cio", "cio-agent-1", "claude", "executive"),
]
