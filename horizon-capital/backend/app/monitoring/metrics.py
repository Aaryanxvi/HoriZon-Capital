"""Prometheus-compatible metrics exporter.

Exposes system metrics in Prometheus text format for Grafana dashboards.
Tracks PnL, agent health, latency, order counts, and risk metrics.

No external dependency required — generates Prometheus text format directly.
For production, can optionally use prometheus_client library.
"""

from __future__ import annotations

import time
from collections import defaultdict

from app.core.logging import get_logger

logger = get_logger("monitoring.metrics")


class MetricValue:
    """A single metric with labels."""

    __slots__ = ("name", "value", "labels", "metric_type", "help_text", "timestamp")

    def __init__(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        metric_type: str = "gauge",
        help_text: str = "",
    ) -> None:
        self.name = name
        self.value = value
        self.labels = labels or {}
        self.metric_type = metric_type
        self.help_text = help_text
        self.timestamp = time.time()


class PrometheusMetrics:
    """Collect and export metrics in Prometheus text exposition format.

    Usage::

        metrics = PrometheusMetrics()
        metrics.set_gauge("horizon_portfolio_value", 1_000_000, {"currency": "USD"})
        metrics.inc_counter("horizon_orders_total", {"side": "BUY", "broker": "ALPACA"})

        # Export for scraping
        text = metrics.export()
    """

    def __init__(self) -> None:
        self._gauges: dict[str, MetricValue] = {}
        self._counters: dict[str, float] = defaultdict(float)
        self._counter_labels: dict[str, dict[str, str]] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Gauge (point-in-time value)
    # ------------------------------------------------------------------

    def set_gauge(
        self, name: str, value: float,
        labels: dict[str, str] | None = None,
        help_text: str = "",
    ) -> None:
        """Set a gauge metric to a specific value."""
        key = self._label_key(name, labels)
        self._gauges[key] = MetricValue(name, value, labels, "gauge", help_text)
        if help_text:
            self._help[name] = help_text
        self._types[name] = "gauge"

    # ------------------------------------------------------------------
    # Counter (monotonically increasing)
    # ------------------------------------------------------------------

    def inc_counter(
        self, name: str,
        labels: dict[str, str] | None = None,
        amount: float = 1.0,
        help_text: str = "",
    ) -> None:
        """Increment a counter metric."""
        key = self._label_key(name, labels)
        self._counters[key] += amount
        self._counter_labels[key] = labels or {}
        if help_text:
            self._help[name] = help_text
        self._types[name] = "counter"

    # ------------------------------------------------------------------
    # Histogram (for latency tracking)
    # ------------------------------------------------------------------

    def observe_histogram(
        self, name: str, value: float,
        labels: dict[str, str] | None = None,
        help_text: str = "",
    ) -> None:
        """Record an observation in a histogram."""
        key = self._label_key(name, labels)
        self._histograms[key].append(value)
        # Keep only last 1000 observations
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-1000:]
        if help_text:
            self._help[name] = help_text
        self._types[name] = "histogram"

    # ------------------------------------------------------------------
    # Convenience methods for Horizon Capital metrics
    # ------------------------------------------------------------------

    def record_portfolio_value(self, value: float, currency: str = "USD") -> None:
        self.set_gauge(
            "horizon_portfolio_value", value,
            {"currency": currency},
            "Current portfolio value",
        )

    def record_pnl(self, realized: float, unrealized: float) -> None:
        self.set_gauge("horizon_pnl_realized", realized, help_text="Realized PnL")
        self.set_gauge("horizon_pnl_unrealized", unrealized, help_text="Unrealized PnL")

    def record_order(self, side: str, broker: str, status: str) -> None:
        self.inc_counter(
            "horizon_orders_total",
            {"side": side, "broker": broker, "status": status},
            help_text="Total orders processed",
        )

    def record_agent_health(self, agent_id: str, healthy: bool) -> None:
        self.set_gauge(
            "horizon_agent_health",
            1.0 if healthy else 0.0,
            {"agent_id": agent_id},
            "Agent health status (1=healthy, 0=unhealthy)",
        )

    def record_debate_latency(self, latency_seconds: float) -> None:
        self.observe_histogram(
            "horizon_debate_latency_seconds", latency_seconds,
            help_text="Debate execution latency",
        )

    def record_api_latency(self, service: str, latency_seconds: float) -> None:
        self.observe_histogram(
            "horizon_api_latency_seconds", latency_seconds,
            {"service": service},
            "External API call latency",
        )

    def record_risk_metrics(self, var_pct: float, drawdown_pct: float, leverage: float) -> None:
        self.set_gauge("horizon_var_pct", var_pct, help_text="Value at Risk %")
        self.set_gauge("horizon_drawdown_pct", drawdown_pct, help_text="Current drawdown %")
        self.set_gauge("horizon_leverage", leverage, help_text="Current portfolio leverage")

    def record_kill_switch(self, active: bool) -> None:
        self.set_gauge(
            "horizon_kill_switch_active",
            1.0 if active else 0.0,
            help_text="Kill switch status (1=active, 0=inactive)",
        )

    # ------------------------------------------------------------------
    # Export in Prometheus text format
    # ------------------------------------------------------------------

    def export(self) -> str:
        """Export all metrics in Prometheus text exposition format.

        Format: https://prometheus.io/docs/instrumenting/exposition_formats/
        """
        lines: list[str] = []
        seen_names: set[str] = set()

        # Gauges
        for key, mv in self._gauges.items():
            if mv.name not in seen_names:
                if mv.name in self._help:
                    lines.append(f"# HELP {mv.name} {self._help[mv.name]}")
                lines.append(f"# TYPE {mv.name} gauge")
                seen_names.add(mv.name)
            label_str = self._format_labels(mv.labels)
            lines.append(f"{mv.name}{label_str} {mv.value}")

        # Counters
        counter_names: set[str] = set()
        for key, value in self._counters.items():
            name = key.split("{")[0] if "{" in key else key
            # Extract base name
            base_name = name
            for cn in self._types:
                if key.startswith(cn):
                    base_name = cn
                    break

            if base_name not in counter_names:
                if base_name in self._help:
                    lines.append(f"# HELP {base_name} {self._help[base_name]}")
                lines.append(f"# TYPE {base_name} counter")
                counter_names.add(base_name)

            labels = self._counter_labels.get(key, {})
            label_str = self._format_labels(labels)
            lines.append(f"{base_name}{label_str} {value}")

        # Histograms (simplified: export sum, count, and quantiles)
        for key, observations in self._histograms.items():
            base_name = key.split("{")[0] if "{" in key else key
            for hn in self._types:
                if key.startswith(hn):
                    base_name = hn
                    break

            if observations:
                import numpy as np
                arr = np.array(observations)
                lines.append(f"# HELP {base_name} {self._help.get(base_name, '')}")
                lines.append(f"# TYPE {base_name} summary")
                lines.append(f'{base_name}_count {len(observations)}')
                lines.append(f'{base_name}_sum {float(np.sum(arr)):.6f}')
                for q in [0.5, 0.9, 0.99]:
                    lines.append(
                        f'{base_name}{{quantile="{q}"}} {float(np.percentile(arr, q * 100)):.6f}'
                    )

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label_key(name: str, labels: dict[str, str] | None) -> str:
        """Create a unique key from name + labels."""
        if not labels:
            return name
        sorted_labels = sorted(labels.items())
        label_parts = ",".join(f'{k}="{v}"' for k, v in sorted_labels)
        return f"{name}{{{label_parts}}}"

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        """Format labels for Prometheus text output."""
        if not labels:
            return ""
        parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{{{parts}}}"


# Module-level singleton
metrics = PrometheusMetrics()
