# AlphaVantage Data Layer - Corrected Architecture

## Status: READY FOR IMPLEMENTATION
Created: 2025-11-14
API Key: QLGCJCCK8X4ZY6VC
Branch: `claude/next-phase-01EqwdS3CUR9K1dEnuN8VeCt`

---

## Core Architecture Principle

**THE BACKTESTER IS NOT A DATA LOADER**

Data loading happens OUTSIDE the backtest. The backtest requests data from a Market Data Provider (MDP) which returns PRE-LOADED cached data.

---

## Corrected Architecture

```
[DATA LOADING PHASE - Runs OUTSIDE backtest]
1. Data Loader Script (tests/validation/load_alphavantage.py)
   ↓
   Fetch from AlphaVantage API (rate-limited)
   ↓
2. SQLiteCache
   ↓
   Store prices persistently

---[BACKTEST PHASE - Uses cached data]---

3. CachedMarketDataProvider (MDP)
   ↓
   Read from SQLiteCache (NO API calls)
   ↓
4. EquityAdapter
   ↓
   Convert MDP data → signal format
   ↓
5. Backtest
   ↓
   Generate signals → optimize → P&L
```

---

## What We're Building

### Component 1: AlphaVantage Data Loader (Standalone Tool)

**File**: `tests/validation/load_alphavantage_improved.py`

**Purpose**: Fetch data from AlphaVantage API and populate SQLite cache

**Usage**:
```bash
# Initial load (outside backtest)
export ALPHAVANTAGE_API_KEY="QLGCJCCK8X4ZY6VC"
python tests/validation/load_alphavantage_improved.py --tickers AAPL MSFT GOOGL

# Update existing cache
python tests/validation/load_alphavantage_improved.py --update

# Force refresh
python tests/validation/load_alphavantage_improved.py --force-refresh
```

**Features**:
- Checks cache before fetching
- Respects rate limits (5/min, 25/day)
- Incrementalupdate (fetch only missing dates)
- Progress reporting
- Error handling and retry logic

**NOT used during backtest**

---

### Component 2: CachedMarketDataProvider (MDP Interface)

**File**: `MDP/CachedMarketDataProvider.py`

**Purpose**: Unified MDP interface for reading cached data

**Usage**:
```python
from MDP.CachedMarketDataProvider import CachedMarketDataProvider
from Data.Cache.SQLiteCache import SQLiteCache

# Setup (once)
cache = SQLiteCache("market_data.db")
mdp = CachedMarketDataProvider(cache)

# Use in adapter/backtest
prices = mdp.get_prices(
    tickers=['AAPL', 'MSFT'],
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    adjusted=True
)

# Returns Polars DataFrame:
# [ticker, date, open, high, low, close, volume]
```

**Features**:
- Read-only (never fetches from API)
- Standard MDP interface
- Graceful handling of missing data
- Compatible with existing adapters

---

### Component 3: Example Workflows

**File**: `examples/workflow_alphavantage_data.py`

**Shows**:
1. How to run data loader (separate step)
2. How to check cache coverage
3. How to run backtest with cached data
4. How to handle missing data

---

## Implementation Tasks (Truly Orthogonal)

### Task 1: Improve AlphaVantage Data Loader

**File**: `tests/validation/load_alphavantage_improved.py`
**Time**: 15 minutes
**Dependencies**: None (standalone script)

**Features**:
- CLI arguments (--tickers, --update, --force-refresh)
- Smart caching (check before fetch)
- Rate limiting (5/min, 25/day) using RateLimiter
- Incremental updates (fetch only missing dates)
- Progress bar
- Error handling

**Success**:
- Can load AAPL, MSFT, GOOGL (3 tickers × 2268 days)
- Writes to market_data.db using SQLiteCache
- Respects rate limits
- Second run uses cache (no API calls)

---

### Task 2: Create CachedMarketDataProvider

**File**: `MDP/CachedMarketDataProvider.py`
**Time**: 15 minutes
**Dependencies**: SQLiteCache (already exists)

**Interface**:
```python
class CachedMarketDataProvider:
    """MDP interface for cached market data."""

    def __init__(self, cache: SQLiteCache):
        self.cache = cache

    def get_prices(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        adjusted: bool = True
    ) -> pl.DataFrame:
        """Get prices from cache."""
        # Read from cache
        # Return standard format
        # Handle missing data gracefully

    def get_equity_data(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        include_fundamentals: bool = False,
        include_sectors: bool = False
    ) -> pl.DataFrame:
        """Alternative interface for compatibility."""
```

**Success**:
- Implements standard MDP interface
- Read-only (no API calls)
- Returns data in expected format
- Handles missing data gracefully

---

### Task 3: Create Tests

**File**: `tests/unit/mdp/test_cached_mdp.py`
**Time**: 10 minutes
**Dependencies**: CachedMarketDataProvider

**Tests**:
- Test get_prices() returns cached data
- Test missing ticker returns empty DataFrame
- Test date range filtering
- Test adjusted vs unadjusted prices
- Test multiple tickers
- No API calls (all from cache)

---

### Task 4: Create Workflow Example

**File**: `examples/workflow_alphavantage_data.py`
**Time**: 10 minutes
**Dependencies**: None (documentation)

**Shows**:
```python
"""
Step 1: Load data (run ONCE, outside backtest)
"""
# python tests/validation/load_alphavantage_improved.py --tickers AAPL MSFT GOOGL

"""
Step 2: Check cache coverage
"""
cache = SQLiteCache("market_data.db")
coverage = cache.get_cache_coverage(symbol_id, 'equity_prices')
print(f"Cached: {coverage['earliest_date']} to {coverage['latest_date']}")

"""
Step 3: Run backtest (uses cached data, NO API calls)
"""
mdp = CachedMarketDataProvider(cache)
adapter = EquityAdapter(mdp)
backtest = Backtest(
    mdp=mdp,
    adapter=adapter,
    signals=MomentumSignal()
)
result = backtest.run(...)
```

---

### Task 5: Update Documentation

**File**: `docs/DATA_LAYER_ARCHITECTURE.md` (already created)
**Time**: 5 minutes

**Content**:
- Architecture overview
- Data flow diagram
- Rules (what NOT to do)
- How to add new sources (Bloomberg, CME, Eris)

---

### Task 6: Create RateLimiter Utility

**File**: `Data/Utils/RateLimiter.py`
**Time**: 10 minutes
**Dependencies**: None

**Interface**:
```python
class RateLimiter:
    """Sliding window rate limiter."""

    def __init__(
        self,
        max_per_minute: int = 5,
        max_per_day: int = 25
    ):
        self.requests = []  # timestamps

    def acquire(self):
        """Block until request is allowed."""

    def can_make_request(self) -> bool:
        """Check if request allowed now."""

    def wait_time(self) -> float:
        """Seconds to wait."""
```

---

## Execution Strategy

### Phase 1: Core Components (Parallel)

```
Task 1 → AlphaVantage data loader (15 min)
Task 2 → CachedMarketDataProvider (15 min)
Task 6 → RateLimiter utility (10 min)

Can run in parallel (different files, no dependencies)
```

### Phase 2: Integration (Sequential)

```
Task 3 → Tests for CachedMDP (10 min) [after Task 2]
Task 4 → Workflow example (10 min) [after Task 1, 2]
Task 5 → Update docs (5 min) [anytime]
```

---

## Success Criteria

### Functional:
- [ ] Data loader can fetch from AlphaVantage and populate cache
- [ ] CachedMDP can read from cache and return standard format
- [ ] EquityAdapter works with CachedMDP
- [ ] Backtest runs using cached data (NO API calls during backtest)
- [ ] Rate limiting prevents API exhaustion

### Performance:
- [ ] First run: Fetches from API (~2 min for 3 tickers with rate limits)
- [ ] Second run: Uses cache (instant, NO API calls)
- [ ] Cache read: <10ms per query

### Architecture:
- [ ] Backtest NEVER calls API directly
- [ ] Data loading is separate step
- [ ] Can add Bloomberg/CME without changing backtest

---

## Timeline

**Phase 1 (Parallel)**: 15 minutes (longest task)
**Phase 2 (Sequential)**: 25 minutes
**Testing & Validation**: 10 minutes

**Total**: ~50 minutes

---

## Files Created/Modified

**New Files**:
- `tests/validation/load_alphavantage_improved.py`
- `MDP/CachedMarketDataProvider.py`
- `Data/Utils/RateLimiter.py`
- `tests/unit/mdp/test_cached_mdp.py`
- `examples/workflow_alphavantage_data.py`
- `docs/DATA_LAYER_ARCHITECTURE.md` (already created)

**Modified Files**:
- None (existing adapters already compatible)

---

## Future Extensions

### Add Bloomberg:
1. Create `tests/validation/load_bloomberg.py`
2. Use same SQLiteCache
3. No changes to MDP, Adapter, or Backtest

### Add CME:
1. Create `tests/validation/load_cme.py`
2. Use same SQLiteCache
3. No changes needed elsewhere

### Add Eris:
1. Create `tests/validation/load_eris.py`
2. Use same SQLiteCache
3. No changes needed elsewhere

---

## Key Differences from Original Plan

### ❌ OLD (Incorrect):
- DataProvider used BY backtest
- Backtest calls API indirectly through DataProvider
- Mixing data loading with backtest execution

### ✅ NEW (Correct):
- Data loader is standalone script
- Backtest uses MDP which reads cache only
- Clear separation: load data → run backtest

---

## Next Steps

1. ✅ SQLiteCache implemented (Task 1 from previous plan)
2. → Implement RateLimiter utility (Task 6)
3. → Implement AlphaVantage data loader (Task 1)
4. → Implement CachedMarketDataProvider (Task 2)
5. → Create tests (Task 3)
6. → Create examples (Task 4)
7. → Validate end-to-end
