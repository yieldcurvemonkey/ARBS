# Database Migrations

This directory contains versioned SQL migrations for the ARBS market data SQLite database.

## Overview

Migrations are applied sequentially and tracked in the `schema_migrations` table. Each migration:
- Is **idempotent** (safe to run multiple times)
- Uses `IF NOT EXISTS` for all CREATE statements
- Uses `INSERT OR IGNORE` for seed data
- Never drops tables or columns (append-only design)

## Migration Files

### 001_initial_schema.sql
**Status**: CORE (required)
**Date**: 2025-11-14
**Components**:
- 17 tables (master, price, corporate actions, cache, API)
- 21 strategic indexes
- 2 views for rate limiting

**Tables**:
- `symbols` - Master instrument list
- `symbol_metadata` - Extended attributes
- `data_sources` - Data source tracking
- `futures_prices` - Futures OHLC data
- `equity_prices` - Equity OHLCV + adjustments
- `forex_rates` - Currency pair rates
- `dividends`, `splits`, `bonus_issues` - Corporate actions
- `corporate_events` - Unified event log
- `price_history` - Audit trail
- `cache_coverage` - Cache freshness tracking
- `cache_metadata` - Cache statistics
- `data_gaps` - Known missing data
- `api_requests` - API call logging
- `schema_migrations` - Version tracking

**Key Features**:
- Comprehensive indexing for performance
- Foreign key constraints for data integrity
- UNIQUE constraints for time-series data
- CHECK constraints for valid enum values
- Partial indexes for large datasets

### Future Migrations (Not yet implemented)

#### 002_add_performance_indexes.sql
**When**: After 1M+ rows in equity_prices
- Partial indexes for recent data (last 1 year)
- Covering indexes for common queries
- Analyze statistics collection

#### 003_add_technical_indicators.sql
**When**: For advanced signal development
- `technical_indicators` table
- Cached SMA, EMA, RSI, etc
- Automatic computation triggers

#### 004_add_portfolio_tracking.sql
**When**: For performance reporting
- Portfolio snapshots
- Position history
- Trade execution log

## Running Migrations

### Automatic (Recommended)

```python
from Data.Cache.MigrationRunner import MigrationRunner

runner = MigrationRunner()
runner.apply_migrations(
    db_path='market_data.db',
    migrations_dir='Data/Cache/migrations'
)
```

### Manual

```bash
# Connect to database
sqlite3 market_data.db

# Run migration
.read Data/Cache/migrations/001_initial_schema.sql

# Check applied migrations
SELECT * FROM schema_migrations;
```

### Checking Status

```python
# See which migrations have been applied
cursor.execute("SELECT * FROM schema_migrations ORDER BY version")
applied = cursor.fetchall()
print(f"Applied migrations: {len(applied)}")
for version, description, sql_file, applied_at, exec_time in applied:
    print(f"  {version}: {description} ({exec_time}ms)")
```

## Schema Versioning

**Current version**: 1.0 (migration 001)

**Version bumping rules**:
- Major version (1.0 → 2.0): Breaking changes to existing tables
- Minor version (1.0 → 1.1): New tables or non-breaking columns
- Patch version (1.0 → 1.0.1): Index additions, view changes

**Example**: Next migration would be v1.1 (migration 002)

## Design Principles

### Idempotency

All CREATE statements use `IF NOT EXISTS`:
```sql
-- GOOD: Safe to run multiple times
CREATE TABLE IF NOT EXISTS symbols (...)

-- GOOD: Safe to run multiple times
CREATE INDEX IF NOT EXISTS idx_... ON ...

-- BAD: Fails on second run
CREATE TABLE symbols (...)
```

### Append-Only

Never alter or drop existing structures:
```sql
-- GOOD: Add new column (but this requires careful migration)
ALTER TABLE equity_prices ADD COLUMN new_field TEXT;

-- BAD: Drop existing column (data loss!)
ALTER TABLE equity_prices DROP COLUMN old_field;

-- Better: Create new table with new schema, copy data
CREATE TABLE equity_prices_v2 AS SELECT ... FROM equity_prices;
DROP TABLE equity_prices;
ALTER TABLE equity_prices_v2 RENAME TO equity_prices;
```

### Seed Data

Pre-populate reference tables:
```sql
INSERT OR IGNORE INTO data_sources (id, name, provider, priority)
VALUES
    (1, 'manual', 'User Upload', 100),
    (2, 'alphavantage', 'Alpha Vantage API', 50);
```

## Backup Before Migrating

Always backup before applying new migrations:

```bash
# Create backup
sqlite3 market_data.db ".backup market_data_backup_$(date +%Y%m%d_%H%M%S).db"

# Apply migration
python -c "from Data.Cache.MigrationRunner import MigrationRunner; MigrationRunner().apply_migrations(...)"

# Verify backup intact
sqlite3 market_data_backup_*.db "PRAGMA integrity_check;"
```

## Rollback Strategy

SQLite doesn't support true rollbacks. Instead:

1. **Restore from backup** (simplest):
   ```bash
   cp market_data_backup_20251114.db market_data.db
   ```

2. **Manual undo** (if backup lost):
   ```sql
   -- For additions, manually cleanup new tables
   DROP TABLE IF EXISTS new_table_name;
   DELETE FROM schema_migrations WHERE version > N;
   ```

3. **Schema reset** (nuclear option):
   ```bash
   rm market_data.db
   python -c "from Data.Cache.SQLiteCache import SQLiteCache; SQLiteCache().initialize_schema()"
   ```

## Testing Migrations

### Unit Test Template

```python
def test_migration_001_creates_symbols_table():
    """Verify migration 001 creates symbols table."""
    db = SQLiteCache(':memory:')  # In-memory for testing
    db.initialize_schema()

    # Check table exists
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols'"
    )
    assert cursor.fetchone() is not None

    # Check columns
    cursor.execute("PRAGMA table_info(symbols)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'symbol' in columns
    assert 'type' in columns
```

### Integration Test Template

```python
def test_migration_001_roundtrip():
    """Verify migration 001 allows full data pipeline."""
    db = SQLiteCache(':memory:')
    db.initialize_schema()

    # Insert a symbol
    db.insert_symbol('AAPL', 'equity', 'NASDAQ', 'USD')

    # Insert price
    db.insert_equity_price('AAPL', date(2024, 1, 1), close=150.0, adjusted_close=150.0)

    # Query back
    prices = db.get_equity_prices('AAPL', date(2024, 1, 1), date(2024, 1, 1))
    assert len(prices) == 1
    assert prices[0]['close'] == 150.0
```

## Common Tasks

### Add a New Data Source

```sql
INSERT INTO data_sources (name, provider, rate_limit_per_minute, rate_limit_per_day)
VALUES ('quandl', 'Quandl API', 120, 10000);
```

### Check Cache Freshness

```sql
SELECT
    s.symbol,
    cc.price_table,
    cc.latest_date,
    cc.last_fetched,
    ROUND((julianday('now') - julianday(cc.last_fetched))) as days_stale
FROM cache_coverage cc
JOIN symbols s ON cc.symbol_id = s.id
WHERE cc.price_table = 'equity_prices'
ORDER BY cc.last_fetched ASC;
```

### Monitor API Rate Limits

```sql
SELECT
    ds.name,
    COUNT(*) as requests_today,
    ds.rate_limit_per_day,
    ROUND(100.0 * COUNT(*) / ds.rate_limit_per_day, 1) as percent_used
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE DATE(ar.request_time) = DATE('now')
  AND ar.status = 'success'
GROUP BY ds.id;
```

### Find Data Gaps

```sql
SELECT
    s.symbol,
    dg.start_date,
    dg.end_date,
    dg.reason,
    dg.created_at
FROM data_gaps dg
JOIN symbols s ON dg.symbol_id = s.id
WHERE dg.reason != 'weekend'
ORDER BY dg.start_date DESC;
```

## Performance Tuning

### Enable WAL Mode

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
```

### Analyze Statistics

```sql
-- Helps query planner optimize
ANALYZE;

-- See what statistics were collected
PRAGMA table_info(sqlite_stat1);
```

### Monitor Database Size

```sql
-- Check database file size
SELECT
    ROUND(page_count * page_size / 1024.0 / 1024.0, 2) as size_mb
FROM pragma_page_count(), pragma_page_size();

-- Check table sizes
SELECT
    name,
    ROUND(SUM(pgsize) / 1024.0 / 1024.0, 2) as size_mb
FROM dbstat
GROUP BY name
ORDER BY size_mb DESC;
```

## Related Documents

- `../SQLITE_SCHEMA_DESIGN.md` - Comprehensive schema design doc
- `../../docs/ALPHAVANTAGE_DATA_PIPELINE_PLAN.md` - Overall data pipeline
- `../SQLiteCache.py` - Python cache implementation

## Support

For questions or migration issues:
1. Check this README first
2. Search for similar issues in test logs
3. Review the migration SQL file
4. Create backup and test in development
5. Contact Peter (project lead) for critical issues
