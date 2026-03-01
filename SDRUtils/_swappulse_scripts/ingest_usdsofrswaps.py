"""
Compatibility shim for legacy SOFR swap ingestion entrypoint.

DEPRECATED:
- Canonical ingestion entrypoint is `ingest_usdswaps.py`.
- This module re-exports canonical symbols and keeps the old CLI path working.
"""

from SDRUtils._swappulse_scripts.ingest_usdswaps import *  # noqa: F401,F403
from SDRUtils._swappulse_scripts.ingest_usdswaps import (
    _to_db_value,
    _parse_timestamp_arg,
    main,
    main_incremental,
    main_service,
    parse_args,
)


if __name__ == "__main__":
    args = parse_args()
    parsed_start = _parse_timestamp_arg(args.start, "start")
    parsed_end = _parse_timestamp_arg(args.end, "end")
    cleanup_orphans = not args.no_cleanup_orphans

    if args.mode == "range":
        main(
            start=parsed_start,
            end=parsed_end,
            days=args.days,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
        )
    elif args.mode == "incremental":
        main_incremental(
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
        )
    else:
        main_service(
            interval_seconds=args.interval_seconds,
            cache_path=args.cache_path,
            ignore_cache=args.ignore_cache,
            only_newt=args.only_newt,
            dry_run=args.dry_run,
            cleanup_orphans=cleanup_orphans,
            initial_lookback_minutes=args.initial_lookback_minutes,
            overlap_seconds=args.overlap_seconds,
            smart_intervals=args.smart_intervals,
            active_interval_seconds=args.active_interval_seconds,
            inactive_interval_seconds=args.inactive_interval_seconds,
            active_window_start=args.active_window_start,
            active_window_end=args.active_window_end,
            market_timezone=args.market_timezone,
            weekdays_only=args.weekdays_only,
            max_iterations=args.max_iterations,
            stop_on_error=args.stop_on_error,
        )
