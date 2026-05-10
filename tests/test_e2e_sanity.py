"""End-to-end sanity check (W2 T9).

Loads the real panel parquet (if present) and runs the full
event-study pipeline with *random synthetic events*. The expectation
is that the IC for these null-events should be ≈ 0 — any large IC
under random-event injection signals a bug in beta/AR/CAR/IC plumbing.

If the panel parquet is absent (e.g. CI without yfinance fetch), the
test skips with a clear message instead of failing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from catalystlab.config.loader import load_sector
from catalystlab.eventstudy.abnormal_returns import compute_event_metrics
from catalystlab.eventstudy.ic import compute_ic

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
PANEL_PATH: Path = REPO_ROOT / "data" / "processed" / "panel_ai_infra.parquet"
BENCH_CACHE: Path = REPO_ROOT / "data" / "raw" / "prices" / "XLK.parquet"

NULL_IC_TOLERANCE: float = 0.20  # within finite-sample noise for ~50 events


@pytest.mark.skipif(
    not PANEL_PATH.is_file() or not BENCH_CACHE.is_file(),
    reason="panel or benchmark cache not present; run `build-panel --sector ai_infra` first",
)
def test_null_event_signal_yields_small_ic() -> None:
    sector_cfg, _ = load_sector(
        "ai_infra", sectors_dir=REPO_ROOT / "sectors"
    )

    panel = pd.read_parquet(PANEL_PATH)
    panel["date"] = pd.to_datetime(panel["date"])

    bench_raw = pd.read_parquet(BENCH_CACHE).sort_values("date")
    bench_returns = bench_raw.set_index("date")["adj_close"].pct_change().dropna()

    # Generate random synthetic events: pick 50 random (ticker, date) pairs
    # from the panel and assign a random magnitude that is INDEPENDENT of
    # the actual return.
    rng = np.random.default_rng(0)
    universe_tickers = [t.ticker for t in sector_cfg.universe]
    panel_universe = panel[panel["ticker"].isin(universe_tickers)].copy()
    # Restrict to dates with enough history for beta estimation (skip first year).
    min_date = panel_universe["date"].min() + pd.Timedelta(days=400)
    eligible = panel_universe[
        (panel_universe["date"] >= min_date) & (panel_universe["return"].notna())
    ]
    sample = eligible.sample(n=50, random_state=42)
    null_events = pd.DataFrame(
        {
            "ticker": sample["ticker"].values,
            "date": sample["date"].values,
            "event_type": ["NULL"] * len(sample),
            "event_magnitude": rng.normal(0, 1, len(sample)),
        }
    )

    metrics = compute_event_metrics(
        panel,
        bench_returns,
        holding_windows=[1, 5, 20],
        beta_window_days=sector_cfg.benchmarks.beta_window_days,
        beta_exclusion_days=sector_cfg.benchmarks.beta_exclusion_window_days,
        events_override=null_events,
    )
    ic = compute_ic(metrics)

    # Drop NaN ICs (e.g. groups with too few valid pairs).
    valid_ic = ic.dropna(subset=["ic"])
    assert not valid_ic.empty, "no valid IC produced — pipeline returned all NaN"
    for _, row in valid_ic.iterrows():
        assert abs(row["ic"]) < NULL_IC_TOLERANCE, (
            f"null-event IC too large at {row['event_type']}/{row['holding_window']}: "
            f"{row['ic']:.4f} (tolerance {NULL_IC_TOLERANCE})"
        )
