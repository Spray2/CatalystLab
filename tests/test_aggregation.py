"""Tests for catalystlab.eventstudy.aggregation (W2 T4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from catalystlab.eventstudy.aggregation import (
    AGGREGATION_COLUMNS,
    _hit,
    aggregate_event_metrics,
)


def _metrics_row(
    ticker: str,
    event_date: str,
    event_type: str,
    event_magnitude: float,
    holding_window: int,
    beta: float,
    n_obs: int,
    car: float,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "event_date": pd.Timestamp(event_date),
        "event_type": event_type,
        "event_magnitude": event_magnitude,
        "holding_window": holding_window,
        "beta": beta,
        "n_obs": n_obs,
        "car": car,
    }


# ---------- _hit ----------


def test_hit_positive_match() -> None:
    assert _hit(magnitude=2.0, car=0.01) is True


def test_hit_negative_match() -> None:
    assert _hit(magnitude=-1.0, car=-0.005) is True


def test_hit_sign_mismatch() -> None:
    assert _hit(magnitude=2.0, car=-0.01) is False


def test_hit_nan_returns_none() -> None:
    assert _hit(magnitude=float("nan"), car=0.01) is None
    assert _hit(magnitude=2.0, car=float("nan")) is None


def test_hit_zero_returns_none() -> None:
    assert _hit(magnitude=0.0, car=0.01) is None
    assert _hit(magnitude=2.0, car=0.0) is None


# ---------- aggregate_event_metrics ----------


def test_aggregate_empty_returns_empty_with_schema() -> None:
    out = aggregate_event_metrics(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == AGGREGATION_COLUMNS


def test_aggregate_missing_columns_raises() -> None:
    bad = pd.DataFrame({"foo": [1]})
    with pytest.raises(ValueError, match="missing required columns"):
        aggregate_event_metrics(bad)


def test_aggregate_basic_three_events_one_window() -> None:
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "B", 1.0, 5, 1.2, 5, 0.01),
            _metrics_row("CEG", "2024-02-02", "B", 1.0, 5, 0.8, 5, 0.02),
            _metrics_row("VST", "2024-03-02", "B", 1.0, 5, 1.0, 5, -0.005),
        ]
    )
    out = aggregate_event_metrics(metrics, cost_bps_round_trip=0.0)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["event_type"] == "B"
    assert row["holding_window"] == 5
    assert row["n_events"] == 3
    assert row["n_valid"] == 3
    assert row["mean_car_gross"] == pytest.approx((0.01 + 0.02 - 0.005) / 3)
    assert row["mean_car_net"] == pytest.approx(row["mean_car_gross"])
    # 2 hits (positive CAR with positive magnitude), 1 miss (negative CAR)
    assert row["hit_rate"] == pytest.approx(2 / 3)


def test_aggregate_subtracts_round_trip_cost() -> None:
    """cost_bps_round_trip=95.5 → mean_car_net = mean_car_gross - 0.00955."""
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "B", 1.0, 5, 1.0, 5, 0.05),
            _metrics_row("CEG", "2024-02-02", "B", 1.0, 5, 1.0, 5, 0.03),
        ]
    )
    out = aggregate_event_metrics(metrics, cost_bps_round_trip=95.5)
    row = out.iloc[0]
    assert row["mean_car_gross"] == pytest.approx(0.04)
    assert row["mean_car_net"] == pytest.approx(0.04 - 0.00955)


def test_aggregate_excludes_nan_car_from_stats() -> None:
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "A", 1.5, 5, 1.0, 5, 0.01),
            _metrics_row("CEG", "2024-02-02", "A", 2.0, 5, float("nan"), 0, float("nan")),
        ]
    )
    out = aggregate_event_metrics(metrics)
    row = out.iloc[0]
    assert row["n_events"] == 2
    assert row["n_valid"] == 1
    assert row["mean_car_gross"] == pytest.approx(0.01)
    assert pd.isna(row["std_car"])  # only 1 valid → ddof=1 → NaN
    assert row["hit_rate"] == pytest.approx(1.0)  # the one valid event hits


def test_aggregate_all_nan_yields_nan_metrics() -> None:
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "B", 1.0, 5, float("nan"), 0, float("nan")),
            _metrics_row("CEG", "2024-02-02", "B", 1.0, 5, float("nan"), 0, float("nan")),
        ]
    )
    out = aggregate_event_metrics(metrics)
    row = out.iloc[0]
    assert row["n_events"] == 2
    assert row["n_valid"] == 0
    assert pd.isna(row["mean_car_gross"])
    assert pd.isna(row["mean_car_net"])
    assert pd.isna(row["std_car"])
    assert pd.isna(row["hit_rate"])


def test_aggregate_multiple_categories_and_windows() -> None:
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "A", 1.5, 1, 1.0, 1, 0.005),
            _metrics_row("VRT", "2024-01-02", "A", 1.5, 5, 1.0, 5, 0.01),
            _metrics_row("CEG", "2024-02-02", "A", -1.5, 1, 1.0, 1, -0.004),
            _metrics_row("CEG", "2024-02-02", "A", -1.5, 5, 1.0, 5, -0.012),
            _metrics_row("VST", "2024-03-02", "B", 1.0, 5, 1.0, 5, 0.02),
        ]
    )
    out = aggregate_event_metrics(metrics)
    # 2 (A,1) + (A,5) + (B,5) = 3 groups
    assert len(out) == 3
    # Sorted by (event_type, holding_window)
    assert out["event_type"].tolist() == ["A", "A", "B"]
    assert out["holding_window"].tolist() == [1, 5, 5]
    # All A events are sign-coherent (SUE>0 → CAR>0; SUE<0 → CAR<0).
    assert (out[out["event_type"] == "A"]["hit_rate"] == 1.0).all()


def test_aggregate_hit_rate_excludes_zero_magnitude() -> None:
    """Zero-magnitude events have no signed thesis → not counted in hit_rate."""
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "B", 0.0, 5, 1.0, 5, 0.01),  # excluded
            _metrics_row("CEG", "2024-02-02", "B", 1.0, 5, 1.0, 5, 0.02),  # hit
            _metrics_row("VST", "2024-03-02", "B", 1.0, 5, 1.0, 5, -0.005),  # miss
        ]
    )
    out = aggregate_event_metrics(metrics)
    row = out.iloc[0]
    # n_events / n_valid still count all 3 (CAR is non-NaN)
    assert row["n_valid"] == 3
    # hit_rate computed over 2 valid signed-magnitude rows
    assert row["hit_rate"] == pytest.approx(0.5)


def test_aggregate_std_uses_ddof_one() -> None:
    metrics = pd.DataFrame(
        [
            _metrics_row("VRT", "2024-01-02", "B", 1.0, 5, 1.0, 5, 0.01),
            _metrics_row("CEG", "2024-02-02", "B", 1.0, 5, 1.0, 5, 0.03),
            _metrics_row("VST", "2024-03-02", "B", 1.0, 5, 1.0, 5, 0.05),
        ]
    )
    out = aggregate_event_metrics(metrics)
    row = out.iloc[0]
    # ddof=1 std of [0.01, 0.03, 0.05] = 0.02
    assert row["std_car"] == pytest.approx(0.02, abs=1e-12)


def test_aggregate_output_schema_and_dtypes() -> None:
    metrics = pd.DataFrame(
        [_metrics_row("VRT", "2024-01-02", "B", 1.0, 5, 1.0, 5, 0.01)]
    )
    out = aggregate_event_metrics(metrics)
    assert list(out.columns) == AGGREGATION_COLUMNS
    assert out["holding_window"].dtype == np.int64 or out["holding_window"].dtype == int
