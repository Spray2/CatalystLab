"""Tests for catalystlab.paper_trading (W5 L2 semi-auto automation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from catalystlab.paper_trading import (
    PAPER_TRADE_COLUMNS,
    VALID_STATUSES,
    _next_trading_day,
    detect_new_candidates,
    empty_paper_csv,
    load_paper_csv,
    paper_tick,
    transition_rows,
)
from tests.conftest import make_mini_sector

# ---------- schema + IO ----------


def test_empty_paper_csv_writes_schema(tmp_path: Path) -> None:
    p = tmp_path / "paper.csv"
    empty_paper_csv(p)
    df = pd.read_csv(p)
    assert list(df.columns) == PAPER_TRADE_COLUMNS
    assert df.empty


def test_load_paper_csv_missing_returns_empty_schema(tmp_path: Path) -> None:
    df = load_paper_csv(tmp_path / "nonexistent.csv")
    assert list(df.columns) == PAPER_TRADE_COLUMNS
    assert df.empty


def test_valid_statuses_set() -> None:
    assert {"pending_review", "approved", "rejected", "in_flight", "closed"} == VALID_STATUSES


# ---------- next trading day ----------


def test_next_trading_day_skips_weekend() -> None:
    # Friday 2024-01-05 -> next session = Monday 2024-01-08
    friday = pd.Timestamp("2024-01-05")
    nxt = _next_trading_day(friday, n=1)
    assert nxt == pd.Timestamp("2024-01-08")


def test_next_trading_day_n_sessions_ahead() -> None:
    # 60 sessions after 2024-01-02 ~= late March 2024
    start = pd.Timestamp("2024-01-02")
    sixty = _next_trading_day(start, n=60)
    # 60 trading days ~= 88 calendar days
    diff_days = (sixty - start).days
    assert 85 <= diff_days <= 95


# ---------- detect_new_candidates ----------


def test_detect_new_candidates_filters_by_sue_threshold() -> None:
    sector = make_mini_sector(["VRT", "ANET"])
    existing = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)

    fake_earnings = pd.DataFrame(
        {
            "ticker": ["VRT", "ANET", "VRT"],
            "announcement_date": pd.to_datetime(["2024-01-15", "2024-02-15", "2024-03-15"]),
            "fiscal_quarter": [pd.NA, pd.NA, pd.NA],
            "estimate_eps": [1.0, 1.0, 1.0],
            "actual_eps": [1.1, 1.5, 1.0],
            "sue": [0.5, 2.0, 0.0],  # only ANET passes |SUE|>1.0
            "has_consensus": [True, True, True],
            "surprise_sign": [1.0, 1.0, 0.0],
        }
    )
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=fake_earnings):
        new = detect_new_candidates(sector, existing, sue_threshold=1.0)

    assert len(new) == 1
    assert new.iloc[0]["ticker"] == "ANET"
    assert new.iloc[0]["status"] == "pending_review"
    assert new.iloc[0]["sue"] == 2.0
    assert new.iloc[0]["sue_sign"] == 1


def test_detect_new_candidates_excludes_existing() -> None:
    sector = make_mini_sector(["VRT"])
    existing = pd.DataFrame(
        [
            {
                "trade_id": 1,
                "ticker": "VRT",
                "event_date": "2024-01-15",
                "sue": 2.0,
                "sue_sign": 1,
                "status": "approved",
                "entry_date": "",
                "entry_price": float("nan"),
                "exit_date": "",
                "exit_price": float("nan"),
                "gross_return": float("nan"),
                "cost_bps": float("nan"),
                "net_return": float("nan"),
                "notes": "",
            }
        ]
    )
    fake_earnings = pd.DataFrame(
        {
            "ticker": ["VRT", "VRT"],
            "announcement_date": pd.to_datetime(["2024-01-15", "2024-04-15"]),
            "fiscal_quarter": [pd.NA, pd.NA],
            "estimate_eps": [1.0, 1.0],
            "actual_eps": [1.2, 1.3],
            "sue": [2.0, 1.5],
            "has_consensus": [True, True],
            "surprise_sign": [1.0, 1.0],
        }
    )
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=fake_earnings):
        new = detect_new_candidates(sector, existing, sue_threshold=1.0)

    # Existing 2024-01-15 excluded, new 2024-04-15 included.
    assert len(new) == 1
    assert new.iloc[0]["event_date"] == "2024-04-15"


def test_detect_new_candidates_trade_id_continues_sequence() -> None:
    sector = make_mini_sector(["VRT"])
    existing = pd.DataFrame(
        [
            {
                "trade_id": 5, "ticker": "X", "event_date": "2024-01-01",
                "sue": 2.0, "sue_sign": 1, "status": "closed",
                "entry_date": "", "entry_price": float("nan"),
                "exit_date": "", "exit_price": float("nan"),
                "gross_return": float("nan"), "cost_bps": float("nan"),
                "net_return": float("nan"), "notes": "",
            }
        ]
    )
    fake_earnings = pd.DataFrame(
        {
            "ticker": ["VRT"], "announcement_date": pd.to_datetime(["2024-05-01"]),
            "fiscal_quarter": [pd.NA], "estimate_eps": [1.0], "actual_eps": [1.5],
            "sue": [2.0], "has_consensus": [True], "surprise_sign": [1.0],
        }
    )
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=fake_earnings):
        new = detect_new_candidates(sector, existing, sue_threshold=1.0)
    assert new.iloc[0]["trade_id"] == 6


def test_detect_new_candidates_filters_by_min_event_date() -> None:
    """Old earnings before min_event_date are excluded (no back-flooding)."""
    sector = make_mini_sector(["VRT"])
    existing = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    fake_earnings = pd.DataFrame(
        {
            "ticker": ["VRT", "VRT"],
            "announcement_date": pd.to_datetime(["2021-01-15", "2026-04-15"]),
            "fiscal_quarter": [pd.NA, pd.NA],
            "estimate_eps": [1.0, 1.0],
            "actual_eps": [1.5, 1.5],
            "sue": [2.0, 2.0],
            "has_consensus": [True, True],
            "surprise_sign": [1.0, 1.0],
        }
    )
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=fake_earnings):
        new = detect_new_candidates(
            sector,
            existing,
            sue_threshold=1.0,
            min_event_date=pd.Timestamp("2026-01-01"),
        )
    assert len(new) == 1
    assert new.iloc[0]["event_date"] == "2026-04-15"


def test_detect_new_candidates_empty_earnings_returns_empty() -> None:
    sector = make_mini_sector(["VRT"])
    existing = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    with patch(
        "catalystlab.paper_trading.fetch_earnings",
        return_value=pd.DataFrame(),
    ):
        new = detect_new_candidates(sector, existing)
    assert new.empty
    assert list(new.columns) == PAPER_TRADE_COLUMNS


# ---------- transition_rows ----------


def _approved_row(trade_id: int, ticker: str, event_date: str, sign: int = 1) -> dict:
    return {
        "trade_id": trade_id, "ticker": ticker, "event_date": event_date,
        "sue": 2.0, "sue_sign": sign, "status": "approved",
        "entry_date": "", "entry_price": float("nan"),
        "exit_date": "", "exit_price": float("nan"),
        "gross_return": float("nan"), "cost_bps": float("nan"),
        "net_return": float("nan"), "notes": "",
    }


def test_transition_approved_to_in_flight() -> None:
    sector = make_mini_sector(["VRT"])
    rows = pd.DataFrame([_approved_row(1, "VRT", "2024-01-15")])
    today = pd.Timestamp("2024-01-20")  # past T+1

    with patch(
        "catalystlab.paper_trading._fetch_close_on",
        return_value=100.0,
    ):
        out, n_if, n_cl = transition_rows(rows, sector, today)

    assert n_if == 1
    assert n_cl == 0
    assert out.iloc[0]["status"] == "in_flight"
    assert out.iloc[0]["entry_price"] == 100.0
    assert out.iloc[0]["entry_date"] == "2024-01-16"  # next trading day


def test_transition_approved_not_yet_t1_stays() -> None:
    sector = make_mini_sector(["VRT"])
    rows = pd.DataFrame([_approved_row(1, "VRT", "2024-01-15")])
    today = pd.Timestamp("2024-01-15")  # T+0 still — no entry yet
    out, n_if, _ = transition_rows(rows, sector, today)
    assert n_if == 0
    assert out.iloc[0]["status"] == "approved"


def test_transition_in_flight_to_closed_positive_sign() -> None:
    sector = make_mini_sector(["VRT"])
    row = _approved_row(1, "VRT", "2024-01-15", sign=1)
    row["status"] = "in_flight"
    row["entry_date"] = "2024-01-16"
    row["entry_price"] = 100.0
    rows = pd.DataFrame([row])
    # T+60 ~= mid-April 2024 -> use a far-future date.
    today = pd.Timestamp("2024-05-01")

    with patch(
        "catalystlab.paper_trading._fetch_close_on",
        return_value=110.0,  # +10% from entry
    ):
        out, _, n_cl = transition_rows(rows, sector, today)

    assert n_cl == 1
    assert out.iloc[0]["status"] == "closed"
    assert out.iloc[0]["exit_price"] == 110.0
    # gross = +0.10 * sign(+1) = +0.10; net = 0.10 - 95.5/10000 = 0.09045
    assert out.iloc[0]["gross_return"] == pytest.approx(0.10, abs=1e-9)
    assert out.iloc[0]["net_return"] == pytest.approx(0.10 - 0.00955, abs=1e-9)


def test_transition_in_flight_negative_sue_inverts_direction() -> None:
    """sue_sign=-1 (miss): paper trade is a SHORT, return = -(exit-entry)/entry."""
    sector = make_mini_sector(["VRT"])
    row = _approved_row(1, "VRT", "2024-01-15", sign=-1)
    row["status"] = "in_flight"
    row["entry_date"] = "2024-01-16"
    row["entry_price"] = 100.0
    rows = pd.DataFrame([row])
    today = pd.Timestamp("2024-05-01")

    with patch(
        "catalystlab.paper_trading._fetch_close_on",
        return_value=90.0,  # -10% from entry
    ):
        out, _, n_cl = transition_rows(rows, sector, today)

    assert n_cl == 1
    # raw = -0.10; sue_sign=-1; gross = -0.10 * -1 = +0.10
    assert out.iloc[0]["gross_return"] == pytest.approx(0.10, abs=1e-9)


def test_transition_rejected_unchanged() -> None:
    sector = make_mini_sector(["VRT"])
    row = _approved_row(1, "VRT", "2024-01-15")
    row["status"] = "rejected"
    rows = pd.DataFrame([row])
    today = pd.Timestamp("2024-05-01")
    out, n_if, n_cl = transition_rows(rows, sector, today)
    assert n_if == 0 and n_cl == 0
    assert out.iloc[0]["status"] == "rejected"


def test_transition_pending_review_unchanged() -> None:
    sector = make_mini_sector(["VRT"])
    row = _approved_row(1, "VRT", "2024-01-15")
    row["status"] = "pending_review"
    rows = pd.DataFrame([row])
    today = pd.Timestamp("2024-05-01")
    out, n_if, n_cl = transition_rows(rows, sector, today)
    # Pending rows are NOT auto-promoted; the human approval is required.
    assert n_if == 0 and n_cl == 0
    assert out.iloc[0]["status"] == "pending_review"


# ---------- paper_tick end-to-end ----------


def test_paper_tick_creates_csv_and_appends_candidate(tmp_path: Path) -> None:
    sector = make_mini_sector(["VRT"])
    csv = tmp_path / "paper.csv"

    fake_earnings = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": pd.to_datetime(["2024-01-15"]),
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.5],
            "sue": [2.0],
            "has_consensus": [True],
            "surprise_sign": [1.0],
        }
    )
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=fake_earnings):
        summary = paper_tick(sector, csv, today=pd.Timestamp("2024-01-10"))

    assert summary["new_candidates"] == 1
    assert csv.is_file()
    loaded = pd.read_csv(csv)
    assert loaded.iloc[0]["status"] == "pending_review"


def test_paper_tick_full_lifecycle(tmp_path: Path) -> None:
    """A 3-tick lifecycle: detect -> approve (manual) -> in_flight -> closed."""
    sector = make_mini_sector(["VRT"])
    csv = tmp_path / "paper.csv"

    earnings = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": pd.to_datetime(["2024-01-15"]),
            "fiscal_quarter": [pd.NA], "estimate_eps": [1.0], "actual_eps": [1.5],
            "sue": [2.0], "has_consensus": [True], "surprise_sign": [1.0],
        }
    )

    # Tick 1: detect candidate
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=earnings):
        paper_tick(sector, csv, today=pd.Timestamp("2024-01-10"))

    # Manual: user verifies IR + approves
    df = pd.read_csv(csv)
    df.loc[df["ticker"] == "VRT", "status"] = "approved"
    df.to_csv(csv, index=False)

    # Tick 2: approved -> in_flight (today >= T+1)
    with (
        patch("catalystlab.paper_trading.fetch_earnings", return_value=earnings),
        patch("catalystlab.paper_trading._fetch_close_on", return_value=100.0),
    ):
        summary2 = paper_tick(sector, csv, today=pd.Timestamp("2024-01-20"))
    assert summary2["transitioned_in_flight"] == 1
    df = pd.read_csv(csv)
    assert df.iloc[0]["status"] == "in_flight"

    # Tick 3: in_flight -> closed (today >= T+60)
    with (
        patch("catalystlab.paper_trading.fetch_earnings", return_value=earnings),
        patch("catalystlab.paper_trading._fetch_close_on", return_value=120.0),
    ):
        summary3 = paper_tick(sector, csv, today=pd.Timestamp("2024-05-01"))
    assert summary3["transitioned_closed"] == 1
    df = pd.read_csv(csv)
    assert df.iloc[0]["status"] == "closed"
    assert df.iloc[0]["gross_return"] == pytest.approx(0.20, abs=1e-9)


def test_paper_tick_cumulative_pnl_aggregates(tmp_path: Path) -> None:
    sector = make_mini_sector(["VRT"])
    csv = tmp_path / "paper.csv"
    # Seed two closed trades.
    seed = pd.DataFrame(
        [
            {
                "trade_id": 1, "ticker": "VRT", "event_date": "2024-01-15",
                "sue": 2.0, "sue_sign": 1, "status": "closed",
                "entry_date": "2024-01-16", "entry_price": 100.0,
                "exit_date": "2024-04-10", "exit_price": 120.0,
                "gross_return": 0.20, "cost_bps": 95.5, "net_return": 0.19045,
                "notes": "",
            },
            {
                "trade_id": 2, "ticker": "VRT", "event_date": "2024-04-15",
                "sue": 2.0, "sue_sign": 1, "status": "closed",
                "entry_date": "2024-04-16", "entry_price": 120.0,
                "exit_date": "2024-07-10", "exit_price": 130.0,
                "gross_return": 0.0833, "cost_bps": 95.5, "net_return": 0.0738,
                "notes": "",
            },
        ]
    )
    seed.to_csv(csv, index=False)
    with patch("catalystlab.paper_trading.fetch_earnings", return_value=pd.DataFrame()):
        summary = paper_tick(sector, csv, today=pd.Timestamp("2024-08-01"))
    assert summary["cumulative_net_return"] == pytest.approx(0.19045 + 0.0738, abs=1e-4)
    assert summary["by_status"].get("closed", 0) == 2
