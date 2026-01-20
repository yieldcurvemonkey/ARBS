-- Critical indexes for SDR Monitor performance
-- Run this script to fix the performance issues

-- 1. Primary indexes for time-based queries (most critical)
CREATE INDEX IF NOT EXISTS idx_sdr_event_timestamp ON sdr_data("Event timestamp");
CREATE INDEX IF NOT EXISTS idx_sdr_event_date ON sdr_data(DATE("Event timestamp"));

-- 2. Indexes for CB meeting analysis (critical for CROSS JOIN queries)
CREATE INDEX IF NOT EXISTS idx_sdr_effective_date ON sdr_data("Effective Date");
CREATE INDEX IF NOT EXISTS idx_sdr_maturity_date ON sdr_data("Maturity date of the underlier");

-- 3. Currency index for filtering
CREATE INDEX IF NOT EXISTS idx_sdr_notional_currency ON sdr_data("Notional currency-Leg 1");

-- 4. Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_sdr_currency_event_date ON sdr_data("Notional currency-Leg 1", DATE("Event timestamp"));
CREATE INDEX IF NOT EXISTS idx_sdr_currency_effective ON sdr_data("Notional currency-Leg 1", "Effective Date");
CREATE INDEX IF NOT EXISTS idx_sdr_currency_maturity ON sdr_data("Notional currency-Leg 1", "Maturity date of the underlier");

-- 5. Product name index for grouping
CREATE INDEX IF NOT EXISTS idx_sdr_product_name ON sdr_data("Product name");

-- 6. File source for slice tracking
CREATE INDEX IF NOT EXISTS idx_sdr_file_source ON sdr_data(file_source);

-- 7. BRIN index for time series data (much smaller than B-tree for large tables)
CREATE INDEX IF NOT EXISTS idx_sdr_event_timestamp_brin 
ON sdr_data USING BRIN ("Event timestamp") 
WITH (pages_per_range = 128);

-- 8. Partial indexes for common filters
CREATE INDEX IF NOT EXISTS idx_sdr_recent_trades 
ON sdr_data("Event timestamp") 
WHERE "Event timestamp" >= CURRENT_DATE - INTERVAL '30 days';

-- 9. Index for notional amount queries
CREATE INDEX IF NOT EXISTS idx_sdr_notional_amount ON sdr_data("Notional amount-Leg 1");

-- Show index creation progress
SELECT 
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_indexes
WHERE tablename = 'sdr_data'
ORDER BY indexname;