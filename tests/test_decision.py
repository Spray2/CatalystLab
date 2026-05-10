"""Tests for catalystlab.reporting.decision (W3 T7)."""

from __future__ import annotations

import pandas as pd

from catalystlab.reporting.decision import (
    DECISION_FLAG_COLUMNS,
    annotate_decision_flags,
    decide,
)

# Standard prereg §6.3 thresholds.
IC = 0.05
HIT = 0.55
ALPHA = 0.05


def _row(
    et: str,
    hw: int,
    ic: float = 0.10,
    bh: float = 0.01,
    hit: float = 0.60,
    crosses: bool = False,
    ci_lower: float = 0.05,
    ci_upper: float = 0.15,
    raw_p: float = 0.005,
    n_valid: int = 30,
    mean_car_net: float = 0.005,
) -> dict[str, object]:
    return {
        "event_type": et,
        "holding_window": hw,
        "n_valid": n_valid,
        "ic": ic,
        "ic_pvalue": raw_p,
        "ic_pvalue_bh": bh,
        "hit_rate": hit,
        "mean_car_net": mean_car_net,
        "ic_ci_lower": ci_lower,
        "ic_ci_upper": ci_upper,
        "ic_ci_crosses_zero": crosses,
    }


# ---------- annotate_decision_flags ----------


def test_flags_winning_combination_marked() -> None:
    summary = pd.DataFrame([_row("A", 60)])
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    assert all(c in out.columns for c in DECISION_FLAG_COLUMNS)
    row = out.iloc[0]
    assert row["passes_ic"]
    assert row["passes_hit_rate"]
    assert row["passes_bh"]
    assert row["passes_ci"]
    assert row["is_winning"]
    assert not row["is_ambiguous"]


def test_flags_ambiguous_when_bh_fails() -> None:
    summary = pd.DataFrame([_row("A", 60, bh=0.10)])
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    row = out.iloc[0]
    assert not row["passes_bh"]
    assert not row["is_winning"]
    assert row["is_ambiguous"]


def test_flags_ambiguous_when_ci_crosses_zero() -> None:
    summary = pd.DataFrame(
        [_row("A", 60, crosses=True, ci_lower=-0.05, ci_upper=0.15)]
    )
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    row = out.iloc[0]
    assert not row["passes_ci"]
    assert not row["is_winning"]
    assert row["is_ambiguous"]


def test_flags_negative_when_ic_fails() -> None:
    summary = pd.DataFrame([_row("A", 60, ic=0.02)])
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    row = out.iloc[0]
    assert not row["passes_ic"]
    assert not row["is_winning"]
    assert not row["is_ambiguous"]


def test_flags_negative_when_hit_rate_fails() -> None:
    summary = pd.DataFrame([_row("A", 60, hit=0.50)])
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    row = out.iloc[0]
    assert not row["passes_hit_rate"]
    assert not row["is_winning"]
    assert not row["is_ambiguous"]


def test_flags_nan_ic_treated_as_fail() -> None:
    summary = pd.DataFrame(
        [_row("A", 60, ic=float("nan"))]
    )
    out = annotate_decision_flags(summary, IC, HIT, ALPHA)
    row = out.iloc[0]
    assert not row["passes_ic"]


# ---------- decide ----------


def test_decide_positive_with_one_winner() -> None:
    summary = pd.DataFrame(
        [
            _row("A", 60),  # winning
            _row("B", 5, ic=0.02),  # negative
        ]
    )
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "positive"
    assert out["n_winning"] == 1
    assert out["n_ambiguous"] == 0
    assert len(out["winning_combinations"]) == 1
    assert out["winning_combinations"][0]["event_type"] == "A"
    assert "paper trading" in out["rationale"].lower()


def test_decide_ambiguous_when_only_ambiguous_present() -> None:
    summary = pd.DataFrame(
        [
            _row("A", 60, bh=0.10),  # ambiguous (BH fails)
            _row("B", 5, ic=0.02),  # negative
        ]
    )
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "ambiguous"
    assert out["n_winning"] == 0
    assert out["n_ambiguous"] == 1
    assert "ambiguous" in out["rationale"].lower()
    assert "trattato come negativo" in out["rationale"] or "treated as negative" in out["rationale"].lower()


def test_decide_negative_when_no_candidates() -> None:
    summary = pd.DataFrame(
        [
            _row("A", 60, ic=0.02),
            _row("B", 5, ic=0.01),
        ]
    )
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "negative"
    assert out["n_winning"] == 0
    assert out["n_ambiguous"] == 0
    assert "no combination" in out["rationale"].lower()


def test_decide_winning_overrides_ambiguous() -> None:
    """If at least one combination wins, verdict is positive even if others are ambiguous."""
    summary = pd.DataFrame(
        [
            _row("A", 60),  # winning
            _row("D", 5, bh=0.10),  # ambiguous
        ]
    )
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "positive"
    assert out["n_winning"] == 1
    # Ambiguous list should still record the failed candidate.
    assert out["n_ambiguous"] == 1


def test_decide_ambiguous_reason_annotated() -> None:
    summary = pd.DataFrame([_row("A", 60, bh=0.10)])
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "ambiguous"
    reason = out["ambiguous_combinations"][0]["ambiguous_reason"]
    assert "BH" in reason or "bh" in reason


def test_decide_ambiguous_reason_ci_crosses() -> None:
    summary = pd.DataFrame(
        [_row("A", 60, crosses=True, ci_lower=-0.05, ci_upper=0.15)]
    )
    out = decide(summary, IC, HIT, ALPHA)
    assert out["verdict"] == "ambiguous"
    reason = out["ambiguous_combinations"][0]["ambiguous_reason"]
    assert "CI" in reason or "ci" in reason or "zero" in reason.lower()


def test_decide_thresholds_echoed() -> None:
    summary = pd.DataFrame([_row("A", 60)])
    out = decide(summary, ic_threshold=0.07, hit_rate_threshold=0.60, bh_alpha=0.10)
    assert out["thresholds"]["ic_threshold"] == 0.07
    assert out["thresholds"]["hit_rate_threshold"] == 0.60
    assert out["thresholds"]["bh_alpha"] == 0.10


def test_decide_empty_summary_returns_negative() -> None:
    out = decide(pd.DataFrame(columns=["event_type", "holding_window", "ic", "ic_pvalue_bh", "hit_rate", "ic_ci_lower", "ic_ci_upper", "ic_ci_crosses_zero"]), IC, HIT, ALPHA)
    assert out["verdict"] == "negative"
    assert out["n_winning"] == 0
    assert out["n_ambiguous"] == 0


def test_decide_w2_smoke_outcome() -> None:
    """Reproduces the W2 smoke-run shape: 1 winner uncorrected, but BH applied."""
    # Simulating: A T+60 IC=0.319 p=0.010 hit=62.5%; BH-corrected (5 cat) makes p≈0.05.
    # If BH-corrected p stays below 0.05 -> winner.
    # If it goes above -> ambiguous.
    summary_winning = pd.DataFrame(
        [_row("A", 60, ic=0.319, bh=0.025, hit=0.625, ci_lower=0.10, ci_upper=0.50, crosses=False)]
    )
    out = decide(summary_winning, IC, HIT, ALPHA)
    assert out["verdict"] == "positive"

    summary_ambiguous = pd.DataFrame(
        [_row("A", 60, ic=0.319, bh=0.10, hit=0.625, ci_lower=0.10, ci_upper=0.50, crosses=False)]
    )
    out = decide(summary_ambiguous, IC, HIT, ALPHA)
    assert out["verdict"] == "ambiguous"


# ---------- detail completeness ----------


def test_decide_winning_row_includes_metric_columns() -> None:
    summary = pd.DataFrame([_row("A", 60)])
    out = decide(summary, IC, HIT, ALPHA)
    win = out["winning_combinations"][0]
    for col in ("event_type", "holding_window", "ic", "ic_pvalue_bh",
                "hit_rate", "mean_car_net", "ic_ci_lower", "ic_ci_upper"):
        assert col in win
