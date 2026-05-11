"""Tests for catalystlab.reporting.dashboard (W5 UX render_dashboard)."""

from __future__ import annotations

import pandas as pd

from catalystlab.paper_trading import (
    PAPER_TRADE_COLUMNS,
    compute_drawdown_status,
    compute_sizing,
    compute_today_actions,
)
from catalystlab.reporting.dashboard import render_dashboard


def _common_kwargs(today: pd.Timestamp) -> dict:
    return {
        "sector": "ai_infra",
        "display_name": "AI Infrastructure US",
        "combination": "A T+60 (PEAD)",
        "cap_eur": 5000.0,
        "max_per_trade_eur": 1000.0,
        "timestamp_utc": "2026-05-11T08:00:00+00:00",
        "today": today,
    }


def test_render_empty_rows_basic_structure() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **_common_kwargs(today),
    )
    assert "<!DOCTYPE html>" in html
    assert "ai_infra" in html
    assert "AI Infrastructure US" in html
    assert "Disclaimer" in html
    # Empty CSV → no actions banner
    assert "No actions today" in html
    assert "Nessuna posizione aperta" in html


def test_render_drawdown_review_banner() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(
        [
            {
                "trade_id": i, "ticker": f"T{i}", "event_date": "2024-01-15",
                "sue": 2.0, "sue_sign": 1, "status": "closed",
                "entry_date": "2024-01-16", "entry_price": 100.0,
                "exit_date": f"2024-0{i+1}-01", "exit_price": 50.0,
                "gross_return": -0.50 + 0.00955, "cost_bps": 95.5,
                "net_return": -0.50, "notes": "",
            }
            for i in range(1, 4)
        ]
    )
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **_common_kwargs(today),
    )
    assert "REVIEW threshold reached" in html
    assert "review" in html  # CSS class


def test_render_hard_stop_banner() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(
        [
            {
                "trade_id": i, "ticker": f"T{i}", "event_date": "2024-01-15",
                "sue": 2.0, "sue_sign": 1, "status": "closed",
                "entry_date": "2024-01-16", "entry_price": 100.0,
                "exit_date": f"2024-{i:02d}-01", "exit_price": 50.0,
                "gross_return": -0.50 + 0.00955, "cost_bps": 95.5,
                "net_return": -0.50, "notes": "",
            }
            for i in range(1, 6)
        ]
    )
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **_common_kwargs(today),
    )
    assert "HARD STOP triggered" in html


def test_render_open_position_listed() -> None:
    today = pd.Timestamp("2024-02-01")
    rows = pd.DataFrame(
        [
            {
                "trade_id": 1, "ticker": "VRT", "event_date": "2024-01-15",
                "sue": 2.5, "sue_sign": 1, "status": "in_flight",
                "entry_date": "2024-01-16", "entry_price": 100.0,
                "exit_date": "", "exit_price": float("nan"),
                "gross_return": float("nan"), "cost_bps": float("nan"),
                "net_return": float("nan"), "notes": "",
            }
        ]
    )
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **_common_kwargs(today),
    )
    assert ">VRT<" in html
    assert "long" in html
    assert "Open positions (1)" in html


def test_render_pending_review_section_shown() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(
        [
            {
                "trade_id": 1, "ticker": "CEG", "event_date": "2026-05-11",
                "sue": 1.8, "sue_sign": 1, "status": "pending_review",
                "entry_date": "", "entry_price": float("nan"),
                "exit_date": "", "exit_price": float("nan"),
                "gross_return": float("nan"), "cost_bps": float("nan"),
                "net_return": float("nan"), "notes": "auto-detected",
            }
        ]
    )
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **_common_kwargs(today),
    )
    assert "Pending review (1)" in html
    assert "IR press release" in html  # caveat note


def test_render_upcoming_earnings_listed() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    upcoming = [
        {"ticker": "CEG", "date": "2026-05-11", "estimate_eps": 2.61},
        {"ticker": "MOD", "date": "2026-05-19", "estimate_eps": 1.55},
    ]
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        upcoming_earnings=upcoming,
        **_common_kwargs(today),
    )
    assert ">CEG<" in html
    assert ">MOD<" in html
    assert "2026-05-19" in html


def test_render_extra_alerts_shown() -> None:
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    alerts = [{"level": "warn", "text": "ADR 0004 caveat: yfinance sign-flip risk"}]
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        extra_alerts=alerts,
        **_common_kwargs(today),
    )
    assert "ADR 0004 caveat" in html


def test_render_html_escapes_user_input() -> None:
    """display_name with HTML chars must be escaped (autoescape=True)."""
    today = pd.Timestamp("2026-05-11")
    rows = pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    kw = _common_kwargs(today)
    kw["display_name"] = "AI Infra <script>alert(1)</script>"
    html = render_dashboard(
        rows=rows,
        drawdown=compute_drawdown_status(rows, 5000.0),
        sizing=compute_sizing(rows, 5000.0),
        today_actions=compute_today_actions(rows, today=today),
        **kw,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
