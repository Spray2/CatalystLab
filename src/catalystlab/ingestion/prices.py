"""Layer 2 — yfinance daily OHLCV fetcher with parquet cache.

Patterns adapted from EquiTeria's `yfinance_provider.py` per ADR 0001 (no
direct imports — re-implementation in CatalystLab namespace):

- ``auto_adjust=False`` keeps raw ``Close`` (split-adjusted only) and exposes
  ``Adj Close`` (split + dividend) as a separate column. Total-return AR
  (Layer 3) uses ``adj_close``; never silently mix the two (CLAUDE.md §"Code
  style").
- ``actions=False`` suppresses the Dividends / Stock Splits columns from the
  OHLCV payload.
- yfinance treats ``end`` as exclusive — bump ``+1 day`` to honour the
  inclusive ``[start, end]`` contract.
- yfinance can return tz-aware indexes (US/Eastern); strip tz and normalise
  to date-only.
- Exceptions are absorbed and surfaced as empty DataFrames; callers inspect
  the result rather than catch.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

OHLCV_LONG_COLUMNS: list[str] = [
    "date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
]

_OHLCV_PRICE_COLUMNS: list[str] = ["open", "high", "low", "close", "adj_close", "volume"]

_YF_RENAME: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


def _empty_long() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV_LONG_COLUMNS)


def _fetch_one(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch OHLCV for a single ticker; return long-format frame or empty."""
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    yf_end = end + timedelta(days=1)  # yfinance end is exclusive

    try:
        raw = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=yf_end.isoformat(),
            auto_adjust=False,
            actions=False,
            raise_errors=False,
        )
    except Exception as e:
        logger.warning("yfinance raised on %s [%s, %s]: %s", ticker, start, end, e)
        return _empty_long()

    if raw is None or raw.empty:
        return _empty_long()

    df = raw.copy()

    # tz-naive normalisation (yfinance may return US/Eastern)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.DatetimeIndex(df.index.normalize())

    df = df.rename(columns=_YF_RENAME)

    missing = [c for c in _OHLCV_PRICE_COLUMNS if c not in df.columns]
    if missing:
        logger.warning(
            "yfinance returned unexpected schema for %s; missing columns: %s",
            ticker,
            missing,
        )
        return _empty_long()

    df = df[_OHLCV_PRICE_COLUMNS].copy()

    # Defensive truncation against the exclusive-boundary edge case.
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    df = df[(df.index >= start_ts) & (df.index <= end_ts)]

    df = df.dropna(subset=_OHLCV_PRICE_COLUMNS)

    if df.empty:
        return _empty_long()

    df = df.reset_index().rename(columns={df.index.name or "Date": "date"})
    if "date" not in df.columns:
        # reset_index() may produce a generic name when the index name is None.
        df = df.rename(columns={df.columns[0]: "date"})
    df["ticker"] = ticker

    return df[OHLCV_LONG_COLUMNS].reset_index(drop=True)


def _try_load_cache(
    cache_path: Path,
    start: date,
    end: date,
) -> pd.DataFrame | None:
    """Load and slice a cached parquet if it covers the requested window."""
    if not cache_path.is_file():
        return None
    try:
        cached = pd.read_parquet(cache_path)
    except Exception as e:
        logger.warning("cache read failed at %s: %s", cache_path, e)
        return None
    if cached.empty:
        return None
    cached_min = cached["date"].min()
    cached_max = cached["date"].max()
    if cached_min > pd.Timestamp(start) or cached_max < pd.Timestamp(end):
        return None  # cache window does not cover the request
    sliced = cached[
        (cached["date"] >= pd.Timestamp(start)) & (cached["date"] <= pd.Timestamp(end))
    ]
    return sliced.reset_index(drop=True)


def fetch_prices(
    tickers: list[str],
    start: date,
    end: date,
    cache_dir: Path | None = None,
    sleep_between: float = 0.2,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch daily OHLCV for ``tickers`` over ``[start, end]`` inclusive.

    Args:
        tickers: list of yfinance-form symbols (e.g. ``["VRT", "ANET"]``).
        start, end: inclusive date range.
        cache_dir: optional directory for per-ticker parquet cache. The cache
            is keyed by ticker and contains the full historical window
            previously fetched. A request whose ``[start, end]`` falls inside
            the cached range is served from cache; otherwise the ticker is
            refetched and the cache is overwritten with the new (broader)
            window.
        sleep_between: seconds to sleep between successive yfinance calls
            (rate-limit hygiene; 0 disables).
        use_cache: if False, ignore cache files (still write them on success).

    Returns:
        Long-format DataFrame with columns
        ``[date, ticker, open, high, low, close, adj_close, volume]``,
        sorted by ``(ticker, date)``.

    Per-ticker fetch failures (network, schema mismatch, empty) are logged
    and the ticker is omitted from the output rather than raising.
    """
    frames: list[pd.DataFrame] = []
    n = len(tickers)

    for i, ticker in enumerate(tickers):
        cache_path: Path | None = None
        if cache_dir is not None:
            cache_path = cache_dir / f"{ticker}.parquet"

        df: pd.DataFrame | None = None
        if use_cache and cache_path is not None:
            df = _try_load_cache(cache_path, start, end)
            if df is not None:
                logger.info(
                    "[%d/%d] %s: cache hit (%d rows in window)",
                    i + 1,
                    n,
                    ticker,
                    len(df),
                )

        if df is None:
            df = _fetch_one(ticker, start, end)
            logger.info(
                "[%d/%d] %s: fetched %d rows from yfinance",
                i + 1,
                n,
                ticker,
                len(df),
            )
            if cache_path is not None and not df.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(cache_path, index=False)
            if sleep_between > 0 and i < n - 1:
                time.sleep(sleep_between)

        if not df.empty:
            frames.append(df)

    if not frames:
        return _empty_long()

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    return out


def expected_trading_days(
    start: date,
    end: date,
    calendar_name: str = "XNYS",
) -> pd.DatetimeIndex:
    """Return the expected NYSE trading days in ``[start, end]`` inclusive.

    Uses ``exchange_calendars`` (XNYS); robust to NYSE-specific holidays
    (Independence Day, Thanksgiving early close days are still trading days).
    """
    import exchange_calendars as xcals

    cal = xcals.get_calendar(calendar_name)
    sessions = cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return pd.DatetimeIndex(sessions).normalize()


def detect_gaps(
    df: pd.DataFrame,
    expected: pd.DatetimeIndex,
) -> dict[str, list[pd.Timestamp]]:
    """Per-ticker, return missing trading days vs the expected calendar.

    Args:
        df: long-format prices DataFrame.
        expected: sorted DatetimeIndex of expected trading days.

    Returns:
        ``{ticker: [missing_days...]}``. Tickers with no gaps are omitted.
        Empty input yields ``{}``.
    """
    if df.empty:
        return {}

    expected_norm = pd.DatetimeIndex(expected).normalize()
    gaps: dict[str, list[pd.Timestamp]] = {}
    for ticker, sub in df.groupby("ticker"):
        ticker_dates = pd.DatetimeIndex(sub["date"]).normalize()
        missing = expected_norm.difference(ticker_dates)
        if len(missing) > 0:
            gaps[str(ticker)] = list(missing)
    return gaps
