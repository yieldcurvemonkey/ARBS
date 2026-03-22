#!/usr/bin/env python
"""UST bond intraday service runner.

Warms raw UST bond pricers and computes timeseries using Webull+WSJ intraday
data at minute granularity during the 07:00-15:00 ET session.

Two modes:
1. ``backfill``: expand a historical date range into intraday minute buckets
   and warm both raw pricers and computed timeseries one trade date at a time.
2. ``live-service``: resolve today's (or explicit) trading date(s) and warm
   the raw snapshot plus timeseries for the current session window.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import logging
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import QuantLib as ql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._ust_service_common import (
    DEFAULT_FREQ,
    DEFAULT_INTRADAY_SOURCE,
    DEFAULT_LAG_MINUTES,
    DEFAULT_LIVE_SERVICE_N_JOBS,
    DEFAULT_N_JOBS,
    DEFAULT_SESSION_END,
    DEFAULT_SESSION_START,
    DEFAULT_TIMEZONE,
    BackfillProgress,
    DayCalibrationStats,
    _argparse_date,
    _argparse_time,
    _format_dt,
    _format_duration,
    _parse_time,
    _safe_warm_raw_bonds,
    _write_perf_event,
    add_common_ust_args,
    build_frb_mdp,
    build_frb_tb,
    build_intraday_minute_buckets,
    configure_logging,
    configure_runtime,
    count_business_days,
    default_perf_log_path,
    is_business_day,
    iter_business_dates,
    parse_cusips_arg,
    parse_values_arg,
    resolve_bond_universe,
    warm_bond_timeseries_window,
)


# ---------------------------------------------------------------------------
# Backfill mode
# ---------------------------------------------------------------------------
def _run_backfill_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    source = str(args.source)
    universe = str(args.universe)
    extra_cusips = parse_cusips_arg(args.cusips)
    values = parse_values_arg(args.values)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else default_perf_log_path("ust_intraday")
    start_date: dt.date = args.start_date
    end_date: dt.date = args.end_date
    session_start: dt.time = args.session_start
    session_end: dt.time = args.session_end
    freq: str = args.freq
    timezone_name: str = args.timezone

    mdp = build_frb_mdp(source)
    tb = None
    if not args.skip_timeseries_warm:
        tb = build_frb_tb(
            mdp,
            show_tqdm=bool(args.show_tqdm),
            use_duckdb=bool(args.use_duckdb),
            ts_base_dir=str(args.ts_base_dir),
            ts_row_group_size=int(args.ts_row_group_size),
            ts_compression=str(args.ts_compression),
        )

    total_days = count_business_days(start_date, end_date)
    overall_failure = False

    progress = BackfillProgress(
        label=f"UST-intraday-{source}",
        total_days=total_days,
        skipped_days=0,
    )

    logger.info(
        "Starting UST intraday backfill [%s -> %s]: universe=%s source=%s days=%s session=%s-%s %s",
        start_date.isoformat(), end_date.isoformat(), universe, source,
        total_days, session_start, session_end, timezone_name,
    )

    for trade_date in iter_business_dates(start_date, end_date):
        cusips = resolve_bond_universe(
            as_of_date=trade_date,
            tier=universe,
            extra_cusips=extra_cusips,
        )
        timestamps = build_intraday_minute_buckets(
            trade_date,
            session_start=session_start,
            session_end=session_end,
            freq=freq,
            timezone_name=timezone_name,
        )
        if not timestamps:
            logger.info("Skipping %s: no timestamps generated.", trade_date.isoformat())
            progress.record_calibration(status="skipped")
            progress.record_timeseries(status="skipped", failed_cusips=[])
            continue

        # --- Raw bond warming ---
        day_started = time.perf_counter()
        status = "ok"
        error = None
        pricers_count = 0
        if not args.skip_curve_warm:
            try:
                pricers_count, failed_ts = _safe_warm_raw_bonds(
                    mdp,
                    cusips=cusips,
                    timestamps=timestamps,
                    force_refresh=bool(args.ignore_cache),
                    show_tqdm=bool(args.show_tqdm),
                    max_workers=int(args.n_jobs),
                    logger=logger,
                )
                if failed_ts:
                    status = "partial"
            except Exception as exc:
                status = "error"
                error = str(exc)
                logger.exception("Raw UST warm failed for %s", trade_date.isoformat())
                if bool(args.fail_fast):
                    overall_failure = True
                    break
        day_elapsed = time.perf_counter() - day_started

        day_result = DayCalibrationStats(
            trade_date=trade_date.isoformat(),
            requested_cusips=len(cusips),
            returned_pricers=pricers_count,
            missing_pricers=max(0, len(cusips) * len(timestamps) - pricers_count),
            first_timestamp=_format_dt(timestamps[0]) if timestamps else None,
            last_timestamp=_format_dt(timestamps[-1]) if timestamps else None,
            elapsed_seconds=day_elapsed,
            pricers_per_second=pricers_count / max(day_elapsed, 0.001),
            status=status,
            error=error,
        )
        _write_perf_event(perf_log_path, {"event": "day_result", **vars(day_result)})
        progress.record_calibration(status=status)

        # --- Timeseries warming ---
        ts_summary: dict[str, Any] = {"status": "skipped", "failed_cusips": []}
        if tb is not None and status != "error":
            ts_summary = warm_bond_timeseries_window(
                cusips=cusips,
                values=values,
                timestamps=timestamps,
                tb=tb,
                n_jobs=int(args.n_jobs),
                ignore_cache=bool(args.ignore_cache),
                perf_log_path=perf_log_path,
                logger=logger,
                label=trade_date.isoformat(),
            )
        progress.record_timeseries(
            status=ts_summary.get("status", "skipped"),
            failed_cusips=ts_summary.get("failed_cusips", []),
        )

        logger.info(progress.format_heartbeat())
        _write_perf_event(perf_log_path, progress.to_perf_event())
        gc.collect()

    if tb is not None:
        tb.close()

    logger.info("UST intraday backfill complete. Performance log: %s", perf_log_path)
    return 0 if not overall_failure else 1


# ---------------------------------------------------------------------------
# Live-service mode
# ---------------------------------------------------------------------------
def _run_live_service_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    source = str(args.source)
    universe = str(args.universe)
    extra_cusips = parse_cusips_arg(args.cusips)
    values = parse_values_arg(args.values)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else default_perf_log_path("ust_intraday_live")
    timezone_name = str(args.timezone)

    mdp = build_frb_mdp(source)
    tb = None
    if not args.skip_timeseries_warm:
        tb = build_frb_tb(
            mdp,
            show_tqdm=bool(args.show_tqdm),
            use_duckdb=bool(args.use_duckdb),
            ts_base_dir=str(args.ts_base_dir),
            ts_row_group_size=int(args.ts_row_group_size),
            ts_compression=str(args.ts_compression),
        )

    tz = ZoneInfo(timezone_name)
    ny_now = dt.datetime.now(tz)
    trading_dates = []
    if args.date:
        trading_dates = list(args.date)
    elif args.start_date is not None and args.end_date is not None:
        trading_dates = list(iter_business_dates(args.start_date, args.end_date))
    else:
        trading_dates = [ny_now.date()]

    window_summaries: list[dict[str, Any]] = []
    for trading_date in trading_dates:
        if not is_business_day(trading_date):
            logger.info("Skipping weekend/holiday %s.", trading_date.isoformat())
            continue

        cusips = resolve_bond_universe(
            as_of_date=trading_date,
            tier=universe,
            extra_cusips=extra_cusips,
        )

        # Build timestamps up to (now - lag_minutes)
        all_timestamps = build_intraday_minute_buckets(
            trading_date,
            session_start=args.session_start,
            session_end=args.session_end,
            freq=args.freq,
            timezone_name=timezone_name,
        )
        lag_cutoff = ny_now - dt.timedelta(minutes=int(args.lag_minutes))
        timestamps = [ts for ts in all_timestamps if ts <= lag_cutoff]
        if not timestamps:
            logger.info("Skipping %s: no timestamps before lag cutoff.", trading_date.isoformat())
            window_summaries.append({"label": trading_date.isoformat(), "status": "skipped"})
            continue

        logger.info(
            "UST intraday live-service %s: cusips=%s timestamps=%s first=%s last=%s",
            trading_date.isoformat(), len(cusips), len(timestamps),
            _format_dt(timestamps[0]), _format_dt(timestamps[-1]),
        )

        # --- Raw warm ---
        curve_ready = 0
        curve_failed: list = []
        if not args.skip_curve_warm:
            curve_ready, curve_failed = _safe_warm_raw_bonds(
                mdp,
                cusips=cusips,
                timestamps=timestamps,
                force_refresh=bool(args.ignore_cache),
                show_tqdm=bool(args.show_tqdm),
                max_workers=int(args.n_jobs),
                logger=logger,
            )

        # --- Timeseries warm ---
        ts_summary: dict[str, Any] = {"status": "skipped", "failed_cusips": [], "rows": 0, "cols": 0}
        if tb is not None and not args.skip_timeseries_warm:
            ts_summary = warm_bond_timeseries_window(
                cusips=cusips,
                values=values,
                timestamps=timestamps,
                tb=tb,
                n_jobs=int(args.n_jobs),
                ignore_cache=bool(args.ignore_cache),
                perf_log_path=perf_log_path,
                logger=logger,
                label=trading_date.isoformat(),
            )

        status = "ok"
        if curve_failed or ts_summary.get("status") == "partial":
            status = "partial"
        if not curve_ready and not args.skip_curve_warm:
            status = "error"

        summary = {
            "event": "service_window",
            "label": trading_date.isoformat(),
            "status": status,
            "curve_requested": len(timestamps),
            "curve_ready": curve_ready,
            "curve_failed_count": len(curve_failed),
            "ts_rows": ts_summary.get("rows", 0),
            "ts_cols": ts_summary.get("cols", 0),
            "ts_failed_cusips": ts_summary.get("failed_cusips", []),
        }
        _write_perf_event(perf_log_path, summary)
        window_summaries.append(summary)

    if tb is not None:
        tb.close()

    non_skipped = [s for s in window_summaries if s.get("status") != "skipped"]
    logger.info(
        "UST intraday live-service summary: windows=%s non_skipped=%s errors=%s",
        len(window_summaries), len(non_skipped),
        sum(1 for s in non_skipped if s.get("status") in ("partial", "error")),
    )
    return 0 if all(s.get("status") == "ok" for s in non_skipped) else (0 if not non_skipped else 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UST bond intraday backfill and live-service warmer.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # --- backfill ---
    backfill = subparsers.add_parser("backfill", help="Backfill raw bond pricers and timeseries across a date range.")
    add_common_ust_args(backfill, default_source=DEFAULT_INTRADAY_SOURCE, default_n_jobs=DEFAULT_N_JOBS)
    backfill.add_argument("--start-date", required=True, type=_argparse_date, help="Start date YYYY-MM-DD.")
    backfill.add_argument("--end-date", required=True, type=_argparse_date, help="End date YYYY-MM-DD.")
    backfill.add_argument("--session-start", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_START))
    backfill.add_argument("--session-end", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_END))
    backfill.add_argument("--freq", default=DEFAULT_FREQ)
    backfill.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    backfill.add_argument("--fail-fast", action="store_true")

    # --- live-service ---
    live_service = subparsers.add_parser("live-service", help="Warm today's intraday session.")
    add_common_ust_args(live_service, default_source=DEFAULT_INTRADAY_SOURCE, default_n_jobs=DEFAULT_LIVE_SERVICE_N_JOBS)
    live_service.add_argument("--date", action="append", type=_argparse_date, default=[], help="Trading date. Repeatable.")
    live_service.add_argument("--start-date", type=_argparse_date, default=None)
    live_service.add_argument("--end-date", type=_argparse_date, default=None)
    live_service.add_argument("--session-start", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_START))
    live_service.add_argument("--session-end", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_END))
    live_service.add_argument("--freq", default=DEFAULT_FREQ)
    live_service.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    live_service.add_argument("--lag-minutes", type=int, default=DEFAULT_LAG_MINUTES)

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.skip_curve_warm and args.skip_timeseries_warm:
        parser.error("At least one of raw curve warming or timeseries warming must remain enabled.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_runtime(disable_l2=bool(args.disable_l2))
    logger = configure_logging(verbose=bool(args.verbose), name="ust_intraday")
    if args.mode == "backfill":
        return _run_backfill_mode(args, logger)
    if args.mode == "live-service":
        return _run_live_service_mode(args, logger)
    raise ValueError(f"Unsupported mode '{args.mode}'")


if __name__ == "__main__":
    raise SystemExit(main())
