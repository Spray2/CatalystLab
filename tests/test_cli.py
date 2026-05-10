"""Tests for catalystlab.cli — argparse parsing + orchestration smoke."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from catalystlab.cli import main


def test_main_no_subcommand_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])


def test_build_panel_requires_sector(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["build-panel"])


def test_build_panel_orchestration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end CLI smoke with mocked fetchers, real YAML, real CSV scaffolds.

    Runs the full orchestrator from a temp working directory holding a copy
    of the sectors/ + data/events/ scaffolds, with mocked yfinance fetchers
    so the test is hermetic.
    """
    repo_root = Path(__file__).resolve().parent.parent

    # Build a temp project workdir.
    sectors_dir = tmp_path / "sectors"
    sectors_dir.mkdir()
    (sectors_dir / "ai_infra.yaml").write_bytes(
        (repo_root / "sectors" / "ai_infra.yaml").read_bytes()
    )

    events_dir = tmp_path / "data" / "events" / "ai_infra"
    events_dir.mkdir(parents=True)
    for fname in ("ppa.csv", "orders.csv", "shocks.csv", "analyst.csv"):
        (events_dir / fname).write_bytes(
            (repo_root / "data" / "events" / "ai_infra" / fname).read_bytes()
        )

    # Mocks: fetch_prices returns a tiny synthetic frame for the universe + benchmarks.
    universe_tickers = ["VRT", "ETN", "GEV", "PWR", "CEG", "VST", "ANET", "MOD"]
    bench_tickers = ["XLK", "SPY"]
    all_tickers = universe_tickers + bench_tickers
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])

    def fake_fetch_prices(*args, **kwargs):
        rows = []
        for t in all_tickers:
            for i, d in enumerate(dates):
                rows.append(
                    {
                        "date": d,
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

    def fake_fetch_earnings(*args, **kwargs):
        return pd.DataFrame(
            {
                "ticker": ["VRT"],
                "announcement_date": pd.to_datetime(["2024-01-03"]),
                "fiscal_quarter": [pd.NA],
                "estimate_eps": [1.0],
                "actual_eps": [1.5],
                "sue": [2.5],
                "has_consensus": [True],
                "surprise_sign": [1.0],
            }
        )

    monkeypatch.chdir(tmp_path)

    with (
        patch("catalystlab.cli.fetch_prices", side_effect=fake_fetch_prices),
        patch("catalystlab.cli.fetch_earnings", side_effect=fake_fetch_earnings),
    ):
        rc = main(["build-panel", "--sector", "ai_infra", "--no-cache", "--sleep", "0"])

    assert rc == 0
    panel_path = tmp_path / "data" / "processed" / "panel_ai_infra.parquet"
    assert panel_path.is_file()
    panel = pd.read_parquet(panel_path)
    # Universe (8) x dates (3) = 24 rows.
    assert len(panel) == 24
    assert set(panel["ticker"].unique()) == set(universe_tickers)
    # The earnings event row should have event_type == "A".
    vrt_event = panel[
        (panel["ticker"] == "VRT") & (panel["date"] == pd.Timestamp("2024-01-03"))
    ]
    assert vrt_event["event_type"].iloc[0] == "A"

    # Manifest emitted.
    manifest_files = list((tmp_path / "data" / "manifests").glob("*.json"))
    assert len(manifest_files) == 1
