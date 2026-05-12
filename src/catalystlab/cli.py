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
from catalystlab.paper_trading import (
    compute_drawdown_status,
    compute_sizing,
    compute_today_actions,
    load_paper_csv,
    paper_tick,
)
from catalystlab.reporting.dashboard import render_dashboard
from catalystlab.reporting.decision import annotate_decision_flags, decide
from catalystlab.reporting.html_report import render_report
from catalystlab.stats.bh_correction import apply_bh_per_holding_window
from catalystlab.stats.bootstrap import apply_bootstrap_to_summary
from catalystlab.stats.stability import compute_stability
from catalystlab.stats.temporal_cv import DEFAULT_SPLIT_DATE, compute_temporal_decay

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


def cmd_decide(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    sectors_dir = repo_root / "sectors"
    metrics_path = (
        repo_root / "data" / "processed" / f"event_metrics_{args.sector}.parquet"
    )
    summary_path = (
        repo_root / "data" / "processed" / f"event_summary_{args.sector}.parquet"
    )
    out_dir = repo_root / "data" / "processed"
    manifest_dir = repo_root / "data" / "manifests"

    if not metrics_path.is_file() or not summary_path.is_file():
        logger.error(
            "event-study artifacts missing (%s / %s) — run `event-study` first",
            metrics_path,
            summary_path,
        )
        return 2

    logger.info("loading sector config: %s", args.sector)
    sector_cfg, sector_sha = load_sector(args.sector, sectors_dir=sectors_dir)

    logger.info("loading event metrics + summary parquet")
    metrics = pd.read_parquet(metrics_path)
    summary = pd.read_parquet(summary_path)

    logger.info("applying BH-FDR correction per holding window (n_tests=5)")
    summary = apply_bh_per_holding_window(
        summary,
        alpha=sector_cfg.stats.bh_alpha,
        pvalue_col="ic_pvalue",
        n_tests_per_window=5,
    )

    logger.info(
        "computing bootstrap CI (n_resample=%d, seed=%d)",
        sector_cfg.stats.bootstrap_n,
        sector_cfg.random_seed,
    )
    summary = apply_bootstrap_to_summary(
        metrics,
        summary,
        n_resample=sector_cfg.stats.bootstrap_n,
        ci_level=sector_cfg.stats.bootstrap_ci,
        seed=sector_cfg.random_seed,
    )

    logger.info("computing temporal decay (split %s)", DEFAULT_SPLIT_DATE.date())
    temporal = compute_temporal_decay(metrics)

    logger.info("computing stability (top-5 |CAR| removal)")
    stability = compute_stability(metrics, k_top=5)

    summary_annotated = annotate_decision_flags(
        summary,
        ic_threshold=sector_cfg.stats.ic_threshold,
        hit_rate_threshold=sector_cfg.stats.hit_rate_threshold,
        bh_alpha=sector_cfg.stats.bh_alpha,
    )

    decision_obj = decide(
        summary_annotated,
        ic_threshold=sector_cfg.stats.ic_threshold,
        hit_rate_threshold=sector_cfg.stats.hit_rate_threshold,
        bh_alpha=sector_cfg.stats.bh_alpha,
        sector_display_name=sector_cfg.display_name,
    )
    logger.info("decision: %s (%s)", decision_obj["verdict"].upper(), decision_obj["rationale"])

    out_dir.mkdir(parents=True, exist_ok=True)
    decision_path = out_dir / f"decision_{args.sector}.json"
    with decision_path.open("w", encoding="utf-8") as f:
        json.dump(decision_obj, f, indent=2, default=str)
    logger.info("decision artifact: %s", decision_path)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    cost_bps = compute_cost_bps(sector_cfg.costs)
    html = render_report(
        sector=sector_cfg.sector,
        display_name=sector_cfg.display_name,
        prereg_version=sector_cfg.prereg_version,
        prereg_lockfile_date=sector_cfg.prereg_lockfile_date.isoformat(),
        period_start=sector_cfg.period.start.isoformat(),
        period_end=sector_cfg.period.end.isoformat(),
        universe=[t.ticker for t in sector_cfg.universe],
        benchmark_primary=sector_cfg.benchmarks.primary,
        benchmark_secondary=sector_cfg.benchmarks.secondary,
        holding_windows=sector_cfg.holding_windows,
        cost_bps_round_trip=cost_bps,
        cost_position_eur=sector_cfg.costs.default_position_size_eur,
        sector_yaml_sha256=sector_sha,
        git_commit=None,  # filled by manifest below
        timestamp_utc=datetime.now(UTC).isoformat(),
        decision=decision_obj,
        summary_full=summary_annotated,
        temporal=temporal,
        stability=stability,
        temporal_split_date=str(DEFAULT_SPLIT_DATE.date()),
        stability_k=5,
    )
    report_path = out_dir / f"report_{args.sector}.html"
    report_path.write_text(html, encoding="utf-8")
    logger.info("report HTML: %s", report_path)

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{timestamp}_{args.sector}_decide.json"
    manifest = compute_manifest(
        args.sector,
        sector_sha,
        runtime_params={
            "stage": "decide",
            "verdict": decision_obj["verdict"],
            "n_winning": decision_obj["n_winning"],
            "n_ambiguous": decision_obj["n_ambiguous"],
            "decision_path": str(decision_path.relative_to(repo_root)),
            "report_path": str(report_path.relative_to(repo_root)),
            "metrics_path": str(metrics_path.relative_to(repo_root)),
            "summary_path": str(summary_path.relative_to(repo_root)),
            "thresholds": decision_obj["thresholds"],
            "bootstrap_n": sector_cfg.stats.bootstrap_n,
            "bootstrap_seed": sector_cfg.random_seed,
        },
        repo_dir=repo_root,
    )
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    logger.info("manifest written: %s", manifest_path)

    sys.stdout.write(f"verdict:  {decision_obj['verdict'].upper()}\n")
    sys.stdout.write(f"decision: {decision_path}\n")
    sys.stdout.write(f"report:   {report_path}\n")
    sys.stdout.write(f"manifest: {manifest_path}\n")
    sys.stdout.write(f"winning:  {decision_obj['n_winning']}\n")
    sys.stdout.write(f"ambig:    {decision_obj['n_ambiguous']}\n")
    return 0


def _default_paper_csv_path(repo_root: Path, sector: str) -> Path:
    del sector  # path doesn't depend on sector currently; reserved arg
    month_tag = datetime.now(UTC).strftime("%Y-%m")
    return repo_root / "paper_trading" / f"A_T+60_{month_tag}.csv"


def _upcoming_earnings(
    sector_cfg, today: pd.Timestamp, horizon_days: int = 14
) -> list[dict]:
    """Return upcoming earnings in the next horizon_days for the universe.

    Tolerates yfinance failures (network/scrape rate limit) and returns
    whatever was retrievable.
    """
    out: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        return out
    horizon = today + pd.Timedelta(days=horizon_days)
    for t in sector_cfg.universe:
        ticker = t.ticker
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=8)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        idx_naive = df.index.tz_localize(None) if df.index.tz is not None else df.index
        mask = (idx_naive >= today) & (idx_naive <= horizon)
        for ev_date, row in df[mask].iterrows():
            est = row.get("EPS Estimate", None)
            out.append(
                {
                    "ticker": ticker,
                    "date": pd.Timestamp(ev_date).date().isoformat(),
                    "estimate_eps": float(est) if pd.notna(est) else None,
                }
            )
    out.sort(key=lambda d: d["date"])
    return out


def _emit_dashboard(
    sector_cfg,
    csv_path: Path,
    out_path: Path,
    today: pd.Timestamp,
    cap_eur: float = 5000.0,
    max_per_trade_eur: float = 1000.0,
) -> None:
    """Render dashboard.html from paper-trading CSV + sector config."""
    rows = load_paper_csv(csv_path)
    drawdown = compute_drawdown_status(rows, cap_eur=cap_eur)
    sizing = compute_sizing(rows, cap_eur=cap_eur, max_per_trade_eur=max_per_trade_eur)
    today_actions = compute_today_actions(rows, today=today)
    upcoming = _upcoming_earnings(sector_cfg, today=today)

    html = render_dashboard(
        sector=sector_cfg.sector,
        display_name=sector_cfg.display_name,
        combination="A T+60 (PEAD)",
        cap_eur=cap_eur,
        max_per_trade_eur=max_per_trade_eur,
        timestamp_utc=datetime.now(UTC).isoformat(),
        today=today,
        rows=rows,
        drawdown=drawdown,
        sizing=sizing,
        today_actions=today_actions,
        upcoming_earnings=upcoming,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def cmd_today(args: argparse.Namespace) -> int:
    """Print today's actions (open/close) + status snapshot."""
    repo_root = Path.cwd()
    sectors_dir = repo_root / "sectors"

    sector_cfg, _ = load_sector(args.sector, sectors_dir=sectors_dir)
    csv_path = (
        Path(args.csv)
        if args.csv
        else _default_paper_csv_path(repo_root, args.sector)
    )
    if not csv_path.is_file():
        sys.stdout.write(f"Paper trading CSV not found: {csv_path}\n")
        sys.stdout.write("Run `catalystlab paper-tick` first.\n")
        return 2

    today_ts = (
        pd.Timestamp(args.today) if args.today else pd.Timestamp.today().normalize()
    )
    cap_eur = args.cap_eur
    max_per_trade_eur = args.max_per_trade_eur

    rows = load_paper_csv(csv_path)
    drawdown = compute_drawdown_status(rows, cap_eur=cap_eur)
    sizing = compute_sizing(rows, cap_eur=cap_eur, max_per_trade_eur=max_per_trade_eur)
    today_actions = compute_today_actions(rows, today=today_ts)

    n_open_actions = len(today_actions["open"]) + len(today_actions["close"])
    in_flight_count = (
        int((rows["status"] == "in_flight").sum()) if not rows.empty else 0
    )

    sys.stdout.write(f"Date: {today_ts.date()}\n")
    sys.stdout.write(
        f"Cap deployed: EUR{sizing['cap_deployed_eur']:.0f} / EUR{cap_eur:.0f} "
        f"({sizing['cap_deployed_eur']/cap_eur*100:.0f}%)  |  "
        f"Slots: {sizing['slots_open']} / {sizing['slots_max']} open\n"
    )
    sys.stdout.write(
        f"Drawdown: {drawdown['drawdown_pct']*100:+.2f}% ({drawdown['trigger_level']})"
        f"  -- review at -30%, hard stop -50%\n\n"
    )

    sys.stdout.write(f"TODAY ACTIONS ({n_open_actions})\n")
    if n_open_actions == 0:
        sys.stdout.write("  (none)\n")
    else:
        for o in today_actions["open"]:
            direction = (
                "long" if o["sue_sign"] > 0
                else "short" if o["sue_sign"] < 0
                else "flat"
            )
            sys.stdout.write(
                f"  OPEN  {o['ticker']:<5} {direction:<5} "
                f"EUR{sizing['recommended_position_eur']:.0f}  "
                f"(SUE={o['sue']:+.2f} from {o['event_date']} earnings)\n"
            )
        for c in today_actions["close"]:
            price_s = (
                f"${c['entry_price']:.2f}"
                if c["entry_price"] == c["entry_price"]
                else "--"
            )
            sys.stdout.write(
                f"  CLOSE {c['ticker']:<5} exit  -- (entered {c['entry_date']} @ "
                f"{price_s}, T+60 exit today)\n"
            )
    sys.stdout.write("\n")

    sys.stdout.write(f"OPEN POSITIONS ({in_flight_count})\n")
    if in_flight_count == 0:
        sys.stdout.write("  (none)\n")
    else:
        in_flight = rows[rows["status"] == "in_flight"]
        for _, r in in_flight.iterrows():
            entry_ts = pd.Timestamp(r["entry_date"]) if r["entry_date"] else None
            days_held = (today_ts - entry_ts).days if entry_ts is not None else 0
            direction = (
                "long" if int(r["sue_sign"]) > 0
                else "short" if int(r["sue_sign"]) < 0
                else "flat"
            )
            sys.stdout.write(
                f"  {r['ticker']:<5} {direction:<5}  day {days_held}/60\n"
            )

    upcoming = _upcoming_earnings(sector_cfg, today=today_ts, horizon_days=14)
    sys.stdout.write(f"\nUPCOMING EARNINGS (next 14 days) ({len(upcoming)})\n")
    if not upcoming:
        sys.stdout.write("  (none)\n")
    else:
        for u in upcoming:
            est = f"est={u['estimate_eps']:.2f}" if u["estimate_eps"] is not None else "est=--"
            sys.stdout.write(f"  {u['ticker']:<5} {u['date']}  {est}\n")

    return 0


def cmd_paper_tick(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    sectors_dir = repo_root / "sectors"
    earnings_cache = repo_root / "data" / "raw" / "earnings"

    logger.info("loading sector config: %s", args.sector)
    sector_cfg, _sector_sha = load_sector(args.sector, sectors_dir=sectors_dir)

    if args.csv is None:
        # Default: paper_trading/A_T+60_<YYYY-MM>.csv based on today
        month_tag = datetime.now(UTC).strftime("%Y-%m")
        csv_path = repo_root / "paper_trading" / f"A_T+60_{month_tag}.csv"
    else:
        csv_path = Path(args.csv)

    logger.info("paper-tick on %s (threshold |SUE|>%.2f)", csv_path, args.sue_threshold)

    min_event_date = (
        pd.Timestamp(args.min_event_date) if args.min_event_date else None
    )
    summary = paper_tick(
        sector_cfg,
        csv_path,
        sue_threshold=args.sue_threshold,
        earnings_cache_dir=earnings_cache,
        min_event_date=min_event_date,
    )

    sys.stdout.write(f"csv:                {csv_path}\n")
    sys.stdout.write(f"new candidates:     {summary['new_candidates']}\n")
    sys.stdout.write(f"-> in_flight:       {summary['transitioned_in_flight']}\n")
    sys.stdout.write(f"-> closed:          {summary['transitioned_closed']}\n")
    sys.stdout.write("by status:\n")
    for status, count in sorted(summary["by_status"].items()):
        sys.stdout.write(f"  {status:<18} {count}\n")
    sys.stdout.write(f"cumulative net P&L: {summary['cumulative_net_return']:+.4f}\n")
    if summary["new_candidates"] > 0:
        sys.stdout.write(
            "\nACTION: review pending_review row(s) — verify IR press release, "
            "edit CSV: status pending_review -> approved (or rejected).\n"
        )

    # Emit dashboard.html alongside the paper tick.
    dashboard_path = repo_root / "data" / "processed" / f"dashboard_{args.sector}.html"
    today_ts = pd.Timestamp.today().normalize()
    _emit_dashboard(
        sector_cfg,
        csv_path,
        dashboard_path,
        today=today_ts,
        cap_eur=args.cap_eur,
        max_per_trade_eur=args.max_per_trade_eur,
    )
    sys.stdout.write(f"dashboard: {dashboard_path}\n")
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

    de = sub.add_parser("decide", help="apply Layer 4 stats + emit decision artifact + HTML report")
    de.add_argument("--sector", required=True, help="sector name (matches sectors/<name>.yaml)")
    de.set_defaults(func=cmd_decide)

    pt = sub.add_parser("paper-tick", help="paper trading: detect new candidates + transition state")
    pt.add_argument("--sector", required=True, help="sector name (matches sectors/<name>.yaml)")
    pt.add_argument("--csv", default=None, help="paper trading CSV path (default: paper_trading/A_T+60_<YYYY-MM>.csv)")
    pt.add_argument("--sue-threshold", type=float, default=1.0, help="|SUE| threshold for new candidate detection")
    pt.add_argument("--min-event-date", default=None, help="only consider events from this date (YYYY-MM-DD); default: today minus 7 days")
    pt.add_argument("--cap-eur", type=float, default=5000.0, help="binding capital cap in EUR (prereg §10.1)")
    pt.add_argument("--max-per-trade-eur", type=float, default=1000.0, help="max position size per trade in EUR (20%% cap, §8.1)")
    pt.set_defaults(func=cmd_paper_tick)

    td = sub.add_parser("today", help="paper/live: print today's actions + status snapshot")
    td.add_argument("--sector", required=True, help="sector name (matches sectors/<name>.yaml)")
    td.add_argument("--csv", default=None, help="paper/live CSV path (default: paper_trading/A_T+60_<YYYY-MM>.csv)")
    td.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD); default: real today")
    td.add_argument("--cap-eur", type=float, default=5000.0, help="binding capital cap in EUR")
    td.add_argument("--max-per-trade-eur", type=float, default=1000.0, help="max position size per trade in EUR")
    td.set_defaults(func=cmd_today)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
