"""Layer 3 — aggregation per (event_type, holding_window) (prereg §6.2).

Consumes the long-format output of `compute_event_metrics` and produces
group-level summary statistics:

    mean_CAR(c, [a,b]) = mean of CAR over all events in category c
    hit_rate(c, [a,b]) = fraction of events whose CAR sign matches the
                         expected direction (sign of event_magnitude)
    std_CAR(c, [a,b])  = sample std of CAR over the events

Per prereg §5.2: "Tutti gli abnormal returns dichiarati nel report
finale di Step 1 sono al netto di questo costo" — round-trip cost is
subtracted from each event's CAR before aggregation. Caller passes the
cost in bps; if 0, the gross CAR is reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from catalystlab.eventstudy.abnormal_returns import EVENT_METRICS_COLUMNS

AGGREGATION_COLUMNS: list[str] = [
    "event_type",
    "holding_window",
    "n_events",
    "n_valid",
    "mean_car_gross",
    "mean_car_net",
    "std_car",
    "hit_rate",
]


def _hit(magnitude: float, car: float) -> bool | None:
    """Hit indicator: True if sign(CAR) matches sign(magnitude).

    Returns None for cases where the test is undefined:
    - either value is NaN
    - magnitude is exactly zero (no signed thesis)
    - CAR is exactly zero (no realised direction)
    """
    if pd.isna(magnitude) or pd.isna(car):
        return None
    if magnitude == 0 or car == 0:
        return None
    return (magnitude > 0 and car > 0) or (magnitude < 0 and car < 0)


def aggregate_event_metrics(
    metrics: pd.DataFrame,
    cost_bps_round_trip: float = 0.0,
) -> pd.DataFrame:
    """Aggregate event metrics per (event_type, holding_window).

    Args:
        metrics: long-format DataFrame from `compute_event_metrics` with
            ``EVENT_METRICS_COLUMNS``.
        cost_bps_round_trip: round-trip cost in bps to subtract from each
            event's CAR before aggregating. The resulting ``mean_car_net``
            is the metric that should be checked against prereg §6.3
            thresholds.

    Returns:
        DataFrame with columns ``AGGREGATION_COLUMNS``, sorted by
        ``(event_type, holding_window)``. Empty input yields an empty
        frame with the same schema.

    Notes:
        - ``n_events``: total event-window rows in the group (including
          NaN CARs).
        - ``n_valid``: count of rows with non-NaN gross CAR.
        - ``hit_rate``: fraction of rows where sign(CAR_net) matches
          sign(magnitude). Excludes NaN cases and zero-magnitude /
          zero-CAR rows from both numerator and denominator.
    """
    if metrics is None or metrics.empty:
        return pd.DataFrame(columns=AGGREGATION_COLUMNS)

    if not set(EVENT_METRICS_COLUMNS).issubset(metrics.columns):
        missing = set(EVENT_METRICS_COLUMNS) - set(metrics.columns)
        raise ValueError(f"metrics is missing required columns: {sorted(missing)}")

    cost_decimal = cost_bps_round_trip / 10_000.0
    df = metrics.copy()
    df["car_net"] = df["car"] - cost_decimal

    rows: list[dict[str, object]] = []
    for (event_type, hw), group in df.groupby(
        ["event_type", "holding_window"], sort=True, dropna=False
    ):
        n_events = len(group)
        valid = group.dropna(subset=["car"])
        n_valid = len(valid)

        if n_valid == 0:
            mean_gross = float("nan")
            mean_net = float("nan")
            std_car = float("nan")
        else:
            mean_gross = float(valid["car"].mean())
            mean_net = mean_gross - cost_decimal
            std_car = float(valid["car"].std(ddof=1)) if n_valid >= 2 else float("nan")

        # Hit rate uses car_net (post-cost) against magnitude sign.
        hits = []
        for _, row in valid.iterrows():
            h = _hit(row["event_magnitude"], row["car_net"])
            if h is not None:
                hits.append(h)

        hit_rate = float(np.mean(hits)) if hits else float("nan")

        rows.append(
            {
                "event_type": event_type,
                "holding_window": int(hw),
                "n_events": n_events,
                "n_valid": n_valid,
                "mean_car_gross": mean_gross,
                "mean_car_net": mean_net,
                "std_car": std_car,
                "hit_rate": hit_rate,
            }
        )

    out = pd.DataFrame(rows, columns=AGGREGATION_COLUMNS)
    return out.sort_values(["event_type", "holding_window"]).reset_index(drop=True)
