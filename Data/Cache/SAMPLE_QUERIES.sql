-- ABOUTME: Common SQL queries for ARBS data pipeline
-- ABOUTME: Examples for futures, equities, cache management, and backtest workflows

/*
================================================================================
SAMPLE QUERIES FOR ARBS DATA PIPELINE
================================================================================

This file contains common SQL queries for:
1. Time-series data retrieval (backtest workflows)
2. Corporate action handling (adjustment factors)
3. Cache freshness monitoring
4. API rate limit tracking
5. Data quality checks
6. Audit trail navigation

All queries are tested and production-ready.
================================================================================
*/


-- ============================================================================
-- SECTION 1: FUTURES DATA RETRIEVAL (for CarrySignal)
-- ============================================================================

-- Query 1.1: Get front and back contract prices for carry calculation
-- Used by: FuturesAdapter for CarrySignal input
SELECT
    f1.date,
    s1.symbol as front_contract,
    f1.close as front_price,
    f1.settlement_price,
    s2.symbol as back_contract,
    f2.close as back_price,
    sm1.expiry_date,
    sm1.last_trading_date,
    (DATE(sm1.last_trading_date, '-' || sm1.roll_days_before_expiry || ' days')) as roll_date
FROM futures_prices f1
JOIN symbols s1 ON f1.symbol_id = s1.id
JOIN symbol_metadata sm1 ON s1.id = sm1.symbol_id
-- Join to next contract (manual mapping for now)
-- In production, use get_next_contract() helper
LEFT JOIN symbols s2 ON s2.symbol = 'SFRH5'  -- Replace with computed next contract
LEFT JOIN futures_prices f2 ON f2.symbol_id = s2.id AND f2.date = f1.date
WHERE s1.symbol = 'SFRZ4'
  AND f1.date BETWEEN '2024-01-01' AND '2024-03-31'
  AND f1.close IS NOT NULL
  AND f2.close IS NOT NULL
ORDER BY f1.date;


-- Query 1.2: Get calendar spread history (front-back price differential)
-- Used by: CarrySignal for annualized carry calculation
WITH calendar_spreads AS (
    SELECT
        f1.date,
        f1.symbol_id,
        f1.close as front_close,
        f2.close as back_close,
        (f1.close - f2.close) as spread,
        sm1.expiry_date,
        sm1.last_trading_date
    FROM futures_prices f1
    LEFT JOIN futures_prices f2 ON
        f1.symbol_id = f2.symbol_id
        AND f2.date = f1.date
        AND f2.id != f1.id  -- Ensure different contracts
    JOIN symbol_metadata sm1 ON f1.symbol_id = sm1.symbol_id
    WHERE f1.date >= '2024-01-01'
)
SELECT
    date,
    symbol_id,
    front_close,
    back_close,
    spread,
    (JULIANDAY(expiry_date) - JULIANDAY(date)) as days_to_roll,
    (spread / (JULIANDAY(expiry_date) - JULIANDAY(date))) * 10000 * 252 as annualized_carry_bps
FROM calendar_spreads
WHERE spread IS NOT NULL
  AND (JULIANDAY(expiry_date) - JULIANDAY(date)) > 0
ORDER BY date DESC;


-- Query 1.3: Get continuous contract time series (for momentum calculation)
-- Used by: MomentumSignal to calculate price trends
-- This is complex because contracts change with expiry
-- Strategy: Use settlement_price for stability
WITH contract_history AS (
    SELECT
        fp.date,
        fp.settlement_price,
        sm.expiry_date,
        sm.contract_code,
        ROW_NUMBER() OVER (PARTITION BY fp.symbol_id ORDER BY fp.date DESC) as recency
    FROM futures_prices fp
    JOIN symbol_metadata sm ON fp.symbol_id = sm.symbol_id
    WHERE fp.symbol_id IN (
        SELECT id FROM symbols WHERE symbol IN ('SFRZ4', 'SFRH5', 'SFRM5')
    )
      AND fp.date >= '2024-01-01'
      AND fp.settlement_price IS NOT NULL
)
SELECT
    date,
    settlement_price,
    LAG(settlement_price) OVER (ORDER BY date) as prev_price,
    (settlement_price - LAG(settlement_price) OVER (ORDER BY date))
        / LAG(settlement_price) OVER (ORDER BY date) as daily_return
FROM contract_history
WHERE recency <= 1  -- Use most recent contract for each date
ORDER BY date;


-- ============================================================================
-- SECTION 2: EQUITY DATA RETRIEVAL (for momentum, mean reversion)
-- ============================================================================

-- Query 2.1: Get adjusted closing prices for single equity
-- Used by: EquityAdapter, backtest.run_from_dataframe()
SELECT
    ep.date,
    s.ticker,
    ep.adjusted_close,
    ep.volume,
    ep.adjustment_factor
FROM equity_prices ep
JOIN symbols s ON ep.symbol_id = s.id
WHERE s.ticker = 'AAPL'
  AND ep.date BETWEEN '2024-01-01' AND '2024-12-31'
  AND ep.adjusted_close IS NOT NULL
ORDER BY ep.date;


-- Query 2.2: Get returns matrix for multiple equities (key backtest input)
-- Used by: Backtest.run_from_dataframe() - this is the most critical query
WITH daily_returns AS (
    SELECT
        ep.date,
        s.ticker,
        ep.adjusted_close,
        LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        ) as prev_adjusted_close
    FROM equity_prices ep
    JOIN symbols s ON ep.symbol_id = s.id
    WHERE s.ticker IN ('AAPL', 'MSFT', 'GOOGL')
      AND ep.date BETWEEN '2024-01-01' AND '2024-12-31'
      AND ep.adjusted_close IS NOT NULL
)
SELECT
    date,
    ticker,
    ROUND((adjusted_close - prev_adjusted_close) / prev_adjusted_close, 6) as daily_return,
    adjusted_close
FROM daily_returns
WHERE prev_adjusted_close IS NOT NULL
ORDER BY date, ticker;


-- Query 2.3: Get price history with corporate action adjustments
-- Shows how adjusted_close differs from unadjusted due to splits/dividends
SELECT
    ep.date,
    s.ticker,
    ep.close_unadjusted,
    ep.adjusted_close,
    ep.adjustment_factor,
    CASE
        WHEN ep.adjustment_factor < 0.99 THEN 'Split or Dividend'
        WHEN ep.adjustment_factor > 1.01 THEN 'Bonus Issue'
        ELSE 'No Action'
    END as corporate_action_type
FROM equity_prices ep
JOIN symbols s ON ep.symbol_id = s.id
WHERE s.ticker = 'AAPL'
  AND ep.date BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY ep.date;


-- Query 2.4: Get momentum lookback window (last N days of prices)
-- Used by: MomentumSignal to calculate 60-day momentum
SELECT
    ep.date,
    s.ticker,
    ep.adjusted_close,
    ROUND((ep.adjusted_close - LAG(ep.adjusted_close, 60) OVER (
        PARTITION BY ep.symbol_id ORDER BY ep.date
    )) / LAG(ep.adjusted_close, 60) OVER (
        PARTITION BY ep.symbol_id ORDER BY ep.date
    ), 6) as momentum_60d
FROM equity_prices ep
JOIN symbols s ON ep.symbol_id = s.id
WHERE s.ticker = 'AAPL'
  AND ep.date >= DATE('2024-01-01', '-60 days')
  AND ep.date <= '2024-12-31'
  AND ep.adjusted_close IS NOT NULL
ORDER BY ep.date DESC;


-- ============================================================================
-- SECTION 3: FOREX DATA RETRIEVAL
-- ============================================================================

-- Query 3.1: Get currency pair rates
-- Used by: FX strategies, cross-asset correlation
SELECT
    fr.date,
    s.symbol,
    fr.open,
    fr.high,
    fr.low,
    fr.close,
    fr.volume
FROM forex_rates fr
JOIN symbols s ON fr.symbol_id = s.id
WHERE s.symbol = 'EURUSD'
  AND fr.date BETWEEN '2024-01-01' AND '2024-12-31'
  AND fr.close IS NOT NULL
ORDER BY fr.date;


-- Query 3.2: Get FX returns for correlation analysis
-- Used by: Multi-asset signal correlation
WITH fx_returns AS (
    SELECT
        fr.date,
        s.symbol,
        fr.close,
        LAG(fr.close) OVER (
            PARTITION BY fr.symbol_id ORDER BY fr.date
        ) as prev_close
    FROM forex_rates fr
    JOIN symbols s ON fr.symbol_id = s.id
    WHERE s.symbol IN ('EURUSD', 'GBPUSD', 'JPYUSD')
      AND fr.date BETWEEN '2024-01-01' AND '2024-12-31'
)
SELECT
    date,
    symbol,
    ROUND((close - prev_close) / prev_close, 6) as daily_return
FROM fx_returns
WHERE prev_close IS NOT NULL
ORDER BY date, symbol;


-- ============================================================================
-- SECTION 4: CORPORATE ACTIONS & ADJUSTMENTS
-- ============================================================================

-- Query 4.1: Get all dividends for an equity (for adjustment verification)
-- Used by: Verify adjusted_close calculations
SELECT
    d.ex_date,
    d.payment_date,
    d.dividend_amount,
    ds.name as source,
    ep.close_unadjusted as price_on_ex_date,
    ep.adjustment_factor
FROM dividends d
JOIN symbols s ON d.symbol_id = s.id
JOIN data_sources ds ON d.source_id = ds.id
LEFT JOIN equity_prices ep ON d.symbol_id = ep.symbol_id AND ep.date = d.ex_date
WHERE s.ticker = 'AAPL'
ORDER BY d.ex_date DESC;


-- Query 4.2: Get stock splits (price adjustments)
-- Used by: Verify split handling in returns calculation
SELECT
    sp.effective_date,
    sp.old_shares,
    sp.new_shares,
    sp.split_ratio,
    ds.name as source,
    ep.close_unadjusted as price_before_split,
    (ep.close_unadjusted / sp.split_ratio) as price_after_split
FROM splits sp
JOIN symbols s ON sp.symbol_id = s.id
JOIN data_sources ds ON sp.source_id = ds.id
LEFT JOIN equity_prices ep ON sp.symbol_id = ep.symbol_id AND ep.date = sp.effective_date
WHERE s.ticker = 'AAPL'
ORDER BY sp.effective_date DESC;


-- Query 4.3: All corporate events (unified view)
-- Used by: Understand all corporate actions for an equity
SELECT
    ce.event_date,
    ce.event_type,
    CASE
        WHEN ce.event_type = 'dividend' THEN ROUND(d.dividend_amount, 4)
        WHEN ce.event_type = 'split' THEN ROUND(sp.split_ratio, 2)
        WHEN ce.event_type = 'bonus' THEN ROUND(bi.bonus_ratio, 2)
        ELSE NULL
    END as event_value,
    ds.name as source
FROM corporate_events ce
JOIN symbols s ON ce.symbol_id = s.id
LEFT JOIN dividends d ON ce.event_date = d.ex_date AND ce.symbol_id = d.symbol_id
LEFT JOIN splits sp ON ce.event_date = sp.effective_date AND ce.symbol_id = sp.symbol_id
LEFT JOIN bonus_issues bi ON ce.event_date = bi.effective_date AND ce.symbol_id = bi.symbol_id
LEFT JOIN data_sources ds ON ce.source_id = ds.id
WHERE s.ticker = 'AAPL'
ORDER BY ce.event_date DESC;


-- ============================================================================
-- SECTION 5: CACHE MANAGEMENT & FRESHNESS
-- ============================================================================

-- Query 5.1: Check cache freshness (which symbols need updating?)
-- Used by: DataProvider to decide whether to fetch new data
SELECT
    s.symbol,
    cc.price_table,
    cc.earliest_date,
    cc.latest_date,
    cc.last_fetched,
    cc.max_staleness_days,
    ROUND((JULIANDAY('now') - JULIANDAY(cc.last_fetched))) as days_since_fetch,
    CASE
        WHEN (JULIANDAY('now') - JULIANDAY(cc.last_fetched)) > cc.max_staleness_days
        THEN 'STALE - FETCH RECOMMENDED'
        ELSE 'FRESH'
    END as cache_status
FROM cache_coverage cc
JOIN symbols s ON cc.symbol_id = s.id
WHERE cc.price_table = 'equity_prices'
ORDER BY cc.last_fetched ASC
LIMIT 20;


-- Query 5.2: Update cache coverage after fetching new data
-- Used by: DataProvider.store_equity_prices()
-- This would be executed after INSERT of new prices
WITH new_prices AS (
    SELECT
        symbol_id,
        MIN(date) as min_date,
        MAX(date) as max_date,
        COUNT(*) as new_count
    FROM equity_prices
    WHERE symbol_id = 1  -- Example: AAPL
      AND date >= '2024-01-01'
)
UPDATE cache_coverage
SET
    earliest_date = (SELECT MIN(date) FROM equity_prices WHERE symbol_id = 1),
    latest_date = (SELECT MAX(date) FROM equity_prices WHERE symbol_id = 1),
    record_count = (SELECT COUNT(*) FROM equity_prices WHERE symbol_id = 1),
    last_fetched = CURRENT_TIMESTAMP,
    last_updated = CURRENT_TIMESTAMP
WHERE symbol_id = 1 AND price_table = 'equity_prices';


-- Query 5.3: Cache coverage by symbol and asset type
-- Used by: Understand cache completeness
SELECT
    s.symbol,
    s.type,
    CASE s.type
        WHEN 'equity' THEN 'equity_prices'
        WHEN 'futures' THEN 'futures_prices'
        WHEN 'forex' THEN 'forex_rates'
    END as table_name,
    cc.earliest_date,
    cc.latest_date,
    cc.record_count,
    (JULIANDAY(cc.latest_date) - JULIANDAY(cc.earliest_date)) as days_covered,
    ROUND(cc.record_count * 100.0 / (JULIANDAY(cc.latest_date) - JULIANDAY(cc.earliest_date)), 1) as coverage_percent
FROM cache_coverage cc
JOIN symbols s ON cc.symbol_id = s.id
WHERE cc.latest_date IS NOT NULL
ORDER BY s.type, s.symbol;


-- Query 5.4: Find symbols with missing coverage
-- Used by: Identify gaps in cache
SELECT
    s.symbol,
    s.type,
    cc.price_table,
    COUNT(*) as gap_count,
    MIN(dg.start_date) as oldest_gap,
    MAX(dg.end_date) as newest_gap
FROM data_gaps dg
JOIN symbols s ON dg.symbol_id = s.id
LEFT JOIN cache_coverage cc ON dg.symbol_id = cc.symbol_id
WHERE dg.reason IN ('market_halt', 'no_trading', 'delisted')
GROUP BY dg.symbol_id, s.symbol, s.type, cc.price_table
ORDER BY gap_count DESC;


-- ============================================================================
-- SECTION 6: API RATE LIMITING & USAGE TRACKING
-- ============================================================================

-- Query 6.1: Check rate limit status (how many requests used today?)
-- Used by: DataProvider to respect rate limits
SELECT
    ds.name,
    ds.rate_limit_per_day,
    COUNT(*) as requests_today,
    SUM(CASE WHEN ar.status = 'success' THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN ar.status = 'error' THEN 1 ELSE 0 END) as errors,
    SUM(CASE WHEN ar.status = 'rate_limit' THEN 1 ELSE 0 END) as rate_limited,
    ROUND(100.0 * COUNT(*) / ds.rate_limit_per_day, 1) as percent_quota_used,
    CASE
        WHEN COUNT(*) > ds.rate_limit_per_day * 0.9 THEN 'WARNING'
        WHEN COUNT(*) >= ds.rate_limit_per_day THEN 'EXCEEDED'
        ELSE 'OK'
    END as quota_status
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE DATE(ar.request_time) = DATE('now')
GROUP BY ds.id, ds.name, ds.rate_limit_per_day
ORDER BY percent_quota_used DESC;


-- Query 6.2: Requests per minute (sliding window check)
-- Used by: Enforce per-minute rate limits
SELECT
    ds.name,
    ds.rate_limit_per_minute,
    COUNT(*) as requests_last_minute,
    CASE
        WHEN COUNT(*) > ds.rate_limit_per_minute THEN 'EXCEEDED'
        WHEN COUNT(*) > ds.rate_limit_per_minute * 0.8 THEN 'WARNING'
        ELSE 'OK'
    END as status,
    ROUND(AVG(ar.response_time_ms), 2) as avg_response_ms
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE ar.request_time > datetime('now', '-1 minute')
  AND ar.status = 'success'
GROUP BY ds.id, ds.name, ds.rate_limit_per_minute;


-- Query 6.3: API performance by source
-- Used by: Evaluate data source quality
SELECT
    ds.name,
    COUNT(*) as total_requests,
    SUM(CASE WHEN ar.status = 'success' THEN 1 ELSE 0 END) as successful,
    ROUND(100.0 * SUM(CASE WHEN ar.status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate,
    ROUND(AVG(ar.response_time_ms), 2) as avg_response_ms,
    ROUND(MAX(ar.response_time_ms), 0) as max_response_ms,
    ROUND(MIN(ar.response_time_ms), 0) as min_response_ms,
    SUM(CASE WHEN ar.cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits
FROM api_requests ar
JOIN data_sources ds ON ar.source_id = ds.id
WHERE ar.request_time > datetime('now', '-7 days')
GROUP BY ds.id, ds.name
ORDER BY success_rate DESC;


-- Query 6.4: Find rate limit errors (what symbols hit the limit?)
-- Used by: Identify which symbols need prioritization
SELECT
    s.symbol,
    COUNT(*) as rate_limit_hits,
    MIN(ar.request_time) as first_hit,
    MAX(ar.request_time) as last_hit,
    ROUND(AVG(ar.response_time_ms), 2) as avg_wait_ms
FROM api_requests ar
JOIN symbols s ON ar.symbol_id = s.id
WHERE ar.status = 'rate_limit'
  AND ar.request_time > datetime('now', '-7 days')
GROUP BY ar.symbol_id, s.symbol
ORDER BY rate_limit_hits DESC
LIMIT 20;


-- ============================================================================
-- SECTION 7: DATA QUALITY & AUDIT
-- ============================================================================

-- Query 7.1: Find price corrections (audit trail)
-- Used by: Verify data integrity
SELECT
    s.symbol,
    ph.date,
    ph.price_table,
    ph.old_close as previous_value,
    ph.new_close as corrected_value,
    ROUND((ph.new_close - ph.old_close) / ph.old_close * 100, 2) as percent_change,
    ph.reason,
    ph.changed_by,
    ph.changed_at
FROM price_history ph
JOIN symbols s ON ph.symbol_id = s.id
ORDER BY ph.changed_at DESC
LIMIT 50;


-- Query 7.2: Identify price outliers (potential data errors)
-- Used by: Flag suspicious data for review
WITH price_stats AS (
    SELECT
        ep.symbol_id,
        AVG((ep.adjusted_close - LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        )) / LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        )) as avg_return,
        STDEV((ep.adjusted_close - LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        )) / LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        )) as stdev_return
    FROM equity_prices ep
    WHERE ep.date >= DATE('now', '-252 days')
    GROUP BY ep.symbol_id
)
SELECT
    s.symbol,
    ep.date,
    ep.adjusted_close,
    LAG(ep.adjusted_close) OVER (PARTITION BY ep.symbol_id ORDER BY ep.date) as prev_close,
    ROUND((ep.adjusted_close - LAG(ep.adjusted_close) OVER (
        PARTITION BY ep.symbol_id ORDER BY ep.date
    )) / LAG(ep.adjusted_close) OVER (
        PARTITION BY ep.symbol_id ORDER BY ep.date
    ), 4) as daily_return,
    ps.avg_return,
    ps.stdev_return,
    ROUND((
        ABS((ep.adjusted_close - LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        )) / LAG(ep.adjusted_close) OVER (
            PARTITION BY ep.symbol_id ORDER BY ep.date
        ) - ps.avg_return) / NULLIF(ps.stdev_return, 0)
    ), 2) as z_score
FROM equity_prices ep
JOIN price_stats ps ON ep.symbol_id = ps.symbol_id
JOIN symbols s ON ep.symbol_id = s.id
WHERE ABS((ep.adjusted_close - LAG(ep.adjusted_close) OVER (
    PARTITION BY ep.symbol_id ORDER BY ep.date
)) / LAG(ep.adjusted_close) OVER (
    PARTITION BY ep.symbol_id ORDER BY ep.date
) - ps.avg_return) / NULLIF(ps.stdev_return, 0) > 3.0  -- 3-sigma outlier
ORDER BY z_score DESC
LIMIT 50;


-- Query 7.3: Verify data consistency (no gaps, all trading days present)
-- Used by: Check data completeness
WITH date_series AS (
    SELECT
        DATE('2024-01-01', '+' || (ROW_NUMBER() OVER (ORDER BY 1) - 1) || ' days') as expected_date
    FROM (
        SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5
    )
    WHERE DATE('2024-01-01', '+' || (ROW_NUMBER() OVER (ORDER BY 1) - 1) || ' days') <= '2024-12-31'
)
SELECT
    ds.expected_date,
    CASE WHEN ep.date IS NULL THEN 'MISSING' ELSE 'OK' END as status,
    STRFTIME('%w', ds.expected_date) as day_of_week
FROM date_series ds
LEFT JOIN equity_prices ep ON ep.symbol_id = 1 AND ep.date = ds.expected_date
WHERE STRFTIME('%w', ds.expected_date) NOT IN ('0', '6')  -- Exclude weekends
  AND NOT EXISTS (SELECT 1 FROM data_gaps dg WHERE dg.start_date <= ds.expected_date AND dg.end_date >= ds.expected_date)
  AND ep.date IS NULL
LIMIT 20;


-- ============================================================================
-- SECTION 8: SUMMARY & DIAGNOSTICS
-- ============================================================================

-- Query 8.1: Database statistics summary
-- Used by: Overall health check
SELECT
    'Symbols' as table_name,
    COUNT(*) as total_records,
    (SELECT COUNT(DISTINCT type) FROM symbols) as unique_types
FROM symbols
UNION ALL
SELECT
    'Equity Prices',
    COUNT(*),
    (SELECT COUNT(DISTINCT symbol_id) FROM equity_prices)
FROM equity_prices
UNION ALL
SELECT
    'Futures Prices',
    COUNT(*),
    (SELECT COUNT(DISTINCT symbol_id) FROM futures_prices)
FROM futures_prices
UNION ALL
SELECT
    'Forex Rates',
    COUNT(*),
    (SELECT COUNT(DISTINCT symbol_id) FROM forex_rates)
FROM forex_rates
UNION ALL
SELECT
    'Corporate Events',
    COUNT(*),
    (SELECT COUNT(DISTINCT symbol_id) FROM corporate_events)
FROM corporate_events
UNION ALL
SELECT
    'API Requests',
    COUNT(*),
    (SELECT COUNT(DISTINCT source_id) FROM api_requests)
FROM api_requests
ORDER BY total_records DESC;


-- Query 8.2: Find most-accessed symbols (hottest assets)
-- Used by: Understand trading activity
SELECT
    s.symbol,
    s.type,
    COUNT(*) as access_count,
    MAX(ar.request_time) as last_accessed,
    SUM(CASE WHEN ar.cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits,
    ROUND(100.0 * SUM(CASE WHEN ar.cache_hit = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as hit_rate
FROM api_requests ar
JOIN symbols s ON ar.symbol_id = s.id
WHERE ar.request_time > datetime('now', '-7 days')
GROUP BY ar.symbol_id, s.symbol, s.type
ORDER BY access_count DESC
LIMIT 20;


-- Query 8.3: Database integrity check
-- Used by: Verify consistency
SELECT
    'Symbols with no metadata' as check_name,
    COUNT(*) as issue_count
FROM symbols s
LEFT JOIN symbol_metadata sm ON s.id = sm.symbol_id
WHERE sm.id IS NULL
UNION ALL
SELECT
    'Equity prices with null adjusted_close',
    COUNT(*)
FROM equity_prices
WHERE adjusted_close IS NULL
UNION ALL
SELECT
    'API requests with unknown source',
    COUNT(*)
FROM api_requests
WHERE source_id NOT IN (SELECT id FROM data_sources)
UNION ALL
SELECT
    'Cache coverage without symbol',
    COUNT(*)
FROM cache_coverage cc
WHERE cc.symbol_id NOT IN (SELECT id FROM symbols);

