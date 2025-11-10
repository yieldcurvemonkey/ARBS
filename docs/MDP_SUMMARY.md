# ARBS Market Data Provider (MDP) - Executive Summary

## Document Location
Full comprehensive analysis: `/home/user/ARBS/docs/MDP_COMPREHENSIVE_ANALYSIS.md` (1514 lines)

## Quick Reference

### What is MDP?
The Market Data Provider module is the core data abstraction layer that:
- Fetches market data from multiple sources (CME, SDR, GSQUANT, WSJ, FedInvest, Webull, etc.)
- Builds yield curves and bond pricers
- Caches results for performance
- Integrates with the backtesting engine

### Key Abstraction
```python
class MarketDataProvider(ABC, Generic[_GP]):
    def get_pricer(self, request: dict) -> _GP: ...
```

A single `get_pricer()` call:
1. Takes a request dict (curve_name, timestamp, source-specific params)
2. Fetches raw market data
3. Builds a curve/pricer object
4. Returns it to backtester

---

## Data Providers

### IRSwapsMDP - Interest Rate Swaps

**Supported Sources:**
| Source | Backend | Timeline | Data | Bulk |
|--------|---------|----------|------|------|
| `CME_NY_EOD_LIVE-QL_BASIC` | QuantLib | Historical EOD | CME swaps | Yes |
| `CME_NY_EOD_LIVE-RL_BASIC` | RatesLib | Historical EOD | CME swaps | Yes |
| `ERIS_EOD_LIVE-RL_BASIC` | RatesLib | Historical EOD | Eris SEF | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_MT_Q12` | RatesLib | Intraday snapshots | SDR | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_MT_Q16` | RatesLib | Intraday snapshots | SDR | Yes |
| `GSQUANT-RL` | RatesLib | Historical EOD | GS Quant | No |

**Usage:**
```python
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-RL_BASIC")
pricer = mdp.get_pricer({
    "curve_name": "USD-SOFR-1D",
    "timestamp": datetime.date(2024, 1, 15)
})
```

---

### FixedRateBondsMDP - UST Bonds

**Supported Sources:**
| Source | Timeline | Data | Features |
|--------|----------|------|----------|
| `USTS_FEDINVEST_WSJ_LIVE-QL` | Live + 3D intraday | FedInvest + WSJ | QL backend |
| `USTS_WEBULL_WSJ_LIVE-RL` | Live + Intraday | Webull + WSJ | RL backend |
| `USTS_PUBLICDOTCOM_WSJ_LIVE-QL` | Historical | Public.com | QL backend |

**Features:**
- Alias resolution: `CT5` (constant-maturity 5Y), `O10` (rank-1 10Y), `0125` (Jan 2025 maturity)
- Bond reference data from FiscalData.treasury.gov
- Parallel fetching with ThreadPoolExecutor
- ZODB persistence caching

**Usage:**
```python
mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
pricers = mdp.get_pricer({
    "cusips": ["CT5", "CT10", "CT30"],  # or actual CUSIPs
    "timestamp": "live"
})
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Backtesting Engine                  │
│                 (BT/query_engine.py)                 │
└─────────────────────┬───────────────────────────────┘
                      │ request = build_mdp_request(now)
                      │ pricer = mdp.get_pricer(request)
                      ▼
┌─────────────────────────────────────────────────────┐
│           MarketDataProvider (Abstract)              │
│              ├─ IRSwapsMDP                           │
│              └─ FixedRateBondsMDP                    │
└─────────────────┬───────────────────────────────────┘
                  │
        ┌─────────┼──────────────────────┐
        ▼         ▼         ▼             ▼
    ┌────────┐ ┌─────┐  ┌──────────┐  ┌────────┐
    │  CME   │ │ SDR │  │GSQUANT   │  │ WSJ    │
    │EOD     │ │Intra│  │Bonds     │  │Webull  │
    └────────┘ └─────┘  └──────────┘  └────────┘
        │         │         │             │
        └─────────┴─────────┴─────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
    ┌─────────┐         ┌─────────┐
    │QuantLib │         │RatesLib │
    │ (QL)    │         │ (RL)    │
    └────┬────┘         └────┬────┘
         │                   │
    ┌────▼───────────────────▼────┐
    │  Curve/Bond Objects          │
    │  (Pricers)                   │
    └──────────────────────────────┘
         │
    ┌────▼──────────────────────────┐
    │  ZODB/Recipe Hash Caching      │
    │  (~/.cache/arbs/MDP/...)       │
    └────────────────────────────────┘
```

---

## Data Flow: From Raw Quotes to Pricer

### Example: CME EOD Curve

```
1. FETCH DATA
   CMEFetcherV2.build_rl_eod_curves()
   └─ Download CME swap quotes (2Y, 3Y, ..., 30Y)
   └─ Download SOFR/OIS futures (3M, 6M)
   └─ Download FRED SOFR fixings

2. BUILD CURVE
   Solver([rl_curve], [instruments=[swap2Y, swap3Y, ...]], [rates=[...]])
   └─ Construct RatesLib curve via rate solver
   └─ Serialize to JSON

3. INJECT FIXINGS
   Fetch historical SOFR fixings (T-1 USBD)
   └─ Store in pricer for revaluation

4. CACHE
   ZODB: {curve_id: {ts, rl_json}} → ~/.cache/arbs/MDP/...

5. RETURN PRICER
   RLIRSwapCurve(rl_curve_handle, fixings_series, metadata)
```

---

## Caching Strategy

### Level 1: Request-Level Cache (Backtester)
```python
# BT/query_engine.py
_cache: Dict[str, Any]  # sig → pricer
```
- Deduplicates identical requests within same backtest run

### Level 2: ZODB Cache (MDP)
```
~/.cache/arbs/MDP/
├── FixedRateBondPricer_Cache.fs     # Bond pricers
├── SDR_INTRADAY-RL_CURVE_CACHE.fs   # Intraday curves
├── ERIS_EOD_LIVE-RL_BASIC.fs        # Eris curves
```
- Persistent storage across runs
- Multi-threaded safe
- Automatic cleanup

### Level 3: Recipe Hash Cache (SDR Intraday)
```python
key = f"{curve_id}__snap={ts}__fx={sofr_hash}__ser=12__sfr=2__fomc=2"
# Same inputs → same cache key → deterministic curves
```
- Deduplicates identical curve builds
- Enables efficient bulk operations

### Level 4: Fixings Cache (Filesystem)
```
~/.cache/arbs/MDP/IRSwaps/fixings_cache/
├── USD-SOFR-1D_fixings/
│   ├── 2024-01-15/fixings.csv
│   ├── 2024-01-14/fixings.csv
│   └── 2024-01-13/fixings.csv
```
- Local CSV storage
- Auto-cleanup (keeps 3 recent dirs)
- Validates published dates before caching

---

## Backend Comparison: QuantLib vs RatesLib

| Feature | QuantLib | RatesLib |
|---------|----------|----------|
| **Maturity** | Mature (20+ years) | Newer (2-3 years) |
| **JSON Serialization** | ❌ (pickle only) | ✅ (native) |
| **Caching Efficiency** | Lower | Higher |
| **Bulk Performance** | Slower | Faster |
| **Interpolation** | 10+ algorithms | Primarily log-linear |
| **Data Sources** | CME only | CME + SDR + GSQUANT |
| **Use Case** | Historical baselines | Intraday, research |

---

## Historical vs Intraday Data

### Historical (Date-Based)
```python
timestamp: datetime.date(2024, 1, 15)  # EOD close
```
- Single snapshot per day
- Fetched from CME EOD, GSQUANT, FedInvest
- Cached by (date, curve_name)
- Deterministic: same date → same curve

### Intraday (DateTime-Based)
```python
timestamp: datetime.datetime(2024, 1, 15, 14, 30, 0)  # 2:30 PM ET
```
- Multiple snapshots per day
- Fetched from SDR repositories (updated ~hourly)
- Cached by recipe hash (snap + fixings content)
- Time-aware: handles FOMC fixing delays

---

## Key Design Patterns

### 1. Generic Pricer Interface
```python
pricer = mdp.get_pricer(request)
# pricer is either:
#   - QLIRSwapCurve(ql_curve_handle, ql_swap_index)
#   - RLIRSwapCurve(rl_curve_handle, fixings_series)
#   - QLFixedRateBondPricer(ytm, cpn, maturity)
#   - RLFixedRateBondPricer(ytm, cpn, maturity)
```

### 2. Bulk Operations
```python
# Parallel fetch of multiple curves/dates
pricers = mdp.bulk_get_data({
    "curve_name": "USD-SOFR-1D",
    "timestamps": [date1, date2, ...],
    "n_jobs": 8  # ThreadPoolExecutor threads
})
# Returns: Dict[timestamp → pricer]
```

### 3. Request Templating
```python
# Backtester injects timestamp dynamically
query.market_request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": "now"  # Replaced by engine
}
```

### 4. Context Management (Bonds)
```python
with FixedRateBondsMDP() as mdp:
    pricers = mdp.bulk_get_data(...)
    # Auto-commits to ZODB on exit
```

---

## Adding a New Data Source - Checklist

**1. Define Fetcher**
```python
# MDP/IRSwaps/MyNewSource/rl_basic/MyFetcher.py
class MyFetcher(BaseFetcher):
    def build_rl_eod_curves(self, curve, bdates, **kwargs) -> Dict[date, rl.Curve]:
        # Fetch data, bootstrap curve, return dict
```

**2. Register in IRSwapsMDP**
```python
# MDP/IRSwaps/IRSwapsMDP.py
elif self.source.upper() in ["MY_NEW_SOURCE-RL_BASIC"]:
    # Instantiate fetcher, build curves, wrap in RLIRSwapCurve
```

**3. Add Curve Definitions**
```python
# Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py
RATESLIB_CURVE_DEFINITIONS["MY-CURVE"] = {
    "Calendar": "us",
    "DayCounter": "ACT/360",
    "ReferenceRate": rl.SOFR,
    ...
}
```

**4. Test**
```python
mdp = IRSwapsMDP(source="MY_NEW_SOURCE-RL_BASIC")
pricer = mdp.get_pricer({
    "curve_name": "MY-CURVE",
    "timestamp": datetime.date(2024, 1, 15)
})
assert pricer is not None
```

See full guide in [MDP_COMPREHENSIVE_ANALYSIS.md](#adding-new-data-sources)

---

## Common Issues & Solutions

### Issue: "Curve Build does not exist"
**Cause**: Source string not recognized  
**Solution**: Check spelling in `IRSwapsMDP._get_curve()` or `FixedRateBondsMDP._get_multi_pricers()`

### Issue: "SOFR fixings not yet published"
**Cause**: Requesting curve before T-1 USBD fixing available  
**Solution**: Use earlier date or handle via FIXINGS_TOL logic (automatic for SDR intraday)

### Issue: Alias resolution fails
**Cause**: Reference data missing or date out of range  
**Solution**: Ensure FiscalData.treasury.gov is accessible; check date is between issue & maturity

### Issue: ZODB cache corruption
**Cause**: Interrupted writes or concurrent access  
**Solution**: Delete cache file (`~/.cache/arbs/MDP/.../Cache.fs`) and rebuild

---

## Performance Tips

1. **Use bulk_get_data()** for multiple timestamps (parallel execution)
2. **Warm the cache** by fetching historical dates first
3. **Share MDPs across backtests** to reuse cached curves
4. **Use n_jobs > 1** for bond bulk operations
5. **Force refresh selectively** with `force_refresh=True` only when needed

---

## File Locations

**Core Module:**
- Abstract Base: `/home/user/ARBS/MDP/MarketDataProvider.py`
- IR Swaps: `/home/user/ARBS/MDP/IRSwaps/IRSwapsMDP.py`
- Bonds: `/home/user/ARBS/MDP/FixedRateBonds/FixedRateBondsMDP.py`

**Caching:**
- ZODB Cache: `Caching/ZODBCacheMixin.py`
- Fixings Cache: `MDP/IRSwaps/fixings_cache/fixings_cache.py`
- Recipe Hashing: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/_RLCurveCache.py`

**Data Sources:**
- CME: `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/ | rl_basic/`
- SDR: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/`
- GSQUANT: `MDP/IRSwaps/GSQUANT/rl_basic/build.py`
- Bonds: `MDP/FixedRateBonds/{FEDINVEST,WSJ,WEBULL,PUBLICDOTCOM}/`

**Integration:**
- Backtester: `BT/query_engine.py` → `QueryDrivenBacktest`
- Query Base: `Query/Base/BaseQuery.py` → `build_mdp_request()`

---

## Summary

The ARBS MDP module provides a **production-grade, extensible** market data abstraction that:

✓ Supports multiple data sources (CME, SDR, GSQUANT, WSJ, FedInvest, Webull)  
✓ Offers dual backends (QuantLib for stability, RatesLib for speed)  
✓ Implements multi-level caching (request-level, ZODB, recipe hashing, fixings)  
✓ Handles both historical (EOD) and intraday (snapshots) data  
✓ Integrates seamlessly with backtester via generic `get_pricer()` interface  
✓ Enables easy addition of new sources via well-defined patterns  

**For detailed implementation details, see**: `/home/user/ARBS/docs/MDP_COMPREHENSIVE_ANALYSIS.md`

