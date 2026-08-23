#!/usr/bin/env python
"""Unified STIRF curve backfill and live-service runner.

This script owns the common STIRF intraday workflow:
1. Pull market data from BARCHART.
2. Build/calibrate the requested IRS curve snapshots.
3. Persist raw curves into the CurveStore/local DB and configured L2 sync.
4. Compute common desk-tenor IRS timeseries from those snapshots.
5. Persist computed timeseries into the local/L2 stores.

Two primary modes are supported:
1. ``backfill``: expand a historical date range into intraday buckets and warm
   both raw curves and computed desk tenors one trade date at a time.
2. ``live-service``: resolve an incremental live window from the latest stored
   timestamp, then warm only the missing raw snapshots plus the requested
   computed tenor timeseries.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import logging
import os
import sys
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence
from zoneinfo import ZoneInfo

import QuantLib as ql
import pandas as pd

# Force line-buffered stderr/stdout so logs appear immediately under conda run.
if not os.environ.get("PYTHONUNBUFFERED"):
    os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from BT.misc import ql_cal_date_range
from Caching.curve_store import CurveStore
from Caching.supabase_curve_sync import CURVE_INTRADAY_BLOCKS_TABLE, SupabaseCurveSync
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from TB.barchart_irs_bulk import (
    build_bulk_request as _shared_build_bulk_request,
    curve_store_trading_date as _shared_curve_store_trading_date,
    normalize_timestamp_utc_minute as _shared_normalize_timestamp_utc_minute,
    read_existing_curve_store_timestamps as _shared_read_existing_curve_store_timestamps,
    safe_warm_raw_curves as _shared_safe_warm_raw_curves,
    select_missing_curve_store_timestamps as _shared_select_missing_curve_store_timestamps,
)


DEFAULT_SOURCE = "BARCHART_STIRF-RL"
DEFAULT_CURVE_NAME = "USD-SOFR-1D-Q12STIRT"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CME_TIMEZONE = "America/Chicago"
DEFAULT_SESSION_START = "07:00"
DEFAULT_SESSION_END = "17:00"
DEFAULT_FREQ = "1min"
DEFAULT_N_JOBS = 16
DEFAULT_CALIBRATION_EXECUTOR = "thread"
DEFAULT_LOG_DIR = REPO_ROOT / "notebooks" / "logs"
DEFAULT_CME_SESSION_OPEN = dt.time(17, 0)
DEFAULT_CME_SESSION_CLOSE = dt.time(16, 0)
DEFAULT_BACKFILL_BATCH_SIZE = 25
DEFAULT_CURVES = (DEFAULT_CURVE_NAME,)
DEFAULT_LIVE_SERVICE_N_JOBS = 16
DEFAULT_LAG_MINUTES = 15
DEFAULT_WINDOW_TEMPLATE = "cme_trading_day"
DEFAULT_TS_BASE_DIR = "./data/ts"
DEFAULT_TS_ROW_GROUP_SIZE = 256_000
DEFAULT_TS_COMPRESSION = "zstd"
DEFAULT_USE_DUCKDB = False
_BASE_OUTRIGHT_TENORS = tuple(
    [f"{months}M" for months in range(1, 24)]
    + [f"{years}Y" for years in range(1, 41)]
)
_STIRT_OUTRIGHT_TENORS = tuple([f"{months}M" for months in range(1, 12)] + ["1Y", "18M", "22M", "2Y", "30M", "33M", "3Y"])
_STIRT_MAX_MATURITY_YEARS = 3
_STIRT_FORWARD_START_TENORS = (
    # 1M fwd
    "1M3M", "1M6M", "1M1Y", "1M18M", "1M2Y",
    # 2M fwd
    "2M3M", "2M6M", "2M1Y", "2M18M", "2M2Y",
    # 3M fwd
    "3M3M", "3M6M", "3M1Y", "3M18M", "3M2Y",
    # 6M fwd
    "6M3M", "6M6M", "6M1Y", "6M18M", "6M2Y",
    # 9M fwd
    "9M3M", "9M6M", "9M1Y", "9M18M",
    # 1Y fwd
    "1Y3M", "1Y6M", "1Y1Y", "1Y18M", "1Y2Y",
    # 18M fwd
    "18M3M", "18M6M", "18M1Y", "18M18M",
    # 2Y fwd
    "2Y3M", "2Y6M", "2Y1Y",
)
_STIRT_IMM_SPANS = (1, 2, 4)  # 1=3M gap, 2=6M gap, 4=1Y gap
_STIRT_IMM_HORIZON_COUNT = 13
_STIRT_DEFAULT_RELATIVE_IMM_TENORS = tuple(
    f"IMM_{idx}xIMM_{idx + 1}" for idx in range(1, 13)
)
_MIXED_STIRT_SPOT_TENORS = tuple(f"{m}M" for m in range(1, 19))
_MIXED_STIRT_FORWARD_TENORS = ("1Y", "1Y1Y", "2Y1Y")
_MIXED_STIRT_FOMC_COUNT = 12
_FORWARD_START_TENORS = _STIRT_FORWARD_START_TENORS
_GENERIC_CB_FORWARD_START_TENORS = (
    "1Y1Y",
    "1Y2Y",
    "2Y1Y",
)
_CB_TOKEN_PREFIX = {"FOMC": "fomc"}
_IMM_MONTH_CODE = {
    3: "H",
    6: "M",
    9: "U",
    12: "Z",
}


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


def _get_rss_mb() -> float:
    """Return current process RSS in MB. Returns 0.0 if unavailable."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import resource
            # maxrss is in KB on Linux, bytes on macOS
            rusage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return rusage / 1024 if sys.platform != "darwin" else rusage / (1024 * 1024)
        except Exception:
            return 0.0


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration like '2h03m' or '45s'."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m{seconds % 60:02.0f}s"
    hours = minutes / 60
    return f"{hours:.0f}h{minutes % 60:02.0f}m"


@dataclass
class BackfillProgress:
    """Tracks cumulative progress across a multi-day backfill run."""

    curve_name: str
    total_days: int
    skipped_days: int
    processed_days: int = 0
    calibration_ok: int = 0
    calibration_error: int = 0
    timeseries_ok: int = 0
    timeseries_partial: int = 0
    failed_tenors: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def record_calibration(self, *, status: str) -> None:
        self.processed_days += 1
        if status == "ok":
            self.calibration_ok += 1
        else:
            self.calibration_error += 1

    def record_timeseries(self, *, status: str, failed_tenors: list[str]) -> None:
        if status == "ok":
            self.timeseries_ok += 1
        elif status in ("partial", "error"):
            self.timeseries_partial += 1
        self.failed_tenors.extend(failed_tenors)

    @property
    def pct_complete(self) -> float:
        if self.total_days == 0:
            return 100.0
        return round((self.skipped_days + self.processed_days) / self.total_days * 100, 1)

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    @property
    def rate_days_per_min(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1 or self.processed_days == 0:
            return 0.0
        return self.processed_days / (elapsed / 60)

    @property
    def eta_seconds(self) -> float:
        rate = self.rate_days_per_min
        if rate <= 0:
            return 0.0
        remaining = self.total_days - self.skipped_days - self.processed_days
        return max(0.0, remaining / rate * 60)

    def format_heartbeat(self) -> str:
        done = self.skipped_days + self.processed_days
        mem = _get_rss_mb()
        parts = [
            f"day {done}/{self.total_days} ({self.pct_complete}%)",
            f"elapsed={_format_duration(self.elapsed_seconds)}",
            f"eta={_format_duration(self.eta_seconds)}",
            f"rate={self.rate_days_per_min:.1f} days/min",
        ]
        if mem > 0:
            parts.append(f"mem={mem:.0f}MB")
        parts.append(
            f"calibration=ok({self.calibration_ok}) error({self.calibration_error})"
        )
        parts.append(
            f"timeseries=ok({self.timeseries_ok}) partial({self.timeseries_partial})"
            f" failed_tenors={len(self.failed_tenors)}"
        )
        return f"Backfill progress for {self.curve_name}: {' '.join(parts)}"

    def to_perf_event(self) -> dict[str, Any]:
        return {
            "event": "backfill_heartbeat",
            "curve_name": self.curve_name,
            "total_days": self.total_days,
            "skipped_days": self.skipped_days,
            "processed_days": self.processed_days,
            "pct_complete": self.pct_complete,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "eta_seconds": round(self.eta_seconds, 2),
            "rate_days_per_min": round(self.rate_days_per_min, 2),
            "rss_mb": round(_get_rss_mb(), 1),
            "calibration_ok": self.calibration_ok,
            "calibration_error": self.calibration_error,
            "timeseries_ok": self.timeseries_ok,
            "timeseries_partial": self.timeseries_partial,
            "failed_tenor_count": len(self.failed_tenors),
        }


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
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logging.root.addHandler(handler)
    logging.root.setLevel(level)
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
    max_tasks_per_child: int | None = None,
) -> dict[str, Any]:
    return _shared_build_bulk_request(
        curve_name=curve_name,
        timestamps=timestamps,
        n_jobs=n_jobs,
        show_tqdm=show_tqdm,
        ignore_cache=ignore_cache,
        calibration_executor=calibration_executor,
        auto_prime_bulk=auto_prime_bulk,
        stirf_fetch_max_workers=stirf_fetch_max_workers,
        calibration_max_workers=calibration_max_workers,
        max_tasks_per_child=max_tasks_per_child,
    )


def _write_perf_event(perf_log_path: Path | None, payload: dict[str, Any]) -> None:
    if perf_log_path is None:
        return
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


def _computed_ts_stores_for_builder(ts_builder: Any | None) -> list[Any]:
    if ts_builder is None:
        return []

    candidates: list[Any] = []
    for attr_name in ("_routers", "_specialized_router_cache", "_generic_router_cache"):
        mapping = getattr(ts_builder, attr_name, None)
        if isinstance(mapping, dict):
            candidates.extend(mapping.values())

    stores: list[Any] = []
    seen: set[int] = set()
    for candidate in candidates:
        store = getattr(candidate, "_computed_ts_store", None)
        if store is None:
            continue
        store_id = id(store)
        if store_id in seen:
            continue
        seen.add(store_id)
        stores.append(store)
    return stores


def _probe_completed_days(
    *,
    raw_complete_dates: set[dt.date],
    ts_complete_dates: set[dt.date],
    skip_timeseries_warm: bool,
) -> set[dt.date]:
    """Return dates fully completed (raw curves + optional timeseries)."""
    if skip_timeseries_warm:
        return set(raw_complete_dates)
    return raw_complete_dates & ts_complete_dates


def _probe_ts_completed_dates(
    *,
    ts_builder: Any | None,
    curve_name: str,
    source: str,
    sentinel_tenor: str,
    start_date: dt.date,
    end_date: dt.date,
) -> set[dt.date]:
    """Probe DuckDB computed TS cache for dates with cached sentinel tenor."""
    if ts_builder is None:
        return set()

    stores = _computed_ts_stores_for_builder(ts_builder)
    if not stores:
        return set()

    # Build sentinel symbol: IRS::{source}::{curve_name}::{fingerprint}
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    sentinel_query = UnifiedQuery(
        curve=curve_name,
        tenor=sentinel_tenor,
        value=UnifiedValue.IRS_RATE,
    )
    # Convert to legacy query and get fingerprint
    legacy_queries = sentinel_query.return_query()
    if not legacy_queries:
        return set()
    legacy_item = legacy_queries[0].to_legacy()
    from TB.IRSwapsTB import _query_fingerprint
    fingerprint = _query_fingerprint(legacy_item)
    sentinel_symbol = f"IRS::{source}::{curve_name}::{fingerprint}"

    # Probe each store for the sentinel symbol
    all_dates: set[dt.date] = set()
    for store in stores:
        duckdb_cache = getattr(store, "_duckdb_cache", None)
        if duckdb_cache is None:
            continue
        available_fn = getattr(duckdb_cache, "available_dates", None)
        if not callable(available_fn):
            continue
        try:
            all_dates |= available_fn(sentinel_symbol, start_date, end_date)
        except Exception:
            pass
    return all_dates


def _flush_computed_ts_pushes(
    *,
    ts_builder: Any | None,
    logger: logging.Logger,
    timeout_seconds: float = 300.0,
) -> None:
    stores = _computed_ts_stores_for_builder(ts_builder)
    if not stores:
        return

    total_waited = 0
    for store in stores:
        wait_fn = getattr(store, "wait_for_background_pushes", None)
        if not callable(wait_fn):
            continue
        try:
            total_waited += int(wait_fn(timeout=timeout_seconds) or 0)
        except Exception:
            logger.warning("Computed TS Supabase sync flush failed.", exc_info=True)

    if total_waited > 0:
        logger.info(
            "Computed TS Supabase sync flush complete after waiting on %s background push task(s) across %s store(s).",
            total_waited,
            len(stores),
        )


def _argparse_date(value: str) -> dt.date:
    try:
        return _parse_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date '{value}'. Expected YYYY-MM-DD.") from exc


def _argparse_time(value: str) -> dt.time:
    try:
        return _parse_time(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid time '{value}'. Expected HH:MM or HH:MM:SS.") from exc


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _resolve_curve_names(values: Sequence[str] | None) -> list[str]:
    return _dedupe_preserve_order(values or list(DEFAULT_CURVES))


def _resolve_dates(
    *,
    explicit_dates: Sequence[dt.date],
    start_date: dt.date | None,
    end_date: dt.date | None,
    default_date: dt.date,
) -> list[dt.date]:
    if explicit_dates:
        return sorted(set(explicit_dates))
    if start_date is None and end_date is None:
        return [default_date]
    if start_date is None or end_date is None:
        raise ValueError("Both --start-date and --end-date are required when either is provided.")
    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date.")

    out: list[dt.date] = []
    current = start_date
    while current <= end_date:
        out.append(current)
        current += dt.timedelta(days=1)
    return out


def _current_trading_date(*, now_utc: dt.datetime | None = None) -> dt.date:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)
    now_chi = now_utc.astimezone(ZoneInfo(DEFAULT_CME_TIMEZONE))
    if now_chi.hour >= DEFAULT_CME_SESSION_OPEN.hour:
        return now_chi.date() + dt.timedelta(days=1)
    return now_chi.date()


def _window_for_date(
    trading_date: dt.date,
    *,
    window_template: str,
    timezone_name: str,
    start_time: dt.time,
    end_time: dt.time,
) -> tuple[dt.datetime, dt.datetime]:
    if window_template == "cme_trading_day":
        chi = ZoneInfo(DEFAULT_CME_TIMEZONE)
        start = dt.datetime.combine(trading_date - dt.timedelta(days=1), DEFAULT_CME_SESSION_OPEN, tzinfo=chi)
        end = dt.datetime.combine(trading_date, DEFAULT_CME_SESSION_CLOSE, tzinfo=chi)
        return start, end

    if window_template == "nyc_rth":
        timezone_name = DEFAULT_TIMEZONE
        start_time = _parse_time(DEFAULT_SESSION_START)
        end_time = _parse_time(DEFAULT_SESSION_END)

    tz = ZoneInfo(timezone_name)
    start = dt.datetime.combine(trading_date, start_time, tzinfo=tz)
    end = dt.datetime.combine(trading_date, end_time, tzinfo=tz)
    if end < start:
        raise ValueError("Custom window requires --end-time to be on or after --start-time.")
    return start, end


def _floor_to_minute(value: dt.datetime) -> dt.datetime:
    return value.replace(second=0, microsecond=0)


def _normalize_timestamp_utc_minute(value: Any) -> dt.datetime | None:
    return _shared_normalize_timestamp_utc_minute(value)


def _curve_store_trading_date(value: dt.datetime) -> dt.date:
    return _shared_curve_store_trading_date(value)


def _cap_end_at_now(
    start: dt.datetime,
    end: dt.datetime,
    *,
    now_utc: dt.datetime | None = None,
    delay_minutes: int = DEFAULT_LAG_MINUTES,
) -> tuple[dt.datetime, dt.datetime] | None:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = _floor_to_minute(
        now_utc.astimezone(start.tzinfo or dt.timezone.utc) - dt.timedelta(minutes=int(delay_minutes))
    )
    capped_end = min(end, now_local)
    if capped_end < start:
        return None
    return start, capped_end


def _build_minute_timestamps(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    if end < start:
        return []
    out: list[dt.datetime] = []
    current = start
    step = dt.timedelta(minutes=1)
    while current <= end:
        out.append(current)
        current += step
    return out


def _curve_reference_id(curve_name: str) -> str:
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CURVE_TO_CB

    curve_upper = str(curve_name or "").strip().upper()
    for candidate in sorted(_CURVE_TO_CB, key=len, reverse=True):
        if curve_upper == candidate or curve_upper.startswith(candidate) or candidate in curve_upper:
            return candidate
    return curve_upper


def _is_stirt_curve(curve_name: str) -> bool:
    return "STIRT" in str(curve_name or "").upper()


def _is_mixed_stirt_curve(curve_name: str) -> bool:
    upper = str(curve_name or "").upper()
    return "STIRT" in upper and "XM" in upper


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if hasattr(value, "to_pydatetime"):
        py_value = value.to_pydatetime()
        return py_value.date() if isinstance(py_value, dt.datetime) else py_value
    year = getattr(value, "year", None)
    month = getattr(value, "month", None)
    day = getattr(value, "day", None)
    if year is None or month is None or day is None:
        raise TypeError(f"Cannot coerce {type(value)!r} to date.")
    return dt.date(int(year), int(month), int(day))


def _next_imm_dates(as_of: dt.date, *, count: int) -> list[dt.date]:
    from rateslib.scheduling import next_imm

    imm = dt.datetime.combine(as_of + dt.timedelta(days=1), dt.time())
    out: list[dt.date] = []
    for _ in range(max(0, int(count))):
        imm_date = _as_date(next_imm(imm))
        out.append(imm_date)
        imm = dt.datetime.combine(imm_date, dt.time())
    return out


def _imm_code_for_date(value: dt.date) -> str:
    date_value = _as_date(value)
    return f"{_IMM_MONTH_CODE[date_value.month]}{date_value.year % 100:02d}"


def _add_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year + int(years))
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + int(years))


def _resolve_imm_token(token: str, ref_date: dt.date) -> dt.date:
    from rateslib.scheduling import get_imm, next_imm

    imm_token = str(token).strip().upper()
    if not imm_token.startswith("IMM_"):
        raise ValueError(f"IMM tenor token required, got {token!r}")

    suffix = imm_token.split("IMM_", 1)[1]
    if suffix.isnumeric():
        offset = int(suffix) - 1
        imm = dt.datetime.combine(ref_date + dt.timedelta(days=1), dt.time())
        for _ in range(offset + 1):
            imm = next_imm(imm)
        return _as_date(imm)

    return _as_date(get_imm(code=suffix))


def _stirt_tenor_maturity_date(curve_name: str, tenor: str, *, anchor_date: dt.date) -> dt.date | None:
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

    tenor_token = str(tenor or "").strip()
    if not tenor_token:
        return None

    if tenor_token.upper().startswith("IMM_") and "X" in tenor_token.upper():
        try:
            imm_date_token, mat_date_token = tenor_token.upper().split("X", 1)
            _ = _resolve_imm_token(imm_date_token, anchor_date)
            return _resolve_imm_token(mat_date_token, anchor_date)
        except Exception:
            return None

    try:
        cb_dates = resolve_central_bank_tenor(
            _curve_reference_id(curve_name),
            tenor_token,
            as_of=anchor_date,
        )
    except Exception:
        cb_dates = None
    if cb_dates is not None:
        return _as_date(cb_dates[1])

    return None


def _relative_imm_pair_tenors(*, max_imm_index: int, spans: Sequence[int]) -> list[str]:
    tenors: list[str] = []
    for span in spans:
        for start_idx in range(1, max_imm_index - int(span) + 1):
            tenors.append(f"IMM_{start_idx}xIMM_{start_idx + int(span)}")
    return tenors


def _explicit_imm_pair_tenors(*, as_of: dt.date, horizon_count: int, spans: Sequence[int]) -> list[str]:
    imm_dates = _next_imm_dates(as_of, count=horizon_count)
    imm_codes = [_imm_code_for_date(d) for d in imm_dates]
    tenors: list[str] = []
    for span in spans:
        for offset in range(0, len(imm_codes) - int(span)):
            tenors.append(f"IMM_{imm_codes[offset]}xIMM_{imm_codes[offset + int(span)]}")
    return tenors


def _resolvable_fomc_ranks(curve_name: str, anchor_date: dt.date) -> int:
    """How many ranked FOMC tenors the published calendar can actually answer.

    ``_MIXED_STIRT_FOMC_COUNT`` is 12 and the FOMC calendar does not always
    reach twelve meetings ahead. ``resolve_central_bank_tenor`` RAISES past the
    end of it, and the pricing loop catches that per (tenor, timestamp) — so the
    grid asked for a tenor it could never have, once per session minute.

    Measured on the 2026-08-21 run: **1,381 pricing failures**, all of them
    ``fomc_12``, one per minute of the session, on
    ``USD-OIS-Q12xM12STIRT-SERFFX-MIX23``. The curve then reported
    ``ts_cols=44 ts_failed=0`` — the failures never reached the summary, so this
    had been running nightly and looked clean.

    Asking the resolver rather than reimplementing its arithmetic: it is the same
    function the pricer will call, so the count cannot disagree with it. Ranks
    are contiguous (rank N is the Nth meeting at or after ``as_of``), so the
    first failure ends the walk.

    The anchor is the run's, not the trade date's, and that direction is safe:
    an earlier trade date has MORE meetings ahead of it, never fewer.
    """
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor

    curve_id = _curve_reference_id(curve_name)
    usable = 0
    for rank in range(1, _MIXED_STIRT_FOMC_COUNT + 1):
        try:
            if resolve_central_bank_tenor(curve_id, f"fomc_{rank}", as_of=anchor_date) is None:
                break
        except Exception:  # noqa: BLE001 - the resolver raises past the calendar
            break
        usable = rank
    if usable < _MIXED_STIRT_FOMC_COUNT:
        # Module logger: this helper is called from tenor resolution, which has
        # no `logger` parameter threaded through it.
        logging.getLogger(__name__).info(
            "FOMC grid for %s capped at %d of %d as of %s: the published calendar "
            "reaches no further, and the ranks past it fail once per session minute.",
            curve_name, usable, _MIXED_STIRT_FOMC_COUNT, anchor_date.isoformat(),
        )
    return usable


def _default_tenors_for_curve(curve_name: str, *, anchor_date: dt.date | None = None) -> list[str]:
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_for_curve

    if anchor_date is None:
        anchor_date = dt.date.today()

    base = list(_BASE_OUTRIGHT_TENORS)
    if _is_mixed_stirt_curve(curve_name):
        tenors = list(_STIRT_DEFAULT_RELATIVE_IMM_TENORS)
        tenors.extend(
            f"fomc_{rank}"
            for rank in range(1, _resolvable_fomc_ranks(curve_name, anchor_date) + 1)
        )
        tenors.extend(_MIXED_STIRT_SPOT_TENORS)
        tenors.extend(_MIXED_STIRT_FORWARD_TENORS)
        return _dedupe_preserve_order(tenors)
    if _is_stirt_curve(curve_name):
        return list(_STIRT_DEFAULT_RELATIVE_IMM_TENORS)

    forward_starts = list(_FORWARD_START_TENORS)
    cb_name = central_bank_for_curve(_curve_reference_id(curve_name))
    if cb_name in _CB_TOKEN_PREFIX:
        meeting_prefix = _CB_TOKEN_PREFIX[cb_name]
        return _dedupe_preserve_order(
            base
            + [f"{meeting_prefix}_{rank}" for rank in range(1, 25)]
            + list(_GENERIC_CB_FORWARD_START_TENORS)
        )
    return _dedupe_preserve_order(base + forward_starts[:37])


def _resolve_curve_store_name(mdp: Any, curve_name: str) -> str:
    builder = mdp._get_curve_store_builder() if hasattr(mdp, "_get_curve_store_builder") else None
    if hasattr(mdp, "_resolve_curve_store_curve_name"):
        try:
            return str(
                mdp._resolve_curve_store_curve_name(
                    requested_curve_name=curve_name,
                    kwargs={},
                    builder=builder,
                )
            )
        except Exception:
            pass
    return str(curve_name)


def _latest_curve_store_timestamp(store: Any, curve_name: str) -> dt.datetime | None:
    try:
        trading_dates = list(store.available_dates(curve_name))
    except Exception:
        return None

    for trading_date in reversed(trading_dates):
        try:
            df = store.read_raw_nodes(curve_name, start=trading_date, end=trading_date)
        except Exception:
            continue
        if df is None or df.empty or "timestamp_utc" not in df.columns:
            continue
        ts_series = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dropna()
        if ts_series.empty:
            continue
        return ts_series.max().to_pydatetime()
    return None


def _read_existing_curve_store_timestamps(
    store: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
) -> set[dt.datetime]:
    return _shared_read_existing_curve_store_timestamps(
        store,
        curve_name=curve_name,
        timestamps=timestamps,
    )


def _select_missing_curve_store_timestamps(
    store: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
) -> list[dt.datetime]:
    return _shared_select_missing_curve_store_timestamps(
        store,
        curve_name=curve_name,
        timestamps=timestamps,
    )


def _resolve_incremental_timestamp_range(
    *,
    curve_name: str,
    mdp: Any,
    ts_builder: Any,
    window_template: str,
    timezone_name: str,
    start_time: dt.time,
    end_time: dt.time,
    now_utc: dt.datetime | None = None,
    delay_minutes: int = DEFAULT_LAG_MINUTES,
) -> list[dt.datetime]:
    if now_utc is None:
        now_utc = dt.datetime.now(dt.timezone.utc)

    store_curve_name = _resolve_curve_store_name(mdp, curve_name)
    latest_timestamp = _latest_curve_store_timestamp(mdp._get_curve_store(), store_curve_name)

    if latest_timestamp is None:
        default_date = (
            _current_trading_date(now_utc=now_utc)
            if window_template == "cme_trading_day"
            else now_utc.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        )
        window = _cap_end_at_now(
            *_window_for_date(
                default_date,
                window_template=window_template,
                timezone_name=timezone_name,
                start_time=start_time,
                end_time=end_time,
            ),
            now_utc=now_utc,
            delay_minutes=delay_minutes,
        )
        if window is None:
            return []
        start, end = window
    else:
        start = _floor_to_minute(latest_timestamp)
        end = _floor_to_minute(
            now_utc.astimezone(start.tzinfo or dt.timezone.utc) - dt.timedelta(minutes=int(delay_minutes))
        )
        if end < start:
            return []

    raw_timestamps = _build_minute_timestamps(start, end)
    if not raw_timestamps:
        return []

    filtered = ts_builder._prepare_product_intraday_timestamps(
        product="IRS",
        mdp=mdp,
        start=start,
        end=end,
        freq=None,
        timestamps=raw_timestamps,
    )
    return filtered if filtered is not None else raw_timestamps


def _concat_timeseries_frames(frames: Sequence[Any]) -> Any:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0]
    out = pd.concat(non_empty, axis=1)
    return out.loc[:, ~out.columns.duplicated(keep="last")].sort_index()


def _build_timeseries_builder(
    *,
    mdp: Any,
    show_tqdm: bool,
    use_duckdb: bool,
    ts_base_dir: str,
    ts_row_group_size: int,
    ts_compression: str,
) -> Any:
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    return TimeseriesBuilder(
        irswaps_tb=IRSwapsTB(
            mdp=mdp,
            show_tqdm=show_tqdm,
            use_duckdb=use_duckdb,
            ts_base_dir=ts_base_dir,
            ts_row_group_size=ts_row_group_size,
            ts_compression=ts_compression,
        )
    )


def _safe_warm_raw_curves(
    mdp: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
    ignore_cache: bool,
    n_jobs: int,
    calibration_executor: str,
    show_tqdm: bool = False,
    auto_prime_bulk: bool = True,
    stirf_fetch_max_workers: int | None = None,
    calibration_max_workers: int | None = None,
    logger: logging.Logger | None = None,
) -> tuple[int, list[dt.datetime]]:
    return _shared_safe_warm_raw_curves(
        mdp,
        curve_name=curve_name,
        timestamps=timestamps,
        ignore_cache=ignore_cache,
        n_jobs=n_jobs,
        calibration_executor=calibration_executor,
        show_tqdm=show_tqdm,
        auto_prime_bulk=auto_prime_bulk,
        stirf_fetch_max_workers=stirf_fetch_max_workers,
        calibration_max_workers=calibration_max_workers,
        logger=logger,
    )


def _safe_warm_timeseries(
    ts_builder: Any,
    *,
    start: dt.datetime,
    end: dt.datetime,
    queries: Sequence[Any],
    n_jobs: int,
    ignore_cache: bool,
    timestamps: Sequence[dt.datetime],
    mdps: dict[str, Any],
    curve_name: str,
    logger: logging.Logger | None = None,
) -> tuple[Any, list[str]]:
    failures: list[str] = []
    query_list = list(queries)
    if not query_list:
        return pd.DataFrame(), failures

    def _run(batch: Sequence[Any], *, depth: int = 0) -> Any:
        batch_list = list(batch)
        try:
            return ts_builder.get_timeseries(
                start=start,
                end=end,
                queries=batch_list,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=None,
                timestamps=list(timestamps),
                mdps=mdps,
            )
        except Exception as exc:
            if len(batch_list) == 1:
                tenor = str(getattr(batch_list[0], "tenor", "<unknown>"))
                failures.append(tenor)
                if logger is not None:
                    logger.warning("TS %s failed for tenor=%s (%s)", curve_name, tenor, exc)
                return pd.DataFrame()
            if depth == 0 and logger is not None:
                logger.warning(
                    "TS %s failed for %s tenors (%s); retrying in smaller batches.",
                    curve_name,
                    len(batch_list),
                    exc,
                )
            midpoint = max(1, len(batch_list) // 2)
            left = _run(batch_list[:midpoint], depth=depth + 1)
            right = _run(batch_list[midpoint:], depth=depth + 1)
            return _concat_timeseries_frames([left, right])

    return _run(query_list), failures


def _warm_timeseries_window(
    *,
    curve_name: str,
    timestamps: Sequence[dt.datetime],
    explicit_tenors: Sequence[str],
    ts_builder: Any,
    mdp: Any,
    n_jobs: int,
    ignore_cache: bool,
    perf_log_path: Path | None,
    logger: logging.Logger,
    label: str,
) -> dict[str, Any]:
    if not timestamps:
        summary = {
            "event": "timeseries_result",
            "curve_name": curve_name,
            "label": label,
            "status": "skipped",
            "rows": 0,
            "cols": 0,
            "tenor_count": 0,
            "failed_tenors": [],
        }
        _write_perf_event(perf_log_path, summary)
        return summary

    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    active_timestamps = list(timestamps)
    anchor_date = active_timestamps[0].date()
    curve_tenors = _dedupe_preserve_order(explicit_tenors) or _default_tenors_for_curve(curve_name, anchor_date=anchor_date)
    queries = [
        UnifiedQuery(
            curve=curve_name,
            tenor=tenor,
            value=UnifiedValue.IRS_RATE,
        )
        for tenor in curve_tenors
    ]
    started = time.perf_counter()
    df, failed_tenors = _safe_warm_timeseries(
        ts_builder,
        start=active_timestamps[0],
        end=active_timestamps[-1],
        queries=queries,
        n_jobs=n_jobs,
        ignore_cache=ignore_cache,
        timestamps=active_timestamps,
        mdps={"IRS": mdp},
        curve_name=curve_name,
        logger=logger,
    )
    elapsed = time.perf_counter() - started
    status = "ok"
    if failed_tenors:
        status = "partial" if not df.empty else "error"
    summary = {
        "event": "timeseries_result",
        "curve_name": curve_name,
        "label": label,
        "status": status,
        "rows": len(df),
        "cols": len(df.columns),
        "tenor_count": len(curve_tenors),
        "failed_tenors": list(failed_tenors),
        "elapsed_seconds": elapsed,
        "first_timestamp": _format_dt(active_timestamps[0]),
        "last_timestamp": _format_dt(active_timestamps[-1]),
    }
    _write_perf_event(perf_log_path, summary)
    logger.info(
        "Timeseries warm complete for %s [%s]: status=%s rows=%s cols=%s failed_tenors=%s elapsed=%.2fs",
        curve_name,
        label,
        status,
        summary["rows"],
        summary["cols"],
        len(failed_tenors),
        elapsed,
    )
    return summary


def _run_live_service_window(
    *,
    curve_name: str,
    curve_timestamps: Sequence[dt.datetime],
    timeseries_timestamps: Sequence[dt.datetime],
    explicit_tenors: Sequence[str],
    mdp: Any,
    ts_builder: Any,
    n_jobs: int,
    calibration_executor: str,
    curve_ignore_cache: bool,
    timeseries_ignore_cache: bool,
    show_tqdm: bool,
    auto_prime_bulk: bool,
    stirf_fetch_max_workers: int | None,
    calibration_max_workers: int | None,
    skip_curve_warm: bool,
    skip_timeseries_warm: bool,
    perf_log_path: Path | None,
    logger: logging.Logger,
    label: str,
) -> dict[str, Any]:
    if not curve_timestamps and not timeseries_timestamps:
        summary = {
            "event": "service_window",
            "curve_name": curve_name,
            "label": label,
            "status": "skipped",
            "curve_requested": 0,
            "curve_ready": 0,
            "curve_failed_timestamps": [],
            "timeseries_rows": 0,
            "timeseries_cols": 0,
            "timeseries_failed_tenors": [],
        }
        _write_perf_event(perf_log_path, summary)
        logger.info("Skipping %s [%s]: no timestamps to warm.", curve_name, label)
        return summary

    curve_failed_timestamps: list[dt.datetime] = []
    curve_ready = 0
    curve_status = "skipped"
    if not skip_curve_warm and curve_timestamps:
        logger.info(
            "Warming %s raw curves for %s [%s] (executor=%s, n_jobs=%s)...",
            len(curve_timestamps),
            curve_name,
            label,
            calibration_executor,
            n_jobs,
        )
        curve_ready, curve_failed_timestamps = _safe_warm_raw_curves(
            mdp,
            curve_name=curve_name,
            timestamps=curve_timestamps,
            ignore_cache=curve_ignore_cache,
            n_jobs=n_jobs,
            calibration_executor=calibration_executor,
            show_tqdm=show_tqdm,
            auto_prime_bulk=auto_prime_bulk,
            stirf_fetch_max_workers=stirf_fetch_max_workers,
            calibration_max_workers=calibration_max_workers,
            logger=logger,
        )
        if curve_failed_timestamps:
            curve_status = "partial" if curve_ready > 0 else "error"
        else:
            curve_status = "ok"
    elif not skip_curve_warm:
        logger.info("Raw curve warm skipped for %s [%s]: requested window already present in CurveStore.", curve_name, label)

    ts_summary = {
        "rows": 0,
        "cols": 0,
        "failed_tenors": [],
        "status": "skipped",
    }
    if not skip_timeseries_warm:
        ts_summary = _warm_timeseries_window(
            curve_name=curve_name,
            timestamps=timeseries_timestamps,
            explicit_tenors=explicit_tenors,
            ts_builder=ts_builder,
            mdp=mdp,
            n_jobs=n_jobs,
            ignore_cache=timeseries_ignore_cache,
            perf_log_path=perf_log_path,
            logger=logger,
            label=label,
        )

    succeeded_curve = skip_curve_warm or not curve_timestamps or curve_ready > 0 or len(curve_failed_timestamps) < len(curve_timestamps)
    succeeded_ts = skip_timeseries_warm or not timeseries_timestamps or ts_summary["status"] in {"ok", "partial"}
    status = "ok"
    if not (succeeded_curve and succeeded_ts):
        status = "error"
    elif curve_failed_timestamps or ts_summary["status"] == "partial":
        status = "partial"
    summary = {
        "event": "service_window",
        "curve_name": curve_name,
        "label": label,
        "status": status,
        "curve_status": curve_status,
        "curve_requested": len(curve_timestamps),
        "curve_ready": curve_ready,
        "curve_failed_timestamps": [timestamp.isoformat() for timestamp in curve_failed_timestamps],
        "timeseries_status": ts_summary["status"],
        "timeseries_rows": int(ts_summary["rows"]),
        "timeseries_cols": int(ts_summary["cols"]),
        "timeseries_failed_tenors": list(ts_summary["failed_tenors"]),
    }
    _write_perf_event(perf_log_path, summary)
    logger.info(
        "Service warm complete for %s [%s]: status=%s curve_ready=%s/%s ts_rows=%s ts_cols=%s ts_failed=%s",
        curve_name,
        label,
        status,
        curve_ready,
        len(curve_timestamps),
        summary["timeseries_rows"],
        summary["timeseries_cols"],
        len(summary["timeseries_failed_tenors"]),
    )
    return summary


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
    day_callback: Callable[[dt.date, list[dt.datetime], dict[Any, Any], DayCalibrationStats], None] | None = None,
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
            max_tasks_per_child=request_options.get("max_tasks_per_child"),
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
        if day_callback is not None:
            day_callback(trade_date, timestamps, curves, day_result)
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


def _configure_runtime(*, disable_l2: bool) -> None:
    if not disable_l2:
        return

    os.environ["ARBS_SUPABASE_ENABLED"] = "0"

    import importlib
    import Caching.supabase_engine as supabase_engine_module

    importlib.reload(supabase_engine_module)
    state = IRSwapsMDP._CURVE_STORE_STATE
    with state["lock"]:
        state["store"] = None


def _add_common_service_args(parser: argparse.ArgumentParser, *, default_n_jobs: int) -> None:
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="IRSwapsMDP source.")
    parser.add_argument("--curve", "--curve-name", dest="curve", action="append", default=[], help="Curve name to warm. Repeatable.")
    parser.add_argument("--tenor", action="append", default=[], help="Computed-timeseries tenor to warm. Repeatable.")
    parser.add_argument("--n-jobs", type=int, default=default_n_jobs, help="Worker count for raw curve and TS warming.")
    parser.add_argument(
        "--calibration-executor",
        choices=("thread", "process"),
        default=DEFAULT_CALIBRATION_EXECUTOR,
        help="Executor for raw bulk curve calibration.",
    )
    parser.add_argument("--stirf-fetch-max-workers", type=int)
    parser.add_argument("--calibration-max-workers", type=int)
    parser.add_argument("--ignore-cache", action="store_true", help="Force cache refresh for raw curves and TS values.")
    parser.add_argument("--disable-l2", action="store_true", help="Disable Supabase L2 for this run.")
    parser.add_argument("--skip-curve-warm", action="store_true", help="Skip raw curve warming.")
    parser.add_argument("--skip-timeseries-warm", action="store_true", help="Skip computed-timeseries warming.")
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(
        show_tqdm=True,
        auto_prime_bulk=True,
        use_duckdb=DEFAULT_USE_DUCKDB,
        ts_base_dir=DEFAULT_TS_BASE_DIR,
        ts_row_group_size=DEFAULT_TS_ROW_GROUP_SIZE,
        ts_compression=DEFAULT_TS_COMPRESSION,
    )
    parser.add_argument("--show-tqdm", dest="show_tqdm", action="store_true")
    parser.add_argument("--hide-tqdm", dest="show_tqdm", action="store_false")
    parser.add_argument("--auto-prime-bulk", dest="auto_prime_bulk", action="store_true")
    parser.add_argument("--no-auto-prime-bulk", dest="auto_prime_bulk", action="store_false")
    parser.add_argument("--use-duckdb", dest="use_duckdb", action="store_true", help="Enable DuckDB backing for computed TS cache.")
    parser.add_argument("--no-use-duckdb", dest="use_duckdb", action="store_false", help="Disable DuckDB backing for computed TS cache.")
    parser.add_argument("--perf-log-path", default=None, help="Optional JSONL output path.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified STIRF backfill and live-service warmer for raw curves plus desk-tenor timeseries.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    backfill = subparsers.add_parser(
        "backfill",
        help="Backfill raw curves and computed desk tenors across a historical date range.",
    )
    _add_common_service_args(backfill, default_n_jobs=DEFAULT_N_JOBS)
    backfill.add_argument("--start-date", required=True, type=_argparse_date, help="Inclusive business-date start in YYYY-MM-DD.")
    backfill.add_argument("--end-date", required=True, type=_argparse_date, help="Inclusive business-date end in YYYY-MM-DD.")
    backfill.add_argument("--session-start", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_START), help="Session start in HH:MM.")
    backfill.add_argument("--session-end", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_END), help="Session end in HH:MM.")
    backfill.add_argument(
        "--cme-session",
        action="store_true",
        help="Use full CME Globex trade-date sessions: prior-day 17:00 America/Chicago through trade-date 16:00 America/Chicago.",
    )
    backfill.add_argument("--freq", default=DEFAULT_FREQ, help="Pandas frequency for intraday bucketing, e.g. 1min.")
    backfill.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for non-CME bucket timestamps.")
    backfill.add_argument("--fail-fast", action="store_true")
    backfill.add_argument(
        "--reprice-timeseries", action="store_true",
        help=(
            "Re-price every minute of every requested day even when the computed "
            "timeseries store already covers it. Off by default: a settled day is "
            "not repriced, which is what stopped a five-day catch-up from spending "
            "3,600 s re-doing warm days and losing the MIX23 curve to its own cap. "
            "Today is always repriced regardless, because today's session is still "
            "moving."
        ),
    )
    backfill.add_argument(
        "--backfill-only",
        action="store_true",
        help="Only push existing local CurveStore days in range to Supabase; skip calibration and timeseries warming.",
    )
    backfill.add_argument("--backfill-batch-size", type=int, default=DEFAULT_BACKFILL_BATCH_SIZE)
    backfill.set_defaults(backfill_local_cache=True, rewrite_existing_supabase=True)
    backfill.add_argument("--backfill-local-cache", dest="backfill_local_cache", action="store_true")
    backfill.add_argument("--no-backfill-local-cache", dest="backfill_local_cache", action="store_false")
    backfill.add_argument("--rewrite-existing-supabase", dest="rewrite_existing_supabase", action="store_true")
    backfill.add_argument("--only-missing-supabase", dest="rewrite_existing_supabase", action="store_false")
    backfill.add_argument(
        "--no-resume",
        "--force",
        dest="resume",
        action="store_false",
        default=True,
        help="Disable checkpoint skip; reprocess all days even if already cached.",
    )
    backfill.add_argument(
        "--max-tasks-per-child",
        type=int,
        default=50,
        help="Recycle process pool workers after N calibrations to limit memory leaks.",
    )

    live_service = subparsers.add_parser(
        "live-service",
        help="Incrementally warm the latest missing raw curves and desk-tenor timeseries.",
    )
    _add_common_service_args(live_service, default_n_jobs=DEFAULT_LIVE_SERVICE_N_JOBS)
    live_service.add_argument("--date", action="append", type=_argparse_date, default=[], help="Trading date to warm. Repeatable.")
    live_service.add_argument("--start-date", type=_argparse_date, default=None, help="Inclusive start date.")
    live_service.add_argument("--end-date", type=_argparse_date, default=None, help="Inclusive end date.")
    live_service.add_argument(
        "--window-template",
        choices=("nyc_rth", "cme_trading_day", "custom"),
        default=DEFAULT_WINDOW_TEMPLATE,
        help="Timestamp expansion template for each trading date.",
    )
    live_service.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="Custom window timezone.")
    live_service.add_argument("--start-time", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_START), help="Custom window start time.")
    live_service.add_argument("--end-time", type=_argparse_time, default=_parse_time(DEFAULT_SESSION_END), help="Custom window end time.")
    live_service.add_argument("--lag-minutes", type=int, default=DEFAULT_LAG_MINUTES, help="Do not warm the most recent N minutes.")
    live_service.add_argument("--freq", default=DEFAULT_FREQ, help="Reserved compatibility flag for intraday timestamp frequency.")

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.mode == "backfill":
        if not args.backfill_only and args.skip_curve_warm and args.skip_timeseries_warm:
            parser.error("At least one of raw curve warming or timeseries warming must remain enabled.")
    elif args.skip_curve_warm and args.skip_timeseries_warm:
        parser.error("At least one of raw curve warming or timeseries warming must remain enabled.")
    return args


def _run_backfill_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    curves = _resolve_curve_names(args.curve)
    explicit_tenors = _dedupe_preserve_order(args.tenor)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else _default_perf_log_path()
    timezone_name = DEFAULT_CME_TIMEZONE if bool(args.cme_session) else str(args.timezone)
    timezone = ZoneInfo(timezone_name)
    start_date = args.start_date
    end_date = args.end_date
    session_start = args.session_start
    session_end = args.session_end

    mdp = IRSwapsMDP(source=str(args.source))
    ts_builder = None
    if not args.skip_timeseries_warm and not args.backfill_only:
        ts_builder = _build_timeseries_builder(
            mdp=mdp,
            show_tqdm=bool(args.show_tqdm),
            use_duckdb=bool(args.use_duckdb),
            ts_base_dir=str(args.ts_base_dir),
            ts_row_group_size=int(args.ts_row_group_size),
            ts_compression=str(args.ts_compression),
        )

    overall_failure = False
    business_days = count_business_day_buckets(start_date=start_date, end_date=end_date)
    for curve_name in curves:
        sync_status = inspect_curve_store_sync_status(
            curve_name=curve_name,
            start_date=start_date,
            end_date=end_date,
        )
        logger.info(
            "CurveStore sync status for %s [%s -> %s]: local_days=%s remote_days=%s local_only_days=%s",
            curve_name,
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
                "curve_name": curve_name,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "local_days": sync_status["local_days"],
                "remote_days": sync_status["remote_days"],
                "local_only_days": sync_status["local_only_days"],
            },
        )

        if bool(args.backfill_local_cache):
            backfill_summary = backfill_local_curve_store_to_supabase(
                curve_name=curve_name,
                start_date=start_date,
                end_date=end_date,
                batch_size=int(args.backfill_batch_size),
                rewrite_existing=bool(args.rewrite_existing_supabase),
                logger=logger,
                perf_log_path=perf_log_path,
            )
            logger.info(
                "Supabase backfill summary for %s: status=%s pushed_days=%s failed_days=%s queued_days=%s",
                curve_name,
                backfill_summary["status"],
                backfill_summary["pushed_days"],
                backfill_summary["failed_days"],
                backfill_summary["queued_days"],
            )
            overall_failure = overall_failure or backfill_summary["failed_days"] > 0

        if bool(args.backfill_only):
            continue

        logger.info(
            "Prepared backfill service run for %s [%s -> %s]: business_days=%s remaining=%s session_mode=%s timezone=%s perf_log=%s",
            curve_name,
            start_date.isoformat(),
            end_date.isoformat(),
            business_days,
            business_days,
            "cme" if args.cme_session else "clock",
            timezone_name,
            perf_log_path,
        )

        progress = BackfillProgress(
            curve_name=curve_name,
            total_days=business_days,
            skipped_days=0,
        )

        window_summaries: list[dict[str, Any]] = []
        try:
            for trade_date, timestamps in iter_daily_minute_buckets(
                start_date=start_date,
                end_date=end_date,
                session_start=session_start,
                session_end=session_end,
                freq=str(args.freq),
                timezone=timezone,
                cme_session=bool(args.cme_session),
            ):
                curve_timestamps = [] if args.skip_curve_warm else _select_missing_curve_store_timestamps(
                    mdp._get_curve_store(),
                    curve_name=_resolve_curve_store_name(mdp, curve_name),
                    timestamps=timestamps,
                )
                logger.info(
                    "Starting window %s for %s: total_timestamps=%s missing_curve_timestamps=%s",
                    trade_date.isoformat(),
                    curve_name,
                    len(timestamps),
                    len(curve_timestamps),
                )
                summary = _run_live_service_window(
                    curve_name=curve_name,
                    curve_timestamps=curve_timestamps,
                    timeseries_timestamps=list(timestamps),
                    explicit_tenors=explicit_tenors,
                    mdp=mdp,
                    ts_builder=ts_builder,
                    n_jobs=int(args.n_jobs),
                    calibration_executor=str(args.calibration_executor),
                    curve_ignore_cache=False,
                    # A SETTLED DAY IS NOT REPRICED, and this used to be an
                    # unconditional True.
                    #
                    # The RAW half of this loop already filters its timestamps
                    # against the CurveStore, three lines up. The TIMESERIES half
                    # was handed the full 1,381-minute grid with
                    # ignore_cache=True - "refetch AND persist" - so every
                    # backfilled day re-priced every minute of every tenor
                    # whether or not the computed store already held it.
                    #
                    # Measured on the 2026-08-15 Saturday run, backfilling
                    # 08-10..08-14 when all five nights had already been warmed
                    # by their own nightly: Q12STIRT 133 s, Q16STIRT 109 s, and
                    # then USD-OIS-Q12xM12STIRT-SERFFX-MIX23 hit the 3,600 s
                    # per-curve cap and was LOST. Job total 3,842.2 s, FAILED -
                    # a job that failed because it insisted on redoing work it
                    # had already done.
                    #
                    # TODAY still reprices, because today's session is still
                    # moving and its partial values SHOULD be refreshed on a
                    # re-run. That is the case the True was written for; it was
                    # simply never bounded to it. ``--reprice-timeseries`` forces
                    # the old behaviour for a deliberate repair.
                    timeseries_ignore_cache=(
                        bool(getattr(args, "reprice_timeseries", False))
                        or trade_date >= dt.date.today()
                    ),
                    show_tqdm=bool(args.show_tqdm),
                    auto_prime_bulk=bool(args.auto_prime_bulk),
                    stirf_fetch_max_workers=args.stirf_fetch_max_workers,
                    calibration_max_workers=args.calibration_max_workers,
                    skip_curve_warm=bool(args.skip_curve_warm),
                    skip_timeseries_warm=bool(args.skip_timeseries_warm),
                    perf_log_path=perf_log_path,
                    logger=logger,
                    label=trade_date.isoformat(),
                )
                window_summaries.append(summary)
                progress.record_calibration(
                    status="ok" if summary.get("curve_status") in {"ok", "skipped"} else "error",
                )
                progress.record_timeseries(
                    status=str(summary.get("timeseries_status", "skipped")),
                    failed_tenors=list(summary.get("timeseries_failed_tenors", [])),
                )
                logger.info(progress.format_heartbeat())
                _write_perf_event(perf_log_path, progress.to_perf_event())
                gc.collect()
        except Exception:
            overall_failure = True
            logger.exception("Backfill service failed for %s", curve_name)
            if bool(args.fail_fast):
                break
            continue

        if window_summaries:
            logger.info(
                "Backfill summary for %s: windows=%s curve_partial_or_error=%s ts_partial_or_error=%s",
                curve_name,
                len(window_summaries),
                sum(1 for summary in window_summaries if summary.get("curve_status") in {"partial", "error"}),
                sum(1 for summary in window_summaries if summary.get("timeseries_status") in {"partial", "error"}),
            )

        overall_failure = overall_failure or any(
            summary.get("curve_status") in {"partial", "error"}
            or summary.get("timeseries_status") in {"partial", "error"}
            for summary in window_summaries
        )

    _flush_curve_store_pushes(logger=logger)
    _flush_computed_ts_pushes(ts_builder=ts_builder, logger=logger)
    logger.info("Performance log written to %s", perf_log_path)
    return 0 if not overall_failure else 1


def _run_live_service_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    curves = _resolve_curve_names(args.curve)
    explicit_tenors = _dedupe_preserve_order(args.tenor)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else None

    mdp = IRSwapsMDP(source=str(args.source))
    ts_builder = _build_timeseries_builder(
        mdp=mdp,
        show_tqdm=bool(args.show_tqdm),
        use_duckdb=bool(args.use_duckdb),
        ts_base_dir=str(args.ts_base_dir),
        ts_row_group_size=int(args.ts_row_group_size),
        ts_compression=str(args.ts_compression),
    )

    use_incremental_mode = not args.date and args.start_date is None and args.end_date is None
    ny_now = dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    trading_dates = [] if use_incremental_mode else _resolve_dates(
        explicit_dates=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        default_date=ny_now.date(),
    )

    window_summaries: list[dict[str, Any]] = []
    if use_incremental_mode:
        now_utc = dt.datetime.now(dt.timezone.utc)
        for curve_name in curves:
            try:
                timeseries_timestamps = _resolve_incremental_timestamp_range(
                    curve_name=curve_name,
                    mdp=mdp,
                    ts_builder=ts_builder,
                    window_template=str(args.window_template),
                    timezone_name=str(args.timezone),
                    start_time=args.start_time,
                    end_time=args.end_time,
                    now_utc=now_utc,
                    delay_minutes=int(args.lag_minutes),
                )
            except Exception:
                logger.exception("Failed to resolve incremental window for %s", curve_name)
                window_summaries.append(
                    {
                        "curve_name": curve_name,
                        "label": "incremental-from-db",
                        "status": "error",
                        "timeseries_failed_tenors": [],
                    }
                )
                continue

            curve_timestamps = [] if args.skip_curve_warm else _select_missing_curve_store_timestamps(
                mdp._get_curve_store(),
                curve_name=_resolve_curve_store_name(mdp, curve_name),
                timestamps=timeseries_timestamps,
            )
            window_summaries.append(
                _run_live_service_window(
                    curve_name=curve_name,
                    curve_timestamps=curve_timestamps,
                    timeseries_timestamps=timeseries_timestamps,
                    explicit_tenors=explicit_tenors,
                    mdp=mdp,
                    ts_builder=ts_builder,
                    n_jobs=int(args.n_jobs),
                    calibration_executor=str(args.calibration_executor),
                    curve_ignore_cache=False,
                    timeseries_ignore_cache=True,
                    show_tqdm=bool(args.show_tqdm),
                    auto_prime_bulk=bool(args.auto_prime_bulk),
                    stirf_fetch_max_workers=args.stirf_fetch_max_workers,
                    calibration_max_workers=args.calibration_max_workers,
                    skip_curve_warm=bool(args.skip_curve_warm),
                    skip_timeseries_warm=bool(args.skip_timeseries_warm),
                    perf_log_path=perf_log_path,
                    logger=logger,
                    label="incremental-from-db",
                )
            )
    else:
        for trading_date in trading_dates:
            if args.window_template != "cme_trading_day" and trading_date.weekday() >= 5:
                logger.info("Skipping weekend date %s for window_template=%s.", trading_date.isoformat(), args.window_template)
                continue

            try:
                window = _cap_end_at_now(
                    *_window_for_date(
                        trading_date,
                        window_template=str(args.window_template),
                        timezone_name=str(args.timezone),
                        start_time=args.start_time,
                        end_time=args.end_time,
                    ),
                    delay_minutes=int(args.lag_minutes),
                )
            except Exception:
                logger.exception("Failed to resolve window for %s", trading_date.isoformat())
                for curve_name in curves:
                    window_summaries.append(
                        {
                            "curve_name": curve_name,
                            "label": trading_date.isoformat(),
                            "status": "error",
                            "timeseries_failed_tenors": [],
                        }
                    )
                continue

            if window is None:
                logger.info("Skipping %s because the requested window is entirely in the future.", trading_date.isoformat())
                continue

            start, end = window
            timestamps = _build_minute_timestamps(start, end)
            if not timestamps:
                logger.info("Skipping %s because no timestamps were generated.", trading_date.isoformat())
                continue

            for curve_name in curves:
                curve_timestamps = [] if args.skip_curve_warm else _select_missing_curve_store_timestamps(
                    mdp._get_curve_store(),
                    curve_name=_resolve_curve_store_name(mdp, curve_name),
                    timestamps=timestamps,
                )
                window_summaries.append(
                    _run_live_service_window(
                        curve_name=curve_name,
                        curve_timestamps=curve_timestamps,
                        timeseries_timestamps=list(timestamps),
                        explicit_tenors=explicit_tenors,
                        mdp=mdp,
                        ts_builder=ts_builder,
                        n_jobs=int(args.n_jobs),
                        calibration_executor=str(args.calibration_executor),
                        curve_ignore_cache=False,
                        timeseries_ignore_cache=True,
                        show_tqdm=bool(args.show_tqdm),
                        auto_prime_bulk=bool(args.auto_prime_bulk),
                        stirf_fetch_max_workers=args.stirf_fetch_max_workers,
                        calibration_max_workers=args.calibration_max_workers,
                        skip_curve_warm=bool(args.skip_curve_warm),
                        skip_timeseries_warm=bool(args.skip_timeseries_warm),
                        perf_log_path=perf_log_path,
                        logger=logger,
                        label=trading_date.isoformat(),
                    )
                )

    _flush_curve_store_pushes(logger=logger)
    _flush_computed_ts_pushes(ts_builder=ts_builder, logger=logger)

    non_skipped = [summary for summary in window_summaries if summary.get("status") != "skipped"]
    logger.info(
        "Live-service summary: windows=%s non_skipped=%s partial_or_error=%s",
        len(window_summaries),
        len(non_skipped),
        sum(1 for summary in non_skipped if summary.get("status") in {"partial", "error"}),
    )
    return 0 if all(summary.get("status") == "ok" for summary in non_skipped) else (0 if not non_skipped else 1)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_runtime(disable_l2=bool(args.disable_l2))
    logger = _configure_logging(verbose=bool(args.verbose))
    if args.mode == "backfill":
        return _run_backfill_mode(args, logger)
    if args.mode == "live-service":
        return _run_live_service_mode(args, logger)
    raise ValueError(f"Unsupported mode '{args.mode}'")


if __name__ == "__main__":
    # Detect conda run without --no-capture-output (output appears buffered until exit).
    if os.environ.get("CONDA_PREFIX") and not sys.stderr.isatty():
        print(
            "NOTE: Running under conda with piped output. "
            "Use 'conda run --no-capture-output -n stir ...' for live progress.",
            file=sys.stderr,
            flush=True,
        )
    raise SystemExit(main())
