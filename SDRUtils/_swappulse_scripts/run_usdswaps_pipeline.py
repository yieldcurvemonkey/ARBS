"""
Single-entry wrapper for the USD swaps SDR pipeline.

Runs classification (ingest_usdswaps) and enriched-tape build
(ingest_usdswaps_tape) as one orchestrated workflow so operators do not
need to remember the two invocations with matching flags.

Subcommands
-----------

    backfill     Explicit date range. Re-classifies + rebuilds tape for a
                 day (or contiguous window). Forces cache invalidation by
                 default so bug-fix deploys actually take effect.

        python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline \
            backfill --date 2026-04-09

        python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline \
            backfill --start 2026-04-07 --end 2026-04-09

    incremental  One catch-up cycle: cursor-based classification delta plus
                 a tape refresh for today. Safe to run on a cron.

        python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline incremental

    service      Continuous loop combining classification + tape on each
                 cycle. Honours the same smart-interval / active-window
                 machinery as ingest_usdswaps --mode service.

        python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline service
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from SDRUtils._swappulse_scripts import ingest_usdswaps, ingest_usdswaps_tape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid date {value!r}; expected YYYY-MM-DD") from exc


def _iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


def _banner(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------


def _run_classification_range(
    *,
    start: date,
    end: date,
    cache_path: Optional[str],
    ignore_cache: bool,
    only_newt: bool,
    dry_run: bool,
) -> None:
    """Run explicit-range classification for an inclusive day window.

    Uses midnight-to-midnight UTC timestamps. The underlying classifier
    buckets by execution date so a [start_00:00, end+1_00:00) window
    captures the full ``end`` day.
    """
    start_ts = pd.Timestamp(start.isoformat(), tz="UTC")
    end_ts = pd.Timestamp((end + timedelta(days=1)).isoformat(), tz="UTC")
    ingest_usdswaps.main(
        start=start_ts,
        end=end_ts,
        cache_path=cache_path,
        ignore_cache=ignore_cache,
        only_newt=only_newt,
        dry_run=dry_run,
    )


def _run_tape_for_dates(
    dates,
    *,
    pg_url: Optional[str],
    use_cache: bool,
    stop_on_error: bool,
    cache_path: Optional[str] = None,
) -> int:
    """Run the enriched tape build one day at a time.

    ``cache_path`` is forwarded to ``ingest_usdswaps_tape.run_ingest`` so the
    tape stage reads the *same* classification parquet cache that the
    classification stage just wrote. Passing None falls through to the shared
    ``_resolve_cache_path`` default inside ``ingest_usdswaps``.
    """
    failures = 0
    resolved_pg_url = ingest_usdswaps_tape.resolve_pg_url(pg_url)
    for d in dates:
        iso = d.isoformat()
        _banner(f"Tape build: {iso}")
        try:
            ingest_usdswaps_tape.run_ingest(
                pg_url=resolved_pg_url,
                start_date=iso,
                end_date=iso,
                use_cache=use_cache,
                cache_path=cache_path,
            )
        except Exception as exc:
            failures += 1
            print(f"Tape build failed for {iso}: {exc}")
            traceback.print_exc()
            if stop_on_error:
                raise
    return failures


# ---------------------------------------------------------------------------
# Subcommand: backfill
# ---------------------------------------------------------------------------


def cmd_backfill(args: argparse.Namespace) -> int:
    if args.date and (args.start or args.end):
        raise SystemExit("--date cannot be combined with --start / --end")

    if args.date:
        start = _parse_date(args.date)
        end = start
    else:
        start = _parse_date(args.start)
        end = _parse_date(args.end) or start

    if start is None:
        raise SystemExit("backfill requires --date or --start")
    if end is None:
        end = start
    if end < start:
        raise SystemExit(f"--end {end} is before --start {start}")

    print(f"Backfill window: {start} -> {end} (inclusive, {(end - start).days + 1} day(s))")
    print(f"  Ignore classification cache: {args.ignore_cache}")
    print(f"  Ignore tape cache:           {args.no_tape_cache}")
    print(f"  Only NEWT/TRAD:              {args.only_newt}")
    print(f"  Dry run:                     {args.dry_run}")
    print(f"  Skip classification:         {args.skip_classification}")
    print(f"  Skip tape:                   {args.skip_tape}")

    if not args.skip_classification:
        _banner(f"Classification: {start} -> {end}")
        _run_classification_range(
            start=start,
            end=end,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
        )
    else:
        print("Skipping classification stage (--skip-classification).")

    if args.dry_run:
        print("Dry run — skipping tape stage as well.")
        return 0

    if args.skip_tape:
        print("Skipping tape stage (--skip-tape).")
        return 0

    failures = _run_tape_for_dates(
        _iter_dates(start, end),
        pg_url=args.pg_url,
        use_cache=not args.no_tape_cache,
        stop_on_error=not args.continue_on_error,
        cache_path=args.cache_path,
    )
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Subcommand: incremental
# ---------------------------------------------------------------------------


def cmd_incremental(args: argparse.Namespace) -> int:
    _banner("Classification: incremental cycle")
    ingest_usdswaps.main_incremental(
        cache_path=args.cache_path,
        ignore_cache=args.ignore_cache,
        only_newt=args.only_newt,
        dry_run=args.dry_run,
        cleanup_orphans=not args.no_cleanup_orphans,
        initial_lookback_minutes=args.initial_lookback_minutes,
        overlap_seconds=args.overlap_seconds,
    )

    if args.dry_run:
        print("Dry run — skipping tape stage.")
        return 0
    if args.skip_tape:
        print("Skipping tape stage (--skip-tape).")
        return 0

    today = _today_utc()
    failures = _run_tape_for_dates(
        [today],
        pg_url=args.pg_url,
        use_cache=not args.no_tape_cache,
        stop_on_error=False,
        cache_path=args.cache_path,
    )
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Subcommand: service
# ---------------------------------------------------------------------------


def cmd_service(args: argparse.Namespace) -> int:
    # Reuse ingest_usdswaps' private window helpers to stay consistent.
    parse_hhmm = ingest_usdswaps._parse_hhmm_to_minutes
    is_active = ingest_usdswaps._is_in_active_window

    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be > 0")
    if args.active_interval_seconds <= 0:
        raise SystemExit("--active-interval-seconds must be > 0")
    if args.inactive_interval_seconds <= 0:
        raise SystemExit("--inactive-interval-seconds must be > 0")
    if args.max_iterations is not None and args.max_iterations <= 0:
        raise SystemExit("--max-iterations must be > 0 when provided")

    active_start_minutes = parse_hhmm(args.active_window_start, "active-window-start")
    active_end_minutes = parse_hhmm(args.active_window_end, "active-window-end")
    try:
        pd.Timestamp.now(tz="UTC").tz_convert(args.market_timezone)
    except Exception as exc:
        raise SystemExit(f"Invalid --market-timezone: {args.market_timezone}") from exc

    cache_path = ingest_usdswaps._resolve_cache_path(args.cache_path)
    engine = ingest_usdswaps.create_db_engine()
    ingest_usdswaps.ensure_schema(engine)

    resolved_pg_url = ingest_usdswaps_tape.resolve_pg_url(args.pg_url)

    print("USD swaps pipeline service (classification + tape)")
    print(f"  Cache:                   {cache_path}")
    print(f"  Ignore classification cache: {args.ignore_cache}")
    print(f"  Ignore tape cache:       {args.no_tape_cache}")
    print(f"  Only NEWT/TRAD:          {args.only_newt}")
    print(f"  Dry run:                 {args.dry_run}")
    print(f"  Initial lookback (min):  {args.initial_lookback_minutes}")
    print(f"  Overlap (sec):           {args.overlap_seconds}")
    print(f"  Tape refresh per cycle:  {not args.skip_tape}")
    if args.smart_intervals:
        print("  Smart intervals:         enabled")
        print(f"  Active interval (sec):   {args.active_interval_seconds}")
        print(f"  Inactive interval (sec): {args.inactive_interval_seconds}")
        print(
            f"  Active window:           {args.active_window_start} - "
            f"{args.active_window_end} ({args.market_timezone})"
        )
        print(f"  Weekdays only:           {args.weekdays_only}")
    else:
        print(f"  Fixed interval (sec):    {args.interval_seconds}")
    if args.max_iterations:
        print(f"  Max iterations:          {args.max_iterations}")

    iteration = 0
    while True:
        iteration += 1
        cycle_wall = pd.Timestamp.now(tz="UTC")
        cycle_mono = time.monotonic()
        _banner(f"Service cycle {iteration} @ {cycle_wall.isoformat()}")

        try:
            ingest_usdswaps.ingest_incremental_once(
                engine,
                cache_path=cache_path,
                ignore_cache=args.ignore_cache,
                only_newt=args.only_newt,
                dry_run=args.dry_run,
                cleanup_orphans=not args.no_cleanup_orphans,
                initial_lookback_minutes=args.initial_lookback_minutes,
                overlap_seconds=args.overlap_seconds,
                force_fetch_end_of_day=True,
                force_fetch_full_market_day=True,
                market_timezone=args.market_timezone,
            )
        except Exception as exc:
            print(f"Classification cycle {iteration} failed: {exc}")
            traceback.print_exc()
            if args.stop_on_error:
                raise

        if not args.dry_run and not args.skip_tape:
            today = _today_utc()
            try:
                ingest_usdswaps_tape.run_ingest(
                    pg_url=resolved_pg_url,
                    start_date=today.isoformat(),
                    end_date=today.isoformat(),
                    use_cache=not args.no_tape_cache,
                    cache_path=cache_path,
                )
            except Exception as exc:
                print(f"Tape cycle {iteration} failed: {exc}")
                traceback.print_exc()
                if args.stop_on_error:
                    raise

        if args.max_iterations is not None and iteration >= args.max_iterations:
            print("Reached max iterations; exiting service loop.")
            break

        if args.smart_intervals:
            local_now = pd.Timestamp.now(tz="UTC").tz_convert(args.market_timezone)
            active = is_active(
                local_now=local_now,
                active_start_minutes=active_start_minutes,
                active_end_minutes=active_end_minutes,
                weekdays_only=args.weekdays_only,
            )
            interval = args.active_interval_seconds if active else args.inactive_interval_seconds
            label = "active market hours" if active else "off-hours"
        else:
            interval = args.interval_seconds
            label = "fixed interval"

        elapsed = time.monotonic() - cycle_mono
        sleep_seconds = max(0.0, interval - elapsed)
        print(f"Sleeping {sleep_seconds:.1f}s ({label}, interval={interval}s).")
        time.sleep(sleep_seconds)

    return 0


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------


def _add_common_flags(sp: argparse.ArgumentParser) -> None:
    """Flags shared across all subcommands. Per-subcommand flags (including
    ``--no-tape-cache`` which has different defaults for backfill vs service)
    are registered by the subcommand itself."""
    sp.add_argument("--pg-url", default=None, help="Postgres URL (overrides env).")
    sp.add_argument("--cache-path", default=None, help="SDR classification cache directory.")
    sp.add_argument("--only-newt", action="store_true", help="Only include NEWT/TRAD events.")
    sp.add_argument("--dry-run", action="store_true", help="Skip all DB writes (both stages).")
    sp.add_argument("--skip-tape", action="store_true", help="Skip the tape-build stage.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_usdswaps_pipeline",
        description=(
            "Orchestrate the USD swaps SDR pipeline: classification ingest "
            "followed by enriched-tape build."
        ),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # backfill
    bp = subparsers.add_parser(
        "backfill",
        help="Re-classify and rebuild tape for an explicit date (range).",
    )
    bp.add_argument("--date", help="Single-day shortcut (YYYY-MM-DD).")
    bp.add_argument("--start", help="Window start date (YYYY-MM-DD).")
    bp.add_argument("--end", help="Window end date (YYYY-MM-DD, inclusive).")
    bp.add_argument(
        "--ignore-cache",
        action="store_true",
        default=True,
        help="Invalidate classification cache (default: on for backfill).",
    )
    bp.add_argument(
        "--use-cache",
        dest="ignore_cache",
        action="store_false",
        help="Reuse classification cache if present (default is to ignore).",
    )
    bp.add_argument(
        "--no-tape-cache",
        action="store_true",
        default=True,
        help="Rebuild tape cache (default: on for backfill).",
    )
    bp.add_argument(
        "--use-tape-cache",
        dest="no_tape_cache",
        action="store_false",
        help="Reuse tape cache if present (default is to rebuild).",
    )
    bp.add_argument("--skip-classification", action="store_true", help="Run tape only.")
    bp.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Do not stop the multi-day loop when one day's tape build fails.",
    )
    _add_common_flags(bp)
    bp.set_defaults(func=cmd_backfill)

    # incremental
    ip = subparsers.add_parser(
        "incremental",
        help="One catch-up cycle plus tape refresh for today.",
    )
    ip.add_argument("--ignore-cache", action="store_true")
    ip.add_argument(
        "--initial-lookback-minutes",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_INITIAL_LOOKBACK_MINUTES", 24 * 60)),
    )
    ip.add_argument(
        "--overlap-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_OVERLAP_SECONDS", 0)),
    )
    ip.add_argument("--no-cleanup-orphans", action="store_true")
    ip.add_argument(
        "--no-tape-cache",
        action="store_true",
        help="Force rebuild of the TradeTape compute cache.",
    )
    _add_common_flags(ip)
    ip.set_defaults(func=cmd_incremental)

    # service
    sp = subparsers.add_parser(
        "service",
        help="Continuous loop: classification + tape per cycle.",
    )
    sp.add_argument("--ignore-cache", action="store_true")
    sp.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_INTERVAL_SECONDS", 30)),
    )
    sp.add_argument(
        "--active-interval-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_ACTIVE_INTERVAL_SECONDS", 30)),
    )
    sp.add_argument(
        "--inactive-interval-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_INACTIVE_INTERVAL_SECONDS", 10 * 60)),
    )
    sp.add_argument(
        "--active-window-start",
        default=os.getenv("SWAPPULSE_INGEST_ACTIVE_WINDOW_START", "07:00"),
    )
    sp.add_argument(
        "--active-window-end",
        default=os.getenv("SWAPPULSE_INGEST_ACTIVE_WINDOW_END", "18:00"),
    )
    sp.add_argument(
        "--market-timezone",
        default=os.getenv("SWAPPULSE_INGEST_MARKET_TIMEZONE", "America/New_York"),
    )
    sp.add_argument(
        "--smart-intervals",
        action="store_true",
        default=True,
        help="Use active/off-hours intervals (default on).",
    )
    sp.add_argument(
        "--no-smart-intervals",
        dest="smart_intervals",
        action="store_false",
        help="Always use --interval-seconds.",
    )
    sp.add_argument(
        "--weekdays-only",
        action="store_true",
        default=True,
        help="Active window applies only Mon-Fri (default on).",
    )
    sp.add_argument(
        "--include-weekends",
        dest="weekdays_only",
        action="store_false",
        help="Active window also applies on weekends.",
    )
    sp.add_argument(
        "--initial-lookback-minutes",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_INITIAL_LOOKBACK_MINUTES", 24 * 60)),
    )
    sp.add_argument(
        "--overlap-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_OVERLAP_SECONDS", 0)),
    )
    sp.add_argument("--no-cleanup-orphans", action="store_true")
    sp.add_argument("--max-iterations", type=int, help="Stop after N cycles (useful for testing).")
    sp.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Exit on the first failed cycle rather than logging and continuing.",
    )
    sp.add_argument(
        "--no-tape-cache",
        action="store_true",
        help="Force rebuild of the TradeTape compute cache each cycle.",
    )
    _add_common_flags(sp)
    sp.set_defaults(func=cmd_service)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
