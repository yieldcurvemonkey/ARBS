#!/usr/bin/env python
"""EOD curve backfill and live-service runner.

This script owns the end-of-day IRS curve workflow:
1. Pull EOD settlement data from ERIS / CME.
2. Build/calibrate the requested IRS curve for each business date.
3. Persist raw curves into the CurveStore/local DB and configured L2 sync.
4. Compute comprehensive desk-tenor IRS timeseries from those snapshots.
5. Persist computed timeseries into the local/L2 stores.

Two primary modes are supported:
1. ``backfill``: expand a historical date range into business dates and warm
   both raw curves and computed desk tenors one trade date at a time.
2. ``live-service``: resolve today's (or explicit) trading date(s) and warm
   the raw EOD curve plus the full desk-tenor timeseries.

EOD curves like ERIS_EOD_LIVE-QL_BASIC produce a single curve snapshot per
business day covering the full maturity spectrum up to 50Y.  The desk-tenor
list is comprehensive with particular depth in the medium-term sector (2Y-10Y).
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Caching.curve_store import CurveStore
from Caching.supabase_curve_sync import CURVE_INTRADAY_BLOCKS_TABLE, SupabaseCurveSync
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SOURCE = "ERIS_EOD_LIVE-RL_BASIC"
DEFAULT_CURVE_NAME = "USD-SOFR-1D"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_N_JOBS = 8
DEFAULT_CALIBRATION_EXECUTOR = "process"
DEFAULT_LOG_DIR = REPO_ROOT / "notebooks" / "logs"
DEFAULT_BACKFILL_BATCH_SIZE = 25
DEFAULT_CURVES = (DEFAULT_CURVE_NAME,)
DEFAULT_TS_BASE_DIR = "./data/ts"
DEFAULT_TS_ROW_GROUP_SIZE = 256_000
DEFAULT_TS_COMPRESSION = "zstd"
DEFAULT_USE_DUCKDB = True
DEFAULT_USE_VECTORIZED_ENGINE = True

# ---------------------------------------------------------------------------
# EOD sources understood by this script
# ---------------------------------------------------------------------------
_EOD_SOURCES = {
    "ERIS_EOD_LIVE-RL_BASIC",
    "ERIS_EOD_LIVE_RL_BASIC",
    "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS",
    "ERIS_EOD_LIVE-QL_BASIC",
    "ERIS_EOD_LIVE_QL_BASIC",
    "ERIS_EOD_LIVE-QL_BASIC-NOJUMPS",
    "CME_NY_EOD_LIVE-QL_BASIC",
    "CME_NY_EOD_LIVE_QL_BASIC",
    "CME_NY_EOD_LIVE-RL_BASIC",
    "CME_NY_EOD_LIVE_RL_BASIC",
}

# ---------------------------------------------------------------------------
# Comprehensive desk-tenor definitions
# ---------------------------------------------------------------------------
# Spot-starting outrights — full spectrum 1M to 50Y
_EOD_SPOT_OUTRIGHT_TENORS = tuple(
    [f"{m}M" for m in range(1, 24)]
    + [f"{y}Y" for y in range(2, 51)]
)

# Medium-term sector focus: additional granular tenors in 2Y-10Y
_EOD_MEDIUM_TERM_GRANULAR = (
    # Semi-annual steps through belly
    "2Y", "30M", "3Y", "42M", "4Y", "54M", "5Y",
    "66M", "6Y", "78M", "7Y", "8Y", "9Y", "10Y",
)

# Forward-starting tenors — comprehensive desk set
# Notation: "{fwd_start}{swap_tenor}" e.g. "1Y1Y" = 1Y forward-starting 1Y swap
_EOD_FORWARD_START_TENORS = (
    # --- 1M forward ---
    "1M3M", "1M6M", "1M1Y", "1M2Y", "1M3Y", "1M5Y", "1M7Y", "1M10Y",
    # --- 2M forward ---
    "2M3M", "2M6M", "2M1Y", "2M2Y", "2M3Y", "2M5Y",
    # --- 3M forward ---
    "3M3M", "3M6M", "3M9M", "3M1Y", "3M18M", "3M2Y", "3M3Y", "3M5Y", "3M7Y", "3M10Y",
    # --- 6M forward ---
    "6M3M", "6M6M", "6M1Y", "6M18M", "6M2Y", "6M3Y", "6M5Y", "6M7Y", "6M10Y",
    # --- 9M forward ---
    "9M3M", "9M6M", "9M1Y", "9M18M", "9M2Y", "9M3Y", "9M5Y",
    # --- 1Y forward (key sector) ---
    "1Y1Y", "1Y18M", "1Y2Y", "1Y3Y", "1Y4Y", "1Y5Y", "1Y7Y", "1Y10Y",
    "1Y15Y", "1Y20Y", "1Y30Y",
    # --- 18M forward ---
    "18M6M", "18M1Y", "18M18M", "18M2Y", "18M3Y", "18M5Y",
    # --- 2Y forward (key sector) ---
    "2Y1Y", "2Y2Y", "2Y3Y", "2Y5Y", "2Y7Y", "2Y8Y", "2Y10Y",
    "2Y15Y", "2Y20Y", "2Y30Y",
    # --- 3Y forward (key sector) ---
    "3Y1Y", "3Y2Y", "3Y3Y", "3Y5Y", "3Y7Y", "3Y10Y",
    "3Y15Y", "3Y20Y",
    # --- 4Y forward ---
    "4Y1Y", "4Y2Y", "4Y3Y", "4Y5Y", "4Y6Y",
    # --- 5Y forward (key sector) ---
    "5Y1Y", "5Y2Y", "5Y3Y", "5Y5Y", "5Y7Y", "5Y10Y",
    "5Y15Y", "5Y20Y", "5Y25Y",
    # --- 7Y forward ---
    "7Y1Y", "7Y2Y", "7Y3Y", "7Y5Y", "7Y10Y",
    "7Y15Y", "7Y23Y",
    # --- 10Y forward ---
    "10Y1Y", "10Y2Y", "10Y3Y", "10Y5Y", "10Y10Y",
    "10Y15Y", "10Y20Y",
    # --- 15Y forward ---
    "15Y1Y", "15Y5Y", "15Y10Y", "15Y15Y",
    # --- 20Y forward ---
    "20Y1Y", "20Y5Y", "20Y10Y", "20Y30Y",
    # --- 30Y forward ---
    "30Y1Y", "30Y5Y", "30Y10Y", "30Y20Y",
)

# Common spread / butterfly building-block tenors used by the medium-term desk
_EOD_SPREAD_BUILDING_BLOCK_TENORS = (
    # 2s3s, 2s5s, 2s7s, 2s10s, 3s5s, 3s7s, 3s10s, 5s7s, 5s10s, 5s30s
    # These are covered by the outrights; listed here for documentation.
    # Forward-starting spreads (medium-term focus)
    "1Y2Y", "1Y3Y", "1Y5Y", "1Y7Y", "1Y10Y",
    "2Y2Y", "2Y3Y", "2Y5Y", "2Y7Y", "2Y10Y",
    "3Y2Y", "3Y3Y", "3Y5Y", "3Y7Y",
    "5Y5Y", "5Y10Y",
)

# FOMC meeting tenors
_CB_TOKEN_PREFIX = {"FOMC": "fomc"}

# IMM tenor configuration for EOD (fewer than STIRF since these are EOD snaps)
_EOD_IMM_SPANS = (1, 2, 4)
_EOD_IMM_HORIZON_COUNT = 8

_IMM_MONTH_CODE = {
    3: "H",
    6: "M",
    9: "U",
    12: "Z",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
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
        return f"EOD Backfill progress for {self.curve_name}: {' '.join(parts)}"

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value).strip())


def _format_dt(value: dt.date | dt.datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _default_perf_log_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"eod_curve_calibration_{stamp}.jsonl"


def _configure_logging(*, verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("eod_curve_calibration")


def _is_business_day(value: dt.date, calendar: ql.Calendar) -> bool:
    ql_date = ql.Date(value.day, value.month, value.year)
    return bool(calendar.isBusinessDay(ql_date))


def _write_perf_event(perf_log_path: Path | None, payload: dict[str, Any]) -> None:
    if perf_log_path is None:
        return
    perf_log_path.parent.mkdir(parents=True, exist_ok=True)
    with perf_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


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


# ---------------------------------------------------------------------------
# IMM tenor helpers
# ---------------------------------------------------------------------------
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


def _explicit_imm_pair_tenors(*, as_of: dt.date, horizon_count: int, spans: Sequence[int]) -> list[str]:
    imm_dates = _next_imm_dates(as_of, count=horizon_count)
    imm_codes = [_imm_code_for_date(d) for d in imm_dates]
    tenors: list[str] = []
    for span in spans:
        for offset in range(0, len(imm_codes) - int(span)):
            tenors.append(f"IMM_{imm_codes[offset]}xIMM_{imm_codes[offset + int(span)]}")
    return tenors


def _relative_imm_pair_tenors(*, max_imm_index: int, spans: Sequence[int]) -> list[str]:
    tenors: list[str] = []
    for span in spans:
        for start_idx in range(1, max_imm_index - int(span) + 1):
            tenors.append(f"IMM_{start_idx}xIMM_{start_idx + int(span)}")
    return tenors


# ---------------------------------------------------------------------------
# Curve reference / central bank helpers
# ---------------------------------------------------------------------------
def _curve_reference_id(curve_name: str) -> str:
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CURVE_TO_CB

    curve_upper = str(curve_name or "").strip().upper()
    for candidate in sorted(_CURVE_TO_CB, key=len, reverse=True):
        if curve_upper == candidate or curve_upper.startswith(candidate) or candidate in curve_upper:
            return candidate
    return curve_upper


# ---------------------------------------------------------------------------
# Tenor resolution
# ---------------------------------------------------------------------------
def _default_tenors_for_curve(curve_name: str, *, anchor_date: dt.date | None = None) -> list[str]:
    """Build comprehensive desk-tenor list for EOD curves.

    The list is biased toward the medium-term sector (2Y-10Y) with:
    - Full spot outright spectrum 1M-50Y
    - Dense forward-starting grid, heaviest in 1Y-5Y fwd x 1Y-10Y swap
    - FOMC meeting-dated tenors (ranked and explicit)
    - IMM-dated pair tenors
    """
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_date_map, central_bank_for_curve

    if anchor_date is None:
        anchor_date = dt.date.today()

    base = list(_EOD_SPOT_OUTRIGHT_TENORS)
    forwards = list(_EOD_FORWARD_START_TENORS)

    # IMM pair tenors
    imm_explicit = _explicit_imm_pair_tenors(
        as_of=anchor_date,
        horizon_count=_EOD_IMM_HORIZON_COUNT,
        spans=_EOD_IMM_SPANS,
    )
    imm_relative = _relative_imm_pair_tenors(
        max_imm_index=_EOD_IMM_HORIZON_COUNT,
        spans=_EOD_IMM_SPANS,
    )

    return _dedupe_preserve_order(
        base
        + forwards
        + imm_explicit
        + imm_relative
    )


# ---------------------------------------------------------------------------
# Business day iteration for EOD (one timestamp per business day)
# ---------------------------------------------------------------------------
def iter_eod_business_dates(
    *,
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
) -> Iterator[dt.date]:
    """Yield each business date in [start_date, end_date]."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    current = start_date
    while current <= end_date:
        if _is_business_day(current, cal):
            yield current
        current += dt.timedelta(days=1)


def count_business_days(
    *,
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
) -> int:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    return sum(1 for _ in iter_eod_business_dates(start_date=start_date, end_date=end_date, calendar=calendar))


# ---------------------------------------------------------------------------
# CurveStore helpers
# ---------------------------------------------------------------------------
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

    summary: dict[str, Any] = {
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
                "Supabase backfill heartbeat for %s: starting day %s/%s trading_date=%s batch=%s/%s pushed=%s failed=%s elapsed=%.1fs",
                curve_name,
                global_day_idx,
                total_days,
                trading_date.isoformat(),
                batch_idx,
                len(batches),
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


# ---------------------------------------------------------------------------
# Day-level calibration
# ---------------------------------------------------------------------------
def _summarize_day(
    *,
    trade_date: dt.date,
    timestamps: list[dt.date],
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


# ---------------------------------------------------------------------------
# Flush helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Checkpoint probe
# ---------------------------------------------------------------------------
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

    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    sentinel_query = UnifiedQuery(
        curve=curve_name,
        tenor=sentinel_tenor,
        value=UnifiedValue.IRS_RATE,
    )
    legacy_queries = sentinel_query.return_query()
    if not legacy_queries:
        return set()
    legacy_item = legacy_queries[0].to_legacy()
    from TB.IRSwapsTB import _query_fingerprint
    fingerprint = _query_fingerprint(legacy_item)
    sentinel_symbol = f"IRS::{source}::{curve_name}::{fingerprint}"

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


# ---------------------------------------------------------------------------
# Timeseries builder
# ---------------------------------------------------------------------------
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


def _concat_timeseries_frames(frames: Sequence[Any]) -> Any:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0]
    out = pd.concat(non_empty, axis=1)
    return out.loc[:, ~out.columns.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# Safe warm wrappers
# ---------------------------------------------------------------------------
def _safe_warm_raw_curves(
    mdp: Any,
    *,
    curve_name: str,
    timestamps: Sequence[dt.date],
    ignore_cache: bool,
    n_jobs: int,
    calibration_executor: str,
    show_tqdm: bool = False,
    logger: logging.Logger | None = None,
) -> tuple[int, list[dt.date]]:
    """Warm raw EOD curves for a batch of business dates."""
    timestamp_list = list(timestamps)
    if not timestamp_list:
        return 0, []

    def _run(batch: Sequence[dt.date], *, depth: int = 0) -> tuple[int, list[dt.date]]:
        batch_list = list(batch)
        request: dict[str, Any] = {
            "curve_name": curve_name,
            "timestamps": list(batch_list),
            "n_jobs": int(n_jobs),
            "show_tqdm": bool(show_tqdm),
            "ignore_cache": bool(ignore_cache),
            "calibration_executor": str(calibration_executor),
            "auto_prime_bulk": True,
        }
        try:
            return len(mdp.bulk_get_data(request)), []
        except Exception as exc:
            if len(batch_list) == 1:
                if logger is not None:
                    logger.warning(
                        "RAW %s failed for date=%s (%s)",
                        curve_name,
                        batch_list[0].isoformat(),
                        exc,
                    )
                return 0, batch_list
            if depth == 0 and logger is not None:
                logger.warning(
                    "RAW %s failed for %s dates (%s); retrying in smaller batches.",
                    curve_name,
                    len(batch_list),
                    exc,
                )
            midpoint = max(1, len(batch_list) // 2)
            left_count, left_failed = _run(batch_list[:midpoint], depth=depth + 1)
            right_count, right_failed = _run(batch_list[midpoint:], depth=depth + 1)
            return left_count + right_count, left_failed + right_failed

    return _run(timestamp_list)


def _safe_warm_timeseries(
    ts_builder: Any,
    *,
    start: dt.date,
    end: dt.date,
    queries: Sequence[Any],
    n_jobs: int,
    ignore_cache: bool,
    timestamps: Sequence[dt.date],
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
    timestamps: Sequence[dt.date],
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
    anchor_date = active_timestamps[0]
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


def _vectorized_timeseries_warm(
    *,
    curve_name: str,
    start_date: dt.date,
    end_date: dt.date,
    explicit_tenors: Sequence[str],
    source: str,
    computed_ts_store: object,
    curve_store: object | None,
    perf_log_path: Path | None,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Compute all EOD timeseries via vectorized engine in one pass."""
    from Caching.eod_vectorized_engine import compute_and_persist_eod_panel

    started = time.perf_counter()
    tenors = _dedupe_preserve_order(explicit_tenors) or _default_tenors_for_curve(curve_name, anchor_date=start_date)

    # Read all raw nodes in one scan
    active_store = curve_store or CurveStore.default()
    raw_df = active_store.read_raw_nodes(
        curve_name,
        start=start_date,
        end=end_date,
    )

    if raw_df.empty:
        logger.warning("No raw nodes found for %s [%s -> %s]", curve_name, start_date, end_date)
        summary = {"status": "empty", "rates_computed": 0, "elapsed_seconds": 0.0}
        _write_perf_event(perf_log_path, {"event": "vectorized_timeseries_result", **summary})
        return summary

    result = compute_and_persist_eod_panel(
        raw_nodes_df=raw_df,
        tenors=tenors,
        curve_name=curve_name,
        source=source,
        computed_ts_store=computed_ts_store,
        curve_store=active_store,
    )

    elapsed = time.perf_counter() - started
    result["elapsed_seconds"] = round(elapsed, 3)
    _write_perf_event(perf_log_path, {"event": "vectorized_timeseries_result", "curve_name": curve_name, **result})
    logger.info(
        "Vectorized TS warm complete for %s: status=%s rates=%s tenors=%s dates=%s elapsed=%.2fs",
        curve_name,
        result["status"],
        result.get("rates_computed", 0),
        result.get("tenor_count", 0),
        result.get("date_count", 0),
        elapsed,
    )
    return result


# ---------------------------------------------------------------------------
# Bucketed calibration runner
# ---------------------------------------------------------------------------
def run_bucketed_calibration(
    *,
    curve_mdp: Any,
    curve_name: str,
    source: str,
    daily_dates: Iterable[dt.date],
    perf_log_path: Path,
    logger: logging.Logger,
    fail_fast: bool,
    n_jobs: int,
    ignore_cache: bool,
    calibration_executor: str,
    show_tqdm: bool,
    business_days: int | None = None,
    day_callback: Callable[[dt.date, dict[Any, Any], DayCalibrationStats], None] | None = None,
) -> tuple[dict[Any, Any], list[DayCalibrationStats], dict[str, Any]]:
    """Run EOD calibration across a sequence of business dates.

    Unlike the STIRF version, each date produces exactly one curve (no intraday
    bucketing), so the request uses a list of dates rather than timestamps.
    """
    daily_results: list[DayCalibrationStats] = []

    _write_perf_event(
        perf_log_path,
        {
            "event": "run_start",
            "curve_name": curve_name,
            "source": source,
            "business_days": business_days,
        },
    )

    run_started = time.perf_counter()
    processed_business_days = 0
    for trade_date in daily_dates:
        processed_business_days += 1
        logger.info("Starting EOD calibration for %s on %s", curve_name, trade_date.isoformat())

        started = time.perf_counter()
        curves: dict[Any, Any] = {}
        status = "ok"
        error: str | None = None
        try:
            request: dict[str, Any] = {
                "curve_name": curve_name,
                "timestamps": [trade_date],
                "n_jobs": int(n_jobs),
                "show_tqdm": bool(show_tqdm),
                "ignore_cache": bool(ignore_cache),
                "calibration_executor": str(calibration_executor),
                "auto_prime_bulk": True,
            }
            curves = curve_mdp.bulk_get_data(request)
        except Exception as exc:
            status = "error"
            error = str(exc)
            logger.exception("EOD calibration failed for %s on %s", curve_name, trade_date.isoformat())
            if fail_fast:
                elapsed = time.perf_counter() - started
                day_result = _summarize_day(
                    trade_date=trade_date,
                    timestamps=[trade_date],
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
                raise

        elapsed = time.perf_counter() - started
        day_result = _summarize_day(
            trade_date=trade_date,
            timestamps=[trade_date],
            curves=curves,
            elapsed_seconds=elapsed,
            status=status,
            error=error,
            requested_curve_name=curve_name,
        )
        daily_results.append(day_result)
        logger.info(
            "Finished EOD %s on %s: status=%s returned=%s elapsed=%.2fs",
            curve_name,
            trade_date.isoformat(),
            day_result.status,
            day_result.returned_curves,
            day_result.elapsed_seconds,
        )
        _write_perf_event(
            perf_log_path,
            {"event": "day_result", **asdict(day_result)},
        )
        if day_callback is not None:
            day_callback(trade_date, curves, day_result)
        curves.clear()
        gc.collect()

    total_elapsed_seconds = time.perf_counter() - run_started
    summary = _summarize_run(
        curve_name=curve_name,
        source=source,
        daily_results=daily_results,
        total_elapsed_seconds=total_elapsed_seconds,
        business_days=processed_business_days,
    )
    _write_perf_event(perf_log_path, summary)
    return {}, daily_results, summary


# ---------------------------------------------------------------------------
# Runtime config
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def _argparse_date(value: str) -> dt.date:
    try:
        return _parse_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date '{value}'. Expected YYYY-MM-DD.") from exc


def _add_common_service_args(parser: argparse.ArgumentParser, *, default_n_jobs: int) -> None:
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="IRSwapsMDP source for EOD curves.")
    parser.add_argument("--curve", "--curve-name", dest="curve", action="append", default=[], help="Curve name to warm. Repeatable.")
    parser.add_argument("--tenor", action="append", default=[], help="Computed-timeseries tenor to warm. Repeatable.")
    parser.add_argument("--n-jobs", type=int, default=default_n_jobs, help="Worker count for raw curve and TS warming.")
    parser.add_argument(
        "--calibration-executor",
        choices=("thread", "process"),
        default=DEFAULT_CALIBRATION_EXECUTOR,
        help="Executor for raw bulk curve calibration.",
    )
    parser.add_argument("--ignore-cache", action="store_true", help="Force cache refresh for raw curves and TS values.")
    parser.add_argument("--disable-l2", action="store_true", help="Disable Supabase L2 for this run.")
    parser.add_argument("--skip-curve-warm", action="store_true", help="Skip raw curve warming.")
    parser.add_argument("--skip-timeseries-warm", action="store_true", help="Skip computed-timeseries warming.")
    parser.add_argument("--verbose", action="store_true")
    parser.set_defaults(
        show_tqdm=True,
        auto_prime_bulk=True,
        use_duckdb=DEFAULT_USE_DUCKDB,
        use_vectorized_engine=DEFAULT_USE_VECTORIZED_ENGINE,
        ts_base_dir=DEFAULT_TS_BASE_DIR,
        ts_row_group_size=DEFAULT_TS_ROW_GROUP_SIZE,
        ts_compression=DEFAULT_TS_COMPRESSION,
    )
    parser.add_argument("--show-tqdm", dest="show_tqdm", action="store_true")
    parser.add_argument("--hide-tqdm", dest="show_tqdm", action="store_false")
    parser.add_argument("--use-duckdb", dest="use_duckdb", action="store_true", help="Enable DuckDB backing for computed TS cache.")
    parser.add_argument("--no-use-duckdb", dest="use_duckdb", action="store_false", help="Disable DuckDB backing for computed TS cache.")
    parser.add_argument("--use-vectorized-engine", dest="use_vectorized_engine", action="store_true", help="Use vectorized EOD engine for timeseries computation.")
    parser.add_argument("--no-vectorized-engine", dest="use_vectorized_engine", action="store_false", help="Disable vectorized EOD engine.")
    parser.add_argument("--perf-log-path", default=None, help="Optional JSONL output path.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EOD curve backfill and live-service warmer for raw curves plus desk-tenor timeseries.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # --- backfill subcommand ---
    backfill = subparsers.add_parser(
        "backfill",
        help="Backfill raw EOD curves and computed desk tenors across a historical date range.",
    )
    _add_common_service_args(backfill, default_n_jobs=DEFAULT_N_JOBS)
    backfill.add_argument("--start-date", required=True, type=_argparse_date, help="Inclusive business-date start in YYYY-MM-DD.")
    backfill.add_argument("--end-date", required=True, type=_argparse_date, help="Inclusive business-date end in YYYY-MM-DD.")
    backfill.add_argument("--fail-fast", action="store_true")
    backfill.add_argument(
        "--backfill-only",
        action="store_true",
        help="Only push existing local CurveStore days to Supabase; skip calibration and timeseries warming.",
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

    # --- live-service subcommand ---
    live_service = subparsers.add_parser(
        "live-service",
        help="Warm today's (or explicit) EOD raw curves and desk-tenor timeseries.",
    )
    _add_common_service_args(live_service, default_n_jobs=DEFAULT_N_JOBS)
    live_service.add_argument("--date", action="append", type=_argparse_date, default=[], help="Trading date to warm. Repeatable.")
    live_service.add_argument("--start-date", type=_argparse_date, default=None, help="Inclusive start date.")
    live_service.add_argument("--end-date", type=_argparse_date, default=None, help="Inclusive end date.")

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


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------
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


def _run_backfill_mode(args: argparse.Namespace, logger: logging.Logger) -> int:
    curves = _resolve_curve_names(args.curve)
    explicit_tenors = _dedupe_preserve_order(args.tenor)
    perf_log_path = Path(args.perf_log_path) if args.perf_log_path else _default_perf_log_path()
    start_date = args.start_date
    end_date = args.end_date

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
    business_days = count_business_days(start_date=start_date, end_date=end_date)
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

        # --- Checkpoint probe ---
        skip_ts = bool(args.skip_timeseries_warm) or ts_builder is None
        skipped_days_set: set[dt.date] = set()
        if bool(args.resume) and not bool(args.ignore_cache):
            raw_complete = set(_local_curve_dates_in_range(
                curve_name=curve_name,
                start_date=start_date,
                end_date=end_date,
            ))
            ts_complete = (
                set()
                if skip_ts
                else _probe_ts_completed_dates(
                    ts_builder=ts_builder,
                    curve_name=curve_name,
                    source=str(args.source),
                    sentinel_tenor=_default_tenors_for_curve(curve_name, anchor_date=start_date)[0],
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            skipped_days_set = _probe_completed_days(
                raw_complete_dates=raw_complete,
                ts_complete_dates=ts_complete,
                skip_timeseries_warm=skip_ts,
            )
            if skipped_days_set:
                logger.info(
                    "Checkpoint: skipping %s/%s already-completed days for %s",
                    len(skipped_days_set),
                    business_days,
                    curve_name,
                )
                _write_perf_event(perf_log_path, {
                    "event": "checkpoint_probe",
                    "curve_name": curve_name,
                    "skipped_days": len(skipped_days_set),
                    "total_days": business_days,
                    "raw_complete": len(raw_complete),
                    "ts_complete": len(ts_complete) if not skip_ts else None,
                })

        remaining_days = business_days - len(skipped_days_set)

        logger.info(
            "Prepared EOD backfill for %s [%s -> %s]: business_days=%s remaining=%s source=%s perf_log=%s",
            curve_name,
            start_date.isoformat(),
            end_date.isoformat(),
            business_days,
            remaining_days,
            args.source,
            perf_log_path,
        )

        # --- Progress tracker ---
        progress = BackfillProgress(
            curve_name=curve_name,
            total_days=business_days,
            skipped_days=len(skipped_days_set),
        )

        timeseries_results: list[dict[str, Any]] = []

        def _day_callback(
            trade_date: dt.date,
            _curves: dict[Any, Any],
            day_result: DayCalibrationStats,
        ) -> None:
            progress.record_calibration(status=day_result.status)
            ts_summary: dict[str, Any] = {}
            if ts_builder is not None and day_result.status != "error" and not bool(args.use_vectorized_engine):
                # For EOD, we warm TS for the range [trade_date, trade_date]
                # (skipped when vectorized engine handles TS in one pass after calibration)
                ts_summary = _warm_timeseries_window(
                    curve_name=curve_name,
                    timestamps=[trade_date],
                    explicit_tenors=explicit_tenors,
                    ts_builder=ts_builder,
                    mdp=mdp,
                    n_jobs=int(args.n_jobs),
                    ignore_cache=bool(args.ignore_cache),
                    perf_log_path=perf_log_path,
                    logger=logger,
                    label=trade_date.isoformat(),
                )
                timeseries_results.append(ts_summary)
            progress.record_timeseries(
                status=ts_summary.get("status", "skipped"),
                failed_tenors=ts_summary.get("failed_tenors", []),
            )
            logger.info(progress.format_heartbeat())
            _write_perf_event(perf_log_path, progress.to_perf_event())
            gc.collect()

        # --- Filtered daily iterator ---
        def _filtered_business_dates():
            for trade_date in iter_eod_business_dates(
                start_date=start_date,
                end_date=end_date,
            ):
                if trade_date in skipped_days_set:
                    continue
                yield trade_date

        try:
            _, daily_results, summary = run_bucketed_calibration(
                curve_mdp=mdp,
                curve_name=curve_name,
                source=str(args.source),
                daily_dates=_filtered_business_dates(),
                perf_log_path=perf_log_path,
                logger=logger,
                fail_fast=bool(args.fail_fast),
                n_jobs=int(args.n_jobs),
                ignore_cache=bool(args.ignore_cache),
                calibration_executor=str(args.calibration_executor),
                show_tqdm=bool(args.show_tqdm),
                business_days=remaining_days,
                day_callback=_day_callback,
            )
        except Exception:
            overall_failure = True
            logger.exception("EOD backfill service failed for %s", curve_name)
            if bool(args.fail_fast):
                break
            continue

        # --- Vectorized timeseries warm (replaces per-date _warm_timeseries_window) ---
        if bool(args.use_vectorized_engine) and ts_builder is not None:
            ts_stores = _computed_ts_stores_for_builder(ts_builder)
            ts_store = ts_stores[0] if ts_stores else None
            if ts_store is not None:
                _vectorized_timeseries_warm(
                    curve_name=curve_name,
                    start_date=start_date,
                    end_date=end_date,
                    explicit_tenors=explicit_tenors,
                    source=str(args.source),
                    computed_ts_store=ts_store,
                    curve_store=None,
                    perf_log_path=perf_log_path,
                    logger=logger,
                )

        logger.info(
            "EOD backfill curve summary for %s: successful_days=%s failed_days=%s returned=%s/%s elapsed=%.2fs",
            curve_name,
            summary["successful_days"],
            summary["failed_days"],
            summary["returned_curves"],
            summary["requested_timestamps"],
            summary["total_elapsed_seconds"],
        )
        if daily_results:
            slowest = max(daily_results, key=lambda row: row.elapsed_seconds)
            logger.info(
                "Slowest day for %s: trade_date=%s elapsed=%.2fs missing=%s",
                curve_name,
                slowest.trade_date,
                slowest.elapsed_seconds,
                slowest.missing_curves,
            )
        if timeseries_results:
            logger.info(
                "EOD backfill timeseries summary for %s: windows=%s partial_or_error=%s failed_tenors=%s",
                curve_name,
                len(timeseries_results),
                sum(1 for result in timeseries_results if result["status"] in {"partial", "error"}),
                sum(len(result["failed_tenors"]) for result in timeseries_results),
            )

        overall_failure = overall_failure or summary["failed_days"] > 0
        overall_failure = overall_failure or any(
            result["status"] in {"partial", "error"} for result in timeseries_results
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

    ny_now = dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    trading_dates = _resolve_dates(
        explicit_dates=args.date,
        start_date=getattr(args, "start_date", None),
        end_date=getattr(args, "end_date", None),
        default_date=ny_now.date(),
    )

    window_summaries: list[dict[str, Any]] = []
    for trading_date in trading_dates:
        if trading_date.weekday() >= 5:
            logger.info("Skipping weekend date %s.", trading_date.isoformat())
            continue

        for curve_name in curves:
            # Warm raw curve
            curve_failed: list[dt.date] = []
            curve_ready = 0
            if not args.skip_curve_warm:
                curve_ready, curve_failed = _safe_warm_raw_curves(
                    mdp,
                    curve_name=curve_name,
                    timestamps=[trading_date],
                    ignore_cache=bool(args.ignore_cache),
                    n_jobs=int(args.n_jobs),
                    calibration_executor=str(args.calibration_executor),
                    show_tqdm=bool(args.show_tqdm),
                    logger=logger,
                )

            # Warm timeseries
            ts_summary: dict[str, Any] = {
                "rows": 0,
                "cols": 0,
                "failed_tenors": [],
                "status": "skipped",
            }
            if not args.skip_timeseries_warm:
                ts_summary = _warm_timeseries_window(
                    curve_name=curve_name,
                    timestamps=[trading_date],
                    explicit_tenors=explicit_tenors,
                    ts_builder=ts_builder,
                    mdp=mdp,
                    n_jobs=int(args.n_jobs),
                    ignore_cache=bool(args.ignore_cache),
                    perf_log_path=perf_log_path,
                    logger=logger,
                    label=trading_date.isoformat(),
                )

            succeeded_curve = args.skip_curve_warm or curve_ready > 0
            succeeded_ts = args.skip_timeseries_warm or ts_summary["status"] in {"ok", "partial"}
            status = "ok"
            if not (succeeded_curve and succeeded_ts):
                status = "error"
            elif curve_failed or ts_summary["status"] == "partial":
                status = "partial"

            summary = {
                "event": "service_window",
                "curve_name": curve_name,
                "label": trading_date.isoformat(),
                "status": status,
                "curve_ready": curve_ready,
                "timeseries_rows": int(ts_summary["rows"]),
                "timeseries_cols": int(ts_summary["cols"]),
                "timeseries_failed_tenors": list(ts_summary["failed_tenors"]),
            }
            _write_perf_event(perf_log_path, summary)
            window_summaries.append(summary)
            logger.info(
                "EOD live-service complete for %s on %s: status=%s curve_ready=%s ts_rows=%s ts_cols=%s",
                curve_name,
                trading_date.isoformat(),
                status,
                curve_ready,
                summary["timeseries_rows"],
                summary["timeseries_cols"],
            )

    _flush_curve_store_pushes(logger=logger)
    _flush_computed_ts_pushes(ts_builder=ts_builder, logger=logger)

    non_skipped = [s for s in window_summaries if s.get("status") != "skipped"]
    logger.info(
        "EOD live-service summary: windows=%s non_skipped=%s partial_or_error=%s",
        len(window_summaries),
        len(non_skipped),
        sum(1 for s in non_skipped if s.get("status") in {"partial", "error"}),
    )
    return 0 if all(s.get("status") == "ok" for s in non_skipped) else (0 if not non_skipped else 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
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
    raise SystemExit(main())
