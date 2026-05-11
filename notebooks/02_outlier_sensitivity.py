"""Outlier-sensitivity analysis on Step 1 ufficiale (W4 verdict POSITIVE).

CONTEXT:
    The W4 quality gate per prereg §3.1 discovered that yfinance EPS data
    differs from Yahoo Finance / IR consensus EPS by GAAP vs adjusted
    methodology. The clearest case is MOD 2026-02-04 which our data reports
    as actual=-$0.90 (loss) → SUE=-13.95 (extreme outlier), while the
    Modine IR press release reports adjusted EPS of +$1.19 (beat vs
    consensus $0.99).

    Spearman IC is rank-based so absolute magnitude errors don't matter as
    long as ranks are preserved. But a SIGN FLIP (miss → beat) corrupts
    the rank, potentially affecting IC.

    This script measures how the cat A T+60 winning verdict moves under
    two outlier-removal scenarios:
        1. Remove only MOD 2026-02-04 (single confirmed sign-flip outlier)
        2. Remove all MOD events (broader robustness — MOD reporting style
           may systematically diverge)

NOTE — PREREG COMPLIANCE:
    Per ADR 0002 §"One shot" the binding Step 1 verdict is the run
    committed in 0643568 + cfc8806. This sensitivity analysis is
    explicitly NON-binding research, lives in notebooks/ (out of pipeline
    per CLAUDE.md), and does NOT modify decision.json or ADR 0003.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from catalystlab.stats.bh_correction import bh_correct_pvalues
from catalystlab.stats.bootstrap import bootstrap_ic_ci

METRICS_PATH = "data/processed/event_metrics_ai_infra.parquet"
SECTOR_SEED = 42  # sector.random_seed
BOOTSTRAP_N = 1000


def _recompute_cat_a_t60(metrics: pd.DataFrame, label: str) -> dict:
    """IC + p + bootstrap CI + hit_rate + mean CAR for cat A T+60."""
    sub = metrics[(metrics["event_type"] == "A") & (metrics["holding_window"] == 60)]
    sub = sub.dropna(subset=["event_magnitude", "car"])
    n = len(sub)

    if n < 2:
        return {"label": label, "n_valid": n}

    mag = sub["event_magnitude"].to_numpy()
    car = sub["car"].to_numpy()

    spear = stats.spearmanr(mag, car)
    ic = float(spear.statistic)
    pvalue = float(spear.pvalue)

    rng = np.random.default_rng(SECTOR_SEED)
    _point, ci_lo, ci_hi = bootstrap_ic_ci(mag, car, n_resample=BOOTSTRAP_N, rng=rng)

    sign_hits = sum(1 for m, c in zip(mag, car, strict=False) if m * c > 0)
    sign_zeros = sum(1 for m, c in zip(mag, car, strict=False) if m == 0 or c == 0)
    hit_rate = sign_hits / max(n - sign_zeros, 1)
    cost = 95.5 / 10_000.0
    mean_car_net = float(np.mean(car)) - cost

    return {
        "label": label,
        "n_valid": n,
        "ic": ic,
        "ic_pvalue": pvalue,
        "ic_ci_lo": ci_lo,
        "ic_ci_hi": ci_hi,
        "hit_rate": hit_rate,
        "mean_car_net_bps": mean_car_net * 10_000,
    }


def _bh_check(scenario_pvalue: float, other_scenarios_pvalues: list[float]) -> float:
    """Recompute BH-corrected p-value for cat A given pvalues of all 5 categories.

    For the binding run, BH is applied per holding_window over 5 categories
    (n_tests=5). We need the same family of p-values to recompute correctly.
    Here we approximate by re-using the W4 binding p-values for B/C/D/E at
    T+60 (since removing MOD doesn't affect them) and only changing A's.
    """
    family = [scenario_pvalue] + other_scenarios_pvalues
    adjusted = bh_correct_pvalues(np.array(family))
    return float(adjusted[0])


def main() -> None:
    metrics = pd.read_parquet(METRICS_PATH)
    metrics["event_date"] = pd.to_datetime(metrics["event_date"])

    # T+60 cat A: identify MOD 2026-02-04
    a60 = metrics[(metrics["event_type"] == "A") & (metrics["holding_window"] == 60)]
    a60_valid = a60.dropna(subset=["event_magnitude", "car"])
    print(f"=== Baseline cat A T+60 ===")
    print(f"  Total rows in metrics: {len(a60)}")
    print(f"  Valid (non-NaN beta/CAR): {len(a60_valid)}")
    print()

    print("=== MOD events in cat A T+60 ===")
    mod_a60 = a60_valid[a60_valid["ticker"] == "MOD"]
    print(mod_a60[["ticker", "event_date", "event_magnitude", "beta", "car"]].to_string(index=False))
    print()

    # W4 binding values from decision.json — for BH context
    BH_FAMILY_T60 = {
        # raw uncorrected p-values at T+60 for each category from W4 summary
        "B": 0.800,
        "C": 0.895,
        "D": 0.031,
        "E": 0.174,
    }

    # Three scenarios
    results = []
    results.append(_recompute_cat_a_t60(metrics, "BINDING (all events)"))

    # Scenario 1: remove only MOD 2026-02-04
    m1 = metrics[
        ~(
            (metrics["ticker"] == "MOD")
            & (metrics["event_date"] == pd.Timestamp("2026-02-04"))
        )
    ]
    results.append(_recompute_cat_a_t60(m1, "MOD 2026-02-04 removed"))

    # Scenario 2: remove all MOD events
    m2 = metrics[metrics["ticker"] != "MOD"]
    results.append(_recompute_cat_a_t60(m2, "ALL MOD events removed"))

    print("=== Sensitivity results: cat A T+60 ===")
    print(f"{'Scenario':<28} {'n':>3} {'IC':>7} {'p-raw':>7} {'BH-p':>7} {'CI lo':>7} {'CI hi':>7} {'hit':>5} {'CAR net':>9}")
    print("-" * 88)
    for r in results:
        if "ic" not in r:
            print(f"{r['label']:<28} {r['n_valid']:>3} (insufficient data)")
            continue
        bh_p = _bh_check(
            r["ic_pvalue"],
            list(BH_FAMILY_T60.values()),
        )
        print(
            f"{r['label']:<28} {r['n_valid']:>3} "
            f"{r['ic']:>+.3f} {r['ic_pvalue']:>.4f} {bh_p:>.4f} "
            f"{r['ic_ci_lo']:>+.3f} {r['ic_ci_hi']:>+.3f} "
            f"{r['hit_rate']:>.1%} {r['mean_car_net_bps']:>+7.0f}bps"
        )
    print()
    print("Binding verdict thresholds (prereg §6.3):")
    print("  IC > 0.05  |  BH-corrected p < 0.05  |  hit_rate > 0.55  |  CI excludes 0")
    print()
    print("Interpretation:")
    print("  - If ALL scenarios still meet all 4 thresholds, verdict POSITIVE is robust.")
    print("  - If MOD removal moves any threshold below pass, the W4 verdict is sensitive")
    print("    to the data-quality issue identified in the §3.1 quality gate.")


if __name__ == "__main__":
    main()
