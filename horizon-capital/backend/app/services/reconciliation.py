"""Position reconciliation engine.

Compares internal position state against broker-reported positions and
detects discrepancies. Auto-resolves minor differences; queues material
discrepancies for CIO review.

Research references
-------------------
- ISDA 2013, "Portfolio Reconciliation in Practice" — formal matching
  pipeline: exact match on identifiers, fuzzy matching on attributes,
  confidence scoring for auto-match vs manual review.
- Klamecki 2023, "Using ML to Solve Data Reconciliation in Financial
  Services" — ML classification on feature vectors (amount delta, date
  offset, string similarity) achieves 95%+ precision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger("services.reconciliation")


@dataclass
class PositionMismatch:
    """A single position discrepancy between internal and broker state."""

    symbol: str
    exchange: str
    internal_qty: float
    broker_qty: float
    delta_qty: float
    internal_avg_price: float
    broker_avg_price: float
    delta_price: float
    severity: str  # "INFO", "WARNING", "CRITICAL"
    auto_resolved: bool = False
    resolution: str = ""
    timestamp: str = ""


@dataclass
class ReconciliationReport:
    """Full reconciliation report."""

    timestamp: str
    positions_checked: int
    matches: int
    mismatches: list[PositionMismatch] = field(default_factory=list)
    auto_resolved: int = 0
    needs_review: int = 0
    broker_name: str = ""


class ReconciliationEngine:
    """Compares internal positions vs broker and detects discrepancies.

    Tolerance thresholds (configurable):
    - Quantity: ±0.01 shares (fractional share rounding)
    - Price: ±0.5% (broker may report slightly different avg prices)

    Ref: ISDA 2013 — the standard three-pass reconciliation:
    1. Exact match on symbol + exchange
    2. Quantity comparison with tolerance
    3. Price comparison with tolerance
    """

    def __init__(
        self,
        qty_tolerance: float = 0.01,
        price_tolerance_pct: float = 0.005,
    ) -> None:
        self.qty_tolerance = qty_tolerance
        self.price_tolerance_pct = price_tolerance_pct

    def reconcile(
        self,
        internal_positions: list[dict[str, Any]],
        broker_positions: list[dict[str, Any]],
        broker_name: str = "UNKNOWN",
    ) -> ReconciliationReport:
        """Run reconciliation between internal and broker positions.

        Parameters
        ----------
        internal_positions:
            List of dicts with keys: symbol, exchange, quantity, avg_entry_price.
        broker_positions:
            List of dicts with keys: symbol, exchange, quantity, avg_price.
        broker_name:
            Name of the broker for reporting.

        Returns
        -------
        ReconciliationReport
        """
        now = datetime.now(UTC).isoformat()

        # Index broker positions by (symbol, exchange)
        broker_map: dict[tuple[str, str], dict] = {}
        for bp in broker_positions:
            key = (bp["symbol"], bp.get("exchange", ""))
            broker_map[key] = bp

        mismatches: list[PositionMismatch] = []
        matches = 0

        # Check each internal position against broker
        for ip in internal_positions:
            symbol = ip["symbol"]
            exchange = ip.get("exchange", "")
            key = (symbol, exchange)

            internal_qty = ip.get("quantity", 0.0)
            internal_price = ip.get("avg_entry_price", 0.0)

            bp = broker_map.pop(key, None)
            if bp is None:
                # Position exists internally but not at broker
                if abs(internal_qty) > self.qty_tolerance:
                    mismatches.append(PositionMismatch(
                        symbol=symbol, exchange=exchange,
                        internal_qty=internal_qty, broker_qty=0.0,
                        delta_qty=internal_qty,
                        internal_avg_price=internal_price, broker_avg_price=0.0,
                        delta_price=internal_price,
                        severity="CRITICAL",
                        resolution="Position missing at broker",
                        timestamp=now,
                    ))
                continue

            broker_qty = bp.get("quantity", bp.get("qty", 0.0))
            broker_price = bp.get("avg_price", bp.get("avg_entry_price", 0.0))

            delta_qty = internal_qty - broker_qty
            delta_price = internal_price - broker_price if broker_price else 0.0

            # Check quantity match
            qty_match = abs(delta_qty) <= self.qty_tolerance
            # Check price match
            price_match = True
            if broker_price > 0:
                price_match = abs(delta_price / broker_price) <= self.price_tolerance_pct

            if qty_match and price_match:
                matches += 1
            else:
                severity = "WARNING"
                auto_resolved = False
                resolution = ""

                if abs(delta_qty) <= self.qty_tolerance * 10:
                    # Minor rounding difference — auto-resolve
                    severity = "INFO"
                    auto_resolved = True
                    resolution = "Auto-resolved: fractional share rounding"
                elif abs(delta_qty) > internal_qty * 0.1:
                    severity = "CRITICAL"
                    resolution = "Material quantity discrepancy — CIO review required"

                mismatches.append(PositionMismatch(
                    symbol=symbol, exchange=exchange,
                    internal_qty=internal_qty, broker_qty=broker_qty,
                    delta_qty=round(delta_qty, 6),
                    internal_avg_price=internal_price,
                    broker_avg_price=broker_price,
                    delta_price=round(delta_price, 4),
                    severity=severity,
                    auto_resolved=auto_resolved,
                    resolution=resolution,
                    timestamp=now,
                ))

        # Broker has positions we don't track internally
        for key, bp in broker_map.items():
            broker_qty = bp.get("quantity", bp.get("qty", 0.0))
            if abs(broker_qty) > self.qty_tolerance:
                mismatches.append(PositionMismatch(
                    symbol=key[0], exchange=key[1],
                    internal_qty=0.0, broker_qty=broker_qty,
                    delta_qty=-broker_qty,
                    internal_avg_price=0.0,
                    broker_avg_price=bp.get("avg_price", 0.0),
                    delta_price=0.0,
                    severity="CRITICAL",
                    resolution="Position exists at broker but not internally",
                    timestamp=now,
                ))

        auto_resolved = sum(1 for m in mismatches if m.auto_resolved)
        needs_review = sum(1 for m in mismatches if not m.auto_resolved)

        report = ReconciliationReport(
            timestamp=now,
            positions_checked=len(internal_positions),
            matches=matches,
            mismatches=mismatches,
            auto_resolved=auto_resolved,
            needs_review=needs_review,
            broker_name=broker_name,
        )

        logger.info(
            "reconciliation_complete",
            broker=broker_name,
            checked=report.positions_checked,
            matches=matches,
            mismatches=len(mismatches),
            needs_review=needs_review,
        )

        return report
