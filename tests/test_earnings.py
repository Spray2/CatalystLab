"""Tests for catalystlab.ingestion.earnings."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from catalystlab.ingestion.earnings import (
    EARNINGS_COLUMNS,
    _compute_sue,
    _fetch_one,
    fetch_earnings,
)

_RUN_INTEGRATION: bool = os.environ.get("CATALYSTLAB_RUN_INTEGRATION") == "1"


def _yf_earnings_payload(
    dates: list[str],
    estimates: list[float | None],
    actuals: list[float | None],
    *,
    tz: str | None = None,
) -> pd.DataFrame:
    """Build a yfinance get_earnings_dates() payload for tests."""
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Earnings Date")
    if tz is not None:
        idx = idx.tz_localize(tz)
    return pd.DataFrame(
        {
            "EPS Estimate": estimates,
            "Reported EPS": actuals,
        },
        index=idx,
    )


def _patch_yf(payload: pd.DataFrame | None):
    inst = MagicMock()
    inst.get_earnings_dates.return_value = payload
    return patch(
        "catalystlab.ingestion.earnings.yf.Ticker",
        return_value=inst,
    )


# ---------- _fetch_one ----------


def test_fetch_one_happy_path() -> None:
    payload = _yf_earnings_payload(
        ["2024-02-01", "2024-05-01"],
        estimates=[1.0, 1.1],
        actuals=[1.2, 1.0],
    )
    with _patch_yf(payload):
        df = _fetch_one("VRT", lookback_quarters=8)

    assert list(df.columns) == [
        "ticker",
        "announcement_date",
        "fiscal_quarter",
        "estimate_eps",
        "actual_eps",
    ]
    assert len(df) == 2
    assert df["ticker"].unique().tolist() == ["VRT"]


def test_fetch_one_strips_tz() -> None:
    payload = _yf_earnings_payload(
        ["2024-02-01"],
        estimates=[1.0],
        actuals=[1.2],
        tz="America/New_York",
    )
    with _patch_yf(payload):
        df = _fetch_one("VRT", lookback_quarters=8)

    assert df["announcement_date"].dt.tz is None


def test_fetch_one_etf_returns_empty() -> None:
    with _patch_yf(None):
        df = _fetch_one("SPY", lookback_quarters=8)

    assert df.empty


def test_fetch_one_yfinance_exception_returns_empty() -> None:
    inst = MagicMock()
    inst.get_earnings_dates.side_effect = RuntimeError("network down")
    with patch("catalystlab.ingestion.earnings.yf.Ticker", return_value=inst):
        df = _fetch_one("VRT", lookback_quarters=8)

    assert df.empty


# ---------- _compute_sue ----------


def test_compute_sue_with_sufficient_history() -> None:
    # 5 quarters: first 4 are priors (estimates 1.0, 1.0, 1.0, 1.0), 5th is current
    # std of priors = 0 → SUE undefined → has_consensus=False even with enough rows
    raw = pd.DataFrame(
        {
            "ticker": ["VRT"] * 5,
            "announcement_date": pd.to_datetime(
                ["2023-02-01", "2023-05-01", "2023-08-01", "2023-11-01", "2024-02-01"]
            ),
            "fiscal_quarter": [pd.NA] * 5,
            "estimate_eps": [1.0, 1.0, 1.0, 1.0, 1.0],
            "actual_eps": [1.0, 1.0, 1.0, 1.0, 1.5],
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    # Last row: priors std == 0 → has_consensus False
    assert out.iloc[-1]["has_consensus"] is False or pd.isna(out.iloc[-1]["sue"])
    # Surprise sign should still be set
    assert out.iloc[-1]["surprise_sign"] == 1.0


def test_compute_sue_real_formula() -> None:
    # Construct priors with known std. Estimates: [1.0, 1.5, 2.0, 2.5] → std (sample) ≈ 0.6455
    # Current row: estimate=2.0, actual=3.0 → surprise=1.0 → SUE = 1.0 / 0.6455 ≈ 1.549
    raw = pd.DataFrame(
        {
            "ticker": ["VRT"] * 5,
            "announcement_date": pd.to_datetime(
                ["2023-02-01", "2023-05-01", "2023-08-01", "2023-11-01", "2024-02-01"]
            ),
            "fiscal_quarter": [pd.NA] * 5,
            "estimate_eps": [1.0, 1.5, 2.0, 2.5, 2.0],
            "actual_eps": [1.0, 1.5, 2.0, 2.5, 3.0],
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    last = out.iloc[-1]
    assert last["has_consensus"] is True or last["has_consensus"] == np.True_
    expected_std = pd.Series([1.0, 1.5, 2.0, 2.5]).std(ddof=1)
    expected_sue = (3.0 - 2.0) / expected_std
    assert last["sue"] == pytest.approx(expected_sue, rel=1e-9)
    assert last["surprise_sign"] == 1.0


def test_compute_sue_insufficient_history_falls_back_to_binary() -> None:
    # Only 2 priors; min_estimates=4 → has_consensus=False, sue=NaN.
    raw = pd.DataFrame(
        {
            "ticker": ["VRT"] * 3,
            "announcement_date": pd.to_datetime(
                ["2023-02-01", "2023-05-01", "2023-08-01"]
            ),
            "fiscal_quarter": [pd.NA] * 3,
            "estimate_eps": [1.0, 1.5, 2.0],
            "actual_eps": [0.9, 1.6, 1.5],  # last row: actual < estimate → sign -1
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    last = out.iloc[-1]
    assert last["has_consensus"] is False or last["has_consensus"] == np.False_
    assert pd.isna(last["sue"])
    assert last["surprise_sign"] == -1.0


def test_compute_sue_missing_estimate_yields_nan_sign() -> None:
    raw = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": pd.to_datetime(["2024-02-01"]),
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [np.nan],
            "actual_eps": [1.0],
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    assert pd.isna(out.iloc[0]["sue"])
    assert pd.isna(out.iloc[0]["surprise_sign"])


def test_compute_sue_zero_surprise_sign_zero() -> None:
    # actual exactly matches estimate → sign 0
    raw = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": pd.to_datetime(["2024-02-01"]),
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.0],
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    assert out.iloc[0]["surprise_sign"] == 0.0


def test_compute_sue_per_ticker_isolation() -> None:
    # Two tickers; SUE for B should not borrow std from A's history.
    raw = pd.DataFrame(
        {
            "ticker": ["A", "A", "A", "A", "A", "B"],
            "announcement_date": pd.to_datetime(
                [
                    "2023-02-01",
                    "2023-05-01",
                    "2023-08-01",
                    "2023-11-01",
                    "2024-02-01",
                    "2024-02-01",
                ]
            ),
            "fiscal_quarter": [pd.NA] * 6,
            "estimate_eps": [1.0, 1.5, 2.0, 2.5, 2.0, 3.0],
            "actual_eps": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        }
    )
    out = _compute_sue(raw, window_quarters=8, min_estimates=4)
    a_last = out[(out["ticker"] == "A")].iloc[-1]
    b_only = out[(out["ticker"] == "B")].iloc[0]
    assert a_last["has_consensus"]
    # B has only 1 row → no priors, has_consensus False
    assert not b_only["has_consensus"]
    assert b_only["surprise_sign"] == 1.0


# ---------- fetch_earnings ----------


def test_fetch_earnings_writes_cache(tmp_path: Path) -> None:
    payload = _yf_earnings_payload(
        ["2024-02-01"],
        estimates=[1.0],
        actuals=[1.2],
    )
    with _patch_yf(payload):
        fetch_earnings(
            ["VRT"],
            cache_dir=tmp_path,
            sleep_between=0.0,
        )

    cache_file = tmp_path / "VRT.parquet"
    assert cache_file.is_file()
    cached = pd.read_parquet(cache_file)
    assert list(cached.columns) == EARNINGS_COLUMNS


def test_fetch_earnings_cache_hit_skips_yfinance(tmp_path: Path) -> None:
    cached = pd.DataFrame(
        {
            "ticker": ["VRT"],
            "announcement_date": pd.to_datetime(["2024-02-01"]),
            "fiscal_quarter": [pd.NA],
            "estimate_eps": [1.0],
            "actual_eps": [1.2],
            "sue": [np.nan],
            "has_consensus": [False],
            "surprise_sign": [1.0],
        }
    )
    cached.to_parquet(tmp_path / "VRT.parquet", index=False)

    inst = MagicMock()
    inst.get_earnings_dates.side_effect = AssertionError("yfinance must not be called")
    with patch("catalystlab.ingestion.earnings.yf.Ticker", return_value=inst):
        df = fetch_earnings(["VRT"], cache_dir=tmp_path, sleep_between=0.0)

    assert len(df) == 1
    inst.get_earnings_dates.assert_not_called()


def test_fetch_earnings_empty_returns_empty_long() -> None:
    with _patch_yf(None):
        df = fetch_earnings(["DELISTED"], cache_dir=None, sleep_between=0.0)

    assert df.empty
    assert list(df.columns) == EARNINGS_COLUMNS


def test_fetch_earnings_multi_ticker_sorted() -> None:
    payload_a = _yf_earnings_payload(
        ["2024-02-01"], estimates=[1.0], actuals=[1.2]
    )
    payload_b = _yf_earnings_payload(
        ["2024-03-01"], estimates=[2.0], actuals=[1.8]
    )
    inst_a = MagicMock()
    inst_a.get_earnings_dates.return_value = payload_a
    inst_b = MagicMock()
    inst_b.get_earnings_dates.return_value = payload_b

    def factory(ticker: str) -> MagicMock:
        return inst_a if ticker == "ANET" else inst_b

    with patch("catalystlab.ingestion.earnings.yf.Ticker", side_effect=factory):
        df = fetch_earnings(["VRT", "ANET"], cache_dir=None, sleep_between=0.0)

    assert df["ticker"].tolist() == ["ANET", "VRT"]


# ---------- integration ----------


@pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="set CATALYSTLAB_RUN_INTEGRATION=1 to run network-dependent test",
)
def test_integration_real_vrt_earnings() -> None:
    df = fetch_earnings(["VRT"], cache_dir=None, sleep_between=0.0)
    # yfinance scrapes Yahoo Finance; the earnings_dates endpoint is
    # intermittently rate-limited and may return empty. We verify structure
    # when the call succeeds; an empty result is treated as yfinance flakiness,
    # not a code bug.
    assert list(df.columns) == EARNINGS_COLUMNS
    if df.empty:
        pytest.skip("yfinance earnings_dates returned empty (likely scrape rate limit)")
    assert df["ticker"].unique().tolist() == ["VRT"]
    assert df["actual_eps"].notna().sum() >= 1
