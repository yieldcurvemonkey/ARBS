# Data Layer Architecture

## Core Principle: Separation of Concerns

**THE BACKTESTER IS NOT A DATA LOADER**

Data loading happens OUTSIDE the backtest in separate tools. The backtest REQUEST data from a Market Data Provider (MDP) which returns PRE-LOADED cached data.

---

## Layer Responsibilities

### 1. Data Loaders (Standalone Tools)

**Location**: `tests/validation/load_*.py`

**Purpose**: Fetch data from external sources and populate cache

**Responsibilities**:
- Fetch from APIs (AlphaVantage, Bloomberg, CME, Eris, Quandl)
- Handle rate limiting
- Parse responses
- Write to SQLite cache
- Run OUTSIDE the backtest (separate process/script)

**Examples**:
```python
# tests/validation/load_alphavantage.py
# Fetches from AlphaVantage API → writes to market_data.db

# tests/validation/load_bloomberg.py (future)
# Fetches from Bloomberg → writes to market_data.db

# tests/validation/load_cme.py (future)
# Fetches from CME → writes to market_data.db
```

**Key Point**: These are CLI scripts, NOT imported by backtest code

---

### 2. SQLite Cache (Storage Layer)

**Location**: `Data/Cache/SQLiteCache.py`

**Purpose**: Persistent storage for market data

**Responsibilities**:
- Store prices (equity, futures, forex)
- Track cache coverage (date ranges)
- Handle CRUD operations
- NO external API calls
- NO data fetching logic

**Interface**:
```python
cache = SQLiteCache("market_data.db")

# Store (called by data loaders)
cache.store_equity_prices(symbol_id, prices_df)

# Retrieve (called by MDP)
prices = cache.get_equity_prices(symbol_id, start_date, end_date)

# Coverage
coverage = cache.get_cache_coverage(symbol_id, 'equity_prices')
```

---

### 3. Market Data Provider (MDP)

**Location**: `MDP/CachedMarketDataProvider.py` (to be created)

**Purpose**: Unified interface for reading cached data

**Responsibilities**:
- Read from SQLite cache
- Return data in MDP standard format
- Handle missing data gracefully
- NO external API calls
- NO data fetching

**Interface**:
```python
mdp = CachedMarketDataProvider(cache)

# Standard MDP interface
prices_df = mdp.get_prices(
    tickers=['AAPL', 'MSFT'],
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    adjusted=True
)

# Returns DataFrame with standard columns
# If data missing: returns empty DataFrame or NaN
```

**Key Point**: MDP is READ-ONLY. It never writes or fetches.

---

### 4. Adapters (Format Conversion)

**Location**: `Adapter/FuturesAdapter.py`, `Adapter/EquityAdapter.py`

**Purpose**: Convert MDP output → signal-ready format

**Responsibilities**:
- Take MDP as dependency
- Call `mdp.get_prices()` to get cached data
- Convert to signal-ready DataFrame
- Add metadata (sector, weight, roll dates)
- NO external API calls
- NO data fetching

**Interface**:
```python
adapter = EquityAdapter(mdp)

# Adapter calls mdp.get_prices() internally
df = adapter.convert(queries, as_of_date)

# Returns signal-ready format:
# [ticker, date, close, return, sector, weight]
```

---

### 5. Backtest (Strategy Execution)

**Location**: `Backtest/Backtest.py`

**Purpose**: Run strategy, generate trades, measure performance

**Responsibilities**:
- Take adapter as dependency
- Call `adapter.convert()` to get data
- Generate signals
- Optimize portfolio
- Track P&L
- NO data loading
- NO external API calls

**Interface**:
```python
backtest = Backtest(
    mdp=mdp,
    adapter=EquityAdapter(mdp),
    signals=MomentumSignal()
)

# Backtest calls adapter.convert() which calls mdp.get_prices()
result = backtest.run(contracts=[...], dates=[...])

# Or with pre-loaded DataFrame (bypass adapter)
result = backtest.run_from_dataframe(returns_df, dates=[...])
```

---

## Data Flow

### Full Pipeline (with data loading)

```
1. Data Loader (external script)
   ↓
   Fetch from API (AlphaVantage, Bloomberg, CME)
   ↓
2. SQLite Cache
   ↓
   Store prices, coverage, metadata

---[BACKTEST STARTS HERE]---

3. Market Data Provider (MDP)
   ↓
   Read from cache (no API calls)
   ↓
4. Adapter
   ↓
   Convert to signal format
   ↓
5. Backtest
   ↓
   Generate signals → optimize → P&L
```

### Backtest-Only Pipeline (data already loaded)

```
[Data already in SQLite cache]
   ↓
1. Market Data Provider (MDP)
   ↓
   Read from cache
   ↓
2. Adapter
   ↓
   Convert to signal format
   ↓
3. Backtest
   ↓
   Generate signals → optimize → P&L
```

---

## Adding New Data Sources

### To add Bloomberg:

1. **Create data loader**: `tests/validation/load_bloomberg.py`
   - Fetches from Bloomberg API
   - Uses SQLiteCache to store
   - Handles Bloomberg-specific parsing

2. **No changes to MDP**: Already reads from cache

3. **No changes to Adapter**: Already uses MDP interface

4. **No changes to Backtest**: Already uses Adapter interface

### To add CME:

1. **Create data loader**: `tests/validation/load_cme.py`
   - Fetches from CME
   - Uses SQLiteCache to store

2. **Everything else unchanged**

---

## Key Rules

### ✅ CORRECT

- Data loader fetches from API → writes to cache
- MDP reads from cache → returns data
- Adapter converts MDP data → signal format
- Backtest uses adapter → generates trades

### ❌ INCORRECT

- Backtest calls API directly
- Backtest loads from cache directly
- Adapter fetches from API
- MDP fetches from API
- Data loader used during backtest execution

---

## Workflows

### Workflow 1: Initial Data Load

```bash
# Step 1: Run data loader (OUTSIDE backtest)
python tests/validation/load_alphavantage.py

# This populates market_data.db with prices

# Step 2: Run backtest (uses cached data)
python examples/run_backtest_with_cached_data.py
```

### Workflow 2: Update Cache

```bash
# Update cache with new data
python tests/validation/load_alphavantage.py --update

# Backtest automatically picks up new data
python examples/run_backtest_with_cached_data.py
```

### Workflow 3: Multiple Sources

```bash
# Load from multiple sources
python tests/validation/load_alphavantage.py  # Equities
python tests/validation/load_cme.py           # Futures
python tests/validation/load_bloomberg.py     # Bonds

# All stored in same market_data.db

# Backtest uses unified MDP interface
python examples/run_multi_asset_backtest.py
```

---

## Benefits

1. **Separation**: Backtest never touches external APIs
2. **Speed**: Backtest reads from fast local cache
3. **Testability**: Mock MDP, not external APIs
4. **Flexibility**: Add new sources without changing backtest
5. **Rate Limiting**: Data loaders handle rate limits, backtest doesn't care
6. **Offline**: Run backtests without internet connection

---

## Implementation Status

**Complete**:
- ✅ SQLite Cache infrastructure
- ✅ FuturesAdapter (uses MDP interface)
- ✅ EquityAdapter (uses MDP interface)
- ✅ Backtest (uses Adapter interface)
- ✅ AlphaVantage data loader (`load_alphavantage.py`)

**To Do**:
- ❌ CachedMarketDataProvider (wrap SQLiteCache with MDP interface)
- ❌ Update examples to show proper workflow
- ❌ Bloomberg data loader
- ❌ CME data loader
- ❌ Eris data loader

---

## Next Steps

1. Create `CachedMarketDataProvider` class
   - Wraps SQLiteCache
   - Implements standard MDP interface
   - Read-only

2. Update EquityAdapter to use CachedMarketDataProvider

3. Create examples showing:
   - How to run data loaders
   - How to run backtests with cached data

4. Document in README:
   - Step 1: Load data (separate script)
   - Step 2: Run backtest (uses cached data)
