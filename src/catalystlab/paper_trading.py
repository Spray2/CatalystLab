"""Paper trading automation (L2 semi-auto) — W5 operational shakedown.

Per ADR 0003 / prereg §8.1, the POSITIVE Step 1 v1 verdict on cat A T+60
triggers a 1-month paper trading phase. Per ADR 0004 the yfinance EPS
data has ~20% sign-flip rate so every candidate trade needs manual IR
verification (the human approval step in the state machine below).

State machine per row:

    pending_review -> approved -> in_flight -> closed
                   \
                    -> rejected (excluded from P&L)

Workflow:
    1. `paper_tick` detects new earnings events from the universe with
       |SUE| > sue_threshold (default 1.0) and not already in the CSV.
       New rows are appended with status="pending_review".
    2. The user manually verifies each pending_review row against the
       company IR press release and sets status to "approved" or
       "rejected" (editing the CSV directly; tooling is intentionally
       minimal — see ADR 0004 caveat).
    3. Subsequent `paper_tick` runs:
       - move approved rows -> in_flight at T+1 by fetching yfinance
         adj_close as entry_price
       - move in_flight rows -> closed at T+60 by fetching exit_price
         and computing gross/net return
    4. Cost: applied via `compute_cost_bps(sector.costs)` (95.5 bps
       round-trip on €1k per prereg §5.2).

Trading-day arithmetic uses `exchange_calendars` XNYS (already used by
ingestion.prices).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

import exchange_calendars as xcals
import pandas as pd

from catalystlab.config.schemas import SectorConfig
from catalystlab.ingestion.costs import compute_cost_bps
from catalystlab.ingestion.earnings import fetch_earnings
from catalystlab.ingestion.prices import fetch_prices

logger = logging.getLogger(__name__)

PAPER_TRADE_COLUMNS: list[str] = [
    "trade_id",
    "ticker",
    "event_date",
    "sue",
    "sue_sign",
    "status",  # pending_review | approved | rejected | in_flight | closed
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "gross_return",
    "cost_bps",
    "net_return",
    "notes",
]

VALID_STATUSES: frozenset[str] = frozenset(
    {"pending_review", "approved", "rejected", "in_flight", "closed"}
)


class TickSummary(TypedDict):
    new_candidates: int
    transitioned_in_flight: int
    transitioned_closed: int
    by_status: dict[str, int]
    cumulative_net_return: float


def empty_paper_csv(path: Path) -> None:
    """Create an empty paper-trading CSV with the schema header."""
    pd.DataFrame(columns=PAPER_TRADE_COLUMNS).to_csv(path, index=False)


def load_paper_csv(path: Path) -> pd.DataFrame:
    """Load the paper-trading CSV, returning an empty schema if missing.

    Date/note columns are coerced to string dtype so later string
    assignments don't trip the float→str dtype-promotion error.
    """
    if not path.is_file():
        return pd.DataFrame(columns=PAPER_TRADE_COLUMNS)
    df = pd.read_csv(
        path,
        dtype={
            "entry_date": "string",
            "exit_date": "string",
            "notes": "string",
            "status": "string",
            "ticker": "string",
            "event_date": "string",
        },
    )
    missing = [c for c in PAPER_TRADE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"paper CSV missing columns: {missing}")
    return df[PAPER_TRADE_COLUMNS]


def _next_trading_day(d: pd.Timestamp, *, n: int = 1) -> pd.Timestamp:
    """Return d + n trading days (XNYS calendar). Inclusive of next session."""
    cal = xcals.get_calendar("XNYS")
    sessions = cal.sessions_in_range(d, d + pd.Timedelta(days=120))
    # Sessions strictly after d
    after = sessions[sessions > pd.Timestamp(d)]
    if len(after) < n:
        raise ValueError(f"insufficient trading sessions after {d}")
    return pd.Timestamp(after[n - 1])


def detect_new_candidates(
    sector: SectorConfig,
    existing: pd.DataFrame,
    sue_threshold: float = 1.0,
    earnings_cache_dir: Path | None = None,
    min_event_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Fetch latest earnings for the universe and return rows to append.

    Args:
        sector: validated SectorConfig.
        existing: current paper CSV (to dedup).
        sue_threshold: |SUE| > this to qualify as candidate.
        earnings_cache_dir: optional cache for fetch_earnings.
        min_event_date: when provided, only events with announcement_date
            >= this date are eligible. This prevents the first paper_tick
            from back-flooding the CSV with the entire historical earnings
            of the universe (W5 paper trading begins on a specific date,
            past events cannot be paper-traded).
    """
    tickers = [t.ticker for t in sector.universe]
    earnings = fetch_earnings(
        tickers,
        cache_dir=earnings_cache_dir,
        sleep_between=0.2,
        use_cache=True,
    )
    if earnings.empty:
        return pd.DataFrame(columns=PAPER_TRADE_COLUMNS)

    # Keep only rows with computed SUE and |SUE| > threshold.
    earnings = earnings.dropna(subset=["sue"])
    earnings = earnings[earnings["sue"].abs() > sue_threshold]
    if min_event_date is not None:
        earnings = earnings[earnings["announcement_date"] >= pd.Timestamp(min_event_date)]
    if earnings.empty:
        return pd.DataFrame(columns=PAPER_TRADE_COLUMNS)

    # Exclude events already in `existing`.
    existing_keys = set(
        zip(
            existing["ticker"].astype(str),
            pd.to_datetime(existing["event_date"]).astype(str),
            strict=False,
        )
    )

    new_rows: list[dict[str, object]] = []
    next_id = (
        int(existing["trade_id"].max() + 1) if not existing.empty else 1
    )
    for _, ev in earnings.iterrows():
        key = (str(ev["ticker"]), str(ev["announcement_date"].date()))
        if key in existing_keys:
            continue
        sign = int(ev["surprise_sign"]) if pd.notna(ev["surprise_sign"]) else 0
        new_rows.append(
            {
                "trade_id": next_id,
                "ticker": ev["ticker"],
                "event_date": str(ev["announcement_date"].date()),
                "sue": float(ev["sue"]),
                "sue_sign": sign,
                "status": "pending_review",
                "entry_date": "",
                "entry_price": float("nan"),
                "exit_date": "",
                "exit_price": float("nan"),
                "gross_return": float("nan"),
                "cost_bps": float("nan"),
                "net_return": float("nan"),
                "notes": "auto-detected; verify IR press release before approving",
            }
        )
        next_id += 1
    return pd.DataFrame(new_rows, columns=PAPER_TRADE_COLUMNS)


def _fetch_close_on(ticker: str, target: pd.Timestamp) -> float:
    """Fetch adj_close for ticker on target trading day; NaN if missing."""
    target_date = target.date() if hasattr(target, "date") else target
    df = fetch_prices(
        [ticker],
        target_date,
        target_date,
        cache_dir=None,
        sleep_between=0.0,
        use_cache=False,
    )
    if df.empty:
        return float("nan")
    return float(df.iloc[0]["adj_close"])


def transition_rows(
    rows: pd.DataFrame,
    sector: SectorConfig,
    today: pd.Timestamp,
) -> tuple[pd.DataFrame, int, int]:
    """Apply state transitions: approved -> in_flight; in_flight -> closed.

    Returns (rows_after, n_in_flight_new, n_closed_new).
    """
    out = rows.copy()
    n_in_flight = 0
    n_closed = 0
    cost_bps = compute_cost_bps(sector.costs)

    holding_window = 60  # cat A T+60 winning combo

    for idx, row in out.iterrows():
        status = row["status"]
        ev_date = pd.Timestamp(row["event_date"])

        if status == "approved" and (
            pd.isna(row["entry_price"]) or row["entry_price"] == ""
        ):
            t1 = _next_trading_day(ev_date, n=1)
            if today >= t1:
                price = _fetch_close_on(row["ticker"], t1)
                if not pd.isna(price):
                    out.at[idx, "entry_date"] = str(t1.date())
                    out.at[idx, "entry_price"] = price
                    out.at[idx, "status"] = "in_flight"
                    n_in_flight += 1
                    logger.info(
                        "trade %d %s entered in_flight at %s price=%.4f",
                        row["trade_id"], row["ticker"], t1.date(), price,
                    )

        elif status == "in_flight" and (
            pd.isna(row["exit_price"]) or row["exit_price"] == ""
        ):
            t60 = _next_trading_day(ev_date, n=holding_window)
            if today >= t60:
                price = _fetch_close_on(row["ticker"], t60)
                if not pd.isna(price):
                    entry = float(row["entry_price"])
                    sign = int(row["sue_sign"])
                    raw_ret = (price - entry) / entry if entry > 0 else float("nan")
                    gross = raw_ret * sign  # apply direction
                    net = gross - cost_bps / 10_000.0
                    out.at[idx, "exit_date"] = str(t60.date())
                    out.at[idx, "exit_price"] = price
                    out.at[idx, "gross_return"] = gross
                    out.at[idx, "cost_bps"] = cost_bps
                    out.at[idx, "net_return"] = net
                    out.at[idx, "status"] = "closed"
                    n_closed += 1
                    logger.info(
                        "trade %d %s closed at %s price=%.4f gross=%+.4f net=%+.4f",
                        row["trade_id"], row["ticker"], t60.date(),
                        price, gross, net,
                    )

    return out, n_in_flight, n_closed


def paper_tick(
    sector: SectorConfig,
    csv_path: Path,
    today: pd.Timestamp | None = None,
    sue_threshold: float = 1.0,
    earnings_cache_dir: Path | None = None,
    min_event_date: pd.Timestamp | None = None,
) -> TickSummary:
    """Run one paper-trading tick: detect new candidates + transition states.

    Args:
        sector: validated SectorConfig.
        csv_path: paper-trading CSV path; created if missing.
        today: optional override timestamp (default: pd.Timestamp.today()).
        sue_threshold: |SUE| threshold for candidate detection.
        earnings_cache_dir: optional cache dir for fetch_earnings.
        min_event_date: only consider candidates announced on/after this
            date. Defaults to ``today`` minus 7 days (one-week lookback)
            when not provided, to prevent back-flooding with historical
            earnings.

    Returns:
        TickSummary dict with counts and cumulative net P&L.
    """
    if not csv_path.is_file():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        empty_paper_csv(csv_path)

    existing = load_paper_csv(csv_path)
    today_ts = pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()
    if min_event_date is None:
        min_event_date = today_ts - pd.Timedelta(days=7)

    new = detect_new_candidates(
        sector,
        existing,
        sue_threshold=sue_threshold,
        earnings_cache_dir=earnings_cache_dir,
        min_event_date=min_event_date,
    )
    if not new.empty:
        existing = pd.concat([existing, new], ignore_index=True)
        logger.info("appended %d new candidate(s)", len(new))

    existing, n_in_flight, n_closed = transition_rows(existing, sector, today_ts)

    existing.to_csv(csv_path, index=False)

    by_status = (
        existing["status"].value_counts(dropna=False).to_dict() if not existing.empty else {}
    )
    cumulative = (
        float(existing["net_return"].dropna().sum()) if not existing.empty else 0.0
    )

    return TickSummary(
        new_candidates=len(new),
        transitioned_in_flight=n_in_flight,
        transitioned_closed=n_closed,
        by_status={str(k): int(v) for k, v in by_status.items()},
        cumulative_net_return=cumulative,
    )


# ---------- W5 UX helpers: drawdown + sizing + today actions ----------


# Prereg §10.2-10.4 thresholds.
DRAWDOWN_REVIEW_THRESHOLD: float = -0.30
DRAWDOWN_HARD_STOP_THRESHOLD: float = -0.50


def compute_drawdown_status(rows: pd.DataFrame, cap_eur: float) -> dict:
    """Drawdown status against prereg §10 cap.

    Args:
        rows: paper-trade DataFrame (`PAPER_TRADE_COLUMNS`).
        cap_eur: binding capital cap (prereg §10.1 = €5000 for AI Infra
            live). For paper trading set this to the notional cap that
            the W5 ledger simulates.

    Returns:
        Dict with:
            - current_pnl_pct: realised cumulative net return on closed
              trades, as a fraction of cap_eur
            - peak_pnl_pct: running peak of current_pnl_pct over the
              sequence of closed trades (monotone non-decreasing)
            - drawdown_pct: current - peak (≤ 0)
            - trigger_level: "safe" | "review" | "hard_stop"

    The "trigger_level" follows prereg §10.2-10.4:
        - safe: drawdown_pct > -0.30
        - review: -0.50 < drawdown_pct ≤ -0.30
        - hard_stop: drawdown_pct ≤ -0.50
    """
    closed = (
        rows[rows["status"] == "closed"].copy()
        if not rows.empty and "status" in rows.columns
        else pd.DataFrame()
    )
    if closed.empty or cap_eur <= 0:
        return {
            "current_pnl_pct": 0.0,
            "peak_pnl_pct": 0.0,
            "drawdown_pct": 0.0,
            "trigger_level": "safe",
        }

    closed = closed.sort_values("exit_date")
    # Each trade's net_return is on a €1000 notional position by convention
    # in the paper ledger. Translate to cap fraction: position_eur / cap_eur.
    position_eur = 1000.0
    weight = position_eur / cap_eur
    cumulative = closed["net_return"].fillna(0.0).cumsum() * weight
    peak = cumulative.cummax()

    current_pnl = float(cumulative.iloc[-1])
    peak_pnl = float(peak.iloc[-1])
    # Drawdown per prereg §10.2: vs starting capital (€5k → €3.5k = -30%),
    # NOT peak-to-trough. The trigger is on the cumulative net P&L
    # against the starting cap, expressed as a fraction. Peak is kept as
    # an informational field.
    drawdown = current_pnl

    if drawdown <= DRAWDOWN_HARD_STOP_THRESHOLD:
        trigger = "hard_stop"
    elif drawdown <= DRAWDOWN_REVIEW_THRESHOLD:
        trigger = "review"
    else:
        trigger = "safe"

    return {
        "current_pnl_pct": current_pnl,
        "peak_pnl_pct": peak_pnl,
        "drawdown_pct": drawdown,
        "trigger_level": trigger,
    }


def compute_sizing(
    rows: pd.DataFrame,
    cap_eur: float,
    max_per_trade_eur: float = 1000.0,
) -> dict:
    """Capital deployment + slot summary.

    Args:
        rows: paper-trade DataFrame.
        cap_eur: binding capital cap.
        max_per_trade_eur: max position size per trade (prereg §8.1 = 20%
            of cap = €1000 for €5k cap).

    Returns:
        Dict with:
            - cap_deployed_eur: max_per_trade_eur * count(in_flight)
            - cap_available_eur: cap_eur - cap_deployed_eur (≥ 0)
            - slots_open: count(in_flight)
            - slots_max: floor(cap_eur / max_per_trade_eur)
            - recommended_position_eur: min(max_per_trade_eur,
                cap_available_eur) — clamped to 0 when no slots.
    """
    if cap_eur <= 0 or max_per_trade_eur <= 0:
        raise ValueError("cap_eur and max_per_trade_eur must be > 0")

    slots_max = int(cap_eur // max_per_trade_eur)

    if rows.empty or "status" not in rows.columns:
        slots_open = 0
    else:
        slots_open = int((rows["status"] == "in_flight").sum())

    cap_deployed = float(slots_open * max_per_trade_eur)
    cap_available = max(0.0, cap_eur - cap_deployed)
    recommended = min(max_per_trade_eur, cap_available) if slots_open < slots_max else 0.0

    return {
        "cap_deployed_eur": cap_deployed,
        "cap_available_eur": cap_available,
        "slots_open": slots_open,
        "slots_max": slots_max,
        "recommended_position_eur": recommended,
    }


def compute_today_actions(
    rows: pd.DataFrame,
    today: pd.Timestamp,
    holding_window: int = 60,
) -> dict:
    """Compute the "today actions" for paper/live execution.

    Args:
        rows: paper-trade DataFrame.
        today: today timestamp (normalised to date).
        holding_window: T+N exit window (cat A T+60 default).

    Returns:
        Dict with:
            - open: list of dicts {trade_id, ticker, sue, sue_sign, event_date}
              for rows in status=approved with T+1 == today.
            - close: list of dicts {trade_id, ticker, entry_date,
              entry_price, days_held} for rows in status=in_flight with
              T+60 == today.

    The intent: a human reads this list and places the corresponding
    manual orders on the broker (Fineco app).
    """
    today_ts = pd.Timestamp(today).normalize()
    open_actions: list[dict] = []
    close_actions: list[dict] = []

    if rows is None or rows.empty:
        return {"open": [], "close": []}

    for _, row in rows.iterrows():
        if pd.isna(row.get("event_date")):
            continue
        ev = pd.Timestamp(row["event_date"])
        status = row.get("status", "")

        if status == "approved":
            try:
                t1 = _next_trading_day(ev, n=1)
            except ValueError:
                continue
            if t1.normalize() == today_ts:
                open_actions.append(
                    {
                        "trade_id": int(row["trade_id"]),
                        "ticker": str(row["ticker"]),
                        "event_date": str(ev.date()),
                        "sue": float(row.get("sue", float("nan"))),
                        "sue_sign": int(row.get("sue_sign", 0)),
                    }
                )

        elif status == "in_flight":
            try:
                t60 = _next_trading_day(ev, n=holding_window)
            except ValueError:
                continue
            if t60.normalize() == today_ts:
                entry_date_raw = row.get("entry_date", "")
                if entry_date_raw and not pd.isna(entry_date_raw):
                    entry_ts = pd.Timestamp(entry_date_raw)
                    days_held = (today_ts - entry_ts).days
                else:
                    days_held = -1
                close_actions.append(
                    {
                        "trade_id": int(row["trade_id"]),
                        "ticker": str(row["ticker"]),
                        "entry_date": str(entry_date_raw) if entry_date_raw else "",
                        "entry_price": (
                            float(row["entry_price"])
                            if pd.notna(row.get("entry_price"))
                            else float("nan")
                        ),
                        "days_held": days_held,
                    }
                )

    return {"open": open_actions, "close": close_actions}
