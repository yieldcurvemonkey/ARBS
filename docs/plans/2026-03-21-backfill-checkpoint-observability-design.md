# Backfill Checkpointing & Observability

**Date:** 2026-03-21
**Scope:** `scripts/stirf_curve_service.py`, `Caching/duckdb_timeseries_cache.py`

## Problem

Large backfills (100+ curves × years of history) have three weaknesses:

1. **No resume.** If the process crashes at day 150/500, re-running reprocesses all 500 days.
   Same problem for incremental appends — running Jan–Dec after Jan–Jun redoes Jan–Jun.
2. **No cumulative observability.** Per-day logs exist but there's no progress %, ETA,
   throughput rate, or memory tracking across the run.
3. **Memory pressure.** Process pool workers are never recycled (`max_tasks_per_child` not set),
   so leaked memory accumulates. No `gc.collect()` after timeseries warm phase.

## Approach: Cache-Implicit Checkpointing

Use the existing cache layers as the checkpoint — no new state files.

### Checkpoint Probe (runs once before day loop)

Two-phase completion check per day:

1. **Raw curves** — `CurveStore.available_dates(curve_name)` returns dates with cached
   raw curves. Single call, returns list of dates.

2. **Computed timeseries** — New `DuckDBTimeseriesCache.available_dates(symbol, start, end)`
   method. Probe with a single "sentinel" tenor symbol (first outright, e.g. `1M`).
   `_warm_timeseries_window` writes all tenors atomically per day — if the sentinel is
   present, all tenors are present.

```
completed_raw = CurveStore.available_dates(curve_name) ∩ requested_range
completed_ts  = duckdb_cache.available_dates(sentinel_symbol, start, end)
fully_done    = completed_raw & completed_ts   (if timeseries warm enabled)
              = completed_raw                  (if --skip-timeseries-warm)
```

Days in `fully_done` are skipped in the iterator. Works for both crash-resume and
incremental-append identically.

### CLI Flags

```
--no-resume / --force    Disable checkpoint skip, reprocess all days (default: resume ON)
--max-tasks-per-child N  Recycle process pool workers after N tasks (default: 50)
```

## Observability: BackfillProgress Tracker

### Dataclass

```python
@dataclass
class BackfillProgress:
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
```

### Heartbeat (emitted after every completed day)

```
INFO Backfill progress for USD-SOFR-1D-Q12STIRT: day 47/500 (9.4%)
     elapsed=12m34s  eta=2h01m  rate=3.7 days/min
     mem=1.2GB  calibration=ok(47) error(0) skipped(12)
     timeseries=ok(47) partial(0) failed_tenors=0
```

Also writes `{"event": "backfill_heartbeat", ...}` to JSONL perf log.

### Memory Reporting

`psutil.Process().memory_info().rss` with fallback to `resource.getrusage` if psutil
unavailable. Included in every heartbeat.

## Memory Pressure Mitigation

### What's already fine

- `retain_all_curves=False` in backfill mode → per-day curve dict cleared
- `_release_barchart_runtime_state()` clears builder cache + `gc.collect()`
- `timeseries_results` holds ~200-byte metadata dicts, not DataFrames
- Per-day DataFrame is ~436KB (139 tenors × 390 rows), GC'd after return

### Changes

1. **Worker recycling** — `--max-tasks-per-child N` (default 50) passed through
   `request_options` to `bulk_get_data`. Prevents slow memory leaks from accumulating.

2. **GC after timeseries warm** — `gc.collect()` at end of day callback, after the
   timeseries DataFrame has gone out of scope.

3. **Memory in heartbeat** — RSS reported every day. Monotonic growth across days is
   the signal to investigate.

## Integration Flow

```
_run_backfill_mode(args)
│
├─ For each curve_name:
│   ├─ 1. Supabase sync (existing, unchanged)
│   │
│   ├─ 2. CHECKPOINT PROBE (new)
│   │   ├─ raw_complete ∩ requested_range
│   │   ├─ ts_complete via sentinel symbol
│   │   ├─ fully_done = raw_complete & ts_complete
│   │   └─ LOG + PERF EVENT
│   │
│   ├─ 3. CREATE BackfillProgress (new)
│   │
│   ├─ 4. iter_daily_minute_buckets → FILTER out fully_done days
│   │
│   ├─ 5. run_bucketed_calibration (existing, augmented day_callback)
│   │   └─ Per day:
│   │       ├─ bulk_get_data (existing)
│   │       ├─ _warm_timeseries_window (existing)
│   │       ├─ progress.record_day()     (new)
│   │       ├─ progress.log_heartbeat()  (new)
│   │       └─ gc.collect()              (new)
│   │
│   ├─ 6. progress.log_summary() (new)
│   └─ 7. Flush pushes (existing)
```

## Files Modified

| File | Change |
|------|--------|
| `scripts/stirf_curve_service.py` | `BackfillProgress` dataclass, checkpoint probe, filtered iterator, heartbeat in day callback, CLI flags |
| `Caching/duckdb_timeseries_cache.py` | `available_dates(symbol, start, end) -> set[date]` method |

No other files touched.
