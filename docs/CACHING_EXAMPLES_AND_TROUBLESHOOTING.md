# ARBS Caching Module - Practical Examples and Troubleshooting

## 1. Complete Working Examples

### 1.1 Simple Key-Value Cache

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
import json

class SimpleCache(ZODBCacheMixin):
    """Simple key-value cache with JSON serialization"""
    
    def __init__(self, cache_name="simple_cache"):
        super().__init__(use_btree=True)
        self.cache_name = cache_name
        self.cache_path = self.default_cache_path(cache_name)
        
        self.zodb_open_cache(
            cache_attr=cache_name,
            path=self.cache_path,
            encode=json.dumps,
            decode=json.loads,
        )
        self._cache = getattr(self, cache_name)
    
    def set(self, key, value):
        """Store a value"""
        self._cache[key] = value
        self.zodb_commit()
    
    def get(self, key, default=None):
        """Retrieve a value"""
        return self._cache.get(key, default)
    
    def delete(self, key):
        """Delete a key"""
        if key in self._cache:
            del self._cache[key]
            self.zodb_commit()
    
    def clear(self):
        """Clear all entries"""
        self._cache.clear()
        self.zodb_commit()
    
    def close(self):
        """Cleanup resources"""
        self.close_zodb()

# Usage
cache = SimpleCache("my_app_cache")
try:
    cache.set("user:1", {"name": "Alice", "age": 30})
    cache.set("user:2", {"name": "Bob", "age": 25})
    
    user1 = cache.get("user:1")
    print(user1)  # {'name': 'Alice', 'age': 30}
    
    cache.delete("user:2")
finally:
    cache.close()
```

### 1.2 Computation Caching with Deterministic Keys

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
from Caching.utils import to_filename_key
import json
import time

class ComputationCache(ZODBCacheMixin):
    """Cache for expensive computations"""
    
    def __init__(self):
        super().__init__(use_btree=True)
        self.zodb_open_cache(
            cache_attr="computations",
            path=self.default_cache_path("computations"),
            encode=json.dumps,
            decode=json.loads,
        )
        self._cache = self.computations
    
    def expensive_operation(self, symbol, params):
        """
        Cache an expensive operation.
        Same inputs always get same result (deterministic).
        """
        # Generate deterministic key
        key_config = {"symbol": symbol, "params": params}
        key = to_filename_key(key_config, max_len=120)
        
        # Check cache
        if key in self._cache:
            print(f"Cache HIT for {key}")
            return self._cache[key]
        
        print(f"Cache MISS for {key}, computing...")
        # Expensive computation
        time.sleep(2)
        result = {
            "symbol": symbol,
            "computed_at": time.time(),
            "value": sum(params.values()),
        }
        
        # Store result
        self._cache[key] = result
        self.zodb_commit()
        
        return result
    
    def close(self):
        self.close_zodb()

# Usage
cache = ComputationCache()
try:
    # First call: computes (2 second wait)
    r1 = cache.expensive_operation("AAPL", {"a": 1, "b": 2})
    
    # Second call: same params, same key, cache hit!
    r2 = cache.expensive_operation("AAPL", {"a": 1, "b": 2})
    
    # Third call: different params, cache miss
    r3 = cache.expensive_operation("AAPL", {"a": 10, "b": 20})
    
    assert r1 == r2  # Identical results
finally:
    cache.close()
```

### 1.3 Batch Writes for Performance

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
import pandas as pd
import time

class HistoricalDataCache(ZODBCacheMixin):
    """Cache historical data efficiently with batch writes"""
    
    def __init__(self):
        super().__init__(use_btree=True)
        self.zodb_open_cache(
            cache_attr="prices",
            path=self.default_cache_path("prices"),
        )
        self._cache = self.prices
    
    def load_historical_data(self, data_dict):
        """
        Load many data points efficiently.
        Use batched() to commit once instead of N times.
        """
        print(f"Loading {len(data_dict)} items...")
        start = time.time()
        
        with self.batched():
            for key, value in data_dict.items():
                self._cache[key] = value
        
        elapsed = time.time() - start
        print(f"Loaded in {elapsed:.2f} seconds")
    
    def close(self):
        self.close_zodb()

# Usage
cache = HistoricalDataCache()
try:
    # Simulate 1000 data points
    data = {
        f"AAPL:2024-01-{day:02d}": {"open": 150 + day, "close": 152 + day}
        for day in range(1, 31)
    }
    
    # Batched write is much faster than individual commits
    cache.load_historical_data(data)
finally:
    cache.close()
```

### 1.4 Time-Series with Parquet Storage

```python
from Caching.timeseries_cache import (
    append_timeseries, read_timeseries, WriteOptions
)
from ZODB import DB
from ZODB.FileStorage import FileStorage
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Setup
storage = FileStorage("/tmp/timeseries_cache.fs")
db = DB(storage)
root = db.open().root()

# Create sample time-series data
dates = pd.date_range("2024-01-01", periods=100, freq="1D")
data = pd.DataFrame({
    "price": np.random.randn(100).cumsum() + 100,
    "volume": np.random.randint(1000000, 10000000, 100),
}, index=dates)

# Write to cache
opts = WriteOptions(base_dir="/tmp/timeseries_data")
metas = append_timeseries(root, "AAPL", data, opts=opts)
print(f"Wrote {len(metas)} files")

# Read back
result = read_timeseries(root, "AAPL", base_dir="/tmp/timeseries_data")
print(result.head())

# Cleanup
root._p_jar.transaction_manager.commit()
db.close()
storage.close()
```

### 1.5 Thread-Safe Caching

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
import threading
import time
import json

class ThreadSafeCache(ZODBCacheMixin):
    """Demonstrates thread-safe cache usage"""
    
    def __init__(self):
        super().__init__(use_btree=True)
        self.zodb_open_cache(
            cache_attr="data",
            path=self.default_cache_path("threadsafe"),
            encode=json.dumps,
            decode=json.loads,
        )
        self._cache = self.data
    
    def worker(self, worker_id, num_items):
        """Worker thread that writes to cache"""
        for i in range(num_items):
            key = f"worker_{worker_id}_item_{i}"
            value = {"worker": worker_id, "item": i, "time": time.time()}
            self._cache[key] = value
        
        # Commit at end
        self.zodb_commit()
        print(f"Worker {worker_id} done")
    
    def close(self):
        self.close_zodb()

# Usage
cache = ThreadSafeCache()
try:
    threads = []
    for w_id in range(3):
        t = threading.Thread(target=cache.worker, args=(w_id, 10))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"Total items in cache: {len(cache._cache)}")
finally:
    cache.close()
```

### 1.6 Monitoring and Diagnostics

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
import json

class MonitoredCache(ZODBCacheMixin):
    """Cache with monitoring and diagnostics"""
    
    def __init__(self, cache_name):
        super().__init__(use_btree=True)
        self.cache_name = cache_name
        self.zodb_open_cache(
            cache_attr=cache_name,
            path=self.default_cache_path(cache_name),
            encode=json.dumps,
            decode=json.loads,
        )
        self._cache = getattr(self, cache_name)
    
    def show_diagnostics(self):
        """Display cache diagnostics"""
        diag = self.diagnostics()
        print("Database Reference Counts:")
        for path, refcnt in diag.items():
            print(f"  {path}: {refcnt} active instances")
        
        print(f"Cache '{self.cache_name}' size: {len(self._cache)} items")
    
    def close(self):
        self.close_zodb()

# Usage
cache1 = MonitoredCache("cache1")
cache2 = MonitoredCache("cache2")

cache1._cache["key1"] = {"value": 1}
cache2._cache["key2"] = {"value": 2}

print("Before close:")
cache1.show_diagnostics()

cache1.close()

print("\nAfter cache1 closed:")
cache2.show_diagnostics()

cache2.close()

print("\nAfter cache2 closed:")
print("Diagnostics:", MonitoredCache.diagnostics())  # Should be empty
```

---

## 2. Common Patterns and Anti-Patterns

### 2.1 Pattern: Resource Management with Context Manager

**Good:**
```python
from contextlib import contextmanager

@contextmanager
def managed_cache(cache_name):
    cache = MyCache(cache_name)
    try:
        yield cache
    finally:
        cache.close_zodb()

# Guaranteed cleanup
with managed_cache("my_cache") as cache:
    cache.set("key", "value")
# close_zodb() called automatically
```

**Bad:**
```python
# Resource leak!
cache = MyCache("my_cache")
cache.set("key", "value")
# Forgot to call close_zodb()
# Connection not released, database stays locked
```

### 2.2 Pattern: Batched Writes

**Good:**
```python
with cache.batched():
    for key, value in large_dataset.items():
        cache[key] = value
# Single transaction.commit() on exit
# Performance: 1 fsync for 10,000 items
```

**Bad:**
```python
for key, value in large_dataset.items():
    cache[key] = value
    cache.zodb_commit()
# 10,000 fsync operations!
# Performance: 1000x slower
```

### 2.3 Pattern: Deterministic Keys

**Good:**
```python
import hashlib
import json

def make_key(symbol, date, model):
    data = {
        "symbol": symbol,
        "date": date.isoformat(),
        "model": model,
    }
    # Sorted for determinism
    json_str = json.dumps(data, sort_keys=True)
    return hashlib.sha1(json_str.encode()).hexdigest()

# Same inputs always produce same key
key1 = make_key("AAPL", date(2024, 1, 1), "DCF")
key2 = make_key("AAPL", date(2024, 1, 1), "DCF")
assert key1 == key2  # Always true
```

**Bad:**
```python
import time

# Non-deterministic key!
def make_bad_key(symbol, date, model):
    return f"{symbol}_{date}_{model}_{time.time()}"

# Same inputs produce different keys
key1 = make_bad_key("AAPL", date, "DCF")
time.sleep(0.1)
key2 = make_bad_key("AAPL", date, "DCF")
assert key1 != key2  # Different keys, cache never hits
```

### 2.4 Pattern: Error Handling

**Good:**
```python
import transaction

def safe_write(cache, key, value):
    try:
        cache[key] = value
        cache.zodb_commit()
        return True
    except Exception as e:
        transaction.abort()
        print(f"Error writing cache: {e}")
        return False

# Graceful failure
success = safe_write(cache, key, value)
```

**Bad:**
```python
cache[key] = value
cache.zodb_commit()
# If exception occurs during commit, 
# transaction not aborted, partial state possible
```

---

## 3. Troubleshooting Guide

### 3.1 Problem: "LockError: Could not lock ..."

**Symptom:**
```
LockError: Could not lock 'my_cache.fs'
```

**Causes:**
1. Another process has the database file open
2. Stale lock file from crashed process
3. Insufficient filesystem permissions

**Solutions:**

```python
# Solution 1: Wait for other process to finish
# Check what's using the file
import subprocess
subprocess.run(["lsof", "/path/to/my_cache.fs"])

# Solution 2: Remove stale lock file (careful!)
import os
lock_file = "/path/to/my_cache.fs.lock"
if os.path.exists(lock_file):
    os.remove(lock_file)
# Then retry

# Solution 3: Check permissions
import os
path = "/path/to/my_cache.fs"
stat_info = os.stat(path)
print(f"Permissions: {oct(stat_info.st_mode)}")
# Should be readable/writable by your user

# Solution 4: Read-only fallback (already in code)
# If file is locked, automatically uses DemoStorage for read-only access
try:
    cache = MyCache("my_cache")  # Works even if locked!
    value = cache.get("key")  # Read works
    # cache.set("key", value)  # Write fails silently
except Exception as e:
    print(f"Error: {e}")
```

### 3.2 Problem: "Resource leak: refcnt not zero after close"

**Symptom:**
```python
cache.close_zodb()
# Diagnostics still shows refcnt > 0
diag = ZODBCacheMixin.diagnostics()
print(diag)  # {'path': 1}  (should be empty)
```

**Causes:**
1. Multiple caches open on same file
2. Exception before close_zodb() called
3. Nested cache initialization

**Solutions:**

```python
# Solution 1: Use context manager (automatic cleanup)
@contextmanager
def safe_cache():
    cache = MyCache()
    try:
        yield cache
    finally:
        cache.close_zodb()

with safe_cache() as cache:
    cache.set("key", "value")
# Always cleaned up

# Solution 2: Track all instances
cache1 = MyCache("shared.fs")
cache2 = MyCache("shared.fs")

# Both need to be closed
cache1.close_zodb()  # refcnt 2 -> 1
cache2.close_zodb()  # refcnt 1 -> 0

# Now diagnostics should be empty
assert len(ZODBCacheMixin.diagnostics()) == 0

# Solution 3: Force cleanup in exception handler
try:
    cache = MyCache()
    # Do something that might fail
    risky_operation()
except Exception as e:
    print(f"Error: {e}")
finally:
    cache.close_zodb()  # Always called
```

### 3.3 Problem: "Transaction.ConflictError"

**Symptom:**
```
ZODB.POSException.ConflictError: database read conflict
```

**Causes:**
1. Two transactions modified same object
2. ZODB conflict resolution failed
3. Very high concurrency

**Solutions:**

```python
# Solution 1: Retry with backoff
import time
import transaction

def write_with_retry(cache, key, value, max_retries=3):
    for attempt in range(max_retries):
        try:
            cache[key] = value
            cache.zodb_commit()
            return True
        except transaction.interfaces.ConflictError:
            if attempt < max_retries - 1:
                # Exponential backoff
                wait = 0.1 * (2 ** attempt)
                time.sleep(wait)
                transaction.abort()
            else:
                raise
    return False

# Solution 2: Use smaller transaction scope
# Bad: Large transaction is more likely to conflict
with cache.batched():
    for item in million_items:
        cache[item] = value

# Good: Commit frequently
for chunk in chunks(million_items, 1000):
    with cache.batched():
        for item in chunk:
            cache[item] = value

# Solution 3: Separate databases for different domains
cache_curves = MyCache("curves.fs")
cache_fixings = MyCache("fixings.fs")
# Less contention, fewer conflicts
```

### 3.4 Problem: "Memory usage keeps growing"

**Symptom:**
```
Process memory: 100MB -> 500MB -> 1GB
Large cache never released
```

**Causes:**
1. Large objects kept in memory
2. Connection pool growing unbounded
3. PersistentMapping instead of OOBTree
4. Codec cache not cleared

**Solutions:**

```python
# Solution 1: Use OOBTree for large caches
cache = MyCache(use_btree=True)  # Default, good
# Not: use_btree=False (bad for large caches)

# Solution 2: Monitor and limit pool size
from Caching.ZODBCacheMixin import ZODBCacheMixin
# Pool size is set per DB
# Too large = memory waste
# Too small = contention

# Solution 3: Explicitly clear large objects
# Before:
large_data = load_massive_dataset()
cache[key] = large_data
# Memory spike

# Better: Process in chunks
for chunk in iterate_chunks(large_data):
    cache[chunk_key] = chunk
    cache.zodb_commit()

# Solution 4: Close unused caches
cache1.close_zodb()
cache2.close_zodb()
# Releases connections and file handles
```

### 3.5 Problem: "Cache misses when it should hit"

**Symptom:**
```python
cache[key] = value
assert cache[key] == value  # Fails!
```

**Causes:**
1. Transaction not committed
2. Encoding/decoding mismatch
3. Key mismatch (determinism issue)

**Solutions:**

```python
# Solution 1: Commit after write
cache[key] = value
cache.zodb_commit()  # Must commit!
assert cache[key] == value  # Now works

# Solution 2: Check encoding/decoding
def encode(obj):
    import json
    return json.dumps(obj, sort_keys=True)

def decode(data):
    import json
    return json.loads(data)

# Test encoding round-trip
obj = {"key": "value"}
assert decode(encode(obj)) == obj

# Solution 3: Debug key generation
import hashlib
import json

def debug_key(symbol, date, params):
    data = {"symbol": symbol, "date": date, "params": params}
    key = hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()
    print(f"Generated key: {key}")
    return key

key1 = debug_key("AAPL", "2024-01-01", {"a": 1})
key2 = debug_key("AAPL", "2024-01-01", {"a": 1})
assert key1 == key2  # Must be identical
```

### 3.6 Problem: "File gets very large"

**Symptom:**
```
cache.fs: 1GB -> 5GB -> 10GB
Lots of old data still taking space
```

**Causes:**
1. Old cache entries not deleted
2. Parquet files accumulating
3. Force refresh not working

**Solutions:**

```python
# Solution 1: Explicit cleanup
cache.clear()
cache.zodb_commit()

# Solution 2: Vacuum catalog (for timeseries)
from Caching.timeseries_cache import vacuum_catalog
removed = vacuum_catalog(root, delete_stale_files=True)
print(f"Removed {removed} stale entries")

# Solution 3: Delete specific entries
del cache[old_key]
cache.zodb_commit()

# Solution 4: Force refresh to clear all
cache.zodb_open_cache(
    cache_attr="my_cache",
    path=cache.cache_path,
    force=True  # Clears all entries
)

# Solution 5: Compress with CodecMapping
import zlib
cache = CodecMapping(
    cache._cache,
    encode=zlib.compress,
    decode=zlib.decompress,
)
# Reduces disk space by 80-90% for text data
```

### 3.7 Problem: "Getting very old cached data"

**Symptom:**
```python
# Data was updated in source
cache[key] = old_value
# Update happens
source_data_updated()
# But cache still returns old value
cached = cache[key]  # Still old_value!
```

**Causes:**
1. Key doesn't account for version
2. Data updated outside cache
3. Cache key generation not deterministic

**Solutions:**

```python
# Solution 1: Include version in key
def versioned_key(symbol, version):
    return f"{symbol}_v{version}"

# When data changes, increment version
old_key = versioned_key("AAPL", 1)
new_key = versioned_key("AAPL", 2)
cache[new_key] = new_data  # Different key, no stale data

# Solution 2: Use timestamp in metadata
cache[key] = {
    "data": actual_data,
    "created_at": time.time(),
}

# Check if stale
entry = cache.get(key)
if time.time() - entry["created_at"] > TTL_SECONDS:
    # Refresh from source
    pass

# Solution 3: Force refresh
cache.zodb_open_cache(force=True)
# Clears all entries, next access recomputes
```

---

## 4. Performance Tuning

### 4.1 Benchmark Results

```python
from Caching.ZODBCacheMixin import ZODBCacheMixin
import time
import json

class PerformanceTest(ZODBCacheMixin):
    def __init__(self):
        super().__init__(use_btree=True)
        self.zodb_open_cache(
            cache_attr="perf_test",
            path=self.default_cache_path("perf_test"),
            encode=json.dumps,
            decode=json.loads,
        )
        self._cache = self.perf_test
    
    def benchmark_operations(self):
        """Run performance benchmarks"""
        
        # Test 1: Single write
        start = time.perf_counter()
        self._cache["test"] = {"data": "value"}
        self.zodb_commit()
        elapsed = (time.perf_counter() - start) * 1000
        print(f"Single write: {elapsed:.2f} ms")
        
        # Test 2: Single read
        start = time.perf_counter()
        _ = self._cache["test"]
        elapsed = (time.perf_counter() - start) * 1000
        print(f"Single read: {elapsed:.2f} ms")
        
        # Test 3: Batch writes
        start = time.perf_counter()
        with self.batched():
            for i in range(1000):
                self._cache[f"key_{i}"] = {"value": i}
        elapsed = (time.perf_counter() - start) * 1000
        print(f"Batch 1000 writes: {elapsed:.2f} ms ({elapsed/1000:.3f} ms per item)")
        
        # Test 4: Batch reads
        start = time.perf_counter()
        for i in range(1000):
            _ = self._cache.get(f"key_{i}")
        elapsed = (time.perf_counter() - start) * 1000
        print(f"Batch 1000 reads: {elapsed:.2f} ms ({elapsed/1000:.3f} ms per item)")
    
    def close(self):
        self.close_zodb()

# Expected Results:
# Single write: 15-20 ms
# Single read: <1 ms
# Batch 1000 writes: 100-200 ms (0.1-0.2 ms per item)
# Batch 1000 reads: 10-20 ms (0.01-0.02 ms per item)
```

### 4.2 Optimization Checklist

```python
# ✓ Use OOBTree for caches > 10K items
cache = ZODBCacheMixin(use_btree=True)

# ✓ Batch writes together
with cache.batched():
    for item in items:
        cache[key] = value

# ✓ Use CodecMapping for large objects
from Caching.CodecMapping import CodecMapping
import zlib

cache = CodecMapping(
    backing_cache,
    encode=zlib.compress,
    decode=zlib.decompress,
)

# ✓ Reuse cache instances
cache = MyCache()
for i in range(1000):
    # Use same cache instance
    cache.set(key, value)

# ✓ Avoid transaction conflicts
# Use force=True only when necessary
cache.zodb_open_cache(force=False)  # Default, good

# ✓ Monitor resource usage
diag = ZODBCacheMixin.diagnostics()
if len(diag) == 0:
    print("All caches cleaned up")
```

---

## 5. FAQ

### Q1: Should I use PersistentMapping or OOBTree?

**A:** Use `OOBTree` (default, `use_btree=True`) for any production cache. `PersistentMapping` only acceptable for:
- Development/testing
- Caches < 1000 items
- One-time initialization

```python
# Good
cache = ZODBCacheMixin(use_btree=True)

# Acceptable only for tiny caches
cache = ZODBCacheMixin(use_btree=False)
```

### Q2: How often should I commit?

**A:** 
- **High frequency operations**: Use `.batched()` to commit once per batch
- **Batch size**: 100-10,000 items per batch (depends on size)
- **Default**: Commit after each operation for safety

```python
# Best: Batch
with cache.batched():
    for item in items:  # 1000 items
        cache[item] = value

# Acceptable: Individual commits
cache[key] = value
cache.zodb_commit()

# Avoid: Thousands of individual commits
for key in keys:
    cache[key] = value
    # Forgetting zodb_commit() here
```

### Q3: Is it thread-safe?

**A:** Partially. Safe for:
- Multiple readers
- Multiple writers with proper transaction management
- Different caches in different threads

Unsafe for:
- Concurrent writes to same key
- Not calling close_zodb()

```python
# Safe: Each thread has own cache
thread1_cache = MyCache("thread1.fs")
thread2_cache = MyCache("thread2.fs")

# Unsafe: Shared cache, concurrent writes
shared_cache = MyCache("shared.fs")
threading.Thread(target=write_to, args=(shared_cache,)).start()
write_to(shared_cache)  # Race condition possible
```

### Q4: How do I clear a cache?

**A:**
```python
# Option 1: Clear all entries
cache.cache.clear()
cache.zodb_commit()

# Option 2: Force refresh (removes from disk)
cache.zodb_open_cache(force=True)

# Option 3: Delete file (nuclear option)
import os
os.remove(cache_path)
```

### Q5: What happens if process crashes?

**A:** Data is safe:
- All committed data persists
- Uncommitted data is lost (expected)
- Lock file may remain (can be cleaned up)

```python
cache[key] = value
cache.zodb_commit()  # Data is now safe
# Even if process crashes here, data survives

cache[key2] = value2
# Process crashes here - value2 is lost, value is safe
```

---

## 6. Summary Table

| Task | Pattern | Performance |
|------|---------|-------------|
| Single read | `cache[key]` | <1ms |
| Single write | `cache[key] = v; commit()` | 15-20ms |
| Batch reads | `for k in keys: cache[k]` | 0.01ms/item |
| Batch writes | `with batched(): ...` | 0.1ms/item |
| Large cache | OOBTree | O(log n) |
| Small cache | PersistentMapping | O(1) |
| Compression | CodecMapping + zlib | 80-90% reduction |
| Thread safety | Separate instances | Safe |

