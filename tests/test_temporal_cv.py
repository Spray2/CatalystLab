"""Tests for catalystlab.stats.temporal_cv (W3 T4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from catalystlab.stats.temporal_cv import (
    DEFAULT_SPLIT_DATE,
    TEMPORAL_CV_COLUMNS,
    compute_temporal_decay,
)


def _row(et: str, hw: int, date: str, mag: float, car: float) -> dict[str, object]:
    return {
        "ticker": "X",
        "event_date": pd.Timestamp(date),
        "event_type": et,
        "event_magnitude": mag,
        "holding_window": hw,
        "beta": 1.0,
        "n_obs": hw,
        "car": car,
    }


def test_temporal_decay_empty_input_returns_empty() -> None:
    out = compute_temporal_decay(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == TEMPORAL_CV_COLUMNS


def test_temporal_decay_missing_columns_raises() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        compute_temporal_decay(pd.DataFrame([{"foo": 1}]))


def test_temporal_decay_split_correct() -> None:
    """Pre / post counts match the split date boundary."""
    rows = (
        [
            _row("A", 5, "2024-01-15", float(i), float(i) * 0.01)
            for i in range(1, 6)
        ]
        + [
            _row("A", 5, "2025-06-15", float(i), float(i) * 0.01)
            for i in range(1, 4)
        ]
    )
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics, split_date=pd.Timestamp("2025-01-01"))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["n_pre"] == 5
    assert row["n_post"] == 3


def test_temporal_decay_perfect_correlation_both_halves() -> None:
    """Perfect rank correlation in both halves -> decay = 0."""
    rows = (
        [
            _row("A", 5, "2024-01-15", float(i), float(i) * 0.01)
            for i in range(1, 8)
        ]
        + [
            _row("A", 5, "2025-06-15", float(i), float(i) * 0.005)
            for i in range(1, 8)
        ]
    )
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics)
    row = out.iloc[0]
    assert row["ic_pre"] == pytest.approx(1.0, abs=1e-12)
    assert row["ic_post"] == pytest.approx(1.0, abs=1e-12)
    assert row["decay"] == pytest.approx(0.0, abs=1e-12)


def test_temporal_decay_sign_flip() -> None:
    """Pre: positive correlation; Post: negative -> decay < 0."""
    rows = (
        [
            _row("A", 5, "2024-01-15", float(i), float(i) * 0.01)
            for i in range(1, 8)
        ]
        + [
            _row("A", 5, "2025-06-15", float(i), -float(i) * 0.01)
            for i in range(1, 8)
        ]
    )
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics)
    row = out.iloc[0]
    assert row["ic_pre"] == pytest.approx(1.0, abs=1e-12)
    assert row["ic_post"] == pytest.approx(-1.0, abs=1e-12)
    assert row["decay"] == pytest.approx(-2.0, abs=1e-12)


def test_temporal_decay_all_pre_yields_nan_post() -> None:
    """All events before split -> ic_post NaN -> decay NaN."""
    rows = [
        _row("A", 5, "2024-01-15", float(i), float(i) * 0.01) for i in range(1, 8)
    ]
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics)
    row = out.iloc[0]
    assert row["n_post"] == 0
    assert np.isnan(row["ic_post"])
    assert np.isnan(row["decay"])


def test_temporal_decay_split_boundary_inclusive_in_post() -> None:
    """Event exactly on split_date goes to 'post' (>= boundary)."""
    rows = [
        _row("A", 5, "2024-12-31", 1.0, 0.01),
        _row("A", 5, "2025-01-01", 2.0, 0.02),
        _row("A", 5, "2025-06-15", 3.0, 0.03),
    ]
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics, split_date=pd.Timestamp("2025-01-01"))
    row = out.iloc[0]
    assert row["n_pre"] == 1
    assert row["n_post"] == 2


def test_temporal_decay_default_split_is_2025_01_01() -> None:
    assert pd.Timestamp("2025-01-01") == DEFAULT_SPLIT_DATE


def test_temporal_decay_multiple_groups() -> None:
    rows = (
        [
            _row("A", 5, "2024-01-15", float(i), float(i) * 0.01)
            for i in range(1, 6)
        ]
        + [
            _row("A", 5, "2025-06-15", float(i), float(i) * 0.01)
            for i in range(1, 6)
        ]
        + [
            _row("B", 1, "2024-01-15", float(i), float(i) * 0.005)
            for i in range(1, 6)
        ]
        + [
            _row("B", 1, "2025-06-15", float(i), -float(i) * 0.005)
            for i in range(1, 6)
        ]
    )
    metrics = pd.DataFrame(rows)
    out = compute_temporal_decay(metrics)
    assert len(out) == 2
    a_row = out[out["event_type"] == "A"].iloc[0]
    b_row = out[out["event_type"] == "B"].iloc[0]
    assert a_row["decay"] == pytest.approx(0.0, abs=1e-12)
    assert b_row["decay"] == pytest.approx(-2.0, abs=1e-12)
