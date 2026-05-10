"""Shared pytest fixtures for catalystlab tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

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


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def real_sectors_dir(repo_root: Path) -> Path:
    return repo_root / "sectors"


@pytest.fixture(scope="session")
def real_events_dir(repo_root: Path) -> Path:
    return repo_root / "data" / "events" / "ai_infra"


def make_mini_sector(universe: list[str]) -> SectorConfig:
    """Build a minimal valid SectorConfig for tests.

    Tests should prefer the `mini_sector` fixture; this function exists for
    parametrised cases that need to vary the universe per test.
    """
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
                name="ppa",
                description="x",
                hypothesis="x",
                magnitude_metric="binary",
                source="manual",
            ),
            "C": EventCategory(
                name="orders",
                description="x",
                hypothesis="x",
                magnitude_metric="usd",
                source="manual",
            ),
            "D": EventCategory(
                name="shocks",
                description="x",
                hypothesis="x",
                magnitude_metric="proxy",
                source="manual",
            ),
            "E": EventCategory(
                name="analyst",
                description="x",
                hypothesis="x",
                magnitude_metric="pct",
                source="manual",
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


@pytest.fixture
def mini_sector() -> SectorConfig:
    """Minimal SectorConfig with universe = [VRT, ANET]."""
    return make_mini_sector(["VRT", "ANET"])


def make_mini_prices(tickers: list[str], dates: list[str]) -> pd.DataFrame:
    """Build a synthetic long-format prices DataFrame for tests."""
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


@pytest.fixture
def prereg_cost_model() -> CostModel:
    """Prereg §5 reference cost model (Interpretation B, round-trip totals)."""
    return CostModel(
        commission_per_execution_eur=3.65,
        spread_round_trip_bps=7.5,
        fx_round_trip_bps=15.0,
        default_position_size_eur=1000.0,
    )
