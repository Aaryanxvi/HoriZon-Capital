"""Interactive CIO chat interface for human CIO mode.

Uses the configured LLM to interpret user intent and map to system actions:
- "How are we doing today?" -> aggregate performance summary
- "What does risk say about our exposure?" -> query risk agent
- "Show me department status" -> department overview
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("tui.cio_chat")


class CIOChat:
    """Natural language interface for human CIO mode.

    Interprets user messages and maps them to system queries and actions.
    When an LLM provider is available, it uses it for natural language
    understanding. Otherwise, falls back to keyword matching.
    """

    def __init__(self, orchestrator=None, dashboard=None) -> None:
        self._orchestrator = orchestrator
        self._dashboard = dashboard
        self._history: list[dict[str, str]] = []

    async def chat(self, user_message: str) -> str:
        """Process a user message and return a response."""
        self._history.append({"role": "user", "content": user_message})

        # Try LLM-powered interpretation first
        response = await self._try_llm_response(user_message)
        if response is None:
            # Fall back to keyword matching
            response = await self._keyword_response(user_message)

        self._history.append({"role": "assistant", "content": response})
        return response

    async def _try_llm_response(self, message: str) -> str | None:
        """Attempt to use an LLM to interpret the message."""
        from app.llm.provider_registry import provider_registry

        available = provider_registry.list_available()
        if not available:
            return None

        provider = provider_registry.get_provider(available[0])
        if provider is None:
            return None

        # Gather system context
        context = self._gather_context()

        system_prompt = (
            "You are the AI assistant for the CIO of Horizon Capital, an AI-powered hedge fund. "
            "The human CIO is asking you questions about the system. "
            "Answer concisely based on the system context provided. "
            "If asked to take an action, describe what would happen but note that "
            "actions must be confirmed via system commands.\n\n"
            f"SYSTEM CONTEXT:\n{context}"
        )

        try:
            response = await provider.complete(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": message}],
                temperature=0.3,
            )
            return response
        except Exception as exc:
            logger.error("cio_chat_llm_error", error=str(exc))
            return None

    async def _keyword_response(self, message: str) -> str:
        """Simple keyword-based response when no LLM is available."""
        msg_lower = message.lower()

        if any(w in msg_lower for w in ["status", "how are", "overview", "summary"]):
            return self._format_status()
        elif any(w in msg_lower for w in ["department", "dept"]):
            return self._format_departments()
        elif any(w in msg_lower for w in ["risk", "var", "drawdown"]):
            return self._format_risk()
        elif any(w in msg_lower for w in ["signal", "trade"]):
            return self._format_signals()
        elif any(w in msg_lower for w in ["portfolio", "nav", "position"]):
            return self._format_portfolio()
        elif any(w in msg_lower for w in ["help", "what can"]):
            return (
                "I can help you with:\n"
                "  - System status and overview\n"
                "  - Department health\n"
                "  - Risk metrics\n"
                "  - Recent signals and trades\n"
                "  - Portfolio summary\n"
                "\nJust ask in natural language, or type 'exit' to return to command mode."
            )
        else:
            return (
                "I understand you're asking about: " + message + "\n"
                "Try asking about: status, departments, risk, signals, or portfolio.\n"
                "Type 'help' for more options, or 'exit' to return to command mode."
            )

    def _gather_context(self) -> str:
        """Gather current system context for LLM."""
        parts: list[str] = []

        if self._orchestrator:
            statuses = self._orchestrator.get_agent_statuses()
            parts.append(f"Agents: {len(statuses)} total")
            running = sum(1 for s in statuses.values() if s.get("status") == "RUNNING")
            parts.append(f"Running: {running}, Stopped: {len(statuses) - running}")

            dept_statuses = self._orchestrator.get_department_statuses()
            for dept in dept_statuses:
                parts.append(
                    f"  {dept['display_name']}: "
                    f"{dept['agents_running']}/{dept['agents_total']} agents running"
                )

        if self._dashboard:
            r = self._dashboard.get_risk_snapshot()
            if r:
                parts.append(
                    f"Risk: VaR95={r.get('var_95', 0):.4f}, "
                    f"Drawdown={r.get('current_drawdown', 0):.2f}%"
                )
            p = self._dashboard.get_portfolio_snapshot()
            if p:
                parts.append(f"Portfolio: NAV=${p.get('nav', 0):,.2f}")

        return "\n".join(parts) if parts else "No system data available yet."

    def _format_status(self) -> str:
        if not self._orchestrator:
            return "Orchestrator not available."
        statuses = self._orchestrator.get_agent_statuses()
        running = sum(1 for s in statuses.values() if s.get("status") == "RUNNING")
        return (
            f"System Status: {running}/{len(statuses)} agents running\n"
            + "\n".join(
                f"  {aid}: {info['status']} ({info.get('department', 'n/a')})"
                for aid, info in sorted(statuses.items())
            )
        )

    def _format_departments(self) -> str:
        if not self._orchestrator:
            return "Orchestrator not available."
        depts = self._orchestrator.get_department_statuses()
        if not depts:
            return "No departments registered."
        lines = ["Department Overview:"]
        for d in depts:
            health = "HEALTHY" if d.get("healthy") else "DEGRADED"
            lines.append(
                f"  {d['display_name']}: "
                f"{d['agents_running']}/{d['agents_total']} agents [{health}]"
            )
        return "\n".join(lines)

    def _format_risk(self) -> str:
        if not self._dashboard:
            return "No risk data available yet."
        r = self._dashboard.get_risk_snapshot()
        if not r:
            return "No risk data available yet."
        return (
            f"Risk Metrics:\n"
            f"  VaR (95%):     {r.get('var_95', 0):.4f}\n"
            f"  VaR (99%):     {r.get('var_99', 0):.4f}\n"
            f"  Max Drawdown:  {r.get('max_drawdown', 0):.2f}%\n"
            f"  Curr Drawdown: {r.get('current_drawdown', 0):.2f}%\n"
            f"  Kill Switch:   {'ACTIVE' if r.get('kill_switch_active') else 'OFF'}"
        )

    def _format_signals(self) -> str:
        if not self._dashboard:
            return "No signals available yet."
        signals = self._dashboard.get_recent_signals(limit=5)
        if not signals:
            return "No signals available yet."
        lines = ["Recent Signals:"]
        for sig in signals:
            symbol = sig.get("symbol", "?")
            direction = sig.get("direction", 0)
            d = "BUY" if direction > 0 else "SELL" if direction < 0 else "HOLD"
            lines.append(f"  {symbol}: {d} (strength={sig.get('strength', 0):.2f})")
        return "\n".join(lines)

    def _format_portfolio(self) -> str:
        if not self._dashboard:
            return "Dashboard not available."
        p = self._dashboard.get_portfolio_snapshot()
        return (
            f"Portfolio:\n"
            f"  NAV:       ${p.get('nav', 0):,.2f}\n"
            f"  Cash:      ${p.get('cash', 0):,.2f}\n"
            f"  Positions: {p.get('positions', 0)}"
        )
