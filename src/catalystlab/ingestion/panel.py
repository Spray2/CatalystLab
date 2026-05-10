"""Layer 2 — panel dataset builder.

Joins prices (long-format from `prices.fetch_prices`) with curated event
logs (`data/events/<sector>/`) into the final per-(ticker, date) panel.

Schema (locked):
    [date, ticker, return, adj_close, ar_vs_xlk_proxy, event_type, event_magnitude]

Notes on scope (W1):
    * `ar_vs_xlk_proxy = r_i - r_xlk` is a *non-beta-adjusted* difference;
      the beta-adjusted AR per prereg §6.1 is computed in Layer 3.
    * Overlapping events on the same (ticker, date) — prereg §12 question 1
      — are resolved here by category priority A < B < C < D < E (first
      match wins). Layer 3 may revisit and store all overlapping events
      separately if needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from catalystlab.config.schemas import SectorConfig

logger = logging.getLogger(__name__)

PANEL_COLUMNS: list[str] = [
    "date",
    "ticker",
    "return",
    "adj_close",
    "ar_vs_xlk_proxy",
    "event_type",
    "event_magnitude",
]

CATEGORY_PRIORITY: list[str] = ["A", "B", "C", "D", "E"]

_EVENT_FILE_NAMES: dict[str, str] = {
    "A": "earnings.csv",
    "B": "ppa.csv",
    "C": "orders.csv",
    "D": "shocks.csv",
    "E": "analyst.csv",
}


def _empty_panel() -> pd.DataFrame:
    return pd.DataFrame(columns=PANEL_COLUMNS)


def load_event_logs(events_dir: Path) -> dict[str, pd.DataFrame]:
    """Read all five event CSVs from `events_dir` keyed by category letter.

    Missing files are logged and skipped (returned dict will lack that key).
    Empty CSVs are returned as empty DataFrames with the expected columns.
    """
    out: dict[str, pd.DataFrame] = {}
    for cat, fname in _EVENT_FILE_NAMES.items():
        path = events_dir / fname
        if not path.is_file():
            logger.warning("event log missing: %s (category %s)", path, cat)
            continue
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        out[cat] = df
    return out


def _normalize_event_to_panel(
    ev_df: pd.DataFrame,
    category: str,
    universe: set[str],
) -> pd.DataFrame:
    """Reduce a category-specific event frame to ``[ticker, date,
    event_type, event_magnitude]``.

    Category D (sector_shock) has no ``ticker`` column and is broadcast to
    every ticker in the universe on the event date.
    """
    cols = ["ticker", "date", "event_type", "event_magnitude"]
    if ev_df.empty:
        return pd.DataFrame(columns=cols)

    df = ev_df.copy()

    if category == "A":
        if "ticker" not in df.columns or "announcement_date" not in df.columns:
            return pd.DataFrame(columns=cols)
        df = df[df["ticker"].isin(universe)]
        df["date"] = pd.to_datetime(df["announcement_date"], errors="coerce")
        df = df.dropna(subset=["date"])
        magnitude_sue = pd.to_numeric(df.get("sue"), errors="coerce")
        magnitude_sign = pd.to_numeric(df.get("surprise_sign"), errors="coerce")
        df["event_type"] = "A"
        df["event_magnitude"] = magnitude_sue.fillna(magnitude_sign)
        return df[cols]

    if category == "B":
        if "ticker" not in df.columns or "announce_date" not in df.columns:
            return pd.DataFrame(columns=cols)
        df = df[df["ticker"].isin(universe)]
        df["date"] = pd.to_datetime(df["announce_date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["event_type"] = "B"
        deal_mw = pd.to_numeric(df.get("deal_mw"), errors="coerce")
        df["event_magnitude"] = deal_mw.fillna(1.0)
        return df[cols]

    if category == "C":
        if "ticker" not in df.columns or "announce_date" not in df.columns:
            return pd.DataFrame(columns=cols)
        df = df[df["ticker"].isin(universe)]
        df["date"] = pd.to_datetime(df["announce_date"], errors="coerce")
        df = df.dropna(subset=["date"])
        deal_value = pd.to_numeric(df.get("deal_value_usd"), errors="coerce")
        backlog = pd.to_numeric(df.get("backlog_change_pct"), errors="coerce")
        df["event_type"] = "C"
        df["event_magnitude"] = deal_value.fillna(backlog)
        return df[cols]

    if category == "D":
        if "event_date" not in df.columns:
            return pd.DataFrame(columns=cols)
        df["date"] = pd.to_datetime(df["event_date"], errors="coerce")
        df = df.dropna(subset=["date"])
        magnitude = pd.to_numeric(df.get("xlk_t1_return"), errors="coerce")
        broadcast: list[dict[str, object]] = []
        for date_val, mag in zip(df["date"], magnitude, strict=False):
            for ticker in sorted(universe):
                broadcast.append(
                    {
                        "ticker": ticker,
                        "date": date_val,
                        "event_type": "D",
                        "event_magnitude": mag,
                    }
                )
        return pd.DataFrame(broadcast, columns=cols)

    if category == "E":
        if "ticker" not in df.columns or "event_date" not in df.columns:
            return pd.DataFrame(columns=cols)
        df = df[df["ticker"].isin(universe)]
        df["date"] = pd.to_datetime(df["event_date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["event_type"] = "E"
        df["event_magnitude"] = pd.to_numeric(df.get("target_change_pct"), errors="coerce")
        return df[cols]

    raise ValueError(f"unknown event category: {category}")


def build_panel(
    sector: SectorConfig,
    prices: pd.DataFrame,
    events: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Assemble the (ticker, date) panel for a sector run.

    Args:
        sector: validated `SectorConfig`.
        prices: long-format prices DataFrame
            ``[date, ticker, open, high, low, close, adj_close, volume]``,
            covering the universe AND ``benchmarks.primary``.
        events: dict ``{category_letter: DataFrame}`` from
            `load_event_logs`. Missing or empty categories are tolerated.

    Returns:
        Panel DataFrame with columns ``PANEL_COLUMNS``, sorted by
        ``(ticker, date)``.
    """
    if prices.empty:
        return _empty_panel()

    universe = {t.ticker for t in sector.universe}
    benchmark = sector.benchmarks.primary

    px = prices.copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"]).reset_index(drop=True)
    px["return"] = px.groupby("ticker")["adj_close"].pct_change()

    bench = (
        px[px["ticker"] == benchmark][["date", "return"]]
        .rename(columns={"return": "_bench_return"})
        .reset_index(drop=True)
    )

    universe_px = px[px["ticker"].isin(universe)].copy()
    universe_px = universe_px.merge(bench, on="date", how="left")
    universe_px["ar_vs_xlk_proxy"] = universe_px["return"] - universe_px["_bench_return"]

    panel = universe_px[
        ["date", "ticker", "return", "adj_close", "ar_vs_xlk_proxy"]
    ].copy()

    event_rows: list[pd.DataFrame] = []
    for cat in CATEGORY_PRIORITY:
        ev = events.get(cat)
        if ev is None:
            continue
        norm = _normalize_event_to_panel(ev, cat, universe)
        if not norm.empty:
            event_rows.append(norm)

    if event_rows:
        all_events = pd.concat(event_rows, ignore_index=True)
        all_events["date"] = pd.to_datetime(all_events["date"])
        # Priority A→E first match wins on (ticker, date) overlap.
        all_events = all_events.drop_duplicates(subset=["ticker", "date"], keep="first")
        panel = panel.merge(all_events, on=["ticker", "date"], how="left")
    else:
        panel["event_type"] = pd.NA
        panel["event_magnitude"] = pd.NA

    return panel[PANEL_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)
