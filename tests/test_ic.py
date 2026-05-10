"""Tests for catalystlab.eventstudy.ic (W2 T5)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from catalystlab.eventstudy.ic import IC_COLUMNS, _spearman_safe, compute_ic


def _metrics(rows: list[tuple]) -> pd.DataFrame:
    """Build a metrics DataFrame from (event_type, holding_window, magnitude, car) tuples."""
    return pd.DataFrame(
        [
            {
                "ticker": "X",
                "event_date": pd.Timestamp("2024-01-01"),
                "event_type": et,
                "event_magnitude": mag,
                "holding_window": hw,
                "beta": 1.0,
                "n_obs": hw,
                "car": car,
            }
            for et, hw, mag, car in rows
        ]
    )


# ---------- _spearman_safe ----------


def test_spearman_safe_perfect_positive_correlation() -> None:
    mag = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    car = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
    rho, p = _spearman_safe(mag, car)
    assert rho == pytest.approx(1.0, abs=1e-12)
    assert p < 0.05


def test_spearman_safe_perfect_negative_correlation() -> None:
    mag = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    car = pd.Series([0.05, 0.04, 0.03, 0.02, 0.01])
    rho, p = _spearman_safe(mag, car)
    assert rho == pytest.approx(-1.0, abs=1e-12)
    assert p < 0.05


def test_spearman_safe_too_few_pairs_returns_nan() -> None:
    rho, p = _spearman_safe(pd.Series([1.0]), pd.Series([0.01]))
    assert pd.isna(rho)
    assert pd.isna(p)


def test_spearman_safe_constant_magnitude_returns_nan() -> None:
    mag = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0])
    car = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
    rho, p = _spearman_safe(mag, car)
    assert pd.isna(rho)
    assert pd.isna(p)


def test_spearman_safe_constant_car_returns_nan() -> None:
    mag = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    car = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01])
    rho, p = _spearman_safe(mag, car)
    assert pd.isna(rho)
    assert pd.isna(p)


def test_spearman_safe_matches_scipy() -> None:
    rng = np.random.default_rng(42)
    mag = pd.Series(rng.normal(0, 1, 100))
    car = pd.Series(0.5 * mag.values + rng.normal(0, 0.5, 100))
    rho, p = _spearman_safe(mag, car)
    expected = stats.spearmanr(mag.to_numpy(), car.to_numpy())
    assert rho == pytest.approx(float(expected.statistic), abs=1e-12)
    assert p == pytest.approx(float(expected.pvalue), abs=1e-12)


# ---------- compute_ic ----------


def test_compute_ic_empty_input_returns_empty_with_schema() -> None:
    out = compute_ic(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == IC_COLUMNS


def test_compute_ic_missing_columns_raises() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        compute_ic(pd.DataFrame({"foo": [1]}))


def test_compute_ic_perfect_correlation_one_group() -> None:
    metrics = _metrics(
        [
            ("A", 5, 1.0, 0.01),
            ("A", 5, 2.0, 0.02),
            ("A", 5, 3.0, 0.03),
            ("A", 5, 4.0, 0.04),
            ("A", 5, 5.0, 0.05),
        ]
    )
    out = compute_ic(metrics)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["event_type"] == "A"
    assert row["holding_window"] == 5
    assert row["n_pairs"] == 5
    assert row["ic"] == pytest.approx(1.0, abs=1e-12)
    assert row["ic_pvalue"] < 0.05


def test_compute_ic_drops_nan_pairs() -> None:
    metrics = _metrics(
        [
            ("A", 5, 1.0, 0.01),
            ("A", 5, float("nan"), 0.02),  # NaN magnitude → drop
            ("A", 5, 3.0, float("nan")),  # NaN car → drop
            ("A", 5, 4.0, 0.04),
            ("A", 5, 5.0, 0.05),
        ]
    )
    out = compute_ic(metrics)
    row = out.iloc[0]
    assert row["n_pairs"] == 3  # only fully-valid rows count


def test_compute_ic_too_few_pairs_yields_nan() -> None:
    metrics = _metrics([("A", 5, 1.0, 0.01)])
    out = compute_ic(metrics)
    row = out.iloc[0]
    assert row["n_pairs"] == 1
    assert pd.isna(row["ic"])
    assert pd.isna(row["ic_pvalue"])


def test_compute_ic_multi_group_sorted_output() -> None:
    metrics = _metrics(
        [
            ("B", 1, 100.0, 0.01),
            ("B", 1, 200.0, 0.02),
            ("B", 1, 300.0, 0.03),
            ("A", 5, 1.0, 0.01),
            ("A", 5, 2.0, 0.02),
            ("A", 5, 3.0, 0.03),
            ("A", 1, 1.0, 0.005),
            ("A", 1, 2.0, 0.010),
            ("A", 1, 3.0, 0.015),
        ]
    )
    out = compute_ic(metrics)
    assert len(out) == 3
    # Sorted by (event_type, holding_window)
    assert out["event_type"].tolist() == ["A", "A", "B"]
    assert out["holding_window"].tolist() == [1, 5, 1]
    # All three groups have perfect rank correlation
    assert np.allclose(out["ic"].to_numpy(), 1.0, atol=1e-12)


def test_compute_ic_random_uncorrelated_yields_small_ic() -> None:
    rng = np.random.default_rng(2026)
    n = 200
    metrics = _metrics(
        [
            ("A", 5, float(rng.normal()), float(rng.normal() * 0.01))
            for _ in range(n)
        ]
    )
    out = compute_ic(metrics)
    row = out.iloc[0]
    assert abs(row["ic"]) < 0.2  # noise in finite sample
    assert row["ic_pvalue"] > 0.01  # likely not significant


def test_compute_ic_constant_magnitude_yields_nan() -> None:
    metrics = _metrics(
        [
            ("D", 5, 0.05, 0.01),
            ("D", 5, 0.05, 0.02),
            ("D", 5, 0.05, 0.03),
            ("D", 5, 0.05, 0.04),
        ]
    )
    out = compute_ic(metrics)
    row = out.iloc[0]
    assert row["n_pairs"] == 4
    assert pd.isna(row["ic"])
    assert pd.isna(row["ic_pvalue"])
