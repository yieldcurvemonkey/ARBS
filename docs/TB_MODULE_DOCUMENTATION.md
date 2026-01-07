# ARBS Toolbox (TB) Module - Comprehensive Documentation

## Overview

The **Toolbox (TB)** module is a high-performance bulk evaluation framework for financial instruments, providing efficient time series generation for Interest Rate Swaps (IRS) and Fixed-Rate Bonds (FRB). It leverages ZODB persistent caching, multithreaded execution, and advanced query fingerprinting for deterministic, reproducible bulk operations.

The module is designed for:
- **Bulk pricing** of hundreds to thousands of instruments across multiple dates
- **Efficient caching** with ZODB persistent storage and partitioned Parquet files
- **Parallel execution** using ThreadPoolExecutor for CPU-bound pricing
- **Query determinism** via cryptographic fingerprinting
- **Seamless integration** with Jupyter notebooks and batch scripts

---

## 1. IRSwapsTB Class and Bulk Evaluation Capabilities

### Overview

`IRSwapsTB` is the primary class for bulk evaluation of Interest Rate Swaps. It handles:
- Multi-date time series generation
- Curve-by-curve workload distribution
- Smart caching with date/curve/query segmentation
- Multi-threaded pricing via ThreadPoolExecutor
- Integration with IRSwapsMDP (Market Data Provider)

### Class Initialization

```python
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Create an IRSwapsMDP instance
mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")

# Initialize the toolbox with caching
tb = IRSwapsTB(
    mdp=mdp,
    date_col="Date",                    # Column name for dates in output
    cache_stem="MyCustomStem",          # Optional custom cache name
    force_refresh=False,                # Force recalculation (bypass cache)
    use_btree=True,                     # Use B-Tree for ZODB (more efficient)
    show_tqdm=True,                     # Show progress bars
    logger=None,                        # Optional custom logger
)
```

**Key Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mdp` | `IRSwapsMDP` | Required | Market Data Provider for curve building |
| `date_col` | `str` | `"Date"` | Column name for date index in output DataFrame |
| `cache_stem` | `str` | Auto-generated | Custom cache file stem (versioned automatically) |
| `force_refresh` | `bool` | `False` | Force recalculation, ignoring cache |
| `use_btree` | `bool` | `True` | Use B-Tree for better ZODB performance |
| `show_tqdm` | `bool` | `True` | Display progress bars during execution |
| `logger` | `logging.Logger` | Auto-created | Custom logger instance |

### Core Method: `get_timeseries()`

The primary entry point for bulk evaluation:

```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
import datetime

df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 31),
    queries=[
        IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="5Y",
            value=IRSwapValue.RATE,
        ),
        IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="10Y",
            value=IRSwapValue.RATE,
        ),
        IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="5Y/10Y",              # CURVE structure (spread)
            value=IRSwapValue.MMSS,      # Money Market Swap Spread
        ),
    ],
    n_jobs=4,                           # 4 worker threads
    ignore_cache=False,                 # Use cached results
    freq=None,                          # None = daily business days
    timestamps=None,                    # None = use start/end range
)

print(df)
# Output: DataFrame with Date index, columns per instrument
#         Index                 USD-SOFR-1D 5Y OUTRIGHT RATE  ...
#         2025-01-02                    4.820                ...
#         2025-01-03                    4.835                ...
```

**Method Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start` | `DateLike` | Required | Start date (date or datetime) |
| `end` | `DateLike` | Required | End date (inclusive) |
| `queries` | `List[IRSwapQuery]` | Required | Queries to evaluate (can be nested lists) |
| `n_jobs` | `int` | `1` | Number of worker threads (1=serial, >1=parallel) |
| `ignore_cache` | `bool` | `False` | Bypass cache and force fresh evaluation |
| `freq` | `str` | `None` | Frequency for intraday (e.g., "1T", "15T", "1H"). Requires timezone-aware datetime |
| `timestamps` | `List[datetime.datetime]` | `None` | Custom evaluation timestamps (overrides start/end) |

### Bulk Evaluation Workflow

The `get_timeseries()` method follows this workflow:

1. **Date Range Expansion**
   - Converts `start`/`end` to business day range or custom timestamps
   - For intraday: uses timezone-aware datetime with specified frequency
   - Returns sorted list of evaluation points

2. **Query Flattening & Grouping**
   - Flattens nested query lists
   - Groups queries by curve (each curve = separate workload)
   - Validates that all queries specify `.curve`

3. **Cache Lookup**
   - Checks ZODB cache for existing results
   - Key: `(version | curve_name | epoch_ns | query_fingerprint)`
   - Skips cache for "today" (always fresh)
   - Batches missing points per curve

4. **Bulk Data Fetching**
   - Calls `mdp.bulk_get_data()` once per curve
   - Returns dictionary: `{date: curve_object, ...}`
   - Caches curve objects to avoid redundant builds

5. **Parallel Pricing**
   - Creates tasks: `(date, query, curve)` triplets
   - If `n_jobs > 1`: uses ThreadPoolExecutor with `max_workers=n_jobs`
   - If `n_jobs = 1`: serial execution
   - Shows progress via tqdm

6. **Cache Persistence**
   - Uses `batched()` context manager for atomic writes
   - Writes: `(date, col_name, value)` tuples to ZODB mapping

7. **DataFrame Construction**
   - Concatenates cached + new results
   - Pivots to wide format: dates as rows, columns as instruments
   - Sets date column as index

### Example: Spread Queries

IRSwapsTB intelligently handles spread structures:

```python
# Curve spread (butterfly-like)
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="2Y/5Y/10Y",           # Front/Belly/Back
    value=IRSwapValue.RATE,
    # Auto-parses as FLY structure
)

# Simple curve (2-legged)
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Yx10Y",              # Can use 'x' or '/'
    value=IRSwapValue.RATE,
    # Auto-parses as CURVE structure
)

# Outright
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
)
```

### Example: Money Market Swap Spread (MMSS)

```python
# Treasury-Swap Spread
queries = [
    IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="5Y",
        value=IRSwapValue.MMSS,      # MMSS = IRS Rate - UST YTM
    ),
    IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="CT5/CT30",             # CT = Constant Tenor notation
        value=IRSwapValue.MMSS,
    ),
]
```

### Performance Characteristics

**Caching Efficiency:**
- First run: ~2-5 seconds per date/curve combination (depends on curve complexity)
- Cached runs: ~10-50ms per result
- ZODB memory-mapped access: sub-millisecond lookups

**Threading Scalability:**
- Linear speedup up to CPU count for pricing-heavy queries
- Overhead: ~5-10ms per thread
- Optimal `n_jobs`: CPU count for pricing, 1 for I/O-bound curves

**Data Volume:**
- Can handle 1000+ queries × 250 dates (typical quarter)
- Memory footprint: ~100-500MB for cached pricing objects
- ZODB file size: 10-100MB per 100k cached results

---

## 2. FixedRateBondsTB Implementation

### Overview

`FixedRateBondsTB` extends the toolbox pattern to Fixed-Rate Bonds (Treasuries, Agency bonds, etc.). It adds:
- CUSIP-based bond selection
- Two-tier caching: ZODB + Parquet timeseries cache
- BondPricer integration via FixedRateBondsMDP
- Business day filtering with QuantLib calendars

### Class Initialization

```python
from TB.FixedRateBondsTB import FixedRateBondsTB
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

tb = FixedRateBondsTB(
    mdp=mdp,
    date_col="Date",
    cache_stem=None,
    force_refresh=False,
    use_btree=True,
    show_tqdm=True,
    logger=None,
    skip_non_business=True,                    # Skip weekends/holidays
    calendar=None,                             # None = US Government Bond calendar
    # Timeseries cache controls
    use_ts_cache=True,                         # Enable Parquet caching
    ts_base_dir="./data/ts",                   # Parquet file location
    ts_row_group_size=256_000,                 # Rows per Parquet group
    ts_compression="zstd",                     # Compression algorithm
)
```

**Key Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip_non_business` | `bool` | `True` | Skip non-business days |
| `calendar` | `ql.Calendar` | US Gov Bond | QuantLib calendar for business day checking |
| `use_ts_cache` | `bool` | `True` | Enable Parquet timeseries cache layer |
| `ts_base_dir` | `str` | `"./data/ts"` | Root directory for Parquet files |
| `ts_row_group_size` | `int` | `256_000` | Rows per Parquet row group |
| `ts_compression` | `str` | `"zstd"` | Compression: "zstd", "snappy", "gzip", "brotli" |

### Core Method: `get_timeseries()`

```python
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 31),
    queries=[
        FixedRateBondQuery(
            cusip="CT5",                    # Constant Tenor 5Y
            value=FixedRateBondValue.YTM,   # Yield to Maturity
        ),
        FixedRateBondQuery(
            cusip="CT10",
            value=FixedRateBondValue.YTM,
        ),
        FixedRateBondQuery(
            cusip="CT5/CT10",               # Yield curve
            value=FixedRateBondValue.YTM,
        ),
    ],
    n_jobs=4,
    ignore_cache=False,
)

print(df)
# Output: DataFrame with treasury yields
```

### Two-Tier Caching Architecture

FixedRateBondsTB uses two complementary caching layers:

#### Layer 1: ZODB Row Cache (Fast, In-Memory)

```
Key: "v1|<epoch_ns>|<query_fingerprint>"
Value: (date, col_name, value)
```

- **Purpose:** Ultra-fast lookups for recent queries
- **Storage:** ZODB persistent mapping (memory-mapped file)
- **Lookup time:** ~1ms
- **Lifetime:** Until process exit or explicit refresh

#### Layer 2: Parquet Timeseries Cache (Durable, Disk)

```
Structure:
./data/ts/
  asset=FRB::USTS_FEDINVEST_WSJ_LIVE-QL::<fingerprint>/
    date=2025-01-02/
      <sha256>.parquet          # Content-addressed file
    date=2025-01-03/
      <sha256>.parquet
```

- **Purpose:** Durable, queryable long-term storage
- **Storage:** Parquet files with ZODB catalog
- **Lookup time:** ~10-50ms (disk I/O)
- **Compression:** zstd (3-5x compression ratio)
- **Features:**
  - Content-addressed files (deduplication)
  - Partitioned by date for efficient range queries
  - Catalog metadata in ZODB root

### Cache Lookup Workflow

```python
# Step 1: Check Parquet timeseries cache
for q in queries:
    symbol = _ts_symbol_for_query(q)  # Content-addressed
    df_ts = read_timeseries(
        ts_root, symbol,
        start=start, end=end,
        base_dir=ts_base_dir
    )
    if df_ts.empty:
        continue  # Skip to Step 2
    # Extract values matching ref_points
    cached_rows.append((rp, q.col_name(), value))

# Step 2: Check ZODB row cache (fallback)
for d in ref_points:
    for q in queries:
        k = _cache_key(d, q)
        if k in zodb_cache:
            cached_rows.append(zodb_cache[k])

# Step 3: Fetch & price missing
to_price = [d for d in ref_points if not fully_cached(d)]
```

### Bulk Get Data with Fallback

FixedRateBondsTB's `get_timeseries()` calls `mdp.bulk_get_data()` for efficiency:

```python
bulk_map = mdp.bulk_get_data(
    timestamps=to_price_dates,
    cusips=unique_symbols,           # Parsed from queries (e.g., CT5, CT10)
    show_tqdm=True,
    force_refresh=ignore_cache,
    max_workers=n_jobs,
)
# Returns: {date: {cusip: pricer, ...}, ...}
```

If bulk fetch fails, FixedRateBondsTB falls back to per-date on-demand fetches:

```python
try:
    bulk_map = mdp.bulk_get_data(...)
except Exception as e:
    logger.exception(f"bulk_get_data failed. Falling back per-date. Error: {e}")
    bulk_map = {}  # Triggers on-demand fetches below
```

### Handling Spread Queries

Like IRSwapsTB, FixedRateBondsTB auto-detects spread structures:

```python
# Curve (2-legged)
FixedRateBondQuery(
    cusip="CT5/CT10",               # '/' or 'x' are equivalent
    value=FixedRateBondValue.YTM,
)

# Butterfly (3-legged)
FixedRateBondQuery(
    cusip="CT2/CT5/CT10",
    value=FixedRateBondValue.YTM,
)

# CUSIP-specific queries
FixedRateBondQuery(
    cusip="912828C55",              # 7.125% US Treasury due 05/15/25
    value=FixedRateBondValue.YTM,
)
```

### Timeseries Cache Append Logic

After pricing, FixedRateBondsTB appends new results to Parquet:

```python
if use_ts_cache and new_rows_with_q:
    # Group results by query (symbol)
    grouped = defaultdict(list)
    for (dt, col, val), q, _d in new_rows_with_q:
        sym = _ts_symbol_for_query(q)
        grouped[sym].append((pd.Timestamp(dt), float(val), col))
    
    # Write each symbol's timeseries
    for sym, rows in grouped.items():
        # Sort by timestamp
        rows_sorted = sorted(rows, key=lambda x: x[0])
        df_sym = pd.DataFrame(
            {"value": [v for (_t, v, _c) in rows_sorted]},
            index=pd.DatetimeIndex([t for (t, _v, _c) in rows_sorted])
        )
        # Atomically append to partitioned Parquet
        append_timeseries(
            ts_root, sym, df_sym,
            opts=WriteOptions(
                base_dir=ts_base_dir,
                compression=ts_compression,
                row_group_size=ts_row_group_size,
            )
        )
```

---

## 3. TimeseriesBuilder Functionality

### Overview

`TimeseriesBuilder` is a **meta-router** that unifies pricing across multiple asset classes. It:
- Routes queries by product type (IRS, FRB, etc.)
- Handles derived metrics (spreads, asset-swap spreads)
- Composes multi-leg strategies
- Merges results across products

### Initialization

```python
from TB.TimeseriesBuilder import TimeseriesBuilder

builder = TimeseriesBuilder(
    irswaps_tb=irswaps_tb,          # IRSwapsTB instance
    fixedratebonds_tb=frb_tb,       # FixedRateBondsTB instance
    date_col="Date",                # Output date column name
)

# Register additional products (future extensibility)
# builder.register_router("SWAPTIONS", swaptions_tb)
```

### Core Method: `get_timeseries()`

```python
df = builder.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 31),
    queries=[
        # IRS queries
        IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
        
        # FRB queries
        FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM),
        
        # Spreads (computed from IRS + FRB)
        IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="CT5",
            value=IRSwapValue.MMSS,     # Auto-routes to both IRS + FRB
        ),
    ],
    n_jobs=4,
    ignore_cache=False,
    freq=None,
    timestamps=None,
    drop_multilevel_cols=True,      # Drop product level from column names
)

print(df)
# Output: MultiIndex columns -> Single index after drop_multilevel_cols
```

### Product Routing Logic

TimeseriesBuilder dispatches queries based on `.product` attribute:

```python
# Internal logic:
by_product = defaultdict(list)
for q in flat_queries:
    product = q.product  # "IRS", "FRB", etc.
    by_product[product].append(q)

for product, qs in by_product.items():
    tb = routers[product]  # Get IRSwapsTB or FixedRateBondsTB
    df = tb.get_timeseries(start, end, qs, ...)
    per_product_frames.append((product, df))
```

### Spread Calculation (MMSS & SPREADOVER)

TimeseriesBuilder automatically computes spreads:

```python
# Example: IRS-UST spread
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.MMSS,           # = IRS Rate - UST Yield
)

# Internally:
# 1. Creates IRS query: tenor=5Y, value=RATE
# 2. Creates FRB query: cusip=CT5, value=YTM
# 3. Prices both independently
# 4. Computes: spread = irs_rate - frb_ytm (× 100 for bp)
```

**Supported Spread Types:**

| Spread Value | Formula | Example |
|--------------|---------|---------|
| `MMSS` | IRS Rate - UST YTM | 5Y IRS vs 5Y Treasury |
| `SPREADOVER` | Flexible notation (CT or Y) | CT5 IRS vs CT5 UST |
| `PAR_PAR_ASW` | Asset-Swap Spread (par-par) | Bond spread to IRS |

### Asset-Swap Spread (ASW) Computation

For `IRSwapValue.PAR_PAR_ASW` queries:

```python
for q in irswap_asw_queries:
    curve = irs_mdp.get_pricer(...)      # IRS curve
    frb_pricer = frb_mdp.get_pricer(...) # Bond pricer
    
    # Build QuantLib AssetSwap
    ql_bond = frb_pricer.build_fixed_rate_bond(...)
    ql_swap = ql.AssetSwap(
        True,                                    # long bond
        ql_bond,
        frb_pricer.clean_price(),
        ql_index,                               # SOFR index
        0.0,
        ql_schedule,
        ...,
        par_par_asw=True,                      # Par-par method
    )
    
    # Solve for fair spread
    asw_bps = float(ql_swap.fairSpread()) * 10_000
```

### Multi-Product Result Merging

TimeseriesBuilder combines results from multiple products:

```python
# Step 1: Process each product
per_product_frames = []
for product, qs in by_product.items():
    df = routers[product].get_timeseries(...)
    df = pd.concat({product: df}, axis=1)  # MultiIndex columns
    per_product_frames.append((product, df))

# Step 2: Merge spreads if present
if irswap_spread_queries:
    # ... compute IRS rates & UST yields ...
    # Combine into spread_df with MultiIndex
    per_product_frames.append(("SWAPSPREADS", spread_df))

# Step 3: Concatenate all products
out = per_product_frames[0][1]
for _, df in per_product_frames[1:]:
    out = out.join(df, how="outer")

# Step 4: Drop product level from columns (optional)
if drop_multilevel_cols:
    out.columns = out.columns.droplevel(0)
```

---

## 4. Parallel Execution Patterns with Threading

### ThreadPoolExecutor Architecture

Both IRSwapsTB and FixedRateBondsTB use Python's `concurrent.futures.ThreadPoolExecutor` for parallel pricing:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

# Control parallelism via n_jobs parameter
if n_jobs > 1:
    max_workers = int(n_jobs)
else:
    max_workers = None  # Use default (CPU count)

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    # Submit all tasks
    fut_map = {}
    for (d, q, curve) in tasks:
        future = executor.submit(_build_row_for_query, curve, q, d, date_col)
        fut_map[future] = (q, d)
    
    # Collect results as they complete
    for fut in as_completed(fut_map):
        q, d = fut_map[fut]
        try:
            row = fut.result()  # Block until result ready
            new_rows_with_q.append((row, q, curve_name, d))
        except Exception as e:
            logger.exception(f"Pricing failed: {e}")
        finally:
            pbar.update(1)  # Update progress bar
```

**Key Features:**

1. **Task Distribution:** Each task = `(date, query, curve/pricer)` triplet
2. **Result Collection:** `as_completed()` processes results in completion order (not submission order)
3. **Error Isolation:** Exceptions in worker threads don't crash main thread
4. **Progress Tracking:** tqdm progress bar updated per-result

### Serial vs. Parallel Execution

```python
# Serial (n_jobs=1)
for d0, q, curve in tasks:
    try:
        row = _build_row_for_query(curve, q, d0, date_col)
        new_rows_with_q.append((row, q, curve_name, d0))
    except Exception as e:
        logger.exception(...)
    finally:
        pbar.update(1)

# Parallel (n_jobs > 1)
with ThreadPoolExecutor(max_workers=int(n_jobs)) as ex:
    fut_map = {ex.submit(...): (q, d) for (d, q, curve) in tasks}
    for fut in as_completed(fut_map):
        ...
```

### Performance Characteristics

**Threading Model:**
- **GIL**: Python threads can execute pricing code in parallel (pricing is C++ via QuantLib)
- **Overhead**: ~5-10ms per thread creation
- **Speedup**: Near-linear up to CPU count for CPU-bound pricing

**Optimal `n_jobs` Values:**

| Scenario | Recommended n_jobs |
|----------|-------------------|
| Laptop (4 cores), fast internet | 4 |
| Server (16 cores), local MDP | 8-12 |
| High-latency MDP (network I/O) | CPU count (I/O parallelism) |
| Memory-constrained | 1-2 (reduce working set) |
| Testing/debugging | 1 (deterministic) |

### Example: Parallel Pricing with Progress

```python
import logging

logger = logging.getLogger("pricing")

# Create many queries
queries = [
    IRSwapQuery(curve=f"USD-SOFR-1D", tenor=tenor, value=IRSwapValue.RATE)
    for tenor in ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
]

tb = IRSwapsTB(
    mdp=mdp,
    logger=logger,
    show_tqdm=True,
)

# Price in parallel
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 12, 31),
    queries=queries,
    n_jobs=4,  # 4 worker threads
)

# Output:
# PRICING USD-SOFR-1D IRSWAPS...: 100%|████████████| 1750/1750 [00:42<00:00, 41.67 it/s]
# (250 dates × 7 queries = 1750 tasks)
```

---

## 5. ZODB Caching Integration in Toolbox

### ZODB Architecture Overview

The ARBS system uses ZODB (Zope Object Database) for persistent object caching. The TB module integrates via `ZODBCacheMixin`:

```
TB Instance
    ↓
ZODBCacheMixin (base class)
    ↓
ZODB Connection Pool
    ↓
FileStorage (memory-mapped file)
    ↓
Persistent Object Tree (OOBTree or PersistentMapping)
```

### ZODBCacheMixin Methods

IRSwapsTB and FixedRateBondsTB inherit from `ZODBCacheMixin`:

```python
class IRSwapsTB(ZODBCacheMixin):
    _CACHE_ATTR_BASE = "_irswaps_tb_cache"
    _CACHE_VERSION = "v2"
    
    def __init__(self, mdp, ...):
        super().__init__(
            use_btree=use_btree,
            force_refresh=force_refresh
        )
        
        # Initialize ZODB cache
        stem = cache_stem or f"IRSwapsTB_{self._CACHE_VERSION}_{mdp.source}"
        self._cache_path = self.default_cache_path(stem=stem)
        self._cache_attr = f"{self._CACHE_ATTR_BASE}_{self._CACHE_VERSION}"
        
        self.zodb_open_cache(
            cache_attr=self._cache_attr,
            path=self._cache_path,
        )
```

**Key Methods:**

### 1. `zodb_open_cache()`

Opens or creates a ZODB cache:

```python
def zodb_open_cache(
    self,
    *,
    cache_attr: str,
    path: str,
    encode: Callable | None = None,
    decode: Callable | None = None,
    force: bool | None = None,
) -> None:
    """
    Opens ZODB cache with optional codec wrappers.
    
    Args:
        cache_attr: Attribute name to store mapping (e.g., "_irswaps_tb_cache_v2")
        path: File path to ZODB storage
        encode: Optional function to encode values before storage
        decode: Optional function to decode values after retrieval
        force: Force refresh (delete & recreate cache)
    """
```

**Inside Implementation:**

1. Acquires DB handle from registry (connection pooling)
2. Opens transaction with `transaction.manager`
3. Gets root object: `root[cache_attr]`
4. Creates OOBTree or PersistentMapping if missing
5. Sets as instance attribute for fast access

### 2. `batched()` Context Manager

Wraps a transaction:

```python
with self.batched():
    mapping = getattr(self, self._cache_attr)
    for key, value in new_entries:
        mapping[key] = value
    # Auto-commits on __exit__
    # Auto-aborts on exception
```

**Benefits:**
- Atomic writes (all-or-nothing)
- Automatic commit/abort
- Prevents partial updates on failure

### 3. `close_zodb()`

Properly closes ZODB connection:

```python
tb = IRSwapsTB(mdp=mdp)
# ... use tb ...
tb.close_zodb()  # Or use context manager
```

**Or use as context manager:**

```python
with IRSwapsTB(mdp=mdp) as tb:
    df = tb.get_timeseries(...)
# Auto-closes on __exit__
```

### Cache Key Structure

TB uses deterministic cache keys:

```python
# IRSwapsTB
key = f"{version}|{curve_name}|{epoch_ns}|{query_fingerprint}"
# Example: "v2|USD-SOFR-1D|1609459200000000000|a1b2c3d4e5f..."

# FixedRateBondsTB
key = f"{version}|{epoch_ns}|{query_fingerprint}"
# Example: "v1|1609459200000000000|f1e2d3c4b5a..."
```

**Components:**

- **version**: Cache schema version (enables backward compatibility)
- **curve_name**: (IRS only) Curve identifier for workload distribution
- **epoch_ns**: Date as nanoseconds since Unix epoch
- **query_fingerprint**: SHA1 hash of normalized query JSON

### Query Fingerprinting (Determinism)

TB ensures queries with identical semantics hash to the same fingerprint:

```python
def _query_fingerprint(q: "IRSwapQuery") -> str:
    payload = {
        "tenor": str(q.tenor) if q.tenor is not None else None,
        "effective_date": _canonicalize_value(q.effective_date),
        "maturity_date": _canonicalize_value(q.maturity_date),
        "structure": q.structure.name if getattr(q, "structure", None) else None,
        "value": ([_canonicalize_value(v) for v in q.value] if isinstance(q.value, list) else _canonicalize_value(q.value)),
        "structure_kwargs": _canonicalize_value(q.structure_kwargs or {}),
        "name": q.name,
        "risk_weight": q.risk_weight,
        # Note: curve is NOT included (separate axis in key)
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()
```

**Canonicalization:**

```python
def _canonicalize_value(v):
    # Dates → ISO strings
    # Enums → names
    # Lists/dicts → recursively canonicalized + sorted keys
    # Numbers/strings → as-is
```

**Why it matters:**

- Same `tenor`, `value`, `structure` → same fingerprint
- Different query objects → same hash (deduplication)
- Caching transparent to user (no explicit keys)

### Connection Pooling

ZODB uses a thread-safe connection pool:

```python
# IRSwapsTB.__init__() internally:
# self._z_conns: Dict[str, (Connection, _DBHandle)]
# Lazily opens connections on first access
# Reuses connections across threads
```

**Registry Pattern:**

```python
class ZODBCacheMixin:
    _DB_REGISTRY: Dict[str, _DBHandle] = {}  # File path → handle
    _REGISTRY_LOCK = threading.Lock()
    
    @classmethod
    def _acquire_db(cls, path: str) -> _DBHandle:
        # Get or create DB handle
        # Increment reference count
        
    @classmethod
    def _release_db(cls, path: str) -> None:
        # Decrement reference count
        # Close DB when refcnt == 0
```

**Benefits:**
- Singleton DB per file path
- Thread-safe reference counting
- Automatic cleanup on process exit

### ZODB with B-Tree

For large caches, B-Trees are more efficient:

```python
from BTrees.OOBTree import OOBTree

# In zodb_open_cache():
if self._use_btree:
    container = OOBTree()  # Sorted, balanced tree
else:
    container = PersistentMapping()  # Simple hash map

root[cache_attr] = container
```

**B-Tree Benefits:**
- O(log N) lookups vs. O(1) avg for mapping
- Sorted keys (useful for range queries)
- Better memory efficiency for 100k+ entries
- Faster ZODB transaction processing

---

## 6. DataFrame Output Formats

### Standard Output Format

TB methods return pandas DataFrames with consistent structure:

```python
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 31),
    queries=[...],
)

print(df)
#                  USD-SOFR-1D 2Y OUTRIGHT RATE  USD-SOFR-1D 5Y OUTRIGHT RATE  ...
# Date                                                                        ...
# 2025-01-02                           4.820                        4.812  ...
# 2025-01-03                           4.835                        4.827  ...
# ...
# [204 rows x 7 columns]

print(df.index)
# DatetimeIndex(['2025-01-02', '2025-01-03', ...], name='Date', freq=None)

print(df.columns)
# Index(['USD-SOFR-1D 2Y OUTRIGHT RATE', ...], dtype='object')
```

**Structure:**
- **Index**: DatetimeIndex (date/timestamp) with `name='Date'` (customizable)
- **Columns**: Query-derived column names (product, tenor, value type)
- **Values**: Float64 (NaN for missing)
- **Index/Column Names**: Preserved for introspection

### Column Naming Convention

Column names are generated by `query.col_name()`:

```python
# IRSwapQuery
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)
col = q.col_name()
# "USD-SOFR-1D 5Y OUTRIGHT RATE"

# FixedRateBondQuery
q = FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM)
col = q.col_name()
# "CT5 OUTRIGHT YTM"

# With custom name
q = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
    name="My5YSwap"
)
col = q.col_name()
# "My5YSwap"  (custom name takes precedence)
```

### Spread Query Columns

Spreads generate derived column names:

```python
# MMSS (Money Market Swap Spread)
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.MMSS)
col = q.col_name()
# "USD-SOFR-1D 5Y OUTRIGHT MMSS"

# SPREADOVER
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT5", value=IRSwapValue.SPREADOVER)
col = q.col_name()
# "USD-SOFR-1D CT5 OUTRIGHT SPREADOVER"
```

### MultiIndex Columns (TimeseriesBuilder)

When using TimeseriesBuilder with `drop_multilevel_cols=False`:

```python
df = builder.get_timeseries(
    ...,
    drop_multilevel_cols=False,  # Keep product level
)

print(df.columns)
# MultiIndex([
#   ('IRS', 'USD-SOFR-1D 5Y OUTRIGHT RATE'),
#   ('IRS', 'USD-SOFR-1D 10Y OUTRIGHT RATE'),
#   ('FRB', 'CT5 OUTRIGHT YTM'),
#   ('FRB', 'CT10 OUTRIGHT YTM'),
#   ('SWAPSPREADS', 'USD-SOFR-1D 5Y OUTRIGHT MMSS'),
#   ...
# ])

# Access by product
df['IRS']  # All IRS columns
df['FRB']  # All FRB columns
df['SWAPSPREADS']  # All computed spreads

# Access specific column
df[('IRS', 'USD-SOFR-1D 5Y OUTRIGHT RATE')]
```

### Intraday DataFrame Format

When using timezone-aware datetimes with `freq`:

```python
df = tb.get_timeseries(
    start=datetime.datetime(
        2025, 1, 2, 9, 30, 0,
        tzinfo=pytz.timezone("America/New_York")
    ),
    end=datetime.datetime(
        2025, 1, 2, 16, 0, 0,
        tzinfo=pytz.timezone("America/New_York")
    ),
    queries=[...],
    freq="1H",  # Hourly resolution
)

print(df.index)
# DatetimeIndex([
#   '2025-01-02 09:30:00-05:00',
#   '2025-01-02 10:30:00-05:00',
#   ...
#   '2025-01-02 16:00:00-05:00'
# ], tz='America/New_York', name='Date', freq='H')
```

### Empty DataFrame Handling

When no data matches criteria:

```python
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 1, 1),
    queries=[],  # Empty query list
)

print(df)
# Empty DataFrame
# Columns: [Date]
# Index: []
```

### Data Types

TB preserves NumPy/Pandas types:

```python
df.dtypes
# USD-SOFR-1D 2Y OUTRIGHT RATE    float64
# USD-SOFR-1D 5Y OUTRIGHT RATE    float64
# USD-SOFR-1D 10Y OUTRIGHT RATE   float64
# dtype: object

# NaN values (missing data)
df.isna()  # Boolean mask
df.fillna(method='ffill')  # Forward fill
df.dropna()  # Remove rows with NaN
```

### Pivoting Logic

Internally, TB pivots from long to wide format:

```python
# Long format (internal)
# date        col_name                        value
# 2025-01-02  USD-SOFR-1D 2Y OUTRIGHT RATE  4.820
# 2025-01-02  USD-SOFR-1D 5Y OUTRIGHT RATE  4.812
# 2025-01-03  USD-SOFR-1D 2Y OUTRIGHT RATE  4.835
# 2025-01-03  USD-SOFR-1D 5Y OUTRIGHT RATE  4.827

# Pivot to wide
df = df.pivot_table(
    index='date',
    columns='col_name',
    values='value',
    aggfunc='last'  # Last value wins if duplicates
)

# Set date as index
df = df.set_index('date')
```

---

## 7. Query Fingerprinting and Determinism

### Determinism Principles

TB ensures **deterministic caching** through cryptographic query fingerprints:

1. **Idempotent Pricing**: Same query always yields same result
2. **Cache Reuse**: Identical queries hit cache (no redundant computation)
3. **Reproducibility**: Results in notebooks/scripts are reproducible
4. **Deduplication**: Equivalent queries share cache entries

### Fingerprint Generation

Both IRSwapsTB and FixedRateBondsTB normalize queries before hashing:

```python
# Step 1: Extract query properties
payload = {
    "tenor": str(q.tenor) if q.tenor is not None else None,
    "effective_date": _canonicalize_value(q.effective_date),
    "maturity_date": _canonicalize_value(q.maturity_date),
    # ... more fields ...
}

# Step 2: Canonicalize (normalize)
# - Dates → ISO strings
# - Enums → enum.name
# - Dicts → sorted keys
# - Lists → recursively canonicalized

# Step 3: Serialize to JSON
s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
# Example: '{"effective_date":"2025-01-02","tenor":"5Y",...}'

# Step 4: Hash
fingerprint = hashlib.sha1(s.encode("utf-8")).hexdigest()
# Example: "a1b2c3d4e5f..."
```

### Canonicalization Details

```python
def _canonicalize_value(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        # Convert to UTC-naive ISO string
        return _to_utc_naive(v).isoformat()
    
    if isinstance(v, Enum):
        # Enum → enum.name (e.g., IRSwapValue.RATE → "RATE")
        return v.name
    
    if isinstance(v, (list, tuple)):
        # Recursively canonicalize elements
        return [_canonicalize_value(x) for x in v]
    
    if isinstance(v, dict):
        # Sort keys + recursively canonicalize values
        return {k: _canonicalize_value(v[k]) for k in sorted(v.keys())}
    
    # Primitives (numbers, strings, None) pass through
    return v
```

**Why Canonicalization?**

Ensures different query objects with same **meaning** hash identically:

```python
q1 = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
)

q2 = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
)

fingerprint1 = _query_fingerprint(q1)
fingerprint2 = _query_fingerprint(q2)

assert fingerprint1 == fingerprint2  # Same query, same hash
```

### Exclusions from Fingerprint

Some fields are **deliberately excluded** from fingerprinting:

```python
# NOT included in fingerprint:
# - curve (for IRSwapsTB): separate axis in cache key
# - execution terms
# - MDP source (market data provider)
# - market_request (dynamic timestamp, updated per-call)
```

**Why?**

- **curve**: Included separately in cache key (workload distribution)
- **market_request**: Added dynamically per evaluation date
- **source**: Varies between MDPs (handled at initialization)

### Determinism Guarantees

```python
# Same query fingerprint → same cache key (given same date/curve)
key = f"{version}|{curve_name}|{epoch_ns}|{fingerprint}"

# Same key → same cached result (no redundant pricing)
cached_result = cache_map.get(key)

# Different query → different fingerprint → different key → different result
q_modified = replace(q1, tenor="10Y")
fp_modified = _query_fingerprint(q_modified)
assert fp_modified != fingerprint1
```

### Testing Determinism

```python
import datetime
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.IRSwapsTB import _query_fingerprint

# Create two queries with identical properties
q1 = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
    effective_date=datetime.date(2025, 1, 2),
)

q2 = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
    effective_date=datetime.date(2025, 1, 2),
)

fp1 = _query_fingerprint(q1)
fp2 = _query_fingerprint(q2)

assert fp1 == fp2, "Identical queries should hash the same"

# Different query → different hash
q3 = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="10Y",  # Changed tenor
    value=IRSwapValue.RATE,
    effective_date=datetime.date(2025, 1, 2),
)

fp3 = _query_fingerprint(q3)
assert fp1 != fp3, "Different queries should hash differently"
```

---

## 8. Performance Optimization Techniques

### Caching Strategy

#### Multi-Level Cache Hierarchy

```
Layer 1: In-Memory ZODB Cache (1-10ms)
    ↓ (miss)
Layer 2: Parquet Timeseries Cache (10-50ms) [FixedRateBondsTB only]
    ↓ (miss)
Layer 3: Bulk MDP Fetch + Pricing (1-10s)
```

**Optimization:**
- Always check fastest cache first (ZODB)
- Avoid redundant network calls (batch by curve)
- Pre-populate cache on first run (penalty amortized)

#### Cache-Aware Date Selection

```python
# Skip "today" (always fetch fresh)
for d in ref_points:
    if _is_today(d):
        to_fetch.add(d)  # Don't check cache
    else:
        k = _cache_key(d, ...)
        if k not in cache:
            to_fetch.add(d)
```

### Workload Distribution

#### By-Curve Grouping (IRSwapsTB)

```python
# Group queries by curve to minimize MDP calls
by_curve = _group_queries_by_curve(flat_queries)
# {
#   "USD-SOFR-1D": [q1, q2, q3],
#   "USD-LIBOR-3M": [q4, q5],
# }

# Fetch curve once, price all queries against it
for curve_name, qs in by_curve.items():
    curve_objects = mdp.bulk_get_data({
        "curve_name": curve_name,
        "timestamps": missing_dates,
    })
    # Single bulk call replaces multiple per-query calls
```

#### Deduplication

Both IRSwapsTB and FixedRateBondsTB deduplicate underlying symbols:

```python
# FixedRateBondsTB example
needed_symbols = []
for q in queries:
    needed_symbols.extend(_split_components(str(q.cusip)))

# Remove duplicates while preserving order
seen = set()
uniq_symbols = []
for s in needed_symbols:
    if s not in seen:
        seen.add(s)
        uniq_symbols.append(s)

# Fetch each symbol once
mdp.bulk_get_data(cusips=uniq_symbols, ...)
```

### Parallelization Tuning

#### Choosing n_jobs

**Rule of Thumb:**

```python
import multiprocessing

n_cpu = multiprocessing.cpu_count()

# Pricing-heavy, local MDP
n_jobs = n_cpu  # Linear speedup up to CPU count

# I/O-heavy, remote MDP
n_jobs = min(n_cpu * 2, 16)  # Oversubscribe for I/O parallelism

# Memory-constrained
n_jobs = 2  # Reduce working set

# Testing/debugging
n_jobs = 1  # Deterministic execution
```

#### Task Granularity

```python
# Too coarse: few large batches (poor parallelism)
# 2 workers × 500 dates × 50 queries = 4 task groups (underutilized)

# Optimal: many small tasks (good load balancing)
# Task = (date, query) pair
# 1000 dates × 50 queries = 50k tasks (excellent parallelism)
```

### Memory Optimization

#### Curve Caching Per-Date

IRSwapsTB caches curve objects to avoid redundant builds:

```python
built_map = mdp.bulk_get_data({...})  # Curves keyed by date
# Don't rebuild curves for each query

for date, curve in built_map.items():
    for query in queries:
        row = _build_row_for_query(curve, query, date, ...)
        # Reuse same curve object
```

#### Lazy DataFrame Construction

TB builds DataFrames only at the end:

```python
# Accumulate as tuples (lightweight)
new_rows_with_q = []
for row, q, curve_name, d in new_rows_with_q:
    new_rows_with_q.append((row, q, curve_name, d))  # O(1) append

# Construct DataFrame once
df = pd.DataFrame(all_rows, columns=[date_col, "_col", "_val"])
out = df.pivot_table(...)  # Single pivot operation
```

### Batch Transaction Optimization

ZODB writes use `batched()` context manager:

```python
# Single transaction for all writes
with self.batched():
    mapping = getattr(self, cache_attr)
    for key, value in new_entries:
        mapping[key] = value
    # Single commit at exit
```

**vs. naive approach:**

```python
# Multiple commits (slow!)
for key, value in new_entries:
    mapping[key] = value
    transaction.commit()  # 1000s of commits!
```

### Network Optimization (MDP Caching)

TB delegates to MDP for network optimization:

```python
# Built-in MDP caching
built_map = mdp.bulk_get_data({
    "curve_name": curve_name,
    "timestamps": sorted(missing_points),
    "ignore_cache": ignore_cache,  # Bypass MDP cache if needed
    "n_jobs": n_jobs,
})
```

### Intraday Optimization

For high-frequency intraday pricing:

```python
# Don't use daily business day logic
df = tb.get_timeseries(
    start=datetime.datetime(..., tzinfo=pytz.timezone("America/New_York")),
    end=datetime.datetime(..., tzinfo=pytz.timezone("America/New_York")),
    freq="1T",  # 1-minute bars
    # Skip business day calendar, use time-based expansion
)
```

---

## 9. Usage Examples for Bulk Operations

### Example 1: Daily IRS Rate Snapshot

```python
import datetime
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Initialize
mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
tb = IRSwapsTB(mdp=mdp, show_tqdm=True)

# Define US Treasury curve
tenors = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]
queries = [
    IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor=tenor,
        value=IRSwapValue.RATE,
    )
    for tenor in tenors
]

# Fetch 1 quarter of data
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 3, 31),
    queries=queries,
    n_jobs=4,
)

# Display
print(df.describe())
print(f"Shape: {df.shape}")
# Output:
#               USD-SOFR-1D 2Y OUTRIGHT RATE  USD-SOFR-1D 5Y OUTRIGHT RATE  ...
# count                                 62.0                           62.0  ...
# mean                                 4.642                           4.681  ...
# std                                  0.089                           0.103  ...
```

### Example 2: Swap Spreads (IRS - UST)

```python
from TB.TimeseriesBuilder import TimeseriesBuilder
from TB.FixedRateBondsTB import FixedRateBondsTB
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

# Initialize both MDPs
irs_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
frb_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

irs_tb = IRSwapsTB(mdp=irs_mdp)
frb_tb = FixedRateBondsTB(mdp=frb_mdp)

# Create TimeseriesBuilder
builder = TimeseriesBuilder(
    irswaps_tb=irs_tb,
    fixedratebonds_tb=frb_tb,
)

# Define spreads (automatically routes to both products)
queries = [
    # Spreads (IRS - UST)
    IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y", value=IRSwapValue.MMSS),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.MMSS),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.MMSS),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="30Y", value=IRSwapValue.MMSS),
    
    # Also get raw rates/yields
    IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y", value=IRSwapValue.RATE),
    FixedRateBondQuery(cusip="CT2", value=FixedRateBondValue.YTM),
]

# Compute spreads
df = builder.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 31),
    queries=queries,
    n_jobs=4,
    drop_multilevel_cols=True,
)

# Extract just spreads
spreads = df[[
    "USD-SOFR-1D 2Y OUTRIGHT MMSS",
    "USD-SOFR-1D 5Y OUTRIGHT MMSS",
    "USD-SOFR-1D 10Y OUTRIGHT MMSS",
    "USD-SOFR-1D 30Y OUTRIGHT MMSS",
]]

print(spreads.describe())
# Shows: mean = 35-45 bps, std = 5-10 bps
```

### Example 3: Treasury Curve with Spreads

```python
queries = [
    # Outrights
    IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y", value=IRSwapValue.RATE),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="30Y", value=IRSwapValue.RATE),
    
    # Curves (2Y/5Y, 5Y/30Y)
    IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y/5Y", value=IRSwapValue.RATE),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y/30Y", value=IRSwapValue.RATE),
    
    # Butterfly (2Y/10Y/30Y)
    IRSwapQuery(curve="USD-SOFR-1D", tenor="2Y/10Y/30Y", value=IRSwapValue.RATE),
]

df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 12, 31),
    queries=queries,
    n_jobs=8,
)

# Plot curve slope
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Outrights
df[[
    "USD-SOFR-1D 2Y OUTRIGHT RATE",
    "USD-SOFR-1D 5Y OUTRIGHT RATE",
    "USD-SOFR-1D 10Y OUTRIGHT RATE",
    "USD-SOFR-1D 30Y OUTRIGHT RATE",
]].plot(ax=ax1)
ax1.set_title("Yield Curve")
ax1.set_ylabel("Rate (bp)")

# Curves
df[[
    "USD-SOFR-1D 2Y/5Y CURVE RATE",
    "USD-SOFR-1D 5Y/30Y CURVE RATE",
]].plot(ax=ax2)
ax2.set_title("Curve Slopes")
ax2.set_ylabel("Slope (bp)")

plt.tight_layout()
plt.show()
```

### Example 4: Parallel Processing for Speed

```python
# Scenario: Need 100 instruments × 252 trading days = 25,200 data points

from timeit import default_timer

queries = [
    IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor=tenor,
        value=IRSwapValue.RATE,
    )
    for tenor in ["2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y",
                  "2Y/5Y", "5Y/10Y", "10Y/30Y", "2Y/10Y/30Y"]
]

start_date = datetime.date(2024, 1, 1)
end_date = datetime.date(2024, 12, 31)

# Serial (n_jobs=1)
t0 = default_timer()
df_serial = tb.get_timeseries(
    start=start_date,
    end=end_date,
    queries=queries,
    n_jobs=1,
)
t_serial = default_timer() - t0

# Parallel (n_jobs=8)
t0 = default_timer()
df_parallel = tb.get_timeseries(
    start=start_date,
    end=end_date,
    queries=queries,
    n_jobs=8,
)
t_parallel = default_timer() - t0

print(f"Serial:    {t_serial:.2f}s")
print(f"Parallel:  {t_parallel:.2f}s")
print(f"Speedup:   {t_serial/t_parallel:.1f}x")
# Typical: 15s serial → 3s parallel (5x speedup on 8-core machine)
```

### Example 5: Incremental Updates with Caching

```python
# Day 1: Full historical fetch
df1 = tb.get_timeseries(
    start=datetime.date(2020, 1, 1),
    end=datetime.date(2025, 10, 24),
    queries=queries,
    n_jobs=8,
)
# Takes ~30-60s (first time, includes pricing + caching)

# Day 2: Only new dates are priced
df2 = tb.get_timeseries(
    start=datetime.date(2020, 1, 1),
    end=datetime.date(2025, 10, 25),
    queries=queries,
    n_jobs=8,
)
# Takes ~5s (only 1 new date priced, rest from cache)

# Day 3: Force refresh if data is stale
df3 = tb.get_timeseries(
    start=datetime.date(2020, 1, 1),
    end=datetime.date(2025, 10, 25),
    queries=queries,
    n_jobs=8,
    ignore_cache=True,  # Bypass cache
)
# Takes ~30s (all dates repriced)
```

### Example 6: Context Manager (Auto-Close)

```python
# Proper resource cleanup
with IRSwapsTB(mdp=mdp) as tb:
    df = tb.get_timeseries(
        start=datetime.date(2025, 1, 1),
        end=datetime.date(2025, 12, 31),
        queries=queries,
        n_jobs=4,
    )
    # Use df here
# ZODB connection automatically closed on exit

# Manual cleanup (less recommended)
tb = IRSwapsTB(mdp=mdp)
try:
    df = tb.get_timeseries(...)
finally:
    tb.close()
```

### Example 7: Custom Logging

```python
import logging

# Set up custom logger
logger = logging.getLogger("my_pricing_app")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler()
formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Pass to TB
tb = IRSwapsTB(
    mdp=mdp,
    logger=logger,
    show_tqdm=True,
)

# Logs pricing events:
# [2025-01-10 10:30:45] DEBUG: Closing ZODB connection for cache: _irswaps_tb_cache_v2
# [2025-01-10 10:30:46] INFO: PRICING USD-SOFR-1D IRSWAPS...: 100%|████| 1750/1750
```

---

## 10. Integration Patterns with Notebooks and Scripts

### Jupyter Notebook Pattern

```python
# Cell 1: Imports and setup
%load_ext autoreload
%autoreload 2

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import pytz

from TB.IRSwapsTB import IRSwapsTB
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.TimeseriesBuilder import TimeseriesBuilder
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

# Cell 2: Initialize MDPs and toolboxes
mdp_irs = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
mdp_frb = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

tb_irs = IRSwapsTB(mdp=mdp_irs, show_tqdm=True)
tb_frb = FixedRateBondsTB(mdp=mdp_frb, show_tqdm=True)

builder = TimeseriesBuilder(
    irswaps_tb=tb_irs,
    fixedratebonds_tb=tb_frb,
)

# Cell 3: Define analysis period and queries
start = datetime.date(2025, 1, 1)
end = datetime.date(2025, 10, 31)

queries = [
    # IRS rates
    IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="30Y", value=IRSwapValue.RATE),
    
    # Treasury yields
    FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM),
    
    # Spreads
    IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.MMSS),
    IRSwapQuery(curve="USD-SOFR-1D", tenor="30Y", value=IRSwapValue.MMSS),
]

# Cell 4: Fetch data
df = builder.get_timeseries(
    start=start,
    end=end,
    queries=queries,
    n_jobs=4,
)

print(df.head())
print(f"Shape: {df.shape}")

# Cell 5: Analysis
# Plot spreads
spreads = df[[
    "USD-SOFR-1D 5Y OUTRIGHT MMSS",
    "USD-SOFR-1D 30Y OUTRIGHT MMSS",
]]

spreads.plot(figsize=(12, 6), title="Swap Spreads")
plt.ylabel("Spread (bp)")
plt.show()

# Cell 6: More advanced analysis
# Correlation matrix
df.corr()

# Rolling volatility
df.rolling(20).std().plot(figsize=(12, 6), title="20-Day Rolling Volatility")
plt.show()

# Cell 7: Export results
df.to_csv("swap_spreads_2025.csv")
df.to_excel("swap_spreads_2025.xlsx")
```

### Production Script Pattern

```python
# analysis/price_curves.py
"""
Batch script for pricing Treasury curves daily.
Runs via cron: 0 16 * * * python /home/user/analysis/price_curves.py
"""

import datetime
import logging
from pathlib import Path

import pandas as pd

from TB.IRSwapsTB import IRSwapsTB
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.TimeseriesBuilder import TimeseriesBuilder
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/pricing.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting daily pricing...")
    
    try:
        # Initialize
        mdp_irs = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
        mdp_frb = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
        
        with IRSwapsTB(mdp=mdp_irs, logger=logger) as tb_irs, \
             FixedRateBondsTB(mdp=mdp_frb, logger=logger) as tb_frb:
            
            builder = TimeseriesBuilder(
                irswaps_tb=tb_irs,
                fixedratebonds_tb=tb_frb,
            )
            
            # Price last 1 year (incremental caching)
            today = datetime.date.today()
            start = today - datetime.timedelta(days=252)
            
            queries = [
                IRSwapQuery(curve="USD-SOFR-1D", tenor=t, value=IRSwapValue.RATE)
                for t in ["2Y", "5Y", "10Y", "30Y"]
            ] + [
                FixedRateBondQuery(cusip=c, value=FixedRateBondValue.YTM)
                for c in ["CT2", "CT5", "CT10", "CT30"]
            ]
            
            df = builder.get_timeseries(
                start=start,
                end=today,
                queries=queries,
                n_jobs=8,
            )
            
            # Save results
            output_dir = Path("/data/curves")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            filename = output_dir / f"curves_{today.isoformat()}.parquet"
            df.to_parquet(filename, compression="zstd")
            
            logger.info(f"Saved {df.shape} to {filename}")
            
    except Exception as e:
        logger.exception("Pricing failed!")
        raise

if __name__ == "__main__":
    main()
```

### Real-Time Intraday Pattern

```python
# streaming/intraday_pricer.py
"""
Intraday pricing of IRS curves.
"""

import datetime
import pytz
import logging

from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

logger = logging.getLogger(__name__)

def price_intraday(start_time: datetime.datetime, end_time: datetime.datetime, freq: str = "15T"):
    """
    Price IRS curves at intraday frequency.
    
    Args:
        start_time: Timezone-aware start datetime
        end_time: Timezone-aware end datetime
        freq: Frequency string (e.g., "1T", "5T", "15T", "1H")
    """
    assert start_time.tzinfo is not None, "Must provide timezone-aware datetime"
    
    mdp = IRSwapsMDP(source="ERIS_LIVE-RL_REALTIME")
    tb = IRSwapsTB(mdp=mdp, logger=logger)
    
    queries = [
        IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="30Y", value=IRSwapValue.RATE),
    ]
    
    # Fetch intraday data
    df = tb.get_timeseries(
        start=start_time,
        end=end_time,
        queries=queries,
        freq=freq,
        n_jobs=4,
    )
    
    logger.info(f"Fetched {len(df)} intraday observations")
    return df

if __name__ == "__main__":
    # Example: Price Jan 2, 2025 from 9:30 AM to 4:00 PM EST
    ny_tz = pytz.timezone("America/New_York")
    
    start = datetime.datetime(2025, 1, 2, 9, 30, tzinfo=ny_tz)
    end = datetime.datetime(2025, 1, 2, 16, 0, tzinfo=ny_tz)
    
    df = price_intraday(start, end, freq="1H")
    print(df)
```

### Testing Pattern

```python
# tests/test_pricing.py
"""
Unit tests for TB module.
"""

import unittest
import datetime
from unittest.mock import Mock, patch

from TB.IRSwapsTB import IRSwapsTB, _query_fingerprint
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

class TestIRSwapsTB(unittest.TestCase):
    
    def setUp(self):
        self.mdp = Mock(spec=IRSwapsMDP)
        self.tb = IRSwapsTB(mdp=self.mdp, force_refresh=True)
    
    def tearDown(self):
        self.tb.close()
    
    def test_fingerprint_determinism(self):
        """Same query should hash identically."""
        q1 = IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="5Y",
            value=IRSwapValue.RATE,
        )
        q2 = IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="5Y",
            value=IRSwapValue.RATE,
        )
        
        fp1 = _query_fingerprint(q1)
        fp2 = _query_fingerprint(q2)
        
        self.assertEqual(fp1, fp2, "Identical queries should hash the same")
    
    def test_cache_key_format(self):
        """Cache key should follow expected format."""
        q = IRSwapQuery(
            curve="USD-SOFR-1D",
            tenor="5Y",
            value=IRSwapValue.RATE,
        )
        d = datetime.date(2025, 1, 2)
        
        key = self.tb._cache_key(d, "USD-SOFR-1D", q)
        
        # Format: "v2|curve|epoch_ns|fingerprint"
        parts = key.split("|")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "v2")
        self.assertEqual(parts[1], "USD-SOFR-1D")
    
    def test_empty_query_list(self):
        """Empty queries should return empty DataFrame."""
        df = self.tb.get_timeseries(
            start=datetime.date(2025, 1, 1),
            end=datetime.date(2025, 1, 31),
            queries=[],
        )
        
        self.assertTrue(df.empty, "Empty queries should return empty DataFrame")

if __name__ == "__main__":
    unittest.main()
```

---

## Summary: Quick Start Guide

### 1-Minute Setup

```python
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
import datetime

mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
tb = IRSwapsTB(mdp=mdp)

df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 12, 31),
    queries=[
        IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE),
    ],
    n_jobs=4,
)

print(df)
```

### Key Takeaways

1. **IRSwapsTB**: Bulk pricing of interest rate swaps with ZODB caching
2. **FixedRateBondsTB**: Bulk pricing of bonds with dual-layer caching (ZODB + Parquet)
3. **TimeseriesBuilder**: Meta-router for multi-product analysis
4. **Deterministic**: Query fingerprinting ensures reproducible results
5. **Fast**: Multi-level caching + parallelization (typical: 5-10x speedup)
6. **Production-Ready**: Context managers, error handling, logging

### Next Steps

- Review notebook examples: `timeseries_builder.ipynb`
- Explore `IRSwapValue` and `FixedRateBondValue` enums for available metrics
- Tune `n_jobs` for your hardware
- Monitor cache hits with `ignore_cache=True` to see fresh pricing time

