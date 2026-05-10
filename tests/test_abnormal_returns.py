"""Tests for catalystlab.eventstudy.abnormal_returns — beta estimation (W2 T2).

Strategy:
    * Synthetic OLS ground truth: known β recovered exactly when noise=0.
    * statsmodels.OLS comparison: β matches the slope coefficient over the
      same window, to floating-point tolerance.
    * Edge cases: insufficient history, zero benchmark variance, event
      before data.
    * Hypothesis property tests: scale invariance, inverse-scaling of
      benchmark.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from catalystlab.eventstudy.abnormal_returns import (
    DEFAULT_BETA_EXCLUSION_DAYS,
    DEFAULT_BETA_WINDOW_DAYS,
    estimate_beta,
    estimate_betas,
)


def _synth_returns(
    n: int,
    beta: float,
    alpha: float = 0.0,
    noise_std: float = 0.0,
    bench_std: float = 0.01,
    seed: int = 0,
) -> tuple[pd.Series, pd.Series]:
    """Generate r_i = alpha + beta * r_b + noise, with optional noise."""
    rng = np.random.default_rng(seed)
    r_b = rng.normal(0.0, bench_std, n)
    eps = rng.normal(0.0, noise_std, n) if noise_std > 0 else np.zeros(n)
    r_i = alpha + beta * r_b + eps
    dates = pd.bdate_range("2022-01-03", periods=n)
    return (
        pd.Series(r_i, index=dates, name="i"),
        pd.Series(r_b, index=dates, name="b"),
    )


# ---------- core β recovery ----------


def test_beta_recovers_known_value_zero_noise() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.5, noise_std=0.0)
    beta = estimate_beta(r_i, r_b, r_i.index[-1])
    assert beta == pytest.approx(1.5, abs=1e-12)


def test_beta_matches_statsmodels_ols_with_noise() -> None:
    sm = pytest.importorskip("statsmodels.api")
    r_i, r_b = _synth_returns(n=400, beta=1.2, noise_std=0.003, seed=42)

    event_date = r_i.index[-1]
    window = DEFAULT_BETA_WINDOW_DAYS
    exclusion = DEFAULT_BETA_EXCLUSION_DAYS

    beta = estimate_beta(r_i, r_b, event_date, window_days=window, exclusion_days=exclusion)

    # Mirror the implementation's window placement: event_pos = len-1
    # (last index), end_pos = event_pos - exclusion, start_pos = end_pos - window.
    event_pos = len(r_i) - 1
    end_pos = event_pos - exclusion
    start_pos = end_pos - window
    sub_i = r_i.iloc[start_pos:end_pos]
    sub_b = r_b.iloc[start_pos:end_pos]
    regressors = sm.add_constant(sub_b.values)
    ols_beta = sm.OLS(sub_i.values, regressors).fit().params[1]

    assert beta == pytest.approx(ols_beta, abs=1e-12)


# ---------- edge cases ----------


def test_beta_insufficient_history_returns_nan() -> None:
    # Need 282 days (252 + 30), have 100 → insufficient.
    r_i, r_b = _synth_returns(n=100, beta=1.0)
    beta = estimate_beta(r_i, r_b, r_i.index[-1])
    assert pd.isna(beta)


def test_beta_zero_benchmark_variance_returns_nan() -> None:
    n = 300
    dates = pd.bdate_range("2023-01-02", periods=n)
    rng = np.random.default_rng(7)
    r_b = pd.Series([0.001] * n, index=dates)  # constant → variance 0
    r_i = pd.Series(rng.normal(0.0, 0.01, n), index=dates)
    beta = estimate_beta(r_i, r_b, r_i.index[-1])
    assert pd.isna(beta)


def test_beta_event_before_data_returns_nan() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.0)
    early_event = pd.Timestamp("2010-01-01")
    beta = estimate_beta(r_i, r_b, early_event)
    assert pd.isna(beta)


def test_beta_empty_returns_nan() -> None:
    empty = pd.Series([], dtype=float, index=pd.DatetimeIndex([], name="date"))
    beta = estimate_beta(empty, empty, pd.Timestamp("2024-01-01"))
    assert pd.isna(beta)


def test_beta_invalid_window_raises() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.0)
    with pytest.raises(ValueError, match="window_days"):
        estimate_beta(r_i, r_b, r_i.index[-1], window_days=0)
    with pytest.raises(ValueError, match="exclusion_days"):
        estimate_beta(r_i, r_b, r_i.index[-1], exclusion_days=-1)


def test_beta_excludes_recent_window() -> None:
    """A perturbation inside the exclusion zone should not affect β."""
    r_i, r_b = _synth_returns(n=400, beta=1.0, noise_std=0.0, seed=11)

    perturbed_i = r_i.copy()
    perturbed_b = r_b.copy()
    perturbed_i.iloc[-DEFAULT_BETA_EXCLUSION_DAYS:] = 0.5
    perturbed_b.iloc[-DEFAULT_BETA_EXCLUSION_DAYS:] = 0.001

    beta_orig = estimate_beta(r_i, r_b, r_i.index[-1])
    beta_pert = estimate_beta(perturbed_i, perturbed_b, r_i.index[-1])
    assert beta_orig == pytest.approx(beta_pert, abs=1e-12)


def test_beta_uses_asof_for_non_trading_event_date() -> None:
    """An event_date that falls on a weekend resolves to the last trading day."""
    r_i, r_b = _synth_returns(n=400, beta=1.5, noise_std=0.0, seed=3)
    # r_i ends on a Friday; specify an event on the following Sunday.
    last = r_i.index[-1]
    weekend = last + pd.Timedelta(days=2)
    beta_friday = estimate_beta(r_i, r_b, last)
    beta_sunday = estimate_beta(r_i, r_b, weekend)
    assert beta_friday == pytest.approx(beta_sunday, abs=1e-12)


# ---------- vectorised wrapper ----------


def test_estimate_betas_returns_series_with_event_index() -> None:
    r_i, r_b = _synth_returns(n=400, beta=1.2, noise_std=0.003, seed=42)
    event_dates = [r_i.index[300], r_i.index[350], r_i.index[399]]

    betas = estimate_betas(event_dates, r_i, r_b)

    assert isinstance(betas, pd.Series)
    assert betas.name == "beta"
    assert len(betas) == 3
    # All should be close to 1.2 (small noise → small estimation error).
    for b in betas:
        assert 0.9 < b < 1.5


def test_estimate_betas_consistent_with_estimate_beta() -> None:
    r_i, r_b = _synth_returns(n=400, beta=1.0, noise_std=0.005, seed=99)
    event_dates = [r_i.index[300], r_i.index[399]]
    vec = estimate_betas(event_dates, r_i, r_b)
    for d, expected in vec.items():
        single = estimate_beta(r_i, r_b, d)
        assert single == pytest.approx(expected, abs=1e-12)


# ---------- hypothesis property tests ----------


@given(scale=st.floats(min_value=0.01, max_value=100.0, allow_nan=False))
@settings(max_examples=25, deadline=None)
def test_beta_invariant_to_uniform_scaling(scale: float) -> None:
    """Scaling both series by the same factor preserves β."""
    r_i, r_b = _synth_returns(n=400, beta=1.2, noise_std=0.003, seed=42)
    beta_orig = estimate_beta(r_i, r_b, r_i.index[-1])
    beta_scaled = estimate_beta(r_i * scale, r_b * scale, r_i.index[-1])
    assert beta_orig == pytest.approx(beta_scaled, abs=1e-9)


@given(scale_b=st.floats(min_value=0.1, max_value=100.0, allow_nan=False))
@settings(max_examples=25, deadline=None)
def test_beta_scales_inversely_with_benchmark(scale_b: float) -> None:
    """Scaling only r_b by k → β must scale by 1/k."""
    r_i, r_b = _synth_returns(n=400, beta=1.2, noise_std=0.003, seed=42)
    beta_orig = estimate_beta(r_i, r_b, r_i.index[-1])
    beta_scaled = estimate_beta(r_i, r_b * scale_b, r_i.index[-1])
    assert beta_scaled == pytest.approx(beta_orig / scale_b, rel=1e-9)


@given(beta_target=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False))
@settings(max_examples=20, deadline=None)
def test_beta_recovers_arbitrary_target_zero_noise(beta_target: float) -> None:
    """For any β in a plausible equity range, zero-noise data recovers it exactly."""
    r_i, r_b = _synth_returns(n=300, beta=beta_target, noise_std=0.0, seed=5)
    beta = estimate_beta(r_i, r_b, r_i.index[-1])
    assert beta == pytest.approx(beta_target, abs=1e-12)
