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

from catalystlab.config.loader import compute_manifest, load_sector
from catalystlab.ingestion.earnings import fetch_earnings
from catalystlab.ingestion.panel import build_panel, load_event_logs
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

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
