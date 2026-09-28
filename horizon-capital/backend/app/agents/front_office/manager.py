# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-5C69D9795A0D
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Front Office department manager -- Investment & Revenue."""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.department_manager import DepartmentManager
from app.agents.departments import DepartmentType
from app.core.logging import get_logger

logger = get_logger("dept.front_office")


class FrontOfficeManager(DepartmentManager):
    """Manages research, strategy, trading, portfolio, and IR agents."""

    department_type = DepartmentType.FRONT_OFFICE
    department_display = "Front Office (Investment & Revenue)"

    def _create_agents(self) -> list[BaseAgent]:
        agents: list[BaseAgent] = []

        # Research agents (sentiment scoring available via SentimentAgent utility class)

        # Trading
        try:
            from app.agents.front_office.trading.execution_agent import ExecutionAgent
            agents.append(ExecutionAgent(bus=self.bus))
        except ImportError:
            logger.warning("execution_agent_not_available")

        # Portfolio
        try:
            from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
            agents.append(PortfolioAgent(bus=self.bus))
        except ImportError:
            logger.warning("portfolio_agent_not_available")

        # Strategy
        try:
            from app.agents.front_office.strategy.strategy_agent import StrategyAgent
            agents.append(StrategyAgent(bus=self.bus))
        except ImportError:
            logger.warning("strategy_agent_not_available")

        # Investor Relations
        try:
            from app.agents.front_office.investor_relations.ir_agent import IRAgent
            agents.append(IRAgent(bus=self.bus))
        except ImportError:
            logger.warning("ir_agent_not_available")

        return agents
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 5C69D9795A0D - verify with scripts/authorship.py verify
