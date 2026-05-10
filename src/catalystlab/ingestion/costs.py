"""Layer 2 — Fineco round-trip cost model per pre-registration §5.

Implements Interpretation B (round-trip totals): the YAML fields
``spread_round_trip_bps`` and ``fx_round_trip_bps`` are already the
round-trip cost; only the commission needs to be doubled (one execution on
entry, one on exit).

Cost formula (round-trip, in bps of position size):

    cost_bps(P) = (commission_per_execution_eur * 2) / P * BPS_PER_RATIO
                  + spread_round_trip_bps
                  + fx_round_trip_bps

where P is the position size in EUR. Sanity check (prereg §5.2): with
P=€1000 the formula must land in the declared range 75-100 bps.
"""

from __future__ import annotations

from catalystlab.config.schemas import CostModel

BPS_PER_RATIO: int = 10_000


def compute_cost_bps(cost: CostModel, position_size_eur: float | None = None) -> float:
    """Round-trip cost in bps of the position size.

    Args:
        cost: validated `CostModel` instance (from `SectorConfig.costs`).
        position_size_eur: position size in EUR; defaults to
            ``cost.default_position_size_eur`` (prereg §5.1 worst-case).

    Returns:
        Total round-trip cost expressed in bps of the notional position.

    Raises:
        ValueError if ``position_size_eur <= 0``.
    """
    p = position_size_eur if position_size_eur is not None else cost.default_position_size_eur
    if p <= 0:
        raise ValueError(f"position_size_eur must be > 0, got {p}")

    commission_bps = (cost.commission_per_execution_eur * 2.0) / p * BPS_PER_RATIO
    return commission_bps + cost.spread_round_trip_bps + cost.fx_round_trip_bps


def compute_cost_eur(cost: CostModel, position_size_eur: float | None = None) -> float:
    """Round-trip cost in EUR — convenience wrapper around `compute_cost_bps`."""
    p = position_size_eur if position_size_eur is not None else cost.default_position_size_eur
    return compute_cost_bps(cost, p) * p / BPS_PER_RATIO
