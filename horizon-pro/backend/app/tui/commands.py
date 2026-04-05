"""Interactive terminal command handler for Horizon Capital.

Provides a REPL-like command interface that runs alongside the dashboard,
allowing the CIO to issue commands like:
  status, signals, risk, regime, debate, mode, departments, cio, quit

Help is organized into six categories (progressive disclosure):
  Trading, Analysis, Intelligence, System, Broker, Advanced

Fuzzy suggestions are shown for unrecognized commands (difflib, cutoff=0.6).
"""

from __future__ import annotations

import asyncio
import difflib
from datetime import UTC
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config import SystemMode, settings

console = Console()

HELP_TEXT = (
    "\n[bold white]HORIZON PRO[/bold white] [dim]— Commands[/dim]\n\n"
    "  [bold cyan]Trading[/bold cyan]"
    "      [green]portfolio[/] | [green]orders[/]"
    " | [green]signals[/] | [green]backtest[/]\n"
    "  [bold cyan]Analysis[/bold cyan]"
    "     [green]risk[/] | [green]regime[/]"
    " | [green]performance[/] | [green]attribution[/]\n"
    "  [bold cyan]Intelligence[/bold cyan]"
    " [green]debate[/] | [green]models[/] | [green]cio[/]\n"
    "  [bold cyan]System[/bold cyan]"
    "       [green]status[/] | [green]departments[/]"
    " | [green]health[/] | [green]config[/] | [green]view[/]\n"
    "  [bold cyan]Broker[/bold cyan]"
    "       [green]connect[/] | [green]broker[/]"
    " | [green]disconnect[/] | [green]go-live[/]\n"
    "  [bold cyan]Advanced[/bold cyan]"
    "     [green]stress-test[/] | [green]alerts[/]"
    " | [green]report[/] | [green]exposures[/]\n\n"
    "  [dim]quit / exit  — Shutdown Horizon Capital[/dim]\n\n"
    "[dim]Type 'help <category>' to expand."
    "  Categories: trading analysis intelligence system broker advanced[/dim]\n"
)

HELP_DETAIL: dict[str, str] = {
    "trading": """
[bold cyan]Trading Commands[/bold cyan]

  [green]portfolio[/]           Show current portfolio (NAV, cash, positions)
  [green]positions[/]           Alias for portfolio
  [green]orders[/] [pending|all]  Show pending or all recent orders
  [green]approve[/] <id>        Approve a pending order (routes to broker)
  [green]reject[/] <id>         Reject a pending order
  [green]signals[/]             Show recent trading signals
  [green]backtest[/] <SYMBOL> [--days N] [--strategy NAME]
                        Run a walk-forward backtest on historical data
                        Strategies: momentum, mean_reversion, volatility, crisis
  [green]backtest results[/]    Show last backtest result summary
  [green]backtest list[/]       List all saved backtest runs
  [green]backtest compare[/] <id1> <id2>  Compare two runs side-by-side
""",
    "analysis": """
[bold cyan]Analysis Commands[/bold cyan]

  [green]risk[/]                      Show VaR, drawdown, Sharpe, kill switch
  [green]regime[/]                    Show market regime per scope (INDIA/US/CRYPTO)
  [green]performance[/] [period]      Show returns/Sharpe/Sortino (1d/7d/30d/90d/YTD/ALL)
  [green]attribution[/] [symbol]      Per-trade attribution breakdown
  [green]exposures[/]                 Show current exposures by market/symbol
""",
    "intelligence": """
[bold cyan]Intelligence Commands[/bold cyan]

  [green]debate[/]                    Show recent AI debate summaries
  [green]debate history[/]            Show debate sessions with linked orders
  [green]models[/]                    Show registered ML models
  [green]model stats[/]               Show Thompson Sampling strategy rotation stats
  [green]cio[/]                       Enter CIO chat mode (natural language)
""",
    "system": """
[bold cyan]System Commands[/bold cyan]

  [green]agents[/]               Show all agent statuses grouped by department
  [green]agents config[/]        Show agent-per-role and LLM configuration
  [green]health[/]               Show system health dashboard
  [green]workers[/]              Show background worker status
  [green]config[/]               Show current configuration (masked secrets)
  [green]status[/]               Alias for agents
  [green]view[/]                 Show current view mode
  [green]view minimal[/]         Switch to minimal (NAV + positions only)
  [green]view standard[/]        Switch to standard (default working view)
  [green]view full[/]            Switch to full (all panels)
  [green]mode[/] <MODE>          Switch system mode (PAPER_TRADING etc.)
  [green]kill-switch[/]          Toggle the kill switch
  [green]symbols[/]              Show trading universe
  [green]data[/]                 Show live market data, feeds, and feature cache
  [green]dashboard[/]            Launch full-screen live dashboard (Ctrl+C to exit)
  [green]office[/]               Show pixel agent office (animated ASCII)
  [green]setup[/]                Re-run the onboarding wizard
  [green]quit[/] / [green]exit[/]      Shutdown Horizon Capital
""",
    "broker": """
[bold cyan]Broker Commands[/bold cyan]

  [green]connect[/]                      Show connected broker status
  [green]connect alpaca[/]               Connect Alpaca (interactive, paper or live)
  [green]connect zerodha[/]              Connect Zerodha (interactive)
  [green]broker[/] / [green]broker status[/]       Show broker connection health
  [green]broker account[/]               Show real account balances/equity
  [green]broker positions[/]             Show real broker positions
  [green]go-live[/]                      Guided checklist to switch to live trading
  [green]disconnect alpaca[/]            Remove Alpaca credentials, revert to paper
  [green]disconnect zerodha[/]           Remove Zerodha credentials, revert to paper
  [green]ai-routing[/]                   Show AI provider per department
  [green]ai-routing[/] <dept> <provider> Assign AI provider (claude/openai/gemini/auto/none)
""",
    "advanced": """
[bold cyan]Advanced Commands[/bold cyan]

  [green]stress-test[/]                   Run all historical crisis scenarios
  [green]stress-test[/] <SCENARIO>        Run a specific scenario (GFC_2008, COVID_2020, etc.)
  [green]alerts[/]                        Show recent alerts
  [green]alert rules[/]                   Show alert rules and their status
  [green]report[/] [daily|weekly|monthly] Generate portfolio report
  [green]report export[/] [csv|json]      Export last report to file
  [green]exposures[/]                     Show current exposures by market/symbol
  [green]attribution[/] [symbol]          Per-trade attribution breakdown
  [green]interrupt[/] <agent_id>          Pause a specific agent
  [green]override regime[/] <SCOPE> <REG> Manually set regime classification
  [green]risk-tolerance[/] <value>        Adjust max drawdown % at runtime
  [green]toggle sentiment[/]              Enable/disable sentiment agent
  [green]execution-mode[/] <MODE>         Change execution mode
""",
}


class CommandHandler:
    """Processes terminal commands and returns formatted output."""

    def __init__(self, dashboard=None, orchestrator=None) -> None:
        self._dashboard = dashboard
        self._orchestrator = orchestrator
        self._should_quit = False
        self._cio_chat = None  # Lazy-initialized
        self._last_backtest_result: dict | None = None

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
        if cmd == "override" and args and args[0].lower() == "regime":
            return await self._cmd_override_regime(args[1:])
        if cmd == "toggle" and args and args[0].lower() == "sentiment":
            return await self._cmd_toggle_sentiment(args[1:])
        if cmd == "execution-mode":
            return await self._cmd_execution_mode(args)
        if cmd == "broker" and args and args[0].lower() == "account":
            return await self._cmd_broker_account([])
        if cmd == "broker" and args and args[0].lower() == "positions":
            return await self._cmd_broker_positions([])
        if cmd == "broker" and args and args[0].lower() == "status":
            return await self._cmd_broker(args[1:])
        if cmd == "go-live":
            return await self._cmd_go_live(args)
        if cmd == "backtest" and args and args[0].lower() == "results":
            return await self._cmd_backtest_results([])
        if cmd == "backtest" and args and args[0].lower() == "list":
            return await self._cmd_backtest_list([])
        if cmd == "backtest" and args and args[0].lower() == "compare":
            return await self._cmd_backtest_compare(args[1:])
        if cmd == "alert" and args and args[0].lower() == "rules":
            return await self._cmd_alert_rules([])
        if cmd == "model" and args and args[0].lower() == "stats":
            return await self._cmd_model_stats([])
        if cmd == "debate" and args and args[0].lower() == "history":
            return await self._cmd_debate_history([])

        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "signals": self._cmd_signals,
            "risk": self._cmd_risk,
            "regime": self._cmd_regime,
            "debate": self._cmd_debate,
            "portfolio": self._cmd_portfolio,
            "positions": self._cmd_portfolio,
            "departments": self._cmd_departments,
            "cio": self._cmd_cio,
            "mode": self._cmd_mode,
            "kill-switch": self._cmd_kill_switch,
            "symbols": self._cmd_symbols,
            "data": self._cmd_data,
            "config": self._cmd_config,
            "setup": self._cmd_setup,
            "interrupt": self._cmd_interrupt,
            "risk-tolerance": self._cmd_risk_tolerance,
            "exposures": self._cmd_exposures,
            "attribution": self._cmd_attribution,
            "performance": self._cmd_performance,
            "workers": self._cmd_workers,
            "backtest": self._cmd_backtest,
            "stress-test": self._cmd_stress_test,
            "alerts": self._cmd_alerts,
            "report": self._cmd_report,
            "health": self._cmd_health,
            "view": self._cmd_view,
            "models": self._cmd_models,
            "office": self._cmd_office,
            "dashboard": self._cmd_dashboard,
            "orders": self._cmd_orders,
            "approve": self._cmd_approve,
            "reject": self._cmd_reject,
            "ai-routing": self._cmd_ai_routing,
            "connect": self._cmd_connect,
            "broker": self._cmd_broker,
            "disconnect": self._cmd_disconnect,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler is None:
            suggestion = self._suggest_command(cmd, list(handlers.keys()))
            if suggestion:
                return (
                    f"[red]Unknown command[/red] '{cmd}'. "
                    f"Did you mean '[green]{suggestion}[/green]'?"
                )
            return (
                f"[red]Unknown command:[/red] '{cmd}'. "
                "Type 'help' for available commands."
            )

        return await handler(args)

    @staticmethod
    def _suggest_command(user_input: str, all_commands: list[str]) -> str | None:
        """Return the closest matching command for a typo, or None."""
        matches = difflib.get_close_matches(user_input, all_commands, n=1, cutoff=0.6)
        return matches[0] if matches else None

    async def _cmd_help(self, args: list[str]) -> str:
        if args:
            category = args[0].lower()
            if category in HELP_DETAIL:
                return HELP_DETAIL[category]
            # Try to match a specific command description from detail pages
            for detail in HELP_DETAIL.values():
                if category in detail:
                    return detail
            return (
                f"[yellow]Unknown help topic:[/yellow] '{category}'\n"
                f"Available categories: {', '.join(HELP_DETAIL.keys())}"
            )
        return HELP_TEXT

    async def _cmd_view(self, args: list[str]) -> str:
        """Show or switch the dashboard view mode."""
        from app.tui.themes import VIEW_FULL, VIEW_MINIMAL, VIEW_STANDARD

        if not args:
            mode = self._dashboard.view_mode if self._dashboard else VIEW_STANDARD
            return (
                f"[bold]Current view mode:[/bold] [cyan]{mode}[/cyan]\n"
                "  [dim]view minimal   — NAV + positions only[/dim]\n"
                "  [dim]view standard  — watchlist + portfolio + risk (default)[/dim]\n"
                "  [dim]view full      — all panels including orders, agents, alerts[/dim]"
            )

        mode = args[0].lower()
        valid = {VIEW_MINIMAL: "minimal", VIEW_STANDARD: "standard", VIEW_FULL: "full"}
        if mode not in valid:
            return (
                f"[red]Unknown view mode:[/red] '{mode}'. "
                f"Use: {', '.join(valid.keys())}"
            )

        if self._dashboard:
            self._dashboard.set_view_mode(mode)
            return f"[green]View mode set to:[/green] [cyan]{mode}[/cyan]"
        return "[yellow]Dashboard not available.[/yellow]"

    async def _cmd_setup(self, args: list[str]) -> str:
        """Re-run the onboarding wizard to reconfigure API keys, brokers, etc."""
        from app.tui.onboarding import run_onboarding

        console.print("[bold cyan]Launching onboarding wizard...[/bold cyan]\n")
        try:
            await asyncio.get_event_loop().run_in_executor(None, run_onboarding)
        except (KeyboardInterrupt, EOFError):
            return "[yellow]Setup cancelled.[/yellow]"

        # Reload settings from updated .env
        import app.config as config_mod
        from app.config import Settings
        config_mod.settings = Settings()

        # Re-register LLM providers with new keys
        from app.llm.provider_registry import provider_registry
        provider_registry.auto_register_from_settings()

        return "[green]Onboarding complete. Settings reloaded.[/green]"

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
        console.print(
            "[dim]Type your questions in natural language."
            " Type 'exit' to return.[/dim]\n"
        )

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

        llm_list = (
            ", ".join(available_llms) if available_llms
            else "none configured"
        )
        lines = [
            "[bold]Agent Configuration:[/bold]",
            f"  Available LLM providers: {llm_list}",
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
                lines.append(
                    f"    {cfg.instance_id:25s} "
                    f"role={cfg.role:20s} "
                    f"llm={llm:10s} {enabled}"
                )
            lines.append("")

        return "\n".join(lines)

    async def _cmd_mode(self, args: list[str]) -> str:
        if not args:
            return (
                f"[bold]Current mode:[/bold] {settings.system_mode.value}\n"
                f"Usage: mode <PAPER_TRADING | HUMAN_APPROVAL"
                f" | FULLY_AUTONOMOUS>"
            )
        new_mode = args[0].upper()
        try:
            SystemMode(new_mode)  # validate
        except ValueError:
            return (
                f"[red]Invalid mode: {new_mode}[/red]. "
                "Use PAPER_TRADING, HUMAN_APPROVAL, "
                "or FULLY_AUTONOMOUS."
            )

        # Safety checks for live modes
        if new_mode in ("HUMAN_APPROVAL", "FULLY_AUTONOMOUS"):
            has_broker = bool(settings.alpaca_api_key or settings.zerodha_api_key)
            if not has_broker:
                console.print(
                    "[yellow]Warning: No broker credentials configured.[/yellow]\n"
                    "  Use 'connect alpaca' or 'connect zerodha' first."
                )

        if new_mode == "FULLY_AUTONOMOUS":
            console.print(
                "[bold red]WARNING: FULLY_AUTONOMOUS mode trades "
                "without human confirmation.[/bold red]"
            )
            try:
                confirm = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("  Type AUTONOMOUS to confirm: ")
                )
            except (EOFError, KeyboardInterrupt):
                return "[yellow]Mode change cancelled.[/yellow]"
            if confirm.strip() != "AUTONOMOUS":
                return "[yellow]Mode change cancelled.[/yellow]"

        settings.system_mode = SystemMode(new_mode)
        return f"[green]System mode changed to: {new_mode}[/green]"

    async def _cmd_kill_switch(self, args: list[str]) -> str:
        from app.core.kv_store import get_kv_store
        from app.core.messaging import AgentMessage, MessageType

        kv = get_kv_store()
        current = await kv.get("horizon:system:kill_switch")
        is_active = current == "1"

        if is_active:
            # Deactivate
            await kv.set("horizon:system:kill_switch", "0")
            if self._orchestrator:
                await self._orchestrator.bus.publish(
                    AgentMessage(
                        sender_id="cio-terminal",
                        channel="horizon.risk.kill_switch",
                        message_type=MessageType.KILL_SWITCH,
                        payload={"active": False, "reason": "Manual deactivation by CIO"},
                    )
                )
            return "[green]Kill switch DEACTIVATED.[/green] Trading resumed."
        else:
            # Activate
            await kv.set("horizon:system:kill_switch", "1")
            if self._orchestrator:
                await self._orchestrator.bus.publish(
                    AgentMessage(
                        sender_id="cio-terminal",
                        channel="horizon.risk.kill_switch",
                        message_type=MessageType.KILL_SWITCH,
                        payload={"active": True, "reason": "Manual activation by CIO"},
                    )
                )
                # Also emit risk alert
                await self._orchestrator.bus.publish(
                    AgentMessage(
                        sender_id="cio-terminal",
                        channel="horizon.risk.alert",
                        message_type=MessageType.RISK_ALERT,
                        payload={
                            "alert_type": "KILL_SWITCH_ACTIVATED",
                            "reason": "Manual activation by CIO",
                            "kill_switch_active": True,
                        },
                    )
                )
            return (
                "[bold red]Kill switch ACTIVATED.[/bold red] "
                "All real trading halted. "
                "Mode forced to PAPER_TRADING."
            )

    async def _cmd_symbols(self, args: list[str]) -> str:
        symbols = settings.all_symbols
        return (
            f"[bold]Trading Universe ({len(symbols)} symbols):[/bold]\n"
            f"  India:  {settings.india_symbols}\n"
            f"  US:     {settings.us_symbols}\n"
            f"  Crypto: {settings.crypto_symbols}"
        )

    async def _cmd_data(self, args: list[str]) -> str:
        """Show live market data: prices, OHLCV counts, features, feed status."""
        from app.config import settings as _settings
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        lines = ["[bold]Market Data Status[/bold]"]

        # -- Latest prices --
        lines.append("\n  [bold cyan]Latest Prices[/bold cyan]")
        all_symbols = _settings.all_symbols
        for symbol in all_symbols:
            # Try canonical (RELIANCE.NSE) then raw (RELIANCE)
            raw = symbol.split(".")[0] if "." in symbol else symbol
            price_str = await kv.get(f"horizon:price:{symbol}")
            if not price_str:
                price_str = await kv.get(f"horizon:price:{raw}")
            if price_str:
                try:
                    price = float(price_str)
                    lines.append(f"    {symbol:20s} ${price:>12,.2f}")
                except (ValueError, TypeError):
                    lines.append(f"    {symbol:20s} [dim]{price_str}[/dim]")
            else:
                lines.append(f"    {symbol:20s} [dim]no data[/dim]")

        # -- OHLCV row counts per symbol --
        lines.append("\n  [bold cyan]OHLCV Data (rows per symbol)[/bold cyan]")
        try:
            from sqlalchemy import text

            def _get_session_factory():
                from app.core.runtime import get_session_factory
                return get_session_factory()

            async with _get_session_factory()() as session:
                result = await session.execute(
                    text(
                        "SELECT symbol, exchange, COUNT(*) as cnt, "
                        "MAX(timestamp) as latest "
                        "FROM ohlcv GROUP BY symbol, exchange "
                        "ORDER BY symbol"
                    )
                )
                rows = result.fetchall()
                if rows:
                    for row in rows:
                        latest = str(row.latest)[:10] if row.latest else "?"
                        lines.append(
                            f"    {row.symbol:16s} {row.exchange:8s} "
                            f"{row.cnt:>6,} bars  latest={latest}"
                        )
                else:
                    lines.append("    [dim]No OHLCV data yet (backfill pending)[/dim]")
        except Exception as exc:
            lines.append(f"    [yellow]DB query failed: {exc}[/yellow]")

        # -- Feature cache status --
        lines.append("\n  [bold cyan]Feature Cache[/bold cyan]")
        for symbol in all_symbols:
            raw = symbol.split(".")[0] if "." in symbol else symbol
            feat_data = await kv.hgetall(f"horizon:features:{raw}:1d")
            if feat_data:
                ts = feat_data.get("timestamp", "?")[:19]
                n_features = len([
                    k for k in feat_data
                    if k not in ("timestamp", "symbol", "timeframe")
                ])
                lines.append(
                    f"    {symbol:20s} {n_features:>2} indicators  "
                    f"updated={ts}"
                )
            else:
                lines.append(f"    {symbol:20s} [dim]not computed[/dim]")

        # -- Forex rate --
        lines.append("\n  [bold cyan]Forex[/bold cyan]")
        forex_rate = await kv.get("horizon:forex:usd_inr")
        if forex_rate:
            lines.append(f"    USD/INR: {float(forex_rate):,.2f}")
        else:
            lines.append("    USD/INR: [dim]not available[/dim]")

        # -- Feed health / circuit breakers --
        lines.append("\n  [bold cyan]Feed Status[/bold cyan]")
        feed_status = await kv.hgetall("horizon:worker:data_ingestion")
        if feed_status:
            last_check = feed_status.get("last_check", "?")[:19]
            lines.append(f"    Last health check:  {last_check}")
            # Map circuit breaker states to user-friendly labels
            _cb_labels = {
                "CLOSED": ("[green]", "OK"),
                "HALF_OPEN": ("[yellow]", "RECOVERING"),
                "OPEN": ("[red]", "DOWN"),
            }
            for key in ("yahoo_circuit", "crypto_circuit", "forex_circuit"):
                state = feed_status.get(key, "?")
                name = key.replace("_circuit", "").title()
                color, label = _cb_labels.get(state, ("[dim]", state))
                lines.append(f"    {name:12s} {color}{label}[/]")
        else:
            lines.append("    [dim]Feed health not reported yet[/dim]")

        # -- Last update timestamps --
        lines.append("\n  [bold cyan]Last Updates[/bold cyan]")
        eod_ts = await kv.get("horizon:data:eod_updated")
        crypto_ts = await kv.get("horizon:data:crypto_updated")
        lines.append(
            f"    Yahoo EOD:  {eod_ts[:19] if eod_ts else '[dim]never[/dim]'}"
        )
        lines.append(
            f"    CoinGecko:  {crypto_ts[:19] if crypto_ts else '[dim]never[/dim]'}"
        )

        return "\n".join(lines)

    async def _cmd_config(self, args: list[str]) -> str:
        from app.llm.provider_registry import provider_registry

        available_llms = provider_registry.list_available()
        llm_list = (
            ", ".join(available_llms) if available_llms
            else "none"
        )
        anthropic_key = (
            "***" + settings.anthropic_api_key[-4:]
            if settings.anthropic_api_key else "NOT SET"
        )
        openai_key = (
            "***" + settings.openai_api_key[-4:]
            if settings.openai_api_key else "NOT SET"
        )
        google_key = (
            "***" + settings.google_api_key[-4:]
            if settings.google_api_key else "NOT SET"
        )
        return (
            f"[bold]Configuration:[/bold]\n"
            f"  Mode:            {settings.system_mode.value}\n"
            f"  CIO Mode:        {settings.cio_mode.value}\n"
            f"  Storage:         {settings.storage_backend.value}\n"
            f"  Max Drawdown:    {settings.risk_max_drawdown_pct}%\n"
            f"  Max Position:    {settings.risk_max_position_pct}%\n"
            f"  Max Leverage:    {settings.risk_max_leverage}x\n"
            f"  VaR Limit:       {settings.risk_var_limit_pct}%\n"
            f"  LLM Providers:   {llm_list}\n"
            f"  Anthropic Key:   {anthropic_key}\n"
            f"  OpenAI Key:      {openai_key}\n"
            f"  Google Key:      {google_key}\n"
            f"  Symbols:         {len(settings.all_symbols)} total"
        )

    # ------------------------------------------------------------------
    # Phase 2 CIO Power Commands
    # ------------------------------------------------------------------

    async def _cmd_interrupt(self, args: list[str]) -> str:
        """Pause a specific agent."""
        if not args:
            return "Usage: interrupt <agent_id>"
        if not self._orchestrator:
            return "[yellow]Orchestrator not available.[/yellow]"

        agent_id = args[0]
        slots = self._orchestrator._slots
        if agent_id not in slots:
            return f"[red]Agent not found:[/red] {agent_id}"

        slot = slots[agent_id]
        if slot.status == "STOPPED":
            return f"[yellow]{agent_id} is already stopped.[/yellow]"

        await self._orchestrator._cancel_agent(slot)
        return f"[yellow]{agent_id} paused.[/yellow] Use 'status' to verify."

    async def _cmd_override_regime(self, args: list[str]) -> str:
        """Manually override regime classification for a scope."""
        if len(args) < 2:
            return (
                "Usage: override regime <SCOPE> <REGIME>\n"
                "  Scopes: INDIA, US, CRYPTO\n"
                "  Regimes: BULL, BEAR, NEUTRAL, CRISIS, HIGH_VOL"
            )

        scope = args[0].upper()
        regime = args[1].upper()

        valid_scopes = {"INDIA", "US", "CRYPTO"}
        valid_regimes = {
            "BULL", "BEAR", "NEUTRAL", "CRISIS",
            "HIGH_VOL", "HIGH_VOLATILITY",
        }

        if scope not in valid_scopes:
            return f"[red]Invalid scope:[/red] {scope}. Use: {', '.join(valid_scopes)}"
        if regime not in valid_regimes:
            return f"[red]Invalid regime:[/red] {regime}. Use: {', '.join(valid_regimes)}"

        if self._orchestrator:
            from app.core.messaging import AgentMessage, MessageType
            await self._orchestrator.bus.publish(
                AgentMessage(
                    sender_id="cio-terminal",
                    channel="horizon.regime.update",
                    message_type=MessageType.REGIME_UPDATE,
                    payload={
                        "market_scope": scope,
                        "regime": regime,
                        "confidence": 1.0,
                        "source": "manual_override",
                    },
                )
            )

        return f"[green]Regime for {scope} overridden to {regime}[/green]"

    async def _cmd_risk_tolerance(self, args: list[str]) -> str:
        """Adjust risk_max_drawdown_pct at runtime."""
        if not args:
            dd = settings.risk_max_drawdown_pct
            return (
                f"[bold]Current risk tolerance:[/bold] "
                f"{dd}% max drawdown\n"
                f"Usage: risk-tolerance <value>"
            )

        try:
            value = float(args[0])
            if not 1.0 <= value <= 50.0:
                return "[red]Value must be between 1.0 and 50.0[/red]"
            old = settings.risk_max_drawdown_pct
            settings.risk_max_drawdown_pct = value
            return f"[green]Max drawdown changed: {old}% -> {value}%[/green]"
        except ValueError:
            return f"[red]Invalid number:[/red] {args[0]}"

    async def _cmd_toggle_sentiment(self, args: list[str]) -> str:
        """Enable/disable the sentiment agent."""
        if not self._orchestrator:
            return "[yellow]Orchestrator not available.[/yellow]"

        slots = self._orchestrator._slots
        sentiment_id = None
        for aid in slots:
            if "sentiment" in aid:
                sentiment_id = aid
                break

        if not sentiment_id:
            return "[yellow]Sentiment agent not found.[/yellow]"

        slot = slots[sentiment_id]
        if slot.status == "RUNNING":
            await self._orchestrator._cancel_agent(slot)
            return f"[yellow]Sentiment agent ({sentiment_id}) DISABLED.[/yellow]"
        else:
            await self._orchestrator._launch_agent(slot)
            return f"[green]Sentiment agent ({sentiment_id}) ENABLED.[/green]"

    async def _cmd_exposures(self, args: list[str]) -> str:
        """Show current exposures by market/symbol."""
        if not self._dashboard:
            return "[yellow]Dashboard not available.[/yellow]"

        signals = self._dashboard._signals
        if not signals:
            return "[yellow]No signal data available to compute exposures.[/yellow]"

        # Aggregate by symbol
        by_symbol: dict[str, dict] = {}
        for sig in signals[:20]:
            symbol = sig.get("symbol", "")
            if symbol and symbol not in by_symbol:
                direction = sig.get("direction", 0)
                d = "LONG" if direction > 0 else "SHORT" if direction < 0 else "FLAT"
                by_symbol[symbol] = {
                    "direction": d,
                    "strength": sig.get("strength", 0.0),
                    "strategy": sig.get("strategy_name", ""),
                }

        lines = ["[bold]Current Exposures:[/bold]"]
        for sym, info in sorted(by_symbol.items()):
            d = info["direction"]
            if d == "LONG":
                color = "green"
            elif d == "SHORT":
                color = "red"
            else:
                color = "dim"
            lines.append(
                f"  {sym:16s} [{color}]{d:6s}[/] "
                f"strength={info['strength']:.2f}"
                f"  via {info['strategy']}"
            )

        if not by_symbol:
            lines.append("  [dim]No active exposures[/dim]")
        return "\n".join(lines)

    async def _cmd_attribution(self, args: list[str]) -> str:
        """Show per-trade attribution breakdown."""
        symbol = args[0] if args else None

        # Try to get attribution engine from orchestrator
        try:
            # Look for engine on orchestrator (it may not be wired yet)
            engine = getattr(
                self._orchestrator,
                "_attribution_engine",
                None,
            )
            if engine is None:
                return (
                    "[yellow]Attribution engine not "
                    "initialized. Trade attributions will "
                    "be available after Phase 2 "
                    "wiring.[/yellow]"
                )

            attributions = engine.get_attributions(
                symbol=symbol, limit=10,
            )
            if not attributions:
                suffix = (
                    " for " + symbol if symbol else ""
                )
                return (
                    "[yellow]No attributions found"
                    f"{suffix}.[/yellow]"
                )

            lines = ["[bold]Trade Attribution Breakdown:[/bold]"]
            for a in attributions:
                lines.append(
                    f"\n  [cyan]{a['symbol']}[/] "
                    f"({a['side']}) — "
                    f"{a['strategy_name']}"
                )
                lines.append(
                    f"    Strategy Alpha:  "
                    f"{a['strategy_alpha']:.2f}"
                )
                lines.append(
                    f"    Sentiment Alpha: "
                    f"{a['sentiment_alpha']:.2f}"
                )
                regime_inf = a['regime_influence']
                lines.append(
                    f"    Regime:          "
                    f"{a['regime']} "
                    f"(influence={regime_inf:.2f})"
                )
                lines.append(
                    f"    Risk Scaling:    "
                    f"{a['risk_scaling']:.2f}"
                )
                lines.append(
                    f"    Debate:          "
                    f"FOR={a['debate_for']} "
                    f"AGAINST={a['debate_against']} "
                    f"consensus="
                    f"{a['debate_consensus_score']:.2f}"
                )
            return "\n".join(lines)
        except ImportError:
            return "[yellow]Attribution engine not available.[/yellow]"

    async def _cmd_execution_mode(self, args: list[str]) -> str:
        """Change execution mode at runtime."""
        if not args:
            return (
                f"[bold]Current execution mode:[/bold] {settings.system_mode.value}\n"
                f"Usage: execution-mode <PAPER_TRADING | HUMAN_APPROVAL | FULLY_AUTONOMOUS>"
            )
        return await self._cmd_mode(args)

    # ------------------------------------------------------------------
    # Backtesting & Analytics
    # ------------------------------------------------------------------

    async def _cmd_performance(self, args: list[str]) -> str:
        """Show performance metrics for a given period."""
        period = args[0].upper() if args else "30d"
        valid = {"1D", "7D", "30D", "90D", "YTD", "ALL"}
        if period not in valid:
            return f"[red]Invalid period:[/red] {period}. Use: {', '.join(sorted(valid))}"

        try:
            from app.services.performance import PerformanceService
            snapshot = await PerformanceService.compute_snapshot(period.lower())
        except Exception as exc:
            return f"[yellow]Performance computation failed: {exc}[/yellow]"

        return (
            f"[bold]Performance ({period}):[/bold]\n"
            f"  Total Return:      {snapshot['total_return']:+.4%}\n"
            f"  Annualized Return: {snapshot['annualized_return']:+.4%}\n"
            f"  Sharpe Ratio:      {snapshot['sharpe']:.4f}\n"
            f"  Sortino Ratio:     {snapshot['sortino']:.4f}\n"
            f"  Calmar Ratio:      {snapshot['calmar']:.4f}\n"
            f"  Max Drawdown:      {snapshot['max_drawdown']:.4%}\n"
            f"  Win Rate:          {snapshot['win_rate']:.1%}\n"
            f"  Profit Factor:     {snapshot['profit_factor']:.2f}\n"
            f"  Total Trades:      {snapshot['total_trades']}"
        )

    async def _cmd_workers(self, args: list[str]) -> str:
        """Show background worker status."""
        lines = ["[bold]Background Workers:[/bold]"]
        worker_names = [
            ("data_ingestion_worker", "Data Ingestion"),
            ("feature_computation_worker", "Feature Computation"),
            ("performance_worker", "Performance Analytics"),
            ("macro_worker", "Macro Factor"),
            ("position_monitor_worker", "Position Monitor"),
        ]

        for task_name, display_name in worker_names:
            # Check if task exists in current event loop
            status = "[yellow]UNKNOWN[/]"
            for task in asyncio.all_tasks():
                if task.get_name() == task_name:
                    if task.done():
                        exc = task.exception() if not task.cancelled() else None
                        if exc:
                            status = f"[red]CRASHED ({type(exc).__name__})[/]"
                        elif task.cancelled():
                            status = "[red]CANCELLED[/]"
                        else:
                            status = "[dim]COMPLETED[/]"
                    else:
                        status = "[green]RUNNING[/]"
                    break
            else:
                status = "[dim]NOT STARTED[/]"

            lines.append(f"  {display_name:30s} {status}")

        return "\n".join(lines)

    async def _cmd_backtest(self, args: list[str]) -> str:
        """Run a backtest on historical data."""
        if not args:
            return (
                "Usage: backtest <SYMBOL> [--days N] [--strategy NAME]\n"
                "  Strategies: momentum, mean_reversion, volatility, crisis\n"
                "  Example: backtest RELIANCE.NSE --days 120 --strategy momentum"
            )

        symbol = args[0]
        days = 252
        strategy_name = "momentum"

        # Parse optional flags
        i = 1
        while i < len(args):
            if args[i] == "--days" and i + 1 < len(args):
                try:
                    days = int(args[i + 1])
                except ValueError:
                    return f"[red]Invalid days value:[/red] {args[i + 1]}"
                i += 2
            elif args[i] == "--strategy" and i + 1 < len(args):
                strategy_name = args[i + 1].lower()
                i += 2
            else:
                i += 1

        console.print(
            f"[dim]Running backtest on {symbol} "
            f"({days}d, strategy={strategy_name})...[/dim]"
        )

        try:
            from datetime import datetime, timedelta

            from app.backtesting.backtest_broker import SimOrder
            from app.backtesting.backtest_engine import BacktestEngine

            end_date = datetime.now(UTC)
            start_date = end_date - timedelta(days=days)

            # Create strategy function based on name
            def _make_strategy(name: str):
                if name == "momentum":
                    def strategy(history, context):
                        if len(history) < 20:
                            return None
                        sma_fast = float(history["close"].iloc[-5:].mean())
                        sma_slow = float(history["close"].iloc[-20:].mean())
                        if sma_fast > sma_slow * 1.02 and context["position_qty"] == 0:
                            qty = context["cash"] * 0.1 / float(history["close"].iloc[-1])
                            return SimOrder(symbol=symbol, side="BUY", quantity=round(qty, 4))
                        elif sma_fast < sma_slow * 0.98 and context["position_qty"] > 0:
                            return SimOrder(
                                symbol=symbol,
                                side="SELL",
                                quantity=context["position_qty"],
                            )
                        return None
                elif name == "mean_reversion":
                    def strategy(history, context):
                        if len(history) < 20:
                            return None
                        close = history["close"]
                        sma = float(close.iloc[-20:].mean())
                        std = float(close.iloc[-20:].std())
                        if std == 0:
                            return None
                        z_score = (float(close.iloc[-1]) - sma) / std
                        if z_score < -2.0 and context["position_qty"] == 0:
                            qty = context["cash"] * 0.1 / float(close.iloc[-1])
                            return SimOrder(symbol=symbol, side="BUY", quantity=round(qty, 4))
                        elif z_score > 1.0 and context["position_qty"] > 0:
                            return SimOrder(
                                symbol=symbol,
                                side="SELL",
                                quantity=context["position_qty"],
                            )
                        return None
                elif name == "volatility":
                    def strategy(history, context):
                        if len(history) < 30:
                            return None
                        returns = history["close"].pct_change().dropna()
                        vol = float(returns.iloc[-20:].std())
                        avg_vol = float(returns.iloc[-30:].std())
                        if vol < avg_vol * 0.7 and context["position_qty"] == 0:
                            qty = context["cash"] * 0.1 / float(history["close"].iloc[-1])
                            return SimOrder(symbol=symbol, side="BUY", quantity=round(qty, 4))
                        elif vol > avg_vol * 1.5 and context["position_qty"] > 0:
                            return SimOrder(
                                symbol=symbol,
                                side="SELL",
                                quantity=context["position_qty"],
                            )
                        return None
                else:  # crisis / default
                    def strategy(history, context):
                        if len(history) < 50:
                            return None
                        close = history["close"]
                        sma_50 = float(close.iloc[-50:].mean())
                        current = float(close.iloc[-1])
                        if current > sma_50 and context["position_qty"] == 0:
                            qty = context["cash"] * 0.05 / current
                            return SimOrder(symbol=symbol, side="BUY", quantity=round(qty, 4))
                        elif current < sma_50 * 0.95 and context["position_qty"] > 0:
                            return SimOrder(
                                symbol=symbol,
                                side="SELL",
                                quantity=context["position_qty"],
                            )
                        return None
                return strategy

            from app.config import settings as _cfg
            engine = BacktestEngine(initial_capital=_cfg.initial_capital_usd)
            result = await engine.run(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                strategy=_make_strategy(strategy_name),
            )

            self._last_backtest_result = {
                "symbol": result.symbol,
                "bars": result.bars_processed,
                "initial": result.initial_capital,
                "final": result.final_capital,
                "trades": len(result.trades),
                "metrics": result.metrics,
            }

            # Persist to backtest_runs table
            run_id = await self._save_backtest_run(
                symbol=symbol,
                strategy=strategy_name,
                start_date=start_date,
                end_date=end_date,
                result=self._last_backtest_result,
            )

            m = result.metrics
            return (
                f"[bold green]Backtest Complete: {symbol}[/bold green]\n"
                f"  Period:            {start_date.date()} -> {end_date.date()}\n"
                f"  Strategy:          {strategy_name}\n"
                f"  Bars Processed:    {result.bars_processed}\n"
                f"  Initial Capital:   ${result.initial_capital:,.2f}\n"
                f"  Final Capital:     ${result.final_capital:,.2f}\n"
                f"  Total Return:      {m.get('total_return', 0):+.4%}\n"
                f"  Sharpe Ratio:      {m.get('sharpe_ratio', 0):.4f}\n"
                f"  Max Drawdown:      {m.get('max_drawdown', 0):.4%}\n"
                f"  Win Rate:          {m.get('win_rate', 0):.1%}\n"
                f"  Profit Factor:     {m.get('profit_factor', 0):.2f}\n"
                f"  Total Trades:      {len(result.trades)}\n"
                f"  Omega Ratio:       {m.get('omega_ratio', 0):.4f}\n"
                f"  Recovery Factor:   {m.get('recovery_factor', 0):.4f}\n"
                f"  [dim]Run ID: {run_id}[/dim]"
            )
        except Exception as exc:
            return f"[red]Backtest failed:[/red] {exc}"

    async def _save_backtest_run(
        self,
        symbol: str,
        strategy: str,
        start_date,
        end_date,
        result: dict,
    ) -> str:
        """Persist a backtest result to the backtest_runs table."""
        import uuid as _uuid

        import orjson
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        run_id = str(_uuid.uuid4())[:8]
        m = result.get("metrics", {})
        try:
            async with _get_sf()() as session:
                await session.execute(
                    text("""
                        INSERT INTO backtest_runs
                            (id, symbol, strategy, start_date, end_date,
                             bars_processed, initial_capital, final_capital,
                             total_return, sharpe_ratio, max_drawdown,
                             win_rate, total_trades, metrics)
                        VALUES
                            (:id, :symbol, :strategy, :start_date, :end_date,
                             :bars, :initial, :final,
                             :ret, :sharpe, :dd,
                             :wr, :trades, :metrics)
                    """),
                    {
                        "id": run_id,
                        "symbol": symbol,
                        "strategy": strategy,
                        "start_date": start_date,
                        "end_date": end_date,
                        "bars": result.get("bars", 0),
                        "initial": result.get("initial", 0.0),
                        "final": result.get("final", 0.0),
                        "ret": m.get("total_return", 0.0),
                        "sharpe": m.get("sharpe_ratio", 0.0),
                        "dd": m.get("max_drawdown", 0.0),
                        "wr": m.get("win_rate", 0.0),
                        "trades": result.get("trades", 0),
                        "metrics": orjson.dumps(m).decode(),
                    },
                )
                await session.commit()
        except Exception as exc:
            console.print(f"[dim]Backtest save failed: {exc}[/dim]")
        return run_id

    async def _cmd_backtest_list(self, args: list[str]) -> str:
        """List all persisted backtest runs."""
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT id, symbol, strategy, start_date, end_date,
                           total_return, sharpe_ratio, max_drawdown, total_trades, created_at
                    FROM backtest_runs
                    ORDER BY created_at DESC
                    LIMIT 20
                """))
                rows = result.fetchall()

            if not rows:
                return "[yellow]No backtest runs saved yet.[/yellow]"

            lines = [
                "[bold]Saved Backtest Runs:[/bold]",
                f"  {'ID':8s}  {'Symbol':16s}  {'Strategy':14s}  "
                f"{'Return':>8s}  {'Sharpe':>7s}  {'MaxDD':>7s}  "
                f"{'Trades':>6s}  Date",
            ]
            for r in rows:
                ret = r.total_return or 0.0
                ret_color = "green" if ret >= 0 else "red"
                date = str(r.created_at)[:10] if r.created_at else "?"
                lines.append(
                    f"  {r.id:8s}  {r.symbol:16s}  {r.strategy:14s}  "
                    f"[{ret_color}]{ret:+8.2%}[/]  "
                    f"{(r.sharpe_ratio or 0):7.4f}  "
                    f"{(r.max_drawdown or 0):7.4%}  "
                    f"{(r.total_trades or 0):6d}  {date}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]backtest list failed:[/red] {exc}"

    async def _cmd_backtest_compare(self, args: list[str]) -> str:
        """Compare two backtest runs side-by-side."""
        if len(args) < 2:
            return "Usage: backtest compare <id1> <id2>"

        import orjson
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        id1, id2 = args[0], args[1]
        try:
            async with _get_sf()() as session:
                r1_row = (await session.execute(
                    text("SELECT * FROM backtest_runs WHERE id = :id"), {"id": id1}
                )).fetchone()
                r2_row = (await session.execute(
                    text("SELECT * FROM backtest_runs WHERE id = :id"), {"id": id2}
                )).fetchone()

            if not r1_row:
                return f"[red]Run not found:[/red] {id1}"
            if not r2_row:
                return f"[red]Run not found:[/red] {id2}"

            m1 = orjson.loads(r1_row.metrics or "{}")
            m2 = orjson.loads(r2_row.metrics or "{}")

            def _fmt(v: float | None, pct: bool = False) -> str:
                if v is None:
                    return "N/A"
                if pct:
                    return f"{v:+.2%}"
                return f"{v:.4f}"

            def _winner(v1: float | None, v2: float | None, higher_better: bool = True) -> tuple:
                if v1 is None or v2 is None:
                    return ("", "")
                better = v1 > v2 if higher_better else v1 < v2
                return ("[green]*[/]", "[dim] [/]") if better else ("[dim] [/]", "[green]*[/]")

            lines = [
                f"[bold]Backtest Comparison: {id1} vs {id2}[/bold]",
                f"  {'Metric':22s}  {id1:>12s}  {id2:>12s}",
                f"  {'-'*22}  {'-'*12}  {'-'*12}",
            ]

            def _row(label: str, v1: float | None, v2: float | None,
                     pct: bool = False, higher_better: bool = True) -> str:
                w1, w2 = _winner(v1, v2, higher_better)
                return (
                    f"  {label:22s}  "
                    f"{w1}{_fmt(v1, pct):>12s}  "
                    f"{w2}{_fmt(v2, pct):>12s}"
                )

            lines += [
                f"  {'Symbol':22s}  {r1_row.symbol:>12s}  {r2_row.symbol:>12s}",
                f"  {'Strategy':22s}  {r1_row.strategy:>12s}  {r2_row.strategy:>12s}",
                _row("Total Return", r1_row.total_return, r2_row.total_return, pct=True),
                _row("Sharpe Ratio", r1_row.sharpe_ratio, r2_row.sharpe_ratio),
                _row("Max Drawdown", r1_row.max_drawdown, r2_row.max_drawdown,
                     pct=True, higher_better=False),
                _row("Win Rate", m1.get("win_rate"), m2.get("win_rate"), pct=True),
                _row("Profit Factor", m1.get("profit_factor"), m2.get("profit_factor")),
                _row("Sortino Ratio", m1.get("sortino_ratio"), m2.get("sortino_ratio")),
                _row("Omega Ratio", m1.get("omega_ratio"), m2.get("omega_ratio")),
                _row("Calmar Ratio", m1.get("calmar_ratio"), m2.get("calmar_ratio")),
                f"  {'Total Trades':22s}  {(r1_row.total_trades or 0):>12d}"
                f"  {(r2_row.total_trades or 0):>12d}",
            ]
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]backtest compare failed:[/red] {exc}"

    async def _cmd_backtest_results(self, args: list[str]) -> str:
        """Show last backtest result summary."""
        if not self._last_backtest_result:
            return (
                "[yellow]No backtest has been run yet. "
                "Use 'backtest <SYMBOL>' to run one.[/yellow]"
            )

        r = self._last_backtest_result
        m = r.get("metrics", {})
        return (
            f"[bold]Last Backtest Result:[/bold]\n"
            f"  Symbol:          {r['symbol']}\n"
            f"  Bars:            {r['bars']}\n"
            f"  Initial:         ${r['initial']:,.2f}\n"
            f"  Final:           ${r['final']:,.2f}\n"
            f"  Total Return:    {m.get('total_return', 0):+.4%}\n"
            f"  Sharpe:          {m.get('sharpe_ratio', 0):.4f}\n"
            f"  Sortino:         {m.get('sortino_ratio', 0):.4f}\n"
            f"  Max Drawdown:    {m.get('max_drawdown', 0):.4%}\n"
            f"  Win Rate:        {m.get('win_rate', 0):.1%}\n"
            f"  Trades:          {r['trades']}\n"
            f"  Omega:           {m.get('omega_ratio', 0):.4f}\n"
            f"  Tail Ratio:      {m.get('tail_ratio', 0):.4f}\n"
            f"  Info Ratio:      {m.get('information_ratio', 0):.4f}\n"
            f"  Avg Win:         {m.get('avg_win', 0):.4f}\n"
            f"  Avg Loss:        {m.get('avg_loss', 0):.4f}\n"
            f"  Max Consec Loss: {m.get('max_consecutive_losses', 0)}"
        )

    # ------------------------------------------------------------------
    # Phase 6: Stress Testing
    # ------------------------------------------------------------------

    async def _cmd_stress_test(self, args: list[str]) -> str:
        """Run stress test scenarios against current portfolio."""
        try:
            from app.services.stress_testing import HISTORICAL_SCENARIOS, StressTestingService

            service = StressTestingService()

            # Get current positions
            positions = []
            if self._dashboard and self._dashboard._signals:
                # Use signal data as proxy for positions
                seen = set()
                for sig in self._dashboard._signals[:20]:
                    sym = sig.get("symbol", "")
                    if sym and sym not in seen:
                        seen.add(sym)
                        positions.append({
                            "symbol": sym,
                            "weight_pct": 100.0 / max(len(self._dashboard._signals), 1),
                        })

            if not positions:
                # Default positions from config
                from app.config import settings
                all_syms = settings.all_symbols
                for sym in all_syms:
                    positions.append({
                        "symbol": sym,
                        "weight_pct": 100.0 / max(len(all_syms), 1),
                    })

            from app.config import settings as _cfg
            portfolio_value = _cfg.initial_capital_usd

            if args:
                # Run specific scenario
                scenario_key = args[0].upper()
                if scenario_key not in HISTORICAL_SCENARIOS:
                    available = ", ".join(sorted(HISTORICAL_SCENARIOS.keys()))
                    return f"[red]Unknown scenario:[/red] {scenario_key}\nAvailable: {available}"

                report = service.run_historical_scenarios(positions, portfolio_value)
                # Find the requested one
                for sr in report.scenario_results:
                    if sr.scenario_key == scenario_key:
                        impact_abs = sr.portfolio_impact_abs
                        return (
                            f"[bold]Stress Test: {sr.scenario_name}[/bold]\n"
                            f"  Portfolio Impact:  "
                            f"{sr.portfolio_impact_pct:+.2%} "
                            f"(${impact_abs:+,.0f})\n"
                            f"  Stressed VaR:      "
                            f"{sr.var_under_stress:.4%}\n"
                            f"  Worst Asset:       "
                            f"{sr.worst_asset} "
                            f"({sr.worst_asset_impact:+.2%})\n"
                            f"  Best Asset:        "
                            f"{sr.best_asset} "
                            f"({sr.best_asset_impact:+.2%})\n"
                            f"  Stressed Corr:     "
                            f"{sr.stressed_correlation:.4f}\n"
                            f"  Est. Recovery:     "
                            f"{sr.recovery_estimate_days} days\n"
                            f"  Ref: "
                            f"{sr.details.get('reference', '')}"
                        )
                return f"[yellow]Scenario {scenario_key} not found in results.[/yellow]"
            else:
                # Run all scenarios
                report = service.run_historical_scenarios(positions, portfolio_value)
                worst_impact = report.worst_case_impact_pct
                lines = [
                    "[bold]Historical Stress Test Results[/bold]",
                    f"  Portfolio Value: ${portfolio_value:,.0f}",
                    f"  Risk Score:      "
                    f"{report.aggregate_risk_score:.0f}/100",
                    (
                        f"  Worst Case:      "
                        f"{report.worst_case_scenario} "
                        f"({worst_impact:+.2%})"
                    ),
                    "",
                ]
                for sr in sorted(
                    report.scenario_results,
                    key=lambda x: x.portfolio_impact_pct,
                ):
                    pct = sr.portfolio_impact_pct
                    if pct < -0.20:
                        color = "red"
                    elif pct < -0.10:
                        color = "yellow"
                    else:
                        color = "green"
                    lines.append(
                        f"  [{color}]"
                        f"{sr.scenario_key:25s} "
                        f"{pct:+8.2%}  "
                        f"${sr.portfolio_impact_abs:+12,.0f}"
                        f"[/]"
                    )
                return "\n".join(lines)

        except Exception as exc:
            return f"[red]Stress test failed:[/red] {exc}"

    # ------------------------------------------------------------------
    # Phase 7: Alerts
    # ------------------------------------------------------------------

    async def _cmd_alerts(self, args: list[str]) -> str:
        """Show recent alerts."""
        try:
            engine = getattr(self._orchestrator, "_alert_manager", None)
            if engine is None:
                return "[yellow]Alert manager not initialized yet.[/yellow]"

            severity = args[0].upper() if args else None
            alerts = engine.get_recent_alerts(limit=15, severity=severity)

            if not alerts:
                return "[dim]No alerts yet.[/dim]"

            lines = ["[bold]Recent Alerts:[/bold]"]
            severity_colors = {
                "INFO": "cyan",
                "WARNING": "yellow",
                "CRITICAL": "red",
                "EMERGENCY": "bold red",
            }
            for a in reversed(alerts):
                color = severity_colors.get(a["severity"], "white")
                ack = " [green]ACK[/]" if a["acknowledged"] else ""
                lines.append(
                    f"  [{color}]{a['severity']:10s}[/] {a['title']}{ack}"
                )
                lines.append(f"           [dim]{a['message']}[/dim]")
            return "\n".join(lines)
        except Exception as exc:
            return f"[yellow]Alerts unavailable: {exc}[/yellow]"

    async def _cmd_alert_rules(self, args: list[str]) -> str:
        """Show alert rules."""
        try:
            engine = getattr(self._orchestrator, "_alert_manager", None)
            if engine is None:
                return "[yellow]Alert manager not initialized yet.[/yellow]"

            rules = engine.get_rules()
            lines = ["[bold]Alert Rules:[/bold]"]
            for r in rules:
                status = "[green]ON[/]" if r["enabled"] else "[red]OFF[/]"
                channels = ", ".join(r["channels"])
                lines.append(
                    f"  {r['name']:25s} {status}  {r['severity']:10s}  -> {channels}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[yellow]Alert rules unavailable: {exc}[/yellow]"

    # ------------------------------------------------------------------
    # Phase 9: Reports
    # ------------------------------------------------------------------

    async def _cmd_report(self, args: list[str]) -> str:
        """Generate and display a portfolio report."""
        try:
            from app.services.report_generator import ReportGenerator

            generator = ReportGenerator()

            # Handle export subcommand
            if args and args[0].lower() == "export":
                if not hasattr(self, "_last_report") or self._last_report is None:
                    return "[yellow]No report generated yet. Run 'report' first.[/yellow]"
                fmt = args[1].lower() if len(args) > 1 else "csv"
                path = await generator.export_to_file(self._last_report, fmt=fmt)
                return f"[green]Report exported to:[/green] {path}"

            report_type = args[0].lower() if args else "daily"
            valid = {"daily", "weekly", "monthly"}
            if report_type not in valid:
                return f"[red]Invalid report type:[/red] {report_type}. Use: {', '.join(valid)}"

            console.print(f"[dim]Generating {report_type} report...[/dim]")
            report = await generator.generate(report_type=report_type)
            self._last_report = report

            return generator.to_rich_text(report)
        except Exception as exc:
            return f"[red]Report generation failed:[/red] {exc}"

    # ------------------------------------------------------------------
    # Phase 10: Health & Models
    # ------------------------------------------------------------------

    async def _cmd_health(self, args: list[str]) -> str:
        """Show system health dashboard."""
        try:
            from app.services.health_monitor import HealthMonitor

            monitor = getattr(
                self._orchestrator,
                "_health_monitor_svc",
                None,
            )
            if monitor is None:
                # Create a temporary one
                monitor = HealthMonitor(
                    bus=(
                        self._orchestrator.bus
                        if self._orchestrator else None
                    ),
                )

            snapshot = await monitor.get_snapshot(orchestrator=self._orchestrator)
            return monitor.to_rich_text(snapshot)
        except Exception as exc:
            return f"[yellow]Health check failed: {exc}[/yellow]"

    async def _cmd_models(self, args: list[str]) -> str:
        """Show registered ML models."""
        try:
            registry = getattr(
                self._orchestrator,
                "_model_registry",
                None,
            )
            if registry is None:
                return (
                    "[yellow]Model registry not initialized. "
                    "Models will be registered after "
                    "first strategy cycle.[/yellow]"
                )

            models = registry.get_all_models()
            if not models:
                return "[dim]No models registered yet.[/dim]"

            lines = ["[bold]Registered Models:[/bold]"]
            for m in models:
                st = m["status"]
                if st == "active":
                    status_color = "green"
                elif st == "deprecated":
                    status_color = "yellow"
                else:
                    status_color = "red"
                sharpe = m["metrics"].get(
                    "sharpe_ratio", "N/A",
                )
                lines.append(
                    f"  {m['model_id']:25s} "
                    f"[{status_color}]{st:12s}[/] "
                    f"type={m['model_type']:10s} "
                    f"sharpe={sharpe}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[yellow]Models unavailable: {exc}[/yellow]"

    async def _cmd_model_stats(self, args: list[str]) -> str:
        """Show Thompson Sampling strategy rotation stats."""
        try:
            selector = getattr(self._orchestrator, "_strategy_selector", None)
            if selector is None:
                return "[yellow]Strategy selector not initialized yet.[/yellow]"

            stats = selector.get_stats()
            if not stats:
                return "[dim]No strategy observations yet.[/dim]"

            lines = ["[bold]Thompson Sampling Strategy Stats:[/bold]"]
            lines.append(
                f"  {'Strategy':20s} {'N':>6s} "
                f"{'Post. Mean':>12s} {'Select %':>10s}"
            )
            for s in sorted(stats, key=lambda x: -x["posterior_mean"]):
                lines.append(
                    f"  {s['strategy']:20s} "
                    f"{s['n_observations']:6d} "
                    f"{s['posterior_mean']:12.6f} "
                    f"{s['selection_rate']:10.1%}"
                )

            rec = selector.get_recommendation()
            if rec["strategy"]:
                pm = rec['posterior_mean']
                lines.append(
                    f"\n  [green]Recommended: "
                    f"{rec['strategy']}[/green] "
                    f"(mean={pm:.6f})"
                )

            return "\n".join(lines)
        except Exception as exc:
            return f"[yellow]Model stats unavailable: {exc}[/yellow]"

    async def _cmd_dashboard(self, args: list[str]) -> str:
        """Show the full-screen live dashboard. Press Ctrl+C to return to REPL."""
        if not self._dashboard:
            return "[yellow]Dashboard not available.[/yellow]"

        console.print("[dim]Launching dashboard... Press Ctrl+C to return to REPL.[/dim]")
        try:
            await self._dashboard.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            self._dashboard.stop()
        return None

    async def _cmd_office(self, args: list[str]) -> str:
        """Show the pixel agent office with animated ASCII characters."""
        if not self._dashboard:
            return "[yellow]Dashboard not available.[/yellow]"

        viz = self._dashboard.pixel_agents

        # Register agents from orchestrator if not already registered
        if viz.get_agent_count() == 0 and self._orchestrator:
            statuses = self._orchestrator.get_agent_statuses()
            for agent_id, info in statuses.items():
                viz.update_state(agent_id, info["status"], department=info.get("department", ""))

        panel = viz.build_panel()
        console.print(panel)
        return None

    # ------------------------------------------------------------------
    # Order management (HUMAN_APPROVAL mode)
    # ------------------------------------------------------------------

    async def _cmd_orders(self, args: list[str]) -> str:
        """Show pending or all recent orders."""
        from sqlalchemy import text

        show_all = args and args[0].lower() == "all"

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                if show_all:
                    result = await session.execute(text("""
                        SELECT id, symbol, side, quantity, status, broker,
                               signal_id, debate_id, created_at
                        FROM orders
                        ORDER BY created_at DESC
                        LIMIT 20
                    """))
                else:
                    result = await session.execute(text("""
                        SELECT id, symbol, side, quantity, status, broker,
                               signal_id, debate_id, created_at
                        FROM orders
                        WHERE status = 'PENDING'
                        ORDER BY created_at ASC
                    """))
                rows = result.fetchall()

            if not rows:
                label = "orders" if show_all else "pending orders"
                return f"[dim]No {label}.[/dim]"

            label = "All Recent Orders" if show_all else "Pending Orders"
            lines = [
                f"[bold]{label}:[/bold]",
                f"  {'ID':8s}  {'Symbol':16s}  {'Side':5s}  {'Qty':>10s}  "
                f"{'Status':10s}  {'Broker':8s}  Age",
            ]
            from datetime import UTC, datetime
            now = datetime.now(UTC)
            for r in rows:
                created = r.created_at
                if created and hasattr(created, "replace"):
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=UTC)
                    age_s = int((now - created).total_seconds())
                    age = f"{age_s // 60}:{age_s % 60:02d}"
                else:
                    age = "?"
                status_color = (
                    "yellow" if r.status == "PENDING"
                    else "green" if r.status == "FILLED"
                    else "red" if r.status in ("REJECTED", "CANCELLED")
                    else "cyan"
                )
                lines.append(
                    f"  {str(r.id)[:8]:8s}  {r.symbol:16s}  "
                    f"{r.side:5s}  {r.quantity:>10.4f}  "
                    f"[{status_color}]{r.status:10s}[/]  {r.broker:8s}  {age}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]orders failed:[/red] {exc}"

    async def _cmd_approve(self, args: list[str]) -> str:
        """Approve a pending order and route it to the broker."""
        if not args:
            return "Usage: approve <order_id>"

        order_id = args[0]
        if not self._orchestrator:
            return "[yellow]Orchestrator not available.[/yellow]"

        from app.core.messaging import AgentMessage, MessageType
        await self._orchestrator.bus.publish(
            AgentMessage(
                sender_id="cio-terminal",
                channel="horizon.execution.order.approve",
                message_type=MessageType.ORDER_APPROVE,
                payload={
                    "order_id": order_id,
                    "approved_by": "CIO",
                },
            )
        )
        return f"[green]Approved order {order_id}.[/green] Routing to broker..."

    async def _cmd_reject(self, args: list[str]) -> str:
        """Reject a pending order."""
        if not args:
            return "Usage: reject <order_id>"

        order_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "Rejected by CIO via REPL"

        if not self._orchestrator:
            return "[yellow]Orchestrator not available.[/yellow]"

        from app.core.messaging import AgentMessage, MessageType
        await self._orchestrator.bus.publish(
            AgentMessage(
                sender_id="cio-terminal",
                channel="horizon.execution.order.reject",
                message_type=MessageType.ORDER_REJECT,
                payload={
                    "order_id": order_id,
                    "reason": reason,
                },
            )
        )
        return f"[yellow]Rejected order {order_id}.[/yellow]"

    # ------------------------------------------------------------------
    # Debate history
    # ------------------------------------------------------------------

    async def _cmd_debate_history(self, args: list[str]) -> str:
        """Show recent debate sessions and their linked orders."""
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT ds.id, ds.symbol, ds.proposed_action, ds.final_decision,
                           ds.consensus_score, o.id as order_id, o.status,
                           ds.created_at
                    FROM debate_sessions ds
                    LEFT JOIN orders o ON o.debate_id = ds.id
                    ORDER BY ds.created_at DESC
                    LIMIT 15
                """))
                rows = result.fetchall()

            if not rows:
                return "[dim]No debate history yet.[/dim]"

            lines = [
                "[bold]Debate History:[/bold]",
                f"  {'Session':8s}  {'Symbol':16s}  {'Decision':10s}  "
                f"{'Consensus':>9s}  {'Order':8s}  Status",
            ]
            for r in rows:
                decision = r.final_decision or "--"
                if decision == "APPROVED":
                    dec_color = "green"
                elif decision == "REJECTED":
                    dec_color = "red"
                else:
                    dec_color = "dim"

                order_id = str(r.order_id)[:8] if r.order_id else "—"
                order_status = r.status or "—"
                consensus = f"{r.consensus_score:.2f}" if r.consensus_score else "--"
                lines.append(
                    f"  {str(r.id)[:8]:8s}  {r.symbol:16s}  "
                    f"[{dec_color}]{decision:10s}[/]  {consensus:>9s}  "
                    f"{order_id:8s}  {order_status}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]debate history failed:[/red] {exc}"

    # ------------------------------------------------------------------
    # AI Department Routing
    # ------------------------------------------------------------------

    async def _cmd_ai_routing(self, args: list[str]) -> str:
        """Show or update per-department AI provider assignments."""
        import app.config as config_mod
        from app.llm.provider_registry import provider_registry

        dept_labels = {
            "front_office": "Front Office",
            "middle_office": "Middle Office",
            "back_office": "Back Office",
            "executive": "Executive",
        }
        dept_attr = {
            "front_office": "ai_front_office",
            "middle_office": "ai_middle_office",
            "back_office": "ai_back_office",
            "executive": "ai_executive",
        }
        valid_providers = {"claude", "openai", "gemini", "auto", "none"}

        # --- UPDATE mode: ai-routing <dept> <provider> ---
        if len(args) >= 2:
            dept = args[0].lower()
            provider = args[1].lower()

            if dept not in dept_attr:
                return (
                    f"[red]Unknown department:[/red] {dept}\n"
                    f"Valid: {', '.join(dept_attr)}"
                )
            if provider not in valid_providers:
                return (
                    f"[red]Unknown provider:[/red] {provider}\n"
                    f"Valid: {', '.join(sorted(valid_providers))}"
                )

            # Persist to .env
            try:
                from pathlib import Path
                env_path = Path(config_mod.settings.model_config.get("env_file", ".env"))
                if not env_path.is_absolute():
                    env_path = Path(__file__).resolve().parents[2] / ".env"
                env_key = f"AI_{dept.upper()}"
                lines: list[str] = []
                found = False
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith(f"{env_key}="):
                            lines.append(f"{env_key}={provider}")
                            found = True
                        else:
                            lines.append(line)
                if not found:
                    lines.append(f"{env_key}={provider}")
                env_path.write_text("\n".join(lines) + "\n")
            except Exception as exc:
                return f"[red]Failed to write .env:[/red] {exc}"

            # Hot-reload settings
            from app.config import Settings
            config_mod.settings = Settings()
            provider_registry.auto_register_from_settings()

            label = dept_labels[dept]
            return (
                f"[green]{label}[/green] AI routing set to [bold]{provider}[/bold]"
                " (saved to .env)."
            )

        # --- DISPLAY mode ---
        available = provider_registry.list_available()
        lines_out = [
            "[bold]AI Department Routing:[/bold]",
            f"  {'Department':20s}  {'Setting':12s}  {'Active Provider':16s}",
        ]
        for dept, label in dept_labels.items():
            attr = dept_attr[dept]
            setting_val = getattr(config_mod.settings, attr, "auto")
            active = provider_registry.get_provider_name_for_department(dept) or "—"
            if not active and setting_val != "none":
                active = "(none configured)"
            color = "green" if active and active != "(none configured)" else "dim"
            lines_out.append(
                f"  {label:20s}  {setting_val:12s}  [{color}]{active}[/]"
            )

        lines_out.append("")
        if available:
            lines_out.append(f"  Registered providers: [cyan]{', '.join(available)}[/cyan]")
        else:
            lines_out.append("  [dim]No LLM providers registered (add API keys via 'setup')[/dim]")

        lines_out.append(
            "\n  [dim]To change: ai-routing <dept> <provider>[/dim]\n"
            "  [dim]Example:   ai-routing front_office claude[/dim]"
        )
        return "\n".join(lines_out)

    # ------------------------------------------------------------------
    # Broker Connect & Go-Live
    # ------------------------------------------------------------------

    def _get_env_path(self) -> Path:
        """Resolve the .env file path."""
        import app.config as config_mod
        env_path = Path(config_mod.settings.model_config.get("env_file", ".env"))
        if not env_path.is_absolute():
            env_path = Path(__file__).resolve().parents[2] / ".env"
        return env_path

    def _write_env_keys(
        self,
        updates: dict[str, str] | None = None,
        removals: list[str] | None = None,
    ) -> None:
        """Merge key=value pairs into .env, removing specified keys."""
        env_path = self._get_env_path()
        lines: list[str] = []
        updated_keys: set[str] = set()
        removals_set = set(removals or [])

        if env_path.exists():
            for line in env_path.read_text().splitlines():
                key_part = line.split("=", 1)[0].strip()
                if key_part in removals_set:
                    continue  # skip removed keys
                if updates and key_part in updates:
                    lines.append(f"{key_part}={updates[key_part]}")
                    updated_keys.add(key_part)
                else:
                    lines.append(line)

        # Append new keys that weren't already in the file
        if updates:
            for k, v in updates.items():
                if k not in updated_keys:
                    lines.append(f"{k}={v}")

        env_path.write_text("\n".join(lines) + "\n")

    def _reload_settings(self) -> None:
        """Hot-reload settings from .env."""
        import app.config as config_mod
        from app.config import Settings
        config_mod.settings = Settings()
        try:
            from app.llm.provider_registry import provider_registry
            provider_registry.auto_register_from_settings()
        except Exception:
            pass

    async def _cmd_connect(self, args: list[str]) -> str:
        """Connect a broker or show connection status."""
        if not args:
            # Show which brokers are connected
            table = Table(title="Broker Connections")
            table.add_column("Broker", style="cyan")
            table.add_column("Credentials", style="white")
            table.add_column("Mode", style="white")

            alpaca_key = settings.alpaca_api_key
            zerodha_key = settings.zerodha_api_key

            table.add_row(
                "Alpaca",
                f"[green]configured (***{alpaca_key[-4:]})[/]" if alpaca_key
                else "[red]not set[/]",
                "Paper" if settings.alpaca_paper_mode else "Live",
            )
            table.add_row(
                "Zerodha",
                f"[green]configured (***{zerodha_key[-4:]})[/]" if zerodha_key
                else "[red]not set[/]",
                "Mock" if settings.zerodha_mock_mode else "Live",
            )
            console.print(table)
            return (
                "[dim]Use 'connect alpaca' or 'connect zerodha' "
                "to add broker credentials.[/dim]"
            )

        broker = args[0].lower()

        if broker == "alpaca":
            return await self._connect_alpaca()
        elif broker == "zerodha":
            return await self._connect_zerodha()
        else:
            return f"[red]Unknown broker:[/red] {broker}. Use: alpaca, zerodha"

    async def _connect_alpaca(self) -> str:
        """Interactive Alpaca connection flow."""
        import httpx

        console.print("\n[bold cyan]Connect Alpaca Broker[/bold cyan]\n")

        # 1. Paper or Live?
        try:
            mode_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: input("  Paper or Live? (paper/live) [paper]: "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Connection cancelled.[/yellow]"

        is_paper = mode_input.strip().lower() != "live"
        base_url = (
            "https://paper-api.alpaca.markets"
            if is_paper
            else "https://api.alpaca.markets"
        )

        # 2. Prompt credentials
        try:
            api_key = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  API Key: "),
            )
            api_secret = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  API Secret: "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Connection cancelled.[/yellow]"

        api_key = api_key.strip()
        api_secret = api_secret.strip()
        if not api_key or not api_secret:
            return "[red]API Key and Secret are required.[/red]"

        # 3. Verify credentials
        console.print("[dim]  Verifying credentials...[/dim]")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{base_url}/v2/account",
                    headers={
                        "APCA-API-KEY-ID": api_key,
                        "APCA-API-SECRET-KEY": api_secret,
                    },
                )
            if resp.status_code != 200:
                return (
                    f"[red]Alpaca verification failed "
                    f"(HTTP {resp.status_code}):[/red] {resp.text[:200]}"
                )

            acct = resp.json()
        except httpx.HTTPError as exc:
            return f"[red]Connection failed:[/red] {exc}"

        # 4. Show account info
        equity = float(acct.get("equity", 0))
        acct_num = acct.get("account_number", "?")
        console.print(
            Panel(
                f"  Account: {acct_num}\n"
                f"  Equity:  ${equity:,.2f}\n"
                f"  Status:  {acct.get('status', '?')}\n"
                f"  Mode:    {'Paper' if is_paper else 'LIVE'}",
                title="[green]Alpaca Connected[/green]",
                border_style="green",
            )
        )

        # 5. Save to .env and hot-reload
        self._write_env_keys({
            "ALPACA_API_KEY": api_key,
            "ALPACA_API_SECRET": api_secret,
            "ALPACA_BASE_URL": base_url,
            "ALPACA_PAPER_MODE": "true" if is_paper else "false",
        })
        self._reload_settings()

        return "[green]Alpaca credentials saved and loaded.[/green]"

    async def _connect_zerodha(self) -> str:
        """Interactive Zerodha connection flow."""
        import httpx

        console.print("\n[bold cyan]Connect Zerodha Broker[/bold cyan]\n")

        # 1. Prompt credentials
        try:
            api_key = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  API Key: "),
            )
            api_secret = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  API Secret: "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Connection cancelled.[/yellow]"

        api_key = api_key.strip()
        api_secret = api_secret.strip()
        if not api_key or not api_secret:
            return "[red]API Key and Secret are required.[/red]"

        # 2. Login URL
        login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
        console.print("\n  [bold]Open this URL in your browser:[/bold]")
        console.print(f"  [cyan]{login_url}[/cyan]\n")
        console.print(
            "  After login, you'll be redirected. "
            "Copy the 'request_token' from the URL."
        )

        try:
            access_token = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Access Token (or request_token): "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Connection cancelled.[/yellow]"

        access_token = access_token.strip()
        if not access_token:
            return "[red]Access token is required.[/red]"

        # 3. Verify via profile API
        console.print("[dim]  Verifying credentials...[/dim]")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.kite.trade/user/profile",
                    headers={
                        "X-Kite-Version": "3",
                        "Authorization": f"token {api_key}:{access_token}",
                    },
                )
            if resp.status_code != 200:
                return (
                    f"[red]Zerodha verification failed "
                    f"(HTTP {resp.status_code}):[/red] {resp.text[:200]}"
                )

            profile = resp.json().get("data", {})
        except httpx.HTTPError as exc:
            return f"[red]Connection failed:[/red] {exc}"

        # 4. Show profile
        console.print(
            Panel(
                f"  User:       {profile.get('user_name', '?')}\n"
                f"  User ID:    {profile.get('user_id', '?')}\n"
                f"  Email:      {profile.get('email', '?')}\n"
                f"  Exchanges:  {', '.join(profile.get('exchanges', []))}",
                title="[green]Zerodha Connected[/green]",
                border_style="green",
            )
        )

        # 5. Save to .env and hot-reload
        self._write_env_keys({
            "ZERODHA_API_KEY": api_key,
            "ZERODHA_API_SECRET": api_secret,
            "ZERODHA_ACCESS_TOKEN": access_token,
            "ZERODHA_MOCK_MODE": "false",
        })
        self._reload_settings()

        return "[green]Zerodha credentials saved and loaded.[/green]"

    async def _cmd_broker(self, args: list[str]) -> str:
        """Show broker connection health."""
        import httpx

        table = Table(title="Broker Status")
        table.add_column("Broker", style="cyan")
        table.add_column("Credentials", style="white")
        table.add_column("Connection", style="white")
        table.add_column("Mode", style="white")

        # Alpaca
        alpaca_key = settings.alpaca_api_key
        alpaca_creds = (
            f"[green]OK (***{alpaca_key[-4:]})[/]" if alpaca_key
            else "[red]not set[/]"
        )
        alpaca_conn = "[dim]—[/]"
        if alpaca_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{settings.alpaca_base_url.rstrip('/')}/v2/account",
                        headers={
                            "APCA-API-KEY-ID": settings.alpaca_api_key,
                            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
                        },
                    )
                alpaca_conn = (
                    "[green]reachable[/]" if resp.status_code == 200
                    else f"[red]HTTP {resp.status_code}[/]"
                )
            except Exception:
                alpaca_conn = "[red]unreachable[/]"

        table.add_row(
            "Alpaca",
            alpaca_creds,
            alpaca_conn,
            "Paper" if settings.alpaca_paper_mode else "Live",
        )

        # Zerodha
        zerodha_key = settings.zerodha_api_key
        zerodha_creds = (
            f"[green]OK (***{zerodha_key[-4:]})[/]" if zerodha_key
            else "[red]not set[/]"
        )
        zerodha_conn = "[dim]—[/]"
        if zerodha_key and settings.zerodha_access_token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.kite.trade/user/profile",
                        headers={
                            "X-Kite-Version": "3",
                            "Authorization": (
                                f"token {zerodha_key}:"
                                f"{settings.zerodha_access_token}"
                            ),
                        },
                    )
                zerodha_conn = (
                    "[green]reachable[/]" if resp.status_code == 200
                    else f"[red]HTTP {resp.status_code}[/]"
                )
            except Exception:
                zerodha_conn = "[red]unreachable[/]"

        table.add_row(
            "Zerodha",
            zerodha_creds,
            zerodha_conn,
            "Mock" if settings.zerodha_mock_mode else "Live",
        )

        console.print(table)
        return f"  System mode: [bold]{settings.system_mode.value}[/bold]"

    async def _cmd_broker_account(self, args: list[str]) -> str:
        """Show real broker account balances."""
        lines = ["[bold]Broker Account Info:[/bold]"]

        # Alpaca
        if settings.alpaca_api_key:
            try:
                from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
                broker = AlpacaBroker()
                acct = await broker.get_account()
                if acct:
                    lines.append("\n  [cyan]Alpaca[/cyan]")
                    lines.append(f"    Account:      {acct['account_number']}")
                    lines.append(f"    Equity:       ${acct['equity']:,.2f}")
                    lines.append(f"    Buying Power: ${acct['buying_power']:,.2f}")
                    lines.append(f"    Cash:         ${acct['cash']:,.2f}")
                    lines.append(f"    Status:       {acct['status']}")
                else:
                    lines.append("\n  [cyan]Alpaca[/cyan]: [red]failed to fetch[/]")
            except Exception as exc:
                lines.append(f"\n  [cyan]Alpaca[/cyan]: [red]{exc}[/]")
        else:
            lines.append("\n  [cyan]Alpaca[/cyan]: [dim]not configured[/dim]")

        # Zerodha
        if settings.zerodha_api_key and not settings.zerodha_mock_mode:
            try:
                from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
                broker = ZerodhaBroker()
                margins = await broker.get_margins()
                if margins:
                    lines.append("\n  [cyan]Zerodha[/cyan]")
                    lines.append(
                        f"    Available:  {margins['currency']} "
                        f"{margins['equity_available']:,.2f}"
                    )
                    lines.append(
                        f"    Used:       {margins['currency']} "
                        f"{margins['equity_used']:,.2f}"
                    )
                    lines.append(
                        f"    Net:        {margins['currency']} "
                        f"{margins['equity_net']:,.2f}"
                    )
                else:
                    lines.append("\n  [cyan]Zerodha[/cyan]: [red]failed to fetch[/]")
            except Exception as exc:
                lines.append(f"\n  [cyan]Zerodha[/cyan]: [red]{exc}[/]")
        else:
            lines.append(
                "\n  [cyan]Zerodha[/cyan]: "
                "[dim]not configured or in mock mode[/dim]"
            )

        # Paper mode NAV
        p = self._dashboard._portfolio if self._dashboard else {}
        nav = p.get("nav", 0.0)
        if nav > 0:
            lines.append("\n  [cyan]Paper Portfolio[/cyan]")
            lines.append(f"    NAV:  ${nav:,.2f}")

        return "\n".join(lines)

    async def _cmd_broker_positions(self, args: list[str]) -> str:
        """Show real broker positions."""
        table = Table(title="Broker Positions")
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", style="white")
        table.add_column("Qty", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Broker", style="dim")

        has_positions = False

        # Alpaca
        if settings.alpaca_api_key:
            try:
                from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
                broker = AlpacaBroker()
                positions = await broker.get_positions()
                for p in positions:
                    has_positions = True
                    pnl = (p["current_price"] - p["avg_entry"]) * p["qty"]
                    pnl_color = "green" if pnl >= 0 else "red"
                    table.add_row(
                        p["symbol"],
                        p["side"],
                        f"{p['qty']:.4f}",
                        f"${p['avg_entry']:.2f}",
                        f"${p['current_price']:.2f}",
                        f"[{pnl_color}]${pnl:+,.2f}[/]",
                        "Alpaca",
                    )
            except Exception as exc:
                console.print(f"[yellow]Alpaca positions error: {exc}[/yellow]")

        # Zerodha
        if settings.zerodha_api_key and not settings.zerodha_mock_mode:
            try:
                from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
                broker = ZerodhaBroker()
                positions = await broker.get_positions()
                for p in positions:
                    has_positions = True
                    pnl = p.get("pnl", 0)
                    pnl_color = "green" if pnl >= 0 else "red"
                    table.add_row(
                        p["symbol"],
                        "LONG" if p["quantity"] > 0 else "SHORT",
                        str(abs(p["quantity"])),
                        f"{p.get('avg_price', 0):.2f}",
                        "—",
                        f"[{pnl_color}]{pnl:+,.2f}[/]",
                        "Zerodha",
                    )
            except Exception as exc:
                console.print(f"[yellow]Zerodha positions error: {exc}[/yellow]")

        if not has_positions:
            return (
                "[dim]No broker positions. "
                "(Brokers may not be connected or have no positions.)[/dim]"
            )

        console.print(table)
        return ""

    async def _cmd_go_live(self, args: list[str]) -> str:
        """Guided safety checklist to switch to live trading."""
        from app.core.kv_store import get_kv_store

        console.print(
            Panel(
                "[bold red]LIVE TRADING[/bold red]\n\n"
                "This will switch the system to use real money.\n"
                "Trades will be executed on your connected broker account.",
                title="[bold red]WARNING[/bold red]",
                border_style="red",
            )
        )

        # Pre-flight checklist
        checks: list[tuple[str, bool, str]] = []

        # 1. Broker credentials configured?
        has_alpaca = bool(settings.alpaca_api_key)
        has_zerodha = bool(settings.zerodha_api_key and settings.zerodha_access_token)
        has_broker = has_alpaca or has_zerodha
        checks.append((
            "Broker credentials configured",
            has_broker,
            "Use 'connect alpaca' or 'connect zerodha'" if not has_broker else "",
        ))

        # 2. Broker API reachable?
        api_ok = False
        if has_alpaca:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{settings.alpaca_base_url.rstrip('/')}/v2/account",
                        headers={
                            "APCA-API-KEY-ID": settings.alpaca_api_key,
                            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
                        },
                    )
                if resp.status_code == 200:
                    api_ok = True
            except Exception:
                pass
        if has_zerodha and not api_ok:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.kite.trade/user/profile",
                        headers={
                            "X-Kite-Version": "3",
                            "Authorization": (
                                f"token {settings.zerodha_api_key}:"
                                f"{settings.zerodha_access_token}"
                            ),
                        },
                    )
                if resp.status_code == 200:
                    api_ok = True
            except Exception:
                pass
        checks.append((
            "Broker API reachable",
            api_ok,
            "Check API keys and network" if not api_ok else "",
        ))

        # 3. Account equity sufficient?
        equity_ok = False
        equity_msg = ""
        if has_alpaca and api_ok:
            try:
                from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
                acct = await AlpacaBroker().get_account()
                if acct and acct["equity"] >= 100:
                    equity_ok = True
                elif acct:
                    equity_msg = f"Equity ${acct['equity']:.2f} < $100 minimum"
            except Exception:
                pass
        if has_zerodha and api_ok and not equity_ok:
            try:
                from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
                margins = await ZerodhaBroker().get_margins()
                if margins and margins["equity_net"] >= 10000:
                    equity_ok = True
                elif margins:
                    equity_msg = f"Equity INR {margins['equity_net']:.2f} < INR 10,000"
            except Exception:
                pass
        checks.append((
            "Account equity sufficient",
            equity_ok,
            equity_msg or ("Add funds to your broker account" if not equity_ok else ""),
        ))

        # 4. Kill switch OFF?
        kv = get_kv_store()
        kill_switch = await kv.get("horizon:system:kill_switch")
        ks_off = kill_switch != "1"
        checks.append((
            "Kill switch OFF",
            ks_off,
            "Run 'kill-switch' to deactivate" if not ks_off else "",
        ))

        # 5. Risk parameters set?
        risk_ok = (
            settings.risk_max_drawdown_pct > 0
            and settings.risk_max_position_pct > 0
        )
        checks.append((
            "Risk parameters set",
            risk_ok,
            "Configure risk settings in .env" if not risk_ok else "",
        ))

        # Display checklist
        console.print("\n[bold]Pre-flight Checklist:[/bold]")
        critical_fail = False
        for label, passed, fix in checks:
            mark = "[green]\u2713[/]" if passed else "[red]\u2717[/]"
            console.print(f"  {mark} {label}")
            if not passed:
                console.print(f"      [dim]{fix}[/dim]")
                if label in ("Broker credentials configured", "Broker API reachable"):
                    critical_fail = True
        console.print()

        if critical_fail:
            return (
                "[red]Cannot go live: critical checks failed.[/red]\n"
                "Fix the issues above and try again."
            )

        # Choose mode
        console.print(
            "  [bold]Choose trading mode:[/bold]\n"
            "  1. HUMAN_APPROVAL — you approve each trade (recommended)\n"
            "  2. FULLY_AUTONOMOUS — AI trades without confirmation\n"
        )
        try:
            choice = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Choice (1/2) [1]: "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Go-live cancelled.[/yellow]"

        new_mode = (
            "FULLY_AUTONOMOUS" if choice.strip() == "2"
            else "HUMAN_APPROVAL"
        )

        # Final confirm
        console.print(
            f"\n  [bold red]You are about to enable {new_mode} "
            f"with real money.[/bold red]"
        )
        try:
            confirm = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Type GO LIVE to confirm: "),
            )
        except (EOFError, KeyboardInterrupt):
            return "[yellow]Go-live cancelled.[/yellow]"

        if confirm.strip() != "GO LIVE":
            return "[yellow]Go-live cancelled.[/yellow]"

        # Write mode
        self._write_env_keys({"SYSTEM_MODE": new_mode})
        self._reload_settings()
        settings.system_mode = SystemMode(new_mode)

        # Also set in KV for workers to pick up
        await kv.set("horizon:system:mode", new_mode)

        return (
            f"\n[bold green]LIVE TRADING ENABLED[/bold green]\n"
            f"  Mode: {new_mode}\n"
            f"  Broker: {'Alpaca' if has_alpaca else ''}"
            f"{'Zerodha' if has_zerodha else ''}\n\n"
            f"  [dim]Use 'kill-switch' for emergency stop.[/dim]"
        )

    async def _cmd_disconnect(self, args: list[str]) -> str:
        """Remove broker credentials and revert to paper mode."""
        if not args:
            return (
                "Usage: disconnect <alpaca|zerodha>\n"
                "  Removes broker credentials from .env and reverts to paper mode."
            )

        broker = args[0].lower()

        if broker == "alpaca":
            self._write_env_keys(
                updates={"ALPACA_PAPER_MODE": "true"},
                removals=["ALPACA_API_KEY", "ALPACA_API_SECRET"],
            )
        elif broker == "zerodha":
            self._write_env_keys(
                updates={"ZERODHA_MOCK_MODE": "true"},
                removals=[
                    "ZERODHA_API_KEY",
                    "ZERODHA_API_SECRET",
                    "ZERODHA_ACCESS_TOKEN",
                ],
            )
        else:
            return f"[red]Unknown broker:[/red] {broker}. Use: alpaca, zerodha"

        # If currently in live mode, revert to paper
        if settings.system_mode != SystemMode.PAPER_TRADING:
            self._write_env_keys({"SYSTEM_MODE": "PAPER_TRADING"})

        self._reload_settings()
        return f"[green]{broker.capitalize()} disconnected.[/green] Reverted to paper mode."

    async def _cmd_quit(self, args: list[str]) -> str:
        self._should_quit = True
        return "[bold red]Shutting down Horizon Capital...[/bold red]"
