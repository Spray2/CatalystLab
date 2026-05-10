"""Layer 3 — abnormal returns engine (prereg §6.1).

W2 task 2 implements the per-event β estimation. Subsequent W2 tasks
extend this module with AR / CAR computation on top.

β estimation rule (prereg §6.1, verbatim):

    β(i) is estimated on a rolling window of `beta_window_days` trading
    days preceding the event, excluding the most recent
    `beta_exclusion_window_days` (anti-contamination buffer).

Window slice for an event at trading-day position ``p``::

    window = aligned[p - exclusion - window : p - exclusion]   (exclusive end)

β is then the OLS slope of asset returns on benchmark returns over the
window — equivalent to ``cov(r_i, r_b) / var(r_b)``.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

DEFAULT_BETA_WINDOW_DAYS: int = 252
DEFAULT_BETA_EXCLUSION_DAYS: int = 30


def _align_returns(
    returns_i: pd.Series,
    returns_bench: pd.Series,
) -> pd.DataFrame:
    """Align two return Series on common trading days, drop NaN rows."""
    df = pd.DataFrame({"i": returns_i, "b": returns_bench})
    df = df.dropna()
    df = df.sort_index()
    df.index = pd.DatetimeIndex(df.index)
    return df


def estimate_beta(
    returns_i: pd.Series,
    returns_bench: pd.Series,
    event_date: pd.Timestamp,
    window_days: int = DEFAULT_BETA_WINDOW_DAYS,
    exclusion_days: int = DEFAULT_BETA_EXCLUSION_DAYS,
) -> float:
    """Estimate β(i) for a single event per prereg §6.1.

    Args:
        returns_i: daily returns of asset i indexed by trading date.
        returns_bench: daily returns of the benchmark indexed by trading date.
        event_date: the event timestamp. β is estimated on the
            ``window_days`` ending ``exclusion_days`` before this date.
        window_days: estimation window length in trading days.
        exclusion_days: number of trading days immediately before
            ``event_date`` excluded from the estimation window.

    Returns:
        β = cov(r_i, r_b) / var(r_b) over the windowed slice. ``NaN`` when:

        - the aligned returns frame is empty,
        - ``event_date`` is before any aligned trading day,
        - the window would start before the first aligned trading day
          (insufficient history),
        - the benchmark variance is zero or undefined in the window.
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be > 0, got {window_days}")
    if exclusion_days < 0:
        raise ValueError(f"exclusion_days must be >= 0, got {exclusion_days}")

    df = _align_returns(returns_i, returns_bench)
    if df.empty:
        return float("nan")

    event_ts = pd.Timestamp(event_date)
    valid_pre = df.index[df.index <= event_ts]
    if len(valid_pre) == 0:
        return float("nan")

    event_pos = df.index.get_loc(valid_pre[-1])
    end_pos = event_pos - exclusion_days
    start_pos = end_pos - window_days

    if start_pos < 0 or end_pos <= start_pos:
        return float("nan")

    window = df.iloc[start_pos:end_pos]
    if len(window) < 2:
        return float("nan")

    var_b = window["b"].var(ddof=1)
    # Use a small epsilon: a true zero-variance benchmark accumulates
    # float-precision noise, but real equity benchmark variance is ≥ 1e-6
    # (volatility ≥ 0.1% daily), so 1e-12 is safely below any signal.
    if pd.isna(var_b) or var_b < 1e-12:
        return float("nan")

    cov_ib = window["i"].cov(window["b"], ddof=1)
    if pd.isna(cov_ib):
        return float("nan")

    return float(cov_ib / var_b)


def estimate_betas(
    event_dates: Iterable[pd.Timestamp],
    returns_i: pd.Series,
    returns_bench: pd.Series,
    window_days: int = DEFAULT_BETA_WINDOW_DAYS,
    exclusion_days: int = DEFAULT_BETA_EXCLUSION_DAYS,
) -> pd.Series:
    """Vectorised β across multiple event dates for a single asset.

    Returns a ``Series`` indexed by ``event_dates`` (as DatetimeIndex) with
    one β per event. NaN entries follow the same rules as `estimate_beta`.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(list(event_dates)))
    betas = np.fromiter(
        (
            estimate_beta(returns_i, returns_bench, d, window_days, exclusion_days)
            for d in dates
        ),
        dtype=float,
        count=len(dates),
    )
    return pd.Series(betas, index=dates, name="beta")
