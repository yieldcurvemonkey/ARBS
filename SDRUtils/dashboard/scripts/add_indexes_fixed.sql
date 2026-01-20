-- Critical indexes for SDR Monitor performance
-- Fixed version that works with PostgreSQL limitations

-- 1. Event timestamp index (most critical)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_event_timestamp 
ON sdr_data("Event timestamp");

-- 2. Indexes for CB meeting analysis (critical for performance)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_effective_date 
ON sdr_data("Effective Date");

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_maturity_date 
ON sdr_data("Maturity date of the underlier");

-- 3. Currency index for filtering
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_notional_currency 
ON sdr_data("Notional currency-Leg 1");

-- 4. Composite indexes for common query patterns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_currency_event 
ON sdr_data("Notional currency-Leg 1", "Event timestamp");

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_currency_effective 
ON sdr_data("Notional currency-Leg 1", "Effective Date");

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_currency_maturity 
ON sdr_data("Notional currency-Leg 1", "Maturity date of the underlier");

-- 5. Product name index
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_product_name 
ON sdr_data("Product name");

-- 6. Notional amount for volume queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_notional_amount 
ON sdr_data("Notional amount-Leg 1");

-- Run ANALYZE to update statistics
ANALYZE sdr_data;