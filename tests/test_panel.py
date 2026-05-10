"""Tests for catalystlab.ingestion.panel."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from catalystlab.config.schemas import (
    Benchmarks,
    CostModel,
    EventCategory,
    Period,
    SectorConfig,
    StatsConfig,
    Threshold,
    TickerEntry,
)
from catalystlab.ingestion.panel import (
    PANEL_COLUMNS,
    _normalize_event_to_panel,
    build_panel,
    load_event_logs,
)


def _mini_sector(universe: list[str]) -> SectorConfig:
    """Build a minimal SectorConfig for tests."""
    return SectorConfig(
        sector="test",
        display_name="Test",
        prereg_version="1.0",
        prereg_lockfile_date=date(2026, 1, 1),
        random_seed=42,
        period=Period(start=date(2024, 1, 1), end=date(2024, 12, 31)),
        universe=[
            TickerEntry(ticker=t, name=t, market="NYSE", type="x") for t in universe
        ],
        benchmarks=Benchmarks(
            primary="XLK",
            secondary="SPY",
            beta_window_days=252,
            beta_exclusion_window_days=30,
        ),
        holding_windows=[1, 5, 20, 60],
        categories={
            "A": EventCategory(
                name="earnings",
                description="x",
                hypothesis="x",
                magnitude_metric="SUE",
                source="yfinance",
                threshold=Threshold(type="abs_gt", value=1.0),
            ),
            "B": EventCategory(
                name="ppa", description="x", hypothesis="x",
                magnitude_metric="binary", source="manual",
            ),
            "C": EventCategory(
                name="orders", description="x", hypothesis="x",
                magnitude_metric="usd", source="manual",
            ),
            "D": EventCategory(
                name="shocks", description="x", hypothesis="x",
                magnitude_metric="proxy", source="manual",
            ),
            "E": EventCategory(
                name="analyst", description="x", hypothesis="x",
                magnitude_metric="pct", source="manual",
            ),
        },
        costs=CostModel(
            commission_per_execution_eur=3.65,
            spread_round_trip_bps=7.5,
            fx_round_trip_bps=15.0,
            default_position_size_eur=1000.0,
        ),
        stats=StatsConfig(
            ic_threshold=0.05,
            hit_rate_threshold=0.55,
            bh_alpha=0.05,
            bootstrap_n=1000,
            bootstrap_ci=0.95,
        ),
    )


def _mini_prices(tickers: list[str], dates: list[str]) -> pd.DataFrame:
    rows = []
    for t in tickers:
        for i, d in enumerate(dates):
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "ticker": t,
                    "open": 100.0 + i,
                    "high": 102.0 + i,
                    "low": 99.0 + i,
                    "close": 101.0 + i,
                    "adj_close": 100.0 + i * 1.01,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


# ---------- build_panel ----------


def test_build_panel_empty_prices_returns_empty() -> None:
    panel = build_panel(_mini_sector(["VRT"]), pd.DataFrame(), {})
    assert list(panel.columns) == PANEL_COLUMNS
    assert panel.empty


def test_build_panel_basic_shape() -> None:
    sector = _mini_sector(["VRT", "ANET"])
    prices = _mini_prices(["VRT", "ANET", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = build_panel(sector, prices, {})

    # Universe only (XLK excluded from panel rows; used as benchmark).
    assert set(panel["ticker"].unique()) == {"VRT", "ANET"}
    assert list(panel.columns) == PANEL_COLUMNS
    # 2 tickers x 3 dates = 6 rows
    assert len(panel) == 6


def test_build_panel_returns_first_row_nan() -> None:
    sector = _mini_sector(["VRT"])
    prices = _mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03"])
    panel = build_panel(sector, prices, {})
    # First row per ticker: pct_change = NaN.
    assert pd.isna(panel.iloc[0]["return"])
    assert not pd.isna(panel.iloc[1]["return"])


def test_build_panel_ar_proxy_is_simple_diff() -> None:
    sector = _mini_sector(["VRT"])
    # VRT adj_close: 100.0, 101.01, 102.02 → returns approx 0, 0.0101, 0.01000099
    # XLK same series → r_xlk identical → ar = 0
    prices = _mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
    panel = build_panel(sector, prices, {})
    non_nan = panel[panel["return"].notna()]
    assert (non_nan["ar_vs_xlk_proxy"].abs() < 1e-9).all()


def test_build_panel_event_join_category_a() -> None:
    sector = _mini_sector(["VRT"])
    prices = _mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03", "2024-01-04"])
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
    sector = _mini_sector(["VRT"])
    prices = _mini_prices(["VRT", "XLK"], ["2024-01-02", "2024-01-03"])
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
    sector = _mini_sector(["VRT", "ANET"])
    prices = _mini_prices(["VRT", "ANET", "XLK"], ["2024-01-02", "2024-01-03"])
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
