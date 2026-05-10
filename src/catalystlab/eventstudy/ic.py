"""Layer 3 — Information Coefficient (Spearman) per prereg §6.2.

For each (event_type, holding_window) group, the IC is the Spearman rank
correlation between the event magnitude (predictor) and the CAR (outcome),
together with the two-sided p-value from `scipy.stats.spearmanr`.

The p-value reported here is *uncorrected*. Per prereg §6.3 the
Benjamini-Hochberg FDR correction over the 5 simultaneous category tests
is applied in Layer 4 (W3) before declaring success/failure.
"""

from __future__ import annotations

import pandas as pd
from scipy import stats

from catalystlab.eventstudy.abnormal_returns import EVENT_METRICS_COLUMNS

IC_COLUMNS: list[str] = [
    "event_type",
    "holding_window",
    "n_pairs",
    "ic",
    "ic_pvalue",
]


def _spearman_safe(magnitudes: pd.Series, cars: pd.Series) -> tuple[float, float]:
    """Wrapper around scipy.stats.spearmanr that absorbs degenerate cases."""
    if len(magnitudes) < 2:
        return float("nan"), float("nan")
    if magnitudes.nunique() < 2 or cars.nunique() < 2:
        # Spearman is undefined when one variable has zero rank variation.
        return float("nan"), float("nan")
    res = stats.spearmanr(magnitudes.to_numpy(), cars.to_numpy())
    rho = float(res.statistic)  # type: ignore[attr-defined]
    pvalue = float(res.pvalue)  # type: ignore[attr-defined]
    return rho, pvalue


def compute_ic(metrics: pd.DataFrame) -> pd.DataFrame:
    """Compute Spearman IC + p-value per (event_type, holding_window).

    Args:
        metrics: long-format DataFrame from `compute_event_metrics`
            (cols ``EVENT_METRICS_COLUMNS``). NaN ``car`` and NaN
            ``event_magnitude`` rows are dropped per group before the
            correlation.

    Returns:
        DataFrame with columns ``IC_COLUMNS``:
            event_type, holding_window, n_pairs, ic, ic_pvalue
        Sorted by (event_type, holding_window). Groups with fewer than 2
        valid (magnitude, CAR) pairs after NaN removal yield NaN IC and
        NaN p-value with ``n_pairs`` recording the actual count.
    """
    if metrics is None or metrics.empty:
        return pd.DataFrame(columns=IC_COLUMNS)

    if not set(EVENT_METRICS_COLUMNS).issubset(metrics.columns):
        missing = set(EVENT_METRICS_COLUMNS) - set(metrics.columns)
        raise ValueError(f"metrics is missing required columns: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    for (event_type, hw), group in metrics.groupby(
        ["event_type", "holding_window"], sort=True, dropna=False
    ):
        valid = group.dropna(subset=["event_magnitude", "car"])
        n_pairs = len(valid)
        if n_pairs < 2:
            ic, pvalue = float("nan"), float("nan")
        else:
            ic, pvalue = _spearman_safe(valid["event_magnitude"], valid["car"])

        rows.append(
            {
                "event_type": event_type,
                "holding_window": int(hw),
                "n_pairs": n_pairs,
                "ic": ic,
                "ic_pvalue": pvalue,
            }
        )

    out = pd.DataFrame(rows, columns=IC_COLUMNS)
    return out.sort_values(["event_type", "holding_window"]).reset_index(drop=True)
