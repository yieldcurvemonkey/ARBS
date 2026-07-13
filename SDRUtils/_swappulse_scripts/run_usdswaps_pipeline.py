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
# Service-loop state persistence (warm start)
# ---------------------------------------------------------------------------

_DTCC_POLL_INTERVAL = 5.0


def _save_service_state(
    cache_path: str,
    *,
    prev_enriched_tape: Optional[pd.DataFrame],
    prev_slice_ids: set,
    prev_trade_count: int,
) -> None:
    """Persist service loop state for warm restart."""
    import pickle
    from pathlib import Path

    state_dir = Path(cache_path) / "service_caches"
    state_dir.mkdir(parents=True, exist_ok=True)

    if prev_enriched_tape is not None and not prev_enriched_tape.empty:
        tape_fp = state_dir / "prev_enriched_tape.parquet"
        tmp = tape_fp.with_suffix(".parquet.tmp")
        try:
            prev_enriched_tape.to_parquet(
                tmp, engine="pyarrow", compression="zstd",
            )
            tmp.replace(tape_fp)
        except Exception as e:
            print(f"  [WARM] Failed to save enriched tape: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    state = {
        "prev_slice_ids": prev_slice_ids,
        "prev_trade_count": prev_trade_count,
    }
    state_fp = state_dir / "service_state.pkl"
    tmp = state_fp.with_suffix(".pkl.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(state_fp)
    except Exception as e:
        print(f"  [WARM] Failed to save service state: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _load_service_state(cache_path: str) -> dict:
    """Load persisted service loop state. Returns dict with available keys."""
    import pickle
    from pathlib import Path

    state_dir = Path(cache_path) / "service_caches"
    result: dict = {}

    tape_fp = state_dir / "prev_enriched_tape.parquet"
    if tape_fp.exists():
        try:
            result["prev_enriched_tape"] = pd.read_parquet(
                tape_fp, engine="pyarrow",
            )
            print(
                f"  [WARM] Loaded enriched tape "
                f"({len(result['prev_enriched_tape'])} rows)"
            )
        except Exception as e:
            print(f"  [WARM] Failed to load enriched tape: {e}")

    state_fp = state_dir / "service_state.pkl"
    if state_fp.exists():
        try:
            with open(state_fp, "rb") as f:
                state = pickle.load(f)
            result.update(state)
            print(
                f"  [WARM] Loaded service state "
                f"(trade_count={state.get('prev_trade_count', '?')})"
            )
        except Exception as e:
            print(f"  [WARM] Failed to load service state: {e}")

    return result


def _interruptible_sleep(
    total_seconds: float,
    dtcc_fetcher,
    prev_slice_ids: set,
) -> bool:
    """Sleep in chunks, polling DTCC for new slices between chunks.

    Returns True if new slices detected (caller should start next cycle).
    Does NOT consume the new slices — the main cycle's check handles that.
    """
    remaining = total_seconds
    while remaining > 0:
        chunk = min(_DTCC_POLL_INTERVAL, remaining)
        time.sleep(chunk)
        remaining -= chunk
        if remaining <= 0:
            break
        try:
            current_ids = set(
                dtcc_fetcher._get_dtcc_intraday_slide_ids(
                    agency="CFTC", asset_class="RATES",
                )
            )
            if current_ids - prev_slice_ids:
                print(
                    f"  [WAKE] New DTCC slice(s) detected during sleep"
                )
                return True
        except Exception:
            pass
    return False


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
    lock_timeout_ms: int = 5_000,
) -> int:
    """Run the enriched tape build one day at a time.

    ``cache_path`` is forwarded to ``ingest_usdswaps_tape.run_ingest`` so the
    tape stage reads the *same* classification parquet cache that the
    classification stage just wrote. Passing None falls through to the shared
    ``_resolve_cache_path`` default inside ``ingest_usdswaps``.
    """
    failures = 0
    resolved_pg_url = ingest_usdswaps_tape.resolve_pg_url(pg_url)
    tape_engine = ingest_usdswaps_tape.create_engine(resolved_pg_url)
    ingest_usdswaps_tape.ensure_schema(tape_engine, lock_timeout_ms=lock_timeout_ms)
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
                engine=tape_engine,
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
        lock_timeout_ms=args.lock_timeout,
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
# Subcommand: migrate
# ---------------------------------------------------------------------------


def cmd_migrate(args: argparse.Namespace) -> int:
    """Run schema migration only — no classification, no tape rebuild."""
    _banner("Schema migration (ensure_schema only)")
    lock_ms = args.lock_timeout
    print(f"  Lock timeout: {lock_ms}ms")
    print(f"  Dry run:      {args.dry_run}")

    if args.dry_run:
        print("Dry run — skipping migration.")
        return 0

    resolved_pg_url = ingest_usdswaps_tape.resolve_pg_url(args.pg_url)
    tape_engine = ingest_usdswaps_tape.create_engine(resolved_pg_url)

    already_current = ingest_usdswaps_tape._schema_already_current(tape_engine)
    if already_current:
        print("Schema is already current — all migration columns present.")
        return 0

    print("Schema needs migration — applying DDL…")
    ingest_usdswaps_tape.ensure_schema(
        tape_engine, lock_timeout_ms=lock_ms,
    )
    print("Migration complete.")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: service
# ---------------------------------------------------------------------------


_FULL_RECLASSIFY_INTERVAL = 3600  # seconds between full reclassifications
_CLEANUP_INTERVAL = 3600  # seconds between orphan cleanup runs


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
    tape_engine = ingest_usdswaps_tape.create_engine(resolved_pg_url)
    ingest_usdswaps_tape.ensure_schema(tape_engine)

    print("USD swaps pipeline service (classification + tape)")
    print(f"  Cache:                   {cache_path}")
    print(f"  Ignore classification cache: {args.ignore_cache}")
    print(f"  Ignore tape cache:       {args.no_tape_cache}")
    print(f"  Only NEWT/TRAD:          {args.only_newt}")
    print(f"  Dry run:                 {args.dry_run}")
    print(f"  Initial lookback (min):  {args.initial_lookback_minutes}")
    print(f"  Overlap (sec):           {args.overlap_seconds}")
    print(f"  Tape refresh per cycle:  {not args.skip_tape}")
    print(f"  Incremental mode:        enabled")
    print(f"  Full reclassify interval: {_FULL_RECLASSIFY_INTERVAL}s")
    print(f"  Cleanup interval:        {_CLEANUP_INTERVAL}s")
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
    if args.force_reclassify:
        print("  Force reclassify:        ON (first cycle will reclassify all trades)")

    # Service state for incremental optimization
    last_full_reclassify: float = 0.0  # monotonic time of last full reclassify
    last_cleanup: float = 0.0  # monotonic time of last orphan cleanup
    prev_classified_df: Optional[pd.DataFrame] = None
    prev_trade_count: int = 0

    # Incremental tape state — carry forward enriched tape across cycles
    prev_enriched_tape: Optional[pd.DataFrame] = None
    prev_trade_ids: set = set()

    # Skip-no-new-slices: track DTCC intraday slice IDs
    prev_slice_ids: set = set()
    _dtcc_fetcher = None  # lazy-init below

    # --- Warm start: load persisted caches from previous process ---
    from SDRUtils.products.usd.usd_swaps import (
        load_service_caches,
        save_service_caches,
        _PACKAGED_DAY_CACHE,
    )

    caches_warm = load_service_caches(cache_path)
    warm_state = _load_service_state(cache_path)
    if caches_warm or warm_state:
        print("  [WARM START] Loaded persisted state from previous run")
        if "prev_enriched_tape" in warm_state:
            prev_enriched_tape = warm_state["prev_enriched_tape"]
            if (
                prev_enriched_tape is not None
                and "trade_id" in prev_enriched_tape.columns
            ):
                prev_trade_ids = set(
                    prev_enriched_tape["trade_id"].astype(str)
                )
        if "prev_slice_ids" in warm_state:
            prev_slice_ids = warm_state["prev_slice_ids"]
        if "prev_trade_count" in warm_state:
            prev_trade_count = warm_state["prev_trade_count"]
        if caches_warm and not args.force_reclassify:
            today_key = str(_today_utc())
            if today_key in _PACKAGED_DAY_CACHE:
                prev_classified_df = _PACKAGED_DAY_CACHE[today_key]
                prev_trade_count = len(prev_classified_df)
                last_full_reclassify = time.monotonic()
                print(
                    f"  [WARM] Skipping cold-start full reclassify "
                    f"({prev_trade_count} cached trades for {today_key})"
                )
        if args.force_reclassify:
            last_full_reclassify = 0.0
            prev_classified_df = None
            prev_trade_count = 0
            prev_enriched_tape = None
            prev_trade_ids = set()
            print("  [FORCE] Discarding warm-start caches; full reclassify on cycle 1")

    iteration = 0
    while True:
        iteration += 1
        cycle_wall = pd.Timestamp.now(tz="UTC")
        cycle_mono = time.monotonic()
        _banner(f"Service cycle {iteration} @ {cycle_wall.isoformat()}")

        # Determine if this cycle should do a full reclassification.
        # When warm start loaded caches, last_full_reclassify was set to
        # ~now so iteration==1 skips the cold-start full reclassify.
        since_full = cycle_mono - last_full_reclassify
        do_full = (
            (iteration == 1 and last_full_reclassify == 0.0)
            or (since_full >= _FULL_RECLASSIFY_INTERVAL)
        )
        do_cleanup = (iteration == 1) or ((cycle_mono - last_cleanup) >= _CLEANUP_INTERVAL)

        # --- Skip-no-new-slices check ---
        # Before running the expensive pipeline, check if DTCC has published
        # new intraday slices since the last cycle. If not, skip entirely.
        if not do_full and prev_classified_df is not None:
            try:
                if _dtcc_fetcher is None:
                    from SDRUtils.data.builder import DTCCFetcher
                    _dtcc_fetcher = DTCCFetcher()
                t_slice = time.monotonic()
                current_slice_ids = set(
                    _dtcc_fetcher._get_dtcc_intraday_slide_ids(
                        agency="CFTC", asset_class="RATES",
                    )
                )
                slice_check_ms = (time.monotonic() - t_slice) * 1000
                new_slices = current_slice_ids - prev_slice_ids
                if not new_slices:
                    elapsed = time.monotonic() - cycle_mono
                    print(
                        f"  No new DTCC slices "
                        f"({len(current_slice_ids)} seen, "
                        f"check: {slice_check_ms:.0f}ms); "
                        f"skipping cycle."
                    )
                    # Jump directly to sleep
                    if args.max_iterations is not None and iteration >= args.max_iterations:
                        print("Reached max iterations; exiting service loop.")
                        break
                    if args.smart_intervals:
                        local_now = pd.Timestamp.now(tz="UTC").tz_convert(
                            args.market_timezone
                        )
                        active = is_active(
                            local_now=local_now,
                            active_start_minutes=active_start_minutes,
                            active_end_minutes=active_end_minutes,
                            weekdays_only=args.weekdays_only,
                        )
                        interval = (
                            args.active_interval_seconds
                            if active
                            else args.inactive_interval_seconds
                        )
                        label = "active market hours" if active else "off-hours"
                    else:
                        interval = args.interval_seconds
                        label = "fixed interval"
                    sleep_seconds = max(0.0, interval - elapsed)
                    print(
                        f"Sleeping {sleep_seconds:.1f}s "
                        f"({label}, interval={interval}s)."
                    )
                    if (
                        _dtcc_fetcher is not None
                        and sleep_seconds > _DTCC_POLL_INTERVAL
                    ):
                        woke = _interruptible_sleep(
                            sleep_seconds, _dtcc_fetcher, prev_slice_ids,
                        )
                        if woke:
                            print("  Starting next cycle (new data)")
                    else:
                        time.sleep(sleep_seconds)
                    continue
                prev_slice_ids = current_slice_ids
                print(
                    f"  {len(new_slices)} new DTCC slice(s) detected "
                    f"(check: {slice_check_ms:.0f}ms)."
                )
            except Exception as exc:
                print(f"  Slice check failed ({exc}); running full cycle.")

        if do_full:
            from SDRUtils.products.usd.usd_swaps import clear_service_caches
            clear_service_caches()
            print(f"  [FULL] Clearing caches, full reclassification")
            last_full_reclassify = cycle_mono
            prev_enriched_tape = None
            prev_trade_ids = set()
            prev_slice_ids = set()

        use_incremental = not do_full and (prev_classified_df is not None)

        classified_df = None
        try:
            t_classify = time.monotonic()
            classified_df = ingest_usdswaps.ingest_incremental_once(
                engine,
                cache_path=cache_path,
                ignore_cache=(args.ignore_cache or args.force_reclassify) if do_full else False,
                only_newt=args.only_newt,
                dry_run=args.dry_run,
                cleanup_orphans=do_cleanup,
                initial_lookback_minutes=args.initial_lookback_minutes,
                overlap_seconds=args.overlap_seconds,
                force_fetch_end_of_day=True,
                force_fetch_full_market_day=True,
                market_timezone=args.market_timezone,
                use_incremental=use_incremental,
                prev_trade_count=0 if do_full else prev_trade_count,
                skip_classification_upsert=not do_full,
            )
            t_classify_done = time.monotonic()
            print(
                f"  [TIMING] Classification: "
                f"{t_classify_done - t_classify:.1f}s"
            )
        except Exception as exc:
            print(f"Classification cycle {iteration} failed: {exc}")
            traceback.print_exc()
            if args.stop_on_error:
                raise

        if do_cleanup:
            last_cleanup = cycle_mono

        new_trade_count = len(classified_df) if classified_df is not None else 0
        has_new_trades = (classified_df is not None) and (
            new_trade_count != prev_trade_count
        )

        # Compute new trade_ids for incremental tape.
        # Delta is computed against prev_enriched_tape (not prev_trade_ids)
        # so that trades from a failed tape cycle are re-enriched next time.
        current_trade_ids: set = set()
        new_trade_ids_delta: set = set()
        if classified_df is not None and "trade_id" in classified_df.columns:
            current_trade_ids = set(classified_df["trade_id"].astype(str))
            if (
                prev_enriched_tape is not None
                and "trade_id" in prev_enriched_tape.columns
            ):
                enriched_ids = set(
                    prev_enriched_tape["trade_id"].astype(str)
                )
                new_trade_ids_delta = current_trade_ids - enriched_ids
            else:
                new_trade_ids_delta = current_trade_ids

        if classified_df is not None:
            prev_classified_df = classified_df
            prev_trade_count = new_trade_count

        if not args.dry_run and not args.skip_tape:
            if classified_df is not None and (has_new_trades or do_full):
                today = _today_utc()
                try:
                    t_tape = time.monotonic()
                    can_incremental = (
                        not do_full
                        and prev_enriched_tape is not None
                        and new_trade_ids_delta
                        and len(new_trade_ids_delta) < len(classified_df)
                    )

                    if can_incremental:
                        print(
                            f"  Incremental tape: "
                            f"{len(new_trade_ids_delta)} new trade(s) "
                            f"/ {len(classified_df)} total"
                        )
                        enriched, _stats = (
                            ingest_usdswaps_tape.run_ingest_incremental(
                                engine=tape_engine,
                                classified_df=classified_df,
                                prev_enriched=prev_enriched_tape,
                                new_trade_ids=new_trade_ids_delta,
                                as_of_date=today.isoformat(),
                            )
                        )
                        prev_enriched_tape = enriched
                    else:
                        # Full path: pass prev_enriched=None so
                        # compute_incremental falls back to full
                        # compute(). Returns enriched tape for carry-
                        # forward — no double computation.
                        print("  Full tape rebuild")
                        enriched, _stats = (
                            ingest_usdswaps_tape.run_ingest_incremental(
                                engine=tape_engine,
                                classified_df=classified_df,
                                prev_enriched=None,
                                new_trade_ids=current_trade_ids,
                                as_of_date=today.isoformat(),
                            )
                        )
                        prev_enriched_tape = enriched

                    t_tape_done = time.monotonic()
                    print(
                        f"  [TIMING] Tape stage: "
                        f"{t_tape_done - t_tape:.1f}s"
                    )
                except Exception as exc:
                    print(f"Tape cycle {iteration} failed: {exc}")
                    traceback.print_exc()
                    if args.stop_on_error:
                        raise
            elif not has_new_trades and not do_full:
                print(
                    "  No new trades since last cycle; "
                    "skipping tape rebuild."
                )

        # Update trade_id state for next cycle
        if current_trade_ids:
            prev_trade_ids = current_trade_ids

        # --- Persist caches + state for warm restart ---
        try:
            save_service_caches(cache_path)
            _save_service_state(
                cache_path,
                prev_enriched_tape=prev_enriched_tape,
                prev_slice_ids=prev_slice_ids,
                prev_trade_count=prev_trade_count,
            )
        except Exception as e:
            print(f"  [WARM] Cache save failed: {e}")

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
        print(
            f"Sleeping {sleep_seconds:.1f}s ({label}, interval={interval}s). "
            f"Cycle total: {elapsed:.1f}s."
        )
        if (
            _dtcc_fetcher is not None
            and sleep_seconds > _DTCC_POLL_INTERVAL
        ):
            woke = _interruptible_sleep(
                sleep_seconds, _dtcc_fetcher, prev_slice_ids,
            )
            if woke:
                print("  Starting next cycle (new data)")
        else:
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
    bp.add_argument(
        "--lock-timeout",
        type=int,
        default=5_000,
        help="DDL lock_timeout in milliseconds (default: 5000).",
    )
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
        default=int(os.getenv("SWAPPULSE_INGEST_INTERVAL_SECONDS", 10)),
    )
    sp.add_argument(
        "--active-interval-seconds",
        type=int,
        default=int(os.getenv("SWAPPULSE_INGEST_ACTIVE_INTERVAL_SECONDS", 10)),
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
        "--force-reclassify",
        action="store_true",
        help="Force full reclassification of every trade on the first cycle, ignoring warm-start caches.",
    )
    sp.add_argument(
        "--no-tape-cache",
        action="store_true",
        help="Force rebuild of the TradeTape compute cache each cycle.",
    )
    _add_common_flags(sp)
    sp.set_defaults(func=cmd_service)

    # migrate
    mp = subparsers.add_parser(
        "migrate",
        help="Run schema migration only (ensure_schema). No classification or tape rebuild.",
    )
    mp.add_argument(
        "--lock-timeout",
        type=int,
        default=90_000,
        help="DDL lock_timeout in milliseconds (default: 90000 for migrations).",
    )
    _add_common_flags(mp)
    mp.set_defaults(func=cmd_migrate)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
