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
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Force run the onboarding setup wizard",
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

    # Check for first-run onboarding
    if args.setup or args.command == "run":
        from app.tui.onboarding import needs_onboarding, run_onboarding

        if args.setup or needs_onboarding():
            try:
                run_onboarding()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Setup cancelled.[/yellow]")
                return
            if args.setup:
                return  # --setup only runs the wizard

    # Default: run the system
    try:
        asyncio.run(_run_system(headless=args.headless))
    except KeyboardInterrupt:
        console.print("\n[bold red]Horizon Capital stopped.[/bold red]")


async def _run_system(headless: bool = False) -> None:
    """Boot agents, optional TUI, and run until quit."""
    from app.core.runtime import get_bus, shutdown, startup
    from app.workers.agent_orchestrator import AgentOrchestrator

    # -- Startup --
    await startup(headless=headless)

    # Warn about insecure defaults
    from app.config import settings as _settings
    sec_warnings = _settings.validate_production_secrets()
    for w in sec_warnings:
        console.print(f"  [yellow]Security:[/yellow] {w}")
    if sec_warnings:
        console.print()

    # Register LLM providers from configured API keys
    from app.llm.provider_registry import provider_registry
    provider_registry.auto_register_from_settings()

    bus = get_bus()
    orchestrator = AgentOrchestrator(bus=bus)

    # -- Background workers (registered for supervision) --
    workers = await _start_workers(orchestrator)

    if headless:
        await _run_headless(orchestrator)
    else:
        await _run_with_tui(orchestrator)

    # -- Shutdown --
    console.print("[dim]Stopping agents...[/dim]")
    await orchestrator.stop_all()
    await _stop_workers(workers)
    await shutdown()
    console.print("[green]Horizon Capital shut down cleanly.[/green]")


async def _start_workers(orchestrator=None) -> list:
    """Start background workers as asyncio tasks and register for supervision."""
    import asyncio
    workers = []
    try:
        from app.workers.data_ingestion_worker import DataIngestionWorker
        diw = DataIngestionWorker()
        task = asyncio.create_task(diw.run(), name="data_ingestion_worker")
        workers.append((diw, task))
        if orchestrator:
            orchestrator.register_worker("data_ingestion_worker", diw, task)
    except Exception as exc:
        console.print(f"[yellow]data_ingestion_worker failed to start: {exc}[/yellow]")

    try:
        from app.workers.feature_computation_worker import FeatureComputationWorker
        fcw = FeatureComputationWorker()
        task = asyncio.create_task(fcw.run(), name="feature_computation_worker")
        workers.append((fcw, task))
        if orchestrator:
            orchestrator.register_worker("feature_computation_worker", fcw, task)
    except Exception as exc:
        console.print(f"[yellow]feature_computation_worker failed to start: {exc}[/yellow]")

    try:
        from app.workers.performance_worker import PerformanceWorker
        pw = PerformanceWorker()
        task = asyncio.create_task(pw.run(), name="performance_worker")
        workers.append((pw, task))
        if orchestrator:
            orchestrator.register_worker("performance_worker", pw, task)
    except Exception as exc:
        console.print(f"[yellow]performance_worker failed to start: {exc}[/yellow]")

    try:
        from app.core.runtime import get_bus
        from app.workers.macro_worker import MacroFactorWorker
        mw = MacroFactorWorker(bus=get_bus())
        task = asyncio.create_task(mw.run(), name="macro_worker")
        workers.append((mw, task))
        if orchestrator:
            orchestrator.register_worker("macro_worker", mw, task)
    except Exception as exc:
        console.print(f"[yellow]macro_worker failed to start: {exc}[/yellow]")

    try:
        from app.workers.position_worker import PositionMonitorWorker
        pmw = PositionMonitorWorker()
        task = asyncio.create_task(pmw.run(), name="position_monitor_worker")
        workers.append((pmw, task))
        if orchestrator:
            orchestrator.register_worker("position_monitor_worker", pmw, task)
    except Exception as exc:
        console.print(f"[yellow]position_monitor_worker failed to start: {exc}[/yellow]")

    return workers


async def _stop_workers(workers: list) -> None:
    """Gracefully stop all background workers."""
    for worker, task in workers:
        try:
            await worker.stop()
        except Exception:
            pass
        if not task.done():
            task.cancel()
            try:
                await task
            except (Exception, asyncio.CancelledError):
                pass


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
    from app.config import settings
    from app.core.messaging import AgentMessage, MessageType
    from app.tui.commands import CommandHandler
    from app.tui.dashboard import TerminalDashboard

    dashboard = TerminalDashboard()
    cmd_handler = CommandHandler(dashboard=dashboard, orchestrator=orchestrator)

    # Wire up bus listeners to feed the dashboard
    bus = orchestrator.bus

    async def _on_any_message(msg: AgentMessage) -> None:
        """Route bus messages to the dashboard."""
        if msg.message_type == MessageType.HEARTBEAT:
            payload = msg.payload.copy()
            agent_id = payload.get("agent_id", msg.sender_id)
            statuses = orchestrator.get_agent_statuses()
            if agent_id in statuses:
                payload["department"] = statuses[agent_id].get("department", "")
            dashboard.update_agent_status(agent_id, payload)
        elif msg.message_type == MessageType.AGENT_STATE_CHANGE:
            agent_id = msg.payload.get("agent_id", msg.sender_id)
            dashboard.update_agent_status(agent_id, msg.payload)
        elif msg.message_type == MessageType.SIGNAL:
            dashboard.add_signal(msg.payload)
        elif msg.message_type == MessageType.RISK_ALERT:
            risk_data = msg.payload.copy()
            try:
                from app.core.kv_store import get_kv_store
                kv = get_kv_store()
                perf = await kv.hgetall("horizon:performance:30d")
                if perf:
                    risk_data["sharpe_30d"] = float(
                        perf.get("sharpe_ratio", 0.0)
                    )
            except Exception:
                pass
            dashboard.update_risk(risk_data)
        elif msg.message_type == MessageType.PORTFOLIO_UPDATE:
            dashboard.update_portfolio(msg.payload)
        elif msg.message_type == MessageType.PRICE_UPDATE:
            dashboard.update_watchlist(msg.payload)
        elif msg.message_type == MessageType.ORDER_NEW:
            dashboard.add_pending_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_FILL:
            dashboard.complete_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_REJECT:
            order_id = msg.payload.get("order_id", "")
            dashboard.remove_order(order_id)
        elif msg.message_type == MessageType.SYSTEM:
            if msg.channel == "horizon.alerts.console":
                dashboard.add_alert(msg.payload)

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

    # Show log file location
    from app.core.logging import _LOG_FILE
    console.print(f"  Logs: [dim]{_LOG_FILE}[/dim]")
    console.print()

    # Show unconfigured services (once, not repeatedly)
    _unconfigured: list[str] = []
    if not settings.alpaca_api_key:
        _unconfigured.append("Alpaca")
    if not settings.zerodha_api_key:
        _unconfigured.append("Zerodha")
    if not settings.polygon_api_key:
        _unconfigured.append("Polygon")
    if not settings.newsapi_api_key:
        _unconfigured.append("NewsAPI")
    if not settings.reddit_client_id:
        _unconfigured.append("Reddit")
    if _unconfigured:
        console.print(f"  [dim]Not configured: {', '.join(_unconfigured)} (optional)[/dim]")
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

    # Startup summary banner
    from app.core.fast import is_rust_available

    rust_label = "[green]ACTIVE[/green]" if is_rust_available() else "[yellow]Python fallback[/yellow]"  # noqa: E501
    agent_statuses = orchestrator.get_agent_statuses()
    agent_count = len(agent_statuses)
    console.print()
    console.print("  [bold]Horizon Pro[/bold] v0.2.0")
    console.print(f"  Acceleration: {rust_label}")
    console.print(f"  Agents: {agent_count} running")
    console.print("  View: standard (change with 'view' command)")
    console.print()

    console.print("[dim]Type 'help' for commands, 'cio' for chat mode, 'quit' to exit.[/dim]\n")

    # Set up readline tab completion for REPL
    try:
        import readline

        _repl_completions = [
            "help", "status", "signals", "risk", "regime", "debate", "portfolio", "dashboard",
            "departments", "performance", "workers", "cio", "agents config",
            "mode", "kill-switch", "symbols", "data", "config", "setup",
            "interrupt", "override regime", "risk-tolerance", "toggle sentiment",
            "exposures", "attribution", "execution-mode",
            "backtest", "backtest results", "backtest list", "backtest compare",
            "stress-test", "stress-test GFC_2008", "stress-test COVID_2020",
            "stress-test DOT_COM", "stress-test FLASH_CRASH",
            "alerts", "alert rules",
            "report", "report daily", "report weekly", "report monthly",
            "report export csv", "report export json",
            "health", "models", "model stats", "office",
            "orders", "orders pending", "orders all",
            "approve", "reject",
            "debate history",
            "ai-routing",
            "ai-routing front_office", "ai-routing middle_office",
            "ai-routing back_office", "ai-routing executive",
            "connect", "connect alpaca", "connect zerodha",
            "broker", "broker status", "broker account", "broker positions",
            "go-live",
            "disconnect", "disconnect alpaca", "disconnect zerodha",
            "quit", "exit",
        ]

        def _completer(text: str, state: int) -> str | None:
            matches = [c for c in _repl_completions if c.startswith(text)]
            return matches[state] if state < len(matches) else None

        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(" \t\n")
    except ImportError:
        pass  # readline not available on all platforms

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
