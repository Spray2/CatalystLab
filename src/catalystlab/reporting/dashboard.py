"""Paper/live trading dashboard renderer (W5 UX).

Sister module to `html_report.py`: same Jinja2 pattern, different
template + payload. Renders `data/processed/dashboard_<sector>.html`
from a paper-trading CSV + helper outputs (drawdown, sizing, today
actions, upcoming earnings).

CLAUDE.md constraints:
    - Streamlit / Dash / interactive UI banned ("No-no")
    - This is a STATIC HTML page, regenerated on every paper-tick.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME: str = "dashboard.html.j2"


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of dicts with NaN replaced by None."""
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


def _enrich_in_flight(
    rows: pd.DataFrame, today: pd.Timestamp, holding_window: int = 60
) -> list[dict[str, Any]]:
    """Add days_held and days_remaining to in_flight rows."""
    in_flight = rows[rows["status"] == "in_flight"].copy() if not rows.empty else pd.DataFrame()
    if in_flight.empty:
        return []
    out: list[dict[str, Any]] = []
    for rec in _records(in_flight):
        entry_date = rec.get("entry_date")
        if entry_date:
            entry_ts = pd.Timestamp(entry_date)
            days_held = (today - entry_ts).days
        else:
            days_held = 0
        days_remaining = max(0, holding_window - days_held)
        rec["days_held"] = days_held
        rec["days_remaining"] = days_remaining
        out.append(rec)
    return out


def render_dashboard(
    *,
    sector: str,
    display_name: str,
    combination: str,
    cap_eur: float,
    max_per_trade_eur: float,
    timestamp_utc: str,
    today: pd.Timestamp,
    rows: pd.DataFrame,
    drawdown: dict,
    sizing: dict,
    today_actions: dict,
    upcoming_earnings: Iterable[dict] | None = None,
    extra_alerts: Iterable[dict] | None = None,
    holding_window: int = 60,
) -> str:
    """Render the paper/live trading dashboard HTML.

    Args:
        sector: sector slug (e.g. "ai_infra").
        display_name: human-readable sector name.
        combination: winning combination label (e.g. "A T+60").
        cap_eur: binding capital cap.
        max_per_trade_eur: max position size per trade.
        timestamp_utc: ISO-8601 generation timestamp.
        today: today timestamp.
        rows: paper-trading DataFrame (`PAPER_TRADE_COLUMNS`).
        drawdown: output of `compute_drawdown_status`.
        sizing: output of `compute_sizing` (must include `cap_deployed_pct`
            convenience field — added here if missing).
        today_actions: output of `compute_today_actions`.
        upcoming_earnings: iterable of {ticker, date, estimate_eps}.
        extra_alerts: iterable of {level: info|warn|danger, text}.
        holding_window: T+N for cat A (default 60).

    Returns:
        Rendered HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_NAME)

    if "cap_deployed_pct" not in sizing:
        sizing = dict(sizing)
        sizing["cap_deployed_pct"] = (
            (sizing["cap_deployed_eur"] / cap_eur) * 100.0 if cap_eur > 0 else 0.0
        )

    if rows is None or rows.empty:
        closed_rows: list[dict[str, Any]] = []
        in_flight_rows: list[dict[str, Any]] = []
        pending_rows: list[dict[str, Any]] = []
        n_closed = n_in_flight = n_pending = 0
        cumulative_net_pct = 0.0
    else:
        closed = rows[rows["status"] == "closed"].copy().sort_values("exit_date")
        closed_rows = _records(closed)
        in_flight_rows = _enrich_in_flight(rows, today, holding_window)
        pending = rows[rows["status"] == "pending_review"].copy()
        pending_rows = _records(pending)
        n_closed = len(closed)
        n_in_flight = len(in_flight_rows)
        n_pending = len(pending)
        # Cumulative net % of cap, using €1000 position convention.
        position_eur = 1000.0
        weight = position_eur / cap_eur if cap_eur > 0 else 0.0
        cumulative_net_pct = float(closed["net_return"].fillna(0.0).sum()) * weight

    return template.render(
        sector=sector,
        display_name=display_name,
        combination=combination,
        cap_eur=cap_eur,
        max_per_trade_eur=max_per_trade_eur,
        timestamp_utc=timestamp_utc,
        drawdown=drawdown,
        sizing=sizing,
        today_actions=today_actions,
        in_flight_rows=in_flight_rows,
        closed_rows=closed_rows,
        pending_rows=pending_rows,
        n_closed=n_closed,
        n_in_flight=n_in_flight,
        n_pending=n_pending,
        cumulative_net_pct=cumulative_net_pct,
        upcoming_earnings=list(upcoming_earnings) if upcoming_earnings else [],
        extra_alerts=list(extra_alerts) if extra_alerts else [],
    )
