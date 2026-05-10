"""Layer 4 — bootstrap confidence intervals on IC (prereg §6.4).

Per prereg §6.4 every IC reported in Step 1 must come with a 95% CI from
1000 bootstrap resamples. Per prereg §8.3 a (category, holding_window)
combination is treated as AMBIGUOUS (= negative) when the bootstrap CI
crosses zero, even if BH-corrected p < 0.05 — so the CI is a binding
input to the Step 1 decision tree.

Determinism: a single ``rng = np.random.default_rng(seed)`` drives the
whole `apply_bootstrap_to_summary` invocation. Two runs with the same
seed and the same input produce identical CIs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

DEFAULT_BOOTSTRAP_RESAMPLES: int = 1000
DEFAULT_BOOTSTRAP_CI_LEVEL: float = 0.95
DEFAULT_BOOTSTRAP_SEED: int = 42


def bootstrap_ic_ci(
    magnitudes: np.ndarray,
    cars: np.ndarray,
    n_resample: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    ci_level: float = DEFAULT_BOOTSTRAP_CI_LEVEL,
    rng: np.random.Generator | None = None,
) -> tuple[float, float, float]:
    """Bootstrap point + CI for the Spearman IC of (magnitudes, cars).

    Args:
        magnitudes: 1-D array of event magnitudes (predictor).
        cars: 1-D array of post-event CARs (outcome).
        n_resample: number of bootstrap resamples (prereg §6.4: 1000).
        ci_level: confidence level for the CI (prereg §6.4: 0.95).
        rng: numpy Generator for sampling. None -> fresh default_rng().

    Returns:
        ``(ic_point, ic_ci_lower, ic_ci_upper)``. NaN-NaN-NaN when n<2,
        when constant input, or when too many resamples are degenerate.

    Resamples that produce constant magnitudes or constant CARs (where
    Spearman is undefined) are dropped from the bootstrap distribution.
    The final percentiles are computed on the surviving resamples; if
    fewer than half the requested n_resample remain, CI returns NaN.
    """
    if rng is None:
        rng = np.random.default_rng()

    m = np.asarray(magnitudes, dtype=float)
    c = np.asarray(cars, dtype=float)
    if m.shape != c.shape or m.ndim != 1:
        raise ValueError("magnitudes and cars must be 1-D arrays of equal length")

    valid_mask = ~(np.isnan(m) | np.isnan(c))
    m, c = m[valid_mask], c[valid_mask]
    n = len(m)

    if n < 2 or np.unique(m).size < 2 or np.unique(c).size < 2:
        return float("nan"), float("nan"), float("nan")

    point_res = stats.spearmanr(m, c)
    point = float(point_res.statistic)  # type: ignore[attr-defined]

    boot_ics = np.full(n_resample, np.nan, dtype=float)
    for i in range(n_resample):
        idx = rng.integers(0, n, size=n)
        m_b, c_b = m[idx], c[idx]
        if np.unique(m_b).size < 2 or np.unique(c_b).size < 2:
            continue
        boot_ics[i] = float(stats.spearmanr(m_b, c_b).statistic)  # type: ignore[attr-defined]

    valid = boot_ics[~np.isnan(boot_ics)]
    if len(valid) < n_resample // 2:
        return point, float("nan"), float("nan")

    pct_lo = (1 - ci_level) / 2 * 100
    pct_hi = 100 - pct_lo
    lo = float(np.percentile(valid, pct_lo))
    hi = float(np.percentile(valid, pct_hi))
    return point, lo, hi


def apply_bootstrap_to_summary(
    metrics: pd.DataFrame,
    summary: pd.DataFrame,
    n_resample: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    ci_level: float = DEFAULT_BOOTSTRAP_CI_LEVEL,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> pd.DataFrame:
    """Add bootstrap CI columns to a summary DataFrame.

    For each (event_type, holding_window) row in ``summary``, looks up the
    matching (magnitude, car) pairs in ``metrics`` and computes a
    bootstrap CI for the Spearman IC. Adds three columns to ``summary``:

        ic_ci_lower, ic_ci_upper, ic_ci_crosses_zero

    Args:
        metrics: long-format event metrics (one row per event x window).
        summary: aggregated summary (one row per category x window) — the
            output of `aggregate_event_metrics` merged with `compute_ic`.
        n_resample, ci_level: forwarded to `bootstrap_ic_ci`.
        seed: deterministic seed for the bootstrap RNG. The same seed +
            same input -> identical CIs across runs.

    Returns:
        Copy of ``summary`` with the three new columns added.
    """
    if summary is None or summary.empty:
        out = summary.copy() if summary is not None else pd.DataFrame()
        for col in ("ic_ci_lower", "ic_ci_upper"):
            out[col] = pd.Series(dtype=float)
        out["ic_ci_crosses_zero"] = pd.Series(dtype=bool)
        return out

    required_summary = {"event_type", "holding_window"}
    required_metrics = {"event_type", "holding_window", "event_magnitude", "car"}
    missing_s = required_summary - set(summary.columns)
    missing_m = required_metrics - set(metrics.columns)
    if missing_s:
        raise ValueError(f"summary missing required columns: {sorted(missing_s)}")
    if missing_m:
        raise ValueError(f"metrics missing required columns: {sorted(missing_m)}")

    rng = np.random.default_rng(seed)

    out = summary.copy()
    out["ic_ci_lower"] = np.nan
    out["ic_ci_upper"] = np.nan

    for idx, row in out.iterrows():
        et = row["event_type"]
        hw = row["holding_window"]
        sub = metrics[
            (metrics["event_type"] == et) & (metrics["holding_window"] == hw)
        ]
        m = sub["event_magnitude"].to_numpy()
        c = sub["car"].to_numpy()
        _, lo, hi = bootstrap_ic_ci(m, c, n_resample=n_resample, ci_level=ci_level, rng=rng)
        out.at[idx, "ic_ci_lower"] = lo
        out.at[idx, "ic_ci_upper"] = hi

    crosses = (out["ic_ci_lower"] < 0) & (out["ic_ci_upper"] > 0)
    # NaN CI -> not "crosses zero" but undecided; surface as False with NaN-aware fill.
    out["ic_ci_crosses_zero"] = crosses.fillna(False)
    return out
