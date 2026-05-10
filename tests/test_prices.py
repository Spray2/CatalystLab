"""Tests for catalystlab.ingestion.prices.

Strategy:
    * Unit tests use mocked yfinance.Ticker.history payloads to cover edge
      cases without network dependency.
    * One integration test runs only when CATALYSTLAB_RUN_INTEGRATION=1, to
      validate against the real yfinance API (rate-limit risk).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from catalystlab.ingestion.prices import (
    OHLCV_LONG_COLUMNS,
    _fetch_one,
    _try_load_cache,
    detect_gaps,
    expected_trading_days,
    fetch_prices,
)

_RUN_INTEGRATION: bool = os.environ.get("CATALYSTLAB_RUN_INTEGRATION") == "1"


def _yf_payload(
    dates: list[str],
    *,
    tz: str | None = None,
    open_: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    close: list[float] | None = None,
    adj_close: list[float] | None = None,
    volume: list[int] | None = None,
) -> pd.DataFrame:
    """Build a synthetic yfinance history() payload for tests."""
    n = len(dates)
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    if tz is not None:
        idx = idx.tz_localize(tz)
    return pd.DataFrame(
        {
            "Open": open_ if open_ is not None else [1.0] * n,
            "High": high if high is not None else [2.0] * n,
            "Low": low if low is not None else [0.5] * n,
            "Close": close if close is not None else [1.5] * n,
            "Adj Close": adj_close if adj_close is not None else [1.4] * n,
            "Volume": volume if volume is not None else [1000] * n,
        },
        index=idx,
    )


def _patch_yf(payload: pd.DataFrame):
    """Return a patcher that makes yf.Ticker(...).history() return payload."""
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.history.return_value = payload
    return patch(
        "catalystlab.ingestion.prices.yf.Ticker",
        return_value=mock_ticker_instance,
    )


# ---------- _fetch_one ----------


def test_fetch_one_happy_path() -> None:
    payload = _yf_payload(["2024-01-02", "2024-01-03"])
    with _patch_yf(payload):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert list(df.columns) == OHLCV_LONG_COLUMNS
    assert len(df) == 2
    assert df["ticker"].unique().tolist() == ["VRT"]
    assert df["adj_close"].tolist() == [1.4, 1.4]


def test_fetch_one_strips_tz_aware_index() -> None:
    payload = _yf_payload(["2024-01-02", "2024-01-03"], tz="US/Eastern")
    with _patch_yf(payload):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert df["date"].dt.tz is None


def test_fetch_one_truncates_exclusive_end_boundary() -> None:
    # yfinance occasionally returns the exclusive boundary day; we truncate.
    payload = _yf_payload(["2024-01-02", "2024-01-03", "2024-01-04"])
    with _patch_yf(payload):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert len(df) == 2
    assert df["date"].max() == pd.Timestamp("2024-01-03")


def test_fetch_one_drops_nan_rows() -> None:
    payload = _yf_payload(
        ["2024-01-02", "2024-01-03"],
        adj_close=[1.4, float("nan")],
    )
    with _patch_yf(payload):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert len(df) == 1
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-02")


def test_fetch_one_empty_payload_returns_empty_long() -> None:
    with _patch_yf(pd.DataFrame()):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert df.empty
    assert list(df.columns) == OHLCV_LONG_COLUMNS


def test_fetch_one_schema_mismatch_returns_empty_long() -> None:
    bad = pd.DataFrame(
        {"Foo": [1.0], "Bar": [2.0]},
        index=pd.DatetimeIndex(["2024-01-02"]),
    )
    with _patch_yf(bad):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert df.empty
    assert list(df.columns) == OHLCV_LONG_COLUMNS


def test_fetch_one_yfinance_exception_returns_empty_long() -> None:
    mock_instance = MagicMock()
    mock_instance.history.side_effect = RuntimeError("network down")
    with patch("catalystlab.ingestion.prices.yf.Ticker", return_value=mock_instance):
        df = _fetch_one("VRT", date(2024, 1, 2), date(2024, 1, 3))

    assert df.empty


def test_fetch_one_start_after_end_raises() -> None:
    with pytest.raises(ValueError, match="start"):
        _fetch_one("VRT", date(2024, 1, 5), date(2024, 1, 2))


# ---------- _try_load_cache ----------


def test_try_load_cache_missing_file(tmp_path: Path) -> None:
    assert _try_load_cache(tmp_path / "nonexistent.parquet", date(2024, 1, 1), date(2024, 1, 31)) is None


def test_try_load_cache_covers_window(tmp_path: Path) -> None:
    cached = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "ticker": ["VRT"] * 3,
            "open": [1.0] * 3,
            "high": [2.0] * 3,
            "low": [0.5] * 3,
            "close": [1.5] * 3,
            "adj_close": [1.4] * 3,
            "volume": [1000] * 3,
        }
    )
    cache_path = tmp_path / "VRT.parquet"
    cached.to_parquet(cache_path, index=False)
    sliced = _try_load_cache(cache_path, date(2024, 1, 2), date(2024, 1, 3))
    assert sliced is not None
    assert len(sliced) == 2


def test_try_load_cache_window_too_narrow(tmp_path: Path) -> None:
    cached = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "ticker": ["VRT"] * 2,
            "open": [1.0] * 2,
            "high": [2.0] * 2,
            "low": [0.5] * 2,
            "close": [1.5] * 2,
            "adj_close": [1.4] * 2,
            "volume": [1000] * 2,
        }
    )
    cache_path = tmp_path / "VRT.parquet"
    cached.to_parquet(cache_path, index=False)
    # Request a wider window than cached → cache miss.
    assert _try_load_cache(cache_path, date(2024, 1, 1), date(2024, 1, 10)) is None


# ---------- fetch_prices ----------


def test_fetch_prices_multi_ticker_concat_sorted(tmp_path: Path) -> None:
    payload = _yf_payload(["2024-01-02", "2024-01-03"])
    with _patch_yf(payload):
        df = fetch_prices(
            ["ANET", "VRT"],
            date(2024, 1, 2),
            date(2024, 1, 3),
            cache_dir=None,
            sleep_between=0.0,
        )

    assert len(df) == 4
    # sort: ANET < VRT lexicographically
    assert df["ticker"].tolist() == ["ANET", "ANET", "VRT", "VRT"]


def test_fetch_prices_writes_cache(tmp_path: Path) -> None:
    payload = _yf_payload(["2024-01-02", "2024-01-03"])
    with _patch_yf(payload):
        fetch_prices(
            ["VRT"],
            date(2024, 1, 2),
            date(2024, 1, 3),
            cache_dir=tmp_path,
            sleep_between=0.0,
        )

    cache_file = tmp_path / "VRT.parquet"
    assert cache_file.is_file()
    cached = pd.read_parquet(cache_file)
    assert len(cached) == 2


def test_fetch_prices_cache_hit_skips_yfinance(tmp_path: Path) -> None:
    # Pre-populate cache.
    cached = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "ticker": ["VRT"] * 2,
            "open": [1.0] * 2,
            "high": [2.0] * 2,
            "low": [0.5] * 2,
            "close": [1.5] * 2,
            "adj_close": [1.4] * 2,
            "volume": [1000] * 2,
        }
    )
    cached.to_parquet(tmp_path / "VRT.parquet", index=False)

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = AssertionError("yfinance must not be called")
    with patch("catalystlab.ingestion.prices.yf.Ticker", return_value=mock_ticker):
        df = fetch_prices(
            ["VRT"],
            date(2024, 1, 2),
            date(2024, 1, 3),
            cache_dir=tmp_path,
            sleep_between=0.0,
        )

    assert len(df) == 2
    mock_ticker.history.assert_not_called()


def test_fetch_prices_no_data_returns_empty_long() -> None:
    with _patch_yf(pd.DataFrame()):
        df = fetch_prices(
            ["DELISTED"],
            date(2024, 1, 2),
            date(2024, 1, 3),
            cache_dir=None,
            sleep_between=0.0,
        )

    assert df.empty
    assert list(df.columns) == OHLCV_LONG_COLUMNS


# ---------- expected_trading_days / detect_gaps ----------


def test_expected_trading_days_excludes_weekends_and_holidays() -> None:
    days = expected_trading_days(date(2024, 1, 1), date(2024, 1, 5))
    # NYSE: 2024-01-01 (New Year) closed; 2024-01-02..05 trading; weekend excluded.
    assert pd.Timestamp("2024-01-01") not in days
    assert pd.Timestamp("2024-01-02") in days
    assert pd.Timestamp("2024-01-05") in days
    assert len(days) == 4


def test_detect_gaps_empty_df_returns_empty_dict() -> None:
    out = detect_gaps(pd.DataFrame(columns=OHLCV_LONG_COLUMNS), pd.DatetimeIndex([]))
    assert out == {}


def test_detect_gaps_reports_missing_days() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-04"]),
            "ticker": ["VRT", "VRT"],
            "open": [1.0, 1.0],
            "high": [2.0, 2.0],
            "low": [0.5, 0.5],
            "close": [1.5, 1.5],
            "adj_close": [1.4, 1.4],
            "volume": [1000, 1000],
        }
    )
    expected = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    gaps = detect_gaps(df, expected)
    assert "VRT" in gaps
    assert pd.Timestamp("2024-01-03") in gaps["VRT"]


def test_detect_gaps_complete_ticker_omitted() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "ticker": ["VRT", "VRT"],
            "open": [1.0, 1.0],
            "high": [2.0, 2.0],
            "low": [0.5, 0.5],
            "close": [1.5, 1.5],
            "adj_close": [1.4, 1.4],
            "volume": [1000, 1000],
        }
    )
    expected = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    gaps = detect_gaps(df, expected)
    assert gaps == {}


# ---------- integration ----------


@pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="set CATALYSTLAB_RUN_INTEGRATION=1 to run network-dependent test",
)
def test_integration_real_vrt_january_2024() -> None:
    df = fetch_prices(
        ["VRT"],
        date(2024, 1, 1),
        date(2024, 1, 31),
        cache_dir=None,
        sleep_between=0.0,
    )
    # NYSE January 2024: 21 trading days (1 = New Year, 15 = MLK).
    assert 19 <= len(df) <= 22, f"unexpected row count {len(df)}"
    assert list(df.columns) == OHLCV_LONG_COLUMNS
    assert df["adj_close"].notna().all()
    assert (df["volume"] > 0).all()
