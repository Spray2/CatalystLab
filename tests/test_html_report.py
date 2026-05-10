"""Tests for catalystlab.reporting.html_report (W3 T6)."""

from __future__ import annotations

import pandas as pd

from catalystlab.reporting.decision import annotate_decision_flags, decide
from catalystlab.reporting.html_report import render_report


def _make_summary(verdict_target: str = "positive") -> pd.DataFrame:
    """Build a summary frame that triggers the requested verdict."""
    if verdict_target == "positive":
        ic_pvalue_bh = 0.025
        crosses = False
    elif verdict_target == "ambiguous":
        ic_pvalue_bh = 0.10
        crosses = False
    else:
        ic_pvalue_bh = 0.50
        crosses = False

    rows = [
        {
            "event_type": "A",
            "holding_window": 60,
            "n_valid": 65,
            "ic": 0.319,
            "ic_pvalue": 0.010,
            "ic_pvalue_bh": ic_pvalue_bh,
            "hit_rate": 0.625,
            "mean_car_net": 0.057,
            "ic_ci_lower": 0.10,
            "ic_ci_upper": 0.50,
            "ic_ci_crosses_zero": crosses,
        },
        {
            "event_type": "B",
            "holding_window": 5,
            "n_valid": 2,
            "ic": float("nan"),
            "ic_pvalue": float("nan"),
            "ic_pvalue_bh": float("nan"),
            "hit_rate": 0.5,
            "mean_car_net": -0.005,
            "ic_ci_lower": float("nan"),
            "ic_ci_upper": float("nan"),
            "ic_ci_crosses_zero": False,
        },
    ]
    return pd.DataFrame(rows)


def _annotate(df: pd.DataFrame) -> pd.DataFrame:
    return annotate_decision_flags(df, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)


def _kwargs() -> dict:
    return {
        "sector": "ai_infra",
        "display_name": "AI Infrastructure US",
        "prereg_version": "1.0",
        "prereg_lockfile_date": "2026-05-10",
        "period_start": "2023-01-01",
        "period_end": "2026-04-30",
        "universe": ["VRT", "ETN", "GEV", "PWR", "CEG", "VST", "ANET", "MOD"],
        "benchmark_primary": "XLK",
        "benchmark_secondary": "SPY",
        "holding_windows": [1, 5, 20, 60],
        "cost_bps_round_trip": 95.5,
        "cost_position_eur": 1000.0,
        "sector_yaml_sha256": "f297cd4b32beac3c" + "0" * 48,
        "git_commit": "abcdef1234567890" + "0" * 24,
        "timestamp_utc": "2026-05-10T20:30:00+00:00",
    }


def test_render_basic_structure_positive_verdict() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())

    assert "<!DOCTYPE html>" in html
    assert "ai_infra" in html
    assert "AI Infrastructure US" in html
    assert "positive" in html.lower()
    assert "WIN" in html  # winning row badge
    assert "DISCLAIMER" in html.upper()


def test_render_negative_verdict_no_winning_rows() -> None:
    summary = _annotate(_make_summary("negative"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())
    assert "negative" in html.lower()
    # No rows should be flagged as winning.
    assert "class=\"winning\"" not in html and 'class="winning"' not in html


def test_render_ambiguous_verdict_marked() -> None:
    summary = _annotate(_make_summary("ambiguous"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())
    assert "ambiguous" in html.lower()
    assert "AMBIG" in html


def test_render_temporal_section_present() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    temporal = pd.DataFrame(
        [
            {
                "event_type": "A",
                "holding_window": 60,
                "split_date": "2025-01-01",
                "n_pre": 30,
                "ic_pre": 0.40,
                "n_post": 35,
                "ic_post": 0.20,
                "decay": -0.20,
            }
        ]
    )
    html = render_report(
        decision=decision_obj,
        summary_full=summary,
        temporal=temporal,
        temporal_split_date="2025-01-01",
        **_kwargs(),
    )
    assert "Temporal decay" in html
    assert "2025-01-01" in html


def test_render_stability_section_present() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    stability = pd.DataFrame(
        [
            {
                "event_type": "A",
                "holding_window": 60,
                "k_removed": 5,
                "n_full": 65,
                "ic_full": 0.319,
                "n_after": 60,
                "ic_after_top_k": 0.250,
                "ic_drift": -0.069,
            }
        ]
    )
    html = render_report(
        decision=decision_obj,
        summary_full=summary,
        stability=stability,
        stability_k=5,
        **_kwargs(),
    )
    assert "Stability check" in html
    assert "top-5" in html


def test_render_handles_nan_values_with_dash() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())
    # The B row has all-NaN ic/p; expect at least one em-dash for missing data.
    assert "—" in html


def test_render_universe_and_benchmark_listed() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())
    for ticker in ["VRT", "ETN", "GEV", "PWR", "CEG", "VST", "ANET", "MOD"]:
        assert ticker in html
    assert "XLK" in html
    assert "SPY" in html


def test_render_cost_and_thresholds_shown() -> None:
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    html = render_report(decision=decision_obj, summary_full=summary, **_kwargs())
    assert "95.50" in html
    assert "0.05" in html
    assert "0.55" in html


def test_render_html_safe_escaping() -> None:
    """Sector display name with HTML chars should be escaped."""
    summary = _annotate(_make_summary("positive"))
    decision_obj = decide(summary, ic_threshold=0.05, hit_rate_threshold=0.55, bh_alpha=0.05)
    kw = _kwargs()
    kw["display_name"] = "AI Infra <script>alert('xss')</script>"
    html = render_report(decision=decision_obj, summary_full=summary, **kw)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
