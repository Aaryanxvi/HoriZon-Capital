"""Interactive terminal command handler for Horizon Capital.

Provides a REPL-like command interface that runs alongside the dashboard,
allowing the CIO to issue commands like:
  status, signals, risk, regime, debate, mode, departments, cio, quit
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from app.config import CIOMode, SystemMode, settings

console = Console()

HELP_TEXT = """
[bold cyan]Horizon Capital Terminal Commands[/bold cyan]

  [green]status[/]         Show all agent statuses (grouped by department)
  [green]signals[/]        Show recent trading signals
  [green]risk[/]           Show current risk metrics
  [green]regime[/]         Show market regime per scope
  [green]debate[/]         Show recent debate summaries
  [green]portfolio[/]      Show current portfolio
  [green]departments[/]    Show department-level overview
  [green]cio[/]            Enter CIO chat mode (natural language)
  [green]agents config[/]  Show agent-per-role configuration
  [green]mode[/] <MODE>    Switch system mode (PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS)
  [green]kill-switch[/]    Toggle kill switch
  [green]symbols[/]        Show trading universe
  [green]config[/]         Show current configuration
  [green]help[/]           Show this help
  [green]quit[/] / [green]exit[/]   Shutdown Horizon Capital
"""


class CommandHandler:
    """Processes terminal commands and returns formatted output."""

    def __init__(self, dashboard=None, orchestrator=None) -> None:
        self._dashboard = dashboard
        self._orchestrator = orchestrator
        self._should_quit = False
        self._cio_chat = None  # Lazy-initialized

    @property
    def should_quit(self) -> bool:
        return self._should_quit

    async def handle(self, raw_input: str) -> str | None:
        """Parse and execute a command. Returns None for empty input."""
        parts = raw_input.strip().split()
        if not parts:
            return None

        cmd = parts[0].lower()
        args = parts[1:]

        # Handle compound commands
        if cmd == "agents" and args and args[0].lower() == "config":
            return await self._cmd_agents_config([])

        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "signals": self._cmd_signals,
            "risk": self._cmd_risk,
            "regime": self._cmd_regime,
            "debate": self._cmd_debate,
            "portfolio": self._cmd_portfolio,
            "departments": self._cmd_departments,
            "cio": self._cmd_cio,
            "mode": self._cmd_mode,
            "kill-switch": self._cmd_kill_switch,
            "symbols": self._cmd_symbols,
            "config": self._cmd_config,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler is None:
            return f"[red]Unknown command:[/red] {cmd}. Type 'help' for available commands."

        return await handler(args)

    async def _cmd_help(self, args: list[str]) -> str:
        return HELP_TEXT

    async def _cmd_status(self, args: list[str]) -> str:
        if self._orchestrator:
            statuses = self._orchestrator.get_agent_statuses()
            if not statuses:
                return "[yellow]No agents registered yet.[/yellow]"

            # Group by department
            by_dept: dict[str, list[tuple[str, dict]]] = {}
            for aid, info in sorted(statuses.items()):
                dept = info.get("department", "unassigned")
                if dept not in by_dept:
                    by_dept[dept] = []
                by_dept[dept].append((aid, info))

            lines = ["[bold]Agent Statuses (by department):[/bold]"]
            dept_order = ["front_office", "middle_office", "back_office", "executive"]
            dept_labels = {
                "front_office": "Front Office",
                "middle_office": "Middle Office",
                "back_office": "Back Office",
                "executive": "Executive",
            }

            for dept in dept_order:
                agents = by_dept.pop(dept, [])
                if not agents:
                    continue
                lines.append(f"\n  [bold cyan]{dept_labels.get(dept, dept)}[/]")
                for aid, info in agents:
                    status = info.get("status", "UNKNOWN")
                    color = "green" if status == "RUNNING" else "red"
                    lines.append(f"    [{color}]{aid:25s} {status}[/]")

            # Unassigned
            for dept, agents in by_dept.items():
                if agents:
                    lines.append(f"\n  [dim]{dept}[/]")
                    for aid, info in agents:
                        status = info.get("status", "UNKNOWN")
                        color = "green" if status == "RUNNING" else "red"
                        lines.append(f"    [{color}]{aid:25s} {status}[/]")

            return "\n".join(lines)
        return "[yellow]Orchestrator not available.[/yellow]"

    async def _cmd_signals(self, args: list[str]) -> str:
        if self._dashboard and self._dashboard._signals:
            lines = ["[bold]Recent Signals:[/bold]"]
            for sig in self._dashboard._signals[:10]:
                symbol = sig.get("symbol", "--")
                direction = sig.get("direction", 0)
                d = "BUY" if direction > 0 else "SELL" if direction < 0 else "HOLD"
                strength = sig.get("strength", 0.0)
                lines.append(f"  {symbol:14s} {d:5s}  strength={strength:.2f}")
            return "\n".join(lines)
        return "[yellow]No signals available yet.[/yellow]"

    async def _cmd_risk(self, args: list[str]) -> str:
        if self._dashboard and self._dashboard._risk:
            r = self._dashboard._risk
            return (
                f"[bold]Risk Metrics:[/bold]\n"
                f"  VaR (95%):     {r.get('var_95', 0.0):.4f}\n"
                f"  VaR (99%):     {r.get('var_99', 0.0):.4f}\n"
                f"  Max Drawdown:  {r.get('max_drawdown', 0.0):.2f}%\n"
                f"  Curr Drawdown: {r.get('current_drawdown', 0.0):.2f}%\n"
                f"  Kill Switch:   {'ACTIVE' if r.get('kill_switch_active') else 'OFF'}"
            )
        return "[yellow]No risk data available yet.[/yellow]"

    async def _cmd_regime(self, args: list[str]) -> str:
        if self._dashboard and self._dashboard._regimes:
            lines = ["[bold]Market Regimes:[/bold]"]
            for scope in ["INDIA", "US", "CRYPTO"]:
                data = self._dashboard._regimes.get(scope, {})
                regime = data.get("regime", "--")
                conf = data.get("confidence", 0.0)
                lines.append(f"  {scope:8s}  {regime:16s}  conf={conf:.1%}")
            return "\n".join(lines)
        return "[yellow]No regime data available yet.[/yellow]"

    async def _cmd_debate(self, args: list[str]) -> str:
        if self._dashboard and self._dashboard._debates:
            lines = ["[bold]Recent Debates:[/bold]"]
            for d in self._dashboard._debates[:5]:
                symbol = d.get("symbol", "--")
                consensus = d.get("consensus", "--")
                lines.append(f"  {symbol:12s}  consensus={consensus}")
            return "\n".join(lines)
        return "[yellow]No debate data available yet.[/yellow]"

    async def _cmd_portfolio(self, args: list[str]) -> str:
        p = self._dashboard._portfolio if self._dashboard else {}
        return (
            f"[bold]Portfolio:[/bold]\n"
            f"  NAV:       ${p.get('nav', 0.0):,.2f}\n"
            f"  Cash:      ${p.get('cash', 0.0):,.2f}\n"
            f"  Positions: {p.get('positions', 0)}"
        )

    async def _cmd_departments(self, args: list[str]) -> str:
        """Show department-level overview."""
        if not self._orchestrator:
            return "[yellow]Orchestrator not available.[/yellow]"

        depts = self._orchestrator.get_department_statuses()
        if not depts:
            return "[yellow]No departments registered.[/yellow]"

        lines = ["[bold]Department Overview:[/bold]"]
        for d in depts:
            health = "[green]HEALTHY[/]" if d.get("healthy") else "[red]DEGRADED[/]"
            lines.append(
                f"  {d['display_name']:40s} "
                f"{d['agents_running']}/{d['agents_total']} agents  {health}"
            )
        return "\n".join(lines)

    async def _cmd_cio(self, args: list[str]) -> str:
        """Enter CIO chat mode."""
        if self._cio_chat is None:
            from app.tui.cio_chat import CIOChat
            self._cio_chat = CIOChat(
                orchestrator=self._orchestrator,
                dashboard=self._dashboard,
            )

        console.print("\n[bold cyan]CIO Chat Mode[/bold cyan]")
        console.print("[dim]Type your questions in natural language. Type 'exit' to return.[/dim]\n")

        while True:
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("cio> ")
                )
                if raw.strip().lower() in ("exit", "quit", "back"):
                    return "[dim]Returned to command mode.[/dim]"
                if not raw.strip():
                    continue

                response = await self._cio_chat.chat(raw.strip())
                console.print(f"\n{response}\n")
            except EOFError:
                return "[dim]Returned to command mode.[/dim]"
            except KeyboardInterrupt:
                return "\n[dim]Returned to command mode.[/dim]"

    async def _cmd_agents_config(self, args: list[str]) -> str:
        """Show agent-per-role configuration."""
        from app.llm.agent_config import DEFAULT_AGENT_CONFIGS
        from app.llm.provider_registry import provider_registry

        available_llms = provider_registry.list_available()

        lines = [
            "[bold]Agent Configuration:[/bold]",
            f"  Available LLM providers: {', '.join(available_llms) if available_llms else 'none configured'}",
            "",
        ]

        dept_order = ["front_office", "middle_office", "back_office", "executive"]
        dept_labels = {
            "front_office": "Front Office",
            "middle_office": "Middle Office",
            "back_office": "Back Office",
            "executive": "Executive",
        }

        for dept in dept_order:
            configs = [c for c in DEFAULT_AGENT_CONFIGS if c.department == dept]
            if not configs:
                continue
            lines.append(f"  [bold cyan]{dept_labels[dept]}[/]")
            for cfg in configs:
                llm = cfg.llm_provider or "rule-based"
                enabled = "[green]ON[/]" if cfg.enabled else "[red]OFF[/]"
                lines.append(f"    {cfg.instance_id:25s} role={cfg.role:20s} llm={llm:10s} {enabled}")
            lines.append("")

        return "\n".join(lines)

    async def _cmd_mode(self, args: list[str]) -> str:
        if not args:
            return (
                f"[bold]Current mode:[/bold] {settings.system_mode.value}\n"
                f"Usage: mode <PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS>"
            )
        new_mode = args[0].upper()
        try:
            settings.system_mode = SystemMode(new_mode)
            return f"[green]System mode changed to: {new_mode}[/green]"
        except ValueError:
            return f"[red]Invalid mode: {new_mode}[/red]. Use PAPER_TRADING, HUMAN_APPROVAL, or FULLY_AUTONOMOUS."

    async def _cmd_kill_switch(self, args: list[str]) -> str:
        return "[yellow]Kill switch toggle not implemented in local mode yet.[/yellow]"

    async def _cmd_symbols(self, args: list[str]) -> str:
        symbols = settings.all_symbols
        return (
            f"[bold]Trading Universe ({len(symbols)} symbols):[/bold]\n"
            f"  India:  {settings.india_symbols}\n"
            f"  US:     {settings.us_symbols}\n"
            f"  Crypto: {settings.crypto_symbols}"
        )

    async def _cmd_config(self, args: list[str]) -> str:
        from app.llm.provider_registry import provider_registry

        available_llms = provider_registry.list_available()
        return (
            f"[bold]Configuration:[/bold]\n"
            f"  Mode:            {settings.system_mode.value}\n"
            f"  CIO Mode:        {settings.cio_mode.value}\n"
            f"  Storage:         {settings.storage_backend.value}\n"
            f"  Max Drawdown:    {settings.risk_max_drawdown_pct}%\n"
            f"  Max Position:    {settings.risk_max_position_pct}%\n"
            f"  Max Leverage:    {settings.risk_max_leverage}x\n"
            f"  VaR Limit:       {settings.risk_var_limit_pct}%\n"
            f"  LLM Providers:   {', '.join(available_llms) if available_llms else 'none'}\n"
            f"  Anthropic Key:   {'***' + settings.anthropic_api_key[-4:] if settings.anthropic_api_key else 'NOT SET'}\n"
            f"  OpenAI Key:      {'***' + settings.openai_api_key[-4:] if settings.openai_api_key else 'NOT SET'}\n"
            f"  Google Key:      {'***' + settings.google_api_key[-4:] if settings.google_api_key else 'NOT SET'}\n"
            f"  Symbols:         {len(settings.all_symbols)} total"
        )

    async def _cmd_quit(self, args: list[str]) -> str:
        self._should_quit = True
        return "[bold red]Shutting down Horizon Capital...[/bold red]"
