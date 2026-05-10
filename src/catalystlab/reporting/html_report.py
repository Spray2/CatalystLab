"""Layer 5 — Jinja2 HTML report renderer.

Consumes the merged summary + temporal decay + stability frames produced
by Layer 3+4 and emits a static HTML page suitable for archival next to
``data/processed/decision_<sector>.json``.

The template is bundled at ``catalystlab/reporting/templates/report.html.j2``;
this module is the thin Python wrapper that fills it.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME: str = "report.html.j2"


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of plain dicts; converts NaN to None for clean Jinja."""
    if df is None or df.empty:
        return []
    out: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        cleaned: dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, float) and v != v:  # NaN
                cleaned[k] = None
            else:
                cleaned[k] = v
        out.append(cleaned)
    return out


def render_report(
    *,
    sector: str,
    display_name: str,
    prereg_version: str,
    prereg_lockfile_date: str,
    period_start: str,
    period_end: str,
    universe: Iterable[str],
    benchmark_primary: str,
    benchmark_secondary: str,
    holding_windows: Iterable[int],
    cost_bps_round_trip: float,
    cost_position_eur: float,
    sector_yaml_sha256: str,
    git_commit: str | None,
    timestamp_utc: str,
    decision: dict,
    summary_full: pd.DataFrame,
    temporal: pd.DataFrame | None = None,
    stability: pd.DataFrame | None = None,
    temporal_split_date: str | None = None,
    stability_k: int | None = None,
) -> str:
    """Render the Step 1 HTML report.

    Args:
        sector / display_name / prereg_version / etc: header metadata
            extracted from ``SectorConfig`` and the run manifest.
        decision: dict from ``reporting.decision.decide``.
        summary_full: per-(category, holding_window) frame already
            annotated with ``annotate_decision_flags`` (must contain
            ``passes_*``, ``is_winning``, ``is_ambiguous`` columns).
        temporal: optional output of ``stats.temporal_cv.compute_temporal_decay``.
        stability: optional output of ``stats.stability.compute_stability``.

    Returns:
        Fully-rendered HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,  # always escape; the only template here renders HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_NAME)

    summary_rows = _records(summary_full.sort_values(["event_type", "holding_window"]))
    temporal_rows = _records(temporal) if temporal is not None else []
    stability_rows = _records(stability) if stability is not None else []

    return template.render(
        sector=sector,
        display_name=display_name,
        prereg_version=prereg_version,
        prereg_lockfile_date=prereg_lockfile_date,
        period_start=period_start,
        period_end=period_end,
        universe=list(universe),
        benchmark_primary=benchmark_primary,
        benchmark_secondary=benchmark_secondary,
        holding_windows=list(holding_windows),
        cost_bps_round_trip=cost_bps_round_trip,
        cost_position_eur=cost_position_eur,
        sector_yaml_sha256=sector_yaml_sha256,
        git_commit=git_commit,
        timestamp_utc=timestamp_utc,
        decision=decision,
        summary_rows=summary_rows,
        temporal_rows=temporal_rows,
        temporal_split_date=temporal_split_date or "",
        stability_rows=stability_rows,
        stability_k=stability_k,
    )
