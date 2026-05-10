"""Tests for catalystlab.ingestion.panel."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from catalystlab.ingestion.panel import (
    PANEL_COLUMNS,
    _normalize_event_to_panel,
    build_panel,
    load_event_logs,
)
from tests.conftest import make_mini_prices, make_mini_sector

# ---------- build_panel ----------


def test_build_panel_empty_prices_returns_empty() -> None:
    panel = build_panel(make_mini_sector(["VRT"]), pd.DataFrame(), {})
    assert list(panel.columns) == PANEL_COLUMNS
    assert panel.empty


def test_build_panel_basic_shape() -> None:
    sector = make_mini_sector(["VRT", "ANET"])
    prices = make_mini_prices(["VRT", "ANET", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = build_panel(sector, prices, {})

    # Universe only (XLK excluded from panel rows; used as benchmark).
    assert set(panel["ticker"].unique()) == {"VRT", "ANET"}
    assert list(panel.columns) == PANEL_COLUMNS
    # 2 tickers x 3 dates = 6 rows
    assert len(panel) == 6


def test_build_panel_returns_first_row_nan() -> None:
    sector = make_mini_sector(["VRT"])
    prices = make_mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03"])
    panel = build_panel(sector, prices, {})
    # First row per ticker: pct_change = NaN.
    assert pd.isna(panel.iloc[0]["return"])
    assert not pd.isna(panel.iloc[1]["return"])


def test_build_panel_ar_proxy_is_simple_diff() -> None:
    sector = make_mini_sector(["VRT"])
    # VRT adj_close: 100.0, 101.01, 102.02 → returns approx 0, 0.0101, 0.01000099
    # XLK same series → r_xlk identical → ar = 0
    prices = make_mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = build_panel(sector, prices, {})
    non_nan = panel[panel["return"].notna()]
    assert (non_nan["ar_vs_xlk_proxy"].abs() < 1e-9).all()


def test_build_panel_event_join_category_a() -> None:
    sector = make_mini_sector(["VRT"])
    prices = make_mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
    earnings_csv = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": ["2024-01-03"],
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.5],
            "sue": [2.5],
            "has_consensus": [True],
            "surprise_sign": [1.0],
        }
    )
    events = {"A": earnings_csv}
    panel = build_panel(sector, prices, events)

    row_event = panel[(panel["ticker"] == "VRT") & (panel["date"] == pd.Timestamp("2024-01-03"))]
    assert row_event["event_type"].iloc[0] == "A"
    assert row_event["event_magnitude"].iloc[0] == 2.5

    row_no_event = panel[(panel["ticker"] == "VRT") & (panel["date"] == pd.Timestamp("2024-01-02"))]
    assert pd.isna(row_no_event["event_type"].iloc[0])


def test_build_panel_priority_a_over_b_on_overlap() -> None:
    sector = make_mini_sector(["VRT"])
    prices = make_mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03"])
    earnings = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": ["2024-01-03"],
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.5],
            "sue": [2.5],
            "has_consensus": [True],
            "surprise_sign": [1.0],
        }
    )
    ppa = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announce_date": ["2024-01-03"],
            "counterparty": ["MSFT"],
            "deal_mw": [500.0],
            "source_url": ["x"],
            "note": [""],
        }
    )
    panel = build_panel(sector, prices, {"A": earnings, "B": ppa})
    row = panel[(panel["ticker"] == "VRT") & (panel["date"] == pd.Timestamp("2024-01-03"))]
    # Category A wins per CATEGORY_PRIORITY.
    assert row["event_type"].iloc[0] == "A"
    assert row["event_magnitude"].iloc[0] == 2.5


def test_build_panel_shocks_broadcast() -> None:
    sector = make_mini_sector(["VRT", "ANET"])
    prices = make_mini_prices(["VRT", "ANET", "XLK"], ["2024-01-02", "2024-01-03"])
    shocks = pd.DataFrame(
        {
            "event_date": ["2024-01-03"],
            "event_type": ["gpu_export"],
            "description": ["x"],
            "xlk_t1_return": [-0.05],
            "source_url": ["x"],
        }
    )
    panel = build_panel(sector, prices, {"D": shocks})
    rows = panel[panel["date"] == pd.Timestamp("2024-01-03")]
    assert (rows["event_type"] == "D").all()
    assert (rows["event_magnitude"] == -0.05).all()
    assert set(rows["ticker"].unique()) == {"VRT", "ANET"}


# ---------- _normalize_event_to_panel ----------


def test_normalize_unknown_category_raises() -> None:
    with pytest.raises(ValueError, match="unknown event category"):
        _normalize_event_to_panel(pd.DataFrame({"a": [1]}), "X", {"VRT"})


def test_normalize_empty_returns_empty() -> None:
    out = _normalize_event_to_panel(pd.DataFrame(), "A", {"VRT"})
    assert out.empty
    assert list(out.columns) == ["ticker", "date", "event_type", "event_magnitude"]


def test_normalize_c_uses_backlog_fallback() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announce_date": ["2024-01-03"],
            "deal_value_usd": [np.nan],
            "backlog_change_pct": [0.15],
            "source_url": ["x"],
            "note": [""],
        }
    )
    out = _normalize_event_to_panel(df, "C", {"VRT"})
    assert out["event_magnitude"].iloc[0] == 0.15


def test_normalize_e_uses_target_change_pct() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "event_date": ["2024-01-03"],
            "bank": ["Goldman Sachs"],
            "action": ["upgrade"],
            "old_target": [100.0],
            "new_target": [120.0],
            "target_change_pct": [0.20],
            "source_url": ["x"],
        }
    )
    out = _normalize_event_to_panel(df, "E", {"VRT"})
    assert out["event_magnitude"].iloc[0] == 0.20


def test_normalize_filters_to_universe() -> None:
    df = pd.DataFrame(
        {
            "ticker": ["VRT", "FOO"],
            "announcement_date": ["2024-01-02", "2024-01-03"],
            "estimate_eps": [1.0, 1.0],
            "actual_eps": [1.5, 1.5],
            "sue": [2.0, 2.0],
            "has_consensus": [True, True],
            "surprise_sign": [1.0, 1.0],
            "fiscal_quarter": [pd.NA, pd.NA],
        }
    )
    out = _normalize_event_to_panel(df, "A", {"VRT"})
    assert out["ticker"].tolist() == ["VRT"]


# ---------- load_event_logs ----------


def test_load_event_logs_reads_real_scaffolds() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    events_dir = repo_root / "data" / "events" / "ai_infra"
    out = load_event_logs(events_dir)
    # All 5 categories present (header-only CSVs at scaffold stage).
    assert set(out.keys()) == {"A", "B", "C", "D", "E"}
    for cat, df in out.items():
        # Header-only → empty rows but columns set.
        assert df.empty or "ticker" in df.columns or cat == "D"


def test_load_event_logs_missing_file(tmp_path: Path) -> None:
    out = load_event_logs(tmp_path)  # no files at all
    assert out == {}


# ---------- enumerate_all_events (W2 T6) ----------


from catalystlab.ingestion.panel import enumerate_all_events  # noqa: E402


def test_enumerate_all_events_preserves_overlap() -> None:
    """Two E events on same (ticker, date) survive (no priority dedup)."""
    sector = make_mini_sector(["VRT"])
    analyst_two_same_day = pd.DataFrame(
        {
            "ticker": ["VRT", "VRT"],
            "event_date": ["2024-01-03", "2024-01-03"],
            "bank": ["Goldman Sachs", "Morgan Stanley"],
            "action": ["target_change", "target_change"],
            "old_target": [100.0, 100.0],
            "new_target": [120.0, 130.0],
            "target_change_pct": [0.20, 0.30],
            "source_url": ["x", "y"],
        }
    )
    out = enumerate_all_events(sector, {"E": analyst_two_same_day})
    assert len(out) == 2
    assert (out["event_type"] == "E").all()
    assert sorted(out["event_magnitude"].tolist()) == [0.20, 0.30]


def test_enumerate_all_events_preserves_cross_category_overlap() -> None:
    """Earnings + analyst on same (ticker, date) both preserved."""
    sector = make_mini_sector(["VRT"])
    earnings = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": ["2024-01-03"],
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.5],
            "sue": [2.5],
            "has_consensus": [True],
            "surprise_sign": [1.0],
        }
    )
    analyst = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "event_date": ["2024-01-03"],
            "bank": ["Goldman Sachs"],
            "action": ["target_change"],
            "old_target": [100.0],
            "new_target": [120.0],
            "target_change_pct": [0.20],
            "source_url": ["x"],
        }
    )
    out = enumerate_all_events(sector, {"A": earnings, "E": analyst})
    assert len(out) == 2
    assert set(out["event_type"].unique()) == {"A", "E"}


def test_enumerate_all_events_empty_input() -> None:
    sector = make_mini_sector(["VRT"])
    out = enumerate_all_events(sector, {})
    assert out.empty
    assert list(out.columns) == ["ticker", "date", "event_type", "event_magnitude"]


def test_build_panel_collapses_overlap_first_wins() -> None:
    """Counterpart documenting build_panel's policy: earlier category wins."""
    sector = make_mini_sector(["VRT"])
    prices = make_mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03"])
    earnings = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": ["2024-01-03"],
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.5],
            "sue": [2.5],
            "has_consensus": [True],
            "surprise_sign": [1.0],
        }
    )
    analyst = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "event_date": ["2024-01-03"],
            "bank": ["Goldman Sachs"],
            "action": ["target_change"],
            "old_target": [100.0],
            "new_target": [120.0],
            "target_change_pct": [0.20],
            "source_url": ["x"],
        }
    )
    panel = build_panel(sector, prices, {"A": earnings, "E": analyst})
    row = panel[(panel["ticker"] == "VRT") & (panel["date"] == pd.Timestamp("2024-01-03"))]
    assert row["event_type"].iloc[0] == "A"
