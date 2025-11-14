-- ABOUTME: Initial SQLite schema for ARBS market data cache
-- ABOUTME: Comprehensive tables for futures, equities, forex with cache management and API tracking

/*
================================================================================
SCHEMA INITIALIZATION
================================================================================
This migration creates all core tables, indexes, and views for the ARBS
data pipeline. It is idempotent and safe to run multiple times.

Components:
1. Master tables (symbols, metadata, data sources)
2. Price tables (futures, equity, forex)
3. Corporate actions (dividends, splits, bonus)
4. Audit trail (price history)
5. Cache management (coverage, metadata, gaps)
6. API tracking (requests, rate limiting)
7. Schema management (migrations table)

Total tables: 17
Total indexes: 21
Total views: 2
*/

-- ============================================================================
-- PRAGMA SETTINGS
-- ============================================================================
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;


-- ============================================================================
-- 1. MASTER TABLES
-- ============================================================================

-- SYMBOLS: Master list of all instruments
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('futures', 'equity', 'forex', 'crypto')),
    exchange TEXT,
    currency TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(type);
CREATE INDEX IF NOT EXISTS idx_symbols_exchange ON symbols(exchange);


-- SYMBOL_METADATA: Extended info for each symbol
CREATE TABLE IF NOT EXISTS symbol_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL UNIQUE REFERENCES symbols(id) ON DELETE CASCADE,

    -- Futures specific
    contract_code TEXT,
    underlying_contract TEXT,
    imm_month TEXT,
    imm_year INTEGER,
    expiry_date DATE,
    first_notice_date DATE,
    last_trading_date DATE,
    roll_days_before_expiry INTEGER DEFAULT 5,
    contract_size INTEGER,
    tick_size REAL,
    point_value REAL,

    -- Equity specific
    ticker TEXT,
    sector TEXT,
    industry TEXT,
    market_cap REAL,
    share_type TEXT,

    -- Forex specific
    base_currency TEXT,
    quote_currency TEXT,
    pip_size REAL,

    -- Crypto specific
    blockchain TEXT,
    decimals INTEGER,

    -- General
    isin TEXT,
    cusip TEXT,
    settlement_days INTEGER DEFAULT 2,
    mic_code TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_symbol_metadata_ticker ON symbol_metadata(ticker);
CREATE INDEX IF NOT EXISTS idx_symbol_metadata_sector ON symbol_metadata(sector);
CREATE INDEX IF NOT EXISTS idx_symbol_metadata_expiry ON symbol_metadata(expiry_date);


-- DATA_SOURCES: Track origin of data
CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    provider TEXT,
    api_endpoint TEXT,
    rate_limit_per_minute INTEGER,
    rate_limit_per_day INTEGER,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_data_sources_name ON data_sources(name);
CREATE INDEX IF NOT EXISTS idx_data_sources_priority ON data_sources(priority);

-- Pre-populate standard sources
INSERT OR IGNORE INTO data_sources (id, name, provider, priority)
VALUES
    (1, 'manual', 'User Upload', 100),
    (2, 'alphavantage', 'Alpha Vantage API', 50),
    (3, 'yahoo', 'Yahoo Finance', 40),
    (4, 'api_integration', 'Custom API', 30);


-- ============================================================================
-- 2. PRICE DATA TABLES
-- ============================================================================

-- FUTURES_PRICES: Daily futures settlement prices
CREATE TABLE IF NOT EXISTS futures_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    date DATE NOT NULL,

    open REAL,
    high REAL,
    low REAL,
    close REAL,
    settlement_price REAL,

    volume INTEGER,
    open_interest INTEGER,

    source_id INTEGER REFERENCES data_sources(id),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    is_adjusted BOOLEAN DEFAULT 0,
    confidence INTEGER DEFAULT 100,

    UNIQUE(symbol_id, date)
);

CREATE INDEX IF NOT EXISTS idx_futures_prices_symbol_date ON futures_prices(symbol_id, date);
CREATE INDEX IF NOT EXISTS idx_futures_prices_date ON futures_prices(date);
CREATE INDEX IF NOT EXISTS idx_futures_prices_fetched ON futures_prices(fetched_at);


-- EQUITY_PRICES: Daily OHLCV with adjustments
CREATE TABLE IF NOT EXISTS equity_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    date DATE NOT NULL,

    open_unadjusted REAL,
    high_unadjusted REAL,
    low_unadjusted REAL,
    close_unadjusted REAL,
    volume INTEGER,

    adjusted_close REAL,
    adjustment_factor REAL DEFAULT 1.0,

    source_id INTEGER REFERENCES data_sources(id),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    confidence INTEGER DEFAULT 100,

    UNIQUE(symbol_id, date)
);

CREATE INDEX IF NOT EXISTS idx_equity_prices_symbol_date ON equity_prices(symbol_id, date);
CREATE INDEX IF NOT EXISTS idx_equity_prices_date ON equity_prices(date);
CREATE INDEX IF NOT EXISTS idx_equity_prices_fetched ON equity_prices(fetched_at);


-- FOREX_RATES: Currency pair rates
CREATE TABLE IF NOT EXISTS forex_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    date DATE NOT NULL,

    open REAL,
    high REAL,
    low REAL,
    close REAL,

    volume REAL,

    source_id INTEGER REFERENCES data_sources(id),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    confidence INTEGER DEFAULT 100,

    UNIQUE(symbol_id, date)
);

CREATE INDEX IF NOT EXISTS idx_forex_rates_symbol_date ON forex_rates(symbol_id, date);
CREATE INDEX IF NOT EXISTS idx_forex_rates_date ON forex_rates(date);
CREATE INDEX IF NOT EXISTS idx_forex_rates_fetched ON forex_rates(fetched_at);


-- ============================================================================
-- 3. CORPORATE ACTIONS
-- ============================================================================

-- DIVIDENDS: Cash dividend events
CREATE TABLE IF NOT EXISTS dividends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    ex_date DATE NOT NULL,
    record_date DATE,
    payment_date DATE,
    dividend_amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    source_id INTEGER REFERENCES data_sources(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(symbol_id, ex_date)
);

CREATE INDEX IF NOT EXISTS idx_dividends_symbol_date ON dividends(symbol_id, ex_date);
CREATE INDEX IF NOT EXISTS idx_dividends_payment_date ON dividends(payment_date);


-- SPLITS: Stock split events
CREATE TABLE IF NOT EXISTS splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    old_shares INTEGER NOT NULL,
    new_shares INTEGER NOT NULL,
    split_ratio REAL GENERATED ALWAYS AS (CAST(new_shares AS REAL) / CAST(old_shares AS REAL)) STORED,
    source_id INTEGER REFERENCES data_sources(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(symbol_id, effective_date)
);

CREATE INDEX IF NOT EXISTS idx_splits_symbol_date ON splits(symbol_id, effective_date);


-- BONUS_ISSUES: Bonus share issuances
CREATE TABLE IF NOT EXISTS bonus_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    effective_date DATE NOT NULL,
    bonus_ratio REAL NOT NULL,
    source_id INTEGER REFERENCES data_sources(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(symbol_id, effective_date)
);

CREATE INDEX IF NOT EXISTS idx_bonus_issues_symbol_date ON bonus_issues(symbol_id, effective_date);


-- CORPORATE_EVENTS: Aggregate log of all corporate actions
CREATE TABLE IF NOT EXISTS corporate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('dividend', 'split', 'bonus', 'rights', 'merger', 'delisting', 'rights_issue')),
    details TEXT,
    source_id INTEGER REFERENCES data_sources(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_corporate_events_symbol_date ON corporate_events(symbol_id, event_date);
CREATE INDEX IF NOT EXISTS idx_corporate_events_type ON corporate_events(event_type);


-- ============================================================================
-- 4. AUDIT TRAIL
-- ============================================================================

-- PRICE_HISTORY: Audit trail for corrections
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    price_table TEXT NOT NULL CHECK(price_table IN ('futures_prices', 'equity_prices', 'forex_rates')),

    old_close REAL,
    old_adjusted_close REAL,
    old_volume INTEGER,

    new_close REAL,
    new_adjusted_close REAL,
    new_volume INTEGER,

    reason TEXT,
    event_id INTEGER,

    changed_by TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_price_history_symbol_date ON price_history(symbol_id, date);
CREATE INDEX IF NOT EXISTS idx_price_history_reason ON price_history(reason);


-- ============================================================================
-- 5. CACHE MANAGEMENT
-- ============================================================================

-- CACHE_COVERAGE: Track date ranges cached
CREATE TABLE IF NOT EXISTS cache_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    price_table TEXT NOT NULL CHECK(price_table IN ('futures_prices', 'equity_prices', 'forex_rates')),

    earliest_date DATE,
    latest_date DATE,
    record_count INTEGER DEFAULT 0,

    last_fetched TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    max_staleness_days INTEGER DEFAULT 1,

    UNIQUE(symbol_id, price_table)
);

CREATE INDEX IF NOT EXISTS idx_cache_coverage_symbol ON cache_coverage(symbol_id);
CREATE INDEX IF NOT EXISTS idx_cache_coverage_last_fetched ON cache_coverage(last_fetched);


-- CACHE_METADATA: Summary stats
CREATE TABLE IF NOT EXISTS cache_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL UNIQUE CHECK(table_name IN ('futures_prices', 'equity_prices', 'forex_rates')),

    total_records INTEGER DEFAULT 0,
    unique_symbols INTEGER DEFAULT 0,
    earliest_date DATE,
    latest_date DATE,

    last_access TIMESTAMP,
    access_count INTEGER DEFAULT 0,

    estimated_size_bytes INTEGER,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- DATA_GAPS: Known missing data
CREATE TABLE IF NOT EXISTS data_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_data_gaps_symbol_date ON data_gaps(symbol_id, start_date);
CREATE INDEX IF NOT EXISTS idx_data_gaps_reason ON data_gaps(reason);


-- ============================================================================
-- 6. API TRACKING
-- ============================================================================

-- API_REQUESTS: Track all API calls for rate limiting
CREATE TABLE IF NOT EXISTS api_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES data_sources(id),
    symbol_id INTEGER REFERENCES symbols(id),

    endpoint TEXT,
    request_params TEXT,

    response_code INTEGER,
    response_time_ms INTEGER,
    cache_hit BOOLEAN DEFAULT 0,

    status TEXT CHECK(status IN ('success', 'error', 'rate_limit', 'timeout')),
    error_message TEXT,

    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_requests_source ON api_requests(source_id, request_time);
CREATE INDEX IF NOT EXISTS idx_api_requests_time ON api_requests(request_time);
CREATE INDEX IF NOT EXISTS idx_api_requests_status ON api_requests(status);
CREATE INDEX IF NOT EXISTS idx_api_requests_symbol ON api_requests(symbol_id, request_time);


-- ============================================================================
-- 7. SCHEMA MANAGEMENT
-- ============================================================================

-- SCHEMA_MIGRATIONS: Track applied migrations
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    description TEXT,
    sql_file TEXT,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    execution_time_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_schema_migrations_version ON schema_migrations(version);

-- Record this migration
INSERT OR IGNORE INTO schema_migrations (version, description, sql_file)
VALUES (1, 'Initial schema creation', '001_initial_schema.sql');


-- ============================================================================
-- 8. VIEWS FOR COMMON OPERATIONS
-- ============================================================================

-- View for rate limit checking (requests per minute)
CREATE VIEW IF NOT EXISTS api_requests_per_minute AS
SELECT
    source_id,
    DATE(request_time) as request_date,
    CAST(FLOOR((julianday(request_time) - julianday(DATE(request_time))) * 24 * 60) AS INTEGER) as minute,
    COUNT(*) as request_count
FROM api_requests
WHERE status = 'success'
  AND request_time > datetime('now', '-1 minute')
GROUP BY source_id, request_date, minute;


-- View for rate limit checking (requests per day)
CREATE VIEW IF NOT EXISTS api_requests_per_day AS
SELECT
    source_id,
    DATE(request_time) as request_date,
    COUNT(*) as request_count
FROM api_requests
WHERE status = 'success'
  AND DATE(request_time) = DATE('now')
GROUP BY source_id, request_date;


-- ============================================================================
-- 9. INITIALIZATION & VALIDATION
-- ============================================================================

-- Verify all tables created successfully
PRAGMA table_list;

-- Show schema version
SELECT 'Schema version 001 initialized' as status;
