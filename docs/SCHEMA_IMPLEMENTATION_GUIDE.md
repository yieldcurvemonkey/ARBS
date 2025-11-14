# SQLite Schema Implementation Guide

## Quick Reference

**Total Deliverables**:
- 1 comprehensive design document (1,200+ lines)
- 1 migration SQL file (500+ lines)
- 1 migrations directory README
- 1 sample queries file (600+ lines with 50+ real-world examples)
- This implementation guide

**Total Tables**: 17
**Total Indexes**: 21
**Total Views**: 2
**Estimated Schema Version**: 1.0

---

## Architecture Overview

### Design Goals
1. **Performance**: Sub-10ms queries for single-stock 1-year history
2. **Simplicity**: SQLite for single-user development (scales to PostgreSQL later)
3. **Auditability**: Full price history audit trail
4. **Cache-Friendly**: Rate limit tracking and staleness management
5. **Data Quality**: Corporate action handling (splits, dividends)
6. **Extensibility**: Easy to add new data sources and signal types

### Core Design Decisions

#### 1. Normalized Structure
```
symbols (1) ──→ (1) symbol_metadata
         ├──→ (N) equity_prices
         ├──→ (N) futures_prices
         ├──→ (N) forex_rates
         ├──→ (N) dividends
         ├──→ (N) splits
         ├──→ (N) corporate_events
         └──→ (N) api_requests
```

**Benefit**: No duplication, efficient updates, referential integrity

#### 2. Multiple Price Tables
- `futures_prices` - Settlement-focused (OHLC, OI, volume)
- `equity_prices` - Adjusted close + unadjusted (splits/dividends)
- `forex_rates` - Currency pairs (OHLC, volume in millions)

**Benefit**: Type-specific columns, optimized for signal calculation

#### 3. Corporate Action Tracking
```
dividends ──┐
splits ─────┼──→ corporate_events → price_adjustment
bonus ──────┘
```

**Benefit**: Proper adjustment_factor for backtesting accuracy

#### 4. Cache Management
- `cache_coverage`: Date ranges per symbol+table
- `cache_metadata`: Summary stats for whole table
- `data_gaps`: Known missing data (weekends, holidays)

**Benefit**: DataProvider knows exactly what to fetch

#### 5. API Rate Limiting
- `api_requests`: Log every API call
- Views for per-minute and per-day aggregation
- Easy to enforce limits before making requests

**Benefit**: Never hit rate limits; know quota usage in real-time

---

## Table Reference

### Master Tables (3)

| Table | Purpose | Key Columns |
|-------|---------|-----------|
| `symbols` | Master instrument list | id, symbol, type, exchange |
| `symbol_metadata` | Extended attributes | ticker, sector, expiry_date, split_ratio |
| `data_sources` | Data source tracking | name, provider, rate_limit_per_minute |

### Price Tables (3)

| Table | Purpose | Unique Key | Key Columns |
|-------|---------|-----------|-------------|
| `futures_prices` | Futures OHLC | (symbol_id, date) | open, high, low, close, settlement_price, volume, oi |
| `equity_prices` | Stock OHLCV + adjust | (symbol_id, date) | open_unadjusted, adjusted_close, adjustment_factor |
| `forex_rates` | Currency pairs | (symbol_id, date) | open, high, low, close, volume |

### Corporate Action Tables (4)

| Table | Purpose | Link | Key Columns |
|-------|---------|------|-------------|
| `dividends` | Cash dividends | symbol_id + ex_date | dividend_amount, payment_date |
| `splits` | Stock splits | symbol_id + effective_date | old_shares, new_shares, split_ratio |
| `bonus_issues` | Bonus shares | symbol_id + effective_date | bonus_ratio |
| `corporate_events` | Unified log | symbol_id + event_date | event_type, details |

### Cache Tables (4)

| Table | Purpose | Usage |
|-------|---------|-------|
| `cache_coverage` | Date ranges cached | Check if refresh needed |
| `cache_metadata` | Summary stats | Overall cache health |
| `data_gaps` | Known missing data | Avoid fetching when data doesn't exist |
| `price_history` | Audit trail | Track all price corrections |

### API Tracking (2)

| Table | Purpose | Key Query |
|-------|---------|-----------|
| `api_requests` | API call log | Rate limiting enforcement |
| `schema_migrations` | Schema versions | Migration tracking |

---

## Common Workflows

### Workflow 1: Initialize Database

```python
from Data.Cache.SQLiteCache import SQLiteCache

# Initialize cache with schema
cache = SQLiteCache('market_data.db')
cache.initialize_schema()

# Check migration status
migrations = cache.get_applied_migrations()
print(f"Applied {len(migrations)} migrations")
```

**SQL**: Runs `001_initial_schema.sql` via migration runner

### Workflow 2: Fetch and Cache Equity Data

```python
from datetime import date
from Data.DataProvider import DataProvider

provider = DataProvider(cache, alphavantage_client)

# Fetch AAPL (checks cache first)
prices = provider.get_equity_prices(
    symbol='AAPL',
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)

# Returns: {date → {price, adjusted_close, volume}}
```

**SQL Query Sequence**:
1. Check `cache_coverage` for AAPL
2. If stale or gap: fetch from API
3. INSERT into `equity_prices`
4. UPDATE `cache_coverage`
5. INSERT into `api_requests` for audit

### Workflow 3: Get Returns Matrix for Backtest

```python
# User provides DataFrame or queries from cache
returns_df = provider.get_equity_returns(
    symbols=['AAPL', 'MSFT', 'GOOGL'],
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)

# Returns: DataFrame with [date, ticker, return]
backtest = Backtest(signals=MomentumSignal())
result = backtest.run_from_dataframe(returns_df, dates=[...])
```

**SQL Query** (from SAMPLE_QUERIES.sql Query 2.2):
```sql
WITH daily_returns AS (
    SELECT
        ep.date, s.ticker, ep.adjusted_close,
        LAG(ep.adjusted_close) OVER (PARTITION BY ep.symbol_id ORDER BY ep.date) as prev_close
    FROM equity_prices ep
    JOIN symbols s ON ep.symbol_id = s.id
    WHERE s.ticker IN (...)
)
SELECT date, ticker,
    ROUND((adjusted_close - prev_close) / prev_close, 6) as daily_return
FROM daily_returns
WHERE prev_close IS NOT NULL
ORDER BY date, ticker;
```

### Workflow 4: Futures Carry Signal

```python
# Get front + back contract prices for carry
carry_signal = CarrySignal()
signals = carry_signal.calculate(
    contracts=['SFRZ4', 'SFRH5'],
    mdp=futures_adapter,  # Uses cache
    as_of=date(2024, 3, 15)
)

# Returns: {SFRZ4 → 50.5, SFRH5 → -30.2}  (annualized carry in bps)
```

**SQL Query** (from SAMPLE_QUERIES.sql Query 1.1):
```sql
SELECT f1.date, s1.symbol as front, f1.close as front_price,
       s2.symbol as back, f2.close as back_price, sm1.expiry_date
FROM futures_prices f1
JOIN futures_prices f2 ON f1.symbol_id = f2.symbol_id AND f1.date = f2.date
WHERE s1.symbol = 'SFRZ4' AND f1.date = date(2024, 3, 15)
```

### Workflow 5: Monitor Cache Freshness

```python
# DataProvider calls this before deciding to fetch
cache_fresh = cache.is_fresh('AAPL', max_age_days=1)

if not cache_fresh:
    # Fetch from API
    new_prices = alphavantage_client.get_daily_adjusted('AAPL')
    cache.store_equity_prices('AAPL', new_prices)
```

**SQL Query** (from SAMPLE_QUERIES.sql Query 5.1):
```sql
SELECT s.symbol, cc.last_fetched,
    ROUND((JULIANDAY('now') - JULIANDAY(cc.last_fetched))) as days_stale
FROM cache_coverage cc
JOIN symbols s ON cc.symbol_id = s.id
WHERE s.symbol = 'AAPL' AND cc.price_table = 'equity_prices'
    AND (JULIANDAY('now') - JULIANDAY(cc.last_fetched)) > 1
```

### Workflow 6: Check API Rate Limits

```python
# Before making API request
remaining = alphavantage_client.get_remaining_quota()

if remaining > 0:
    data = alphavantage_client.get_daily_adjusted('MSFT')
else:
    print(f"Rate limit hit. {remaining} requests left. Reset at EOD.")
```

**SQL Query** (from SAMPLE_QUERIES.sql Query 6.1):
```sql
SELECT COUNT(*) as requests_today, rate_limit_per_day
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE DATE(ar.request_time) = DATE('now')
    AND ar.status = 'success'
GROUP BY ds.id
```

---

## Implementation Phases

### Phase 0: Preparation (2 hours)
- [ ] Read SQLITE_SCHEMA_DESIGN.md (30 min)
- [ ] Review 001_initial_schema.sql (30 min)
- [ ] Understand SAMPLE_QUERIES.sql (60 min)

### Phase 1: Core Infrastructure (4-6 hours)

#### Task 1.1: Create SQLiteCache Module (2-3 hours)
**File**: `Data/Cache/SQLiteCache.py`
**Responsibilities**:
- Connect to/create database
- Run migrations
- Implement basic CRUD methods

**Key Methods**:
```python
class SQLiteCache:
    def __init__(self, db_path: str = "market_data.db")
    def initialize_schema(self)
    def insert_symbol(self, symbol: str, type: str, exchange: str = None)
    def get_symbol_id(self, symbol: str) -> int
    def insert_equity_price(self, symbol_id: int, date: date, **kwargs)
    def get_equity_prices(self, symbol: str, start: date, end: date) -> List[Dict]
    def get_cache_coverage(self, symbol: str, table: str) -> Dict
    def is_stale(self, symbol: str, max_age_days: int = 1) -> bool
```

**Tests** (3-4): Basic CRUD, constraint enforcement, index verification

#### Task 1.2: Create MigrationRunner (1 hour)
**File**: `Data/Cache/MigrationRunner.py`
**Responsibilities**:
- Find unapplied migrations
- Execute migrations in order
- Record in schema_migrations table

**Key Method**:
```python
def apply_migrations(self, db_path: str, migrations_dir: str):
    # 1. Check if schema_migrations exists
    # 2. Get applied versions
    # 3. Find unapplied migrations (sorted)
    # 4. Execute each in transaction
    # 5. Record execution time
```

**Tests** (2-3): Migration ordering, idempotency, rollback tracking

#### Task 1.3: Write Tests (1-2 hours)
**File**: `tests/unit/data/test_sqlite_cache.py`
**Coverage**:
- Table creation
- CRUD operations
- Constraint enforcement
- Migration execution
- Cache coverage logic

**Targets**: 20+ tests, all green

### Phase 2: Data Provider Integration (3-4 hours)

#### Task 2.1: Update DataProvider (2 hours)
**File**: `Data/DataProvider.py` (new or extended)
**Integration Points**:
- Inject SQLiteCache
- Implement cache-first strategy
- Track API requests
- Handle rate limiting

**Key Method**:
```python
def get_equity_prices(self, symbol, start_date, end_date, force_refresh=False):
    # 1. Check cache_coverage
    # 2. If fresh and complete: return from cache
    # 3. If stale or gap: fetch from API + log request
    # 4. Merge cache + API data
    # 5. Update cache + cache_coverage
    # 6. Return data
```

**Tests** (5-8): Cache hit, miss, partial, stale, merge logic

#### Task 2.2: Update Adapter (1 hour)
**File**: `Adapter/EquityAdapter.py` or extend `FuturesAdapter.py`
**Changes**:
- Accept DataProvider as dependency
- Query real data instead of mock
- Maintain backward compatibility

**Tests** (3-4): Backward compat, real data flow, format conversion

### Phase 3: Validation & Documentation (2-3 hours)

#### Task 3.1: Integration Tests (1 hour)
**File**: `tests/integration/test_data_pipeline.py`
**Coverage**:
- Fetch AAPL from AlphaVantage (real API call)
- Store in cache
- Retrieve from cache
- Verify adjustment factors
- Check rate limiting

#### Task 3.2: Sample Queries Testing (30 min)
**File**: `tests/unit/data/test_sample_queries.py`
**Coverage**:
- Each sample query in SAMPLE_QUERIES.sql
- Verify results structure
- Check performance (should be <100ms)

#### Task 3.3: Documentation (1 hour)
**Updates**:
- README with setup instructions
- Docstrings in all new modules
- Migration README (already created)
- Schema design doc (already created)

---

## Query Performance Expectations

### Benchmarks (Single Symbol, 1-Year History)

| Query | Expected Time |
|-------|---------------|
| Get 252 daily prices | <1ms |
| Calculate 60-day momentum | <5ms |
| Get returns matrix (10 stocks) | <10ms |
| Check cache freshness (all symbols) | <50ms |
| Rate limit check (sliding window) | <100ms |

### Index Strategy

**Composite Indexes** (most important):
- `(symbol_id, date)` on each price table - enables efficient time-series queries
- `(source_id, request_time)` on api_requests - enables rate limit window checks

**Single-Column Indexes** (supporting):
- `(date)` on price tables - enables date-range queries
- `(fetched_at)` on price tables - enables staleness checks
- `(last_fetched)` on cache_coverage - enables freshness monitoring

**Partial Indexes** (for large datasets):
- Only index last 1 year of prices
- Only index successful API calls
- Only index non-weekend dates

---

## Error Handling Strategy

### Database Errors

```python
# TIMEOUT (database locked)
while retries < 3:
    try:
        cursor.execute(...)
        break
    except sqlite3.OperationalError as e:
        if 'locked' in str(e):
            time.sleep(0.1 * 2^retry)  # Exponential backoff
            continue
        raise

# CONSTRAINT VIOLATION (duplicate key)
try:
    cursor.execute("INSERT INTO equity_prices (...)")
except sqlite3.IntegrityError:
    # Ignore if duplicate - price already cached
    pass

# SCHEMA MISMATCH
try:
    cursor.execute("SELECT * FROM equity_prices")
except sqlite3.OperationalError:
    # Table doesn't exist - run migrations
    MigrationRunner().apply_migrations(...)
```

### API Errors

```python
# RATE LIMIT
if response_code == 429:
    wait_seconds = int(response.headers.get('Retry-After', 60))
    time.sleep(wait_seconds)
    return get_with_retry(...)

# STALE CACHE + RATE LIMIT
if cache_stale and hit_rate_limit:
    return cache.get_equity_prices(...)  # Return stale but don't error

# MISSING DATA
if not api_response:
    record_data_gap(symbol, start_date, end_date, reason='no_data')
    return cache.get_equity_prices(...)  # Return what we have
```

---

## Monitoring & Health Checks

### Daily Health Check Script

```python
def health_check():
    """Run daily to verify database health."""
    checks = {
        'symbols_count': cache.get_symbol_count(),
        'equity_prices': cache.get_record_count('equity_prices'),
        'cache_freshness': check_cache_freshness(),
        'api_quota_usage': check_api_quota(),
        'db_integrity': verify_integrity(),
    }
    return checks

# Output:
{
    'symbols_count': 1000,
    'equity_prices': 252000,  # 1000 symbols × 252 days
    'cache_freshness': '48 symbols stale',
    'api_quota_usage': '12 of 25 requests used',
    'db_integrity': 'OK'
}
```

### Common Health Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| Database locked | Timeout on writes | Close other connections |
| Stale cache | Backtest using old data | Run refresh cycle |
| Rate limit hit | Can't fetch new data | Wait for 24h reset |
| Missing data | Gaps in returns | Check data_gaps table |
| Corrupt database | Integrity check fails | Restore from backup |

---

## Migration Path to PostgreSQL

If SQLite becomes limiting (100M+ rows, concurrent writers):

```python
# Phase 1: Abstract database layer
class Database:
    """Abstract interface - compatible with SQLite and PostgreSQL."""
    def execute(self, sql, params=None): pass
    def fetch_one(self, sql, params=None): pass
    def fetch_all(self, sql, params=None): pass

# Phase 2: Create PostgreSQL implementation
class PostgreSQLDatabase(Database):
    def __init__(self, connection_string):
        self.conn = psycopg2.connect(connection_string)

# Phase 3: Use factory
db = SQLiteDatabase('market_data.db')
# Later:
db = PostgreSQLDatabase('postgresql://user:pass@host/dbname')
```

**Cost**: ~1-2 days migration, no application code changes (if using abstraction)

---

## Related Documents

### Design & Reference
- `SQLITE_SCHEMA_DESIGN.md` - Comprehensive 1200+ line design
- `Data/Cache/migrations/001_initial_schema.sql` - DDL
- `Data/Cache/migrations/README.md` - Migration management
- `Data/Cache/SAMPLE_QUERIES.sql` - 50+ real-world queries

### Implementation
- `Data/Cache/SQLiteCache.py` - Core cache module (to be created)
- `Data/Cache/MigrationRunner.py` - Migration runner (to be created)
- `Data/DataProvider.py` - DataProvider integration (to be created)

### Testing
- `tests/unit/data/test_sqlite_cache.py` - Unit tests
- `tests/integration/test_data_pipeline.py` - Integration tests

---

## Checklist for Completion

### Schema Design (DONE)
- [x] Write SQLITE_SCHEMA_DESIGN.md
- [x] Create 001_initial_schema.sql
- [x] Write migrations/README.md
- [x] Create SAMPLE_QUERIES.sql

### Implementation (READY)
- [ ] Create SQLiteCache module
- [ ] Create MigrationRunner module
- [ ] Create DataProvider integration
- [ ] Update Adapter for real data

### Testing
- [ ] Unit tests for cache (20+ tests)
- [ ] Integration tests with real API (5+ tests)
- [ ] Sample queries validation
- [ ] Performance benchmarks

### Verification
- [ ] All tests passing
- [ ] Real backtest with AAPL data
- [ ] Rate limit enforcement verified
- [ ] Cache hit rate > 95%

---

## Quick Start

### For Developers Implementing This

1. **Read the docs** (30 min):
   ```bash
   cat docs/SQLITE_SCHEMA_DESIGN.md
   cat Data/Cache/migrations/README.md
   ```

2. **Understand the schema** (30 min):
   ```bash
   sqlite3 :memory: < Data/Cache/migrations/001_initial_schema.sql
   .schema
   ```

3. **Review sample queries** (30 min):
   ```bash
   grep "^-- Query" Data/Cache/SAMPLE_QUERIES.sql
   # Pick a few and understand them
   ```

4. **Implement in phases**:
   - Phase 1: SQLiteCache + MigrationRunner
   - Phase 2: DataProvider integration
   - Phase 3: Tests and validation

### For Users Running Backtests

1. **Initialize database**:
   ```python
   from Data.Cache.SQLiteCache import SQLiteCache
   cache = SQLiteCache()
   cache.initialize_schema()
   ```

2. **Fetch data** (first run fetches from API, subsequent runs use cache):
   ```python
   from Data.DataProvider import DataProvider
   provider = DataProvider(cache, alphavantage_client)
   prices = provider.get_equity_prices('AAPL', start, end)
   ```

3. **Run backtest**:
   ```python
   backtest = Backtest(signals=MomentumSignal())
   result = backtest.run_from_dataframe(returns_df, dates=[...])
   ```

---

## Success Criteria

### Functional
- ✓ Database initializes without errors
- ✓ Prices can be inserted and retrieved
- ✓ Corporate actions tracked correctly
- ✓ Adjustment factors calculated properly
- ✓ API requests logged and rate limits enforced
- ✓ Cache freshness checked and updated

### Performance
- ✓ Single stock 1-year query: <1ms
- ✓ 10 stocks returns matrix: <20ms
- ✓ Cache freshness check: <50ms
- ✓ API request logging: <5ms

### Quality
- ✓ All unit tests pass
- ✓ Integration tests with real API pass
- ✓ Sample queries return expected results
- ✓ Database integrity checks pass

### Documentation
- ✓ Setup instructions clear
- ✓ API reference complete
- ✓ Sample queries documented
- ✓ Troubleshooting guide covers common issues

---

This comprehensive schema design provides a solid foundation for the ARBS data pipeline. It supports immediate needs (futures carry, equity signals) and scales for future enhancements (portfolio tracking, performance attribution).

