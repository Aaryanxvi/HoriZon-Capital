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
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the local SQLite DB and KV store before starting",
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

    # --reset: wipe local state before doing anything else. Lets the user
    # recover from stale positions / cash / NAV left over from prior runs
    # where configuration (universe, capital) differed.
    if args.reset:
        _wipe_local_state()

    # Run onboarding on every startup. The wizard's update mode handles the
    # case where .env already exists — it lets the user keep current values.
    if args.setup or args.command == "run":
        from app.tui.onboarding import run_onboarding

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
        from app.workers.performance_worker import PerformanceWorker
        pw = PerformanceWorker()
        task = asyncio.create_task(pw.run(), name="performance_worker")
        workers.append((pw, task))
        if orchestrator:
            orchestrator.register_worker("performance_worker", pw, task)
    except Exception as exc:
        console.print(f"[yellow]performance_worker failed to start: {exc}[/yellow]")

    try:
        from app.agents.front_office.research.sentiment_agent import SentimentAgent
        from app.config import settings as _cfg
        from app.core.runtime import get_bus as _get_bus
        sa = SentimentAgent(
            bus=_get_bus(),
            symbols=_cfg.all_symbols,
            api_key=getattr(_cfg, "newsapi_api_key", ""),
        )
        task = asyncio.create_task(sa.start(), name="sentiment_agent")
        workers.append((sa, task))
    except Exception as exc:
        console.print(f"[yellow]sentiment_agent failed to start: {exc}[/yellow]")

    try:
        from app.workers.position_worker import PositionMonitorWorker
        pmw = PositionMonitorWorker()
        task = asyncio.create_task(pmw.run(), name="position_monitor_worker")
        workers.append((pmw, task))
        if orchestrator:
            orchestrator.register_worker("position_monitor_worker", pmw, task)
    except Exception as exc:
        console.print(f"[yellow]position_monitor_worker failed to start: {exc}[/yellow]")

    try:
        from app.config import settings as _cfg
        if _cfg.telegram_bot_token and _cfg.telegram_chat_id:
            from app.services.telegram_approvals import TelegramApprovalWorker
            taw = TelegramApprovalWorker(orchestrator=orchestrator)
            task = asyncio.create_task(taw.run(), name="telegram-approvals")
            workers.append((taw, task))
            if orchestrator:
                orchestrator.register_worker("telegram-approvals", taw, task)
    except Exception as exc:
        console.print(f"[yellow]telegram-approvals failed to start: {exc}[/yellow]")

    try:
        from app.workers.eod_report_worker import EODReportWorker
        eod = EODReportWorker(orchestrator=orchestrator)
        task = asyncio.create_task(eod.run(), name="eod-report-worker")
        workers.append((eod, task))
        if orchestrator:
            orchestrator.register_worker("eod-report-worker", eod, task)
    except Exception as exc:
        console.print(f"[yellow]eod-report-worker failed to start: {exc}[/yellow]")

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
    from app.core.logging import get_logger
    from app.core.messaging import AgentMessage, MessageType
    from app.tui.commands import CommandHandler
    from app.tui.dashboard import TerminalDashboard

    logger = get_logger("main.tui")

    dashboard = TerminalDashboard()
    cmd_handler = CommandHandler(dashboard=dashboard, orchestrator=orchestrator)

    # CIO agent is wired AFTER ``orchestrator.start_all()`` below — at this
    # point none of the agents are registered yet.
    from app.config import CIOMode

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
        elif msg.message_type == MessageType.AGENT_STATUS:
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
        elif msg.message_type == MessageType.TICK:
            dashboard.update_watchlist(msg.payload)
        elif msg.message_type == MessageType.ORDER_NEW:
            # Show every outstanding order (not just human-approval ones).
            # `complete_order` removes it from the pending list when the
            # ORDER_FILL arrives; for paper fills that's milliseconds later,
            # so the user still sees "in flight" on the dashboard.
            if msg.payload.get("order_id"):
                dashboard.add_pending_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_FILL:
            dashboard.complete_order(msg.payload)
        elif msg.message_type == MessageType.ORDER_CANCEL:
            order_id = msg.payload.get("order_id", "")
            dashboard.remove_order(order_id)
        elif msg.message_type == MessageType.SENTIMENT_UPDATE:
            dashboard.update_sentiment(msg.payload)
        elif msg.message_type == MessageType.CIO_ADVISORY:
            dashboard.update_cio_advisory(msg.payload)
        elif msg.message_type == MessageType.HEALTH_CHECK:
            if msg.channel == "horizon.alerts.console":
                dashboard.add_alert(msg.payload)

    await bus.subscribe("horizon.*", _on_any_message)

    # Load initial state from DB/KV so dashboard isn't empty on start
    async def _load_initial_dashboard_state() -> None:
        try:
            from sqlalchemy import text as sa_text

            from app.core.kv_store import get_kv_store
            from app.core.runtime import get_session_factory

            kv = get_kv_store()

            # Cash & NAV — always publish, even if 0, so the dashboard shows
            # the seeded balance immediately instead of waiting 60s for the
            # first portfolio snapshot.
            cash_usd = float(await kv.get("horizon:cash:usd") or 0)
            cash_inr = float(await kv.get("horizon:cash:inr") or 0)
            nav = float(await kv.get("horizon:portfolio:nav") or 0)
            # Use the best estimate available: persisted NAV, else seeded cash.
            total = nav if nav > 0 else (cash_usd + cash_inr / 83.0)
            dashboard.update_portfolio({
                "total_value": total,
                "cash_usd": cash_usd,
                "cash_inr": cash_inr,
                "positions": [],
            })

            # Risk metrics
            risk = await kv.hgetall("horizon:risk:latest")
            if risk:
                perf = await kv.hgetall("horizon:performance:30d")
                dashboard.update_risk({
                    "var_95": float(risk.get("var_1d_95", 0)),
                    "var_99": float(risk.get("var_1d_99", 0)),
                    "max_drawdown": float(risk.get("max_drawdown", 0)) * 100,
                    "current_drawdown": float(
                        risk.get("current_drawdown", 0)
                    ) * 100,
                    "kill_switch_active": risk.get(
                        "kill_switch_active"
                    ) == "1",
                    "sharpe_30d": float(
                        perf.get("sharpe_ratio", 0)
                    ) if perf else 0.0,
                })

            # Recent positions
            async with get_session_factory()() as session:
                result = await session.execute(sa_text("""
                    SELECT symbol, exchange, side, quantity,
                           avg_entry_price, current_price,
                           unrealized_pnl, currency
                    FROM positions WHERE quantity != 0
                """))
                pos_rows = result.fetchall()
                if pos_rows:
                    positions = [
                        {
                            "symbol": r.symbol,
                            "exchange": r.exchange,
                            "side": r.side,
                            "qty": r.quantity,
                            "current_price": r.current_price,
                            "unrealized_pnl": r.unrealized_pnl,
                            "currency": r.currency,
                        }
                        for r in pos_rows
                    ]
                    dashboard._portfolio["positions"] = positions

                # Recent trades
                result = await session.execute(sa_text("""
                    SELECT f.order_id, o.symbol, o.side,
                           f.filled_qty, f.fill_price,
                           f.slippage, f.created_at
                    FROM fills f
                    JOIN orders o ON f.order_id = o.id
                    ORDER BY f.created_at DESC
                    LIMIT 20
                """))
                fill_rows = result.fetchall()
                for r in fill_rows:
                    dashboard._trade_history.append({
                        "order_id": r.order_id,
                        "symbol": r.symbol,
                        "side": r.side,
                        "filled_qty": r.filled_qty,
                        "fill_price": r.fill_price,
                        "slippage": r.slippage,
                        "status": "FILLED",
                        "timestamp": str(r.created_at),
                    })
        except Exception as exc:
            logger.warning("initial_dashboard_load_error", error=str(exc))

    await _load_initial_dashboard_state()

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

    # Now that agents are registered and running, wire the CIO into the REPL
    # so `cio`, `cio why`, `cio confirm halt` all work.
    if settings.cio_mode == CIOMode.AI:
        try:
            cio_agent = orchestrator.get_agent("cio-agent-1")
            if cio_agent:
                cmd_handler.set_cio_agent(cio_agent)
                logger.info("cio_agent_wired_to_repl")
            else:
                console.print(
                    "[yellow]CIO agent not found in orchestrator.[/yellow]"
                )
        except Exception as exc:
            console.print(f"[yellow]CIO agent wiring failed: {exc}[/yellow]")

    # Show department summary
    depts = orchestrator.get_department_statuses()
    for d in depts:
        console.print(
            f"  [green]{d['display_name']}[/green]: "
            f"{d['agents_running']}/{d['agents_total']} agents"
        )

    console.print()
    console.print("[green]All departments started.[/green]")
    console.print(
        "[dim]Type 'dashboard' for live view, 'help' for commands, 'quit' to exit.[/dim]\n"
    )

    # Set up readline tab completion for REPL
    try:
        import readline

        _repl_completions = [
            "help",
            "dashboard",
            "status",
            "brief",
            "buy",
            "sell",
            "watchlist",
            "watchlist add",
            "watchlist remove",
            "portfolio",
            "positions",
            "orders",
            "orders all",
            "signals",
            "trades",
            "pnl",
            "backtest",
            "backtest results",
            "risk",
            "sentiment",
            "debate",
            "agents",
            "health",
            "performance",
            "performance 1d",
            "performance 7d",
            "performance 30d",
            "performance 90d",
            "performance ytd",
            "performance all",
            "report",
            "config",
            "pending",
            "approve",
            "reject",
            "cio",
            "cio why",
            "cio confirm halt",
            "settings",
            "quit",
            "exit",
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
            if result == "__OPEN_SETTINGS__":
                from app.tui.settings_panel import SettingsPanel
                panel = SettingsPanel(
                    registry=provider_registry, env_path=".env"
                )
                panel.run(console)
            elif result:
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


def _wipe_local_state() -> None:
    """Delete the local SQLite DB so the system starts with a clean slate."""
    import os
    from pathlib import Path

    data_dir = Path(os.getenv("HORIZON_DATA_DIR", Path.home() / ".horizon-capital"))
    wiped = []
    for pattern in ("horizon.db", "horizon.db-shm", "horizon.db-wal"):
        f = data_dir / pattern
        if f.exists():
            try:
                f.unlink()
                wiped.append(f.name)
            except OSError as exc:
                console.print(f"[red]Could not delete {f}: {exc}[/red]")
    if wiped:
        console.print(f"[yellow]Wiped local state: {', '.join(wiped)}[/yellow]")
    else:
        console.print("[dim]No local state to wipe.[/dim]")


def _show_key(name: str, value: str) -> None:
    if value:
        console.print(f"  {name:12s}: [green]configured[/green] (***{value[-4:]})")
    else:
        console.print(f"  {name:12s}: [red]not set[/red]")


if __name__ == "__main__":
    main()
