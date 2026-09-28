# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-2E1CF8D5517C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Middle Office department manager -- Risk & Control."""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.department_manager import DepartmentManager
from app.agents.departments import DepartmentType
from app.core.logging import get_logger

logger = get_logger("dept.middle_office")


class MiddleOfficeManager(DepartmentManager):
    """Manages risk, compliance, and operations agents."""

    department_type = DepartmentType.MIDDLE_OFFICE
    department_display = "Middle Office (Risk & Control)"

    def _create_agents(self) -> list[BaseAgent]:
        agents: list[BaseAgent] = []

        # Risk agent (always required)
        from app.agents.middle_office.risk.risk_agent import RiskAgent
        agents.append(RiskAgent(bus=self.bus))

        # Compliance
        try:
            from app.agents.middle_office.compliance.compliance_agent import ComplianceAgent
            agents.append(ComplianceAgent(bus=self.bus))
        except ImportError:
            logger.warning("compliance_agent_not_available")

        # Operations
        try:
            from app.agents.middle_office.operations.operations_agent import OperationsAgent
            agents.append(OperationsAgent(bus=self.bus))
        except ImportError:
            logger.warning("operations_agent_not_available")

        # Debate
        try:
            from app.agents.middle_office.debate_agent import DebateAgent
            agents.append(DebateAgent(bus=self.bus))
        except ImportError:
            logger.warning("debate_agent_not_available")

        # Alpha Monitor (Phase 2)
        try:
            from app.agents.middle_office.alpha_monitor import AlphaMonitorAgent
            agents.append(AlphaMonitorAgent(bus=self.bus))
        except ImportError:
            logger.warning("alpha_monitor_agent_not_available")

        return agents
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 2E1CF8D5517C - verify with scripts/authorship.py verify
