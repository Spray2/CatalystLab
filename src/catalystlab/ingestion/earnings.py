"""Layer 2 — earnings dates + SUE computation per pre-registration §3.1.

SUE definition (prereg §3.1, taken verbatim):

    SUE = (actual - consensus) / std(consensus)

with the std of consensus estimated on a rolling window of the previous
quarters (default 8) of the same ticker. Threshold for event qualification
is |SUE| > 1.0 (top/bottom decile, prereg §3.1).

Fallback when the consensus window has fewer than `MIN_ESTIMATES_FOR_SUE`
priors: `has_consensus=False`, `sue=NaN`, and `surprise_sign` (binary
fallback per CLAUDE.md "ingestion earnings" task) is set to
``sign(actual - estimate)`` if both are available, else NaN.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

EARNINGS_COLUMNS: list[str] = [
    "ticker",
    "announcement_date",
    "fiscal_quarter",
    "estimate_eps",
    "actual_eps",
    "sue",
    "has_consensus",
    "surprise_sign",
]

_YF_EARNINGS_RENAME: dict[str, str] = {
    "EPS Estimate": "estimate_eps",
    "Reported EPS": "actual_eps",
}

DEFAULT_LOOKBACK_QUARTERS: int = 24
DEFAULT_SUE_WINDOW_QUARTERS: int = 8
MIN_ESTIMATES_FOR_SUE: int = 4


def _empty_earnings() -> pd.DataFrame:
    return pd.DataFrame(columns=EARNINGS_COLUMNS)


def _fetch_one(ticker: str, lookback_quarters: int) -> pd.DataFrame:
    """Fetch raw earnings rows for one ticker; columns
    [ticker, announcement_date, fiscal_quarter, estimate_eps, actual_eps].
    """
    try:
        raw = yf.Ticker(ticker).get_earnings_dates(limit=lookback_quarters)
    except Exception as e:
        logger.warning("yfinance earnings_dates raised on %s: %s", ticker, e)
        return pd.DataFrame(
            columns=[
                "ticker",
                "announcement_date",
                "fiscal_quarter",
                "estimate_eps",
                "actual_eps",
            ]
        )

    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "announcement_date",
                "fiscal_quarter",
                "estimate_eps",
                "actual_eps",
            ]
        )

    df = raw.reset_index()
    if "Earnings Date" not in df.columns:
        logger.warning(
            "yfinance returned unexpected earnings shape for %s: %s",
            ticker,
            list(df.columns),
        )
        return pd.DataFrame(
            columns=[
                "ticker",
                "announcement_date",
                "fiscal_quarter",
                "estimate_eps",
                "actual_eps",
            ]
        )

    df = df.rename(columns={"Earnings Date": "announcement_date", **_YF_EARNINGS_RENAME})

    df["announcement_date"] = pd.to_datetime(df["announcement_date"], errors="coerce")
    df = df.dropna(subset=["announcement_date"])
    if isinstance(df["announcement_date"].dtype, pd.DatetimeTZDtype):
        df["announcement_date"] = df["announcement_date"].dt.tz_localize(None)
    df["announcement_date"] = df["announcement_date"].dt.normalize()

    # yfinance does not surface fiscal_quarter; left NA per ADR 0001 reference.
    if "fiscal_quarter" not in df.columns:
        df["fiscal_quarter"] = pd.NA

    for col in ("estimate_eps", "actual_eps"):
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ticker"] = ticker

    return df[
        ["ticker", "announcement_date", "fiscal_quarter", "estimate_eps", "actual_eps"]
    ].drop_duplicates(subset=["ticker", "announcement_date"])


def _compute_sue(
    df: pd.DataFrame,
    window_quarters: int = DEFAULT_SUE_WINDOW_QUARTERS,
    min_estimates: int = MIN_ESTIMATES_FOR_SUE,
) -> pd.DataFrame:
    """Compute SUE + binary fallback per prereg §3.1.

    SUE_t = (actual_t - estimate_t) / std(estimate over previous N quarters)

    The std is computed on the prior window only (current row excluded via
    ``shift(1)``) to avoid leakage of the current quarter into its own
    standardisation denominator.
    """
    if df.empty:
        return _empty_earnings()

    out = df.copy().sort_values(["ticker", "announcement_date"]).reset_index(drop=True)

    sue_vals: list[float] = []
    has_consensus_vals: list[bool] = []
    surprise_sign_vals: list[float] = []

    for _, group in out.groupby("ticker", sort=False):
        ests = group["estimate_eps"].astype(float)
        actuals = group["actual_eps"].astype(float)

        # Binary fallback: sign(actual - estimate); NaN if either missing.
        surprises = actuals - ests
        signs = np.where(
            surprises.notna(),
            np.sign(surprises.fillna(0).to_numpy()),
            np.nan,
        )

        # Rolling std of priors (current row excluded via shift).
        rolling_std = (
            ests.shift(1).rolling(window=window_quarters, min_periods=min_estimates).std(ddof=1)
        )

        sue = (actuals - ests) / rolling_std
        sue = sue.where(rolling_std.notna() & (rolling_std > 0))
        consensus = sue.notna()

        sue_vals.extend(sue.tolist())
        has_consensus_vals.extend(consensus.tolist())
        surprise_sign_vals.extend(signs.tolist())

    out["sue"] = sue_vals
    out["has_consensus"] = has_consensus_vals
    out["surprise_sign"] = surprise_sign_vals

    return out[EARNINGS_COLUMNS]


def fetch_earnings(
    tickers: list[str],
    lookback_quarters: int = DEFAULT_LOOKBACK_QUARTERS,
    cache_dir: Path | None = None,
    sleep_between: float = 0.2,
    use_cache: bool = True,
    sue_window_quarters: int = DEFAULT_SUE_WINDOW_QUARTERS,
    min_estimates_for_sue: int = MIN_ESTIMATES_FOR_SUE,
) -> pd.DataFrame:
    """Fetch standardized earnings rows for ``tickers``.

    Returns a long-format DataFrame with columns ``EARNINGS_COLUMNS``.

    SUE follows prereg §3.1: ``(actual - estimate) / std(estimate over
    previous `sue_window_quarters` quarters)``. When fewer than
    ``min_estimates_for_sue`` priors are available, ``has_consensus=False``
    and ``sue=NaN``; ``surprise_sign`` (-1/0/+1) is the binary fallback
    when both ``actual_eps`` and ``estimate_eps`` are present.

    Cache: per-ticker parquet under ``cache_dir``. Cache miss refetches and
    overwrites; column-mismatched cache files are ignored.
    """
    frames: list[pd.DataFrame] = []
    n = len(tickers)

    for i, ticker in enumerate(tickers):
        cache_path: Path | None = None
        if cache_dir is not None:
            cache_path = cache_dir / f"{ticker}.parquet"

        df: pd.DataFrame | None = None
        if use_cache and cache_path is not None and cache_path.is_file():
            try:
                cached = pd.read_parquet(cache_path)
                if list(cached.columns) == EARNINGS_COLUMNS:
                    df = cached
                else:
                    logger.warning(
                        "earnings cache schema mismatch at %s; refetching", cache_path
                    )
            except Exception as e:
                logger.warning("earnings cache read failed at %s: %s", cache_path, e)

        if df is None:
            raw = _fetch_one(ticker, lookback_quarters)
            df = _compute_sue(
                raw,
                window_quarters=sue_window_quarters,
                min_estimates=min_estimates_for_sue,
            )
            if cache_path is not None and not df.empty:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(cache_path, index=False)
            if sleep_between > 0 and i < n - 1:
                time.sleep(sleep_between)

        consensus_count = int(df["has_consensus"].sum()) if not df.empty else 0
        logger.info(
            "[%d/%d] %s: %d earnings rows (consensus on %d)",
            i + 1,
            n,
            ticker,
            len(df),
            consensus_count,
        )

        if not df.empty:
            frames.append(df)

    if not frames:
        return _empty_earnings()

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["ticker", "announcement_date"]).reset_index(drop=True)
    return out
