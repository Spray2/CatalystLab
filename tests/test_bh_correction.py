"""Tests for catalystlab.stats.bh_correction (W3 T2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from catalystlab.stats.bh_correction import (
    DEFAULT_BH_ALPHA,
    apply_bh_per_holding_window,
    bh_correct_pvalues,
)

# ---------- bh_correct_pvalues ----------


def test_bh_known_5_pvalues_matches_textbook() -> None:
    """BH on 5 sorted p-values reproduces textbook step-up adjusted values."""
    raw = np.array([0.001, 0.008, 0.039, 0.041, 0.042])
    # Step-up: q_(k) = min over j >= k of (p_(j) * 5 / j)
    # k=5: 0.042 * 5/5 = 0.042
    # k=4: 0.041 * 5/4 = 0.05125 -> min(0.05125, 0.042) = 0.042
    # k=3: 0.039 * 5/3 = 0.065   -> min(0.065,   0.042) = 0.042
    # k=2: 0.008 * 5/2 = 0.020   -> min(0.020,   0.042) = 0.020
    # k=1: 0.001 * 5/1 = 0.005   -> min(0.005,   0.020) = 0.005
    expected = np.array([0.005, 0.020, 0.042, 0.042, 0.042])
    out = bh_correct_pvalues(raw)
    np.testing.assert_allclose(out, expected, atol=1e-12)


def test_bh_rank_monotone() -> None:
    """corrected_p is rank-monotone: lower raw -> lower corrected."""
    rng = np.random.default_rng(0)
    raw = rng.uniform(0, 1, 50)
    out = bh_correct_pvalues(raw)
    order = np.argsort(raw)
    assert np.all(np.diff(out[order]) >= -1e-12)


def test_bh_corrected_geq_raw() -> None:
    rng = np.random.default_rng(1)
    raw = rng.uniform(0, 1, 30)
    out = bh_correct_pvalues(raw)
    assert (out >= raw - 1e-12).all()


def test_bh_capped_at_one() -> None:
    raw = np.array([0.5, 0.6, 0.7, 0.8, 0.9])
    out = bh_correct_pvalues(raw)
    assert (out <= 1.0).all()


def test_bh_propagates_nan() -> None:
    raw = np.array([0.01, np.nan, 0.04, 0.03, np.nan])
    out = bh_correct_pvalues(raw)
    assert np.isnan(out[1])
    assert np.isnan(out[4])
    assert not np.isnan(out[0])


def test_bh_n_tests_inflation() -> None:
    """Forcing n_tests above valid count makes corrections more conservative."""
    raw = np.array([0.01, 0.02, np.nan, np.nan, np.nan])
    inferred = bh_correct_pvalues(raw)
    forced = bh_correct_pvalues(raw, n_tests=5)
    valid_idx = ~np.isnan(raw)
    assert (forced[valid_idx] >= inferred[valid_idx] - 1e-12).all()
    # With m=5 forced, k=1 -> 0.01*5/1=0.05, k=2 -> 0.02*5/2=0.05
    np.testing.assert_allclose(forced[valid_idx], [0.05, 0.05], atol=1e-12)


def test_bh_n_tests_smaller_than_valid_raises() -> None:
    raw = np.array([0.01, 0.02, 0.03])
    with pytest.raises(ValueError, match="n_tests"):
        bh_correct_pvalues(raw, n_tests=2)


def test_bh_invalid_n_tests_raises() -> None:
    raw = np.array([0.01, 0.02])
    with pytest.raises(ValueError, match="n_tests"):
        bh_correct_pvalues(raw, n_tests=0)


def test_bh_2d_input_raises() -> None:
    with pytest.raises(ValueError, match="1-D"):
        bh_correct_pvalues(np.array([[0.01, 0.02], [0.03, 0.04]]))


def test_bh_empty_input() -> None:
    out = bh_correct_pvalues(np.array([], dtype=float))
    assert len(out) == 0


def test_bh_all_nan_input() -> None:
    raw = np.array([np.nan, np.nan, np.nan])
    out = bh_correct_pvalues(raw)
    assert np.isnan(out).all()


def test_bh_single_pvalue_unchanged() -> None:
    """With m=1, BH-corrected = raw."""
    raw = np.array([0.03])
    out = bh_correct_pvalues(raw)
    np.testing.assert_allclose(out, [0.03], atol=1e-12)


# ---------- apply_bh_per_holding_window ----------


def _summary_row(category: str, hw: int, pvalue: float) -> dict[str, object]:
    return {"event_type": category, "holding_window": hw, "ic_pvalue": pvalue}


def test_apply_bh_per_window_groups_correctly() -> None:
    summary = pd.DataFrame(
        [
            _summary_row("A", 1, 0.01),
            _summary_row("B", 1, 0.50),
            _summary_row("C", 1, 0.30),
            _summary_row("D", 1, 0.04),
            _summary_row("E", 1, 0.02),
            _summary_row("A", 5, 0.40),
            _summary_row("B", 5, 0.45),
            _summary_row("C", 5, 0.001),
            _summary_row("D", 5, 0.005),
            _summary_row("E", 5, 0.10),
        ]
    )
    out = apply_bh_per_holding_window(summary, alpha=0.05)

    # Window 1: 5 p-values [0.01, 0.50, 0.30, 0.04, 0.02]
    # Sorted: [0.01, 0.02, 0.04, 0.30, 0.50]
    # q_(k) raw: [0.05, 0.05, 0.0667, 0.375, 0.50]
    # right-cumulative-min: [0.05, 0.05, 0.0667, 0.375, 0.50]
    win1 = out[out["holding_window"] == 1].sort_values("ic_pvalue")
    np.testing.assert_allclose(
        win1["ic_pvalue_bh"].to_numpy(),
        [0.05, 0.05, 0.0667, 0.375, 0.50],
        atol=1e-3,
    )


def test_apply_bh_adds_reject_column() -> None:
    summary = pd.DataFrame(
        [
            _summary_row("A", 1, 0.001),
            _summary_row("B", 1, 0.50),
            _summary_row("C", 1, 0.30),
            _summary_row("D", 1, 0.40),
            _summary_row("E", 1, 0.45),
        ]
    )
    out = apply_bh_per_holding_window(summary, alpha=0.05)
    # Only A's BH-corrected p (0.005) < 0.05.
    rejects = out[out["bh_reject"]]
    assert len(rejects) == 1
    assert rejects.iloc[0]["event_type"] == "A"


def test_apply_bh_handles_nan_pvalues() -> None:
    summary = pd.DataFrame(
        [
            _summary_row("A", 1, 0.01),
            _summary_row("B", 1, np.nan),
            _summary_row("C", 1, np.nan),
            _summary_row("D", 1, 0.04),
            _summary_row("E", 1, 0.50),
        ]
    )
    out = apply_bh_per_holding_window(summary, alpha=0.05, n_tests_per_window=5)
    # NaN p-values stay NaN BH; do not pass.
    nan_rows = out[out["ic_pvalue"].isna()]
    assert nan_rows["ic_pvalue_bh"].isna().all()
    assert not nan_rows["bh_reject"].any()


def test_apply_bh_empty_input_returns_empty_with_extra_cols() -> None:
    summary = pd.DataFrame(columns=["event_type", "holding_window", "ic_pvalue"])
    out = apply_bh_per_holding_window(summary)
    assert "ic_pvalue_bh" in out.columns
    assert "bh_reject" in out.columns
    assert out.empty


def test_apply_bh_missing_pvalue_column_raises() -> None:
    summary = pd.DataFrame(
        [{"event_type": "A", "holding_window": 1}]
    )
    with pytest.raises(ValueError, match="ic_pvalue"):
        apply_bh_per_holding_window(summary)


def test_apply_bh_missing_holding_window_raises() -> None:
    summary = pd.DataFrame([{"event_type": "A", "ic_pvalue": 0.01}])
    with pytest.raises(ValueError, match="holding_window"):
        apply_bh_per_holding_window(summary)


def test_apply_bh_uses_default_alpha() -> None:
    summary = pd.DataFrame(
        [_summary_row("A", 1, 0.005), _summary_row("B", 1, 0.5)]
    )
    out = apply_bh_per_holding_window(summary)
    # Default alpha = 0.05; A's BH p = 0.005 * 2/1 = 0.01 < 0.05 -> reject.
    assert DEFAULT_BH_ALPHA == 0.05
    assert out[out["event_type"] == "A"]["bh_reject"].iloc[0]


# ---------- hypothesis property tests ----------


@given(
    pvalues=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        min_size=2,
        max_size=20,
    )
)
@settings(max_examples=50, deadline=None)
def test_bh_corrected_geq_raw_property(pvalues: list[float]) -> None:
    """corrected_p >= raw_p element-wise for any input array."""
    raw = np.asarray(pvalues, dtype=float)
    out = bh_correct_pvalues(raw)
    assert (out >= raw - 1e-12).all()


@given(
    pvalues=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        min_size=2,
        max_size=20,
    )
)
@settings(max_examples=50, deadline=None)
def test_bh_corrected_capped_at_1_property(pvalues: list[float]) -> None:
    raw = np.asarray(pvalues, dtype=float)
    out = bh_correct_pvalues(raw)
    assert (out <= 1.0).all()


@given(
    pvalues=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        min_size=2,
        max_size=20,
    )
)
@settings(max_examples=50, deadline=None)
def test_bh_rank_monotone_property(pvalues: list[float]) -> None:
    raw = np.asarray(pvalues, dtype=float)
    out = bh_correct_pvalues(raw)
    order = np.argsort(raw)
    assert np.all(np.diff(out[order]) >= -1e-12)
