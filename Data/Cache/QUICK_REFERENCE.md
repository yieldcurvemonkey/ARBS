# SQLite Schema - Quick Reference Card

## Database File Location
```
market_data.db
```

## Connection & Initialization

```python
from Data.Cache.SQLiteCache import SQLiteCache
from Data.Cache.MigrationRunner import MigrationRunner

# Initialize (creates tables if needed)
cache = SQLiteCache('market_data.db')
cache.initialize_schema()

# Or run migrations manually
runner = MigrationRunner()
runner.apply_migrations('market_data.db', 'Data/Cache/migrations')

# Check migration status
migrations = cache.get_applied_migrations()
print(f"Schema version: {len(migrations)}")
```

## Core Tables (17 total)

### Master Data
```
symbols              → Master instrument list
symbol_metadata      → Ticker, sector, expiry dates
data_sources         → AlphaVantage, Yahoo, manual sources
```

### Price Data
```
futures_prices       → Contract OHLC, settlement, OI
equity_prices        → Stock OHLCV with adjustments
forex_rates          → Currency pair rates
```

### Corporate Actions
```
dividends            → Cash dividend events
splits               → Stock split events (e.g., 2:1)
bonus_issues         → Bonus share events
corporate_events     → Unified event log
```

### Cache Management
```
cache_coverage       → Date ranges cached per symbol
cache_metadata       → Table-level statistics
data_gaps            → Known missing data
price_history        → Audit trail of corrections
```

### API Tracking
```
api_requests         → Every API call logged
schema_migrations    → Migration history
```

---

## Most Important Queries

### Get Equity Prices (backtest input)
```sql
SELECT date, ticker, adjusted_close
FROM equity_prices ep
JOIN symbols s ON ep.symbol_id = s.id
WHERE s.ticker = 'AAPL'
  AND ep.date BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY date;
```

### Get Returns Matrix (for backtest)
```sql
-- With adjusted closes and returns
WITH returns AS (
    SELECT
        ep.date, s.ticker, ep.adjusted_close,
        LAG(ep.adjusted_close) OVER (PARTITION BY ep.symbol_id ORDER BY ep.date) as prev_close
    FROM equity_prices ep
    JOIN symbols s ON ep.symbol_id = s.id
    WHERE s.ticker IN ('AAPL', 'MSFT', 'GOOGL')
)
SELECT date, ticker, (adjusted_close - prev_close) / prev_close as return
FROM returns
WHERE prev_close IS NOT NULL;
```

### Get Futures Carry Inputs (front + back prices)
```sql
SELECT
    f1.date,
    s1.symbol as front,
    f1.close as front_price,
    f2.close as back_price,
    sm.expiry_date
FROM futures_prices f1
LEFT JOIN futures_prices f2 ON f1.symbol_id = f2.symbol_id AND f1.date = f2.date
LEFT JOIN symbols s1 ON f1.symbol_id = s1.id
LEFT JOIN symbol_metadata sm ON s1.id = sm.symbol_id
WHERE s1.symbol = 'SFRZ4' AND f1.date = '2024-03-15';
```

### Check Cache Freshness (which symbols need fetching?)
```sql
SELECT s.symbol, cc.last_fetched,
    ROUND((JULIANDAY('now') - JULIANDAY(cc.last_fetched))) as days_stale
FROM cache_coverage cc
JOIN symbols s ON cc.symbol_id = s.id
WHERE cc.price_table = 'equity_prices'
    AND (JULIANDAY('now') - JULIANDAY(cc.last_fetched)) > 1
ORDER BY cc.last_fetched;
```

### Check API Rate Limits (quota remaining?)
```sql
SELECT ds.name, ds.rate_limit_per_day,
    COUNT(*) as used_today,
    ds.rate_limit_per_day - COUNT(*) as remaining
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE DATE(ar.request_time) = DATE('now')
    AND ar.status = 'success'
GROUP BY ds.id;
```

---

## Key Indexes (Performance)

| Index | Purpose | Query Pattern |
|-------|---------|---------------|
| `(symbol_id, date)` on each price table | Time-series lookup | "Get prices for AAPL between dates" |
| `(date)` on each price table | Date-range scans | "Get all prices on date X" |
| `(last_fetched)` on cache_coverage | Staleness detection | "Which symbols are stale?" |
| `(source_id, request_time)` on api_requests | Rate limit checks | "Requests in last minute?" |

---

## Common Operations

### Insert a Symbol
```python
cache.insert_symbol('AAPL', 'equity', 'NASDAQ', 'USD')
symbol_id = cache.get_symbol_id('AAPL')
```

### Insert Equity Price
```python
cache.insert_equity_price(
    symbol_id=1,
    date=date(2024, 1, 1),
    open=150.0,
    high=155.0,
    low=149.0,
    close=152.0,
    volume=50000000,
    adjusted_close=152.0,
    adjustment_factor=1.0,
    source='alphavantage'
)
```

### Insert Dividend (corporate action)
```python
cache.insert_dividend(
    symbol_id=1,
    ex_date=date(2024, 2, 15),
    dividend_amount=0.24,
    payment_date=date(2024, 3, 1),
    source='alphavantage'
)
```

### Update Cache Coverage
```python
cache.update_cache_coverage(
    symbol_id=1,
    table='equity_prices',
    earliest_date=date(2024, 1, 1),
    latest_date=date(2024, 12, 31),
    record_count=252
)
```

### Check Cache Freshness
```python
is_stale = cache.is_stale('AAPL', max_age_days=1)
if is_stale:
    # Fetch new data from API
    pass
```

### Log API Request (for rate limiting)
```python
cache.log_api_request(
    source='alphavantage',
    symbol='AAPL',
    status='success',
    response_time_ms=250,
    cache_hit=False
)
```

---

## Data Integrity Checks

### Verify Corporate Actions Applied
```sql
-- Check that dividends appear in adjustment_factor
SELECT s.ticker, ep.date, ep.adjusted_close, ep.adjustment_factor, d.dividend_amount
FROM dividends d
LEFT JOIN equity_prices ep ON d.symbol_id = ep.symbol_id AND ep.date = d.ex_date
LEFT JOIN symbols s ON d.symbol_id = s.id
WHERE s.ticker = 'AAPL'
ORDER BY ep.date DESC;
```

### Check for Missing Data (gaps)
```sql
-- Find trading days with no data
SELECT COUNT(*) as missing_days
FROM (
    SELECT DATE('2024-01-01', '+' || (ROW_NUMBER() OVER (ORDER BY 1) - 1) || ' days') as expected_date
    FROM (SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5)
    WHERE DATE('2024-01-01', '+' || (ROW_NUMBER() OVER (ORDER BY 1) - 1) || ' days') <= '2024-12-31'
) dates
LEFT JOIN equity_prices ep ON ep.symbol_id = 1 AND ep.date = dates.expected_date
WHERE STRFTIME('%w', expected_date) NOT IN ('0', '6')  -- Not weekend
    AND ep.date IS NULL;
```

### Verify Referential Integrity
```sql
-- Check for orphaned prices (symbol_id doesn't exist)
SELECT COUNT(*) as orphaned
FROM equity_prices ep
WHERE ep.symbol_id NOT IN (SELECT id FROM symbols);

-- Should return 0
```

---

## Performance Optimization

### Enable WAL Mode (faster writes)
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
```

### Analyze Query Plans
```sql
EXPLAIN QUERY PLAN
SELECT * FROM equity_prices
WHERE symbol_id = 1 AND date BETWEEN '2024-01-01' AND '2024-12-31';

-- Should show "SEARCH equity_prices USING idx_equity_prices_symbol_date"
```

### Check Database Size
```sql
SELECT
    ROUND(page_count * page_size / 1024.0 / 1024.0, 2) as size_mb
FROM pragma_page_count(), pragma_page_size();
```

---

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `database is locked` | Multiple writers | Wait or close connections |
| `no such table: equity_prices` | Schema not initialized | Run `cache.initialize_schema()` |
| `UNIQUE constraint failed` | Duplicate price | Use `INSERT OR IGNORE` |
| `no such column: ticker` | Schema outdated | Run migrations: `MigrationRunner().apply_migrations(...)` |
| Queries returning NULL | Missing data | Check `data_gaps` table |
| Very slow queries | Missing indexes | Analyze query plan with `EXPLAIN` |
| Backtest returns wrong IC | Adjustment factor not applied | Verify `equity_prices.adjusted_close` |

---

## Backup & Recovery

### Backup Database
```bash
sqlite3 market_data.db ".backup market_data_backup_$(date +%Y%m%d).db"
```

### Restore from Backup
```bash
cp market_data_backup_20251114.db market_data.db
```

### Check Database Integrity
```sql
PRAGMA integrity_check;
-- Should return "ok"
```

### Rebuild Indexes (if corrupted)
```sql
REINDEX;
```

---

## DataProvider Integration

### Basic Usage
```python
from Data.DataProvider import DataProvider
from Data.Cache.SQLiteCache import SQLiteCache
from Data.Providers.AlphaVantageClient import AlphaVantageClient

# Setup
cache = SQLiteCache('market_data.db')
client = AlphaVantageClient(api_key='YOUR_KEY')
provider = DataProvider(cache, client)

# Fetch (uses cache if available, API if stale)
prices = provider.get_equity_prices(
    symbol='AAPL',
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    force_refresh=False  # Use cache if available
)

# Get returns for backtest
returns_df = provider.get_equity_returns(
    symbols=['AAPL', 'MSFT', 'GOOGL'],
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)
```

### Rate Limit Handling
```python
# DataProvider automatically:
# 1. Checks remaining quota before API calls
# 2. Waits if rate limited (respects Retry-After header)
# 3. Returns cached data if API unavailable
# 4. Logs all requests to api_requests table

remaining = provider.get_api_quota('alphavantage')
print(f"AlphaVantage quota: {remaining} requests left today")
```

---

## Schema Versions

| Version | Migration | Date | Key Changes |
|---------|-----------|------|-------------|
| 1.0 | 001_initial_schema.sql | 2025-11-14 | Core schema: 17 tables, 21 indexes |
| 1.1 | 002_add_performance_indexes.sql | PENDING | Partial indexes for large datasets |
| 1.2 | 003_add_technical_indicators.sql | PENDING | Pre-computed indicators |

---

## SQLite vs PostgreSQL

**Use SQLite When**:
- Single-user development
- <1M rows total data
- <100 requests/minute
- Embedded in application

**Migrate to PostgreSQL When**:
- Multiple concurrent writers
- >10M rows of data
- >1000 requests/minute
- Need advanced features (JSON, arrays, PostGIS)

**Migration Path**: Use abstraction layer (Database interface)

---

## Related Files

```
Data/Cache/
├── SQLiteCache.py              # Core cache module (to implement)
├── MigrationRunner.py          # Migration execution (to implement)
├── QUICK_REFERENCE.md          # This file
├── SAMPLE_QUERIES.sql          # 50+ production queries
└── migrations/
    ├── 001_initial_schema.sql  # Core schema (DDL)
    └── README.md               # Migration management

docs/
├── SQLITE_SCHEMA_DESIGN.md     # Comprehensive design (1200+ lines)
├── SCHEMA_IMPLEMENTATION_GUIDE.md
└── ALPHAVANTAGE_DATA_PIPELINE_PLAN.md
```

---

## Key Principles

1. **Cache-First**: Always check cache before API
2. **Rate-Limit Aware**: Never exceed API quotas
3. **Append-Only**: Never delete data (use soft deletes)
4. **Audit Trail**: Log all changes in price_history
5. **Corporate Actions**: Always adjust for splits/dividends
6. **Idempotent**: Safe to run migrations multiple times

---

## Contact & Support

- **Design**: See SQLITE_SCHEMA_DESIGN.md
- **Implementation**: See SCHEMA_IMPLEMENTATION_GUIDE.md
- **Examples**: See SAMPLE_QUERIES.sql
- **Questions**: Check Data/Cache/migrations/README.md

---

**Print this card and keep it handy while developing!**

