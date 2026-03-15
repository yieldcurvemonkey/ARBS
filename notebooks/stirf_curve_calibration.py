#!/usr/bin/env python
"""Run bulk STIRF curve calibration over daily minute buckets.

This script expands a business-date range into per-day intraday timestamp buckets,
runs one bulk calibration call per day, and writes structured performance logs.

It supports both:
1. Simple same-day clock windows such as 07:00 -> 17:00.
2. Full CME Globex trade-date sessions, which run from 5:00 PM America/Chicago
   on the prior calendar day through 4:00 PM America/Chicago on the trade date,
   with the 4:00 PM -> 5:00 PM maintenance break excluded.

Example:
    python notebooks/stirf_curve_calibration.py ^
        --start-date 2026-03-10 ^
        --end-date 2026-03-12 ^
        --curve-name USD-SOFR-1D-Q12STIRT ^
        --cme-session ^
        --freq 1min ^
        --n-jobs 8 ^
        --calibration-executor process
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import logging
import sys
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import QuantLib as ql
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from BT.misc import ql_cal_date_range
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP


DEFAULT_SOURCE = "BARCHART_STIRF-RL"
DEFAULT_CURVE_NAME = "USD-SOFR-1D-Q12STIRT"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CME_TIMEZONE = "America/Chicago"
DEFAULT_SESSION_START = "07:00"
DEFAULT_SESSION_END = "17:00"
DEFAULT_FREQ = "1min"
DEFAULT_N_JOBS = 8
DEFAULT_CALIBRATION_EXECUTOR = "process"
DEFAULT_LOG_DIR = REPO_ROOT / "notebooks" / "logs"
DEFAULT_CME_SESSION_OPEN = dt.time(17, 0)
DEFAULT_CME_SESSION_CLOSE = dt.time(16, 0)


@dataclass
class DayCalibrationStats:
    trade_date: str
    requested_timestamps: int
    returned_curves: int
    missing_curves: int
    first_timestamp: str | None
    last_timestamp: str | None
    elapsed_seconds: float
    curves_per_second: float
    status: str
    error: str | None = None
    requested_curve_name: str | None = None
    resolved_curve_name: str | None = None


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value).strip())


def _parse_time(value: str) -> dt.time:
    token = str(value).strip()
    try:
        return dt.time.fromisoformat(token)
    except ValueError as exc:
        raise ValueError(f"Invalid time '{value}'. Expected HH:MM or HH:MM:SS.") from exc


def _format_dt(value: dt.datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _default_perf_log_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"stirf_curve_calibration_{stamp}.jsonl"


def _configure_logging(*, verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("stirf_curve_calibration")


def _is_business_day(value: dt.date, calendar: ql.Calendar) -> bool:
    ql_date = ql.Date(value.day, value.month, value.year)
    return bool(calendar.isBusinessDay(ql_date))


def _normalize_timestamp_list(values: list[Any]) -> list[dt.datetime]:
    out: list[dt.datetime] = []
    for value in values:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if not isinstance(value, dt.datetime):
            raise TypeError(f"Expected datetime-like bucket value, got {type(value)}")
        out.append(value)
    return out


def _build_sunday_open_segment(
    *,
    trade_date: dt.date,
    freq: str,
    timezone: ZoneInfo,
) -> list[dt.datetime]:
    session_open_date = trade_date - dt.timedelta(days=1)
    segment_start = dt.datetime.combine(session_open_date, DEFAULT_CME_SESSION_OPEN, tzinfo=timezone)
    segment_end = dt.datetime.combine(session_open_date, dt.time(23, 59), tzinfo=timezone)
    return _normalize_timestamp_list(list(pd.date_range(start=segment_start, end=segment_end, freq=freq)))


def _build_cme_trade_date_bucket(
    *,
    trade_date: dt.date,
    freq: str,
    timezone: ZoneInfo,
    calendar: ql.Calendar,
) -> list[dt.datetime]:
    if not _is_business_day(trade_date, calendar):
        return []

    current_start = dt.datetime.combine(trade_date, dt.time(0, 0), tzinfo=timezone)
    current_end = dt.datetime.combine(trade_date, DEFAULT_CME_SESSION_CLOSE, tzinfo=timezone)
    current_session = _normalize_timestamp_list(
        list(
            ql_cal_date_range(
                calendar,
                start=current_start,
                end=current_end,
                freq=freq,
                cme_session=True,
            )
        )
    )

    previous_date = trade_date - dt.timedelta(days=1)
    if _is_business_day(previous_date, calendar):
        previous_start = dt.datetime.combine(previous_date, DEFAULT_CME_SESSION_OPEN, tzinfo=timezone)
        previous_end = dt.datetime.combine(previous_date, dt.time(23, 59), tzinfo=timezone)
        previous_session = _normalize_timestamp_list(
            list(
                ql_cal_date_range(
                    calendar,
                    start=previous_start,
                    end=previous_end,
                    freq=freq,
                    cme_session=True,
                )
            )
        )
    elif previous_date.weekday() == 6:
        # Sunday evening is part of Monday's Globex trade date even though Sunday is not
        # a business day on the QuantLib calendar.
        previous_session = _build_sunday_open_segment(
            trade_date=trade_date,
            freq=freq,
            timezone=timezone,
        )
    else:
        previous_session = []

    return previous_session + current_session


def build_daily_minute_buckets(
    *,
    start_date: dt.date,
    end_date: dt.date,
    session_start: dt.time,
    session_end: dt.time,
    freq: str,
    timezone: ZoneInfo,
    calendar: ql.Calendar | None = None,
    cme_session: bool = False,
) -> OrderedDict[dt.date, list[dt.datetime]]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    if not cme_session and session_end < session_start:
        raise ValueError("session_end must be on or after session_start.")

    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out: OrderedDict[dt.date, list[dt.datetime]] = OrderedDict()

    current = start_date
    while current <= end_date:
        if _is_business_day(current, cal):
            if cme_session:
                bucket = _build_cme_trade_date_bucket(
                    trade_date=current,
                    freq=freq,
                    timezone=timezone,
                    calendar=cal,
                )
            else:
                bucket_start = dt.datetime.combine(current, session_start, tzinfo=timezone)
                bucket_end = dt.datetime.combine(current, session_end, tzinfo=timezone)
                bucket = _normalize_timestamp_list(
                    list(
                        ql_cal_date_range(
                            cal,
                            start=bucket_start,
                            end=bucket_end,
                            freq=freq,
                            open_time=session_start,
                            close_time=session_end,
                        )
                    )
                )
            out[current] = list(bucket)
        current += dt.timedelta(days=1)

    return out


def build_bulk_request(
    *,
    curve_name: str,
    timestamps: list[dt.datetime],
    n_jobs: int,
    show_tqdm: bool,
    ignore_cache: bool,
    calibration_executor: str,
    auto_prime_bulk: bool,
    stirf_fetch_max_workers: int | None = None,
    calibration_max_workers: int | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "curve_name": curve_name,
        "timestamps": list(timestamps),
        "n_jobs": int(n_jobs),
        "show_tqdm": bool(show_tqdm),
        "ignore_cache": bool(ignore_cache),
        "calibration_executor": str(calibration_executor),
        "auto_prime_bulk": bool(auto_prime_bulk),
    }
    if stirf_fetch_max_workers is not None:
        request["stirf_fetch_max_workers"] = int(stirf_fetch_max_workers)
    if calibration_max_workers is not None:
        request["calibration_max_workers"] = int(calibration_max_workers)
    return request


def _write_perf_event(perf_log_path: Path, payload: dict[str, Any]) -> None:
    perf_log_path.parent.mkdir(parents=True, exist_ok=True)
    with perf_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _curve_meta(curve: Any) -> dict[str, Any]:
    if curve is None or not hasattr(curve, "meta"):
        return {}
    meta = curve.meta()
    return meta if isinstance(meta, dict) else {}


def _summarize_day(
    *,
    trade_date: dt.date,
    timestamps: list[dt.datetime],
    curves: dict[Any, Any],
    elapsed_seconds: float,
    status: str,
    error: str | None,
    requested_curve_name: str,
) -> DayCalibrationStats:
    sample_curve = next(iter(curves.values()), None)
    sample_meta = _curve_meta(sample_curve)
    returned_curves = len(curves)
    requested = len(timestamps)
    return DayCalibrationStats(
        trade_date=trade_date.isoformat(),
        requested_timestamps=requested,
        returned_curves=returned_curves,
        missing_curves=max(requested - returned_curves, 0),
        first_timestamp=_format_dt(timestamps[0] if timestamps else None),
        last_timestamp=_format_dt(timestamps[-1] if timestamps else None),
        elapsed_seconds=elapsed_seconds,
        curves_per_second=(returned_curves / elapsed_seconds) if elapsed_seconds > 0 else 0.0,
        status=status,
        error=error,
        requested_curve_name=requested_curve_name,
        resolved_curve_name=sample_meta.get("curve_name"),
    )


def _summarize_run(
    *,
    curve_name: str,
    source: str,
    daily_results: list[DayCalibrationStats],
    total_elapsed_seconds: float,
    business_days: int,
) -> dict[str, Any]:
    successful_days = sum(1 for row in daily_results if row.status == "ok")
    failed_days = sum(1 for row in daily_results if row.status != "ok")
    requested_timestamps = sum(row.requested_timestamps for row in daily_results)
    returned_curves = sum(row.returned_curves for row in daily_results)
    missing_curves = sum(row.missing_curves for row in daily_results)
    return {
        "event": "run_summary",
        "curve_name": curve_name,
        "source": source,
        "business_days": business_days,
        "successful_days": successful_days,
        "failed_days": failed_days,
        "requested_timestamps": requested_timestamps,
        "returned_curves": returned_curves,
        "missing_curves": missing_curves,
        "total_elapsed_seconds": total_elapsed_seconds,
        "curves_per_second": (returned_curves / total_elapsed_seconds) if total_elapsed_seconds > 0 else 0.0,
    }


def _release_barchart_runtime_state(*, source: str, logger: logging.Logger | None = None) -> None:
    source_token = str(source).upper().strip()
    if source_token not in {"BARCHART_STIRF-RL", "BARCHART_STIRF_RL"}:
        return

    state = getattr(IRSwapsMDP, "_BARCHART_STIRF_STATE", None)
    if not isinstance(state, dict):
        return

    builder = None
    state_lock = state.get("lock")
    if state_lock is None:
        builder = state.get("builder")
        state["builder"] = None
    else:
        with state_lock:
            builder = state.get("builder")
            state["builder"] = None

    if builder is None:
        gc.collect()
        return

    builder_cls = builder.__class__
    mem_cache = getattr(builder_cls, "_CURVE_MEM_CACHE", None)
    mem_cache_lock = getattr(builder_cls, "_CURVE_MEM_CACHE_LOCK", None)
    if isinstance(mem_cache, dict):
        if mem_cache_lock is None:
            mem_cache.clear()
        else:
            with mem_cache_lock:
                mem_cache.clear()

    for child_attr in ("stirf_mdp", "stirf_mdp_schwab_app", "stirf_mdp_barchart"):
        child = getattr(builder, child_attr, None)
        if child is None:
            continue
        close_child_cache = getattr(child, "close_cache", None)
        if callable(close_child_cache):
            try:
                close_child_cache()
            except Exception:
                if logger is not None:
                    logger.debug("Failed to close %s cache while releasing BARCHART runtime state.", child_attr, exc_info=True)
        if hasattr(child, "_cache_ready"):
            try:
                child._cache_ready = False
            except Exception:
                pass

    close_builder_cache = getattr(builder, "close_cache", None)
    if callable(close_builder_cache):
        try:
            close_builder_cache()
        except Exception:
            if logger is not None:
                logger.debug("Failed to close BARCHART builder cache while releasing runtime state.", exc_info=True)

    del builder
    gc.collect()


def run_bucketed_calibration(
    *,
    curve_mdp: Any,
    curve_name: str,
    source: str,
    daily_buckets: OrderedDict[dt.date, list[dt.datetime]],
    request_options: dict[str, Any],
    perf_log_path: Path,
    logger: logging.Logger,
    fail_fast: bool,
    retain_all_curves: bool = False,
    release_runtime_state: bool = True,
) -> tuple[dict[Any, Any], list[DayCalibrationStats], dict[str, Any]]:
    all_curves: dict[Any, Any] = {}
    daily_results: list[DayCalibrationStats] = []

    _write_perf_event(
        perf_log_path,
        {
            "event": "run_start",
            "curve_name": curve_name,
            "source": source,
            "business_days": len(daily_buckets),
            "request_options": {
                key: value
                for key, value in request_options.items()
                if key != "timestamps"
            },
        },
    )

    run_started = time.perf_counter()
    for trade_date, timestamps in daily_buckets.items():
        request = build_bulk_request(
            curve_name=curve_name,
            timestamps=timestamps,
            n_jobs=request_options["n_jobs"],
            show_tqdm=request_options["show_tqdm"],
            ignore_cache=request_options["ignore_cache"],
            calibration_executor=request_options["calibration_executor"],
            auto_prime_bulk=request_options["auto_prime_bulk"],
            stirf_fetch_max_workers=request_options.get("stirf_fetch_max_workers"),
            calibration_max_workers=request_options.get("calibration_max_workers"),
        )
        logger.info(
            "Starting %s bucket: requested=%s first=%s last=%s executor=%s",
            trade_date.isoformat(),
            len(timestamps),
            _format_dt(timestamps[0] if timestamps else None),
            _format_dt(timestamps[-1] if timestamps else None),
            request["calibration_executor"],
        )

        started = time.perf_counter()
        curves: dict[Any, Any] = {}
        status = "ok"
        error: str | None = None
        try:
            curves = curve_mdp.bulk_get_data(request)
            if retain_all_curves:
                all_curves.update(curves)
        except Exception as exc:
            status = "error"
            error = str(exc)
            logger.exception("Bulk calibration failed for %s", trade_date.isoformat())
            if fail_fast:
                elapsed = time.perf_counter() - started
                day_result = _summarize_day(
                    trade_date=trade_date,
                    timestamps=timestamps,
                    curves=curves,
                    elapsed_seconds=elapsed,
                    status=status,
                    error=error,
                    requested_curve_name=curve_name,
                )
                daily_results.append(day_result)
                _write_perf_event(
                    perf_log_path,
                    {"event": "day_result", **asdict(day_result)},
                )
                curves.clear()
                if release_runtime_state:
                    _release_barchart_runtime_state(source=source, logger=logger)
                raise

        elapsed = time.perf_counter() - started
        day_result = _summarize_day(
            trade_date=trade_date,
            timestamps=timestamps,
            curves=curves,
            elapsed_seconds=elapsed,
            status=status,
            error=error,
            requested_curve_name=curve_name,
        )
        daily_results.append(day_result)
        logger.info(
            "Finished %s bucket: status=%s returned=%s/%s missing=%s elapsed=%.2fs",
            trade_date.isoformat(),
            day_result.status,
            day_result.returned_curves,
            day_result.requested_timestamps,
            day_result.missing_curves,
            day_result.elapsed_seconds,
        )
        _write_perf_event(
            perf_log_path,
            {"event": "day_result", **asdict(day_result)},
        )
        if not retain_all_curves:
            curves.clear()
        if release_runtime_state:
            _release_barchart_runtime_state(source=source, logger=logger)

    total_elapsed_seconds = time.perf_counter() - run_started
    summary = _summarize_run(
        curve_name=curve_name,
        source=source,
        daily_results=daily_results,
        total_elapsed_seconds=total_elapsed_seconds,
        business_days=len(daily_buckets),
    )
    _write_perf_event(perf_log_path, summary)
    return all_curves, daily_results, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bucket business dates into minute snapshots and run bulk STIRF calibration.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--curve-name", default=DEFAULT_CURVE_NAME)
    parser.add_argument("--start-date", required=True, help="Inclusive business-date start in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Inclusive business-date end in YYYY-MM-DD.")
    parser.add_argument("--session-start", default=DEFAULT_SESSION_START, help="Session start in HH:MM.")
    parser.add_argument("--session-end", default=DEFAULT_SESSION_END, help="Session end in HH:MM.")
    parser.add_argument(
        "--cme-session",
        action="store_true",
        help="Use full CME Globex trade-date sessions: prior-day 17:00 America/Chicago through trade-date 16:00 America/Chicago.",
    )
    parser.add_argument("--freq", default=DEFAULT_FREQ, help="Pandas frequency for intraday bucketing, e.g. 1min.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for bucket timestamps.")
    parser.add_argument("--n-jobs", type=int, default=DEFAULT_N_JOBS)
    parser.add_argument(
        "--calibration-executor",
        choices=("thread", "process"),
        default=DEFAULT_CALIBRATION_EXECUTOR,
    )
    parser.add_argument("--stirf-fetch-max-workers", type=int)
    parser.add_argument("--calibration-max-workers", type=int)
    parser.add_argument("--ignore-cache", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(show_tqdm=True, auto_prime_bulk=True)
    parser.add_argument("--show-tqdm", dest="show_tqdm", action="store_true")
    parser.add_argument("--hide-tqdm", dest="show_tqdm", action="store_false")
    parser.add_argument("--auto-prime-bulk", dest="auto_prime_bulk", action="store_true")
    parser.add_argument("--no-auto-prime-bulk", dest="auto_prime_bulk", action="store_false")
    parser.add_argument(
        "--perf-log-path",
        default=None,
        help="Optional JSONL output path. Defaults to notebooks/logs/stirf_curve_calibration_<timestamp>.jsonl.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger = _configure_logging(verbose=bool(args.verbose))

    timezone_name = DEFAULT_CME_TIMEZONE if bool(args.cme_session) else str(args.timezone)
    timezone = ZoneInfo(timezone_name)
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    session_start = _parse_time(args.session_start)
    session_end = _parse_time(args.session_end)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else _default_perf_log_path()

    daily_buckets = build_daily_minute_buckets(
        start_date=start_date,
        end_date=end_date,
        session_start=session_start,
        session_end=session_end,
        freq=str(args.freq),
        timezone=timezone,
        cme_session=bool(args.cme_session),
    )
    total_requested = sum(len(bucket) for bucket in daily_buckets.values())
    logger.info(
        "Prepared %s business-day buckets covering %s timestamps; session_mode=%s timezone=%s perf_log=%s",
        len(daily_buckets),
        total_requested,
        "cme" if args.cme_session else "clock",
        timezone_name,
        perf_log_path,
    )

    mdp = IRSwapsMDP(source=str(args.source))
    request_options = {
        "n_jobs": int(args.n_jobs),
        "show_tqdm": bool(args.show_tqdm),
        "ignore_cache": bool(args.ignore_cache),
        "calibration_executor": str(args.calibration_executor),
        "auto_prime_bulk": bool(args.auto_prime_bulk),
        "stirf_fetch_max_workers": args.stirf_fetch_max_workers,
        "calibration_max_workers": args.calibration_max_workers,
        "cme_session": bool(args.cme_session),
        "timezone": timezone_name,
    }

    try:
        _, daily_results, summary = run_bucketed_calibration(
            curve_mdp=mdp,
            curve_name=str(args.curve_name),
            source=str(args.source),
            daily_buckets=daily_buckets,
            request_options=request_options,
            perf_log_path=perf_log_path,
            logger=logger,
            fail_fast=bool(args.fail_fast),
        )
    except Exception:
        logger.info("Performance log written to %s", perf_log_path)
        raise

    logger.info(
        "Run complete: business_days=%s successful_days=%s failed_days=%s returned=%s/%s elapsed=%.2fs",
        summary["business_days"],
        summary["successful_days"],
        summary["failed_days"],
        summary["returned_curves"],
        summary["requested_timestamps"],
        summary["total_elapsed_seconds"],
    )
    if daily_results:
        slowest = max(daily_results, key=lambda row: row.elapsed_seconds)
        logger.info(
            "Slowest bucket: trade_date=%s elapsed=%.2fs missing=%s",
            slowest.trade_date,
            slowest.elapsed_seconds,
            slowest.missing_curves,
        )
    logger.info("Performance log written to %s", perf_log_path)
    return 0 if summary["failed_days"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
