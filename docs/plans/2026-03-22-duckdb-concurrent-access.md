# DuckDB Concurrent Access — Graceful Lock Fallback

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow multiple notebooks to use the DuckDB timeseries cache concurrently without crashing, by falling back to read-only or parquet-only mode when the write lock is held.

**Architecture:** Try read-write → read-only → None (parquet fallback). Write operations no-op in read-only mode. Supabase L2 push and parquet writes are unaffected (CORE preserved).

**Tech Stack:** DuckDB, Python

---

### Task 1: Add read-only mode to DuckDBTimeseriesCache

**Files:**
- Modify: `Caching/duckdb_timeseries_cache.py:60-68`

**Step 1: Add `read_only` parameter to `__init__`**

```python
def __init__(self, db_path: Optional[str] = None, *, read_only: bool = False) -> None:
    self._db_path = db_path or os.environ.get("ARBS_DUCKDB_PATH") or _default_db_path()
    self._read_only = read_only
    Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
    self._conn = duckdb.connect(self._db_path, read_only=read_only)
    self._lock = threading.Lock()
    if not read_only:
        self._init_schema()
```

**Step 2: Make write methods no-op when read-only**

Guard `upsert_rows`, `upsert_many_rows`, `set_watermark` with early return when `self._read_only`.

**Step 3: Expose `read_only` property**

```python
@property
def read_only(self) -> bool:
    return self._read_only
```

---

### Task 2: Add graceful lock fallback to ComputedTimeseriesStore

**Files:**
- Modify: `Caching/computed_timeseries_store.py:87-91`

**Step 1: Replace direct DuckDB construction with try/except cascade**

```python
if use_duckdb:
    from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache
    resolved_duckdb_path = duckdb_path or str(Path(self._opts.base_dir) / "computed_ts.duckdb")
    self._duckdb_cache = _open_duckdb_graceful(resolved_duckdb_path)
```

**Step 2: Implement `_open_duckdb_graceful` helper**

```python
def _open_duckdb_graceful(db_path: str) -> Optional["DuckDBTimeseriesCache"]:
    from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache
    # Try read-write
    try:
        return DuckDBTimeseriesCache(db_path=db_path)
    except Exception:
        pass
    # Try read-only
    try:
        cache = DuckDBTimeseriesCache(db_path=db_path, read_only=True)
        logger.info("DuckDB opened read-only (write lock held by another process): %s", db_path)
        return cache
    except Exception:
        pass
    # Give up — parquet fallback
    logger.warning("DuckDB unavailable (locked), falling back to parquet-only: %s", db_path)
    return None
```

---

### Task 3: Add tests

**Files:**
- Modify: `tests/test_duckdb_timeseries_cache.py`
- Modify: `tests/test_computed_timeseries_store_duckdb.py`

**Step 1: Test read-only mode skips writes**

```python
def test_read_only_skips_writes(self, tmp_path):
    db_path = str(tmp_path / "ro.duckdb")
    rw = DuckDBTimeseriesCache(db_path=db_path)
    rw.upsert_rows("SYM", [(datetime.date(2026, 1, 6), "col", 1.0)])
    rw.close()

    ro = DuckDBTimeseriesCache(db_path=db_path, read_only=True)
    assert ro.read_only is True
    # Writes should no-op
    ro.upsert_rows("SYM", [(datetime.date(2026, 1, 7), "col", 2.0)])
    rows = ro.read_rows("SYM", start=datetime.date(2026, 1, 6), end=datetime.date(2026, 1, 7))
    assert len(rows) == 1  # only the original row
    ro.close()
```

**Step 2: Test graceful fallback in ComputedTimeseriesStore**

```python
def test_duckdb_lock_falls_back_gracefully(self, tmp_path):
    db_path = str(tmp_path / "locked.duckdb")
    blocker = duckdb.connect(db_path)  # holds write lock

    store = ComputedTimeseriesStore(
        base_dir=str(tmp_path / "ts"),
        use_duckdb=True,
        duckdb_path=db_path,
    )
    # Should not crash — falls back to read-only or None
    assert store._duckdb_cache is None or store._duckdb_cache.read_only
    blocker.close()
```

---

### Task 4: Run all tests

Run: `pytest tests/test_duckdb_timeseries_cache.py tests/test_computed_timeseries_store_duckdb.py -v`

### Task 5: Commit

```bash
git add Caching/duckdb_timeseries_cache.py Caching/computed_timeseries_store.py tests/
git commit -m "fix(duckdb): graceful fallback on file lock for concurrent notebook access"
```
