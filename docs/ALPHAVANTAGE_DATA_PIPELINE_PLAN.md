# AlphaVantage Data Pipeline Implementation Plan

## Status: READY FOR PARALLEL EXECUTION
Created: 2025-11-13
API Key: QLGCJCCK8X4ZY6VC
Branch: Will create `claude/alphavantage-data-pipeline-[SESSION_ID]`

## Executive Summary

Current state: Generic Backtest complete, but using mock data.
Goal: Integrate real market data from AlphaVantage with local SQLite caching.

**Core Principle**: Never hit AlphaVantage unnecessarily
- First check: SQLite cache (fast, local)
- If missing or stale: Fetch from AlphaVantage (rate-limited)
- Always update cache after fetch

**Architecture**:
```
User Request → DataProvider → SQLite Cache (check)
                            ↓
                     (if miss or stale)
                            ↓
                 AlphaVantage API (rate-limited)
                            ↓
                  Update SQLite Cache
                            ↓
                    Return Data
```

---

## AlphaVantage API Capabilities

**What AlphaVantage Provides** (with API key: QLGCJCCK8X4ZY6VC):
1. **Equities**: Daily/intraday prices, adjusted for splits/dividends
2. **Forex**: Currency pairs, real-time and historical
3. **Crypto**: Digital currencies
4. **Technical Indicators**: SMA, EMA, RSI, MACD, etc.
5. **Fundamental Data**: Balance sheets, earnings, cash flow

**Rate Limits**:
- Free tier: 25 requests/day (strict limit)
- 5 API requests per minute (rate limiting needed)

**Strategy**: Aggressive caching, batch fetching, respectful rate limiting

---

## SQLite Schema Design

### Database: `market_data.db`

**Table: `equity_prices`**
```sql
CREATE TABLE equity_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume INTEGER,
    dividend_amount REAL,
    split_coefficient REAL,
    source TEXT DEFAULT 'alphavantage',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);

CREATE INDEX idx_equity_prices_symbol_date ON equity_prices(symbol, date);
CREATE INDEX idx_equity_prices_fetched ON equity_prices(fetched_at);
```

**Table: `forex_rates`**
```sql
CREATE TABLE forex_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency TEXT NOT NULL,
    to_currency TEXT NOT NULL,
    date DATE NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    source TEXT DEFAULT 'alphavantage',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_currency, to_currency, date)
);

CREATE INDEX idx_forex_rates_pair_date ON forex_rates(from_currency, to_currency, date);
```

**Table: `futures_prices`**
```sql
CREATE TABLE futures_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract TEXT NOT NULL,
    date DATE NOT NULL,
    price REAL,
    settlement_price REAL,
    volume INTEGER,
    open_interest INTEGER,
    source TEXT DEFAULT 'manual',  -- May need different source
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract, date)
);

CREATE INDEX idx_futures_prices_contract_date ON futures_prices(contract, date);
```

**Table: `api_requests`** (rate limiting tracking)
```sql
CREATE TABLE api_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    symbol TEXT,
    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_code INTEGER,
    cache_hit BOOLEAN DEFAULT 0,
    error_message TEXT
);

CREATE INDEX idx_api_requests_time ON api_requests(request_time);
```

**Table: `cache_metadata`**
```sql
CREATE TABLE cache_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    earliest_date DATE,
    latest_date DATE,
    record_count INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, symbol)
);
```

---

## Task Decomposition (5 Orthogonal Streams)

### Stream 1: SQLite Cache Infrastructure
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: Database schema, connection management, basic CRUD

**Tasks**:

**1.1: Create Database Module** (`Data/Cache/SQLiteCache.py`)
```python
class SQLiteCache:
    """SQLite-based cache for market data."""

    def __init__(self, db_path: str = "market_data.db"):
        self.db_path = db_path
        self.conn = None

    def initialize_schema(self):
        """Create all tables and indexes."""

    def get_equity_prices(self, symbol: str, start_date: date, end_date: date):
        """Fetch equity prices from cache."""

    def store_equity_prices(self, symbol: str, data: pl.DataFrame):
        """Store equity prices in cache."""

    def get_cache_coverage(self, table: str, symbol: str):
        """Check what date range is cached."""

    def is_stale(self, symbol: str, max_age_days: int = 1):
        """Check if cached data needs refresh."""
```

**1.2: Create Schema Migration Script** (`Data/Cache/migrations/001_initial_schema.sql`)
- SQL file with all CREATE TABLE statements
- Version tracking for future migrations
- Idempotent (can run multiple times safely)

**1.3: Create Cache Tests** (`tests/unit/data/test_sqlite_cache.py`)
- Test table creation
- Test CRUD operations (create, read, update)
- Test uniqueness constraints
- Test index performance
- Test cache coverage checks

**Files touched**:
- `Data/Cache/SQLiteCache.py` (new)
- `Data/Cache/__init__.py` (new)
- `Data/Cache/migrations/001_initial_schema.sql` (new)
- `tests/unit/data/test_sqlite_cache.py` (new)
- `market_data.db` (created during tests, gitignored)

**Success criteria**:
- All tables created successfully
- CRUD operations work correctly
- Tests pass (15+ tests)
- No SQL injection vulnerabilities

**Orthogonality**: Only touches `Data/Cache/` and related tests

---

### Stream 2: AlphaVantage API Client
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: HTTP client, rate limiting, error handling

**Tasks**:

**2.1: Create AlphaVantage Client** (`Data/Providers/AlphaVantageClient.py`)
```python
class AlphaVantageClient:
    """Client for AlphaVantage API with rate limiting."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(
            max_requests_per_minute=5,
            max_requests_per_day=25
        )

    def get_daily_adjusted(self, symbol: str, outputsize: str = "full"):
        """Fetch daily adjusted prices (with splits/dividends)."""

    def get_intraday(self, symbol: str, interval: str = "5min"):
        """Fetch intraday prices."""

    def get_forex_daily(self, from_currency: str, to_currency: str):
        """Fetch forex daily rates."""

    def _make_request(self, params: dict):
        """Make rate-limited API request."""

    def _check_rate_limit(self):
        """Check if we can make request without exceeding limits."""
```

**2.2: Create Rate Limiter** (`Data/Providers/RateLimiter.py`)
```python
class RateLimiter:
    """Rate limiter using sliding window."""

    def __init__(self, max_requests_per_minute: int, max_requests_per_day: int):
        self.requests_log = []  # timestamps of requests

    def acquire(self):
        """Block until we can make a request."""

    def can_make_request(self) -> bool:
        """Check if we can make request now."""

    def wait_time(self) -> float:
        """How long to wait before next request."""
```

**2.3: Create API Tests** (`tests/unit/data/test_alphavantage_client.py`)
- Mock API responses
- Test rate limiting (should block appropriately)
- Test error handling (bad symbol, API errors)
- Test response parsing
- Integration test with real API (marked @pytest.mark.integration)

**Files touched**:
- `Data/Providers/AlphaVantageClient.py` (new)
- `Data/Providers/RateLimiter.py` (new)
- `Data/Providers/__init__.py` (new)
- `tests/unit/data/test_alphavantage_client.py` (new)
- `tests/integration/test_alphavantage_live.py` (new, uses real API)

**Success criteria**:
- Rate limiting works (5/min, 25/day enforced)
- API responses parsed correctly
- Error handling is robust
- Integration test with real API passes

**Orthogonality**: Only touches `Data/Providers/` and related tests

---

### Stream 3: Unified Data Provider
**Agent**: `general-purpose`
**Complexity**: High (60-90 min)
**Why this agent**: Integration logic, caching strategy, fallback handling

**Tasks**:

**3.1: Create Data Provider** (`Data/DataProvider.py`)
```python
class DataProvider:
    """Unified interface for market data with caching."""

    def __init__(
        self,
        cache: SQLiteCache,
        alphavantage: AlphaVantageClient,
        cache_staleness_days: int = 1
    ):
        self.cache = cache
        self.alphavantage = alphavantage
        self.staleness = cache_staleness_days

    def get_equity_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        force_refresh: bool = False
    ) -> pl.DataFrame:
        """
        Get equity prices with cache-first strategy.

        Algorithm:
        1. Check cache coverage
        2. If full coverage and not stale: return from cache
        3. If partial coverage: fetch missing dates from API
        4. If no coverage or stale: fetch all from API
        5. Update cache
        6. Return data
        """

    def get_forex_rates(self, from_currency: str, to_currency: str, ...):
        """Get forex rates with caching."""

    def get_futures_prices(self, contract: str, ...):
        """Get futures prices (may use different source)."""

    def _fetch_and_cache_equity(self, symbol: str):
        """Fetch from API and update cache."""

    def _merge_cache_and_api(self, cached_data, api_data):
        """Merge cached and newly fetched data."""
```

**3.2: Create Caching Strategy Tests** (`tests/unit/data/test_data_provider.py`)
- Test cache hit (no API call)
- Test cache miss (API call + cache update)
- Test partial cache (API call for missing dates only)
- Test stale cache (force refresh)
- Test rate limit handling (should wait)

**3.3: Create Integration Tests** (`tests/integration/test_data_provider_live.py`)
- Test with real AlphaVantage API
- Verify caching works end-to-end
- Test multiple requests (should hit cache second time)
- Verify rate limiting in practice

**Files touched**:
- `Data/DataProvider.py` (new)
- `Data/__init__.py` (new)
- `tests/unit/data/test_data_provider.py` (new)
- `tests/integration/test_data_provider_live.py` (new)

**Success criteria**:
- Cache-first strategy works correctly
- API is only called when necessary
- Rate limiting prevents API exhaustion
- Partial cache updates work
- Integration tests pass with real API

**Orthogonality**: Only touches `Data/DataProvider.py` and related tests

---

### Stream 4: Adapter Integration
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: Integration with existing adapters, backwards compatibility

**Tasks**:

**4.1: Create Equity Adapter** (`Adapter/EquityAdapter.py`)
```python
class EquityAdapter:
    """Adapter for equity data → Backtest format."""

    def __init__(self, data_provider: DataProvider):
        self.data_provider = data_provider

    def convert(
        self,
        symbols: List[str],
        as_of: date,
        lookback_days: int = 252
    ) -> pl.DataFrame:
        """
        Convert equity data to standardized format.

        Returns:
            DataFrame with columns: [date, ticker, price, return, volume]
        """

    def get_returns(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """
        Get returns matrix for Backtest.run_from_dataframe().

        Returns:
            DataFrame with columns: [date, ticker, return]
        """
```

**4.2: Update FuturesAdapter** (`Adapter/FuturesAdapter.py`)
- Add optional data_provider parameter
- If provided, use real data instead of mock
- Maintain backwards compatibility (mock still works)

**4.3: Create Adapter Tests** (`tests/unit/adapter/test_equity_adapter.py`)
- Test conversion to standard format
- Test returns calculation
- Test with cached data (fast)
- Test with API data (slower, rate-limited)

**Files touched**:
- `Adapter/EquityAdapter.py` (new)
- `Adapter/FuturesAdapter.py` (modify, add optional data_provider)
- `Adapter/__init__.py` (update exports)
- `tests/unit/adapter/test_equity_adapter.py` (new)

**Success criteria**:
- EquityAdapter works with DataProvider
- Returns correct format for Backtest.run_from_dataframe()
- FuturesAdapter backwards compatible
- Tests pass

**Orthogonality**: Only touches `Adapter/` and related tests

---

### Stream 5: Examples & Documentation
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: End-to-end examples, user-facing documentation

**Tasks**:

**5.1: Create Example with Real Data** (`examples/run_backtest_with_real_data.py`)
```python
"""
Example: Run backtest with real AlphaVantage data.

Demonstrates:
1. Setting up DataProvider with SQLite cache
2. Fetching real equity data
3. Running backtest with cached data
4. Rate limiting in action
"""

from datetime import date
from Data.DataProvider import DataProvider
from Data.Cache.SQLiteCache import SQLiteCache
from Data.Providers.AlphaVantageClient import AlphaVantageClient
from Backtest.Backtest import Backtest
from Signals.Futures.MomentumSignal import MomentumSignal

# Setup
cache = SQLiteCache("market_data.db")
alphavantage = AlphaVantageClient(api_key="QLGCJCCK8X4ZY6VC")
data_provider = DataProvider(cache, alphavantage)

# Get real data (uses cache if available)
symbols = ['AAPL', 'MSFT', 'GOOGL']
start_date = date(2024, 1, 1)
end_date = date(2024, 12, 31)

# This may take time on first run (API calls)
# Subsequent runs will be fast (cache hit)
returns_df = data_provider.get_equity_returns(symbols, start_date, end_date)

# Run backtest
backtest = Backtest(signals=MomentumSignal(lookback_days=20))
result = backtest.run_from_dataframe(returns_df, dates=[...])

print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Total Return: {result.total_return:.2%}")
```

**5.2: Create Setup Guide** (`docs/DATA_PIPELINE_SETUP.md`)
- How to get AlphaVantage API key
- Setting up SQLite database
- First-time data fetch
- Cache management
- Rate limit best practices

**5.3: Create Data Provider Guide** (`docs/DATA_PROVIDER_API.md`)
- Complete API reference
- Caching strategy explanation
- Examples for different use cases
- Troubleshooting guide

**Files touched**:
- `examples/run_backtest_with_real_data.py` (new)
- `docs/DATA_PIPELINE_SETUP.md` (new)
- `docs/DATA_PROVIDER_API.md` (new)
- `README.md` (update with data setup instructions)

**Success criteria**:
- Example runs successfully
- Documentation is complete and clear
- Setup instructions are step-by-step
- Troubleshooting covers common issues

**Orthogonality**: Only touches `examples/` and `docs/`

---

## Execution Strategy

### Phase 1: Launch Parallel Streams (5 agents)
```bash
# All agents can start simultaneously

Agent 1 → Stream 1: SQLite Cache Infrastructure
Agent 2 → Stream 2: AlphaVantage API Client
Agent 3 → Stream 3: Unified Data Provider (depends on 1 & 2 being done)
Agent 4 → Stream 4: Adapter Integration (depends on 3 being done)
Agent 5 → Stream 5: Examples & Documentation (can start early)
```

**Note**: Streams 3 and 4 have dependencies, but 1, 2, 5 are fully independent.

### Phase 2: Integration Testing
After all streams complete:
1. Run full test suite (unit + integration)
2. Test example with real API (first run will fetch, second run will cache)
3. Verify rate limiting works
4. Check cache performance

### Phase 3: Real-World Validation
1. Fetch data for 10 symbols (should take ~2 min with rate limiting)
2. Run backtest with real data
3. Cache second backtest run (should be instant)
4. Verify results are reasonable

---

## Rate Limiting Strategy

**Problem**: AlphaVantage free tier allows 25 requests/day, 5/minute

**Solutions**:

**1. Aggressive Caching**
- Cache full history on first fetch
- Never re-fetch unless explicitly requested
- Default staleness: 1 day (configurable)

**2. Batch Fetching**
- When fetching multiple symbols, batch requests
- Wait between requests (12 seconds minimum for 5/min limit)
- Track daily quota in database

**3. Smart Updates**
- Only fetch new data (dates after latest cached)
- Use "compact" mode when possible (last 100 days)
- Use "full" mode only on first fetch

**4. Fallback Mechanisms**
- If rate limit hit: return cached data with warning
- If cache miss + rate limit: raise informative error
- Option to use CSV upload for manual data

---

## Database Migration Strategy

**Current**: No database
**Target**: SQLite with versioned schema

**Approach**:
1. Create `Data/Cache/migrations/` directory
2. Each migration is numbered: `001_initial_schema.sql`, `002_add_indexes.sql`
3. Track applied migrations in `schema_migrations` table
4. Migration runner checks and applies missing migrations
5. Idempotent: can run multiple times safely

**Example Migration Runner**:
```python
class MigrationRunner:
    def apply_migrations(self, db_path: str, migrations_dir: str):
        # Check schema_migrations table
        # Find unapplied migrations
        # Apply in order
        # Record in schema_migrations
```

---

## Error Handling Strategy

**API Errors**:
- Rate limit exceeded: Wait and retry, or return cached
- Invalid symbol: Log error, skip symbol
- Network error: Retry 3 times with backoff, then fail
- API key invalid: Fail fast with clear message

**Cache Errors**:
- Database locked: Retry with backoff
- Corrupt data: Invalidate and re-fetch
- Schema mismatch: Run migrations

**Data Quality Errors**:
- Missing dates: Fill with NaN or forward-fill
- Outliers: Log warning but don't filter
- Splits/dividends: Use adjusted_close from AlphaVantage

---

## Testing Strategy

**Unit Tests** (fast, no external dependencies):
- SQLiteCache CRUD operations
- RateLimiter logic
- Data parsing/formatting
- Adapter conversions

**Integration Tests** (slower, uses real API):
- Mark with `@pytest.mark.integration`
- Use real API key from environment variable
- Limit to 1-2 symbols to respect rate limits
- Run in CI on schedule (not every commit)

**Performance Tests**:
- Benchmark cache retrieval (should be <10ms)
- Benchmark API fetch (12+ seconds due to rate limiting)
- Test with 100+ symbols in cache

**Golden Tests**:
- Save known-good data snapshots
- Verify parsing doesn't drift
- Ensure backwards compatibility

---

## Configuration Management

**Environment Variables** (create `.env.example`):
```bash
# AlphaVantage API Key
ALPHAVANTAGE_API_KEY=QLGCJCCK8X4ZY6VC

# Database path (default: market_data.db)
MARKET_DATA_DB_PATH=market_data.db

# Cache staleness (days)
CACHE_STALENESS_DAYS=1

# Rate limits
ALPHAVANTAGE_MAX_PER_MINUTE=5
ALPHAVANTAGE_MAX_PER_DAY=25
```

**Config File** (`Data/config.py`):
```python
import os
from dataclasses import dataclass

@dataclass
class DataConfig:
    alphavantage_api_key: str
    db_path: str = "market_data.db"
    cache_staleness_days: int = 1
    max_requests_per_minute: int = 5
    max_requests_per_day: int = 25

    @classmethod
    def from_env(cls):
        return cls(
            alphavantage_api_key=os.getenv("ALPHAVANTAGE_API_KEY", "QLGCJCCK8X4ZY6VC"),
            db_path=os.getenv("MARKET_DATA_DB_PATH", "market_data.db"),
        )
```

---

## Git Ignore Updates

Add to `.gitignore`:
```
# Market data cache
market_data.db
market_data.db-journal
*.db
*.db-journal

# Environment variables
.env

# Downloaded data
data/raw/
data/cache/
```

---

## Success Metrics

**Functionality**:
- All data provider tests pass (unit + integration)
- Real API integration works
- Caching reduces API calls by >95%
- Rate limiting prevents API exhaustion

**Performance**:
- Cache retrieval: <10ms
- First API fetch: 12-15 seconds (rate limited)
- Subsequent cache hits: <50ms
- 100 symbols in cache: <100ms query

**Quality**:
- Data accuracy verified against AlphaVantage website
- No data loss in cache
- Proper handling of splits/dividends
- Edge cases handled (missing data, weekends, holidays)

**Documentation**:
- Setup guide is clear and complete
- API reference is accurate
- Examples run successfully
- Troubleshooting covers common issues

---

## Timeline Estimate

**Parallel Execution** (Streams 1, 2, 5 can run simultaneously):
- Stream 1 (Cache): 45-60 min
- Stream 2 (API Client): 45-60 min
- Stream 5 (Examples/Docs): 45-60 min

**Sequential Execution** (Streams 3, 4 depend on 1, 2):
- Stream 3 (Data Provider): 60-90 min (after 1, 2)
- Stream 4 (Adapters): 45-60 min (after 3)

**Integration & Testing**: 45-60 min
**Real-world Validation**: 30 min

**Total**: ~4-5 hours with partial parallelization
(vs ~6-7 hours fully sequential)

---

## Risks & Mitigation

**Risk**: Rate limit exhaustion during testing
- **Mitigation**: Mock API responses in unit tests
- **Mitigation**: Limit integration tests to 1-2 symbols
- **Mitigation**: Use separate API key for development/testing

**Risk**: SQLite database corruption
- **Mitigation**: Regular backups
- **Mitigation**: Transaction-based writes
- **Mitigation**: WAL mode for concurrency

**Risk**: AlphaVantage API changes
- **Mitigation**: Version API client
- **Mitigation**: Comprehensive error handling
- **Mitigation**: Fallback to cached data

**Risk**: Clock drift causing stale data
- **Mitigation**: Compare dates, not timestamps
- **Mitigation**: Configurable staleness threshold
- **Mitigation**: Force refresh option

---

## Future Enhancements (Post-MVP)

**After initial implementation**:
1. **Additional Data Sources**:
   - Quandl integration
   - Yahoo Finance fallback
   - Manual CSV upload

2. **Advanced Caching**:
   - Compression for older data
   - Archival to cheaper storage
   - Cache warming strategies

3. **Data Quality**:
   - Outlier detection
   - Missing data interpolation
   - Cross-validation between sources

4. **Performance**:
   - Async API calls (concurrent fetching)
   - Read replicas for query performance
   - In-memory cache layer (Redis)

5. **Monitoring**:
   - API usage dashboard
   - Cache hit rate metrics
   - Data freshness tracking

---

## Next Steps

1. **Merge current branch** (generic Backtest foundation)
2. **Create new branch**: `claude/alphavantage-data-pipeline-[SESSION_ID]`
3. **Set API key in environment**: `export ALPHAVANTAGE_API_KEY=QLGCJCCK8X4ZY6VC`
4. **Launch parallel streams**: Start agents 1, 2, 5 simultaneously
5. **Sequential completion**: Agent 3 after 1&2, Agent 4 after 3
6. **Integration testing**: Verify with real API
7. **Create PR**: Comprehensive data pipeline

---

## Notes

- AlphaVantage free tier is limited (25 requests/day)
- Aggressive caching is essential
- SQLite is sufficient for single-user workloads
- Can scale to PostgreSQL later if needed
- Rate limiting must be strictly enforced
- This enables real backtesting with real data
