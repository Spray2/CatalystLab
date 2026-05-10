"""Layer 4 — Benjamini-Hochberg FDR correction (prereg §6.3).

The pre-registration asks for BH-FDR correction across the 5 simultaneous
category tests (one per category A-E), at family-wise level alpha = 0.05
(``sector.stats.bh_alpha``). The threshold for declaring a (category,
holding_window) successful is then::

    IC > 0.05  AND  BH-corrected p < 0.05  AND  hit_rate > 0.55

Implementation choices documented inline:

1. The BH correction is applied INDEPENDENTLY PER HOLDING WINDOW, treating
   the 5 categories within a window as the family of simultaneous tests.
   This matches the prereg framing ("5 test simultanei, uno per categoria")
   while still letting each holding window be evaluated in isolation.

2. ``n_tests`` can be overridden to pin the family size. With NaN p-values
   (e.g. underpowered B/C/E categories with n<5 events), the default is
   ``m = number of non-NaN p-values``; passing ``n_tests=5`` enforces the
   strict 5-test family even when some are missing — more conservative,
   prereg-aligned.

3. Corrected p-values are computed as the right-cumulative minimum of
   ``p_(k) * m / k`` over rank k, capped at 1. This is the "step-up"
   adjusted p-value form (Benjamini-Hochberg 1995) which guarantees:

   - corrected_p >= raw_p element-wise
   - rank-monotone: corrected_(i) <= corrected_(j) when raw_p_(i) <= raw_p_(j)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

DEFAULT_BH_ALPHA: float = 0.05


def bh_correct_pvalues(
    pvalues: ArrayLike,
    n_tests: int | None = None,
) -> np.ndarray:
    """Compute BH-FDR adjusted p-values for an array of raw p-values.

    Args:
        pvalues: array-like of raw p-values, possibly containing NaN.
        n_tests: total family size. If None, inferred from non-NaN count.
            Pass an integer to enforce a fixed family size larger than the
            observed valid count (e.g. 5 for prereg "5 test simultanei").

    Returns:
        ``np.ndarray`` of shape ``len(pvalues)`` with BH-corrected p-values.
        NaN inputs propagate to NaN outputs (those tests are excluded from
        the ranking and family count when ``n_tests is None``).

    Properties:
        - corrected_p >= raw_p (element-wise on non-NaN entries)
        - corrected_p is rank-monotone in raw_p
        - corrected_p capped at 1.0
    """
    raw = np.asarray(pvalues, dtype=float)
    if raw.ndim != 1:
        raise ValueError(f"pvalues must be 1-D, got {raw.ndim}-D")

    out = np.full_like(raw, np.nan, dtype=float)
    valid_mask = ~np.isnan(raw)
    valid = raw[valid_mask]
    n_valid = len(valid)

    if n_valid == 0:
        return out

    m = n_tests if n_tests is not None else n_valid
    if m <= 0:
        raise ValueError(f"n_tests must be > 0, got {n_tests}")
    if m < n_valid:
        raise ValueError(
            f"n_tests ({m}) must be >= number of valid p-values ({n_valid})"
        )

    order = np.argsort(valid, kind="mergesort")
    sorted_p = valid[order]

    # Step-up adjusted: q_(k) = min_{j >= k} (p_(j) * m / j)
    ranks = np.arange(1, n_valid + 1)
    raw_adj = sorted_p * m / ranks
    # Right-cumulative minimum to enforce rank-monotonicity.
    adj_sorted = np.minimum.accumulate(raw_adj[::-1])[::-1]
    adj_sorted = np.minimum(adj_sorted, 1.0)

    adj_unordered = np.empty(n_valid, dtype=float)
    adj_unordered[order] = adj_sorted
    out[valid_mask] = adj_unordered
    return out


def apply_bh_per_holding_window(
    summary: pd.DataFrame,
    alpha: float = DEFAULT_BH_ALPHA,
    pvalue_col: str = "ic_pvalue",
    n_tests_per_window: int | None = None,
) -> pd.DataFrame:
    """Apply BH-FDR within each holding_window group across categories.

    Args:
        summary: DataFrame with at least ``holding_window`` and
            ``pvalue_col`` columns (typically the merged event_summary
            from the W2 CLI).
        alpha: FDR level (default 0.05 from prereg §6.3).
        pvalue_col: name of the raw p-value column.
        n_tests_per_window: optional fixed family size per window. With
            5 categories A-E and ``n_tests_per_window=5`` the correction
            stays strict even when NaN p-values reduce the observed family.

    Returns:
        Copy of ``summary`` with two new columns:
            - ``ic_pvalue_bh``: BH-adjusted p-value
            - ``bh_reject``: True when ``ic_pvalue_bh < alpha`` and not NaN
    """
    if summary is None or summary.empty:
        out = summary.copy() if summary is not None else pd.DataFrame()
        out["ic_pvalue_bh"] = pd.Series(dtype=float)
        out["bh_reject"] = pd.Series(dtype=bool)
        return out

    if pvalue_col not in summary.columns:
        raise ValueError(f"summary missing required column: {pvalue_col!r}")
    if "holding_window" not in summary.columns:
        raise ValueError("summary missing required column: 'holding_window'")

    out = summary.copy()
    out["ic_pvalue_bh"] = np.nan

    for _hw, group in out.groupby("holding_window", sort=True):
        idx = group.index
        pvals = group[pvalue_col].to_numpy()
        adjusted = bh_correct_pvalues(pvals, n_tests=n_tests_per_window)
        out.loc[idx, "ic_pvalue_bh"] = adjusted

    out["bh_reject"] = (out["ic_pvalue_bh"] < alpha).fillna(False)
    return out
