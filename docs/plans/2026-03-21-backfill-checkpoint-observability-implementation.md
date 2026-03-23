# Backfill Checkpointing & Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add crash-resume checkpointing, cumulative heartbeat logging, and memory pressure mitigation to `stirf_curve_service.py` backfill mode.

**Architecture:** Cache-implicit checkpointing — probe existing CurveStore + DuckDB computed TS cache to detect completed days, skip them on re-run. A `BackfillProgress` tracker emits per-day heartbeats with progress %, ETA, throughput, and memory. Worker recycling via `max_tasks_per_child` prevents slow memory leaks.

**Tech Stack:** Python stdlib (`dataclasses`, `gc`, `os`), existing `DuckDBTimeseriesCache`, existing `CurveStore`, `psutil` (optional, for RSS)

**Design doc:** `docs/plans/2026-03-21-backfill-checkpoint-observability-design.md`

---

### Task 1: Add `available_dates` to DuckDBTimeseriesCache

**Files:**
- Modify: `Caching/duckdb_timeseries_cache.py:137` (after `has_symbol`)
- Test: `tests/test_duckdb_timeseries_cache.py`

**Step 1: Write the failing test**

Add to `tests/test_duckdb_timeseries_cache.py` inside `TestDuckDBTimeseriesCache`:

```python
def test_available_dates_returns_dates_with_data(self, cache):
    dates = [datetime.date(2026, 1, d) for d in (6, 7, 8, 9, 10)]
    cache.upsert_rows(
        "IRS::TEST::1M",
        [(d, "1M RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)],
    )
    result = cache.available_dates(
        "IRS::TEST::1M",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 1, 31),
    )
    assert result == set(dates)

def test_available_dates_empty_when_no_data(self, cache):
    result = cache.available_dates(
        "IRS::TEST::MISSING",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 1, 31),
    )
    assert result == set()

def test_available_dates_filters_by_range(self, cache):
    all_dates = [datetime.date(2026, 1, d) for d in (6, 7, 8, 9, 10)]
    cache.upsert_rows(
        "IRS::TEST::1M",
        [(d, "1M RATE", 4.0) for d in all_dates],
    )
    result = cache.available_dates(
        "IRS::TEST::1M",
        start=datetime.date(2026, 1, 8),
        end=datetime.date(2026, 1, 9),
    )
    assert result == {datetime.date(2026, 1, 8), datetime.date(2026, 1, 9)}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_duckdb_timeseries_cache.py::TestDuckDBTimeseriesCache::test_available_dates_returns_dates_with_data -v`
Expected: FAIL with `AttributeError: 'DuckDBTimeseriesCache' object has no attribute 'available_dates'`

**Step 3: Implement `available_dates`**

Add after `has_symbol` method (line ~143) in `Caching/duckdb_timeseries_cache.py`:

```python
def available_dates(
    self,
    symbol: str,
    start: datetime.date,
    end: datetime.date,
) -> set[datetime.date]:
    """Return the set of trading dates that have cached rows for symbol in [start, end]."""
    with self._lock:
        result = self._conn.execute(
            """
            SELECT DISTINCT trading_date
            FROM computed_timeseries
            WHERE symbol = ? AND trading_date BETWEEN ? AND ?
            """,
            [symbol, start, end],
        ).fetchall()
    return {row[0] for row in result}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_duckdb_timeseries_cache.py -v -k available_dates`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add Caching/duckdb_timeseries_cache.py tests/test_duckdb_timeseries_cache.py
git commit -m "feat(duckdb-cache): add available_dates query for checkpoint probing"
```

---

### Task 2: Add `BackfillProgress` dataclass and helpers

**Files:**
- Modify: `scripts/stirf_curve_service.py:124` (after `DayCalibrationStats`)
- Test: `tests/test_stirf_curve_calibration.py`

**Step 1: Write the failing test**

Add to `tests/test_stirf_curve_calibration.py`:

```python
import time
from scripts.stirf_curve_service import BackfillProgress


class TestBackfillProgress:
    def test_record_day_increments_counters(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=2)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        assert p.processed_days == 1
        assert p.calibration_ok == 1
        assert p.timeseries_ok == 1

    def test_record_day_tracks_errors(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=0)
        p.record_calibration(status="error")
        p.record_timeseries(status="partial", failed_tenors=["1M1Y"])
        assert p.calibration_error == 1
        assert p.timeseries_partial == 1
        assert p.failed_tenors == ["1M1Y"]

    def test_pct_complete_includes_skipped(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=5)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        # 5 skipped + 1 processed = 6/10 = 60%
        assert p.pct_complete == 60.0

    def test_format_heartbeat_returns_string(self):
        p = BackfillProgress(curve_name="TEST", total_days=10, skipped_days=0)
        p.record_calibration(status="ok")
        p.record_timeseries(status="ok", failed_tenors=[])
        msg = p.format_heartbeat()
        assert "TEST" in msg
        assert "1/10" in msg

    def test_to_perf_event_returns_dict(self):
        p = BackfillProgress(curve_name="TEST", total_days=5, skipped_days=1)
        event = p.to_perf_event()
        assert event["event"] == "backfill_heartbeat"
        assert event["curve_name"] == "TEST"
        assert event["total_days"] == 5
        assert event["skipped_days"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_stirf_curve_calibration.py::TestBackfillProgress -v`
Expected: FAIL with `ImportError: cannot import name 'BackfillProgress'`

**Step 3: Implement `BackfillProgress`**

Add after `DayCalibrationStats` (line ~124) in `scripts/stirf_curve_service.py`:

```python
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
```

Note: also add `field` to the existing `from dataclasses import asdict, dataclass` import on line 30.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_stirf_curve_calibration.py::TestBackfillProgress -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add scripts/stirf_curve_service.py tests/test_stirf_curve_calibration.py
git commit -m "feat(backfill): add BackfillProgress tracker with heartbeat formatting"
```

---

### Task 3: Add checkpoint probe function

**Files:**
- Modify: `scripts/stirf_curve_service.py` (new function after `_computed_ts_stores_for_builder`, ~line 850)
- Test: `tests/test_stirf_curve_calibration.py`

**Step 1: Write the failing test**

```python
import datetime as dt
from unittest.mock import MagicMock
from scripts.stirf_curve_service import _probe_completed_days


class TestCheckpointProbe:
    def test_returns_intersection_of_raw_and_ts(self):
        raw_dates = {dt.date(2026, 1, 6), dt.date(2026, 1, 7), dt.date(2026, 1, 8)}
        ts_dates = {dt.date(2026, 1, 7), dt.date(2026, 1, 8), dt.date(2026, 1, 9)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=ts_dates,
            skip_timeseries_warm=False,
        )
        assert result == {dt.date(2026, 1, 7), dt.date(2026, 1, 8)}

    def test_returns_raw_only_when_ts_skipped(self):
        raw_dates = {dt.date(2026, 1, 6), dt.date(2026, 1, 7)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=set(),
            skip_timeseries_warm=True,
        )
        assert result == raw_dates

    def test_returns_empty_when_no_overlap(self):
        raw_dates = {dt.date(2026, 1, 6)}
        ts_dates = {dt.date(2026, 1, 7)}
        result = _probe_completed_days(
            raw_complete_dates=raw_dates,
            ts_complete_dates=ts_dates,
            skip_timeseries_warm=False,
        )
        assert result == set()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_stirf_curve_calibration.py::TestCheckpointProbe -v`
Expected: FAIL with `ImportError`

**Step 3: Implement checkpoint probe**

Add after `_computed_ts_stores_for_builder` (~line 850) in `scripts/stirf_curve_service.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_stirf_curve_calibration.py::TestCheckpointProbe -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add scripts/stirf_curve_service.py tests/test_stirf_curve_calibration.py
git commit -m "feat(backfill): add checkpoint probe functions for resume detection"
```

---

### Task 4: Add CLI flags and wire checkpoint + heartbeat into `_run_backfill_mode`

**Files:**
- Modify: `scripts/stirf_curve_service.py:1910-1937` (argparse), `scripts/stirf_curve_service.py:1973-2161` (`_run_backfill_mode`)

**Step 1: Add CLI flags**

In `_build_parser()`, after line 1937 (`--only-missing-supabase`), add:

```python
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
```

**Step 2: Wire checkpoint probe into `_run_backfill_mode`**

Replace lines 2046-2093 (after `backfill_only` check, before `daily_bucket_iter`) with:

```python
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
            "Prepared backfill service run for %s [%s -> %s]: business_days=%s remaining=%s session_mode=%s timezone=%s perf_log=%s",
            curve_name,
            start_date.isoformat(),
            end_date.isoformat(),
            business_days,
            remaining_days,
            "cme" if args.cme_session else "clock",
            timezone_name,
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
            timestamps: list[dt.datetime],
            _curves: dict[Any, Any],
            day_result: DayCalibrationStats,
        ) -> None:
            progress.record_calibration(status=day_result.status)
            ts_summary: dict[str, Any] = {}
            if ts_builder is not None and day_result.status != "error":
                ts_summary = _warm_timeseries_window(
                    curve_name=curve_name,
                    timestamps=timestamps,
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
        def _filtered_daily_buckets():
            for trade_date, timestamps in iter_daily_minute_buckets(
                start_date=start_date,
                end_date=end_date,
                session_start=session_start,
                session_end=session_end,
                freq=str(args.freq),
                timezone=timezone,
                cme_session=bool(args.cme_session),
            ):
                if trade_date in skipped_days_set:
                    continue
                yield trade_date, timestamps

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
            "max_tasks_per_child": int(args.max_tasks_per_child),
        }
```

Then update the `run_bucketed_calibration` call to use `_filtered_daily_buckets()`:

```python
        try:
            _, daily_results, summary = run_bucketed_calibration(
                curve_mdp=mdp,
                curve_name=curve_name,
                source=str(args.source),
                daily_buckets=_filtered_daily_buckets(),
                request_options=request_options,
                perf_log_path=perf_log_path,
                logger=logger,
                fail_fast=bool(args.fail_fast),
                business_days=remaining_days,
                day_callback=_day_callback,
            )
```

The rest of the function (summary logging, flush) stays unchanged.

**Step 3: Run the full test suite to verify nothing is broken**

Run: `python -m pytest tests/test_stirf_curve_calibration.py -v`
Expected: All existing tests PASS

**Step 4: Manual smoke test**

Run a single-day backfill that's already cached (should skip):
```bash
python scripts/stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT --start-date 2026-03-20 --end-date 2026-03-20 --cme-session
```
Expected: `Checkpoint: skipping 1/1 already-completed days` in output.

Run with `--force` to verify override:
```bash
python scripts/stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT --start-date 2026-03-20 --end-date 2026-03-20 --cme-session --force
```
Expected: No skip, full reprocessing, heartbeat line after day completes.

**Step 5: Commit**

```bash
git add scripts/stirf_curve_service.py
git commit -m "feat(backfill): wire checkpoint probe + heartbeat into backfill mode"
```

---

### Task 5: Pass `max_tasks_per_child` through to process pool

**Files:**
- Modify: `scripts/stirf_curve_service.py` (pass through `request_options`)
- Explore: `MDP/IRSwaps/BARCHART_STIRF/rl.py` (find where `ProcessPoolExecutor` is created)

**Step 1: Find the ProcessPoolExecutor creation in rl.py**

Search for `ProcessPoolExecutor` in `MDP/IRSwaps/BARCHART_STIRF/rl.py`. The `max_tasks_per_child` parameter needs to be passed to the `ProcessPoolExecutor(max_tasks_per_child=N)` constructor.

**Step 2: Thread `max_tasks_per_child` from `request_options` into `bulk_get_data`**

This depends on what `bulk_get_data` accepts. The `request_options` dict already passes through to `build_bulk_request()`. Add `max_tasks_per_child` to the request dict in `build_bulk_request()` (line ~330), then consume it where the executor is created in `rl.py`.

**Note:** This task requires reading `rl.py` to find the exact insertion point. The executor may be created in `_calibrate_bucketed_batch` or similar. If `ProcessPoolExecutor` is created by the MDP and doesn't accept this parameter, add it. If the MDP uses a shared executor, add worker recycling support.

**Step 3: Verify with a multi-day backfill**

Run a 2-3 day backfill and confirm heartbeat shows stable memory:
```bash
python scripts/stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT --start-date 2026-03-18 --end-date 2026-03-20 --cme-session --force --max-tasks-per-child 10
```
Expected: Heartbeat `mem=` value should not grow monotonically.

**Step 4: Commit**

```bash
git add scripts/stirf_curve_service.py MDP/IRSwaps/BARCHART_STIRF/rl.py
git commit -m "feat(backfill): add max_tasks_per_child for process pool worker recycling"
```

---

### Task 6: Final integration test and cleanup

**Files:**
- All modified files

**Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --timeout=120 -x
```
Expected: All PASS

**Step 2: Run a multi-day backfill end-to-end with resume**

```bash
# First run: process 3 days
python scripts/stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT --start-date 2026-03-18 --end-date 2026-03-20 --cme-session

# Second run: same range, should skip all 3
python scripts/stirf_curve_service.py backfill --curve USD-SOFR-1D-Q12STIRT --start-date 2026-03-18 --end-date 2026-03-20 --cme-session
```
Expected: Second run logs `Checkpoint: skipping 3/3 already-completed days`

**Step 3: Verify perf log contains heartbeat events**

```bash
cat notebooks/logs/stirf_curve_calibration_*.jsonl | python -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('event') == 'backfill_heartbeat':
        print(json.dumps(e, indent=2))
        break
"
```
Expected: JSON with all heartbeat fields (pct_complete, eta_seconds, rss_mb, etc.)

**Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(backfill): complete checkpoint + observability integration"
```
