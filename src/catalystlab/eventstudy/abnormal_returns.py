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


# ---------- AR / CAR computation (W2 T3) ----------


EVENT_METRICS_COLUMNS: list[str] = [
    "ticker",
    "event_date",
    "event_type",
    "event_magnitude",
    "holding_window",
    "beta",
    "n_obs",
    "car",
]


def compute_ar_car(
    returns_i: pd.Series,
    returns_bench: pd.Series,
    beta: float,
    event_date: pd.Timestamp,
    holding_window: int,
) -> tuple[float, int]:
    """Compute CAR(i, [t+1, t+holding_window]) and the count of observations.

    Args:
        returns_i: daily returns of asset i indexed by trading date.
        returns_bench: daily returns of benchmark indexed by trading date.
        beta: estimated β(i) for this event (from `estimate_beta`).
        event_date: anchor date — AR is computed on dates strictly AFTER
            this (T+1 to T+holding_window). Per prereg §4 T+0 is excluded.
        holding_window: number of trading days post-event to accumulate.

    Returns:
        (car, n_obs):
            car: sum of AR(t+1..t+holding_window) over available days. NaN
                if β is NaN or no post-event observations are available.
            n_obs: count of non-NaN AR contributions in the window
                (≤ holding_window; smaller when the event is near the end
                of the data or there are gaps).
    """
    if holding_window <= 0:
        raise ValueError(f"holding_window must be > 0, got {holding_window}")
    if pd.isna(beta):
        return float("nan"), 0

    df = _align_returns(returns_i, returns_bench)
    if df.empty:
        return float("nan"), 0

    event_ts = pd.Timestamp(event_date)
    valid_pre = df.index[df.index <= event_ts]
    if len(valid_pre) == 0:
        return float("nan"), 0

    event_pos = df.index.get_loc(valid_pre[-1])
    start_pos = event_pos + 1
    end_pos = start_pos + holding_window

    if start_pos >= len(df):
        return float("nan"), 0

    window = df.iloc[start_pos:end_pos]
    if window.empty:
        return float("nan"), 0

    ar = window["i"] - beta * window["b"]
    ar_valid = ar.dropna()
    if ar_valid.empty:
        return float("nan"), 0

    return float(ar_valid.sum()), len(ar_valid)


def compute_event_metrics(
    panel: pd.DataFrame,
    benchmark_returns: pd.Series,
    holding_windows: Iterable[int],
    beta_window_days: int = DEFAULT_BETA_WINDOW_DAYS,
    beta_exclusion_days: int = DEFAULT_BETA_EXCLUSION_DAYS,
) -> pd.DataFrame:
    """Compute beta + CAR for every event in the panel x every holding window.

    Args:
        panel: long-format panel from `ingestion.panel.build_panel` with
            columns including ``[date, ticker, return, event_type,
            event_magnitude]``.
        benchmark_returns: daily returns of the primary benchmark
            (e.g. XLK), indexed by trading date.
        holding_windows: iterable of post-event windows (e.g. [1, 5, 20, 60]).
        beta_window_days: window length for β estimation.
        beta_exclusion_days: exclusion buffer before the event for β.

    Returns:
        Long-format DataFrame with columns ``EVENT_METRICS_COLUMNS``,
        sorted by ``(ticker, event_date, holding_window)``. One row per
        (event x holding_window) combination. Beta is computed once per
        event and replicated across the window rows for that event.

    Notes:
        Events whose β cannot be estimated (insufficient history etc.) get
        NaN car and 0 n_obs. Events with valid β but no post-event data
        (event near end of series, or pre-IPO ticker positioning) also get
        NaN car / 0 n_obs.
    """
    windows = sorted(set(int(w) for w in holding_windows))
    if not windows:
        return pd.DataFrame(columns=EVENT_METRICS_COLUMNS)
    if any(w <= 0 for w in windows):
        raise ValueError("all holding_windows must be > 0 (T+0 excluded by prereg §4)")

    if panel.empty:
        return pd.DataFrame(columns=EVENT_METRICS_COLUMNS)

    events = panel[panel["event_type"].notna()].copy()
    if events.empty:
        return pd.DataFrame(columns=EVENT_METRICS_COLUMNS)

    returns_wide = panel.pivot_table(
        index="date",
        columns="ticker",
        values="return",
        aggfunc="first",
    )
    returns_wide.index = pd.DatetimeIndex(returns_wide.index)
    bench = benchmark_returns.copy()
    bench.index = pd.DatetimeIndex(bench.index)

    rows: list[dict[str, object]] = []
    for _, ev in events.iterrows():
        ticker = str(ev["ticker"])
        event_date = pd.Timestamp(ev["date"])
        event_type = ev["event_type"]
        event_magnitude = ev["event_magnitude"]

        if ticker not in returns_wide.columns:
            beta = float("nan")
        else:
            ri = returns_wide[ticker].dropna()
            beta = estimate_beta(
                ri,
                bench,
                event_date,
                window_days=beta_window_days,
                exclusion_days=beta_exclusion_days,
            )

        for hw in windows:
            if pd.isna(beta) or ticker not in returns_wide.columns:
                car, n_obs = float("nan"), 0
            else:
                car, n_obs = compute_ar_car(
                    returns_wide[ticker],
                    bench,
                    beta,
                    event_date,
                    hw,
                )

            rows.append(
                {
                    "ticker": ticker,
                    "event_date": event_date,
                    "event_type": event_type,
                    "event_magnitude": event_magnitude,
                    "holding_window": hw,
                    "beta": beta,
                    "n_obs": n_obs,
                    "car": car,
                }
            )

    out = pd.DataFrame(rows, columns=EVENT_METRICS_COLUMNS)
    return out.sort_values(["ticker", "event_date", "holding_window"]).reset_index(drop=True)
