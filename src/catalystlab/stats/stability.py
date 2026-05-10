"""Layer 4 — outlier-driven IC stability check (prereg §6.4).

Per prereg §6.4: "rimozione iterativa dei top 5 eventi per categoria per
testare se l'IC è driven da outlier".

For each (event_type, holding_window) group, the stability check
recomputes the Spearman IC after dropping the top-k events ranked by the
absolute magnitude of CAR (the natural notion of "outlier driver" in the
event-study setting). A large gap between ``ic_full`` and
``ic_after_top_k`` signals a fragile result driven by a small number of
extreme observations.

This stat is informational; the binding §8 decision criteria are IC + BH +
hit_rate + bootstrap CI. Stability enters the qualitative review at the
closure of Step 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

DEFAULT_K_TOP_REMOVE: int = 5

STABILITY_COLUMNS: list[str] = [
    "event_type",
    "holding_window",
    "k_removed",
    "n_full",
    "ic_full",
    "n_after",
    "ic_after_top_k",
    "ic_drift",
]


def _spearman_or_nan(magnitudes: np.ndarray, cars: np.ndarray) -> float:
    valid = ~(np.isnan(magnitudes) | np.isnan(cars))
    m, c = magnitudes[valid], cars[valid]
    if len(m) < 2 or np.unique(m).size < 2 or np.unique(c).size < 2:
        return float("nan")
    return float(stats.spearmanr(m, c).statistic)  # type: ignore[attr-defined]


def compute_stability(
    metrics: pd.DataFrame,
    k_top: int = DEFAULT_K_TOP_REMOVE,
) -> pd.DataFrame:
    """Per (event_type, holding_window), recompute IC after dropping top-k events.

    Args:
        metrics: long-format event metrics with at least
            ``[event_type, holding_window, event_magnitude, car]``.
        k_top: number of top-|CAR| events to remove. If a group has fewer
            than ``k_top + 2`` valid pairs, ``ic_after_top_k`` is NaN
            (Spearman undefined on <2 pairs).

    Returns:
        DataFrame with columns ``STABILITY_COLUMNS`` sorted by
        ``(event_type, holding_window)``. ``ic_drift = ic_after_top_k -
        ic_full``; NaN propagates from either side.
    """
    if k_top <= 0:
        raise ValueError(f"k_top must be > 0, got {k_top}")

    if metrics is None or metrics.empty:
        return pd.DataFrame(columns=STABILITY_COLUMNS)

    required = {"event_type", "holding_window", "event_magnitude", "car"}
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"metrics missing required columns: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    for (et, hw), group in metrics.groupby(["event_type", "holding_window"], sort=True):
        valid = group.dropna(subset=["event_magnitude", "car"]).copy()
        n_full = len(valid)
        ic_full = _spearman_or_nan(
            valid["event_magnitude"].to_numpy(), valid["car"].to_numpy()
        )

        if n_full <= k_top:
            ic_after = float("nan")
            n_after = 0
            actual_k = n_full
        else:
            valid["_abs_car"] = valid["car"].abs()
            kept = valid.nsmallest(n_full - k_top, "_abs_car")
            ic_after = _spearman_or_nan(
                kept["event_magnitude"].to_numpy(), kept["car"].to_numpy()
            )
            n_after = len(kept)
            actual_k = k_top

        drift = (
            float("nan")
            if np.isnan(ic_full) or np.isnan(ic_after)
            else ic_after - ic_full
        )

        rows.append(
            {
                "event_type": et,
                "holding_window": int(hw),
                "k_removed": actual_k,
                "n_full": n_full,
                "ic_full": ic_full,
                "n_after": n_after,
                "ic_after_top_k": ic_after,
                "ic_drift": drift,
            }
        )

    return pd.DataFrame(rows, columns=STABILITY_COLUMNS)
