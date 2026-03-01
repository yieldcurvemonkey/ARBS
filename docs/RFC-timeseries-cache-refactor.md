# RFC: Refactor Timeseries Caching — Replace ZODB

**Status:** Proposal
**Date:** 2026-03-01

---

## 1. Problem Statement

The current caching layer uses **ZODB 6.0.1** (with BTrees, persistent, transaction,
zc.lockfile) for two fundamentally different purposes:

| Layer | What ZODB does today | Pain |
|-------|---------------------|------|
| **Timeseries catalog** (`timeseries_cache.py`) | OOBTree index over Parquet file metadata (path, rows, sha256, min/max timestamps) partitioned by `asset={symbol}/date={YYYY-MM-DD}` | Separate catalog + filesystem is a consistency liability; reads scan all partitions then filter in-memory; no predicate pushdown; SHA256 double-hash overhead |
| **Object cache** (`ZODBCacheMixin.py`, 12+ consumers) | OOBTree key→value store for curves, pricers, raw file bytes, query-result tuples | FileStorage is append-only and grows unbounded; silent fallback to in-memory DemoStorage on lock contention; manual transaction batching (SMALL_TXN_BATCH=32); 5 extra ZODB dependencies; no built-in TTL/expiry |

### Concrete issues

1. **Append-only growth** — FileStorage `.fs` files can reach multi-GB; `pack()` is
   expensive and rarely scheduled.
2. **Lock fragility** — If another process holds the `.lock`, the mixin silently opens a
   throw-away `DemoStorage`. Every write in that session is lost.
3. **Transaction boilerplate** — Every consumer must call `transaction.commit()`,
   `transaction.abort()`, use `with self.batched()`, and manage connection/pool lifecycle.
4. **No native time-range queries** — `read_timeseries` iterates
   `s_idx.by_date.keys()` in Python, opens each Parquet file, concatenates, then trims.
5. **Dependency weight** — ZODB pulls in BTrees, persistent, transaction, zc.lockfile,
   zope.interface (~5 transitive deps) for what amounts to a persistent dict.
6. **No expiry on object cache** — Stale curves/pricers live forever unless manually
   evicted or `force_refresh=True` is passed.

---

## 2. Evaluation of Alternatives

### 2a. Candidates considered

| Candidate | Type | Strengths | Weaknesses for ARBS |
|-----------|------|-----------|---------------------|
| **DuckDB** | Embedded OLAP | Zero-copy Parquet reads; predicate/projection pushdown; SQL; single-file DB; concurrent readers; in-process | Write-heavy MVCC can bottleneck; categorical columns use more memory than pandas |
| **DiskCache** | SQLite-backed k/v | Thread/process safe; built-in TTL, tagging, eviction; FanoutCache for write sharding; pure-Python; zero config | Key-value only — no time-range queries; pickle overhead for large objects |
| **TinyFlux** | CSV-backed TSDB | Pure-Python; time-first design; no dependencies | CSV storage; 100K-point practical ceiling; no Parquet integration; no concurrent writers; too small-scale |
| **OpenTSDB** | Distributed TSDB (HBase) | Proven at scale; rich query language | Requires HBase cluster; massive operational overhead; Java ecosystem; absurd for local caching |
| **SQLite (raw)** | Embedded RDBMS | stdlib; WAL mode for concurrent reads+writes; indexed datetime range queries | Must manage schema, serialization, migrations manually |
| **Polars** | DataFrame library | Fast scan_parquet with pushdown; lazy evaluation | Not a database; no persistence layer; would still need a catalog |

### 2b. Recommended approach: **DuckDB + DiskCache hybrid**

The two ZODB use-cases map cleanly onto two purpose-built tools:

```
┌─────────────────────────────────────────────────────────────┐
│                     Current (ZODB)                          │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │  TSCatalog        │    │  ZODBCacheMixin (OOBTree)    │   │
│  │  (OOBTree index   │    │  12+ consumers: curves,      │   │
│  │   over Parquet    │    │  pricers, raw files, tuples  │   │
│  │   file metadata)  │    │                              │   │
│  └──────────────────┘    └──────────────────────────────┘   │
│         ↓                           ↓                       │
│   Parquet files on disk      ZODB .fs files on disk         │
└─────────────────────────────────────────────────────────────┘
                          ⬇ refactor to ⬇
┌─────────────────────────────────────────────────────────────┐
│                   Proposed (DuckDB + DiskCache)             │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │  DuckDB           │    │  DiskCache (FanoutCache)     │   │
│  │  • Direct Parquet │    │  • SQLite-backed k/v         │   │
│  │    reads (no      │    │  • Built-in TTL & eviction   │   │
│  │    separate       │    │  • Thread & process safe     │   │
│  │    catalog)       │    │  • Sharded writes            │   │
│  │  • SQL range      │    │  • Curves, pricers, raw      │   │
│  │    queries with   │    │    bytes, query tuples        │   │
│  │    pushdown       │    │                              │   │
│  └──────────────────┘    └──────────────────────────────┘   │
│         ↓                           ↓                       │
│   Same Parquet files         ~/.cache/arbs/diskcache/       │
│   (no catalog needed)        (SQLite + sharded files)       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Design

### 3a. DuckDB replaces `timeseries_cache.py` (the catalog + Parquet reads)

**Key insight:** DuckDB can query Parquet files directly with glob patterns, pushing
down date-range filters and column selection. This **eliminates the need for a separate
metadata catalog entirely**.

```python
# BEFORE — ZODB catalog + manual Parquet scan
# (timeseries_cache.py: read_timeseries)
cat = _ensure_catalog(root)
s_idx = _symbol_index(cat, symbol)
dates = [d for d in s_idx.by_date.keys() if s <= d <= e]
parts = []
for d in dates:
    for _, meta in s_idx.by_date[d].items():
        tbl = pq.read_table(Path(meta["path"]), columns=columns)
        parts.append(tbl.to_pandas())
out = pd.concat(parts).sort_index()

# AFTER — DuckDB direct Parquet query
import duckdb

def read_timeseries(symbol: str, start: date, end: date,
                    columns: list[str] | None = None,
                    base_dir: str = "./data/ts") -> pd.DataFrame:
    col_expr = ", ".join(columns) if columns else "*"
    return duckdb.sql(f"""
        SELECT {col_expr}
        FROM read_parquet('{base_dir}/asset={symbol}/date=*//*.parquet',
                          hive_partitioning=true)
        WHERE date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
        ORDER BY _index_ts
    """).df()
```

**Benefits:**
- Partition pruning via Hive-style directory layout (already in place)
- Column projection pushdown (only reads requested columns from Parquet)
- Row-group statistics pushdown (skips row-groups outside date range)
- No catalog to maintain, no ZODB transactions, no vacuum needed
- Parallel I/O across row-groups automatically
- `read_parquet` with glob pattern replaces the entire `TSCatalog` + `SymbolIndex` +
  `_symbol_index` + `_ensure_catalog` machinery

**Writes stay the same** — continue writing partitioned Parquet files with pyarrow
(content-addressed SHA256 naming is a good pattern worth keeping). DuckDB is used
read-side only, which avoids its write-concurrency limitations.

**Negative cache** — replace the ZODB `__MISS__` entries with a small DiskCache instance
keyed by `(symbol, date)` with a TTL (built-in).

**Migration effort:**
- Delete `TSCatalog`, `SymbolIndex`, `_ensure_catalog`, `_symbol_index`,
  `vacuum_catalog`, `register_negative_cache` from `timeseries_cache.py`
- Rewrite `append_timeseries` to drop all ZODB catalog updates (keep the Parquet write
  logic)
- Rewrite `read_timeseries` as a 5-line DuckDB query
- Existing Parquet files on disk require **zero migration** — DuckDB reads them as-is

### 3b. DiskCache replaces `ZODBCacheMixin.py` (the object cache)

**DiskCache** provides a drop-in persistent dict backed by SQLite with built-in TTL,
size limits, thread safety, and process safety. It eliminates all ZODB transaction
management, connection pooling, and lock-fallback complexity.

```python
# BEFORE — ZODBCacheMixin
class CMEFetcher(BaseFetcher, ZODBCacheMixin):
    def _ensure_cache(self):
        self.zodb_open_cache(
            cache_attr="_curve_report_cache",
            path=self.default_cache_path("CMEFetcher_curve_reports"),
        )

    def get_report(self, key: str):
        if key in self._curve_report_cache:
            return self._curve_report_cache[key]
        result = self._fetch_from_cme(key)
        self._curve_report_cache[key] = result
        self.zodb_commit()
        return result

# AFTER — DiskCacheMixin
import diskcache

class DiskCacheMixin:
    """Drop-in replacement for ZODBCacheMixin."""
    _CACHE_REGISTRY: dict[str, diskcache.FanoutCache] = {}
    _REGISTRY_LOCK = threading.Lock()

    def open_cache(self, *, cache_attr: str, directory: str,
                   size_limit: int = 2**32,  # 4 GB default
                   ttl: float | None = None,
                   encode: Callable | None = None,
                   decode: Callable | None = None) -> None:
        with self._REGISTRY_LOCK:
            if cache_attr not in self._CACHE_REGISTRY:
                self._CACHE_REGISTRY[cache_attr] = diskcache.FanoutCache(
                    directory=directory,
                    shards=8,
                    size_limit=size_limit,
                    eviction_policy="least-recently-used",
                )
        cache = self._CACHE_REGISTRY[cache_attr]
        if encode or decode:
            cache = _CodecCacheWrapper(cache, encode, decode)
        setattr(self, cache_attr, cache)

    def close_cache(self) -> None:
        # FanoutCache.close() is safe to call multiple times
        for attr, cache in self._CACHE_REGISTRY.items():
            cache.close()
        self._CACHE_REGISTRY.clear()
```

**Benefits over ZODB:**
- **Built-in TTL** — `cache.set(key, value, expire=3600)` replaces manual
  `expires_at` tracking
- **Built-in eviction** — LRU/LFU eviction with configurable `size_limit` eliminates
  unbounded growth
- **No transaction management** — writes are auto-committed (SQLite WAL mode)
- **Process safety** — multiple processes can read/write the same cache directory
  without lock fallback hacks
- **FanoutCache sharding** — 8 SQLite shards by default, reducing write contention
  vs. single FileStorage
- **Zero new concepts** — dict-like API (`cache[key] = value`, `key in cache`,
  `del cache[key]`)
- **Tagging** — `cache.set(key, value, tag="sofr_curves")` enables bulk invalidation
  by tag (`cache.evict(tag="sofr_curves")`)

**Migration per consumer:**

| Consumer | cache_attr | Migration notes |
|----------|-----------|-----------------|
| `IRSwapsTB` | `_irswaps_tb_cache_v2` | Replace OOBTree with FanoutCache; add TTL for today-skip logic |
| `FixedRateBondsTB` | `_fixedratebonds_tb_cache_v1` | Same pattern; dual-level cache (Parquet + DiskCache) preserved |
| `FixedRateBondsMDP` | `_frb_pricer_cache` | Thread-safe `_threadsafe_cache_get/put` → direct `cache[key]` (already thread-safe) |
| `STIRFutureMDP` | `_stir_pricer_cache` | Same simplification |
| `STIRFutureOptionMDP` | `_stir_option_cache` | Same simplification |
| `USTFuturesMDP` | `USTFuturePricer_Cache`, `USTFutureDeliveryBasket_Cache` | Two caches → two FanoutCache dirs |
| `FXForwardMDP` | `_fxfwd_pricer_cache` | Same simplification |
| `_RLCurveCache` | dynamic (`cache_name`) | Largest consumer; `bulk_get_*` methods drop `with self.batched()` |
| `CMEFetcher` (ql + rl) | `_curve_report_cache` | Direct replacement |
| `ErisFuturesFetcher` (ql + rl) | `eris_raw` | Staged writes (`_stage_cache_write` → `_commit_staged`) simplify to direct `cache.set()` |
| `FedInvestFetcher` | `_fedinvest_prices_cache` | Direct replacement |

### 3c. Fixings cache (`fixings_cache.py`) — no change

The CSV-based fixings cache is small, simple, and purpose-built for the SOFR 8:00 AM
publish-time logic. It has no ZODB dependency. Leave it as-is.

---

## 4. Dependency Impact

### Removed (5 packages)
```
ZODB==6.0.1
BTrees==6.1
persistent==6.1.1
transaction==5.0
zc.lockfile==3.0.post1
```
Also drops transitive: `zope.interface==7.2` (only needed by ZODB/transaction).

### Added (2 packages)
```
duckdb>=1.3.0       # ~25 MB wheel; zero external dependencies
diskcache>=5.6.0    # pure-Python; zero external dependencies
```

**Net: −6 packages, +2 packages, −4 dependencies.**

DuckDB is a single self-contained shared library. DiskCache is pure-Python stdlib only.
Neither requires a running server process.

---

## 5. Migration Strategy

### Phase 1 — DiskCacheMixin (object cache replacement)

**Scope:** Replace `ZODBCacheMixin` with `DiskCacheMixin` across all 12 consumers.

1. Write `Caching/DiskCacheMixin.py` implementing the same interface
   (`open_cache`, `close_cache`, `batched` context manager for backward compat).
2. Update `CodecMapping.py` to wrap `diskcache.FanoutCache` instead of
   `PersistentMapping`.
3. Migrate consumers one-by-one (each is isolated by `cache_attr`):
   - Swap `ZODBCacheMixin` → `DiskCacheMixin` in class inheritance
   - Replace `self.zodb_open_cache(...)` → `self.open_cache(...)`
   - Replace `self.zodb_commit()` → remove (auto-committed)
   - Replace `self.close_zodb()` → `self.close_cache()`
   - Replace `with self.batched():` → remove or keep as no-op for safety
   - Add TTL where appropriate (e.g., `expire=86400` for daily-refresh data)
4. Delete old `.fs` files from `~/.cache/arbs/zodb/dump/` (one-time cleanup).

**Risk:** Low. Each consumer's cache is independent. Can be done incrementally
(one `.fs` file at a time). Old and new caches can coexist during transition.

**Data migration:** Not needed. Caches are ephemeral — they rebuild on first miss.
Rolling out the new mixin simply causes a cold-cache on first run.

### Phase 2 — DuckDB timeseries reads

**Scope:** Replace `timeseries_cache.py` catalog logic with DuckDB Parquet queries.

1. Add `duckdb` to requirements.
2. Rewrite `read_timeseries()` as DuckDB `read_parquet()` with hive partitioning.
3. Simplify `append_timeseries()` to only write Parquet (drop all ZODB catalog
   updates).
4. Move negative-cache to DiskCache with TTL.
5. Delete `TSCatalog`, `SymbolIndex`, `vacuum_catalog`.
6. Update `FixedRateBondsTB` and `IRSwapsTB` to use new `read_timeseries`.

**Risk:** Medium. Requires testing that DuckDB glob + hive partitioning correctly
discovers all existing Parquet files. The existing `asset=.../date=.../` layout is
already standard Hive format, so this should work out-of-the-box.

### Phase 3 — Cleanup

1. Remove ZODB, BTrees, persistent, transaction, zc.lockfile, zope.interface from
   `requirements.txt`.
2. Delete `ZODBCacheMixin.py`, `_DBHandle`, connection pool code.
3. Update `config/settings.example.yaml`: `backend: "diskcache"` (drop `"zodb"`).
4. Update documentation.

---

## 6. Performance Expectations

| Operation | Current (ZODB + pyarrow) | Proposed (DuckDB + DiskCache) |
|-----------|-------------------------|-------------------------------|
| **Read 1 day, 1 symbol** | ~50ms (catalog lookup + pq.read_table) | ~5–10ms (DuckDB partition prune + pushdown) |
| **Read 250 days, 1 symbol** | ~2–5s (iterate 250 OOBTree entries, open 250 files, concat) | ~100–500ms (DuckDB parallel glob, vectorized concat) |
| **Read 250 days, 10 columns from 50** | Same as above (no projection pushdown) | ~50–200ms (only reads 10 columns from Parquet) |
| **Object cache hit** | ~0.1ms (OOBTree lookup + unpickle) | ~0.1ms (SQLite lookup + unpickle) |
| **Object cache miss + write** | ~1–5ms (OOBTree insert + `transaction.commit()`) | ~0.5–2ms (SQLite WAL insert, auto-commit) |
| **Negative cache check** | ~0.1ms (OOBTree lookup + TTL check in Python) | ~0.1ms (DiskCache with native TTL) |
| **Concurrent processes** | Broken (second process falls back to DemoStorage) | Works (DiskCache + DuckDB both support concurrent readers) |

---

## 7. Why Not the Other Candidates

### TinyFlux
- CSV-backed with a practical ceiling of ~100K data points
- No Parquet integration — would require converting all data
- No concurrent writer support
- Good for IoT/hobby projects, not for a professional quant system with
  millions of rows

### OpenTSDB / opentsdb-pandas
- Requires a running HBase cluster (Java, ZooKeeper, HDFS)
- Massive operational overhead for what is fundamentally a local file cache
- Network latency for every read
- The `opentsdb-pandas` connector just wraps HTTP calls to an OpenTSDB server
- Completely disproportionate to the problem

### Raw SQLite
- Viable but requires writing all schema management, TTL logic, serialization,
  migration code from scratch
- DiskCache is essentially "SQLite done right for caching" — uses it internally
  but handles all the boilerplate

### Polars
- Excellent DataFrame library but not a database; would still need something
  to manage the catalog/file discovery
- DuckDB provides the same Parquet pushdown benefits plus SQL, persistence, and
  a query optimizer

---

## 8. Open Questions

1. **DuckDB connection lifecycle** — Should we use a single persistent connection per
   process (fastest, ~0 overhead per query) or open/close per call (safest)?
   Recommendation: single connection stored on a module-level singleton, similar
   to the current `_DB_REGISTRY` pattern.

2. **DiskCache size limits** — What's the right `size_limit` per cache? The current
   ZODB caches have no limit. Recommendation: start with 4 GB per cache dir,
   monitor, and adjust. LRU eviction ensures the hottest data stays cached.

3. **Pickle protocol** — DiskCache uses pickle by default. For security-sensitive
   deployments, consider using `diskcache.Disk` with a custom serializer (e.g.,
   `ujson` for JSON-serializable objects, which covers most of our cache values).

4. **DuckDB version pinning** — DuckDB has frequent releases with occasional breaking
   changes in extension APIs. Pin to a specific minor version (e.g., `duckdb==1.3.1`).
