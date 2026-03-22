#!/usr/bin/env python
"""UST bond end-of-day service runner.

Warms raw UST bond pricers and computes timeseries using FedInvest + WSJ
3pm ET snapshots. One snapshot per business date.

Two modes:
1. ``backfill``: expand a historical date range into business dates and
   warm both raw pricers and computed timeseries one trade date at a time.
2. ``live-service``: resolve today's (or explicit) trading date(s) and warm
   the raw EOD snapshot plus timeseries.
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
    DEFAULT_EOD_SOURCE,
    DEFAULT_N_JOBS,
    DEFAULT_TIMEZONE,
    BackfillProgress,
    DayCalibrationStats,
    _argparse_date,
    _format_dt,
    _format_duration,
    _write_perf_event,
    add_common_ust_args,
    build_frb_mdp,
    build_frb_tb,
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
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else default_perf_log_path("ust_eod")
    start_date: dt.date = args.start_date
    end_date: dt.date = args.end_date

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
        label=f"UST-eod-{source}",
        total_days=total_days,
        skipped_days=0,
    )

    logger.info(
        "Starting UST EOD backfill [%s -> %s]: universe=%s source=%s days=%s",
        start_date.isoformat(), end_date.isoformat(), universe, source, total_days,
    )

    for trade_date in iter_business_dates(start_date, end_date):
        cusips = resolve_bond_universe(
            as_of_date=trade_date,
            tier=universe,
            extra_cusips=extra_cusips,
        )

        # --- Raw bond warming (single EOD snapshot per date) ---
        day_started = time.perf_counter()
        status = "ok"
        error = None
        pricers_count = 0
        if not args.skip_curve_warm:
            try:
                result = mdp.get_data({
                    "cusips": list(cusips),
                    "timestamp": trade_date,
                })
                pricers_count = len(result) if result else 0
                if pricers_count == 0:
                    status = "error"
                    error = "No pricers returned"
                elif pricers_count < len(cusips):
                    status = "partial"
                    error = f"{len(cusips) - pricers_count}/{len(cusips)} cusips failed"
            except Exception as exc:
                status = "error"
                error = str(exc)
                logger.exception("Raw UST EOD warm failed for %s", trade_date.isoformat())
                if bool(args.fail_fast):
                    overall_failure = True
                    break
        day_elapsed = time.perf_counter() - day_started

        day_result = DayCalibrationStats(
            trade_date=trade_date.isoformat(),
            requested_cusips=len(cusips),
            returned_pricers=pricers_count,
            missing_pricers=max(0, len(cusips) - pricers_count),
            first_timestamp=trade_date.isoformat(),
            last_timestamp=trade_date.isoformat(),
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
                timestamps=[trade_date],
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

    logger.info("UST EOD backfill complete. Performance log: %s", perf_log_path)
    return 0 if not overall_failure else 1


# ---------------------------------------------------------------------------
# Live-service mode
# ---------------------------------------------------------------------------
def _run_live_service_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    source = str(args.source)
    universe = str(args.universe)
    extra_cusips = parse_cusips_arg(args.cusips)
    values = parse_values_arg(args.values)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else default_perf_log_path("ust_eod_live")

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

    tz = ZoneInfo(DEFAULT_TIMEZONE)
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

        logger.info(
            "UST EOD live-service %s: cusips=%s source=%s",
            trading_date.isoformat(), len(cusips), source,
        )

        # --- Raw warm (single EOD snapshot) ---
        pricers_count = 0
        status = "ok"
        if not args.skip_curve_warm:
            try:
                result = mdp.get_data({
                    "cusips": list(cusips),
                    "timestamp": trading_date,
                })
                pricers_count = len(result) if result else 0
            except Exception as exc:
                status = "error"
                logger.exception("Raw UST EOD warm failed for %s: %s", trading_date.isoformat(), exc)

        # --- Timeseries warm ---
        ts_summary: dict[str, Any] = {"status": "skipped", "failed_cusips": [], "rows": 0, "cols": 0}
        if tb is not None and not args.skip_timeseries_warm and status != "error":
            ts_summary = warm_bond_timeseries_window(
                cusips=cusips,
                values=values,
                timestamps=[trading_date],
                tb=tb,
                n_jobs=int(args.n_jobs),
                ignore_cache=bool(args.ignore_cache),
                perf_log_path=perf_log_path,
                logger=logger,
                label=trading_date.isoformat(),
            )

        if ts_summary.get("status") == "partial" and status == "ok":
            status = "partial"

        summary = {
            "event": "service_window",
            "label": trading_date.isoformat(),
            "status": status,
            "cusips_requested": len(cusips),
            "pricers_returned": pricers_count,
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
        "UST EOD live-service summary: windows=%s non_skipped=%s errors=%s",
        len(window_summaries), len(non_skipped),
        sum(1 for s in non_skipped if s.get("status") in ("partial", "error")),
    )
    return 0 if all(s.get("status") == "ok" for s in non_skipped) else (0 if not non_skipped else 1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="UST bond EOD backfill and live-service warmer.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # --- backfill ---
    backfill = subparsers.add_parser("backfill", help="Backfill raw EOD pricers and timeseries across a date range.")
    add_common_ust_args(backfill, default_source=DEFAULT_EOD_SOURCE, default_n_jobs=DEFAULT_N_JOBS)
    backfill.add_argument("--start-date", required=True, type=_argparse_date, help="Start date YYYY-MM-DD.")
    backfill.add_argument("--end-date", required=True, type=_argparse_date, help="End date YYYY-MM-DD.")
    backfill.add_argument("--fail-fast", action="store_true")

    # --- live-service ---
    live_service = subparsers.add_parser("live-service", help="Warm today's EOD snapshot.")
    add_common_ust_args(live_service, default_source=DEFAULT_EOD_SOURCE, default_n_jobs=DEFAULT_N_JOBS)
    live_service.add_argument("--date", action="append", type=_argparse_date, default=[], help="Trading date. Repeatable.")
    live_service.add_argument("--start-date", type=_argparse_date, default=None)
    live_service.add_argument("--end-date", type=_argparse_date, default=None)

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
    logger = configure_logging(verbose=bool(args.verbose), name="ust_eod")
    if args.mode == "backfill":
        return _run_backfill_mode(args, logger)
    if args.mode == "live-service":
        return _run_live_service_mode(args, logger)
    raise ValueError(f"Unsupported mode '{args.mode}'")


if __name__ == "__main__":
    raise SystemExit(main())
