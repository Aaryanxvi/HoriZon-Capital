"""Portfolio Reporting & Export Service.

Generates daily/weekly/monthly portfolio reports with performance summary,
risk metrics, attribution, and trade journal. Supports Rich terminal
tables and CSV export.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text

from app.core.logging import get_logger

logger = get_logger("services.report_generator")


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


@dataclass
class PortfolioReport:
    """A complete portfolio report."""

    report_id: str
    report_type: str  # "daily", "weekly", "monthly", "custom"
    period_start: str
    period_end: str
    generated_at: str = ""

    # Performance summary
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0

    # Portfolio state
    portfolio_value: float = 0.0
    cash: float = 0.0
    n_positions: int = 0
    gross_leverage: float = 0.0

    # Trading activity
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_commission: float = 0.0

    # Risk
    var_95: float = 0.0
    var_99: float = 0.0
    current_drawdown: float = 0.0

    # Attribution by strategy
    strategy_attribution: dict = field(default_factory=dict)

    # Position details
    positions: list[dict] = field(default_factory=list)

    # Trade journal
    trades: list[dict] = field(default_factory=list)

    # Regime context
    regime_summary: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat()


class ReportGenerator:
    """Portfolio report generator.

    Produces performance reports with standardized metrics including
    returns, risk-adjusted ratios, drawdown analysis, and trade attribution.
    """

    def __init__(self) -> None:
        self._report_counter = 0

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate(
        self,
        report_type: str = "daily",
        days: int | None = None,
    ) -> PortfolioReport:
        """Generate a portfolio report.

        Parameters
        ----------
        report_type : str
            One of: "daily", "weekly", "monthly", "custom".
        days : int, optional
            Custom number of days to look back (for "custom" type).
        """
        now = datetime.now(UTC)

        if report_type == "daily":
            start = now - timedelta(days=1)
        elif report_type == "weekly":
            start = now - timedelta(days=7)
        elif report_type == "monthly":
            start = now - timedelta(days=30)
        else:
            start = now - timedelta(days=days or 30)

        self._report_counter += 1
        report_id = f"rpt-{report_type}-{self._report_counter:06d}"

        report = PortfolioReport(
            report_id=report_id,
            report_type=report_type,
            period_start=start.isoformat(),
            period_end=now.isoformat(),
        )

        try:
            await self._fill_performance(report, start, now)
            await self._fill_positions(report)
            await self._fill_trades(report, start, now)
            await self._fill_risk(report)
            await self._fill_regime(report)
        except Exception as exc:
            logger.warning("report_generation_partial", error=str(exc))

        logger.info(
            "report_generated",
            report_id=report_id,
            type=report_type,
            total_return=f"{report.total_return:.4%}",
        )

        return report

    async def _fill_performance(
        self, report: PortfolioReport, start: datetime, end: datetime
    ) -> None:
        """Fill performance metrics from portfolio snapshots."""
        async with _get_session_factory()() as session:
            rows = await session.execute(
                text("""
                    SELECT total_value, created_at
                    FROM portfolio_snapshots
                    WHERE created_at >= :start
                    ORDER BY created_at ASC
                """),
                {"start": start},
            )
            data = rows.fetchall()

        if len(data) < 2:
            return

        values = np.array([float(r[0]) for r in data])
        returns = np.diff(values) / values[:-1]
        returns = returns[~np.isnan(returns)]

        report.portfolio_value = round(float(values[-1]), 2)

        if len(returns) > 0:
            total_ret = (values[-1] - values[0]) / values[0] if values[0] != 0 else 0
            n_days = max(len(values), 1)
            annual_ret = (1 + total_ret) ** (252 / n_days) - 1

            from app.config import settings
            rf = settings.risk_free_rate
            daily_rf = (1.0 + rf) ** (1 / 252) - 1
            excess = returns - daily_rf
            vol = float(np.std(returns, ddof=1)) if len(returns) >= 2 else 0.0

            report.total_return = round(total_ret, 6)
            report.annualized_return = round(annual_ret, 6)
            report.volatility = round(vol * np.sqrt(252), 6)
            std_ex = float(np.std(excess, ddof=1)) if len(excess) >= 2 else 0.0
            report.sharpe_ratio = round(
                float(np.mean(excess) / std_ex * np.sqrt(252))
                if std_ex > 0 else 0.0, 4
            )

            # Sortino
            downside = excess[excess < 0]
            ds_std = float(np.std(downside, ddof=1)) if len(downside) >= 2 else 0.0
            if ds_std > 0:
                report.sortino_ratio = round(
                    float(np.mean(excess) / ds_std * np.sqrt(252)), 4
                )

            # Max drawdown
            running_max = np.maximum.accumulate(values)
            dd = (values - running_max) / np.where(running_max == 0, 1, running_max)
            report.max_drawdown = round(float(abs(np.min(dd))), 6)
            report.current_drawdown = round(float(abs(dd[-1])), 6)

    async def _fill_positions(self, report: PortfolioReport) -> None:
        """Fill current positions."""
        async with _get_session_factory()() as session:
            rows = await session.execute(
                text("""
                    SELECT symbol, exchange, side, quantity, avg_entry_price,
                           current_price, unrealized_pnl, realized_pnl, weight_pct
                    FROM positions
                    WHERE quantity > 0
                    ORDER BY weight_pct DESC
                """)
            )
            data = rows.fetchall()

        report.n_positions = len(data)
        report.positions = [
            {
                "symbol": r[0],
                "exchange": r[1],
                "side": r[2],
                "quantity": float(r[3]),
                "avg_entry": round(float(r[4]), 4),
                "current_price": round(float(r[5]), 4),
                "unrealized_pnl": round(float(r[6]), 2),
                "realized_pnl": round(float(r[7]), 2),
                "weight_pct": round(float(r[8]), 2),
            }
            for r in data
        ]

        # Cash from latest portfolio snapshot
        async with _get_session_factory()() as session:
            row = await session.execute(
                text("""
                    SELECT cash_inr, cash_usd, gross_leverage
                    FROM portfolio_snapshots
                    ORDER BY created_at DESC LIMIT 1
                """)
            )
            snap = row.fetchone()
        if snap:
            report.cash = round(float(snap[0] or 0) + float(snap[1] or 0), 2)
            report.gross_leverage = round(float(snap[2] or 0), 2)

    async def _fill_trades(
        self, report: PortfolioReport, start: datetime, end: datetime
    ) -> None:
        """Fill trade journal from fills."""
        async with _get_session_factory()() as session:
            rows = await session.execute(
                text("""
                    SELECT o.symbol, o.side, f.filled_qty, f.fill_price,
                           f.commission, f.slippage, f.filled_at, o.signal_id
                    FROM fills f
                    JOIN orders o ON o.id = f.order_id
                    WHERE f.filled_at >= :start
                    ORDER BY f.filled_at DESC
                """),
                {"start": start},
            )
            data = rows.fetchall()

        trades = []
        total_commission = 0.0

        for r in data:
            trade = {
                "symbol": r[0],
                "side": r[1],
                "quantity": float(r[2]),
                "price": round(float(r[3]), 4),
                "commission": round(float(r[4] or 0), 4),
                "slippage": round(float(r[5] or 0), 4),
                "filled_at": str(r[6]),
            }
            total_commission += trade["commission"]
            trades.append(trade)

        report.trades = trades
        report.total_trades = len(trades)
        report.total_commission = round(total_commission, 2)

    async def _fill_risk(self, report: PortfolioReport) -> None:
        """Fill latest risk metrics."""
        async with _get_session_factory()() as session:
            row = await session.execute(
                text("""
                    SELECT var_1d_95, var_1d_99, max_drawdown, current_drawdown
                    FROM risk_metrics
                    ORDER BY created_at DESC LIMIT 1
                """)
            )
            data = row.fetchone()

        if data:
            report.var_95 = round(float(data[0] or 0), 6)
            report.var_99 = round(float(data[1] or 0), 6)

    async def _fill_regime(self, report: PortfolioReport) -> None:
        """Fill current regime context."""
        async with _get_session_factory()() as session:
            rows = await session.execute(
                text("""
                    SELECT market_scope, regime, confidence
                    FROM regime_states
                    WHERE id IN (
                        SELECT id FROM regime_states
                        GROUP BY market_scope
                        HAVING created_at = MAX(created_at)
                    )
                """)
            )
            data = rows.fetchall()

        report.regime_summary = {
            r[0]: {"regime": r[1], "confidence": round(float(r[2] or 0), 4)}
            for r in data
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_rich_text(self, report: PortfolioReport) -> str:
        """Format report as Rich terminal markup."""
        lines = [
            f"[bold cyan]{'=' * 60}[/]",
            f"[bold cyan]  Portfolio Report ({report.report_type.upper()})[/]",
            f"[bold cyan]{'=' * 60}[/]",
            f"  Period: {report.period_start[:10]} → {report.period_end[:10]}",
            f"  Generated: {report.generated_at[:19]}",
            "",
            "[bold]Performance:[/]",
            f"  Total Return:       {report.total_return:+.2%}",
            f"  Annualized Return:  {report.annualized_return:+.2%}",
            f"  Sharpe Ratio:       {report.sharpe_ratio:.4f}",
            f"  Sortino Ratio:      {report.sortino_ratio:.4f}",
            f"  Volatility:         {report.volatility:.2%}",
            f"  Max Drawdown:       {report.max_drawdown:.2%}",
            "",
            "[bold]Portfolio:[/]",
            f"  Value:              ${report.portfolio_value:,.2f}",
            f"  Cash:               ${report.cash:,.2f}",
            f"  Positions:          {report.n_positions}",
            f"  Gross Leverage:     {report.gross_leverage:.2f}x",
            "",
            "[bold]Trading:[/]",
            f"  Total Trades:       {report.total_trades}",
            f"  Total Commission:   ${report.total_commission:,.2f}",
            "",
            "[bold]Risk:[/]",
            f"  VaR (95%):          {report.var_95:.4f}",
            f"  VaR (99%):          {report.var_99:.4f}",
            f"  Current Drawdown:   {report.current_drawdown:.2%}",
        ]

        if report.regime_summary:
            lines.append("")
            lines.append("[bold]Market Regimes:[/]")
            for scope, info in report.regime_summary.items():
                lines.append(
                    f"  {scope:8s}  {info['regime']:16s}  conf={info['confidence']:.1%}"
                )

        if report.positions:
            lines.append("")
            lines.append("[bold]Positions:[/]")
            lines.append(
                f"  {'Symbol':16s} {'Side':6s} {'Qty':>10s} "
                f"{'Entry':>10s} {'Current':>10s} {'PnL':>12s}"
            )
            for p in report.positions[:15]:
                color = "green" if p["unrealized_pnl"] >= 0 else "red"
                lines.append(
                    f"  {p['symbol']:16s} {p['side']:6s} {p['quantity']:10.2f} "
                    f"{p['avg_entry']:10.2f} {p['current_price']:10.2f} "
                    f"[{color}]{p['unrealized_pnl']:12.2f}[/]"
                )

        return "\n".join(lines)

    def to_csv(self, report: PortfolioReport) -> str:
        """Export report trades to CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["Horizon Capital Portfolio Report"])
        writer.writerow([f"Period: {report.period_start} to {report.period_end}"])
        writer.writerow([])

        # Performance summary
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Total Return", f"{report.total_return:.6f}"])
        writer.writerow(["Annualized Return", f"{report.annualized_return:.6f}"])
        writer.writerow(["Sharpe Ratio", f"{report.sharpe_ratio:.4f}"])
        writer.writerow(["Sortino Ratio", f"{report.sortino_ratio:.4f}"])
        writer.writerow(["Max Drawdown", f"{report.max_drawdown:.6f}"])
        writer.writerow(["Portfolio Value", f"{report.portfolio_value:.2f}"])
        writer.writerow(["Total Trades", report.total_trades])
        writer.writerow([])

        # Positions
        if report.positions:
            writer.writerow([
                "Symbol", "Side", "Quantity", "Avg Entry",
                "Current Price", "Unrealized PnL", "Weight %",
            ])
            for p in report.positions:
                writer.writerow([
                    p["symbol"], p["side"], p["quantity"],
                    p["avg_entry"], p["current_price"],
                    p["unrealized_pnl"], p["weight_pct"],
                ])
            writer.writerow([])

        # Trades
        if report.trades:
            writer.writerow(["Symbol", "Side", "Quantity", "Price", "Commission", "Filled At"])
            for t in report.trades:
                writer.writerow([
                    t["symbol"], t["side"], t["quantity"],
                    t["price"], t["commission"], t["filled_at"],
                ])

        return output.getvalue()

    async def export_to_file(
        self,
        report: PortfolioReport,
        directory: str | None = None,
        fmt: str = "csv",
    ) -> str:
        """Export report to file. Returns the file path."""
        import os
        data_dir = Path(
            directory
            or os.getenv("HORIZON_DATA_DIR", Path.home() / ".horizon-capital")
        ) / "reports"
        data_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{report.report_type}_{timestamp}.{fmt}"
        filepath = data_dir / filename

        if fmt == "csv":
            content = self.to_csv(report)
            filepath.write_text(content, encoding="utf-8")
        elif fmt == "json":
            content = json.dumps({
                "report_id": report.report_id,
                "report_type": report.report_type,
                "period_start": report.period_start,
                "period_end": report.period_end,
                "total_return": report.total_return,
                "sharpe_ratio": report.sharpe_ratio,
                "portfolio_value": report.portfolio_value,
                "positions": report.positions,
                "trades": report.trades,
            }, indent=2)
            filepath.write_text(content, encoding="utf-8")

        logger.info("report_exported", path=str(filepath), format=fmt)
        return str(filepath)
