"""Tests for event-log CSV scaffolds — schema-only at this stage.

These CSVs are committed empty (header-only). Their schemas are part of the
contract with the panel builder (T9) and downstream Layer 3 event-study
consumers. Schema drift here is a binding violation of the pre-registration
(events as defined are locked at §3).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
EVENTS_DIR: Path = REPO_ROOT / "data" / "events" / "ai_infra"

EXPECTED_SCHEMAS: dict[str, list[str]] = {
    "earnings.csv": [
        "ticker",
        "announcement_date",
        "fiscal_quarter",
        "estimate_eps",
        "actual_eps",
        "sue",
        "has_consensus",
        "surprise_sign",
    ],
    "ppa.csv": [
        "ticker",
        "announce_date",
        "counterparty",
        "deal_mw",
        "source_url",
        "note",
    ],
    "orders.csv": [
        "ticker",
        "announce_date",
        "deal_value_usd",
        "backlog_change_pct",
        "source_url",
        "note",
    ],
    "shocks.csv": [
        "event_date",
        "event_type",
        "description",
        "xlk_t1_return",
        "source_url",
    ],
    "analyst.csv": [
        "ticker",
        "event_date",
        "bank",
        "action",
        "old_target",
        "new_target",
        "target_change_pct",
        "source_url",
    ],
}


@pytest.mark.parametrize("filename", sorted(EXPECTED_SCHEMAS.keys()))
def test_event_csv_schema_present(filename: str) -> None:
    path = EVENTS_DIR / filename
    assert path.is_file(), f"missing event CSV: {path}"
    df = pd.read_csv(path)
    expected = EXPECTED_SCHEMAS[filename]
    assert list(df.columns) == expected, (
        f"{filename}: column drift — expected {expected}, got {list(df.columns)}"
    )


def test_all_five_categories_present() -> None:
    """Five committed CSVs (one per prereg §3 category)."""
    files = {p.name for p in EVENTS_DIR.glob("*.csv")}
    assert files == set(EXPECTED_SCHEMAS.keys()), (
        f"missing or extra event files: got {files}, expected {set(EXPECTED_SCHEMAS.keys())}"
    )
