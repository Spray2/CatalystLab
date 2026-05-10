"""Layer 5 — Step 1 binary decision (prereg §8).

Reads the merged Layer 3+4 summary (one row per category x holding_window
with: ic, ic_pvalue, ic_pvalue_bh, bh_reject, hit_rate, mean_car_net,
ic_ci_lower, ic_ci_upper, ic_ci_crosses_zero) and emits a decision record
following the prereg §8 binding rules:

    §8.1 POSITIVE  : at least 1 (cat x hw) with
                     IC > stats.ic_threshold AND
                     BH-corrected p < stats.bh_alpha AND
                     hit_rate > stats.hit_rate_threshold AND
                     bootstrap CI does NOT cross zero
                  -> step 2a (paper trading 1 month) -> step 2b (live €5k cap)

    §8.2 NEGATIVE  : no combination passes the success rule
                  -> closure of AI Infra; new sector pre-registration

    §8.3 AMBIGUOUS : at least 1 combination passes IC + hit_rate but fails
                     either BH or has bootstrap CI crossing zero
                  -> treated as NEGATIVE for action ("trattato come
                     negativo per evitare confirmation bias")

The function records the per-combination outcome flags so the HTML
report can show which conditions were met / failed for each candidate.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

DecisionVerdict = Literal["positive", "negative", "ambiguous"]

DECISION_FLAG_COLUMNS: list[str] = [
    "passes_ic",
    "passes_hit_rate",
    "passes_bh",
    "passes_ci",
    "is_winning",
    "is_ambiguous",
]


def annotate_decision_flags(
    summary: pd.DataFrame,
    ic_threshold: float,
    hit_rate_threshold: float,
    bh_alpha: float,
) -> pd.DataFrame:
    """Add per-combination decision flags to a summary frame.

    The summary must already contain ``ic, ic_pvalue_bh, hit_rate,
    ic_ci_crosses_zero`` (apply Layer 4 corrections beforehand).

    Adds columns ``DECISION_FLAG_COLUMNS``:
        passes_ic        -> ic > ic_threshold
        passes_hit_rate  -> hit_rate > hit_rate_threshold
        passes_bh        -> ic_pvalue_bh < bh_alpha
        passes_ci        -> NOT ic_ci_crosses_zero
        is_winning       -> all four pass
        is_ambiguous     -> passes_ic AND passes_hit_rate
                           AND (NOT passes_bh OR NOT passes_ci)
    """
    out = summary.copy()
    out["passes_ic"] = (out["ic"] > ic_threshold).fillna(False)
    out["passes_hit_rate"] = (out["hit_rate"] > hit_rate_threshold).fillna(False)
    out["passes_bh"] = (out["ic_pvalue_bh"] < bh_alpha).fillna(False)

    crosses = out.get(
        "ic_ci_crosses_zero",
        pd.Series([False] * len(out), index=out.index),
    )
    out["passes_ci"] = (~crosses.astype(bool)).where(
        ~(out["ic_ci_lower"].isna() if "ic_ci_lower" in out else pd.Series([False] * len(out))),
        other=False,
    )

    out["is_winning"] = (
        out["passes_ic"]
        & out["passes_hit_rate"]
        & out["passes_bh"]
        & out["passes_ci"]
    )
    out["is_ambiguous"] = (
        out["passes_ic"]
        & out["passes_hit_rate"]
        & ~(out["passes_bh"] & out["passes_ci"])
    )
    return out


def decide(
    summary: pd.DataFrame,
    ic_threshold: float,
    hit_rate_threshold: float,
    bh_alpha: float,
) -> dict:
    """Return a decision artifact for the Step 1 sector run.

    Args:
        summary: long-format summary DataFrame, one row per (event_type,
            holding_window). Must contain ``ic, ic_pvalue_bh, hit_rate``;
            ``ic_ci_crosses_zero`` is required when bootstrap CIs are
            computed (otherwise treated as ``False`` -> CI passes).
        ic_threshold: prereg §6.3 base threshold (typically 0.05).
        hit_rate_threshold: prereg §6.3 hit rate floor (typically 0.55).
        bh_alpha: prereg §6.3 FDR alpha (typically 0.05).

    Returns:
        Dict with keys:
            - verdict: "positive" | "negative" | "ambiguous"
            - rationale: human-readable summary string
            - n_winning: count of fully-passing combinations
            - n_ambiguous: count of IC+hit_rate-passing but BH or CI failing
            - winning_combinations: list of dicts (event_type, holding_window,
                ic, ic_pvalue_bh, hit_rate, mean_car_net, ic_ci_lower, ic_ci_upper)
            - ambiguous_combinations: same shape; reason annotates which
                subcheck failed
            - thresholds: echoed thresholds
    """
    annotated = annotate_decision_flags(
        summary,
        ic_threshold=ic_threshold,
        hit_rate_threshold=hit_rate_threshold,
        bh_alpha=bh_alpha,
    )

    detail_cols = [
        c
        for c in (
            "event_type",
            "holding_window",
            "n_valid",
            "ic",
            "ic_pvalue",
            "ic_pvalue_bh",
            "hit_rate",
            "mean_car_net",
            "ic_ci_lower",
            "ic_ci_upper",
            "ic_ci_crosses_zero",
        )
        if c in annotated.columns
    ]

    winning = annotated[annotated["is_winning"]]
    ambiguous = annotated[annotated["is_ambiguous"] & ~annotated["is_winning"]]

    n_winning = len(winning)
    n_ambiguous = len(ambiguous)

    if n_winning >= 1:
        verdict: DecisionVerdict = "positive"
        rationale = (
            f"{n_winning} combinations pass IC > {ic_threshold}, "
            f"BH-corrected p < {bh_alpha}, hit_rate > {hit_rate_threshold}, "
            f"and bootstrap CI excludes 0. Per prereg §8.1 -> paper trading "
            f"(1 month) then live trading capped at €5,000."
        )
    elif n_ambiguous >= 1:
        verdict = "ambiguous"
        rationale = (
            f"{n_ambiguous} combinations pass IC + hit_rate but fail BH "
            f"correction or have bootstrap CI crossing 0. Per prereg §8.3 "
            f"ambiguous is treated as negative for action — closure of AI "
            f"Infra, no live trading."
        )
    else:
        verdict = "negative"
        rationale = (
            "No combination passes the prereg §6.3 success rule. "
            "Per prereg §8.2 -> closure of AI Infra; new sector "
            "pre-registration required for further research."
        )

    def _rows(df: pd.DataFrame) -> list[dict]:
        return df[detail_cols].to_dict(orient="records") if not df.empty else []

    def _annotate_ambiguous(rows: list[dict]) -> list[dict]:
        for r in rows:
            reasons = []
            bh_p = r.get("ic_pvalue_bh")
            if bh_p is None or pd.isna(bh_p) or bh_p >= bh_alpha:
                reasons.append(f"BH-corrected p >= {bh_alpha}")
            crosses = r.get("ic_ci_crosses_zero")
            if crosses:
                reasons.append("bootstrap CI crosses zero")
            r["ambiguous_reason"] = "; ".join(reasons) if reasons else "unknown"
        return rows

    return {
        "verdict": verdict,
        "rationale": rationale,
        "n_winning": n_winning,
        "n_ambiguous": n_ambiguous,
        "winning_combinations": _rows(winning),
        "ambiguous_combinations": _annotate_ambiguous(_rows(ambiguous)),
        "thresholds": {
            "ic_threshold": ic_threshold,
            "hit_rate_threshold": hit_rate_threshold,
            "bh_alpha": bh_alpha,
        },
    }
