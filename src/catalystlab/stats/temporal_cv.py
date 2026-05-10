"""Layer 4 — temporal cross-validation (prereg §6.4).

Per prereg §6.4: "Cross-validation temporale: split del dataset in
pre-2025 e 2025-2026 per detection di decay".

For each (event_type, holding_window), compute the Spearman IC on the
two halves separately and report ``decay = ic_post - ic_pre``. A large
negative decay (especially when the pre-period IC was strong) is a
signal that the alpha is becoming priced-in over time.

This is informational; the binding decision criteria sit in §8.1-§8.3
(IC + BH-p + hit_rate + bootstrap CI). Temporal decay enters the
qualitative review at the closure of Step 1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

DEFAULT_SPLIT_DATE: pd.Timestamp = pd.Timestamp("2025-01-01")

TEMPORAL_CV_COLUMNS: list[str] = [
    "event_type",
    "holding_window",
    "split_date",
    "n_pre",
    "ic_pre",
    "n_post",
    "ic_post",
    "decay",
]


def _spearman_or_nan(magnitudes: np.ndarray, cars: np.ndarray) -> float:
    valid = ~(np.isnan(magnitudes) | np.isnan(cars))
    m, c = magnitudes[valid], cars[valid]
    if len(m) < 2 or np.unique(m).size < 2 or np.unique(c).size < 2:
        return float("nan")
    return float(stats.spearmanr(m, c).statistic)  # type: ignore[attr-defined]


def compute_temporal_decay(
    metrics: pd.DataFrame,
    split_date: pd.Timestamp = DEFAULT_SPLIT_DATE,
) -> pd.DataFrame:
    """Per (event_type, holding_window), compute IC on pre/post split halves.

    Args:
        metrics: long-format event metrics with ``event_date`` column.
        split_date: events with ``event_date < split_date`` go to "pre",
            others to "post". Defaults to 2025-01-01 per prereg §6.4.

    Returns:
        DataFrame with columns ``TEMPORAL_CV_COLUMNS`` sorted by
        (event_type, holding_window). ``decay = ic_post - ic_pre``;
        NaN propagates from either side.
    """
    if metrics is None or metrics.empty:
        return pd.DataFrame(columns=TEMPORAL_CV_COLUMNS)

    required = {"event_type", "holding_window", "event_magnitude", "car", "event_date"}
    missing = required - set(metrics.columns)
    if missing:
        raise ValueError(f"metrics missing required columns: {sorted(missing)}")

    df = metrics.copy()
    df["event_date"] = pd.to_datetime(df["event_date"])
    split_ts = pd.Timestamp(split_date)

    rows: list[dict[str, object]] = []
    for (et, hw), group in df.groupby(["event_type", "holding_window"], sort=True):
        pre = group[group["event_date"] < split_ts]
        post = group[group["event_date"] >= split_ts]

        ic_pre = _spearman_or_nan(
            pre["event_magnitude"].to_numpy(), pre["car"].to_numpy()
        )
        ic_post = _spearman_or_nan(
            post["event_magnitude"].to_numpy(), post["car"].to_numpy()
        )
        decay = (
            float("nan")
            if np.isnan(ic_pre) or np.isnan(ic_post)
            else ic_post - ic_pre
        )

        rows.append(
            {
                "event_type": et,
                "holding_window": int(hw),
                "split_date": split_ts.date().isoformat(),
                "n_pre": len(pre),
                "ic_pre": ic_pre,
                "n_post": len(post),
                "ic_post": ic_post,
                "decay": decay,
            }
        )

    return pd.DataFrame(rows, columns=TEMPORAL_CV_COLUMNS)
