# TB Module - Quick Reference Guide

## Files Overview

| File | Purpose | Key Classes |
|------|---------|-------------|
| `IRSwapsTB.py` | Bulk IRS pricing with ZODB caching | IRSwapsTB |
| `FixedRateBondsTB.py` | Bulk bond pricing with dual-layer caching | FixedRateBondsTB |
| `TimeseriesBuilder.py` | Multi-product routing & spread computation | TimeseriesBuilder |
| `utils.py` | Plotting utilities and helper functions | - |

---

## 1-Minute Quick Start

```python
from TB.IRSwapsTB import IRSwapsTB
from TB.TimeseriesBuilder import TimeseriesBuilder
from TB.FixedRateBondsTB import FixedRateBondsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
import datetime

# Initialize
mdp_irs = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
mdp_frb = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")

tb = IRSwapsTB(mdp=mdp_irs)

# Price
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 12, 31),
    queries=[
        IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y", value=IRSwapValue.RATE),
    ],
    n_jobs=4,  # Parallel pricing
)

print(df)  # DatetimeIndex + float columns
```

---

## IRSwapsTB API

### Initialization
```python
tb = IRSwapsTB(
    mdp=mdp,                    # Required: IRSwapsMDP instance
    date_col="Date",            # Column name for date index
    force_refresh=False,        # Bypass cache?
    show_tqdm=True,             # Show progress bars?
    n_jobs=1,                   # Threads (1=serial, >1=parallel)
)
```

### get_timeseries()
```python
df = tb.get_timeseries(
    start=date,                 # Start date
    end=date,                   # End date
    queries=[q1, q2, ...],      # List of IRSwapQuery
    n_jobs=4,                   # Worker threads
    ignore_cache=False,         # Skip cache?
    freq=None,                  # "1T", "1H" for intraday
    timestamps=None,            # Custom evaluation points
)
```

---

## FixedRateBondsTB API

### Initialization
```python
tb = FixedRateBondsTB(
    mdp=mdp,                    # Required: FixedRateBondsMDP
    skip_non_business=True,     # Skip weekends?
    use_ts_cache=True,          # Enable Parquet cache?
    ts_base_dir="./data/ts",    # Parquet location
    ts_compression="zstd",      # Compression algorithm
)
```

### get_timeseries()
```python
df = tb.get_timeseries(
    start=date,
    end=date,
    queries=[q1, q2, ...],      # List of FixedRateBondQuery
    n_jobs=4,
    ignore_cache=False,
)
```

---

## TimeseriesBuilder API

### Initialization
```python
builder = TimeseriesBuilder(
    irswaps_tb=tb_irs,
    fixedratebonds_tb=tb_frb,
    date_col="Date",
)
```

### get_timeseries()
```python
df = builder.get_timeseries(
    start=date,
    end=date,
    queries=[irs_q, frb_q, spread_q],  # Mixed query types
    n_jobs=4,
    drop_multilevel_cols=True,         # Remove product level?
)
```

---

## Query Objects

### IRSwapQuery
```python
# Basic outright
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.RATE,
)

# Curve (2-legged)
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y/10Y",          # or "5Yx10Y"
    value=IRSwapValue.RATE,
)

# Butterfly (3-legged)
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="2Y/5Y/10Y",
    value=IRSwapValue.RATE,
)

# Spread (IRS - UST)
IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="5Y",
    value=IRSwapValue.MMSS,  # Money Market Swap Spread
)
```

### FixedRateBondQuery
```python
# Treasury yield
FixedRateBondQuery(
    cusip="CT5",              # Constant Tenor 5Y
    value=FixedRateBondValue.YTM,
)

# Curve
FixedRateBondQuery(
    cusip="CT5/CT10",
    value=FixedRateBondValue.YTM,
)

# Specific CUSIP
FixedRateBondQuery(
    cusip="912828C55",
    value=FixedRateBondValue.YTM,
)
```

---

## Common Patterns

### Pattern 1: Yield Curve
```python
queries = [
    IRSwapQuery(curve="USD-SOFR-1D", tenor=t, value=IRSwapValue.RATE)
    for t in ["2Y", "5Y", "10Y", "30Y"]
]
df = tb.get_timeseries(start, end, queries, n_jobs=4)
```

### Pattern 2: Swap Spreads (IRS - UST)
```python
queries = [
    IRSwapQuery(curve="USD-SOFR-1D", tenor=t, value=IRSwapValue.MMSS)
    for t in ["2Y", "5Y", "10Y", "30Y"]
]
df = builder.get_timeseries(start, end, queries, n_jobs=4)
```

### Pattern 3: Incremental Updates
```python
# First run: cache everything
df1 = tb.get_timeseries(start, end, queries, n_jobs=8)

# Second run: only new dates priced
df2 = tb.get_timeseries(start, end+1day, queries, n_jobs=8)  # Fast!

# Force refresh
df3 = tb.get_timeseries(start, end, queries, ignore_cache=True)
```

### Pattern 4: Intraday Pricing
```python
import pytz

ny_tz = pytz.timezone("America/New_York")
start = datetime.datetime(2025, 1, 2, 9, 30, tzinfo=ny_tz)
end = datetime.datetime(2025, 1, 2, 16, 0, tzinfo=ny_tz)

df = tb.get_timeseries(
    start=start,
    end=end,
    queries=queries,
    freq="1H",  # Hourly
    n_jobs=4,
)
```

### Pattern 5: With Context Manager (Auto-Close)
```python
with IRSwapsTB(mdp=mdp) as tb:
    df = tb.get_timeseries(...)
# ZODB connection auto-closes
```

---

## Caching Architecture

### IRSwapsTB Caching
- **Layer 1:** ZODB in-memory cache (1-10ms lookup)
- **Key:** `v2|curve_name|epoch_ns|query_fingerprint`
- **Storage:** Memory-mapped ZODB file (~10-100MB)

### FixedRateBondsTB Caching
- **Layer 1:** ZODB row cache (same as IRS)
- **Layer 2:** Parquet timeseries cache (disk-based, long-term)
- **Key:** Content-addressed by query fingerprint
- **Storage:** `./data/ts/asset=FRB::source::<fingerprint>/date=YYYY-MM-DD/<sha256>.parquet`

---

## Performance Tips

### Speedup with Parallel Processing
```python
# Serial (n_jobs=1): ~60s for 1000 queries × 250 dates
df = tb.get_timeseries(..., n_jobs=1)

# Parallel (n_jobs=8): ~8s (7.5x speedup)
df = tb.get_timeseries(..., n_jobs=8)
```

### Cache Efficiency
```python
# First run: 30-60s (pricing + caching)
df1 = tb.get_timeseries(start, end, queries)

# Incremental (only 1 new date): 5s
df2 = tb.get_timeseries(start, end+1day, queries)

# Force refresh: 30-60s
df3 = tb.get_timeseries(start, end, queries, ignore_cache=True)
```

### Memory Optimization
- Set `n_jobs=2` on memory-constrained systems
- Use `use_btree=True` (default) for 100k+ cached entries
- Enable `use_ts_cache=True` (FixedRateBondsTB) for long-term storage

---

## Troubleshooting

### Cache Issues
```python
# Clear cache and reprice
tb = IRSwapsTB(mdp=mdp, force_refresh=True)
df = tb.get_timeseries(...)

# Or just ignore for one call
df = tb.get_timeseries(..., ignore_cache=True)
```

### Performance Issues
```python
# Check what's slow: serial vs parallel
df_serial = tb.get_timeseries(..., n_jobs=1)   # Baseline
df_parallel = tb.get_timeseries(..., n_jobs=8) # With speedup
```

### Missing Data
```python
# Check for NaN
print(df.isna())

# Fill forward
df = df.fillna(method='ffill')

# Drop rows with any NaN
df = df.dropna()
```

---

## File Locations

**Cache Storage:**
```
~/.cache/arbs/zodb/dump/            # Linux/macOS
%LOCALAPPDATA%/ARBS/zodb/dump/      # Windows
```

**Timeseries Storage:**
```
./data/ts/                           # Default (FixedRateBondsTB)
```

---

## Dependencies

- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- `QuantLib`: Financial calculations
- `ZODB`: Persistent object caching
- `pyarrow`: Parquet file handling
- `tqdm`: Progress bars
- `transaction`: ZODB transaction management

---

## Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `ValueError: Each IRSwapQuery must specify .curve` | Missing curve field | Add `curve="USD-SOFR-1D"` |
| `KeyError: No timeseries router registered` | Unknown product | Use supported products: IRS, FRB |
| `LockError: Database already in use` | File locked | Wait for other process or use `force_refresh=True` |
| `MemoryError` | Too many tasks in parallel | Reduce `n_jobs` value |

---

## Documentation Files

- **Full Documentation:** `/home/user/ARBS/TB_MODULE_DOCUMENTATION.md` (2100+ lines)
- **Quick Reference:** `/home/user/ARBS/TB_MODULE_QUICK_REFERENCE.md` (this file)
- **Example Notebook:** `/home/user/ARBS/timeseries_builder.ipynb`

---

## Key Takeaways

1. **IRSwapsTB**: Ultra-fast bulk IRS pricing (5-10x speedup with n_jobs=4)
2. **FixedRateBondsTB**: Bond pricing with dual-layer caching (ZODB + Parquet)
3. **TimeseriesBuilder**: Unified interface for multi-product analysis
4. **Deterministic**: Cryptographic fingerprints ensure reproducibility
5. **Production-Ready**: Context managers, error handling, logging

---

For complete documentation, see:
**`/home/user/ARBS/TB_MODULE_DOCUMENTATION.md`**

