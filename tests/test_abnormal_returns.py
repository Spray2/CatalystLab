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


# ---------- AR / CAR ----------


from catalystlab.eventstudy.abnormal_returns import (  # noqa: E402
    EVENT_METRICS_COLUMNS,
    compute_ar_car,
    compute_event_metrics,
)


def test_ar_car_zero_when_returns_track_benchmark_at_beta_one() -> None:
    """r_i = r_b, β=1 → AR ≡ 0 → CAR = 0."""
    r_i, r_b = _synth_returns(n=400, beta=1.0, noise_std=0.0, seed=1)
    event_pos = 350
    car, n_obs = compute_ar_car(r_i, r_b, beta=1.0, event_date=r_i.index[event_pos], holding_window=10)
    assert n_obs == 10
    assert car == pytest.approx(0.0, abs=1e-12)


def test_ar_car_constant_alpha_yields_k_times_alpha() -> None:
    """r_i = a + b r_b -> AR = a each day -> CAR(window=k) = k*a."""
    n = 400
    rng = np.random.default_rng(123)
    r_b = pd.Series(rng.normal(0, 0.01, n), index=pd.bdate_range("2022-01-03", periods=n))
    alpha = 0.005
    beta = 1.3
    r_i = alpha + beta * r_b

    event_pos = 350
    for k in [1, 5, 10, 20]:
        car, n_obs = compute_ar_car(r_i, r_b, beta=beta, event_date=r_i.index[event_pos], holding_window=k)
        assert n_obs == k
        assert car == pytest.approx(k * alpha, abs=1e-12)


def test_ar_car_event_at_end_returns_nan() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.0, noise_std=0.0)
    car, n_obs = compute_ar_car(r_i, r_b, beta=1.0, event_date=r_i.index[-1], holding_window=5)
    assert pd.isna(car)
    assert n_obs == 0


def test_ar_car_truncates_at_end_of_data() -> None:
    """Event 3 days from end with window=10 -> only 3 obs."""
    r_i, r_b = _synth_returns(n=300, beta=1.0, noise_std=0.0)
    _car, n_obs = compute_ar_car(r_i, r_b, beta=1.0, event_date=r_i.index[-4], holding_window=10)
    assert n_obs == 3


def test_ar_car_nan_beta_yields_nan_car() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.0, noise_std=0.0)
    car, n_obs = compute_ar_car(r_i, r_b, beta=float("nan"), event_date=r_i.index[100], holding_window=5)
    assert pd.isna(car)
    assert n_obs == 0


def test_ar_car_invalid_window_raises() -> None:
    r_i, r_b = _synth_returns(n=300, beta=1.0, noise_std=0.0)
    with pytest.raises(ValueError, match="holding_window"):
        compute_ar_car(r_i, r_b, beta=1.0, event_date=r_i.index[100], holding_window=0)


def test_ar_car_skips_t0() -> None:
    """Per prereg §4: T+0 not counted. Window starts at T+1."""
    n = 100
    dates = pd.bdate_range("2022-01-03", periods=n)
    r_b = pd.Series([0.01] * n, index=dates)
    # r_i: huge return on event day, small after.
    r_i = pd.Series([0.01] * n, index=dates)
    r_i.iloc[50] = 0.5  # T+0 spike
    car, n_obs = compute_ar_car(r_i, r_b, beta=1.0, event_date=dates[50], holding_window=3)
    # T+0 (the event day) is excluded; T+1, T+2, T+3 all have AR = 0
    assert n_obs == 3
    assert car == pytest.approx(0.0, abs=1e-12)


# ---------- compute_event_metrics ----------


def _make_synth_panel(
    tickers: list[str],
    n_days: int,
    benchmark_returns: pd.Series,
    beta_per_ticker: dict[str, float],
    alpha_per_event: dict[tuple[str, int], float],  # (ticker, event_pos) -> alpha
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build a synthetic long-format panel for compute_event_metrics tests."""
    del seed  # noise-free panels for tests; rng kept out for determinism
    rows = []
    for t in tickers:
        beta = beta_per_ticker[t]
        ri = (beta * benchmark_returns).copy()
        # No noise; tests rely on exact arithmetic.
        for (tk, pos), alpha in alpha_per_event.items():
            if tk == t:
                # Inject alpha at positions pos+1..pos+200; the event itself
                # is at `pos` and post-event returns get shifted by alpha.
                ri.iloc[pos + 1 : pos + 200] = ri.iloc[pos + 1 : pos + 200] + alpha
        for d, v in zip(benchmark_returns.index, ri.values, strict=False):
            rows.append({
                "date": d,
                "ticker": t,
                "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
                "adj_close": 100.0, "volume": 1_000_000,
                "return": v,
                "ar_vs_xlk_proxy": v - benchmark_returns.loc[d],
                "event_type": None,
                "event_magnitude": float("nan"),
            })
    df = pd.DataFrame(rows)
    return df, benchmark_returns


def test_compute_event_metrics_recovers_constant_alpha() -> None:
    """For an event with post-event alpha=0.005 and beta=1.5, CAR(k) approx k*alpha."""
    n = 500
    dates = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(0)
    bench = pd.Series(rng.normal(0, 0.01, n), index=dates, name="bench")

    event_pos = 400  # leave room for window=20
    panel, _ = _make_synth_panel(
        tickers=["VRT"],
        n_days=n,
        benchmark_returns=bench,
        beta_per_ticker={"VRT": 1.5},
        alpha_per_event={("VRT", event_pos): 0.005},
    )
    # Mark the event at position event_pos.
    mask = (panel["ticker"] == "VRT") & (panel["date"] == dates[event_pos])
    panel.loc[mask, "event_type"] = "A"
    panel.loc[mask, "event_magnitude"] = 1.0

    metrics = compute_event_metrics(
        panel,
        bench,
        holding_windows=[1, 5, 20],
    )

    assert list(metrics.columns) == EVENT_METRICS_COLUMNS
    # 1 event x 3 windows = 3 rows
    assert len(metrics) == 3
    assert (metrics["ticker"] == "VRT").all()
    # beta recovered approx 1.5
    assert metrics["beta"].iloc[0] == pytest.approx(1.5, abs=1e-9)
    # CAR = k * alpha = k * 0.005
    for k in [1, 5, 20]:
        row = metrics[metrics["holding_window"] == k].iloc[0]
        assert row["n_obs"] == k
        assert row["car"] == pytest.approx(k * 0.005, abs=1e-12)


def test_compute_event_metrics_empty_panel() -> None:
    metrics = compute_event_metrics(
        pd.DataFrame(),
        pd.Series([], dtype=float, index=pd.DatetimeIndex([])),
        holding_windows=[1, 5],
    )
    assert metrics.empty
    assert list(metrics.columns) == EVENT_METRICS_COLUMNS


def test_compute_event_metrics_no_events_in_panel() -> None:
    n = 100
    dates = pd.bdate_range("2022-01-03", periods=n)
    bench = pd.Series([0.0] * n, index=dates)
    panel = pd.DataFrame({
        "date": dates,
        "ticker": ["VRT"] * n,
        "return": [0.0] * n,
        "adj_close": [100.0] * n,
        "ar_vs_xlk_proxy": [0.0] * n,
        "event_type": [None] * n,
        "event_magnitude": [float("nan")] * n,
    })
    metrics = compute_event_metrics(panel, bench, holding_windows=[1, 5])
    assert metrics.empty


def test_compute_event_metrics_invalid_window_raises() -> None:
    n = 100
    dates = pd.bdate_range("2022-01-03", periods=n)
    bench = pd.Series([0.0] * n, index=dates)
    panel = pd.DataFrame({
        "date": [dates[50]],
        "ticker": ["VRT"],
        "return": [0.01],
        "adj_close": [100.0],
        "ar_vs_xlk_proxy": [0.01],
        "event_type": ["A"],
        "event_magnitude": [1.0],
    })
    with pytest.raises(ValueError, match="holding_windows"):
        compute_event_metrics(panel, bench, holding_windows=[0, 5])


def test_compute_event_metrics_multi_window_replicates_beta() -> None:
    """β is computed once per event and replicated across holding windows."""
    n = 500
    dates = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(7)
    bench = pd.Series(rng.normal(0, 0.01, n), index=dates)

    panel, _ = _make_synth_panel(
        tickers=["VRT"],
        n_days=n,
        benchmark_returns=bench,
        beta_per_ticker={"VRT": 0.8},
        alpha_per_event={},
    )
    panel.loc[(panel["ticker"] == "VRT") & (panel["date"] == dates[400]), "event_type"] = "B"
    panel.loc[(panel["ticker"] == "VRT") & (panel["date"] == dates[400]), "event_magnitude"] = 100.0

    metrics = compute_event_metrics(panel, bench, holding_windows=[1, 5, 20, 60])
    betas = metrics["beta"].unique()
    assert len(betas) == 1
    assert betas[0] == pytest.approx(0.8, abs=1e-9)


def test_compute_event_metrics_events_override_preserves_overlap() -> None:
    """events_override processes every row independently — no panel dedup."""
    n = 500
    dates = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(31)
    bench = pd.Series(rng.normal(0, 0.01, n), index=dates)

    panel, _ = _make_synth_panel(
        tickers=["VRT"],
        n_days=n,
        benchmark_returns=bench,
        beta_per_ticker={"VRT": 1.0},
        alpha_per_event={},
    )

    # Two events on the same (ticker, date), as if E1 and E2 from analyst.csv.
    events = pd.DataFrame(
        [
            {
                "ticker": "VRT",
                "date": dates[400],
                "event_type": "E",
                "event_magnitude": 0.20,
            },
            {
                "ticker": "VRT",
                "date": dates[400],
                "event_type": "E",
                "event_magnitude": 0.30,
            },
        ]
    )
    metrics = compute_event_metrics(
        panel,
        bench,
        holding_windows=[5],
        events_override=events,
    )
    # 2 events * 1 window = 2 rows (panel-extracted would yield 0 since panel.event_type is empty)
    assert len(metrics) == 2
    assert sorted(metrics["event_magnitude"].tolist()) == [0.20, 0.30]


@given(alpha=st.floats(min_value=-0.05, max_value=0.05, allow_nan=False))
@settings(max_examples=15, deadline=None)
def test_compute_ar_car_linear_in_alpha(alpha: float) -> None:
    """Hypothesis: for r_i = b r_b + a post-event, CAR(k) = k * a exactly."""
    n = 400
    dates = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(2026)
    r_b = pd.Series(rng.normal(0, 0.01, n), index=dates)
    beta = 1.2

    event_pos = 300
    r_i = beta * r_b
    r_i.iloc[event_pos + 1 :] = r_i.iloc[event_pos + 1 :] + alpha

    car, n_obs = compute_ar_car(r_i, r_b, beta=beta, event_date=dates[event_pos], holding_window=20)
    assert n_obs == 20
    assert car == pytest.approx(20 * alpha, abs=1e-12)
