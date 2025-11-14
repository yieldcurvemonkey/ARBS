# ABOUTME: Tests for SQLite cache implementation
# ABOUTME: Comprehensive tests for CRUD operations, schema management, and cache coverage

import pytest
import polars as pl
from datetime import date, datetime, timedelta
import os
import tempfile

from Data.Cache.SQLiteCache import SQLiteCache


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.unlink(path)
    # Also cleanup WAL files
    for suffix in ['-wal', '-shm']:
        wal_path = path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)


@pytest.fixture
def cache(temp_db):
    """Create SQLiteCache instance with temp database."""
    cache = SQLiteCache(db_path=temp_db)
    cache.initialize_schema()
    yield cache
    cache.close()


class TestSchemaInitialization:
    """Test database schema creation and initialization."""

    def test_initialize_schema_creates_tables(self, cache):
        """Test that schema initialization creates all required tables."""
        tables = cache._execute_query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).to_dict(as_series=False)['name']

        required_tables = [
            'api_requests', 'bonus_issues', 'cache_coverage', 'cache_metadata',
            'corporate_events', 'data_gaps', 'data_sources', 'dividends',
            'equity_prices', 'forex_rates', 'futures_prices', 'price_history',
            'schema_migrations', 'splits', 'symbol_metadata', 'symbols'
        ]

        for table in required_tables:
            assert table in tables, f"Table {table} not created"

    def test_initialize_schema_idempotent(self, cache):
        """Test that schema initialization can be run multiple times."""
        # Run initialize_schema again
        cache.initialize_schema()

        # Should not raise error and tables should still exist
        tables = cache._execute_query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).to_dict(as_series=False)['name']

        assert 'symbols' in tables
        assert 'equity_prices' in tables

    def test_data_sources_populated(self, cache):
        """Test that data_sources table is pre-populated."""
        sources = cache._execute_query(
            "SELECT name FROM data_sources ORDER BY priority DESC"
        ).to_dict(as_series=False)['name']

        assert 'manual' in sources
        assert 'alphavantage' in sources

    def test_schema_version_recorded(self, cache):
        """Test that migration version is recorded."""
        version = cache._execute_query(
            "SELECT version FROM schema_migrations WHERE version = 1"
        ).to_dict(as_series=False)['version']

        assert version == [1]


class TestSymbolManagement:
    """Test symbol registration and lookup."""

    def test_register_symbol_new(self, cache):
        """Test registering a new symbol."""
        symbol_id = cache.register_symbol('AAPL', 'equity', exchange='NASDAQ')
        assert symbol_id is not None
        assert isinstance(symbol_id, int)

    def test_register_symbol_duplicate(self, cache):
        """Test registering the same symbol twice returns same ID."""
        id1 = cache.register_symbol('AAPL', 'equity')
        id2 = cache.register_symbol('AAPL', 'equity')
        assert id1 == id2

    def test_get_symbol_id_exists(self, cache):
        """Test getting ID of existing symbol."""
        cache.register_symbol('MSFT', 'equity')
        symbol_id = cache.get_symbol_id('MSFT')
        assert symbol_id is not None

    def test_get_symbol_id_not_exists(self, cache):
        """Test getting ID of non-existent symbol returns None."""
        symbol_id = cache.get_symbol_id('NONEXISTENT')
        assert symbol_id is None


class TestEquityPrices:
    """Test equity price storage and retrieval."""

    def test_store_equity_prices(self, cache):
        """Test storing equity prices."""
        symbol_id = cache.register_symbol('AAPL', 'equity')

        data = pl.DataFrame({
            'date': [date(2024, 1, 1), date(2024, 1, 2)],
            'open': [150.0, 151.0],
            'high': [152.0, 153.0],
            'low': [149.0, 150.0],
            'close': [151.0, 152.0],
            'adjusted_close': [151.0, 152.0],
            'volume': [1000000, 1100000]
        })

        cache.store_equity_prices(symbol_id, data)

        # Verify stored
        stored = cache.get_equity_prices(
            symbol_id,
            date(2024, 1, 1),
            date(2024, 1, 2)
        )

        assert stored.height == 2
        assert stored['close'].to_list() == [151.0, 152.0]

    def test_store_equity_prices_duplicate_update(self, cache):
        """Test that storing duplicate dates updates existing records."""
        symbol_id = cache.register_symbol('GOOGL', 'equity')

        data1 = pl.DataFrame({
            'date': [date(2024, 1, 1)],
            'close': [100.0],
            'adjusted_close': [100.0],
            'volume': [1000000]
        })

        cache.store_equity_prices(symbol_id, data1)

        # Update with new data
        data2 = pl.DataFrame({
            'date': [date(2024, 1, 1)],
            'close': [105.0],
            'adjusted_close': [105.0],
            'volume': [1200000]
        })

        cache.store_equity_prices(symbol_id, data2)

        # Should have updated, not duplicated
        stored = cache.get_equity_prices(symbol_id, date(2024, 1, 1), date(2024, 1, 1))
        assert stored.height == 1
        assert stored['close'][0] == 105.0

    def test_get_equity_prices_date_range(self, cache):
        """Test retrieving equity prices for a date range."""
        symbol_id = cache.register_symbol('TSLA', 'equity')

        data = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 11)],
            'close': [float(100 + i) for i in range(10)],
            'adjusted_close': [float(100 + i) for i in range(10)],
            'volume': [1000000] * 10
        })

        cache.store_equity_prices(symbol_id, data)

        # Get subset
        stored = cache.get_equity_prices(
            symbol_id,
            date(2024, 1, 3),
            date(2024, 1, 7)
        )

        assert stored.height == 5
        assert stored['close'].to_list() == [103.0, 104.0, 105.0, 106.0, 107.0]

    def test_get_equity_prices_empty(self, cache):
        """Test retrieving prices when none exist."""
        symbol_id = cache.register_symbol('EMPTY', 'equity')

        stored = cache.get_equity_prices(
            symbol_id,
            date(2024, 1, 1),
            date(2024, 1, 10)
        )

        assert stored.height == 0


class TestCacheCoverage:
    """Test cache coverage tracking."""

    def test_get_cache_coverage_no_data(self, cache):
        """Test getting coverage when no data exists."""
        symbol_id = cache.register_symbol('NOCOV', 'equity')
        coverage = cache.get_cache_coverage(symbol_id, 'equity_prices')
        assert coverage is None

    def test_get_cache_coverage_with_data(self, cache):
        """Test getting coverage after storing data."""
        symbol_id = cache.register_symbol('AAPL', 'equity')

        data = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 11)],
            'close': [150.0] * 10,
            'adjusted_close': [150.0] * 10,
            'volume': [1000000] * 10
        })

        cache.store_equity_prices(symbol_id, data)

        coverage = cache.get_cache_coverage(symbol_id, 'equity_prices')

        assert coverage is not None
        assert coverage['earliest_date'] == date(2024, 1, 1)
        assert coverage['latest_date'] == date(2024, 1, 10)
        assert coverage['record_count'] == 10

    def test_is_stale_no_data(self, cache):
        """Test staleness check when no data exists."""
        symbol_id = cache.register_symbol('NOSTALE', 'equity')
        assert cache.is_stale(symbol_id, 'equity_prices', max_age_days=1)

    def test_is_stale_fresh_data(self, cache):
        """Test staleness check with fresh data."""
        symbol_id = cache.register_symbol('FRESH', 'equity')

        data = pl.DataFrame({
            'date': [date.today()],
            'close': [150.0],
            'adjusted_close': [150.0],
            'volume': [1000000]
        })

        cache.store_equity_prices(symbol_id, data)

        assert not cache.is_stale(symbol_id, 'equity_prices', max_age_days=1)

    def test_is_stale_old_data(self, cache):
        """Test staleness check with old data."""
        symbol_id = cache.register_symbol('OLD', 'equity')

        # Manually insert old data with old fetched_at
        cache._execute_query(f"""
            INSERT INTO cache_coverage
            (symbol_id, price_table, last_fetched, last_updated)
            VALUES ({symbol_id}, 'equity_prices',
                    datetime('now', '-10 days'), datetime('now', '-10 days'))
        """)

        assert cache.is_stale(symbol_id, 'equity_prices', max_age_days=1)


class TestFuturesPrices:
    """Test futures price storage and retrieval."""

    def test_store_futures_prices(self, cache):
        """Test storing futures prices."""
        symbol_id = cache.register_symbol('SFRZ4', 'futures')

        data = pl.DataFrame({
            'date': [date(2024, 1, 1), date(2024, 1, 2)],
            'settlement_price': [95.5, 95.6],
            'volume': [10000, 11000],
            'open_interest': [50000, 51000]
        })

        cache.store_futures_prices(symbol_id, data)

        stored = cache.get_futures_prices(
            symbol_id,
            date(2024, 1, 1),
            date(2024, 1, 2)
        )

        assert stored.height == 2
        assert stored['settlement_price'].to_list() == [95.5, 95.6]


class TestForexRates:
    """Test forex rate storage and retrieval."""

    def test_store_forex_rates(self, cache):
        """Test storing forex rates."""
        symbol_id = cache.register_symbol('EURUSD', 'forex')

        data = pl.DataFrame({
            'date': [date(2024, 1, 1), date(2024, 1, 2)],
            'open': [1.10, 1.11],
            'high': [1.12, 1.13],
            'low': [1.09, 1.10],
            'close': [1.11, 1.12],
            'volume': [1000000, 1100000]
        })

        cache.store_forex_rates(symbol_id, data)

        stored = cache.get_forex_rates(
            symbol_id,
            date(2024, 1, 1),
            date(2024, 1, 2)
        )

        assert stored.height == 2
        assert stored['close'].to_list() == [1.11, 1.12]


class TestPerformance:
    """Test cache performance."""

    def test_bulk_insert_performance(self, cache):
        """Test that bulk insert is reasonably fast."""
        import time

        symbol_id = cache.register_symbol('PERF', 'equity')

        # Create 1000 days of data
        data = pl.DataFrame({
            'date': [date(2020, 1, 1) + timedelta(days=i) for i in range(1000)],
            'close': [float(100 + i) for i in range(1000)],
            'adjusted_close': [float(100 + i) for i in range(1000)],
            'volume': [1000000] * 1000
        })

        start = time.time()
        cache.store_equity_prices(symbol_id, data)
        elapsed = time.time() - start

        # Should take less than 1 second
        assert elapsed < 1.0

    def test_query_performance(self, cache):
        """Test that queries are fast."""
        import time

        symbol_id = cache.register_symbol('QUERY', 'equity')

        # Store 1000 days
        data = pl.DataFrame({
            'date': [date(2020, 1, 1) + timedelta(days=i) for i in range(1000)],
            'close': [float(100 + i) for i in range(1000)],
            'adjusted_close': [float(100 + i) for i in range(1000)],
            'volume': [1000000] * 1000
        })

        cache.store_equity_prices(symbol_id, data)

        # Query subset
        start = time.time()
        cache.get_equity_prices(
            symbol_id,
            date(2020, 6, 1),
            date(2020, 12, 31)
        )
        elapsed = time.time() - start

        # Should take less than 10ms
        assert elapsed < 0.01


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_invalid_table_name(self, cache):
        """Test that invalid table names raise errors."""
        symbol_id = cache.register_symbol('TEST', 'equity')

        with pytest.raises(ValueError):
            cache.get_cache_coverage(symbol_id, 'invalid_table')

    def test_connection_closed_handling(self, cache):
        """Test that operations after close raise informative errors."""
        cache.close()

        with pytest.raises(Exception):
            cache.register_symbol('TEST', 'equity')
