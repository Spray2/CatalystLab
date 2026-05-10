"""Tests for catalystlab.ingestion.costs.

Covers the prereg §5 cost model (Interpretation B, round-trip totals):
deterministic happy-path, monotonicity in position size, and the §5.2
sanity bound (cost on €1000 must land in 75-100 bps).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from catalystlab.config.schemas import CostModel
from catalystlab.ingestion.costs import (
    BPS_PER_RATIO,
    compute_cost_bps,
    compute_cost_eur,
)


def _prereg_cost() -> CostModel:
    """Prereg §5 reference parameters."""
    return CostModel(
        commission_per_execution_eur=3.65,
        spread_round_trip_bps=7.5,
        fx_round_trip_bps=15.0,
        default_position_size_eur=1000.0,
    )


def test_prereg_position_lands_in_section_5_2_range() -> None:
    cost = _prereg_cost()
    bps = compute_cost_bps(cost)
    # Prereg §5.2 declared range for €1000 round-trip cost.
    assert 75.0 <= bps <= 100.0
    # Hand math: 73 + 7.5 + 15 = 95.5
    assert bps == pytest.approx(95.5, abs=1e-6)


def test_default_position_used_when_unspecified() -> None:
    cost = _prereg_cost()
    assert compute_cost_bps(cost) == compute_cost_bps(cost, 1000.0)


def test_cost_eur_consistency() -> None:
    cost = _prereg_cost()
    bps = compute_cost_bps(cost, 1000.0)
    eur = compute_cost_eur(cost, 1000.0)
    assert eur == pytest.approx(bps * 1000.0 / BPS_PER_RATIO, rel=1e-9)


def test_cost_lower_bound_is_spread_plus_fx() -> None:
    """As P → ∞, commission term → 0, leaving only spread + fx."""
    cost = _prereg_cost()
    bps_huge = compute_cost_bps(cost, 1_000_000_000.0)
    assert bps_huge == pytest.approx(
        cost.spread_round_trip_bps + cost.fx_round_trip_bps,
        abs=1e-3,
    )


def test_zero_or_negative_position_raises() -> None:
    cost = _prereg_cost()
    with pytest.raises(ValueError, match="position_size_eur"):
        compute_cost_bps(cost, 0.0)
    with pytest.raises(ValueError, match="position_size_eur"):
        compute_cost_bps(cost, -100.0)


def test_larger_position_decreases_cost_5k_vs_1k() -> None:
    cost = _prereg_cost()
    cost_1k = compute_cost_bps(cost, 1000.0)
    cost_5k = compute_cost_bps(cost, 5000.0)
    # Live-trading cap (€5k from prereg §10.1): expected lower per-bps cost.
    assert cost_5k < cost_1k


@given(
    p1=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False),
    p2=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False),
)
def test_cost_monotone_decreasing_in_position(p1: float, p2: float) -> None:
    """Hypothesis: cost_bps(P) is non-increasing in P (commission dilutes)."""
    cost = _prereg_cost()
    if p1 < p2:
        assert compute_cost_bps(cost, p1) >= compute_cost_bps(cost, p2)
    elif p1 > p2:
        assert compute_cost_bps(cost, p1) <= compute_cost_bps(cost, p2)
    else:
        assert compute_cost_bps(cost, p1) == compute_cost_bps(cost, p2)


@given(
    commission=st.floats(min_value=0.01, max_value=50.0, allow_nan=False),
    spread=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    fx=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    position=st.floats(min_value=100.0, max_value=10_000_000.0, allow_nan=False),
)
def test_cost_components_additive(
    commission: float, spread: float, fx: float, position: float
) -> None:
    """cost_bps decomposes as commission_bps + spread + fx exactly."""
    cost = CostModel(
        commission_per_execution_eur=commission,
        spread_round_trip_bps=spread,
        fx_round_trip_bps=fx,
        default_position_size_eur=position,
    )
    bps = compute_cost_bps(cost, position)
    expected_commission_bps = (commission * 2.0) / position * BPS_PER_RATIO
    assert bps == pytest.approx(expected_commission_bps + spread + fx, rel=1e-9)
