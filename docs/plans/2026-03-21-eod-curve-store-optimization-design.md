# EOD Curve Store Optimization — Vectorized EOD Engine

**Date:** 2026-03-21
**Status:** Approved
**Approach:** Vectorized EOD Engine (Approach B) with elements of Approach A

## Problem

Building EOD timeseries is slow. The intraday STIRT store has been optimized with analytics panels, DuckDB L1 cache, and curve-store fast paths, but the EOD path has critical gaps:

1. **DuckDB L1 cache disabled by default** (`DEFAULT_USE_DUCKDB = False`) — every read falls through to Parquet scan
2. **Per-tenor, per-date pricing** — 200+ tenors x N dates priced individually via `_build_row_for_query()`
3. **No vectorized rate computation** — each (date, tenor) reconstructs a curve object and prices independently
4. **Analytics panel may not be populated** for EOD sources during backfill

## Solution: Layered Acceleration with Vectorized Engine

### Architecture

```
Query arrives (curve_name, tenors[], date_range)
        |
        v
+--- DuckDB L1 Cache ----------------------------+
|  Sub-ms read for (symbol, date) pairs           |
|  Hit -> return immediately                       |
+-----------------+-------------------------------+
                  | miss
                  v
+--- Analytics Panel (Parquet) -------------------+
|  Wide-format pre-computed rates at desk tenors   |
|  Single DuckDB Hive scan per curve               |
|  Hit -> return + backfill DuckDB L1              |
+-----------------+-------------------------------+
                  | miss
                  v
+--- Vectorized EOD Engine (NEW) -----------------+
|  1. Read raw nodes as columnar arrays            |
|  2. Compute payment schedules per tenor          |
|  3. Log-linear interpolate DFs at payment dates  |
|  4. Apply par swap rate formula (NumPy)          |
|  5. Write results -> Analytics + DuckDB + Parquet|
+-------------------------------------------------+
```

No QuantLib/rateslib fallback needed — vectorized engine covers 100% of EOD tenors (spot outrights, forward-starting, medium-term granular, spreads).

## Core Math

### Par Swap Rate Formula

```
Par Swap Rate = (DF_effective - DF_maturity) / SUM(DF_i * tau_i)
```

Where:
- `DF_effective` = discount factor at effective date (1.0 for spot-starting)
- `DF_maturity` = discount factor at maturity date
- `DF_i` = discount factors at each fixed leg payment date
- `tau_i` = accrual fraction for each period (ACT/360)

### Log-Linear DF Interpolation

```python
log_dfs = np.log(node_discount_factors)
t_target = (target_date - curve_base_date).days
t_nodes = [(node - curve_base_date).days for node in node_dates]
log_df_interp = np.interp(t_target, t_nodes, log_dfs)
df_interp = np.exp(log_df_interp)
```

### Conventions (USD-SOFR-1D)

- Day count: ACT/360
- Payment frequency: Annual
- Settlement days: T+2
- Business day convention: Modified Following
- Calendar: US Government Bond

### Tenor Coverage

| Tenor Type | Example | Vectorized |
|---|---|---|
| Spot outright | "5Y" | Yes |
| Forward-starting | "2Y3Y" | Yes |
| Medium-term granular | "30M", "42M" | Yes |
| Spread (derived) | 2s10s | Yes (difference of outrights) |

## Integration Points

### A. Backfill Path (eod_curve_service.py)

**Current:**
```
per batch: bulk_get_data() -> raw curves -> CurveStore
per batch: _warm_timeseries_window() -> 200+ _build_row_for_query() calls
```

**New:**
```
per batch: bulk_get_data() -> raw curves -> CurveStore  (unchanged)
ONCE at end: vectorized_engine.compute_eod_panel(curve_name, start, end, tenors)
  -> single DuckDB scan of raw nodes
  -> vectorized rate computation for all tenors x all dates
  -> batch write to: Analytics Panel + DuckDB L1 + Parquet TS
```

### B. Interactive Read Path (TimeseriesBuilder)

**New flow:**
```
DuckDB L1 hit -> return (sub-ms)
Analytics panel hit -> return + backfill DuckDB
Vectorized engine on missing dates -> compute + write back -> return
```

### Config Changes

```python
DEFAULT_USE_DUCKDB = True   # was False
DEFAULT_USE_VECTORIZED_ENGINE = True  # new flag, opt-out via --no-vectorized-engine
```

## Performance Model

### Backfill (1 year, 252 dates, 200 tenors)

| Stage | Current | Optimized |
|---|---|---|
| Raw curve calibration | ~5-10 min | ~5-10 min (unchanged) |
| Timeseries warm (Phase 2) | ~8-10 min | **~1-2s** |
| **Total** | ~15-20 min | **~5-10 min** |

### Optimized Phase 2 Breakdown

| Step | Cost |
|---|---|
| Read raw nodes (DuckDB scan) | ~100-200ms |
| Schedule computation | ~50ms |
| DF interpolation + rate calc | ~200-500ms |
| Write DuckDB L1 | ~100ms |
| Write analytics panel | ~50ms |
| Write Parquet TS | ~500ms |
| **Total** | **~1-2s** |

### Interactive Reads

| Scenario | Current | Optimized |
|---|---|---|
| Warm cache (DuckDB hit) | N/A (disabled) | **<1ms** |
| Analytics panel hit | ~50-100ms | ~50-100ms |
| Cold miss | ~2-5s | **~100-500ms** |

### Memory: <10MB peak for a full year

## Error Handling

- **Out-of-range interpolation:** Detect before interpolation, exclude as NaN, log warning
- **Missing raw nodes:** Skip dates with no calibrated curve
- **Schedule edge cases:** Use QuantLib calendar for business day adjustment
- **Write failures:** Log and continue — data can be recomputed

## Testing Strategy

### 1. Numerical Validation (gate)
- Compare vectorized vs `_build_row_for_query()` for 10 sample dates x all tenors
- Assertion: `|diff| < 1e-6` (0.01bp)

### 2. Interpolation Edge Cases
- Maturity on node date, between first/last nodes, beyond last node
- Degenerate single-node curve

### 3. Schedule Generation
- Verify payment dates match QuantLib `MakeVanillaSwap` for spot and forward tenors
- Verify ACT/360 accrual fractions
- Leap years, holiday-adjacent dates

### 4. Integration Round-Trip
- Backfill 5 dates, verify DuckDB L1 + analytics panel + Parquet TS populated
- Read back via `TimeseriesBuilder.get_timeseries()`, confirm DuckDB fast path taken

### 5. Performance Regression
- Benchmark 252 dates x 200 tenors, assert Phase 2 < 5s

## New Files

- `Caching/eod_vectorized_engine.py` — core vectorized computation module
- `tests/test_eod_vectorized_engine.py` — numerical validation + edge case tests

## Modified Files

- `scripts/eod_curve_service.py` — replace `_warm_timeseries_window()` with vectorized engine call, flip `DEFAULT_USE_DUCKDB`
- `TB/TimeseriesBuilder.py` — add vectorized engine as fallback before curve reconstruction in interactive path
- `Caching/computed_timeseries_store.py` — no changes (used as-is for write-back)
- `Caching/curve_store.py` — no changes (used as-is for raw node reads)
