#!/usr/bin/env python
"""Shared utilities for UST bond service scripts.

Provides:
- Bond universe resolution (benchmarks, OTR+old, full active)
- Alias-aware CUSIP expansion (CT10, O10, OO10, 0231-10, raw CUSIPs)
- FixedRateBondsMDP / FixedRateBondsTB factory helpers
- Binary subdivision retry wrappers for raw bond warming and timeseries
- Performance logging, progress tracking, common argparse groups
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd
import QuantLib as ql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_INTRADAY_SOURCE = "USTS_WEBULL_WSJ_LIVE-RL"
DEFAULT_EOD_SOURCE = "USTS_FEDINVEST_WSJ_LIVE-RL"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_SESSION_START = "07:00"
DEFAULT_SESSION_END = "15:00"
DEFAULT_FREQ = "1min"
DEFAULT_N_JOBS = 8
DEFAULT_LIVE_SERVICE_N_JOBS = 12
DEFAULT_LOG_DIR = REPO_ROOT / "notebooks" / "logs"
DEFAULT_BACKFILL_BATCH_SIZE = 25
DEFAULT_LAG_MINUTES = 15
DEFAULT_TS_BASE_DIR = "./data/ts"
DEFAULT_TS_ROW_GROUP_SIZE = 256_000
DEFAULT_TS_COMPRESSION = "zstd"
DEFAULT_USE_DUCKDB = False
DEFAULT_UNIVERSE = "otr-plus-old"

# ---------------------------------------------------------------------------
# Bond universe tier definitions
# ---------------------------------------------------------------------------
# Original-issue buckets supported by fiscaldata reference data
_OI_TENORS = (2, 3, 5, 7, 10, 20, 30)

_BENCHMARK_ALIASES = tuple(f"CT{t}" for t in _OI_TENORS)

_OTR_PLUS_OLD_ALIASES = tuple(
    alias
    for t in _OI_TENORS
    for alias in (f"CT{t}", f"O{t}", f"OO{t}", f"OOO{t}")
)


def resolve_bond_universe(
    as_of_date: dt.date,
    tier: str = DEFAULT_UNIVERSE,
    extra_cusips: list[str] | None = None,
    source: str = "fiscaldata",
) -> list[str]:
    """Return list of aliases/CUSIPs for the requested tier + extras.

    Tiers:
        benchmarks     — CT2..CT30 (7 on-the-run aliases)
        otr-plus-old   — CT/O/OO/OOO for each OI bucket (28 aliases)
        full-active    — every CUSIP from reference data where
                         issue_date <= as_of_date <= maturity_date
    """
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (
        update_reference_data,
    )

    tier_lower = tier.lower().replace("_", "-")
    if tier_lower == "benchmarks":
        aliases = list(_BENCHMARK_ALIASES)
    elif tier_lower in ("otr-plus-old", "otr_plus_old"):
        aliases = list(_OTR_PLUS_OLD_ALIASES)
    elif tier_lower in ("full-active", "full_active"):
        ref_df = update_reference_data(source=source, force_refresh=False)
        ref_df = ref_df[
            (ref_df["issue_date"] <= as_of_date)
            & (ref_df["maturity_date"] >= as_of_date)
        ]
        aliases = ref_df["cusip"].astype(str).unique().tolist()
    else:
        raise ValueError(
            f"Unknown universe tier '{tier}'. "
            "Expected: benchmarks, otr-plus-old, full-active"
        )

    if extra_cusips:
        seen = set(aliases)
        for c in extra_cusips:
            c = c.strip()
            if c and c not in seen:
                aliases.append(c)
                seen.add(c)

    return aliases


# ---------------------------------------------------------------------------
# MDP / TB factories
# ---------------------------------------------------------------------------
def build_frb_mdp(source: str):
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    return FixedRateBondsMDP(source=source)


def build_frb_tb(mdp, *, show_tqdm: bool = True, use_duckdb: bool = DEFAULT_USE_DUCKDB,
                 ts_base_dir: str = DEFAULT_TS_BASE_DIR,
                 ts_row_group_size: int = DEFAULT_TS_ROW_GROUP_SIZE,
                 ts_compression: str = DEFAULT_TS_COMPRESSION):
    from TB.FixedRateBondsTB import FixedRateBondsTB
    return FixedRateBondsTB(
        mdp=mdp,
        show_tqdm=show_tqdm,
        use_ts_cache=True,
        ts_base_dir=ts_base_dir,
        ts_row_group_size=ts_row_group_size,
        ts_compression=ts_compression,
    )


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------
def build_frb_queries(
    cusips: list[str],
    values: list[str] | None = None,
):
    """Build one FixedRateBondQuery per cusip x value."""
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    if values is None:
        value_enums = [FixedRateBondValue.YTM]
    else:
        value_enums = [FixedRateBondValue[v.upper()] for v in values]

    queries = []
    for cusip in cusips:
        for val in value_enums:
            queries.append(
                FixedRateBondQuery(
                    cusip=cusip,
                    value=val,
                )
            )
    return queries


# ---------------------------------------------------------------------------
# Perf helpers (mirror IRS services)
# ---------------------------------------------------------------------------
def _get_rss_mb() -> float:
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
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m{seconds % 60:02.0f}s"
    hours = minutes / 60
    return f"{hours:.0f}h{minutes % 60:02.0f}m"


def _format_dt(value: dt.datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _write_perf_event(path: Path | None, event: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        json.dump(event, fh, default=str)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Stats / Progress
# ---------------------------------------------------------------------------
@dataclass
class DayCalibrationStats:
    trade_date: str
    requested_cusips: int
    returned_pricers: int
    missing_pricers: int
    first_timestamp: str | None
    last_timestamp: str | None
    elapsed_seconds: float
    pricers_per_second: float
    status: str
    error: str | None = None


@dataclass
class BackfillProgress:
    label: str
    total_days: int
    skipped_days: int
    processed_days: int = 0
    calibration_ok: int = 0
    calibration_error: int = 0
    timeseries_ok: int = 0
    timeseries_partial: int = 0
    failed_cusips: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    def record_calibration(self, *, status: str) -> None:
        self.processed_days += 1
        if status == "ok":
            self.calibration_ok += 1
        else:
            self.calibration_error += 1

    def record_timeseries(self, *, status: str, failed_cusips: list[str]) -> None:
        if status == "ok":
            self.timeseries_ok += 1
        elif status in ("partial", "error"):
            self.timeseries_partial += 1
        self.failed_cusips.extend(failed_cusips)

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
            f" failed_cusips={len(self.failed_cusips)}"
        )
        return f"UST backfill progress for {self.label}: {' '.join(parts)}"

    def to_perf_event(self) -> dict[str, Any]:
        return {
            "event": "backfill_heartbeat",
            "label": self.label,
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
            "failed_cusip_count": len(self.failed_cusips),
        }


# ---------------------------------------------------------------------------
# Binary subdivision retry
# ---------------------------------------------------------------------------
def _safe_warm_raw_bonds(
    mdp,
    *,
    cusips: list[str],
    timestamps: Sequence[dt.datetime] | Sequence[dt.date],
    force_refresh: bool = False,
    show_tqdm: bool = False,
    max_workers: int = 8,
    logger: logging.Logger | None = None,
) -> tuple[int, list]:
    """Warm raw bond pricers via bulk_get_data with binary subdivision on failure."""
    ts_list = list(timestamps)
    if not ts_list:
        return 0, []

    def _run(batch, *, depth: int = 0) -> tuple[int, list]:
        batch_list = list(batch)
        try:
            result = mdp.bulk_get_data(
                timestamps=batch_list,
                cusips=cusips,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
                max_workers=max_workers,
            )
            count = sum(len(v) for v in result.values()) if isinstance(result, dict) else 0
            return count, []
        except Exception as exc:
            if len(batch_list) == 1:
                if logger is not None:
                    logger.warning(
                        "RAW UST warm failed for timestamp=%s (%s)",
                        batch_list[0],
                        exc,
                    )
                return 0, batch_list
            if depth == 0 and logger is not None:
                logger.warning(
                    "RAW UST warm failed for %s timestamps (%s); retrying in smaller batches.",
                    len(batch_list),
                    exc,
                )
            midpoint = max(1, len(batch_list) // 2)
            left_count, left_failed = _run(batch_list[:midpoint], depth=depth + 1)
            right_count, right_failed = _run(batch_list[midpoint:], depth=depth + 1)
            return left_count + right_count, left_failed + right_failed

    return _run(ts_list)


def _safe_warm_bond_timeseries(
    tb,
    *,
    start,
    end,
    queries: Sequence,
    timestamps: Sequence,
    n_jobs: int = 1,
    ignore_cache: bool = False,
    logger: logging.Logger | None = None,
) -> tuple[Any, list[str]]:
    """Warm bond timeseries with binary subdivision on failure."""
    query_list = list(queries)
    if not query_list:
        return pd.DataFrame(), []

    failures: list[str] = []

    def _run(batch, *, depth: int = 0):
        batch_list = list(batch)
        try:
            return tb.get_timeseries(
                start=start,
                end=end,
                queries=batch_list,
                n_jobs=n_jobs,
                ignore_cache=ignore_cache,
                freq=None,
                timestamps=list(timestamps),
            )
        except Exception as exc:
            cusip_label = str(getattr(batch_list[0], "cusip", "<unknown>")) if batch_list else "<empty>"
            if len(batch_list) == 1:
                failures.append(cusip_label)
                if logger is not None:
                    logger.warning("TS UST failed for cusip=%s (%s)", cusip_label, exc)
                return pd.DataFrame()
            if depth == 0 and logger is not None:
                logger.warning(
                    "TS UST failed for %s queries (%s); retrying in smaller batches.",
                    len(batch_list),
                    exc,
                )
            midpoint = max(1, len(batch_list) // 2)
            left = _run(batch_list[:midpoint], depth=depth + 1)
            right = _run(batch_list[midpoint:], depth=depth + 1)
            return _concat_ts_frames([left, right])

    return _run(query_list), failures


def _concat_ts_frames(frames: list) -> pd.DataFrame:
    valid = [f for f in frames if f is not None and not f.empty]
    if not valid:
        return pd.DataFrame()
    return pd.concat(valid, axis=1)


# ---------------------------------------------------------------------------
# Timeseries warming window helper
# ---------------------------------------------------------------------------
def warm_bond_timeseries_window(
    *,
    cusips: list[str],
    values: list[str] | None,
    timestamps: Sequence,
    tb,
    n_jobs: int,
    ignore_cache: bool,
    perf_log_path: Path | None,
    logger: logging.Logger,
    label: str,
) -> dict[str, Any]:
    if not timestamps:
        summary = {
            "event": "ust_timeseries_result",
            "label": label,
            "status": "skipped",
            "rows": 0,
            "cols": 0,
            "query_count": 0,
            "failed_cusips": [],
        }
        _write_perf_event(perf_log_path, summary)
        return summary

    queries = build_frb_queries(cusips, values)
    active_timestamps = list(timestamps)
    started = time.perf_counter()
    df, failed_cusips = _safe_warm_bond_timeseries(
        tb,
        start=active_timestamps[0],
        end=active_timestamps[-1],
        queries=queries,
        timestamps=active_timestamps,
        n_jobs=n_jobs,
        ignore_cache=ignore_cache,
        logger=logger,
    )
    elapsed = time.perf_counter() - started
    status = "ok"
    if failed_cusips:
        status = "partial" if not df.empty else "error"
    summary = {
        "event": "ust_timeseries_result",
        "label": label,
        "status": status,
        "rows": len(df),
        "cols": len(df.columns),
        "query_count": len(queries),
        "failed_cusips": list(failed_cusips),
        "elapsed_seconds": elapsed,
        "first_timestamp": _format_dt(active_timestamps[0]) if active_timestamps else None,
        "last_timestamp": _format_dt(active_timestamps[-1]) if active_timestamps else None,
    }
    _write_perf_event(perf_log_path, summary)
    logger.info(
        "UST timeseries warm complete [%s]: status=%s rows=%s cols=%s failed=%s elapsed=%.2fs",
        label, status, summary["rows"], summary["cols"], len(failed_cusips), elapsed,
    )
    return summary


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------
def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value).strip())


def _parse_time(value: str) -> dt.time:
    token = str(value).strip()
    try:
        return dt.time.fromisoformat(token)
    except ValueError as exc:
        raise ValueError(f"Invalid time '{value}'. Expected HH:MM or HH:MM:SS.") from exc


def _argparse_date(value: str) -> dt.date:
    return _parse_date(value)


def _argparse_time(value: str) -> dt.time:
    return _parse_time(value)


def is_business_day(value: dt.date, calendar: ql.Calendar | None = None) -> bool:
    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    ql_date = ql.Date(value.day, value.month, value.year)
    return bool(cal.isBusinessDay(ql_date))


def iter_business_dates(
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
):
    """Yield each business date in [start_date, end_date]."""
    cal = calendar or ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    current = start_date
    while current <= end_date:
        if is_business_day(current, cal):
            yield current
        current += dt.timedelta(days=1)


def count_business_days(start_date: dt.date, end_date: dt.date) -> int:
    return sum(1 for _ in iter_business_dates(start_date, end_date))


def build_intraday_minute_buckets(
    trade_date: dt.date,
    *,
    session_start: dt.time | None = None,
    session_end: dt.time | None = None,
    freq: str = DEFAULT_FREQ,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[dt.datetime]:
    """Build minute-level timestamps for a single trade date, 07:00-15:00 ET."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_name)
    start_time = session_start or _parse_time(DEFAULT_SESSION_START)
    end_time = session_end or _parse_time(DEFAULT_SESSION_END)
    start_dt = dt.datetime.combine(trade_date, start_time, tzinfo=tz)
    end_dt = dt.datetime.combine(trade_date, end_time, tzinfo=tz)
    timestamps = list(pd.date_range(start=start_dt, end=end_dt, freq=freq))
    return [
        ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        for ts in timestamps
    ]


# ---------------------------------------------------------------------------
# Logging / runtime
# ---------------------------------------------------------------------------
def configure_logging(*, verbose: bool, name: str = "ust_service") -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Suppress noisy per-request HTTP logs from httpx/httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logging.getLogger(name)


def configure_runtime(*, disable_l2: bool) -> None:
    if not disable_l2:
        return
    os.environ["ARBS_SUPABASE_ENABLED"] = "0"
    import importlib
    import Caching.supabase_engine as supabase_engine_module
    importlib.reload(supabase_engine_module)


# ---------------------------------------------------------------------------
# Common argparse groups
# ---------------------------------------------------------------------------
def add_common_ust_args(
    parser: argparse.ArgumentParser,
    *,
    default_source: str,
    default_n_jobs: int = DEFAULT_N_JOBS,
) -> None:
    parser.add_argument("--source", default=default_source, help="FixedRateBondsMDP source.")
    parser.add_argument(
        "--universe",
        choices=("benchmarks", "otr-plus-old", "full-active"),
        default=DEFAULT_UNIVERSE,
        help="Bond universe tier.",
    )
    parser.add_argument(
        "--cusips",
        default="",
        help="Comma-separated extra aliases/CUSIPs to include (e.g. CT10,0231-10,91282CKN6).",
    )
    parser.add_argument(
        "--values",
        default="YTM",
        help="Comma-separated FixedRateBondValue names (e.g. YTM,CLEAN_PRICE,PV01).",
    )
    parser.add_argument("--n-jobs", type=int, default=default_n_jobs, help="Worker count.")
    parser.add_argument("--ignore-cache", action="store_true", help="Force cache refresh.")
    parser.add_argument("--disable-l2", action="store_true", help="Disable Supabase L2.")
    parser.add_argument("--skip-curve-warm", action="store_true", help="Skip raw bond warming.")
    parser.add_argument("--skip-timeseries-warm", action="store_true", help="Skip timeseries warming.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--perf-log-path", default=None, help="Optional JSONL output path.")
    parser.set_defaults(
        show_tqdm=True,
        use_duckdb=DEFAULT_USE_DUCKDB,
        ts_base_dir=DEFAULT_TS_BASE_DIR,
        ts_row_group_size=DEFAULT_TS_ROW_GROUP_SIZE,
        ts_compression=DEFAULT_TS_COMPRESSION,
    )
    parser.add_argument("--show-tqdm", dest="show_tqdm", action="store_true")
    parser.add_argument("--hide-tqdm", dest="show_tqdm", action="store_false")
    parser.add_argument("--use-duckdb", dest="use_duckdb", action="store_true")
    parser.add_argument("--no-use-duckdb", dest="use_duckdb", action="store_false")


def parse_cusips_arg(cusips_str: str) -> list[str]:
    """Parse comma-separated cusips arg into list, stripping whitespace."""
    if not cusips_str or not cusips_str.strip():
        return []
    return [c.strip() for c in cusips_str.split(",") if c.strip()]


def parse_values_arg(values_str: str) -> list[str]:
    """Parse comma-separated values arg into list."""
    if not values_str or not values_str.strip():
        return ["YTM"]
    return [v.strip().upper() for v in values_str.split(",") if v.strip()]


def default_perf_log_path(prefix: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"{prefix}_{stamp}.jsonl"
