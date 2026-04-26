"""Interactive terminal command handler for Horizon Capital."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console

from app.config import settings

console = Console()

HELP_TEXT = """
[bold cyan]Horizon Capital Terminal Commands[/bold cyan]

  [green]help[/]                Show this help
  [green]status[/]              Show all agent statuses
  [green]portfolio[/]           Show current portfolio (NAV, cash, positions)
  [green]positions[/]           Show open positions from the database
  [green]orders[/] [all]        Show recent orders (default: last 20)
  [green]signals[/]             Show recent trading signals
  [green]trades[/] [page N|all]  Show filled trades (newest first, paginated)
  [green]pnl[/]                 Show realized & unrealized P&L summary
  [green]backtest[/] <SYMBOL> [--days N] [--strategy NAME]
                          Run a backtest using Alpaca historical data
                          Strategies: momentum, mean_reversion, volatility, crisis
                          Example: backtest AAPL --days 252 --strategy momentum
  [green]risk[/] [reset]       Show risk metrics. `risk reset` clears kill-switch halt.
  [green]sentiment[/]           Show latest sentiment data
  [green]debate[/]              Show recent debate summaries
  [green]agents[/]              Show agent configuration
  [green]health[/]              Show system health
  [green]performance[/] [period] Show performance metrics (1d/7d/30d/90d/YTD/ALL)
  [green]config[/]              Show current configuration

  [bold yellow]Order Approval (HUMAN_APPROVAL mode):[/bold yellow]
  [green]pending[/]             Show orders awaiting CIO approval
  [green]approve[/] <id>        Approve a pending order
  [green]reject[/] <id>         Reject a pending order

  [green]settings[/]            Open interactive settings editor (keys, AI allocation, debate roles)
  [green]model[/]               Per-agent LLM model selection (cheap/mid/premium)
                          Usage: model | model list [provider] | model agents
                                 model set <agent_id> <provider> <model_id>
                                 model clear <agent_id>

  [bold yellow]CIO Commands:[/bold yellow]
  [green]cio[/]                 Show latest CIO advisory
  [green]cio why[/]             Show reasoning behind the most recent CIO override
  [green]cio confirm halt[/]    Confirm a CIO-recommended HALT in FULLY_AUTONOMOUS mode

  [bold yellow]Watchlist:[/bold yellow]
  [green]watchlist[/]            Show current watchlist symbols
  [green]watchlist add[/] <SYM>  Add a US symbol (e.g. NVDA.NASDAQ, JPM.NYSE)
  [green]watchlist remove[/] <SYM>  Remove a symbol from watchlist

  [bold yellow]Manual Trading:[/bold yellow]
  [green]buy[/] <SYMBOL> [qty]   Place a manual BUY order (default qty: auto-size)
  [green]sell[/] <SYMBOL> [qty]  Place a manual SELL order (default: sell entire position)

  [green]dashboard[/]           Open live fullscreen dashboard (press q to exit)

  [green]quit[/] / [green]exit[/]        Shutdown Horizon Capital
"""


class CommandHandler:
    """Processes terminal commands and returns formatted output."""

    def __init__(self, dashboard=None, orchestrator=None) -> None:
        self._dashboard = dashboard
        self._orchestrator = orchestrator
        self._should_quit = False
        self._cio_chat = None
        self._cio_agent = None
        self._last_backtest_result: dict | None = None

    @property
    def should_quit(self) -> bool:
        return self._should_quit

    async def handle(self, raw_input: str) -> str | None:
        """Parse and execute a command."""
        parts = raw_input.strip().split()
        if not parts:
            return None

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "backtest" and args and args[0].lower() == "results":
            return await self._cmd_backtest_results([])

        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "portfolio": self._cmd_portfolio,
            "positions": self._cmd_positions,
            "orders": self._cmd_orders,
            "signals": self._cmd_signals,
            "backtest": self._cmd_backtest,
            "risk": self._cmd_risk,
            "sentiment": self._cmd_sentiment,
            "debate": self._cmd_debate,
            "agents": self._cmd_agents,
            "health": self._cmd_health,
            "performance": self._cmd_performance,
            "config": self._cmd_config,
            "approve": self._cmd_approve,
            "reject": self._cmd_reject,
            "pending": self._cmd_pending,
            "trades": self._cmd_trades,
            "pnl": self._cmd_pnl,
            "cio": self._cmd_cio,
            "watchlist": self._cmd_watchlist,
            "buy": self._cmd_buy,
            "sell": self._cmd_sell,
            "strategy": self._cmd_strategy,
            "dashboard": self._cmd_dashboard,
            "settings": self._cmd_settings,
            "model": self._cmd_model,
            "models": self._cmd_model,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler is None:
            return f"[red]Unknown command:[/red] {cmd}. Type 'help' for available commands."

        return await handler(args)

    async def _cmd_strategy(self, args: list[str]) -> str:
        """Show sleeve-system diagnostics.

        `strategy status` — sleeves, cadences, last refresh, last targets.
        `strategy tick`   — force one poll cycle NOW (ignores market-hours).
        """
        sub = args[0].lower() if args else "status"

        if self._orchestrator is None:
            return "[red]Orchestrator not available.[/red]"
        agent = None
        for slot in self._orchestrator._slots.values():
            if slot.agent.agent_type == "strategy":
                agent = slot.agent
                break
        if agent is None:
            return "[red]Strategy agent not running.[/red]"

        if sub == "tick":
            try:
                await agent._tick(force=True)
                return "[green]Forced strategy tick complete. Check `signals`.[/green]"
            except Exception as exc:
                return f"[red]Forced tick failed: {exc}[/red]"

        # status
        from app.agents.front_office.strategy.strategy_agent import (
            _is_us_market_open,
        )
        lines = [
            "[bold]Strategy Agent — Sleeve System[/bold]",
            f"  Market open now:       {_is_us_market_open()}",
            f"  Symbols tracked:       {len(agent._symbols)}",
            f"  Last poll counter:     {agent._bar_count}",
            "",
            "[bold]Sleeves:[/bold]",
        ]
        for sleeve in agent._sleeves:
            last_refresh = agent._sleeve_last_refresh.get(sleeve.name)
            cached = agent._sleeve_cache.get(sleeve.name, [])
            lines.append(
                f"  {sleeve.name:14s} "
                f"weight={sleeve.target_weight:>5.0%}  "
                f"cadence={sleeve.rebalance_days:>2}d  "
                f"last={last_refresh}  "
                f"signals={len(cached)}"
            )
        if agent._last_emitted_weight:
            lines.append("")
            lines.append("[bold]Last-emitted target weights:[/bold]")
            for sym, w in sorted(agent._last_emitted_weight.items()):
                lines.append(f"  {sym:14s}  {w:.2%}")
        else:
            lines.append("")
            lines.append(
                "[dim]No signals emitted yet. Sleeves fire only during US "
                "market hours — run `strategy tick` to force one cycle.[/dim]"
            )
        return "\n".join(lines)

    async def _cmd_dashboard(self, args: list[str]) -> str | None:
        """Launch the live fullscreen dashboard."""
        if not self._dashboard:
            return "[red]Dashboard not available.[/red]"
        console.print("[dim]Opening live dashboard... press 'q' to return to REPL.[/dim]")
        await self._dashboard.run_interactive()
        return None

    async def _cmd_help(self, args: list[str]) -> str:
        return HELP_TEXT

    async def _cmd_status(self, args: list[str]) -> str:
        if self._orchestrator:
            statuses = self._orchestrator.get_agent_statuses()
            if not statuses:
                return "[yellow]No agents registered yet.[/yellow]"

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

            for dept, agents in by_dept.items():
                if agents:
                    lines.append(f"\n  [dim]{dept}[/]")
                    for aid, info in agents:
                        status = info.get("status", "UNKNOWN")
                        color = "green" if status == "RUNNING" else "red"
                        lines.append(f"    [{color}]{aid:25s} {status}[/]")

            return "\n".join(lines)
        return "[yellow]Orchestrator not available.[/yellow]"

    async def _cmd_portfolio(self, args: list[str]) -> str:
        p = self._dashboard._portfolio if self._dashboard else {}
        nav = p.get("nav", 0.0)
        cash = p.get("cash", 0.0)

        # Fallback: read directly from KV if dashboard hasn't received update yet
        if nav == 0.0 and cash == 0.0:
            try:
                from app.core.kv_store import get_kv_store
                kv = get_kv_store()
                cash_str = await kv.get("horizon:cash:usd")
                nav_str = await kv.get("horizon:portfolio:nav")
                if cash_str:
                    cash = float(cash_str)
                if nav_str:
                    nav = float(nav_str)
                if nav == 0.0:
                    nav = cash  # Before first snapshot, NAV ≈ cash
            except Exception:
                pass

        positions = p.get("positions", 0)
        if isinstance(positions, list):
            positions = len(positions)

        return (
            f"[bold]Portfolio:[/bold]\n"
            f"  NAV:       ${nav:,.2f}\n"
            f"  Cash:      ${cash:,.2f}\n"
            f"  Positions: {positions}"
        )

    async def _cmd_positions(self, args: list[str]) -> str:
        """Show open positions from the database."""
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT symbol, exchange, side, quantity, avg_entry_price,
                           current_price, unrealized_pnl
                    FROM positions
                    WHERE quantity != 0
                    ORDER BY symbol
                """))
                rows = result.fetchall()

            if not rows:
                return "[dim]No open positions.[/dim]"

            lines = [
                "[bold]Open Positions:[/bold]",
                f"  {'Symbol':16s}  {'Side':5s}  {'Qty':>10s}  "
                f"{'Entry':>10s}  {'Price':>10s}  {'P&L':>10s}",
            ]
            for r in rows:
                pnl = r.unrealized_pnl or 0.0
                color = "green" if pnl >= 0 else "red"
                lines.append(
                    f"  {r.symbol:16s}  {r.side:5s}  {r.quantity:>10.4f}  "
                    f"${r.avg_entry_price or 0:>9.2f}  "
                    f"${r.current_price or 0:>9.2f}  "
                    f"[{color}]${pnl:>+9.2f}[/]"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]positions failed:[/red] {exc}"

    async def _cmd_orders(self, args: list[str]) -> str:
        """Show recent orders."""
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT id, symbol, side, quantity, status, broker, created_at
                    FROM orders
                    ORDER BY created_at DESC
                    LIMIT 20
                """))
                rows = result.fetchall()

            if not rows:
                return "[dim]No orders.[/dim]"

            lines = [
                "[bold]Recent Orders:[/bold]",
                f"  {'ID':8s}  {'Symbol':16s}  {'Side':5s}  "
                f"{'Qty':>10s}  {'Status':10s}  {'Broker':8s}",
            ]
            for r in rows:
                status_color = (
                    "yellow" if r.status == "PENDING"
                    else "green" if r.status == "FILLED"
                    else "red" if r.status in ("REJECTED", "CANCELLED")
                    else "cyan"
                )
                lines.append(
                    f"  {str(r.id)[:8]:8s}  {r.symbol:16s}  "
                    f"{r.side:5s}  {r.quantity:>10.4f}  "
                    f"[{status_color}]{r.status:10s}[/]  {r.broker:8s}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]orders failed:[/red] {exc}"

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

        # Fall through to the DB — signals emitted on prior runs live there
        # even if the dashboard buffer is empty after a restart.
        try:
            from sqlalchemy import text

            from app.core.runtime import get_session_factory as _gsf
            async with _gsf()() as session:
                result = await session.execute(text(
                    """
                    SELECT symbol, direction, strength, strategy_name, created_at
                    FROM signals
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                ))
                rows = result.fetchall()
            if rows:
                lines = ["[bold]Recent Signals (from DB):[/bold]"]
                for r in rows:
                    lines.append(
                        f"  {r.symbol:14s} {r.direction:5s}  "
                        f"str={float(r.strength or 0):.2f}  "
                        f"{r.strategy_name}  {str(r.created_at)[:19]}"
                    )
                return "\n".join(lines)
        except Exception:
            pass

        return (
            "[yellow]No signals available yet.[/yellow]\n"
            "[dim]Sleeves (trend/gap/momentum) emit only during US market "
            "hours (9:30–16:00 ET, Mon–Fri).\n"
            "Run `strategy status` for diagnostics or `buy <SYM>` to trade "
            "manually.[/dim]"
        )

    async def _cmd_backtest(self, args: list[str]) -> str:
        """Run a backtest on historical data."""
        if not args:
            return (
                "Usage: backtest <SYMBOL> [--days N] [--strategy NAME]\n"
                "  Strategies: momentum, mean_reversion, volatility, crisis\n"
                "  Example: backtest AAPL --days 120 --strategy momentum"
            )

        symbol = args[0]
        days = 252
        strategy_name = "momentum"

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
                                symbol=symbol, side="SELL",
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
                                symbol=symbol, side="SELL",
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
                                symbol=symbol, side="SELL",
                                quantity=context["position_qty"],
                            )
                        return None
                else:
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
                                symbol=symbol, side="SELL",
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
                f"  Total Trades:      {len(result.trades)}"
            )
        except Exception as exc:
            return f"[red]Backtest failed:[/red] {exc}"

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
            f"  Max Drawdown:    {m.get('max_drawdown', 0):.4%}\n"
            f"  Win Rate:        {m.get('win_rate', 0):.1%}\n"
            f"  Trades:          {r['trades']}"
        )

    async def _cmd_risk(self, args: list[str]) -> str:
        # `risk reset` clears the kill-switch halt flag manually (sticky halt
        # design: automatic auto-recovery was removed).
        if args and args[0] == "reset":
            from app.core.kv_store import get_kv_store
            kv = get_kv_store()
            halted = await kv.get("horizon:system:halted")
            if halted != "1":
                return "[yellow]System not currently halted. Nothing to reset.[/yellow]"
            await kv.set("horizon:system:halted", "0")
            return (
                "[bold green]Kill switch reset — system may resume trading.[/bold green]"
            )

        if self._dashboard and self._dashboard._risk:
            r = self._dashboard._risk
            halted_hint = ""
            if r.get("kill_switch_active"):
                halted_hint = (
                    "\n[bold red]Kill switch ACTIVE.[/bold red] "
                    "Run `risk reset` to clear."
                )
            return (
                f"[bold]Risk Metrics:[/bold]\n"
                f"  VaR (95%):     {r.get('var_95', 0.0):.4f}\n"
                f"  Max Drawdown:  {r.get('max_drawdown', 0.0):.2f}%\n"
                f"  Curr Drawdown: {r.get('current_drawdown', 0.0):.2f}%"
                f"{halted_hint}"
            )
        return "[yellow]No risk data available yet.[/yellow]"

    async def _cmd_sentiment(self, args: list[str]) -> str:
        """Show latest sentiment data from KV store."""
        from app.core.kv_store import get_kv_store
        kv = get_kv_store()
        lines = ["[bold]Sentiment Data:[/bold]"]
        symbols = settings.all_symbols[:5]
        found = False
        for symbol in symbols:
            raw = symbol.split(".")[0] if "." in symbol else symbol
            data = await kv.hgetall(f"horizon:sentiment:{raw}")
            if data:
                found = True
                score = data.get("score", "?")
                label = data.get("label", "?")
                lines.append(f"  {raw:16s}  {label:10s}  score={score}")
        if not found:
            return "[yellow]No sentiment data available yet.[/yellow]"
        return "\n".join(lines)

    async def _cmd_debate(self, args: list[str]) -> str:
        """Show recent debate history."""
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT id, symbol, proposed_action, final_decision,
                           consensus_score, reason, created_at
                    FROM debate_sessions
                    ORDER BY created_at DESC
                    LIMIT 10
                """))
                rows = result.fetchall()

            if not rows:
                return "[dim]No debate history yet.[/dim]"

            lines = [
                "[bold]Recent Debates:[/bold]",
                f"  {'Session':8s}  {'Symbol':16s}  {'Action':6s}  "
                f"{'Decision':10s}  {'Score':>7s}  {'Reason'}",
            ]
            for r in rows:
                decision = r.final_decision or "--"
                dec_color = (
                    "green" if decision == "APPROVED"
                    else "red" if decision == "REJECTED"
                    else "dim"
                )
                score = f"{r.consensus_score:.2f}" if r.consensus_score else "--"
                reason = (r.reason or "")[:60]
                lines.append(
                    f"  {str(r.id)[:8]:8s}  {r.symbol:16s}  "
                    f"{r.proposed_action or '':6s}  "
                    f"[{dec_color}]{decision:10s}[/]  {score:>7s}"
                    f"  [dim]{reason}[/dim]"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]debate failed:[/red] {exc}"

    async def _cmd_agents(self, args: list[str]) -> str:
        """Show agent configuration."""
        from app.llm.agent_config import DEFAULT_AGENT_CONFIGS
        from app.llm.provider_registry import provider_registry

        available_llms = provider_registry.list_available()
        llm_list = ", ".join(available_llms) if available_llms else "none configured"
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

    async def _cmd_health(self, args: list[str]) -> str:
        """Show system health."""
        try:
            from app.services.health_monitor import HealthMonitor

            monitor = getattr(self._orchestrator, "_health_monitor_svc", None)
            if monitor is None:
                monitor = HealthMonitor(
                    bus=self._orchestrator.bus if self._orchestrator else None,
                )

            snapshot = await monitor.get_snapshot(orchestrator=self._orchestrator)
            return monitor.to_rich_text(snapshot)
        except Exception as exc:
            return f"[yellow]Health check failed: {exc}[/yellow]"

    async def _cmd_performance(self, args: list[str]) -> str:
        """Show performance metrics for a given period."""
        period = args[0].upper() if args else "30D"
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
            f"  Max Drawdown:      {snapshot['max_drawdown']:.4%}\n"
            f"  Win Rate:          {snapshot['win_rate']:.1%}\n"
            f"  Total Trades:      {snapshot['total_trades']}"
        )

    async def _cmd_config(self, args: list[str]) -> str:
        from app.llm.provider_registry import provider_registry

        available_llms = provider_registry.list_available()
        llm_list = ", ".join(available_llms) if available_llms else "none"
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

    # ------------------------------------------------------------------ #
    # Order approval commands (HUMAN_APPROVAL mode)
    # ------------------------------------------------------------------ #

    def _get_execution_agent(self):
        """Find the execution agent from the orchestrator."""
        if not self._orchestrator:
            return None
        for slot in self._orchestrator._slots.values():
            if slot.agent.agent_type == "execution":
                return slot.agent
        return None

    async def _cmd_approve(self, args: list[str]) -> str:
        """Approve a pending order by ID prefix."""
        if not args:
            return "Usage: approve <order-id-prefix>"
        agent = self._get_execution_agent()
        if not agent:
            return "[red]Execution agent not available.[/red]"
        ok = await agent.approve_order(args[0])
        if ok:
            return f"[green]Order {args[0]} approved and sent for execution.[/green]"
        return f"[red]No pending order matching '{args[0]}'. Use 'pending' to list.[/red]"

    async def _cmd_reject(self, args: list[str]) -> str:
        """Reject a pending order by ID prefix."""
        if not args:
            return "Usage: reject <order-id-prefix>"
        agent = self._get_execution_agent()
        if not agent:
            return "[red]Execution agent not available.[/red]"
        ok = await agent.reject_order(args[0])
        if ok:
            return f"[yellow]Order {args[0]} rejected.[/yellow]"
        return f"[red]No pending order matching '{args[0]}'. Use 'pending' to list.[/red]"

    async def _cmd_pending(self, args: list[str]) -> str:
        """Show orders awaiting CIO approval."""
        agent = self._get_execution_agent()
        if not agent:
            return "[red]Execution agent not available.[/red]"
        pending = agent.get_pending_approvals()
        if not pending:
            return "[dim]No orders awaiting approval.[/dim]"
        lines = [
            "[bold]Pending Approvals:[/bold]",
            f"  {'ID':8s}  {'Symbol':16s}  {'Side':5s}  {'Qty':>10s}  {'Type':8s}",
        ]
        for o in pending:
            oid = str(o.get("id", ""))[:8]
            lines.append(
                f"  {oid:8s}  {o['symbol']:16s}  {o['side']:5s}  "
                f"{o['quantity']:>10.4f}  {o.get('order_type', 'MARKET'):8s}"
            )
        lines.append("\n  Use 'approve <id>' or 'reject <id>' to act on an order.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Trade and P&L commands
    # ------------------------------------------------------------------ #

    async def _cmd_trades(self, args: list[str]) -> str:
        """Show filled trades. Usage: trades [page N] [all]

        trades          — last 20 trades (most recent first)
        trades page 2   — trades 21-40
        trades all       — all trades (capped at 100)
        """
        from sqlalchemy import text

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        page_size = 20
        page = 1
        show_all = False

        # Parse args: "trades page 2" or "trades all"
        if args:
            if args[0] == "all":
                show_all = True
            elif args[0] == "page" and len(args) > 1:
                try:
                    page = max(1, int(args[1]))
                except ValueError:
                    pass

        limit = 100 if show_all else page_size
        offset = 0 if show_all else (page - 1) * page_size

        try:
            async with _get_sf()() as session:
                # Get total count
                count_result = await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM fills")
                )
                total = count_result.scalar() or 0

                result = await session.execute(text("""
                    SELECT o.id, o.symbol, o.side,
                           f.filled_qty, f.fill_price,
                           f.commission, f.slippage, f.filled_at
                    FROM fills f
                    JOIN orders o ON f.order_id = o.id
                    ORDER BY f.filled_at DESC
                    LIMIT :lim OFFSET :off
                """), {"lim": limit, "off": offset})
                rows = result.fetchall()

            if not rows:
                if page > 1:
                    return f"[dim]No trades on page {page}.[/dim]"
                return "[dim]No trades executed yet.[/dim]"

            total_pages = max(1, (total + page_size - 1) // page_size)
            if show_all:
                header = f"[bold]All Trades ({total}):[/bold]"
            else:
                header = (
                    f"[bold]Trades (page {page}/{total_pages},"
                    f" {total} total):[/bold]"
                )

            lines = [
                header,
                f"  {'Symbol':16s}  {'Side':5s}  {'Qty':>10s}  "
                f"{'Price':>10s}  {'Slippage':>10s}  {'Time':>6s}",
            ]
            for r in rows:
                ts = str(r.filled_at)[11:16] if r.filled_at else "--:--"
                side_color = "green" if r.side == "BUY" else "red"
                lines.append(
                    f"  {r.symbol:16s}  [{side_color}]{r.side:5s}[/]  "
                    f"{r.filled_qty:>10.4f}  ${r.fill_price:>9.2f}  "
                    f"${r.slippage:>9.4f}  {ts}"
                )

            if not show_all and total_pages > 1:
                lines.append("")
                nav_parts = []
                if page > 1:
                    nav_parts.append(
                        f"[dim]trades page {page - 1}[/dim] ←"
                    )
                if page < total_pages:
                    nav_parts.append(
                        f"→ [dim]trades page {page + 1}[/dim]"
                    )
                nav_parts.append("[dim]trades all[/dim]")
                lines.append("  " + "  |  ".join(nav_parts))

            return "\n".join(lines)
        except Exception as exc:
            return f"[red]trades failed:[/red] {exc}"

    async def _cmd_pnl(self, args: list[str]) -> str:
        """Show total realized and unrealized P&L."""
        from sqlalchemy import text

        from app.core.kv_store import get_kv_store

        def _get_sf():
            from app.core.runtime import get_session_factory
            return get_session_factory()

        try:
            kv = get_kv_store()
            cash_usd = float(await kv.get("horizon:cash:usd") or 0)
            cash_inr = float(await kv.get("horizon:cash:inr") or 0)
            nav_str = await kv.get("horizon:portfolio:nav")
            nav = float(nav_str) if nav_str else 0.0

            async with _get_sf()() as session:
                result = await session.execute(text("""
                    SELECT COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized,
                           COALESCE(SUM(realized_pnl), 0) AS total_realized,
                           COUNT(*) AS position_count
                    FROM positions WHERE quantity != 0
                """))
                row = result.fetchone()

            unrealized = row.total_unrealized if row else 0.0
            realized = row.total_realized if row else 0.0
            pos_count = row.position_count if row else 0
            total = realized + unrealized

            initial_usd = settings.initial_capital_usd
            return_pct = ((nav - initial_usd) / initial_usd * 100) if initial_usd else 0.0

            r_color = "green" if realized >= 0 else "red"
            u_color = "green" if unrealized >= 0 else "red"
            t_color = "green" if total >= 0 else "red"
            ret_color = "green" if return_pct >= 0 else "red"

            return (
                f"[bold]Profit & Loss:[/bold]\n"
                f"  Initial Capital:   ${initial_usd:>12,.2f}\n"
                f"  Current NAV:       ${nav:>12,.2f}\n"
                f"  Cash (USD):        ${cash_usd:>12,.2f}\n"
                f"  Cash (INR):        ₹{cash_inr:>12,.2f}\n"
                f"  Open Positions:    {pos_count}\n"
                f"  [{r_color}]Realized P&L:      ${realized:>+12,.2f}[/]\n"
                f"  [{u_color}]Unrealized P&L:    ${unrealized:>+12,.2f}[/]\n"
                f"  [{t_color}]Total P&L:         ${total:>+12,.2f}[/]\n"
                f"  [{ret_color}]Return:            {return_pct:>+11.2f}%[/]"
            )
        except Exception as exc:
            return f"[red]pnl failed:[/red] {exc}"

    # ------------------------------------------------------------------ #
    # CIO commands
    # ------------------------------------------------------------------ #

    def set_cio_agent(self, cio_agent) -> None:
        """Wire in the running CIO agent instance."""
        self._cio_agent = cio_agent

    def _get_cio_agent(self):
        """Resolve the CIO agent: prefer wired instance, fall back to orchestrator lookup."""
        if self._cio_agent is not None:
            return self._cio_agent
        if self._orchestrator is not None:
            agent = self._orchestrator.get_agent("cio-agent-1")
            if agent is not None:
                self._cio_agent = agent
                return agent
        return None

    async def _cmd_cio(self, args: list[str]) -> str:
        """Handle 'cio', 'cio why', 'cio confirm halt' commands."""
        sub = " ".join(args).lower().strip() if args else ""

        if sub == "why":
            cio = self._get_cio_agent()
            if cio is None:
                from app.config import CIOMode, settings
                if settings.cio_mode != CIOMode.AI:
                    return "[yellow]CIO is in HUMAN mode. Set CIO_MODE=AI to enable AI CIO.[/yellow]"
                return "[yellow]CIO agent not running.[/yellow]"
            override = cio.get_last_override()
            if override is None:
                return "[dim]No override has been issued this session.[/dim]"
            reasoning = override.get("full_prompt", "No reasoning recorded.")
            timestamp = override.get("timestamp", "unknown")
            return (
                f"[bold red]Last CIO Override[/bold red]\n"
                f"Time: {timestamp}\n"
                f"Confidence: {override.get('confidence', '?')}\n"
                f"Reasoning: {reasoning}"
            )

        elif sub == "confirm halt":
            cio = self._get_cio_agent()
            if cio is None:
                from app.config import CIOMode, settings
                if settings.cio_mode != CIOMode.AI:
                    return "[yellow]CIO is in HUMAN mode. Set CIO_MODE=AI to enable AI CIO.[/yellow]"
                return "[yellow]CIO agent not running.[/yellow]"
            cio.set_halt_confirmed()
            return (
                "[bold red]HALT confirmed. "
                "CIO will proceed with halt actions.[/bold red]"
            )

        else:
            return await self._cmd_cio_latest()

    async def _cmd_cio_latest(self) -> str:
        """Fetch and display the latest CIO advisory from DB."""
        try:
            from sqlalchemy import text

            from app.core.runtime import get_session_factory
            async with get_session_factory()() as session:
                result = await session.execute(text(
                    "SELECT outlook, summary, recommended_adjustments, "
                    "risk_flags, timestamp "
                    "FROM cio_advisories ORDER BY timestamp DESC LIMIT 1"
                ))
                row = result.fetchone()
            if row is None:
                return (
                    "[dim]No CIO advisory recorded yet. "
                    "CIO issues advisories every 15 minutes "
                    "when LLM is configured.[/dim]"
                )
            import json
            adj = json.loads(row[2]) if row[2] else []
            flags = json.loads(row[3]) if row[3] else []
            lines = [
                f"[bold cyan]CIO Advisory[/bold cyan] — {row[4]}",
                f"Outlook: [yellow]{row[0]}[/yellow]",
                f"Summary: {row[1]}",
            ]
            if adj:
                lines.append("Adjustments:")
                for a in adj[:5]:
                    if isinstance(a, dict):
                        lines.append(
                            f"  • {a.get('symbol', '')} → {a.get('action', '')}: "
                            f"{a.get('reason', '')}"
                        )
                    else:
                        lines.append(f"  • {a}")
            if flags:
                lines.append("Risk flags: " + ", ".join(flags[:3]))
            return "\n".join(lines)
        except Exception as exc:
            return f"[red]Error fetching CIO advisory: {exc}[/red]"

    # ------------------------------------------------------------------ #
    # Watchlist commands
    # ------------------------------------------------------------------ #

    async def _cmd_watchlist(self, args: list[str]) -> str:
        """Show, add, or remove watchlist symbols."""
        if not args:
            symbols = settings.all_symbols
            lines = ["[bold]Watchlist ([/bold]" + str(len(symbols)) + "[bold] symbols):[/bold]"]
            for s in symbols:
                lines.append(f"  {s}")
            lines.append("\n  [dim]Use 'watchlist add <SYM>' or 'watchlist remove <SYM>'[/dim]")
            return "\n".join(lines)

        sub = args[0].lower()
        if sub == "add" and len(args) >= 2:
            symbol = args[1].upper()
            return await self._watchlist_add(symbol)
        elif sub == "remove" and len(args) >= 2:
            symbol = args[1].upper()
            return await self._watchlist_remove(symbol)
        return "[red]Usage: watchlist [add|remove] <SYMBOL>[/red]"

    async def _watchlist_add(self, symbol: str) -> str:
        """Add a symbol to the trading universe via .env."""
        current = settings.all_symbols
        if symbol in current:
            return f"[yellow]{symbol} already in watchlist.[/yellow]"

        # US-only scope — Alpaca feed handles US equities; INR/crypto buckets
        # are currently zero so orders would fail sizing.
        if ".NSE" in symbol or ".BSE" in symbol:
            return (
                "[red]Indian symbols not supported in current scope "
                "(INR cash bucket is 0).[/red]"
            )
        if "-USD" in symbol or "-USDT" in symbol:
            return (
                "[red]Crypto symbols not supported in current scope.[/red]"
            )

        key = "US_SYMBOLS"
        current_csv = settings.us_symbols

        new_csv = current_csv + "," + symbol if current_csv else symbol
        self._update_env(key, new_csv)

        # Update settings in-memory
        if key == "INDIA_SYMBOLS":
            settings.india_symbols = new_csv
        elif key == "CRYPTO_SYMBOLS":
            settings.crypto_symbols = new_csv
        else:
            settings.us_symbols = new_csv

        return f"[green]{symbol} added to watchlist.[/green] Restart for strategy agent to pick it up."

    async def _watchlist_remove(self, symbol: str) -> str:
        """Remove a symbol from the trading universe via .env."""
        current = settings.all_symbols
        if symbol not in current:
            return f"[yellow]{symbol} not in watchlist.[/yellow]"

        if ".NSE" in symbol or ".BSE" in symbol:
            key = "INDIA_SYMBOLS"
            current_csv = settings.india_symbols
        elif "-USD" in symbol:
            key = "CRYPTO_SYMBOLS"
            current_csv = settings.crypto_symbols
        else:
            key = "US_SYMBOLS"
            current_csv = settings.us_symbols

        parts = [s.strip() for s in current_csv.split(",") if s.strip() != symbol]
        new_csv = ",".join(parts)
        self._update_env(key, new_csv)

        if key == "INDIA_SYMBOLS":
            settings.india_symbols = new_csv
        elif key == "CRYPTO_SYMBOLS":
            settings.crypto_symbols = new_csv
        else:
            settings.us_symbols = new_csv

        return f"[green]{symbol} removed from watchlist.[/green] Restart for changes to take effect."

    @staticmethod
    def _update_env(key: str, value: str) -> None:
        """Update a key in the backend .env file."""
        import os
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith(key + "="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")
        with open(env_path, "w") as f:
            f.writelines(lines)

    # ------------------------------------------------------------------ #
    # Manual trading commands
    # ------------------------------------------------------------------ #

    async def _cmd_buy(self, args: list[str]) -> str:
        """Place a manual BUY order."""
        if not args:
            return "Usage: buy <SYMBOL> [quantity]"
        return await self._manual_order(args, side="BUY")

    async def _cmd_sell(self, args: list[str]) -> str:
        """Place a manual SELL order."""
        if not args:
            return "Usage: sell <SYMBOL> [quantity]"
        return await self._manual_order(args, side="SELL")

    async def _manual_order(self, args: list[str], side: str) -> str:
        """Execute a manual buy/sell order."""
        from datetime import datetime

        from app.core.kv_store import get_kv_store
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        symbol = args[0].upper()
        qty = None
        if len(args) >= 2:
            try:
                qty = float(args[1])
            except ValueError:
                return f"[red]Invalid quantity: {args[1]}[/red]"

        kv = get_kv_store()

        # Get price — Alpaca live first (if configured and US ticker), then
        # KV cache, then yfinance as a last resort.
        raw = symbol.split(".")[0] if "." in symbol else symbol
        price: float | None = None

        from app.data_layer import alpaca_quotes
        is_us = not (".NSE" in symbol or ".BSE" in symbol or "-USD" in symbol)
        if is_us and alpaca_quotes.is_configured():
            price = await alpaca_quotes.get_latest_price(symbol)

        if price is None or price <= 0:
            price_str = (
                await kv.get(f"horizon:price:{symbol}")
                or await kv.get(f"horizon:price:{raw}")
            )
            if price_str:
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    price = None

        if price is None or price <= 0:
            try:
                import asyncio
                import yfinance as yf
                yf_ticker = raw + ".NS" if ".NSE" in symbol else (
                    raw + ".BO" if ".BSE" in symbol else raw
                )
                ticker = yf.Ticker(yf_ticker)
                hist = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ticker.history(period="1d")
                )
                if hist is not None and not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            except Exception:
                pass

        if price is None or price <= 0:
            return (
                f"[red]No price available for {symbol}. "
                f"Check Alpaca credentials or wait for the data feed.[/red]"
            )
        await kv.set(f"horizon:price:{symbol}", str(price))
        await kv.set(f"horizon:price:{symbol}:ts", datetime.now(UTC).isoformat())

        # Auto-size if no qty given
        if qty is None:
            if side == "SELL":
                # Sell entire position
                from sqlalchemy import text
                from app.core.runtime import get_session_factory
                async with get_session_factory()() as session:
                    result = await session.execute(
                        text("SELECT quantity FROM positions WHERE symbol = :sym AND quantity > 0 LIMIT 1"),
                        {"sym": symbol},
                    )
                    row = result.fetchone()
                if not row:
                    return f"[red]No open position in {symbol} to sell.[/red]"
                qty = row.quantity
            else:
                # Buy: use 3% of NAV
                cash_str = await kv.get("horizon:cash:usd")
                cash = float(cash_str) if cash_str else 0.0
                allocation = cash * (settings.risk_max_position_pct / 100.0)
                qty = int(allocation / price) if price > 0 else 0
                if qty <= 0:
                    return f"[red]Insufficient cash to buy {symbol} at ${price:.2f}[/red]"

        # Determine exchange
        if ".NSE" in symbol:
            exchange = "NSE"
        elif ".BSE" in symbol:
            exchange = "BSE"
        elif "-USD" in symbol:
            exchange = "CRYPTO"
        else:
            exchange = "NASDAQ"

        # Publish order to execution pipeline
        bus = get_bus()
        await bus.publish(
            AgentMessage(
                sender_id="manual-cio",
                channel="horizon.execution.order.new",
                message_type=MessageType.ORDER_NEW,
                payload={
                    "symbol": symbol,
                    "exchange": exchange,
                    "side": side,
                    "quantity": qty,
                    "order_type": "MARKET",
                    "signal_id": None,
                    "debate_id": None,
                    "stop_loss": None,
                    "allocation_usd": qty * price,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

        action = "Buying" if side == "BUY" else "Selling"
        return f"[green]{action} {qty:.4f} {symbol} @ ~${price:.2f} (${qty * price:,.2f})[/green]"

    async def _cmd_settings(self, args: list[str]) -> str:
        """Open the interactive settings panel."""
        return "__OPEN_SETTINGS__"

    async def _cmd_model(self, args: list[str]) -> str:
        """Per-agent LLM model selection.

        Usage:
            model                                — show current overrides + LLM agents
            model list                           — list every available model (cheap->premium)
            model list <provider>                — list models for one provider
            model agents                         — list agents that use an LLM
            model set <agent_id> <provider> <model_id>  — pin agent to model
            model clear <agent_id>               — remove override (back to default)
        """
        from app.llm.agent_config import get_agent_configs
        from app.llm.agent_model_overrides import (
            clear_override,
            list_overrides,
            set_override,
        )
        from app.llm.models_registry import all_models, list_models
        from app.llm.provider_registry import provider_registry

        sub = args[0].lower() if args else ""

        if sub == "list":
            provider = args[1].lower() if len(args) > 1 else None
            models = list_models(provider) if provider else all_models()
            if not models:
                return f"[yellow]No models for provider '{provider}'.[/yellow]"
            lines = [
                "[bold]Available models[/bold] (provider | model_id | tier | "
                "$/1M in | $/1M out)",
            ]
            for m in models:
                lines.append(
                    f"  {m.provider:8s} {m.model_id:34s} {m.tier:8s} "
                    f"${m.input_cost_per_1m:>5.2f} / ${m.output_cost_per_1m:>5.2f}  "
                    f"({m.label})"
                )
            return "\n".join(lines)

        if sub == "agents":
            cfgs = [c for c in get_agent_configs() if c.llm_provider]
            if not cfgs:
                return "[yellow]No LLM-using agents (no providers registered?).[/yellow]"
            lines = ["[bold]LLM-using agents[/bold] (id | role | dept | default-provider)"]
            for c in cfgs:
                lines.append(
                    f"  {c.instance_id:30s} {c.role:22s} "
                    f"{c.department:14s} {c.llm_provider}"
                )
            return "\n".join(lines)

        if sub == "set":
            if len(args) < 4:
                return "[red]Usage:[/red] model set <agent_id> <provider> <model_id>"
            agent_id, provider, model_id = args[1], args[2].lower(), args[3]
            ok = set_override(agent_id, provider, model_id)
            if not ok:
                return (
                    f"[red]Rejected.[/red] Check provider/model. "
                    f"Run `model list {provider}` for valid IDs."
                )
            # Verify the registry can actually build the provider
            prov = provider_registry.get_provider_for_agent(agent_id, provider)
            if prov is None:
                return (
                    f"[yellow]Override saved but provider '{provider}' not "
                    f"registered yet.[/yellow] Set the API key for {provider} "
                    f"and restart, or use a registered provider."
                )
            return (
                f"[green]Override set:[/green] {agent_id} -> "
                f"{provider}/{model_id} (active model: {prov.model})"
            )

        if sub == "clear":
            if len(args) < 2:
                return "[red]Usage:[/red] model clear <agent_id>"
            agent_id = args[1]
            existed = clear_override(agent_id)
            return (
                f"[green]Cleared override for {agent_id}[/green]" if existed
                else f"[yellow]No override existed for {agent_id}[/yellow]"
            )

        # Default: show current overrides + LLM agents
        overrides = list_overrides()
        cfgs = {c.instance_id: c for c in get_agent_configs() if c.llm_provider}
        lines = [
            "[bold]Per-agent LLM model selection[/bold]",
            f"Configured overrides: {len(overrides)}",
            "",
            "[bold]LLM agents[/bold] (agent_id | role | default | OVERRIDE):",
        ]
        for aid, c in sorted(cfgs.items()):
            ov = overrides.get(aid)
            ov_str = (f"[green]-> {ov['provider']}/{ov['model']}[/green]"
                      if ov else "[dim]none[/dim]")
            lines.append(
                f"  {aid:30s} {c.role:22s} {c.llm_provider:8s} {ov_str}"
            )
        lines.append("")
        lines.append(
            "[dim]Subcommands: list [provider], agents, set <agent> <provider> "
            "<model>, clear <agent>[/dim]"
        )
        return "\n".join(lines)

    async def _cmd_quit(self, args: list[str]) -> str:
        self._should_quit = True
        return "[bold red]Shutting down Horizon Capital...[/bold red]"
