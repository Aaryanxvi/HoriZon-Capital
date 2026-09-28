# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4635A8EBE552
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Report exporter — CSV export for backtest results and trade journals.

Exports backtest metrics, equity curves, trade lists, and journal entries
to CSV format for external analysis and record-keeping.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger("backtesting.exporter")


class ReportExporter:
    """Export backtest results and trade journals to CSV."""

    @staticmethod
    def metrics_to_csv(metrics: dict[str, Any]) -> str:
        """Export a metrics dict to CSV string (2-column: metric, value)."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["metric", "value"])
        for key, value in metrics.items():
            writer.writerow([key, value])
        return output.getvalue()

    @staticmethod
    def equity_curve_to_csv(
        equity_curve: list[float],
        timestamps: list[Any] | None = None,
    ) -> str:
        """Export equity curve to CSV with optional timestamps."""
        output = io.StringIO()
        writer = csv.writer(output)
        if timestamps:
            writer.writerow(["timestamp", "portfolio_value"])
            for ts, val in zip(timestamps, equity_curve):
                writer.writerow([str(ts), round(val, 2)])
        else:
            writer.writerow(["bar_index", "portfolio_value"])
            for i, val in enumerate(equity_curve):
                writer.writerow([i, round(val, 2)])
        return output.getvalue()

    @staticmethod
    def trades_to_csv(trades: list[dict]) -> str:
        """Export trade list to CSV."""
        if not trades:
            return "No trades\n"

        output = io.StringIO()
        # Use all keys from first trade as headers
        headers = list(trades[0].keys())
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade)
        return output.getvalue()

    @staticmethod
    def journal_to_csv(entries: list[dict]) -> str:
        """Export trade journal entries to CSV."""
        if not entries:
            return "No journal entries\n"

        output = io.StringIO()
        # Ordered columns for readability
        priority_cols = [
            "trade_id", "symbol", "side", "quantity", "price", "timestamp",
            "pnl", "pnl_pct", "strategy_name", "signal_strength",
            "regime", "regime_confidence", "sentiment_score",
            "debate_result", "debate_consensus",
            "portfolio_value_at_entry", "position_size_pct",
            "commission", "slippage", "holding_period_bars",
        ]
        # Include any extra keys not in priority list
        all_keys = set()
        for entry in entries:
            all_keys.update(entry.keys())
        extra = sorted(all_keys - set(priority_cols))
        headers = [c for c in priority_cols if c in all_keys] + extra

        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)
        return output.getvalue()

    @staticmethod
    def benchmark_to_csv(comparisons: list[dict]) -> str:
        """Export benchmark comparison results to CSV."""
        if not comparisons:
            return "No benchmark comparisons\n"

        output = io.StringIO()
        headers = list(comparisons[0].keys())
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for comp in comparisons:
            writer.writerow(comp)
        return output.getvalue()

    @staticmethod
    def monte_carlo_to_csv(mc_result: dict) -> str:
        """Export Monte Carlo simulation summary to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["statistic", "value"])

        # Exclude sample_paths from CSV (too large)
        for key, value in mc_result.items():
            if key == "sample_paths":
                writer.writerow([key, f"{len(value)} paths (omitted)"])
            else:
                writer.writerow([key, value])
        return output.getvalue()

    @classmethod
    def full_report_to_csv(
        cls,
        metrics: dict | None = None,
        equity_curve: list[float] | None = None,
        trades: list[dict] | None = None,
        journal_entries: list[dict] | None = None,
        benchmark_comparisons: list[dict] | None = None,
        monte_carlo: dict | None = None,
    ) -> dict[str, str]:
        """Generate a full report as a dict of filename -> CSV content.

        Returns a dict where keys are suggested filenames and values
        are CSV strings.
        """
        now = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        report: dict[str, str] = {}

        if metrics:
            report[f"metrics_{now}.csv"] = cls.metrics_to_csv(metrics)
        if equity_curve:
            report[f"equity_curve_{now}.csv"] = cls.equity_curve_to_csv(equity_curve)
        if trades:
            report[f"trades_{now}.csv"] = cls.trades_to_csv(trades)
        if journal_entries:
            report[f"trade_journal_{now}.csv"] = cls.journal_to_csv(journal_entries)
        if benchmark_comparisons:
            report[f"benchmark_{now}.csv"] = cls.benchmark_to_csv(benchmark_comparisons)
        if monte_carlo:
            report[f"monte_carlo_{now}.csv"] = cls.monte_carlo_to_csv(monte_carlo)

        logger.info("report_exported", n_files=len(report))
        return report

    @staticmethod
    def save_to_file(filepath: str, content: str) -> None:
        """Write CSV content to a file."""
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            f.write(content)
        logger.info("file_saved", path=filepath)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4635A8EBE552 - verify with scripts/authorship.py verify
