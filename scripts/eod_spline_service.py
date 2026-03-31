#!/usr/bin/env python
"""EOD cash spline backfill and live-service runner.

This script owns the end-of-day UST cash spline workflow:
1. Fetch all eligible bond pricers from FixedRateBondsMDP for each business date.
2. Build/fit the requested CashSpline (JPM par curve, MMSS, or custom config).
3. Persist fitted splines into the 3-tier cache (memory -> diskcache -> Supabase L2).
4. Optionally warm computed timeseries (SPLINE_SPREAD, SPLINE_RMSE, SPLINE_RMSE_BUCKET)
   via FixedRateBondsTB for downstream backtesting.

Two primary modes:
1. ``backfill``: expand a historical date range into business dates and warm
   both raw splines and computed desk timeseries one trade date at a time.
2. ``live-service``: resolve today's (or explicit) trading date(s) and warm
   the EOD spline plus the full metric timeseries.

Mirrors the architecture of ``eod_curve_service.py``.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

import QuantLib as ql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_FRB_SOURCE = "USTS_FEDINVEST_WSJ_LIVE-QL"
DEFAULT_N_JOBS = 4
DEFAULT_BACKFILL_BATCH_SIZE = 25
DEFAULT_LOG_DIR = REPO_ROOT / "notebooks" / "logs"

# Default CUSIP tenors for TS warming (on-the-runs + first olds)
DEFAULT_TS_CUSIPS = (
    "CT2", "CT3", "CT5", "CT7", "CT10", "CT20", "CT30",
    "O2", "O3", "O5", "O7", "O10", "O20", "O30",
)

# Default maturity buckets for RMSE time series
DEFAULT_RMSE_BUCKETS = (
    "0-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y", "10-15Y", "15-20Y", "20-30Y",
)

logger = logging.getLogger("eod_spline_service")


# ---------------------------------------------------------------------------
# Progress tracking (mirrors eod_curve_service.BackfillProgress)
# ---------------------------------------------------------------------------
def _get_rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
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


@dataclass
class SplineBackfillProgress:
    """Tracks cumulative progress across a multi-day spline backfill."""

    total_days: int
    skipped_days: int
    processed_days: int = 0
    spline_ok: int = 0
    spline_error: int = 0
    ts_ok: int = 0
    ts_error: int = 0
    started_at: float = field(default_factory=time.perf_counter)

    def record_spline(self, *, ok: bool) -> None:
        self.processed_days += 1
        if ok:
            self.spline_ok += 1
        else:
            self.spline_error += 1

    def record_ts(self, *, ok: bool) -> None:
        if ok:
            self.ts_ok += 1
        else:
            self.ts_error += 1

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
        parts.append(f"spline=ok({self.spline_ok}) error({self.spline_error})")
        parts.append(f"ts=ok({self.ts_ok}) error({self.ts_error})")
        return f"Spline Backfill: {' '.join(parts)}"

    def to_perf_event(self) -> dict[str, Any]:
        return {
            "event": "backfill_heartbeat",
            "total_days": self.total_days,
            "skipped_days": self.skipped_days,
            "processed_days": self.processed_days,
            "pct_complete": self.pct_complete,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "eta_seconds": round(self.eta_seconds, 2),
            "rate_days_per_min": round(self.rate_days_per_min, 2),
            "rss_mb": round(_get_rss_mb(), 1),
            "spline_ok": self.spline_ok,
            "spline_error": self.spline_error,
            "ts_ok": self.ts_ok,
            "ts_error": self.ts_error,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value).strip())


def _argparse_date(value: str) -> dt.date:
    try:
        return _parse_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date '{value}'.") from exc


def _write_perf_event(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            payload["_ts"] = dt.datetime.now().isoformat()
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


def _default_perf_log_path() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_LOG_DIR / f"eod_spline_backfill_{stamp}.jsonl"


def _configure_logging(*, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy loggers
    for name in ("httpx", "httpcore", "urllib3", "diskcache"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _is_business_day(d: dt.date, cal: ql.Calendar) -> bool:
    qd = ql.Date(d.day, d.month, d.year)
    return cal.isBusinessDay(qd)


def iter_eod_business_dates(
    *,
    start_date: dt.date,
    end_date: dt.date,
    calendar: ql.Calendar | None = None,
) -> Iterator[dt.date]:
    """Yield each US govt bond business date in [start_date, end_date]."""
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
    return sum(1 for _ in iter_eod_business_dates(start_date=start_date, end_date=end_date, calendar=calendar))


# ---------------------------------------------------------------------------
# Spline cache probe (checkpoint / resume)
# ---------------------------------------------------------------------------
def _probe_cached_spline_dates(
    *,
    start_date: dt.date,
    end_date: dt.date,
    config: Any,
) -> set[dt.date]:
    """Return dates for which a fitted spline is already in the diskcache."""
    from MDP.FixedRateBonds.cash_spline import get_cached_spline

    cached = set()
    for d in iter_eod_business_dates(start_date=start_date, end_date=end_date):
        if get_cached_spline(d, config) is not None:
            cached.add(d)
    return cached


# ---------------------------------------------------------------------------
# Core: build spline for one date
# ---------------------------------------------------------------------------
def _build_spline_for_date(
    *,
    trade_date: dt.date,
    mdp: Any,
    config: Any,
    ignore_cache: bool = False,
) -> tuple[bool, float, dict[str, Any]]:
    """Build and cache a CashSpline for *trade_date*.

    Returns (ok, elapsed_ms, stats_dict).
    """
    from MDP.FixedRateBonds.cash_spline import CashSpline

    t0 = time.perf_counter()
    try:
        spline = mdp.fetch_cash_spline(
            trade_date,
            config=config,
            force_refresh=ignore_cache,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        if spline is None:
            return False, elapsed_ms, {"error": "no data"}

        stats = {
            "n_bonds": len(spline.fit_ttm) if spline.fit_ttm is not None else 0,
            "rmse_bp": round(spline.rmse, 2) if spline.rmse is not None else None,
            "mae_bp": round(spline.mae, 2) if spline.mae is not None else None,
        }
        return True, elapsed_ms, stats

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return False, elapsed_ms, {"error": str(exc)}


# ---------------------------------------------------------------------------
# TS warming: build SPLINE_SPREAD / RMSE / RMSE_BUCKET time series
# ---------------------------------------------------------------------------
def _build_ts_queries(
    *,
    cusips: Sequence[str],
    buckets: Sequence[str],
    config: Any | None = None,
) -> list:
    """Build FixedRateBondQuery objects for TS warming."""
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    queries = []
    vkw = {}
    if config is not None:
        vkw["spline_config"] = config

    # Per-CUSIP spline spread
    for cusip in cusips:
        queries.append(FixedRateBondQuery(
            cusip=cusip,
            value=FixedRateBondValue.SPLINE_SPREAD,
            value_kwargs=vkw,
        ))

    # Whole-curve RMSE (use first cusip as anchor — value is date-level)
    anchor = cusips[0] if cusips else "CT10"
    queries.append(FixedRateBondQuery(
        cusip=anchor,
        value=FixedRateBondValue.SPLINE_RMSE,
        value_kwargs=vkw,
    ))

    # Per-bucket RMSE
    for bucket in buckets:
        queries.append(FixedRateBondQuery(
            cusip=anchor,
            value=FixedRateBondValue.SPLINE_RMSE_BUCKET,
            value_kwargs={**vkw, "bucket": bucket},
        ))

    return queries


def _warm_ts_for_date(
    *,
    trade_date: dt.date,
    ts_builder: Any,
    queries: list,
    n_jobs: int = 4,
) -> tuple[bool, float]:
    """Run TS warming for a single date. Returns (ok, elapsed_ms)."""
    t0 = time.perf_counter()
    try:
        df = ts_builder.get_timeseries(
            start=trade_date,
            end=trade_date,
            queries=queries,
            n_jobs=n_jobs,
            drop_multilevel_cols=True,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ok = df is not None and not df.empty
        return ok, elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.warning("TS warming failed for %s: %s", trade_date, exc)
        return False, elapsed_ms


# ---------------------------------------------------------------------------
# Backfill mode
# ---------------------------------------------------------------------------
def _run_backfill(args: argparse.Namespace) -> int:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from MDP.FixedRateBonds.cash_spline import (
        CashSplineConfig,
        JPM_PAR_CURVE_CONFIG,
        clear_spline_cache,
    )

    perf_log = Path(args.perf_log_path) if args.perf_log_path else _default_perf_log_path()
    config = _resolve_spline_config(args)

    _write_perf_event(perf_log, {
        "event": "run_start",
        "mode": "backfill",
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "config_hash": config.config_hash,
        "config_method": config.method,
    })

    # --- MDP ---
    mdp = FixedRateBondsMDP(source=args.source)

    # --- TS builder (optional) ---
    ts_builder = None
    ts_queries = None
    if not args.skip_timeseries_warm:
        from TB.FixedRateBondsTB import FixedRateBondsTB
        from TB.TimeseriesBuilder import TimeseriesBuilder

        frb_tb = FixedRateBondsTB(mdp, show_tqdm=False)
        ts_builder = TimeseriesBuilder(fixedratebonds_tb=frb_tb)
        ts_queries = _build_ts_queries(
            cusips=args.cusips or list(DEFAULT_TS_CUSIPS),
            buckets=args.buckets or list(DEFAULT_RMSE_BUCKETS),
            config=config,
        )
        logger.info("TS warming: %d queries (%d cusips + %d bucket RMSEs + 1 total RMSE)",
                     len(ts_queries),
                     len(args.cusips or DEFAULT_TS_CUSIPS),
                     len(args.buckets or DEFAULT_RMSE_BUCKETS))

    # --- Count dates ---
    total_days = count_business_days(start_date=args.start_date, end_date=args.end_date)
    logger.info("Backfill range: %s to %s (%d business days)", args.start_date, args.end_date, total_days)

    # --- Checkpoint probe (resume) ---
    skipped_dates: set[dt.date] = set()
    if args.resume and not args.ignore_cache:
        logger.info("Probing cache for completed dates...")
        skipped_dates = _probe_cached_spline_dates(
            start_date=args.start_date,
            end_date=args.end_date,
            config=config,
        )
        if skipped_dates:
            logger.info("Checkpoint: %d/%d dates already cached, will skip.", len(skipped_dates), total_days)
        _write_perf_event(perf_log, {
            "event": "checkpoint_probe",
            "total_days": total_days,
            "skipped_days": len(skipped_dates),
        })

    # --- Progress ---
    progress = SplineBackfillProgress(
        total_days=total_days,
        skipped_days=len(skipped_dates),
    )

    # --- Main loop ---
    had_failures = False
    with mdp:
        for trade_date in iter_eod_business_dates(start_date=args.start_date, end_date=args.end_date):
            if trade_date in skipped_dates:
                continue

            # Phase 1: Build spline
            ok, spline_ms, stats = _build_spline_for_date(
                trade_date=trade_date,
                mdp=mdp,
                config=config,
                ignore_cache=args.ignore_cache,
            )
            progress.record_spline(ok=ok)

            _write_perf_event(perf_log, {
                "event": "spline_result",
                "date": trade_date.isoformat(),
                "ok": ok,
                "elapsed_ms": round(spline_ms, 1),
                **stats,
            })

            if not ok:
                logger.warning("Spline failed for %s: %s", trade_date, stats.get("error", "unknown"))
                had_failures = True
                if args.fail_fast:
                    logger.error("--fail-fast: aborting after first failure.")
                    break
                continue

            # Phase 2: TS warming
            if ts_builder is not None and ts_queries:
                ts_ok, ts_ms = _warm_ts_for_date(
                    trade_date=trade_date,
                    ts_builder=ts_builder,
                    queries=ts_queries,
                    n_jobs=args.n_jobs,
                )
                progress.record_ts(ok=ts_ok)
                _write_perf_event(perf_log, {
                    "event": "ts_result",
                    "date": trade_date.isoformat(),
                    "ok": ts_ok,
                    "elapsed_ms": round(ts_ms, 1),
                })
                if not ts_ok:
                    had_failures = True

            # Heartbeat
            logger.info(progress.format_heartbeat())
            _write_perf_event(perf_log, progress.to_perf_event())

            # GC
            gc.collect()

    # --- Summary ---
    _write_perf_event(perf_log, {
        "event": "run_end",
        "mode": "backfill",
        **progress.to_perf_event(),
    })
    logger.info("Backfill complete: %s", progress.format_heartbeat())
    logger.info("Perf log: %s", perf_log)

    return 1 if had_failures else 0


# ---------------------------------------------------------------------------
# Live-service mode
# ---------------------------------------------------------------------------
def _run_live_service(args: argparse.Namespace) -> int:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    perf_log = Path(args.perf_log_path) if args.perf_log_path else _default_perf_log_path()
    config = _resolve_spline_config(args)
    mdp = FixedRateBondsMDP(source=args.source)

    # Resolve dates
    dates = _resolve_live_dates(args)
    logger.info("Live-service: processing %d date(s): %s", len(dates), [d.isoformat() for d in dates])

    _write_perf_event(perf_log, {
        "event": "run_start",
        "mode": "live-service",
        "dates": [d.isoformat() for d in dates],
    })

    # TS builder
    ts_builder = None
    ts_queries = None
    if not args.skip_timeseries_warm:
        from TB.FixedRateBondsTB import FixedRateBondsTB
        from TB.TimeseriesBuilder import TimeseriesBuilder

        frb_tb = FixedRateBondsTB(mdp, show_tqdm=False)
        ts_builder = TimeseriesBuilder(fixedratebonds_tb=frb_tb)
        ts_queries = _build_ts_queries(
            cusips=args.cusips or list(DEFAULT_TS_CUSIPS),
            buckets=args.buckets or list(DEFAULT_RMSE_BUCKETS),
            config=config,
        )

    had_failures = False
    with mdp:
        for trade_date in dates:
            ok, spline_ms, stats = _build_spline_for_date(
                trade_date=trade_date,
                mdp=mdp,
                config=config,
                ignore_cache=args.ignore_cache,
            )
            logger.info(
                "Spline %s: %s in %.0fms (bonds=%s rmse=%s)",
                trade_date, "OK" if ok else "FAIL", spline_ms,
                stats.get("n_bonds"), stats.get("rmse_bp"),
            )
            _write_perf_event(perf_log, {
                "event": "spline_result",
                "date": trade_date.isoformat(),
                "ok": ok,
                "elapsed_ms": round(spline_ms, 1),
                **stats,
            })

            if ok and ts_builder and ts_queries:
                ts_ok, ts_ms = _warm_ts_for_date(
                    trade_date=trade_date,
                    ts_builder=ts_builder,
                    queries=ts_queries,
                    n_jobs=args.n_jobs,
                )
                logger.info("TS warming %s: %s in %.0fms", trade_date, "OK" if ts_ok else "FAIL", ts_ms)
                if not ts_ok:
                    had_failures = True
            elif not ok:
                had_failures = True

    _write_perf_event(perf_log, {"event": "run_end", "mode": "live-service"})
    return 1 if had_failures else 0


def _resolve_live_dates(args: argparse.Namespace) -> list[dt.date]:
    if hasattr(args, "date") and args.date:
        return sorted(set(args.date))
    start = getattr(args, "start_date", None)
    end = getattr(args, "end_date", None)
    if start and end:
        return list(iter_eod_business_dates(start_date=start, end_date=end))
    return [dt.date.today()]


# ---------------------------------------------------------------------------
# Spline config resolution
# ---------------------------------------------------------------------------
def _resolve_spline_config(args: argparse.Namespace) -> Any:
    """Build CashSplineConfig from CLI args."""
    from MDP.FixedRateBonds.cash_spline import (
        CashSplineConfig,
        JPM_PAR_CURVE_CONFIG,
        MMSS_SPLINE_CONFIG,
        ROLL_SPLINE_CONFIG,
    )

    preset = getattr(args, "preset", "jpm_par")
    if preset == "mmss":
        base = MMSS_SPLINE_CONFIG
    elif preset == "roll":
        base = ROLL_SPLINE_CONFIG
    else:
        base = JPM_PAR_CURVE_CONFIG

    # Apply CLI overrides
    overrides = {}
    method = getattr(args, "spline_method", None)
    if method:
        overrides["method"] = method
    min_ttm = getattr(args, "min_ttm", None)
    if min_ttm is not None:
        overrides["min_ttm"] = min_ttm
    degree = getattr(args, "spline_degree", None)
    if degree is not None:
        overrides["degree"] = degree

    if overrides:
        return base.with_overrides(**overrides)
    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default=DEFAULT_FRB_SOURCE, help="FixedRateBondsMDP source.")
    parser.add_argument("--n-jobs", type=int, default=DEFAULT_N_JOBS, help="Worker count for TS warming.")
    parser.add_argument("--ignore-cache", action="store_true", help="Force cache refresh.")
    parser.add_argument("--skip-timeseries-warm", action="store_true", help="Skip TS warming.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--perf-log-path", default=None, help="JSONL perf log output.")

    # Spline config
    parser.add_argument(
        "--preset",
        choices=("jpm_par", "mmss", "roll"),
        default="jpm_par",
        help="Base spline config preset (default: jpm_par).",
    )
    parser.add_argument("--spline-method", default=None, help="Override spline interpolation method.")
    parser.add_argument("--min-ttm", type=float, default=None, help="Override minimum TTM filter.")
    parser.add_argument("--spline-degree", type=int, default=None, help="Override spline degree.")

    # TS scope
    parser.add_argument("--cusip", dest="cusips", action="append", default=[], help="CUSIP/alias for TS spread warming. Repeatable.")
    parser.add_argument("--bucket", dest="buckets", action="append", default=[], help="Maturity bucket for RMSE TS. Repeatable.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EOD UST cash spline backfill and live-service.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # --- backfill ---
    backfill = subparsers.add_parser("backfill", help="Backfill splines across a date range.")
    _add_common_args(backfill)
    backfill.add_argument("--start-date", required=True, type=_argparse_date, help="Start date (YYYY-MM-DD).")
    backfill.add_argument("--end-date", required=True, type=_argparse_date, help="End date (YYYY-MM-DD).")
    backfill.add_argument("--fail-fast", action="store_true", help="Abort on first spline failure.")
    backfill.add_argument(
        "--no-resume", "--force",
        dest="resume", action="store_false", default=True,
        help="Reprocess all dates even if already cached.",
    )

    # --- live-service ---
    live = subparsers.add_parser("live-service", help="Build today's (or explicit) EOD spline.")
    _add_common_args(live)
    live.add_argument("--date", action="append", type=_argparse_date, default=[], help="Date to process. Repeatable.")
    live.add_argument("--start-date", type=_argparse_date, default=None)
    live.add_argument("--end-date", type=_argparse_date, default=None)

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("EOD Spline Service — mode=%s", args.mode)
    logger.info("=" * 60)

    if args.mode == "backfill":
        return _run_backfill(args)
    elif args.mode == "live-service":
        return _run_live_service(args)
    else:
        parser.error(f"Unknown mode: {args.mode}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
