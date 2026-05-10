"""Tests for catalystlab.stats.bootstrap (W3 T3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from catalystlab.stats.bootstrap import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    apply_bootstrap_to_summary,
    bootstrap_ic_ci,
)

# ---------- bootstrap_ic_ci ----------


def test_bootstrap_ci_brackets_point_estimate() -> None:
    rng = np.random.default_rng(42)
    n = 50
    x = rng.normal(0, 1, n)
    y = 0.5 * x + rng.normal(0, 0.5, n)
    point, lo, hi = bootstrap_ic_ci(x, y, n_resample=500, rng=np.random.default_rng(0))
    assert lo <= point <= hi


def test_bootstrap_seed_determinism() -> None:
    rng = np.random.default_rng(0)
    n = 50
    x = rng.normal(0, 1, n)
    y = 0.5 * x + rng.normal(0, 0.5, n)
    p1, lo1, hi1 = bootstrap_ic_ci(x, y, rng=np.random.default_rng(123))
    p2, lo2, hi2 = bootstrap_ic_ci(x, y, rng=np.random.default_rng(123))
    assert (p1, lo1, hi1) == (p2, lo2, hi2)


def test_bootstrap_different_seed_different_ci() -> None:
    rng = np.random.default_rng(0)
    n = 50
    x = rng.normal(0, 1, n)
    y = 0.5 * x + rng.normal(0, 0.5, n)
    _, lo1, hi1 = bootstrap_ic_ci(x, y, rng=np.random.default_rng(1))
    _, lo2, hi2 = bootstrap_ic_ci(x, y, rng=np.random.default_rng(2))
    # Different seeds should give different CI bounds (with high prob).
    assert (lo1, hi1) != (lo2, hi2)


def test_bootstrap_strong_correlation_ci_excludes_zero() -> None:
    """Strong correlation -> CI well above 0."""
    rng = np.random.default_rng(0)
    n = 100
    x = rng.normal(0, 1, n)
    y = 0.9 * x + rng.normal(0, 0.1, n)
    point, lo, _hi = bootstrap_ic_ci(x, y, rng=np.random.default_rng(5))
    assert point > 0.5
    assert lo > 0  # CI strictly above zero


def test_bootstrap_zero_correlation_ci_includes_zero() -> None:
    """Random-pair correlation -> CI brackets 0."""
    rng = np.random.default_rng(0)
    n = 100
    x = rng.normal(0, 1, n)
    y = rng.normal(0, 1, n)  # independent
    _, lo, hi = bootstrap_ic_ci(x, y, n_resample=1000, rng=np.random.default_rng(7))
    assert lo < 0 < hi


def test_bootstrap_too_few_pairs_returns_nan() -> None:
    p, lo, hi = bootstrap_ic_ci(np.array([1.0]), np.array([2.0]))
    assert all(np.isnan(v) for v in (p, lo, hi))


def test_bootstrap_constant_input_returns_nan() -> None:
    p, lo, hi = bootstrap_ic_ci(
        np.array([1.0, 1.0, 1.0]), np.array([2.0, 3.0, 4.0])
    )
    assert all(np.isnan(v) for v in (p, lo, hi))


def test_bootstrap_propagates_nan_pairs() -> None:
    """NaN entries are dropped before resampling."""
    rng = np.random.default_rng(0)
    n = 50
    x = rng.normal(0, 1, n)
    y = 0.5 * x + rng.normal(0, 0.5, n)
    # Inject a few NaNs.
    x_with_nan = x.copy()
    x_with_nan[0] = np.nan
    x_with_nan[5] = np.nan
    y_with_nan = y.copy()
    y_with_nan[10] = np.nan

    p, lo, hi = bootstrap_ic_ci(x_with_nan, y_with_nan, rng=np.random.default_rng(0))
    assert not np.isnan(p)
    assert lo <= p <= hi


def test_bootstrap_unequal_lengths_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        bootstrap_ic_ci(np.array([1.0, 2.0]), np.array([1.0]))


# ---------- apply_bootstrap_to_summary ----------


def _metric_row(et: str, hw: int, mag: float, car: float) -> dict[str, object]:
    return {
        "ticker": "X",
        "event_date": pd.Timestamp("2024-01-01"),
        "event_type": et,
        "event_magnitude": mag,
        "holding_window": hw,
        "beta": 1.0,
        "n_obs": hw,
        "car": car,
    }


def test_apply_bootstrap_adds_columns_to_summary() -> None:
    rng = np.random.default_rng(0)
    n = 30
    metrics = pd.DataFrame(
        [
            _metric_row("A", 5, float(rng.normal()), float(rng.normal() * 0.01))
            for _ in range(n)
        ]
    )
    summary = pd.DataFrame([{"event_type": "A", "holding_window": 5}])
    out = apply_bootstrap_to_summary(metrics, summary, n_resample=200, seed=0)

    assert "ic_ci_lower" in out.columns
    assert "ic_ci_upper" in out.columns
    assert "ic_ci_crosses_zero" in out.columns
    row = out.iloc[0]
    assert not np.isnan(row["ic_ci_lower"])
    assert not np.isnan(row["ic_ci_upper"])
    assert row["ic_ci_lower"] <= row["ic_ci_upper"]


def test_apply_bootstrap_seed_determinism() -> None:
    rng = np.random.default_rng(0)
    n = 30
    metrics = pd.DataFrame(
        [
            _metric_row("A", 5, float(rng.normal()), float(rng.normal() * 0.01))
            for _ in range(n)
        ]
    )
    summary = pd.DataFrame([{"event_type": "A", "holding_window": 5}])
    out1 = apply_bootstrap_to_summary(metrics, summary, n_resample=200, seed=42)
    out2 = apply_bootstrap_to_summary(metrics, summary, n_resample=200, seed=42)
    pd.testing.assert_frame_equal(out1, out2)


def test_apply_bootstrap_crosses_zero_flag() -> None:
    """For independent x/y, CI should bracket 0 -> crosses_zero=True."""
    rng = np.random.default_rng(0)
    n = 100
    metrics = pd.DataFrame(
        [
            _metric_row("A", 5, float(rng.normal()), float(rng.normal() * 0.01))
            for _ in range(n)
        ]
    )
    summary = pd.DataFrame([{"event_type": "A", "holding_window": 5}])
    out = apply_bootstrap_to_summary(metrics, summary, n_resample=500, seed=0)
    assert out.iloc[0]["ic_ci_crosses_zero"]


def test_apply_bootstrap_empty_input() -> None:
    out = apply_bootstrap_to_summary(pd.DataFrame(), pd.DataFrame())
    assert "ic_ci_lower" in out.columns
    assert out.empty


def test_apply_bootstrap_missing_columns_raises() -> None:
    metrics = pd.DataFrame([_metric_row("A", 5, 1.0, 0.01)])
    summary = pd.DataFrame([{"foo": "bar"}])
    with pytest.raises(ValueError, match="summary"):
        apply_bootstrap_to_summary(metrics, summary)


def test_default_bootstrap_constants() -> None:
    assert DEFAULT_BOOTSTRAP_RESAMPLES == 1000
    assert DEFAULT_BOOTSTRAP_SEED == 42
