# ARBS Caching Module - Architecture Diagrams and Flow Charts

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ARBS Application Layer                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │ _RLCurveCache   │  │ MyCacheUser     │  │ OtherClient     │         │
│  │ (Extends        │  │ (Extends        │  │ (Extends        │         │
│  │  ZODBCacheMixin)│  │  ZODBCacheMixin)│  │  ZODBCacheMixin)│         │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘         │
└───────────┼───────────────────┼────────────────────┼──────────────────┘
            │                   │                    │
            │ zodb_open_cache() │ zodb_open_cache()  │
            │                   │                    │
┌───────────▼───────────────────▼────────────────────▼──────────────────┐
│                       ZODBCacheMixin                                   │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ _z_conns: Dict[str, Tuple[Connection, _DBHandle]]            │  │
│  │ _codec_wrappers: Dict[str, CodecMapping]                     │  │
│  │ _use_btree: bool                                             │  │
│  │ _force_refresh: bool                                         │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                          │                                             │
│  Methods:                │                                             │
│  • zodb_open_cache()     ├─→ _acquire_db() ──┐                        │
│  • close_zodb()          │   _release_db()   │                        │
│  • zodb_commit()         │                   ▼                        │
│  • batched()             │   ┌───────────────────────────┐            │
│  • default_cache_path()  │   │ _DB_REGISTRY              │            │
│  • diagnostics()         │   │ Dict[path, _DBHandle]     │            │
└─────────────────────────┼───┤ with _REGISTRY_LOCK       │───────────┘
                          │   └───────┬───────────────────┘
                          │           │
                          └───────────┼───────────────────┐
                                      ▼                   ▼
                          ┌──────────────────┐  ┌──────────────────┐
                          │  /tmp/cache1.fs  │  │  /tmp/cache2.fs  │
                          │                  │  │                  │
                          │  _DBHandle       │  │  _DBHandle       │
                          │  • refcnt: 2     │  │  • refcnt: 1     │
                          │  • db: DB        │  │  • db: DB        │
                          │  • storage: FS   │  │  • storage: FS   │
                          │  • _conns: []    │  │  • _conns: []    │
                          └──────────┬───────┘  └──────────┬───────┘
                                     │                    │
                          ┌──────────▼────────┐ ┌────────▼───────────┐
                          │   FileStorage     │ │   FileStorage      │
                          │   (.fs file)      │ │   (.fs file)       │
                          │                   │ │                    │
                          │  ┌──────────────┐ │ │ ┌──────────────┐  │
                          │  │ OOBTree      │ │ │ │ OOBTree      │  │
                          │  │ (root)       │ │ │ │ (root)       │  │
                          │  │ ├─cache_attr1│ │ │ │ ├─ts_catalog │  │
                          │  │ └─cache_attr2│ │ │ │ └─other...   │  │
                          │  └──────────────┘ │ │ └──────────────┘  │
                          └───────────────────┘ └────────────────────┘
```

## 2. Cache Opening Sequence Diagram

```
User                 ZODBCacheMixin              _DBHandle           FileStorage
  │                      │                           │                   │
  ├─ zodb_open_cache() ──>│                           │                   │
  │                      │                           │                   │
  │   force_refresh?     │                           │                   │
  │   ┌─ No ─────────────>│ zodb_open_cache()       │                   │
  │   │                  │ ├─ cache_attr in        │                   │
  │   │                  │ │  _z_conns?            │                   │
  │   │                  │ │ ┌─ Yes ─> return      │                   │
  │   │                  │ │ │ (cached)            │                   │
  │   │                  │ │ └─ No ────────────>   │                   │
  │   │                  │ ├─ _acquire_db(path) ──>│                   │
  │   │                  │ │                   ┌───>│ _acquire_db()     │
  │   │                  │ │                   │ ┌──>│ [with registry   │
  │   │                  │ │                   │ │  │  lock]           │
  │   │                  │ │<──────────────────┘ │  │                   │
  │   │                  │ │  _DBHandle returned  │  │                   │
  │   │                  │ ├─ get_conn()         │  │                   │
  │   │                  │ │  ┌─────────────────>│  │ open connection   │
  │   │                  │ │  │                  │  │  from pool        │
  │   │                  │ │  │ ┌────────────────┼─>│ FileStorage       │
  │   │                  │ │  │ │                │  │ /file.fs          │
  │   │                  │ │  │ │                │  │                   │
  │   │                  │ ├─ get root()          │  │                   │
  │   │                  │ │  root['cache_attr']? │  │                   │
  │   │                  │ │  ├─ No ─────────────>│  │ create OOBTree()  │
  │   │                  │ │  │ root[cache_attr] │  │                   │
  │   │                  │ │  │                  │  │                   │
  │   │                  │ │  ├─ commit()        │  │                   │
  │   │                  │ │  │                  │  │ [fsync]           │
  │   │                  │ │                      │                   │
  │   │                  │ ├─ CodecMapping wrap? │                   │
  │   │                  │ │  ┌─ Yes ────>      │                   │
  │   │                  │ │  │ CodecMapping()   │                   │
  │   │                  │ │  │ _codec_wrappers  │                   │
  │   │                  │ │  └─ No ────────────>│                   │
  │   │                  │                       │                   │
  │   │                  │ ├─ setattr(          │                   │
  │   │                  │ │   cache_attr,      │                   │
  │   │                  │ │   mapping)          │                   │
  │   │                  │ │                     │                   │
  │   │                  │ ├─ _z_conns[cache_attr] │                   │
  │   │                  │ │   = (conn, handle) │                   │
  │   │                  │ │                     │                   │
  │   │                  │ ├─ handle.incref()   │                   │
  │   │                  │ │                   (refcnt++)            │
  │   │<─────────────────┤                       │                   │
  │   │ Cache ready!     │                       │                   │
  │
  └─ cache[key] = value                          │
```

## 3. Transaction and Commit Flow

```
User Application
      │
      ├─ cache[key1] = value1   ──────┐
      │                               │
      ├─ cache[key2] = value2   ──────┼──> Modification in Memory
      │                               │    (No fsync yet)
      └─ cache[key3] = value3   ──────┘
            │
            │ cache.zodb_commit()
            │ or
            │ with cache.batched():
            │     ...
            │ (exit context)
            │
            ▼
      ┌─────────────────────────────┐
      │  transaction.commit()       │
      │  ┌─────────────────────────┐│
      │  │ Serialize objects to    ││
      │  │ persistent format       ││
      │  │                         ││
      │  │ Write to FileStorage    ││
      │  │ ┌─────────────────────┐││
      │  │ │ .fs file on disk    │││
      │  │ │ ┌─────────────────┐ │││
      │  │ │ │ OOBTree root    │ │││
      │  │ │ │ ├─ cache_attr:  │ │││
      │  │ │ │ │   key1: v1    │ │││
      │  │ │ │ │   key2: v2    │ │││
      │  │ │ │ │   key3: v3    │ │││
      │  │ │ │ └─────────────── │ │││
      │  │ │ └─────────────────┘ │││
      │  │ └─────────────────────┘││
      │  │ fsync() ─────────────── ││ (Durable!)
      │  └─────────────────────────┘│
      └─────────────────────────────┘
            │
            ▼
      ┌─────────────────────────────┐
      │  Data persisted on disk     │
      │  Can be read by other       │
      │  processes/applications     │
      └─────────────────────────────┘
```

## 4. Reference Counting Lifecycle

```
Time →

Process 1: cache = _RLCurveCache(path="/tmp/cache.fs")
    │
    └─> _acquire_db("/tmp/cache.fs")
        │
        └─> _DB_REGISTRY["/tmp/cache.fs"] = _DBHandle(...)
            refcnt = 0
                │
                └─> incref()
                    refcnt = 1
                         │
                         ├─ cache[k] = v
                         ├─ commit()
                         │  │
                         │  ▼
                         │ [Data persisted]
                         │
                         └─ cache.close_zodb()
                            │
                            └─> decref()
                                refcnt = 0
                                    │
                                    └─> Close all connections
                                        Close DB
                                        Close FileStorage
                                        Delete from _DB_REGISTRY


Process 2: cache2 = _RLCurveCache(path="/tmp/cache.fs") [overlapping]
    │
    └─> _acquire_db("/tmp/cache.fs")
        │
        └─> Get existing _DBHandle (already in registry!)
            refcnt = 1 → 2
                │
                ├─ cache2[k] = v
                ├─ commit()
                │
                ├─ cache.close_zodb() [from Process 1]
                │ refcnt = 2 → 1
                │ (DB still open for Process 2)
                │
                └─ cache2.close_zodb() [from Process 2]
                   refcnt = 1 → 0
                   (Now close DB and FileStorage)
```

## 5. CodecMapping Encoding/Decoding Flow

```
User Code                CodecMapping               Backing Storage
    │                          │                          │
    ├─ cache['key'] = {        │                          │
    │     'tenor': '5Y',        │                          │
    │     'rate': 0.045        │                          │
    │   }                       │                          │
    │                           │                          │
    │  ┌─────────────────────>  │ __setitem__              │
    │  │                        │ (k='key', v={...})       │
    │  │                        │                          │
    │  │                        ├─ encode(v)              │
    │  │                        │ ┌────────────────────┐  │
    │  │                        │ │ def encode(obj):   │  │
    │  │                        │ │   return           │  │
    │  │                        │ │   json.dumps(obj)  │  │
    │  │                        │ └────────────────────┘  │
    │  │                        │                    ▼    │
    │  │                        │ encoded_str =          │
    │  │                        │ '{"tenor":"5Y",...}'   │
    │  │                        │                          │
    │  │                        ├─> _b[k] = encoded_str  │
    │  │                        │        │                │
    │  │                        │        └─────────────>  │ Store JSON string
    │  │                        │                         │ in PersistentMapping
    │  │                        │                          │
    │
    │ (Later...)
    │
    ├─ result = cache['key']   │                          │
    │                           │                          │
    │  ┌─────────────────────>  │ __getitem__(k='key')     │
    │  │                        │                          │
    │  │                        ├─> _b[k]                 │
    │  │                        │      │                  │
    │  │                        │      └────────────────> │ Retrieve JSON string
    │  │                        │<─────────────────────── │ '{"tenor":"5Y",...}'
    │  │                        │ encoded_str
    │  │                        │                          │
    │  │                        ├─ decode(encoded_str)   │
    │  │                        │ ┌────────────────────┐  │
    │  │                        │ │ def decode(s):     │  │
    │  │                        │ │   return json.load │  │
    │  │                        │ │   (s)              │  │
    │  │                        │ └────────────────────┘  │
    │  │                        │ ▼                       │
    │  │                        │ {'tenor': '5Y', ...}    │
    │  │                        │                          │
    │  └──────────────────────< │ return decoded dict    │
    │                           │                          │
    ├─ assert result == {...}   │
    │
```

## 6. Sharding Strategy for Time Series

```
Symbol Input: "AAPL"
    │
    ▼
sha256("AAPL") = "0e1a4d7b8f..."[:2] = "0e"
    │
    ▼
root['ts_catalog'].shards['0e']
    │
    ▼
┌─────────────────────────────────────────────┐
│ OOBTree (Shard '0e')                        │
│                                             │
│  ┌─ 'AAPL'                                  │
│  │  └─ SymbolIndex                          │
│  │     └─ by_date (OOBTree)                 │
│  │        ├─ '2024-01-01' ─> OOBTree        │
│  │        │  ├─ 'abc123...parquet'          │
│  │        │  │  {path, rows, size, ...}     │
│  │        │  └─ 'def456...parquet'          │
│  │        │     {path, rows, size, ...}     │
│  │        │                                  │
│  │        ├─ '2024-01-02' ─> OOBTree        │
│  │        │  └─ 'xyz789...parquet'          │
│  │        │     {path, rows, size, ...}     │
│  │        │                                  │
│  │        └─ '2024-12-31' ─> OOBTree        │
│  │           └─ ...                         │
│  │                                          │
│  ├─ 'MSFT'                                  │
│  │  └─ SymbolIndex (similar structure)      │
│  │                                          │
│  └─ 'META'                                  │
│     └─ SymbolIndex (similar structure)      │
│                                             │
└─────────────────────────────────────────────┘

Other Shards:
  '5a' ─> OOBTree (different symbols)
  '7b' ─> OOBTree (different symbols)
  ...
  'ff' ─> OOBTree (different symbols)

Total: 256 possible shards (00-ff)
Distribution: ~3 symbols per shard (if 1000 total symbols)
```

## 7. Thread Safety and Lock Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Lock Hierarchy                              │
│                                                                 │
│  Level 1: _REGISTRY_LOCK (Class-level)                         │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ with ZODBCacheMixin._REGISTRY_LOCK:                     │  │
│  │   handle = _DB_REGISTRY.get(path)                      │  │
│  │   if handle is None:                                    │  │
│  │       # Create new _DBHandle                           │  │
│  │       storage = FileStorage(path)                      │  │
│  │       db = DB(storage)                                 │  │
│  │       handle = _DBHandle(db, storage)                  │  │
│  │       _DB_REGISTRY[path] = handle                      │  │
│  │   handle.incref()                                      │  │
│  │                                                         │  │
│  │   Release lock here                                    │  │
│  └──────────────────────┬──────────────────────────────────┘  │
│                         ▼                                     │
│  Level 2: _DBHandle._lock (Per-database)                       │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ with handle._lock:                                      │  │
│  │   if self._conns:                                       │  │
│  │       return self._conns.pop()  # Reuse connection      │  │
│  │   else:                                                 │  │
│  │       return self.db.open()  # Create new connection    │  │
│  │                                                         │  │
│  │   Release lock here                                    │  │
│  └──────────────────────┬──────────────────────────────────┘  │
│                         ▼                                     │
│  Level 3: ZODB Transaction Manager (Thread-local)              │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ import transaction                                      │  │
│  │ transaction.commit()  # Per-thread transaction          │  │
│  │ transaction.abort()   # Rollback                        │  │
│  │                                                         │  │
│  │ Each thread gets its own transaction context           │  │
│  │ No explicit locking needed at this level                │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Deadlock Prevention:
  ✓ No nested lock acquisition within same level
  ✓ Registry lock released before pool lock acquired
  ✓ No locks held during I/O operations
```

## 8. Cache Invalidation and Refresh Flow

```
Original Cache State:
    ┌──────────────────────┐
    │ root['curves']       │
    │ ├─ 'curve_v1': {...} │
    │ ├─ 'curve_v2': {...} │
    │ └─ 'curve_v3': {...} │
    └──────────────────────┘

User calls: cache.zodb_open_cache(cache_attr='curves', force=True)

    ▼ Execution Path:

    if force and 'curves' in self._z_conns:
        conn, handle = self._z_conns.pop('curves')
        │
        ├─ Close old connection
        │  handle.release_conn(conn)
        │
        └─ Delete old data from root
           del root['curves']
           transaction.commit()

    Then reinitialize:
        container = OOBTree()
        root['curves'] = container
        transaction.commit()

    Result:
    ┌──────────────────────┐
    │ root['curves']       │ ← Empty OOBTree
    │ (empty)              │
    └──────────────────────┘

    Old data still in cache file but no longer referenced
    Can be recovered if needed, or file can be garbage collected
```

## 9. Performance Scaling Characteristics

```
Cache Size vs. Operation Time

Time (ms)
  │
  │                                        Large cache (OOBTree)
  │                                        ╱─── 1M items
  │                                       ╱
  │                                      ╱
  │                    Small-Medium     ╱ ╱─── 100K items
  │                     (OOBTree)      ╱╱╱
  │                    ╱──────────────╱╱
  │                   ╱               O(log n) lookups
  │                  ╱                
  │                 ╱
  │                ╱
  │───────────────────────────────────────────── Large cache
  │  ╱                                           (PersistentMapping)
  │ ╱                                            1M items
  │╱──────────────────────────────────────────── O(n) lookups
  │
  └────────────────────────────────────────────────────────────
      1K    10K   100K   1M    10M    100M      Cache Size

OOBTree advantages become clear at >10K items
PersistentMapping only acceptable for small caches
```

## 10. Complete Workflow Example

```
Start                   App creates cache
  │                     ┌─────────────────────────┐
  ▼                     │ cache = MyCacheUser()   │
                        │  ├─ __init__()          │
                        │  ├─ super().__init__()  │
                        │  └─ zodb_open_cache()   │
                        └──────────┬──────────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
          [Check path exists]              [_acquire_db()]
          [Create if needed]                │
                  │                         ├─ Registry lock acquired
                  │                         ├─ Check _DB_REGISTRY
                  │                         ├─ Create _DBHandle (if new)
                  │                         ├─ Get connection from pool
                  │                         ├─ Registry lock released
                  │                         └─ return handle
                  │
                  └────────────────┬────────────────┘
                                   ▼
                        ┌─────────────────────────┐
                        │ Initialize cache in DB │
                        │  ├─ Open connection     │
                        │  ├─ Get root dict      │
                        │  ├─ Create container   │
                        │  └─ commit()           │
                        └──────────┬──────────────┘
                                   │
                        ┌──────────┴──────────┐
                        ▼                     ▼
                     Wrap with          Set as instance
                  CodecMapping?         attribute
                        │                     │
                        ├─ Yes ────>         │
                        │   CodecMapping()   │
                        │                    │
                        └─────────┬──────────┘
                                  ▼
                        ┌─────────────────────────┐
                        │ Cache ready for use!    │
                        └──────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
         Read cache           Write cache          Monitor
         ┌─────────┐         ┌─────────┐         ┌──────────┐
         │ k in c? │         │ c[k]=v  │         │ refcnt?  │
         │ c[k]    │         │ commit()│         │diag()    │
         └────┬────┘         └────┬────┘         └──────────┘
              │                   │
              └────────┬──────────┘
                       │
              ┌────────▼─────────┐
              │ Close when done  │
              │ close_zodb()     │
              │  ├─ release_conn │
              │  ├─ decref()     │
              │  └─ cleanup      │
              └──────────────────┘
                       │
                       ▼
                    End
```

---

## 11. Memory Layout Comparison

```
Small Cache (1K items):
┌─────────────────────────────────────────────┐
│ PersistentMapping (5KB)                     │
│ ┌─────────────────────────────────────────┐ │
│ │ key1 -> (small obj)                     │ │
│ │ key2 -> (small obj)                     │ │
│ │ ... (all in memory)                     │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘

Large Cache (1M items) - PersistentMapping:
┌──────────────────────────────────────────────────┐
│ PersistentMapping (100MB)                        │
│ ┌──────────────────────────────────────────────┐ │
│ │ ALL 1M items loaded into memory              │ │
│ │ ├─ key1 -> obj                               │ │
│ │ ├─ key2 -> obj                               │ │
│ │ ├─ ...                                        │ │
│ │ └─ key1000000 -> obj                          │ │
│ │ [Full linear scan for queries]                │ │
│ └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘

Large Cache (1M items) - OOBTree:
┌──────────────────────────────────────────────────┐
│ OOBTree (1-5MB in memory)                        │
│ ┌──────────────────────────────────────────────┐ │
│ │ [Root node - always in memory]               │ │
│ │  │                                            │ │
│ │  ├─ [Branch node 1] ← only loaded on access │ │
│ │  │   ├─ [Leaf node] ← only loaded on access │ │
│ │  │   │  ├─ key50000 -> obj [1MB page]      │ │
│ │  │   │  ├─ key50001 -> obj                 │ │
│ │  │   │  └─ ...                              │ │
│ │  │   └─ [Leaf node] ← not in memory        │ │
│ │  │                                           │ │
│ │  ├─ [Branch node 2] ← not in memory         │ │
│ │  │                                           │ │
│ │  └─ [Branch node N] ← not in memory         │ │
│ │                                             │ │
│ │ [Efficient O(log n) navigation]              │ │
│ └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘

Result:
  PersistentMapping: 100MB resident for 1M items
  OOBTree:          1-5MB resident (and lazy loads needed pages)
```

---

## 12. Parquet File Content Addressing

```
User provides DataFrame:
┌────────────────────────────────────┐
│ Timestamp       | Open  | Close    │
│ 2024-01-01 9:30 | 100.5 | 101.2    │
│ 2024-01-01 10:0 | 101.0 | 101.8    │
│ ...            | ...   | ...      │
└────────────────────────────────────┘
              │
              ▼
  ┌─────────────────────────────────┐
  │ Convert to Arrow Table           │
  │ Apply Zstd compression           │
  │ Write to bytes                   │
  └─────────────────────────────────┘
              │
              ▼
  ┌─────────────────────────────────┐
  │ Compute SHA256(bytes)           │
  │ Result: abc123def456...         │
  └─────────────────────────────────┘
              │
              ▼
  File saved as: abc123def456.parquet
              │
              ▼
  ┌─────────────────────────────────┐
  │ Catalog entry:                  │
  │ {                               │
  │   "path": "/.../abc123de.pq",  │
  │   "rows": 1000,                │
  │   "size": 45000,               │
  │   "sha256": "abc123def456...",  │
  │   "min_ts": "2024-01-01",       │
  │   "max_ts": "2024-12-31"        │
  │ }                               │
  └─────────────────────────────────┘

Benefits:
  ✓ Identical content → same filename
  ✓ Automatic deduplication
  ✓ Can verify file integrity via hash
  ✓ Prevents duplicate storage
```

---

## Key Takeaways Diagram

```
┌──────────────────────────────────────────────────────────────┐
│     ARBS Caching Module - Key Characteristics                │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ✓ Deterministic                                              │
│    └─ Same inputs → Same cache key → Reproducible results   │
│                                                               │
│  ✓ Persistent                                                 │
│    └─ FileStorage → Data survives process restart            │
│                                                               │
│  ✓ Thread-Safe                                                │
│    └─ Multi-level locking → Safe concurrent access          │
│                                                               │
│  ✓ Scalable                                                   │
│    └─ OOBTree O(log n) → Handles 100M+ items efficiently    │
│                                                               │
│  ✓ Efficient                                                  │
│    └─ Connection pooling + lazy loading → Low overhead       │
│                                                               │
│  ✓ Flexible                                                   │
│    └─ CodecMapping → Transparent serialization/compression   │
│                                                               │
│  ✓ Durable                                                    │
│    └─ ACID transactions → No data loss, all-or-nothing       │
│                                                               │
│  ✓ Observable                                                 │
│    └─ diagnostics() → Monitor reference counts and leaks     │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

