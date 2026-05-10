"""CatalystLab CLI — sector pipeline orchestrator.

Subcommands:
    build-panel --sector <name>
        Loads sector YAML, fetches prices and earnings, regenerates the
        category-A event log (earnings.csv), reads the manually curated
        event logs (B-E), assembles the panel, writes parquet output and
        a run manifest.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from catalystlab.config.loader import compute_manifest, load_sector
from catalystlab.eventstudy.abnormal_returns import compute_event_metrics
from catalystlab.eventstudy.aggregation import aggregate_event_metrics
from catalystlab.eventstudy.ic import compute_ic
from catalystlab.ingestion.costs import compute_cost_bps
from catalystlab.ingestion.earnings import fetch_earnings
from catalystlab.ingestion.panel import (
    build_panel,
    enumerate_all_events,
    load_event_logs,
)
from catalystlab.ingestion.prices import (
    detect_gaps,
    expected_trading_days,
    fetch_prices,
)

logger = logging.getLogger("catalystlab")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def cmd_build_panel(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    sectors_dir = repo_root / "sectors"
    cache_root = repo_root / "data" / "raw"
    events_dir = repo_root / "data" / "events" / args.sector
    out_dir = repo_root / "data" / "processed"
    manifest_dir = repo_root / "data" / "manifests"

    logger.info("loading sector config: %s", args.sector)
    sector_cfg, sector_sha = load_sector(args.sector, sectors_dir=sectors_dir)
    universe_tickers = [t.ticker for t in sector_cfg.universe]
    bench_tickers = [sector_cfg.benchmarks.primary, sector_cfg.benchmarks.secondary]
    fetch_tickers = universe_tickers + bench_tickers

    logger.info(
        "fetching prices: %d tickers, %s → %s",
        len(fetch_tickers),
        sector_cfg.period.start,
        sector_cfg.period.end,
    )
    prices = fetch_prices(
        fetch_tickers,
        sector_cfg.period.start,
        sector_cfg.period.end,
        cache_dir=cache_root / "prices" if args.cache else None,
        sleep_between=args.sleep,
        use_cache=args.cache,
    )

    if prices.empty:
        logger.error("no prices fetched — aborting")
        return 2

    expected = expected_trading_days(sector_cfg.period.start, sector_cfg.period.end)
    gaps = detect_gaps(prices, expected)
    if gaps:
        logger.warning("gap detection: %d tickers with missing days", len(gaps))
        for ticker, missing in gaps.items():
            logger.warning("  %s: %d days missing", ticker, len(missing))

    logger.info("fetching earnings (category A) for %d tickers", len(universe_tickers))
    earnings = fetch_earnings(
        universe_tickers,
        cache_dir=cache_root / "earnings" if args.cache else None,
        sleep_between=args.sleep,
        use_cache=args.cache,
    )
    events_dir.mkdir(parents=True, exist_ok=True)
    earnings_csv_path = events_dir / "earnings.csv"
    earnings.to_csv(earnings_csv_path, index=False)
    logger.info("wrote %d earnings rows to %s", len(earnings), earnings_csv_path)

    logger.info("loading event logs from %s", events_dir)
    events = load_event_logs(events_dir)

    logger.info("building panel")
    panel = build_panel(sector_cfg, prices, events)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"panel_{args.sector}.parquet"
    panel.to_parquet(out_path, index=False)
    logger.info("panel written: %s (%d rows)", out_path, len(panel))

    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"{timestamp}_{args.sector}.json"
    manifest = compute_manifest(
        args.sector,
        sector_sha,
        runtime_params={
            "panel_rows": len(panel),
            "panel_path": str(out_path.relative_to(repo_root)),
            "tickers_universe": universe_tickers,
            "tickers_benchmark": bench_tickers,
            "prices_rows": len(prices),
            "earnings_rows": len(earnings),
            "events_loaded": {k: len(v) for k, v in events.items()},
            "gap_tickers": list(gaps.keys()),
        },
        repo_dir=repo_root,
    )
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    logger.info("manifest written: %s", manifest_path)

    sys.stdout.write(f"panel:    {out_path}\n")
    sys.stdout.write(f"manifest: {manifest_path}\n")
    sys.stdout.write(f"rows:     {len(panel)}\n")
    return 0


def _fill_d_magnitudes(events: pd.DataFrame, bench_returns: pd.Series) -> pd.DataFrame:
    """Populate xlk_t1_return for cat D events whose magnitude is NaN.

    Per prereg §3.4 cat D magnitude is the XLK T+1 return. The CSV may
    leave it blank for runtime computation. Returns a new DataFrame.
    """
    if events.empty:
        return events
    out = events.copy()
    bench_idx = pd.DatetimeIndex(bench_returns.index)
    for idx, row in out.iterrows():
        if row["event_type"] != "D" or not pd.isna(row["event_magnitude"]):
            continue
        event_ts = pd.Timestamp(row["date"])
        after = bench_idx[bench_idx > event_ts]
        if len(after) == 0:
            continue
        out.at[idx, "event_magnitude"] = float(bench_returns.loc[after[0]])
    return out


def cmd_event_study(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    sectors_dir = repo_root / "sectors"
    events_dir = repo_root / "data" / "events" / args.sector
    panel_path = repo_root / "data" / "processed" / f"panel_{args.sector}.parquet"
    out_dir = repo_root / "data" / "processed"
    manifest_dir = repo_root / "data" / "manifests"

    if not panel_path.is_file():
        logger.error("panel parquet not found: %s — run `build-panel` first", panel_path)
        return 2

    logger.info("loading sector config: %s", args.sector)
    sector_cfg, sector_sha = load_sector(args.sector, sectors_dir=sectors_dir)

    logger.info("loading panel: %s", panel_path)
    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])

    benchmark = sector_cfg.benchmarks.primary
    if benchmark in panel["ticker"].unique():
        bench_panel = panel[panel["ticker"] == benchmark]
    else:
        bench_panel = pd.DataFrame()

    if bench_panel.empty:
        logger.info(
            "benchmark %s not in panel — recomputing returns from raw cache",
            benchmark,
        )
        bench_cache = repo_root / "data" / "raw" / "prices" / f"{benchmark}.parquet"
        if not bench_cache.is_file():
            logger.error(
                "benchmark cache not found: %s — re-run build-panel without --no-cache",
                bench_cache,
            )
            return 3
        bench_raw = pd.read_parquet(bench_cache).sort_values("date")
        bench_returns = bench_raw.set_index("date")["adj_close"].pct_change().dropna()
    else:
        bench_returns = (
            bench_panel.set_index("date")["return"].dropna().sort_index()
        )

    logger.info("loading event logs from %s", events_dir)
    event_logs = load_event_logs(events_dir)

    logger.info("enumerating events without priority dedup")
    events = enumerate_all_events(sector_cfg, event_logs)
    events = _fill_d_magnitudes(events, bench_returns)
    logger.info("events to process: %d (across %d categories)", len(events), events["event_type"].nunique() if not events.empty else 0)

    logger.info("computing event metrics (beta + AR/CAR)")
    metrics = compute_event_metrics(
        panel,
        bench_returns,
        holding_windows=sector_cfg.holding_windows,
        beta_window_days=sector_cfg.benchmarks.beta_window_days,
        beta_exclusion_days=sector_cfg.benchmarks.beta_exclusion_window_days,
        events_override=events,
    )

    cost_bps = compute_cost_bps(sector_cfg.costs)
    logger.info("aggregating per (event_type, holding_window) — cost: %.2f bps", cost_bps)
    agg = aggregate_event_metrics(metrics, cost_bps_round_trip=cost_bps)

    logger.info("computing Spearman IC + uncorrected p-values")
    ic = compute_ic(metrics)

    summary = agg.merge(
        ic[["event_type", "holding_window", "n_pairs", "ic", "ic_pvalue"]],
        on=["event_type", "holding_window"],
        how="left",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / f"event_metrics_{args.sector}.parquet"
    metrics.to_parquet(metrics_path, index=False)
    summary_path = out_dir / f"event_summary_{args.sector}.parquet"
    summary.to_parquet(summary_path, index=False)
    logger.info("metrics written: %s (%d rows)", metrics_path, len(metrics))
    logger.info("summary written: %s (%d rows)", summary_path, len(summary))

    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = manifest_dir / f"{timestamp}_{args.sector}_eventstudy.json"
    manifest = compute_manifest(
        args.sector,
        sector_sha,
        runtime_params={
            "stage": "event-study",
            "panel_path": str(panel_path.relative_to(repo_root)),
            "metrics_path": str(metrics_path.relative_to(repo_root)),
            "summary_path": str(summary_path.relative_to(repo_root)),
            "n_events": len(events),
            "n_metric_rows": len(metrics),
            "cost_bps_round_trip": cost_bps,
            "holding_windows": list(sector_cfg.holding_windows),
        },
        repo_dir=repo_root,
    )
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    logger.info("manifest written: %s", manifest_path)

    sys.stdout.write(f"metrics:  {metrics_path}\n")
    sys.stdout.write(f"summary:  {summary_path}\n")
    sys.stdout.write(f"manifest: {manifest_path}\n")
    sys.stdout.write(f"events:   {len(events)}\n")
    sys.stdout.write(f"rows:     {len(metrics)}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="catalystlab",
        description="CatalystLab — event-driven research pipeline.",
    )
    parser.add_argument("--verbose", action="store_true", help="enable DEBUG logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bp = sub.add_parser("build-panel", help="assemble panel parquet for a sector")
    bp.add_argument("--sector", required=True, help="sector name (matches sectors/<name>.yaml)")
    bp.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="bypass parquet cache (force refetch)",
    )
    bp.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="seconds between yfinance calls (rate-limit hygiene)",
    )
    bp.set_defaults(cache=True, func=cmd_build_panel)

    es = sub.add_parser("event-study", help="compute beta/AR/CAR/IC from panel + event logs")
    es.add_argument("--sector", required=True, help="sector name (matches sectors/<name>.yaml)")
    es.set_defaults(func=cmd_event_study)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
