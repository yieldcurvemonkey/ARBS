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
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

import QuantLib as ql
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from BT.misc import ql_cal_date_range
from Caching.curve_store import CurveStore
from Caching.supabase_curve_sync import CURVE_INTRADAY_BLOCKS_TABLE, SupabaseCurveSync
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
DEFAULT_BACKFILL_BATCH_SIZE = 25


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
    return OrderedDict(
        iter_daily_minute_buckets(
            start_date=start_date,
            end_date=end_date,
            session_start=session_start,
            session_end=session_end,
            freq=freq,
            timezone=timezone,
            calendar=calendar,
            cme_session=cme_session,
        )
    )


def iter_daily_minute_buckets(
    *,
    start_date: dt.date,
    end_date: dt.date,
    session_start: dt.time,
    session_end: dt.time,
    freq: str,
    timezone: ZoneInfo,
    calendar: ql.Calendar | None = None,
    cme_session: bool = False,
) -> Iterator[tuple[dt.date, list[dt.datetime]]]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    if not cme_session and session_end < session_start:
        raise ValueError("session_end must be on or after session_start.")

    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)

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
            yield current, list(bucket)
        current += dt.timedelta(days=1)


def count_business_day_buckets(
    *,
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
) -> int:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    count = 0
    current = start_date
    while current <= end_date:
        if _is_business_day(current, cal):
            count += 1
        current += dt.timedelta(days=1)
    return count


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


def _supabase_engine_diagnostics() -> dict[str, Any]:
    from Caching import supabase_engine

    db_url = supabase_engine.get_database_url()
    safe_target = None
    if db_url:
        safe_target = db_url.split("@", 1)[-1]
    return {
        "supabase_enabled": bool(supabase_engine.SUPABASE_ENABLED),
        "database_target": safe_target,
    }


def _chunked(values: list[dt.date], batch_size: int) -> list[list[dt.date]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    return [
        values[idx : idx + batch_size]
        for idx in range(0, len(values), batch_size)
    ]


def _local_curve_dates_in_range(
    *,
    curve_name: str,
    start_date: dt.date,
    end_date: dt.date,
    store: CurveStore | None = None,
) -> list[dt.date]:
    active_store = store or CurveStore.default()
    return [
        trading_date
        for trading_date in active_store.available_dates(curve_name)
        if start_date <= trading_date <= end_date
    ]


def _remote_curve_dates_in_range(
    *,
    curve_name: str,
    start_date: dt.date,
    end_date: dt.date,
    sync: SupabaseCurveSync | None = None,
) -> list[dt.date]:
    active_sync = sync or SupabaseCurveSync.from_defaults()
    engine = getattr(active_sync, "_engine", None)
    if engine is None:
        return []

    from Caching.supabase_schema import ensure_schema
    from sqlalchemy import text

    if not ensure_schema(engine):
        return []

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT trading_date
                FROM {CURVE_INTRADAY_BLOCKS_TABLE}
                WHERE curve_name = :curve_name
                  AND trading_date BETWEEN :start_date AND :end_date
                ORDER BY trading_date
                """
            ),
            {
                "curve_name": curve_name,
                "start_date": start_date,
                "end_date": end_date,
            },
        ).fetchall()

    out: list[dt.date] = []
    for row in rows:
        value = getattr(row, "trading_date", row[0])
        if isinstance(value, dt.datetime):
            out.append(value.date())
        elif isinstance(value, dt.date):
            out.append(value)
        else:
            out.append(dt.date.fromisoformat(str(value)))
    return out


def inspect_curve_store_sync_status(
    *,
    curve_name: str,
    start_date: dt.date,
    end_date: dt.date,
    store: CurveStore | None = None,
    sync: SupabaseCurveSync | None = None,
) -> dict[str, Any]:
    local_dates = sorted(
        _local_curve_dates_in_range(
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
            store=store,
        )
    )
    remote_dates = sorted(
        _remote_curve_dates_in_range(
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
            sync=sync,
        )
    )
    remote_date_set = set(remote_dates)
    local_only_dates = [trading_date for trading_date in local_dates if trading_date not in remote_date_set]
    return {
        "curve_name": curve_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "local_dates": local_dates,
        "remote_dates": remote_dates,
        "local_days": len(local_dates),
        "remote_days": len(remote_dates),
        "local_only_days": len(local_only_dates),
        "local_only_dates": local_only_dates,
    }


def backfill_local_curve_store_to_supabase(
    *,
    curve_name: str,
    start_date: dt.date,
    end_date: dt.date,
    batch_size: int,
    rewrite_existing: bool,
    logger: logging.Logger,
    perf_log_path: Path,
    store: CurveStore | None = None,
    sync: SupabaseCurveSync | None = None,
    event_calendar: dict[dt.date, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    active_sync = sync or SupabaseCurveSync.from_defaults()
    engine = getattr(active_sync, "_engine", None)
    started_at = time.perf_counter()
    status = inspect_curve_store_sync_status(
        curve_name=curve_name,
        start_date=start_date,
        end_date=end_date,
        store=store,
        sync=active_sync,
    )

    local_dates = list(status["local_dates"])
    remote_date_set = set(status["remote_dates"])
    dates_to_push = local_dates if rewrite_existing else [
        trading_date for trading_date in local_dates if trading_date not in remote_date_set
    ]

    summary = {
        "event": "supabase_backfill_summary",
        "curve_name": curve_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rewrite_existing": bool(rewrite_existing),
        "batch_size": int(batch_size),
        "local_days": len(local_dates),
        "remote_days_before": int(status["remote_days"]),
        "queued_days": len(dates_to_push),
        "pushed_days": 0,
        "failed_days": 0,
        "status": "ok",
    }

    if engine is None:
        summary["status"] = "disabled"
        diagnostics = _supabase_engine_diagnostics()
        summary["diagnostics"] = diagnostics
        _write_perf_event(perf_log_path, summary)
        logger.info(
            "Supabase backfill skipped for %s: engine unavailable; local_days=%s remote_days=%s supabase_enabled=%s target=%s",
            curve_name,
            summary["local_days"],
            summary["remote_days_before"],
            diagnostics["supabase_enabled"],
            diagnostics["database_target"],
        )
        return summary

    if not dates_to_push:
        _write_perf_event(perf_log_path, summary)
        logger.info(
            "Supabase backfill not needed for %s: local_days=%s remote_days=%s rewrite_existing=%s",
            curve_name,
            summary["local_days"],
            summary["remote_days_before"],
            rewrite_existing,
        )
        return summary

    batches = _chunked(dates_to_push, batch_size)
    logger.info(
        "Supabase backfill starting for %s: local_days=%s remote_days=%s queued_days=%s batches=%s rewrite_existing=%s",
        curve_name,
        summary["local_days"],
        summary["remote_days_before"],
        summary["queued_days"],
        len(batches),
        rewrite_existing,
    )

    calendar = event_calendar or {}
    failed_dates: list[str] = []
    total_days = len(dates_to_push)
    processed_days = 0
    for batch_idx, batch in enumerate(batches, start=1):
        batch_success = 0
        batch_failure = 0
        for day_idx, trading_date in enumerate(batch, start=1):
            global_day_idx = processed_days + day_idx
            elapsed_before = time.perf_counter() - started_at
            logger.info(
                "Supabase backfill heartbeat for %s: starting day %s/%s trading_date=%s batch=%s/%s batch_day=%s/%s pushed=%s failed=%s elapsed=%.1fs",
                curve_name,
                global_day_idx,
                total_days,
                trading_date.isoformat(),
                batch_idx,
                len(batches),
                day_idx,
                len(batch),
                summary["pushed_days"],
                summary["failed_days"],
                elapsed_before,
            )
            day_started_at = time.perf_counter()
            day_status = "ok"
            try:
                pushed = bool(active_sync.push_day(curve_name, trading_date, event_calendar=calendar))
            except Exception as exc:
                pushed = False
                day_status = "error"
                batch_failure += 1
                failed_dates.append(trading_date.isoformat())
                logger.warning(
                    "Supabase backfill failed for %s/%s: %s",
                    curve_name,
                    trading_date.isoformat(),
                    exc,
                )

            if pushed:
                batch_success += 1
            elif day_status != "error":
                day_status = "skipped"
                batch_failure += 1
                failed_dates.append(trading_date.isoformat())

            summary["pushed_days"] += int(pushed)
            summary["failed_days"] += int(not pushed)
            elapsed_after = time.perf_counter() - started_at
            day_elapsed = time.perf_counter() - day_started_at
            remaining_days = total_days - global_day_idx
            _write_perf_event(
                perf_log_path,
                {
                    "event": "supabase_backfill_day",
                    "curve_name": curve_name,
                    "day_index": global_day_idx,
                    "day_count": total_days,
                    "batch_index": batch_idx,
                    "batch_count": len(batches),
                    "batch_day_index": day_idx,
                    "batch_day_count": len(batch),
                    "trading_date": trading_date.isoformat(),
                    "status": day_status,
                    "pushed": bool(pushed),
                    "pushed_days": summary["pushed_days"],
                    "failed_days": summary["failed_days"],
                    "remaining_days": remaining_days,
                    "day_elapsed_seconds": day_elapsed,
                    "elapsed_seconds": elapsed_after,
                },
            )
            logger.info(
                "Supabase backfill heartbeat for %s: completed day %s/%s trading_date=%s status=%s pushed=%s failed=%s remaining=%s day_elapsed=%.1fs total_elapsed=%.1fs",
                curve_name,
                global_day_idx,
                total_days,
                trading_date.isoformat(),
                day_status,
                summary["pushed_days"],
                summary["failed_days"],
                remaining_days,
                day_elapsed,
                elapsed_after,
            )

        processed_days += len(batch)
        _write_perf_event(
            perf_log_path,
            {
                "event": "supabase_backfill_batch",
                "curve_name": curve_name,
                "batch_index": batch_idx,
                "batch_count": len(batches),
                "batch_size": len(batch),
                "first_date": batch[0].isoformat(),
                "last_date": batch[-1].isoformat(),
                "success_days": batch_success,
                "failed_days": batch_failure,
            },
        )
        logger.info(
            "Supabase backfill batch %s/%s complete for %s: success=%s failure=%s first=%s last=%s",
            batch_idx,
            len(batches),
            curve_name,
            batch_success,
            batch_failure,
            batch[0].isoformat(),
            batch[-1].isoformat(),
        )

    if failed_dates:
        summary["status"] = "partial" if summary["pushed_days"] > 0 else "error"
        summary["failed_date_list"] = failed_dates

    _write_perf_event(perf_log_path, summary)
    return summary


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


def _flush_curve_store_pushes(*, logger: logging.Logger, timeout_seconds: float = 300.0) -> None:
    try:
        waited = CurveStore.default().wait_for_background_pushes(timeout=timeout_seconds)
        if waited > 0:
            logger.info("CurveStore Supabase sync flush complete after waiting on %s background push thread(s).", waited)
    except Exception:
        logger.warning("CurveStore Supabase sync flush failed.", exc_info=True)


def run_bucketed_calibration(
    *,
    curve_mdp: Any,
    curve_name: str,
    source: str,
    daily_buckets: OrderedDict[dt.date, list[dt.datetime]] | Iterable[tuple[dt.date, list[dt.datetime]]],
    request_options: dict[str, Any],
    perf_log_path: Path,
    logger: logging.Logger,
    fail_fast: bool,
    retain_all_curves: bool = False,
    release_runtime_state: bool = True,
    business_days: int | None = None,
) -> tuple[dict[Any, Any], list[DayCalibrationStats], dict[str, Any]]:
    all_curves: dict[Any, Any] = {}
    daily_results: list[DayCalibrationStats] = []
    if hasattr(daily_buckets, "items"):
        daily_bucket_iter = daily_buckets.items()
        expected_business_days = len(daily_buckets) if business_days is None else int(business_days)
    else:
        daily_bucket_iter = iter(daily_buckets)
        expected_business_days = None if business_days is None else int(business_days)

    _write_perf_event(
        perf_log_path,
        {
            "event": "run_start",
            "curve_name": curve_name,
            "source": source,
            "business_days": expected_business_days,
            "request_options": {
                key: value
                for key, value in request_options.items()
                if key != "timestamps"
            },
        },
    )

    run_started = time.perf_counter()
    processed_business_days = 0
    for trade_date, timestamps in daily_bucket_iter:
        processed_business_days += 1
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
        business_days=processed_business_days,
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
    parser.add_argument("--backfill-only", action="store_true", help="Only push existing local CurveStore days in range to Supabase; skip calibration.")
    parser.add_argument("--backfill-batch-size", type=int, default=DEFAULT_BACKFILL_BATCH_SIZE)
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(show_tqdm=True, auto_prime_bulk=True, backfill_local_cache=True, rewrite_existing_supabase=True)
    parser.add_argument("--show-tqdm", dest="show_tqdm", action="store_true")
    parser.add_argument("--hide-tqdm", dest="show_tqdm", action="store_false")
    parser.add_argument("--auto-prime-bulk", dest="auto_prime_bulk", action="store_true")
    parser.add_argument("--no-auto-prime-bulk", dest="auto_prime_bulk", action="store_false")
    parser.add_argument("--backfill-local-cache", dest="backfill_local_cache", action="store_true")
    parser.add_argument("--no-backfill-local-cache", dest="backfill_local_cache", action="store_false")
    parser.add_argument("--rewrite-existing-supabase", dest="rewrite_existing_supabase", action="store_true")
    parser.add_argument("--only-missing-supabase", dest="rewrite_existing_supabase", action="store_false")
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

    sync_status = inspect_curve_store_sync_status(
        curve_name=str(args.curve_name),
        start_date=start_date,
        end_date=end_date,
    )
    logger.info(
        "CurveStore sync status for %s [%s -> %s]: local_days=%s remote_days=%s local_only_days=%s",
        args.curve_name,
        start_date.isoformat(),
        end_date.isoformat(),
        sync_status["local_days"],
        sync_status["remote_days"],
        sync_status["local_only_days"],
    )
    _write_perf_event(
        perf_log_path,
        {
            "event": "supabase_backfill_status",
            "curve_name": str(args.curve_name),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "local_days": sync_status["local_days"],
            "remote_days": sync_status["remote_days"],
            "local_only_days": sync_status["local_only_days"],
        },
    )

    if bool(args.backfill_local_cache):
        backfill_summary = backfill_local_curve_store_to_supabase(
            curve_name=str(args.curve_name),
            start_date=start_date,
            end_date=end_date,
            batch_size=int(args.backfill_batch_size),
            rewrite_existing=bool(args.rewrite_existing_supabase),
            logger=logger,
            perf_log_path=perf_log_path,
        )
        logger.info(
            "Supabase backfill summary for %s: status=%s pushed_days=%s failed_days=%s queued_days=%s",
            args.curve_name,
            backfill_summary["status"],
            backfill_summary["pushed_days"],
            backfill_summary["failed_days"],
            backfill_summary["queued_days"],
        )

    if bool(args.backfill_only):
        logger.info("Backfill-only mode enabled; skipping calibration run.")
        logger.info("Performance log written to %s", perf_log_path)
        return 0

    business_days = count_business_day_buckets(
        start_date=start_date,
        end_date=end_date,
    )
    logger.info(
        "Prepared streaming run for %s business-day buckets across [%s -> %s]; intraday timestamps will be built and calibrated one trade date at a time; session_mode=%s timezone=%s perf_log=%s",
        business_days,
        start_date.isoformat(),
        end_date.isoformat(),
        "cme" if args.cme_session else "clock",
        timezone_name,
        perf_log_path,
    )
    daily_bucket_iter = iter_daily_minute_buckets(
        start_date=start_date,
        end_date=end_date,
        session_start=session_start,
        session_end=session_end,
        freq=str(args.freq),
        timezone=timezone,
        cme_session=bool(args.cme_session),
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
            daily_buckets=daily_bucket_iter,
            request_options=request_options,
            perf_log_path=perf_log_path,
            logger=logger,
            fail_fast=bool(args.fail_fast),
            business_days=business_days,
        )
    except Exception:
        _flush_curve_store_pushes(logger=logger)
        logger.info("Performance log written to %s", perf_log_path)
        raise

    _flush_curve_store_pushes(logger=logger)

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
