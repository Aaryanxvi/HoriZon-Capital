"""Horizon Capital CLI entry point.

Usage:
    python -m app                  # Start the terminal agent (TUI + agents)
    python -m app --headless       # Start agents without TUI (log-only)
    python -m app status           # Show system status
    python -m app config           # Show current configuration
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from rich.console import Console

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="horizon-capital",
        description="Horizon Capital -- Autonomous AI Hedge Fund Terminal Agent",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status", "config", "version"],
        help="Command to execute (default: run)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run agents without the terminal UI (log output only)",
    )
    parser.add_argument(
        "--mode",
        choices=["PAPER_TRADING", "HUMAN_APPROVAL", "FULLY_AUTONOMOUS"],
        default=None,
        help="Override system mode",
    )
    parser.add_argument(
        "--storage",
        choices=["LOCAL", "POSTGRES"],
        default=None,
        help="Override storage backend",
    )
    parser.add_argument(
        "--cio-mode",
        choices=["HUMAN", "AI"],
        default=None,
        help="Override CIO mode (HUMAN=interactive, AI=autonomous)",
    )

    args = parser.parse_args()

    # Apply overrides before importing config-dependent modules
    if args.mode:
        import os
        os.environ["SYSTEM_MODE"] = args.mode
    if args.storage:
        import os
        os.environ["STORAGE_BACKEND"] = args.storage
    if args.cio_mode:
        import os
        os.environ["CIO_MODE"] = args.cio_mode

    if args.command == "version":
        console.print("[bold]Horizon Capital[/bold] v0.2.0")
        return

    if args.command == "config":
        _show_config()
        return

    if args.command == "status":
        console.print("[yellow]Status check requires a running instance.[/yellow]")
        return

    # Default: run the system
    try:
        asyncio.run(_run_system(headless=args.headless))
    except KeyboardInterrupt:
        console.print("\n[bold red]Horizon Capital stopped.[/bold red]")


async def _run_system(headless: bool = False) -> None:
    """Boot agents, optional TUI, and run until quit."""
    from app.core.runtime import get_bus, startup, shutdown
    from app.workers.agent_orchestrator import AgentOrchestrator

    # -- Startup --
    await startup()

    # Register LLM providers from configured API keys
    from app.llm.provider_registry import provider_registry
    provider_registry.auto_register_from_settings()

    bus = get_bus()
    orchestrator = AgentOrchestrator(bus=bus)

    if headless:
        await _run_headless(orchestrator)
    else:
        await _run_with_tui(orchestrator)

    # -- Shutdown --
    console.print("[dim]Stopping agents...[/dim]")
    await orchestrator.stop_all()
    await shutdown()
    console.print("[green]Horizon Capital shut down cleanly.[/green]")


async def _run_headless(orchestrator) -> None:
    """Run agents in headless mode (log output only)."""
    from app.core.logging import get_logger
    logger = get_logger("main")

    console.print("[bold cyan]Horizon Capital[/bold cyan] starting in headless mode...")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    await orchestrator.start_all()
    logger.info("system_running_headless")

    # Wait for interrupt
    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass


async def _run_with_tui(orchestrator) -> None:
    """Run agents with the Rich terminal dashboard + command REPL."""
    from app.tui.dashboard import TerminalDashboard
    from app.tui.commands import CommandHandler
    from app.core.messaging import AgentMessage, MessageType
    from app.config import settings

    dashboard = TerminalDashboard()
    cmd_handler = CommandHandler(dashboard=dashboard, orchestrator=orchestrator)

    # Wire up bus listeners to feed the dashboard
    bus = orchestrator.bus

    async def _on_any_message(msg: AgentMessage) -> None:
        """Route bus messages to the dashboard."""
        if msg.message_type == MessageType.HEARTBEAT:
            payload = msg.payload.copy()
            # Include department info from orchestrator
            agent_id = payload.get("agent_id", msg.sender_id)
            statuses = orchestrator.get_agent_statuses()
            if agent_id in statuses:
                payload["department"] = statuses[agent_id].get("department", "")
            dashboard.update_agent_status(agent_id, payload)
        elif msg.message_type == MessageType.SIGNAL:
            dashboard.add_signal(msg.payload)
        elif msg.message_type == MessageType.REGIME_UPDATE:
            scope = msg.payload.get("market_scope", "UNKNOWN")
            dashboard.update_regime(scope, msg.payload)
        elif msg.message_type == MessageType.RISK_ALERT:
            dashboard.update_risk(msg.payload)
        elif msg.message_type in (
            MessageType.DEBATE_CONCLUSION,
            MessageType.DEBATE_START,
        ):
            dashboard.add_debate(msg.payload)

    await bus.subscribe("horizon.*", _on_any_message)

    # Print startup banner
    console.print()
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print("[bold cyan]  HORIZON CAPITAL  --  Autonomous AI Hedge Fund[/bold cyan]")
    console.print("[bold cyan]  Terminal Agent v0.2.0[/bold cyan]")
    console.print("[bold cyan]" + "=" * 60 + "[/bold cyan]")
    console.print()
    console.print(f"  CIO Mode: [bold]{settings.cio_mode.value}[/bold]")

    # Show available LLM providers
    from app.llm.provider_registry import provider_registry
    available = provider_registry.list_available()
    if available:
        console.print(f"  LLM Providers: [green]{', '.join(available)}[/green]")
    else:
        console.print("  LLM Providers: [yellow]none configured[/yellow]")
    console.print()

    # Start agents
    console.print("[dim]Starting departments...[/dim]")
    await orchestrator.start_all()

    # Show department summary
    depts = orchestrator.get_department_statuses()
    for d in depts:
        console.print(
            f"  [green]{d['display_name']}[/green]: "
            f"{d['agents_running']}/{d['agents_total']} agents"
        )

    console.print()
    console.print("[green]All departments started.[/green]")
    console.print("[dim]Type 'help' for commands, 'cio' for chat mode, 'quit' to exit.[/dim]\n")

    # REPL loop
    while not cmd_handler.should_quit:
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("horizon> ")
            )
            result = await cmd_handler.handle(raw)
            if result:
                console.print(result)
                console.print()
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("\n[dim]Use 'quit' to exit cleanly.[/dim]")


def _show_config() -> None:
    """Print current configuration."""
    from app.config import settings
    from app.llm.provider_registry import provider_registry

    provider_registry.auto_register_from_settings()
    available_llms = provider_registry.list_available()

    console.print("[bold cyan]Horizon Capital Configuration[/bold cyan]\n")
    console.print(f"  System Mode:     {settings.system_mode.value}")
    console.print(f"  CIO Mode:        {settings.cio_mode.value}")
    console.print(f"  Storage Backend: {settings.storage_backend.value}")
    console.print(f"  Environment:     {settings.app_env}")
    console.print(f"  Debug:           {settings.app_debug}")
    console.print()
    console.print("[bold]Departments:[/bold]")
    console.print("  Front Office   (Investment & Revenue)")
    console.print("  Middle Office  (Risk & Control)")
    console.print("  Back Office    (Support & Finance)")
    console.print("  Executive      (Management)")
    console.print()
    console.print("[bold]Risk Parameters:[/bold]")
    console.print(f"  Max Drawdown:    {settings.risk_max_drawdown_pct}%")
    console.print(f"  Max Position:    {settings.risk_max_position_pct}%")
    console.print(f"  Max Leverage:    {settings.risk_max_leverage}x")
    console.print(f"  VaR Limit:       {settings.risk_var_limit_pct}%")
    console.print()
    console.print("[bold]Trading Universe:[/bold]")
    console.print(f"  India:  {settings.india_symbols}")
    console.print(f"  US:     {settings.us_symbols}")
    console.print(f"  Crypto: {settings.crypto_symbols}")
    console.print()
    console.print("[bold]LLM Providers:[/bold]")
    if available_llms:
        for p in available_llms:
            console.print(f"  {p:12s}: [green]configured[/green]")
    else:
        console.print("  [yellow]No LLM providers configured[/yellow]")
    console.print()
    console.print("[bold]API Keys:[/bold]")
    _show_key("Anthropic", settings.anthropic_api_key)
    _show_key("OpenAI", settings.openai_api_key)
    _show_key("Google", settings.google_api_key)
    _show_key("Alpaca", settings.alpaca_api_key)
    _show_key("Zerodha", settings.zerodha_api_key)
    _show_key("Polygon", settings.polygon_api_key)
    _show_key("NewsAPI", settings.newsapi_api_key)


def _show_key(name: str, value: str) -> None:
    if value:
        console.print(f"  {name:12s}: [green]configured[/green] (***{value[-4:]})")
    else:
        console.print(f"  {name:12s}: [red]not set[/red]")


if __name__ == "__main__":
    main()
