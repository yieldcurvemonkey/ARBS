# Compute Once, Read Everywhere (CORE) — Distributed Cache Design

**Date:** 2026-03-16
**Status:** Approved
**Approach:** Dual-Track (Structured CurveStore + Generic KV)

## 1. Overview

Transition the ARBS caching architecture from a local, duplicated-compute model to a "Compute Once, Read Everywhere" (CORE) paradigm. Curves are solved once by a centralized producer (the existing local workflow) and persisted to Supabase/Postgres. All researchers and production systems read pre-computed results.

### Design Constraints

| Decision | Choice |
|----------|--------|
| Scale | 1-3 researchers, near-term |
| Scope | Everything — CurveStore artifacts + DiskCacheMixin generics |
| L1 Invalidation | TTL-based (simple) |
| Blob storage | Postgres BYTEA directly |
| Serialization | Cloudpickle now, refactor to typed serializers later |
| Producer model | Existing local workflow + write-through |

### Architecture Summary

Two distinct subsystems, each optimized for its access pattern:

1. **CurveStore Sync** (`SupabaseCurveSync`): Hybrid relational-blob schema for structured curve data. Tagged priority snapshots (EOD, FOMC, CPI) queryable via SQL. Daily Parquet blobs for bulk backtesting.

2. **LayeredCacheMixin**: Drop-in replacement for `DiskCacheMixin`. L1 (local diskcache) + L2 (Supabase generic KV table). TTL-based freshness. Zero interface changes for consuming MDPs.

```
                        PRODUCER (existing workflow)
                                  |
                    ┌─────────────┼─────────────┐
                    |             |              |
              CurveStore    DiskCacheMixin    Fixings
              .write_day()  obj.cache[k]=v   cache.set()
                    |             |              |
                    v             v              v
              ┌───────────────────────────────────────┐
              |        LOCAL L1 (unchanged)            |
              |  Parquet/Hive    diskcache.FanoutCache  |
              └──────────────┬────────────────────────┘
                             |  write-through (background)
                             v
              ┌───────────────────────────────────────┐
              |        SUPABASE L2 (new)               |
              |  curve_snapshots    arbs_kv_cache_v1   |
              |  curve_intraday_blocks                 |
              └───────────────────────────────────────┘
                             |
                             v
              ┌───────────────────────────────────────┐
              |        CONSUMER (researcher node)      |
              |  L1 check → L2 fallback → L1 hydrate  |
              └───────────────────────────────────────┘
```

## 2. Postgres Schema

### 2.1 Connection Infrastructure

Single SQLAlchemy engine per process, singleton pattern, using Supabase's connection pooler.

```python
# Caching/supabase_engine.py
_engine: Engine | None = None
_lock = threading.Lock()

def get_engine() -> Engine:
    """Thread-safe singleton SQLAlchemy engine.

    Config:
    - pool_size=3, max_overflow=2
    - Uses Supabase pooler endpoint (port 6543)
    - SUPABASE_DATABASE_URL from environment
    """
```

Auto-disables if `SUPABASE_DATABASE_URL` is not set. All downstream code checks `SUPABASE_ENABLED` before attempting L2 operations.

### 2.2 Table: `curve_snapshots` (Relational — Priority Curves)

Tagged, queryable curves for instant access to EOD, FOMC, CPI snapshots.

```sql
CREATE TABLE curve_snapshots (
    curve_name VARCHAR NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,
    trading_date DATE NOT NULL,
    session_minute SMALLINT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    cfg_hash VARCHAR NOT NULL,
    reference_key VARCHAR NOT NULL,
    interpolation VARCHAR NOT NULL,
    source_variant VARCHAR NOT NULL,
    node_dates DATE[] NOT NULL,
    discount_factors FLOAT8[] NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (curve_name, timestamp_utc)
);

CREATE INDEX idx_snapshots_tags ON curve_snapshots USING GIN (tags);
CREATE INDEX idx_snapshots_date ON curve_snapshots (curve_name, trading_date);
```

**Scale:** ~5-10 rows per asset per day. ~12,500 rows per asset over 5 years. Trivial for Postgres.

**Query pattern A — "EOD curves for 5 years":**
```sql
SELECT timestamp_utc, node_dates, discount_factors
FROM curve_snapshots
WHERE curve_name = 'USD-SOFR-1D' AND 'EOD' = ANY(tags)
ORDER BY timestamp_utc;
```

### 2.3 Table: `curve_intraday_blocks` (Blob — Bulk Backtesting)

One compressed Parquet blob per curve per day. Contains all minutely snapshots.

```sql
CREATE TABLE curve_intraday_blocks (
    trading_date DATE NOT NULL,
    curve_name VARCHAR NOT NULL,
    data_format VARCHAR NOT NULL DEFAULT 'parquet_zstd',
    row_count INTEGER NOT NULL,
    payload BYTEA NOT NULL,
    sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (trading_date, curve_name)
);
```

**Scale:** 1 row per asset per day. ~1,250 rows per asset over 5 years. Blob sizes: 80KB-500KB compressed.

**Query pattern B — "5-year minutely backtest":**
```sql
SELECT trading_date, payload
FROM curve_intraday_blocks
WHERE curve_name = 'USD-SOFR-1D'
  AND trading_date BETWEEN '2021-01-01' AND '2026-01-01'
ORDER BY trading_date;
```

### 2.4 Table: `arbs_kv_cache_v1` (Generic KV Store)

Universal key-value store replacing DiskCacheMixin's remote persistence layer.

```sql
CREATE TABLE arbs_kv_cache_v1 (
    cache_ns VARCHAR NOT NULL,
    cache_key VARCHAR NOT NULL,
    key_repr TEXT,
    payload BYTEA NOT NULL,
    serializer VARCHAR NOT NULL DEFAULT 'cloudpickle',
    ttl_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cache_ns, cache_key)
);

CREATE INDEX idx_kv_updated ON arbs_kv_cache_v1 (updated_at);
```

**Scale:** ~14.3M records initially (full diskcache migration). Grows with new MDP computations.

## 3. CurveStore Supabase Sync

### 3.1 `SupabaseCurveSync` Class

New module: `Caching/supabase_curve_sync.py`

The existing `CurveStore` class stays intact. `SupabaseCurveSync` handles bidirectional sync between local Parquet and Supabase.

### 3.2 Write Path (Producer)

When `CurveStore.write_day()` completes its local atomic Parquet write:

```
CurveStore.write_day(curve_name, trading_date, snapshots)
  ├── Local Parquet write (existing, unchanged)
  └── SupabaseCurveSync.push_day(curve_name, trading_date)  [background thread]
       ├── Read local Parquet file bytes
       ├── UPSERT into curve_intraday_blocks (payload=bytes, sha256=hash)
       └── Extract priority snapshots (EOD/FOMC/CPI based on event calendar)
            └── UPSERT into curve_snapshots with appropriate tags
```

Background write is fire-and-forget with retry. Local write always succeeds immediately. Supabase failure is logged, not raised.

### 3.3 Read Path (Consumer)

Modified `CurveStore.read_raw_day()`:

```
CurveStore.read_raw_day(curve_name, date)
  ├── Local Parquet exists? → return immediately (fast path, ~5ms)
  └── SUPABASE_ENABLED and L2_READ?
       ├── SupabaseCurveSync.pull_day(curve_name, date)
       │    ├── SELECT payload FROM curve_intraday_blocks WHERE ...
       │    ├── Write blob to local Parquet directory (L1 hydration)
       │    └── Return via normal local read path
       └── If Supabase miss → raise FileNotFoundError (as today)
```

### 3.4 Bulk Pre-fetch for Backtesting

```python
def prefetch_range(
    self, curve_name: str, start: date, end: date
) -> list[date]:
    """Download all missing days from Supabase to local Parquet.

    1. List locally available dates
    2. Query Supabase for missing dates only
    3. Stream blobs and write to local Parquet directory
    4. Returns list of dates that were fetched
    """
```

Called before the pricing loop starts. Once complete, the backtest runs 100% against local NVMe.

### 3.5 Priority Tags & Event Calendar

`CurveTagConfig` class determines which timestamps get tagged in `curve_snapshots`:

```python
class CurveTagConfig:
    @staticmethod
    def get_tags(snapshot: CurveSnapshot, event_calendar: dict) -> list[str]:
        tags = []
        if snapshot.session_minute == 0:
            tags.append("OPEN")
        if is_last_snapshot_of_day(snapshot):
            tags.append("EOD")
        event_date = snapshot.trading_date
        if event_date in event_calendar:
            event = event_calendar[event_date]
            if snapshot_near_event_time(snapshot, event):
                tags.append(event["tag"])  # "FOMC_RATE_DECISION", "CPI_PRINT", etc.
        return tags
```

Event calendar: simple YAML or dict mapping dates to `{tag, time_utc}`. Can be populated from Bloomberg calendar, FRED release schedule, or manual entries.

## 4. LayeredCacheMixin — Generic KV Store

### 4.1 Class Hierarchy

```python
class LayeredCacheMixin(DiskCacheMixin):
    """Drop-in replacement for DiskCacheMixin with L2 Supabase persistence."""

    L2_ENABLED: ClassVar[bool] = True
    L2_READ: ClassVar[bool] = True
    L2_WRITE: ClassVar[bool] = True
    L2_TTL_SECONDS: ClassVar[int] = 300  # 5 minutes
```

New module: `Caching/layered_cache_mixin.py`

### 4.2 LayeredDictProxy

Wraps the existing L1 diskcache with L2 Supabase fallback:

```python
class LayeredDictProxy(MutableMapping):
    def __init__(self, l1_cache, cache_ns: str, config: LayeredCacheConfig):
        self._l1 = l1_cache          # Existing diskcache.FanoutCache or CodecMapping
        self._ns = cache_ns           # e.g., "USTFuturePricer_Cache"
        self._config = config

    def __getitem__(self, key):
        cache_key = self._hash_key(key)

        # 1. L1 check
        try:
            value, stored_at = self._l1_get_with_timestamp(cache_key)
            if not self._is_stale(stored_at):
                return value
            # Stale — fall through to L2
        except KeyError:
            pass

        # 2. L2 check (if enabled)
        if self._config.l2_read:
            row = self._l2_get(cache_key)
            if row is not None:
                value = self._deserialize(row.payload, row.serializer)
                self._l1_set(cache_key, value)  # Hydrate L1
                return value

        raise KeyError(key)

    def __setitem__(self, key, value):
        cache_key = self._hash_key(key)

        # 1. L1 write (always, synchronous)
        self._l1_set(cache_key, value)

        # 2. L2 write (background, best-effort)
        if self._config.l2_write:
            self._l2_set_async(cache_key, key, value)

    def _hash_key(self, key) -> str:
        return hashlib.sha256(cloudpickle.dumps(key)).hexdigest()

    def _is_stale(self, stored_at: float) -> bool:
        return (time.time() - stored_at) > self._config.ttl_seconds
```

### 4.3 Modified `open_cache()`

`LayeredCacheMixin.open_cache()` overrides `DiskCacheMixin.open_cache()`:

```python
def open_cache(self, *, cache_attr: str, path: str, encode=None, decode=None):
    # Call parent to set up L1 diskcache as normal
    super().open_cache(cache_attr=cache_attr, path=path, encode=encode, decode=decode)

    if SUPABASE_ENABLED and self.L2_ENABLED:
        # Wrap the L1 cache with LayeredDictProxy
        l1_cache = getattr(self, cache_attr)
        cache_ns = path.split("/")[-1]  # Extract namespace from path
        proxy = LayeredDictProxy(l1_cache, cache_ns, self._l2_config())
        setattr(self, cache_attr, proxy)
```

### 4.4 Per-MDP Configuration

Each MDP subclass can override toggles:

```python
class USTFuturesMDP(LayeredCacheMixin, MarketDataProvider):
    L2_TTL_SECONDS = 600  # Bond data — 10 min TTL

class IRSwapsMDP(LayeredCacheMixin, MarketDataProvider):
    L2_TTL_SECONDS = 120  # Rate curves — 2 min TTL

class STIRFutureMDP(LayeredCacheMixin, MarketDataProvider):
    L2_TTL_SECONDS = 60   # Futures — 1 min TTL
```

### 4.5 Failure Modes

| Scenario | Behavior |
|----------|----------|
| Supabase unreachable | L1 serves normally, L2 writes silently dropped, warning logged |
| L1 miss + L2 miss | `KeyError` raised → MDP computes fresh → writes to both L1 and L2 |
| L1 stale + L2 has newer data | L1 refreshed from L2 payload |
| Cloudpickle deserialization fails | Warning logged, treat as miss, recompute |
| `SUPABASE_DATABASE_URL` not set | Entire L2 layer disabled, operates as pure DiskCacheMixin |

## 5. Migration Strategy

### 5.1 Existing Diskcache Data

Batch migration script: `scripts/migrate_diskcache_to_supabase.py`

```python
def migrate_namespace(cache_dir: str, cache_ns: str):
    """Walk a FanoutCache and bulk-insert into arbs_kv_cache_v1."""
    cache = diskcache.FanoutCache(cache_dir)
    batch = []
    for key in cache:
        value = cache[key]
        row = {
            "cache_ns": cache_ns,
            "cache_key": sha256(cloudpickle.dumps(key)),
            "key_repr": repr(key)[:500],
            "payload": cloudpickle.dumps(value),
            "serializer": "cloudpickle",
        }
        batch.append(row)
        if len(batch) >= 10_000:
            execute_values(cursor, upsert_sql, batch)
            batch.clear()
```

Estimated: 14.3M records, 2-3 hours one-time migration.

### 5.2 Existing CurveStore Parquet Data

```python
def backfill_curve_store(store: CurveStore, sync: SupabaseCurveSync):
    """Push all local Parquet data to Supabase."""
    for curve_name in store.list_curves():
        for trading_date in store.available_dates(curve_name):
            sync.push_day(curve_name, trading_date)
```

## 6. Rollout Plan

### Phase 1: Infrastructure (Week 1)
- Create Supabase tables (3 tables + indexes)
- Implement `Caching/supabase_engine.py`
- Add `SUPABASE_DATABASE_URL` to environment config
- Write and run DDL scripts

### Phase 2: CurveStore Sync (Week 2-3)
- Implement `Caching/supabase_curve_sync.py` (`SupabaseCurveSync`)
- Wire into `CurveStore.write_day()` (background write-through)
- Wire into `CurveStore.read_raw_day()` / `read_raw_nodes()` (L2 fallback)
- Implement `CurveTagConfig` with event calendar
- Run backfill script for existing Parquet data

### Phase 3: LayeredCacheMixin (Week 3-4)
- Implement `Caching/layered_cache_mixin.py`
- Implement `LayeredDictProxy` with TTL-based L1/L2 fall-through
- Re-parent MDPs: `DiskCacheMixin` → `LayeredCacheMixin`
- Run diskcache migration script

### Phase 4: Shadow Mode & Validation (Week 4-5)
- Deploy with `L2_WRITE = True`, `L2_READ = False` (shadow writes only)
- Validate: compare L1 vs L2 for identical keys across namespaces
- Enable `L2_READ = True` per-MDP, starting with lowest-risk (FixedRateBondsMDP)
- Monitor: connection pool usage, payload sizes, write latency
- Graduate remaining MDPs to full L2 read

### Graceful Degradation Guarantee

At every phase, if `SUPABASE_DATABASE_URL` is unset or Supabase is unreachable, the system operates identically to today. No code path breaks. No researcher is blocked.

## 7. New Files

| File | Purpose |
|------|---------|
| `Caching/supabase_engine.py` | Singleton SQLAlchemy engine + `SUPABASE_ENABLED` flag |
| `Caching/supabase_curve_sync.py` | `SupabaseCurveSync` — push/pull/prefetch for CurveStore |
| `Caching/layered_cache_mixin.py` | `LayeredCacheMixin` + `LayeredDictProxy` |
| `Caching/curve_tag_config.py` | Priority tag logic + event calendar |
| `scripts/migrate_diskcache_to_supabase.py` | One-time diskcache → Postgres migration |
| `scripts/backfill_curve_store.py` | One-time Parquet → Postgres backfill |
| `config/event_calendar.yaml` | FOMC/CPI/NFP dates and times |
| `sql/create_tables.sql` | DDL for all 3 tables + indexes |

## 8. Modified Files

| File | Change |
|------|--------|
| `Caching/curve_store.py` | Add L2 fallback in `read_raw_day()`, background sync in `write_day()` |
| `Caching/DiskCacheMixin.py` | No changes (LayeredCacheMixin extends it) |
| `MDP/*/` (all MDPs) | Change base class from `DiskCacheMixin` to `LayeredCacheMixin` |
| `.env` | Add `SUPABASE_DATABASE_URL` |
| `requirements.txt` | Add `sqlalchemy`, `psycopg2-binary`, `cloudpickle` |

## 9. Future Work (Out of Scope)

- **Vectorized matrix pricing**: `read_raw_matrix()` returning 3D NumPy arrays for Numba-compiled swap pricing. Separate design cycle.
- **Type-aware serialization**: Migrate from cloudpickle to typed serializers (Arrow for DataFrames, JSON for dataclasses) per namespace.
- **LISTEN/NOTIFY invalidation**: Replace TTL with real-time Postgres notifications if staleness window becomes unacceptable.
- **Object storage backend**: Swap BYTEA for S3/R2 if blob sizes exceed Postgres comfort zone.
- **Table partitioning**: Partition `arbs_kv_cache_v1` by `cache_ns` if row count reaches hundreds of millions.
