"""Adaptive order splitting: TWAP, VWAP, and Almgren-Chriss optimal execution.

Splits large orders into smaller child orders to minimize market impact,
scheduling them across time intervals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from app.core.logging import get_logger

logger = get_logger("execution.order_splitter")


@dataclass
class ChildOrder:
    """A single child order in an execution schedule."""

    slice_index: int
    quantity: float
    scheduled_time: str  # ISO format
    order_type: str = "MARKET"  # MARKET or LIMIT
    limit_price: float | None = None
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED


@dataclass
class ExecutionSchedule:
    """Full execution schedule for a parent order."""

    parent_order_id: str
    symbol: str
    side: str
    total_quantity: float
    algorithm: str  # "TWAP", "VWAP", "ALMGREN_CHRISS"
    n_slices: int
    child_orders: list[ChildOrder] = field(default_factory=list)
    estimated_impact_pct: float = 0.0
    created_at: str = ""


class OrderSplitter:
    """Splits large orders into optimally-scheduled child orders.

    Three algorithms:

    1. **TWAP** — Time-Weighted Average Price. Splits quantity equally across
       N time intervals. Simple, transparent, widely used as benchmark.

    2. **VWAP** — Volume-Weighted Average Price. Shapes the schedule to match
       historical intraday volume profile, executing more during high-volume
       periods.

    3. **Almgren-Chriss optimal** — Minimizes expected cost + risk penalty.
       Front-loads execution when urgency (risk aversion) is high; distributes
       evenly when patient.
    """

    # Default intraday volume profile (US equities, hourly buckets 9:30-16:00)
    # U-shaped: high at open, low at midday, high at close
    _DEFAULT_VOLUME_PROFILE = np.array([
        0.18, 0.12, 0.08, 0.07, 0.07, 0.08, 0.10, 0.12, 0.18,
    ])

    def __init__(
        self,
        daily_volume: float = 1_000_000,
        volatility: float = 0.02,
        risk_aversion: float = 1e-6,
    ) -> None:
        """
        Parameters
        ----------
        daily_volume:
            Average daily volume in shares.
        volatility:
            Daily volatility as decimal (0.02 = 2%).
        risk_aversion:
            Lambda parameter for Almgren-Chriss. Higher = more urgency
            to execute quickly (front-loads). Lower = patient execution.
        """
        self.daily_volume = daily_volume
        self.volatility = volatility
        self.risk_aversion = risk_aversion

    # ------------------------------------------------------------------
    # TWAP — Time-Weighted Average Price
    # ------------------------------------------------------------------

    def twap(
        self,
        parent_order_id: str,
        symbol: str,
        side: str,
        total_quantity: float,
        n_slices: int = 10,
        interval_seconds: int = 60,
        start_time: datetime | None = None,
    ) -> ExecutionSchedule:
        """Generate a TWAP schedule: equal-sized slices at regular intervals."""
        start = start_time or datetime.now(UTC)
        qty_per_slice = total_quantity / n_slices

        children = []
        for i in range(n_slices):
            scheduled = start + timedelta(seconds=i * interval_seconds)
            children.append(ChildOrder(
                slice_index=i,
                quantity=round(qty_per_slice, 4),
                scheduled_time=scheduled.isoformat(),
            ))

        participation = total_quantity / self.daily_volume
        estimated_impact = self._estimate_impact_pct(participation, n_slices)

        schedule = ExecutionSchedule(
            parent_order_id=parent_order_id,
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            algorithm="TWAP",
            n_slices=n_slices,
            child_orders=children,
            estimated_impact_pct=round(estimated_impact, 6),
            created_at=start.isoformat(),
        )

        logger.info(
            "twap_schedule_created",
            symbol=symbol, slices=n_slices,
            qty_per_slice=round(qty_per_slice, 2),
            impact_pct=schedule.estimated_impact_pct,
        )
        return schedule

    # ------------------------------------------------------------------
    # VWAP — Volume-Weighted Average Price
    # ------------------------------------------------------------------

    def vwap(
        self,
        parent_order_id: str,
        symbol: str,
        side: str,
        total_quantity: float,
        n_slices: int = 9,
        interval_seconds: int = 60,
        volume_profile: np.ndarray | None = None,
        start_time: datetime | None = None,
    ) -> ExecutionSchedule:
        """Generate a VWAP schedule: shaped by intraday volume profile."""
        start = start_time or datetime.now(UTC)
        profile = volume_profile if volume_profile is not None else self._DEFAULT_VOLUME_PROFILE

        # Normalize and interpolate to n_slices
        if len(profile) != n_slices:
            x_old = np.linspace(0, 1, len(profile))
            x_new = np.linspace(0, 1, n_slices)
            profile = np.interp(x_new, x_old, profile)

        profile = profile / profile.sum()  # Normalize to sum=1

        children = []
        for i in range(n_slices):
            qty = total_quantity * profile[i]
            scheduled = start + timedelta(seconds=i * interval_seconds)
            children.append(ChildOrder(
                slice_index=i,
                quantity=round(qty, 4),
                scheduled_time=scheduled.isoformat(),
            ))

        participation = total_quantity / self.daily_volume
        estimated_impact = self._estimate_impact_pct(participation, n_slices)

        schedule = ExecutionSchedule(
            parent_order_id=parent_order_id,
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            algorithm="VWAP",
            n_slices=n_slices,
            child_orders=children,
            estimated_impact_pct=round(estimated_impact, 6),
            created_at=start.isoformat(),
        )

        logger.info(
            "vwap_schedule_created",
            symbol=symbol, slices=n_slices,
            impact_pct=schedule.estimated_impact_pct,
        )
        return schedule

    # ------------------------------------------------------------------
    # Almgren-Chriss Optimal Execution
    # ------------------------------------------------------------------

    def almgren_chriss(
        self,
        parent_order_id: str,
        symbol: str,
        side: str,
        total_quantity: float,
        n_slices: int = 10,
        interval_seconds: int = 60,
        start_time: datetime | None = None,
    ) -> ExecutionSchedule:
        """Generate an Almgren-Chriss optimal execution schedule.

        The optimal trajectory minimizes E[cost] + lambda * Var[cost].
        Higher lambda front-loads execution.

        The optimal trajectory is:

            x_j = X * sinh(kappa * (T - t_j)) / sinh(kappa * T)

        where kappa = sqrt(lambda * sigma^2 / eta) is the urgency parameter,
        T = total time, X = total quantity, eta = temporary impact coefficient.
        """
        start = start_time or datetime.now(UTC)
        X = total_quantity  # noqa: N806
        T = n_slices  # Normalized time units  # noqa: N806

        # Almgren-Chriss parameters
        sigma = self.volatility
        eta = 0.142  # Temporary impact coefficient (calibrated for liquid equities)
        lam = self.risk_aversion

        # Urgency parameter kappa
        kappa_sq = lam * sigma ** 2 / eta if eta > 0 else 0.01
        kappa = math.sqrt(max(kappa_sq, 1e-10))

        # Optimal remaining holdings at each time step
        sinh_kT = math.sinh(kappa * T) if kappa * T < 100 else 1e30  # noqa: N806
        if sinh_kT == 0:
            sinh_kT = 1e-10  # noqa: N806

        holdings = []
        for j in range(n_slices + 1):
            t_j = j
            remaining = X * math.sinh(kappa * (T - t_j)) / sinh_kT
            holdings.append(max(remaining, 0))

        # Child order quantities = difference in holdings
        children = []
        for i in range(n_slices):
            qty = holdings[i] - holdings[i + 1]
            scheduled = start + timedelta(seconds=i * interval_seconds)
            children.append(ChildOrder(
                slice_index=i,
                quantity=round(max(qty, 0), 4),
                scheduled_time=scheduled.isoformat(),
            ))

        # Estimate total impact
        participation = total_quantity / self.daily_volume
        estimated_impact = self._estimate_impact_pct(participation, n_slices)

        schedule = ExecutionSchedule(
            parent_order_id=parent_order_id,
            symbol=symbol,
            side=side,
            total_quantity=total_quantity,
            algorithm="ALMGREN_CHRISS",
            n_slices=n_slices,
            child_orders=children,
            estimated_impact_pct=round(estimated_impact, 6),
            created_at=start.isoformat(),
        )

        logger.info(
            "almgren_chriss_schedule_created",
            symbol=symbol, slices=n_slices,
            kappa=round(kappa, 6),
            impact_pct=schedule.estimated_impact_pct,
        )
        return schedule

    # ------------------------------------------------------------------
    # Auto-select algorithm based on order size
    # ------------------------------------------------------------------

    def create_schedule(
        self,
        parent_order_id: str,
        symbol: str,
        side: str,
        total_quantity: float,
        algorithm: str = "auto",
        n_slices: int = 10,
        interval_seconds: int = 60,
        start_time: datetime | None = None,
    ) -> ExecutionSchedule:
        """Create an execution schedule, auto-selecting algorithm if needed.

        Auto-selection logic:
        - participation < 1%: no splitting needed (single order)
        - participation 1-5%: TWAP
        - participation 5-15%: VWAP
        - participation > 15%: Almgren-Chriss (impact-aware)
        """
        participation = total_quantity / self.daily_volume if self.daily_volume > 0 else 1.0

        if algorithm == "auto":
            if participation < 0.01:
                algorithm = "TWAP"
                n_slices = 1
            elif participation < 0.05:
                algorithm = "TWAP"
            elif participation < 0.15:
                algorithm = "VWAP"
            else:
                algorithm = "ALMGREN_CHRISS"

        if algorithm == "TWAP":
            return self.twap(parent_order_id, symbol, side, total_quantity,
                             n_slices, interval_seconds, start_time)
        elif algorithm == "VWAP":
            return self.vwap(parent_order_id, symbol, side, total_quantity,
                             n_slices, interval_seconds, start_time=start_time)
        elif algorithm == "ALMGREN_CHRISS":
            return self.almgren_chriss(parent_order_id, symbol, side,
                                       total_quantity, n_slices, interval_seconds,
                                       start_time)
        else:
            return self.twap(parent_order_id, symbol, side, total_quantity,
                             n_slices, interval_seconds, start_time)

    # ------------------------------------------------------------------
    # Impact estimation
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_impact_pct(participation: float, n_slices: int) -> float:
        """Estimate total market impact as percentage of price.

        Uses simplified Almgren-Chriss: impact scales with participation^0.6.
        Splitting across N slices reduces per-slice participation.
        """
        if participation <= 0 or n_slices <= 0:
            return 0.0
        per_slice = participation / n_slices
        # Temporary impact per slice: epsilon + eta * |per_slice|^gamma
        epsilon = 0.0005  # Half-spread (5 bps)
        eta = 0.142
        gamma = 0.6
        per_slice_impact = epsilon + eta * (per_slice ** gamma)
        # Total impact ≈ permanent (one-time) + avg temporary
        permanent = 0.142 * (participation ** 0.314)
        total = permanent + per_slice_impact
        return total
