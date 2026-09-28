# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4F96A7635CA7
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Rich-based terminal dashboard for Horizon Capital.

Renders a live-updating 3-column Intelligence Hub TUI showing:
  - Header: system mode, CIO mode, NAV, VaR, drawdown, uptime
  - Left column: agent status with current tasks, alerts
  - Center column: live watchlist with sparklines and signal direction
  - Right column: portfolio positions with P&L, risk metrics
  - Bottom strip: pending orders and trade history
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.config import settings

DEPARTMENT_COLORS = {
    "front_office": "bright_blue",
    "middle_office": "bright_yellow",
    "back_office": "bright_magenta",
    "executive": "bright_red",
}

SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def render_sparkline(values: list[float], width: int = 0) -> str:
    """Render a list of values as a Unicode sparkline string."""
    if not values:
        return ""
    if width and len(values) > width:
        values = values[-width:]
    mn, mx = min(values), max(values)
    spread = mx - mn
    if spread == 0:
        return SPARKLINE_CHARS[3] * len(values)
    return "".join(
        SPARKLINE_CHARS[min(int((v - mn) / spread * 7), 7)] for v in values
    )


class TerminalDashboard:
    """Live terminal dashboard that polls system state and renders with Rich."""

    def __init__(self) -> None:
        self.console = Console()
        self._running = False
        self._agent_statuses: dict[str, dict[str, Any]] = {}
        self._signals: list[dict[str, Any]] = []
        self._risk: dict[str, Any] = {}
        self._start_time: datetime = datetime.now(UTC)
        self._portfolio: dict[str, Any] = {
            "nav": 0.0, "cash": 0.0, "positions": [],
        }
        self._alerts: list[dict[str, Any]] = []
        self._watchlist: dict[str, dict[str, Any]] = {}
        self._pending_orders: list[dict[str, Any]] = []
        self._trade_history: list[dict[str, Any]] = []

        # Pixel agent office view
        from app.tui.pixel_agents import PixelAgentVisualizer
        self.pixel_agents = PixelAgentVisualizer()
        self._sentiment: dict[str, dict[str, Any]] = {}

    # -- Data update methods (called by the orchestrator) ----------------

    def add_alert(self, alert: dict[str, Any]) -> None:
        self._alerts.insert(0, alert)
        self._alerts = self._alerts[:20]

    def update_agent_status(self, agent_id: str, status: dict[str, Any]) -> None:
        self._agent_statuses[agent_id] = status
        dept = status.get("department", "")
        agent_state = status.get("status", status.get("state", "IDLE"))
        self.pixel_agents.update_state(agent_id, agent_state, department=dept)

    def add_signal(self, signal: dict[str, Any]) -> None:
        self._signals.insert(0, signal)
        self._signals = self._signals[:20]

    def update_risk(self, data: dict[str, Any]) -> None:
        self._risk = data

    def update_portfolio(self, data: dict[str, Any]) -> None:
        # Normalize keys so dashboard/commands can use consistent names
        self._portfolio["nav"] = data.get("total_value", data.get("nav", 0.0))
        self._portfolio["cash"] = data.get("cash_usd", data.get("cash", 0.0))
        if "positions" in data:
            self._portfolio["positions"] = data["positions"]

    def update_watchlist(self, data: dict[str, Any]) -> None:
        """Update a symbol's price data in the watchlist."""
        symbol = data.get("symbol", "")
        if not symbol:
            return
        if symbol not in self._watchlist:
            self._watchlist[symbol] = {
                "price": 0.0,
                "change_pct": 0.0,
                "prev_close": 0.0,
                "history": [],
            }
        entry = self._watchlist[symbol]
        entry["price"] = data.get("price", entry["price"])
        entry["change_pct"] = data.get("change_pct", 0.0)
        entry["prev_close"] = data.get("prev_close", entry.get("prev_close", 0.0))
        entry["history"].append(entry["price"])
        if len(entry["history"]) > 20:
            entry["history"] = entry["history"][-20:]

    def add_pending_order(self, order: dict[str, Any]) -> None:
        """Add an order to the pending orders list."""
        self._pending_orders.insert(0, order)
        self._pending_orders = self._pending_orders[:20]

    def complete_order(self, fill: dict[str, Any]) -> None:
        """Move a filled order from pending to trade history."""
        order_id = fill.get("order_id", "")
        symbol = fill.get("symbol", "")
        side = fill.get("side", "")
        # Match by order_id first, then by symbol+side as fallback
        self._pending_orders = [
            o for o in self._pending_orders
            if o.get("order_id") != order_id
            and not (
                o.get("symbol") == symbol
                and o.get("side") == side
                and not order_id
            )
        ]
        self._trade_history.insert(0, fill)
        self._trade_history = self._trade_history[:20]

    def remove_order(self, order_id: str) -> None:
        """Remove a rejected/cancelled order from pending."""
        self._pending_orders = [
            o for o in self._pending_orders if o.get("order_id") != order_id
        ]

    def update_sentiment(self, data: dict[str, Any]) -> None:
        """Store latest sentiment for a symbol."""
        symbol = data.get("symbol", "")
        if symbol:
            self._sentiment[symbol] = data

    def update_cio_advisory(self, payload: dict[str, Any]) -> None:
        """Store the latest CIO advisory for rendering."""
        self._cio_advisory = payload

    # -- Layout builders -------------------------------------------------

    def _build_header(self) -> Panel:
        uptime = datetime.now(UTC) - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        mode_colors = {
            "PAPER_TRADING": "yellow",
            "HUMAN_APPROVAL": "cyan",
            "FULLY_AUTONOMOUS": "red",
        }
        mode = settings.system_mode.value
        mode_color = mode_colors.get(mode, "white")

        nav = self._portfolio.get("nav", 0.0)
        var_95 = self._risk.get("var_95", 0.0)
        curr_dd = self._risk.get("current_drawdown", 0.0)
        dd_color = "red" if curr_dd > 5.0 else "yellow" if curr_dd > 2.0 else "green"

        header = Text()
        header.append("HORIZON CAPITAL ", style="bold white")
        header.append("v0.2.0 ", style="dim")
        header.append("│ ", style="dim")
        header.append(f"{mode}", style=f"bold {mode_color}")
        header.append(" │ ", style="dim")
        header.append("CIO:", style="white")
        cio_mode = settings.cio_mode.value
        cio_color = "cyan" if cio_mode == "HUMAN" else "bright_red"
        header.append(f"{cio_mode}", style=f"bold {cio_color}")
        header.append(" │ ", style="dim")
        header.append("NAV: ", style="white")
        header.append(f"${nav:,.2f}", style="bold green")
        header.append(" │ ", style="dim")
        header.append("VaR: ", style="white")
        header.append(f"{var_95:.4f}", style="bright_red")
        header.append(" │ ", style="dim")
        header.append("DD: ", style="white")
        header.append(f"{curr_dd:.1f}%", style=f"{dd_color}")
        header.append(" │ ", style="dim")
        header.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="cyan")

        return Panel(header, style="blue", height=3)

    def _build_agents_table(self) -> Panel:
        status_colors = {
            "RUNNING": "green", "ANALYZING": "green",
            "DEBATING": "blue", "EXECUTING": "bright_red",
            "INIT": "yellow", "STOPPED": "red",
            "CRASHED": "bold red", "IDLE": "dim",
        }

        lines: list[Text] = []
        if not self._agent_statuses:
            lines.append(Text("  (no agents registered)", style="dim"))
        else:
            for agent_id in sorted(self._agent_statuses.keys()):
                info = self._agent_statuses[agent_id]
                status = info.get("status", info.get("state", "IDLE"))
                s_color = status_colors.get(status, "dim")
                current_task = info.get("current_task")

                line = Text()
                line.append(" ● ", style=s_color)
                name = agent_id[:18]
                line.append(
                    f"{name:<18} ", style="white" if status != "IDLE" else "dim"
                )
                line.append(f"{status}", style=s_color)
                lines.append(line)

                if current_task and status not in ("IDLE", "STOPPED"):
                    task_line = Text()
                    task_line.append(f"     {current_task[:40]}", style="dim")
                    lines.append(task_line)

        content = Text("\n").join(lines) if lines else Text("(no agents)")
        return Panel(content, title="[bold]Agents[/bold]", border_style="cyan")

    def _build_alerts_panel(self) -> Panel:
        if not self._alerts:
            return Panel("[dim]No alerts[/dim]", title="[bold]Alerts[/bold]",
                         border_style="bright_red")

        severity_colors = {
            "INFO": "cyan",
            "WARNING": "yellow",
            "CRITICAL": "red",
            "EMERGENCY": "bold red on white",
        }
        lines: list[str] = []
        for a in self._alerts[:6]:
            sev = a.get("severity", "INFO")
            color = severity_colors.get(sev, "white")
            title = a.get("title", a.get("message", ""))
            lines.append(f"  [{color}]{sev:9s}[/] {title}")

        return Panel("\n".join(lines), title="[bold]Alerts[/bold]",
                     border_style="bright_red")

    def _build_watchlist_panel(self) -> Panel:
        if not self._watchlist:
            return Panel(
                "[dim]Awaiting price data...[/dim]",
                title="[bold]Watchlist[/bold]",
                border_style="green",
            )

        table = Table(show_header=True, header_style="bold green", expand=True)
        table.add_column("Symbol", width=14)
        table.add_column("Trend", width=10)
        table.add_column("Price", width=12, justify="right")
        table.add_column("Chg%", width=7, justify="right")
        table.add_column("Signal", width=6, justify="center")

        # Get latest signal per symbol
        latest_signals: dict[str, int] = {}
        for sig in self._signals:
            sym = sig.get("symbol", "")
            if sym and sym not in latest_signals:
                latest_signals[sym] = sig.get("direction", 0)

        for symbol in sorted(self._watchlist.keys()):
            data = self._watchlist[symbol]
            price = data["price"]
            change_pct = data["change_pct"]
            history = data["history"]

            # Guard against NaN/inf from missing prior price
            if not isinstance(change_pct, (int, float)) or math.isnan(
                change_pct
            ) or math.isinf(change_pct):
                change_pct = 0.0

            price_color = "green" if change_pct >= 0 else "red"
            arrow = "▲" if change_pct > 0 else "▼" if change_pct < 0 else " "

            spark = render_sparkline(history, width=10)

            direction = latest_signals.get(symbol, 0)
            if direction > 0:
                sig_str = "[bold green]BUY↑[/]"
            elif direction < 0:
                sig_str = "[bold red]SELL↓[/]"
            else:
                sig_str = "[dim]—[/]"

            if ".NSE" in symbol or ".BSE" in symbol:
                price_str = f"₹{price:,.2f}"
            else:
                price_str = f"${price:,.2f}"

            table.add_row(
                f"[{price_color}]{symbol}[/]",
                f"[dim]{spark}[/]",
                f"[{price_color}]{price_str}[/]",
                f"[{price_color}]{arrow}{change_pct:+.1f}%[/]",
                sig_str,
            )

        return Panel(table, title="[bold]Watchlist[/bold]", border_style="green")

    def _build_portfolio_panel(self) -> Panel:
        positions = self._portfolio.get("positions", [])
        cash = self._portfolio.get("cash", 0.0)
        nav = self._portfolio.get("nav", 0.0)

        lines: list[str] = []
        cash_pct = (cash / nav * 100) if nav > 0 else 0
        lines.append(
            f"  [dim]Cash[/dim]{'':>20} ${cash:>12,.0f} [dim]({cash_pct:.0f}%)[/]"
        )

        if not positions:
            lines.append("  [dim]No open positions[/dim]")
        elif isinstance(positions, list):
            for pos in positions[:8]:
                symbol = pos.get("symbol", "?")
                qty = pos.get("qty", 0)
                pnl = pos.get("unrealized_pnl", 0.0)
                pnl_color = "green" if pnl >= 0 else "red"
                if ".NSE" in symbol or ".BSE" in symbol:
                    pnl_str = f"₹{pnl:+,.0f}"
                else:
                    pnl_str = f"${pnl:+,.0f}"
                lines.append(
                    f"  {symbol:<18} ×{qty:<6} [{pnl_color}]{pnl_str:>10}[/]"
                )

        return Panel(
            "\n".join(lines),
            title="[bold]Portfolio[/bold]",
            border_style="magenta",
        )

    def _build_risk_panel(self) -> Panel:
        if not self._risk:
            return Panel(
                "Awaiting risk data...",
                title="[bold]Risk[/bold]",
                border_style="red",
            )

        var_95 = self._risk.get("var_95", 0.0)
        var_99 = self._risk.get("var_99", 0.0)
        max_dd = self._risk.get("max_drawdown", 0.0)
        curr_dd = self._risk.get("current_drawdown", 0.0)
        sharpe = self._risk.get("sharpe_30d", 0.0)
        kill = self._risk.get("kill_switch_active", False)

        dd_color = "red" if curr_dd > 5.0 else "yellow" if curr_dd > 2.0 else "green"

        lines = [
            f"  [dim]VaR (95%)[/dim]   {var_95:>10.4f}",
            f"  [dim]VaR (99%)[/dim]   {var_99:>10.4f}",
            f"  [dim]Max DD[/dim]      {max_dd:>10.2f}%",
            f"  [dim]Curr DD[/dim]     [{dd_color}]{curr_dd:>9.2f}%[/]",
            f"  [dim]Sharpe 30d[/dim]  {sharpe:>10.2f}",
        ]
        if kill:
            lines.append("  [bold red]KILL SWITCH   ACTIVE[/bold red]")

        return Panel("\n".join(lines), title="[bold]Risk[/bold]", border_style="red")

    def _build_orders_panel(self) -> Panel:
        if not self._pending_orders:
            return Panel(
                "[dim]No pending orders[/dim]",
                title="[bold]Pending Orders[/bold]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("ID", width=8)
        table.add_column("Side", width=5)
        table.add_column("Symbol", width=14)
        table.add_column("Qty", width=6, justify="right")
        table.add_column("Status", width=18)

        status_colors = {
            "PENDING": "yellow",
            "AWAITING_APPROVAL": "yellow",
            "IN_DEBATE": "blue",
            "SUBMITTED": "cyan",
            "PARTIAL": "yellow",
        }

        for order in self._pending_orders[:6]:
            oid = str(order.get("order_id", ""))[-8:]
            side = order.get("side", "?")
            side_color = "green" if side == "BUY" else "red"
            symbol = order.get("symbol", "?")
            qty = str(order.get("quantity", 0))
            status = order.get("status", "PENDING")
            s_color = status_colors.get(status, "white")

            table.add_row(
                f"[dim]{oid}[/]",
                f"[{side_color}]{side}[/]",
                symbol,
                qty,
                f"[{s_color}]{status}[/]",
            )

        return Panel(table, title="[bold]Pending Orders[/bold]", border_style="cyan")

    def _build_trades_panel(self) -> Panel:
        if not self._trade_history:
            return Panel(
                "[dim]No trades yet[/dim]",
                title="[bold]Trade History[/bold]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Time", width=6)
        table.add_column("Side", width=5)
        table.add_column("Symbol", width=14)
        table.add_column("Qty @ Price", width=18)
        table.add_column("Status", width=8)

        for trade in self._trade_history[:6]:
            ts = trade.get("timestamp", "")
            if isinstance(ts, str) and len(ts) > 16:
                ts = ts[11:16]
            elif not ts:
                ts = "--:--"
            side = trade.get("side", "?")
            side_color = "green" if side == "BUY" else "red"
            symbol = trade.get("symbol", "?")
            qty = trade.get("filled_qty", trade.get("quantity", 0))
            fill_price = trade.get("fill_price", 0.0)
            status = trade.get("status", "FILLED")

            table.add_row(
                f"[dim]{ts}[/]",
                f"[{side_color}]{side}[/]",
                symbol,
                f"{qty} @ {fill_price:,.2f}",
                f"[green]{status}[/]",
            )

        return Panel(table, title="[bold]Trade History[/bold]", border_style="cyan")

    def _build_sentiment_panel(self) -> Panel:
        """Show per-symbol sentiment with colour coding."""
        if not self._sentiment:
            return Panel(
                "[dim]Awaiting sentiment data...[/dim]",
                title="[bold]Sentiment[/bold]",
                border_style="yellow",
            )

        lines: list[str] = []
        for symbol in sorted(self._sentiment.keys()):
            data = self._sentiment[symbol]
            label = data.get("sentiment", "neutral")
            score = float(data.get("score", 0.0))
            raw = symbol.split(".")[0] if "." in symbol else symbol
            if label == "positive":
                color = "green"
                icon = "▲"
            elif label == "negative":
                color = "red"
                icon = "▼"
            else:
                color = "dim white"
                icon = "—"
            lines.append(
                f"  [{color}]{icon} {raw:<14}[/] [{color}]{label:8s}[/] {score:.2f}"
            )

        return Panel(
            "\n".join(lines) if lines else "[dim]No data[/dim]",
            title="[bold]Sentiment[/bold]",
            border_style="yellow",
        )

    def _build_cio_panel(self) -> Panel:
        """Render the latest CIO advisory as a Rich Panel."""
        adv = getattr(self, "_cio_advisory", None)
        if adv is None:
            return Panel("[dim]No CIO advisory yet[/dim]", title="CIO View")

        outlook_color = {"bullish": "green", "bearish": "red", "neutral": "yellow"}.get(
            adv.get("outlook", "neutral"), "white"
        )
        text = Text()
        text.append("Outlook: ", style="bold")
        text.append(adv.get("outlook", "?").upper() + "\n", style=outlook_color)
        text.append(adv.get("summary", ""), style="white")
        flags = adv.get("risk_flags", [])
        if flags:
            text.append(f"\n⚠  {', '.join(flags[:2])}", style="yellow")
        return Panel(text, title="[bold cyan]CIO View[/bold cyan]")

    def build_layout(self) -> Layout:
        """Compose the full 3-column Intelligence Hub layout."""
        layout = Layout()
        layout.split_column(
            Layout(self._build_header(), name="header", size=3),
            Layout(name="body"),
            Layout(name="orders", size=10),
        )

        layout["body"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="center", ratio=4),
            Layout(name="right", ratio=3),
        )

        layout["left"].split_column(
            Layout(self._build_agents_table(), name="agents"),
            Layout(self._build_alerts_panel(), name="alerts", size=8),
        )

        layout["center"].update(self._build_watchlist_panel())

        layout["right"].split_column(
            Layout(self._build_portfolio_panel(), name="portfolio"),
            Layout(self._build_risk_panel(), name="risk", size=10),
            Layout(self._build_cio_panel(), name="cio_view", size=8),
            Layout(self._build_sentiment_panel(), name="sentiment", size=9),
        )

        layout["orders"].split_row(
            Layout(self._build_orders_panel(), name="pending", ratio=1),
            Layout(self._build_trades_panel(), name="history", ratio=1),
        )

        return layout

    # -- Run loop --------------------------------------------------------

    async def run(self) -> None:
        """Start the live dashboard. Blocks until stopped."""
        self._running = True
        self._start_time = datetime.now(UTC)

        with Live(
            self.build_layout(),
            console=self.console,
            refresh_per_second=2,
            screen=True,
        ) as live:
            while self._running:
                live.update(self.build_layout())
                await asyncio.sleep(0.5)

    async def run_interactive(self) -> None:
        """Run live dashboard until user presses 'q' or Escape."""
        import sys

        self._running = True
        if not self._start_time:
            self._start_time = datetime.now(UTC)

        # Platform-specific key detection
        if sys.platform == "win32":
            import msvcrt

            def _key_pressed() -> str | None:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    return ch
                return None
        else:
            import select
            import termios
            import tty

            _old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

            def _key_pressed() -> str | None:
                if select.select([sys.stdin], [], [], 0)[0]:
                    return sys.stdin.read(1)
                return None

        try:
            with Live(
                self.build_layout(),
                console=self.console,
                refresh_per_second=2,
                screen=True,
            ) as live:
                while self._running:
                    live.update(self.build_layout())
                    key = await asyncio.get_event_loop().run_in_executor(
                        None, _key_pressed
                    )
                    if key and key.lower() in ("q", "\x1b"):
                        break
                    await asyncio.sleep(0.25)
        finally:
            if sys.platform != "win32":
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _old_settings)

    def stop(self) -> None:
        """Signal the dashboard to stop."""
        self._running = False

    # -- Public accessors (for CIO chat and other consumers) -------------

    def get_risk_snapshot(self) -> dict[str, Any]:
        """Return a copy of the latest risk metrics."""
        return dict(self._risk)

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        """Return a copy of the latest portfolio summary."""
        return dict(self._portfolio)

    def get_recent_signals(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return a copy of recent signals (most recent first)."""
        return list(self._signals[:limit])
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4F96A7635CA7 - verify with scripts/authorship.py verify
