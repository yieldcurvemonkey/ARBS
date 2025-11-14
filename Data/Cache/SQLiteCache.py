# ABOUTME: SQLite-based cache for market data with comprehensive CRUD operations
# ABOUTME: Manages futures, equity, and forex price data with coverage tracking and staleness detection

import sqlite3
import polars as pl
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SQLiteCache:
    """SQLite-based cache for market data.

    Provides persistent storage for futures, equity, and forex prices
    with automatic coverage tracking and staleness detection.

    Attributes:
        db_path: Path to SQLite database file
        conn: Active SQLite connection
    """

    def __init__(self, db_path: str = "market_data.db"):
        """Initialize SQLite cache.

        Args:
            db_path: Path to database file (default: market_data.db)
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self):
        """Establish database connection with proper settings."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        logger.info(f"Connected to database: {self.db_path}")

    def initialize_schema(self):
        """Create all tables and indexes from migration script.

        This method is idempotent and safe to run multiple times.
        """
        migration_path = Path(__file__).parent / "migrations" / "001_initial_schema.sql"

        with open(migration_path, 'r') as f:
            schema_sql = f.read()

        self.conn.executescript(schema_sql)
        self.conn.commit()
        logger.info("Schema initialized successfully")

    def _execute_query(self, query: str, params: tuple = ()) -> pl.DataFrame:
        """Execute SQL query and return results as Polars DataFrame.

        Args:
            query: SQL query string
            params: Query parameters for parameterized queries

        Returns:
            Query results as Polars DataFrame
        """
        cursor = self.conn.execute(query, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        if not rows:
            return pl.DataFrame(schema=columns)

        return pl.DataFrame(rows, schema=columns, orient='row')

    def register_symbol(
        self,
        symbol: str,
        symbol_type: str,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        description: Optional[str] = None
    ) -> int:
        """Register a new symbol or return existing ID.

        Args:
            symbol: Ticker or contract code
            symbol_type: One of 'futures', 'equity', 'forex', 'crypto'
            exchange: Exchange code (optional)
            currency: Currency code (optional)
            description: Human-readable description (optional)

        Returns:
            Symbol ID (integer primary key)
        """
        # Check if symbol exists
        existing = self._execute_query(
            "SELECT id FROM symbols WHERE symbol = ?",
            (symbol,)
        )

        if existing.height > 0:
            return existing['id'][0]

        # Insert new symbol
        cursor = self.conn.execute(
            """
            INSERT INTO symbols (symbol, type, exchange, currency, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (symbol, symbol_type, exchange, currency, description)
        )
        self.conn.commit()

        logger.debug(f"Registered symbol: {symbol} (ID: {cursor.lastrowid})")
        return cursor.lastrowid

    def get_symbol_id(self, symbol: str) -> Optional[int]:
        """Get symbol ID by ticker/contract code.

        Args:
            symbol: Ticker or contract code

        Returns:
            Symbol ID or None if not found
        """
        result = self._execute_query(
            "SELECT id FROM symbols WHERE symbol = ?",
            (symbol,)
        )

        return result['id'][0] if result.height > 0 else None

    def store_equity_prices(
        self,
        symbol_id: int,
        data: pl.DataFrame,
        source_name: str = 'manual'
    ):
        """Store equity prices in cache.

        Args:
            symbol_id: Symbol ID from symbols table
            data: DataFrame with columns: date, close, adjusted_close, volume
                  Optional: open, high, low
            source_name: Data source name (default: 'manual')
        """
        if data.height == 0:
            return

        # Get source_id
        source = self._execute_query(
            "SELECT id FROM data_sources WHERE name = ?",
            (source_name,)
        )
        source_id = source['id'][0] if source.height > 0 else 1

        # Prepare data for insertion
        required_cols = {'date', 'close', 'adjusted_close', 'volume'}
        if not required_cols.issubset(data.columns):
            raise ValueError(f"Data must contain columns: {required_cols}")

        # Add optional columns with defaults
        if 'open' not in data.columns:
            data = data.with_columns(pl.lit(None).alias('open'))
        if 'high' not in data.columns:
            data = data.with_columns(pl.lit(None).alias('high'))
        if 'low' not in data.columns:
            data = data.with_columns(pl.lit(None).alias('low'))

        # Add metadata columns
        data = data.with_columns([
            pl.lit(symbol_id).alias('symbol_id'),
            pl.lit(source_id).alias('source_id')
        ])

        # Convert to format for SQL insertion
        data = data.select([
            'symbol_id', 'date', 'open', 'high', 'low', 'close',
            'adjusted_close', 'volume', 'source_id'
        ])

        # Use INSERT OR REPLACE to handle duplicates
        for row in data.iter_rows(named=True):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO equity_prices
                (symbol_id, date, open_unadjusted, high_unadjusted,
                 low_unadjusted, close_unadjusted, adjusted_close,
                 volume, source_id, adjustment_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                        CASE WHEN ? IS NOT NULL AND ? IS NOT NULL
                             THEN ? / ?
                             ELSE 1.0
                        END)
                """,
                (
                    row['symbol_id'], row['date'], row['open'], row['high'],
                    row['low'], row['close'], row['adjusted_close'],
                    row['volume'], row['source_id'],
                    row['adjusted_close'], row['close'],
                    row['adjusted_close'], row['close']
                )
            )

        self.conn.commit()

        # Update cache coverage
        self._update_cache_coverage(symbol_id, 'equity_prices')

        logger.debug(f"Stored {data.height} equity prices for symbol_id={symbol_id}")

    def get_equity_prices(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """Retrieve equity prices from cache.

        Args:
            symbol_id: Symbol ID
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            DataFrame with columns: date, open, high, low, close,
                                   adjusted_close, volume, adjustment_factor
        """
        result = self._execute_query(
            """
            SELECT
                date,
                open_unadjusted as open,
                high_unadjusted as high,
                low_unadjusted as low,
                close_unadjusted as close,
                adjusted_close,
                volume,
                adjustment_factor
            FROM equity_prices
            WHERE symbol_id = ?
              AND date >= ?
              AND date <= ?
            ORDER BY date
            """,
            (symbol_id, start_date, end_date)
        )

        return result

    def store_futures_prices(
        self,
        symbol_id: int,
        data: pl.DataFrame,
        source_name: str = 'manual'
    ):
        """Store futures prices in cache.

        Args:
            symbol_id: Symbol ID
            data: DataFrame with columns: date, settlement_price
                  Optional: open, high, low, close, volume, open_interest
            source_name: Data source name
        """
        if data.height == 0:
            return

        # Get source_id
        source = self._execute_query(
            "SELECT id FROM data_sources WHERE name = ?",
            (source_name,)
        )
        source_id = source['id'][0] if source.height > 0 else 1

        # Required column
        if 'settlement_price' not in data.columns:
            raise ValueError("Data must contain 'settlement_price' column")

        # Add optional columns
        for col in ['open', 'high', 'low', 'close', 'volume', 'open_interest']:
            if col not in data.columns:
                data = data.with_columns(pl.lit(None).alias(col))

        # Add metadata
        data = data.with_columns([
            pl.lit(symbol_id).alias('symbol_id'),
            pl.lit(source_id).alias('source_id')
        ])

        # Insert
        for row in data.iter_rows(named=True):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO futures_prices
                (symbol_id, date, open, high, low, close, settlement_price,
                 volume, open_interest, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row['symbol_id'], row['date'], row['open'], row['high'],
                    row['low'], row['close'], row['settlement_price'],
                    row['volume'], row['open_interest'], row['source_id']
                )
            )

        self.conn.commit()
        self._update_cache_coverage(symbol_id, 'futures_prices')

        logger.debug(f"Stored {data.height} futures prices for symbol_id={symbol_id}")

    def get_futures_prices(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """Retrieve futures prices from cache.

        Args:
            symbol_id: Symbol ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with futures price data
        """
        result = self._execute_query(
            """
            SELECT
                date, open, high, low, close, settlement_price,
                volume, open_interest
            FROM futures_prices
            WHERE symbol_id = ?
              AND date >= ?
              AND date <= ?
            ORDER BY date
            """,
            (symbol_id, start_date, end_date)
        )

        return result

    def store_forex_rates(
        self,
        symbol_id: int,
        data: pl.DataFrame,
        source_name: str = 'manual'
    ):
        """Store forex rates in cache.

        Args:
            symbol_id: Symbol ID
            data: DataFrame with columns: date, open, high, low, close
                  Optional: volume
            source_name: Data source name
        """
        if data.height == 0:
            return

        source = self._execute_query(
            "SELECT id FROM data_sources WHERE name = ?",
            (source_name,)
        )
        source_id = source['id'][0] if source.height > 0 else 1

        required_cols = {'date', 'close'}
        if not required_cols.issubset(data.columns):
            raise ValueError(f"Data must contain columns: {required_cols}")

        # Add optional columns
        for col in ['open', 'high', 'low', 'volume']:
            if col not in data.columns:
                data = data.with_columns(pl.lit(None).alias(col))

        data = data.with_columns([
            pl.lit(symbol_id).alias('symbol_id'),
            pl.lit(source_id).alias('source_id')
        ])

        for row in data.iter_rows(named=True):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO forex_rates
                (symbol_id, date, open, high, low, close, volume, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row['symbol_id'], row['date'], row['open'], row['high'],
                    row['low'], row['close'], row['volume'], row['source_id']
                )
            )

        self.conn.commit()
        self._update_cache_coverage(symbol_id, 'forex_rates')

        logger.debug(f"Stored {data.height} forex rates for symbol_id={symbol_id}")

    def get_forex_rates(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """Retrieve forex rates from cache.

        Args:
            symbol_id: Symbol ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with forex rate data
        """
        result = self._execute_query(
            """
            SELECT date, open, high, low, close, volume
            FROM forex_rates
            WHERE symbol_id = ?
              AND date >= ?
              AND date <= ?
            ORDER BY date
            """,
            (symbol_id, start_date, end_date)
        )

        return result

    def _update_cache_coverage(self, symbol_id: int, price_table: str):
        """Update cache coverage metadata after storing data.

        Args:
            symbol_id: Symbol ID
            price_table: Table name ('equity_prices', 'futures_prices', 'forex_rates')
        """
        # Get date range and count
        stats = self._execute_query(
            f"""
            SELECT
                MIN(date) as earliest_date,
                MAX(date) as latest_date,
                COUNT(*) as record_count
            FROM {price_table}
            WHERE symbol_id = ?
            """,
            (symbol_id,)
        )

        if stats.height == 0 or stats['record_count'][0] == 0:
            return

        # Compute timestamp in Python (not SQL) to avoid non-deterministic index error
        current_timestamp = datetime.now().isoformat(sep=' ', timespec='seconds')

        # Update or insert coverage
        self.conn.execute(
            """
            INSERT OR REPLACE INTO cache_coverage
            (symbol_id, price_table, earliest_date, latest_date,
             record_count, last_fetched, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol_id, price_table, stats['earliest_date'][0],
                stats['latest_date'][0], stats['record_count'][0],
                current_timestamp, current_timestamp
            )
        )

        self.conn.commit()

    def get_cache_coverage(
        self,
        symbol_id: int,
        price_table: str
    ) -> Optional[Dict[str, Any]]:
        """Check cache coverage for a symbol.

        Args:
            symbol_id: Symbol ID
            price_table: Table name

        Returns:
            Dictionary with earliest_date, latest_date, record_count
            or None if no coverage
        """
        valid_tables = {'equity_prices', 'futures_prices', 'forex_rates'}
        if price_table not in valid_tables:
            raise ValueError(f"Invalid table name. Must be one of: {valid_tables}")

        result = self._execute_query(
            """
            SELECT earliest_date, latest_date, record_count, last_fetched
            FROM cache_coverage
            WHERE symbol_id = ? AND price_table = ?
            """,
            (symbol_id, price_table)
        )

        if result.height == 0:
            return None

        # Convert string dates to Python date objects
        earliest_str = result['earliest_date'][0]
        latest_str = result['latest_date'][0]

        return {
            'earliest_date': date.fromisoformat(earliest_str) if earliest_str else None,
            'latest_date': date.fromisoformat(latest_str) if latest_str else None,
            'record_count': result['record_count'][0],
            'last_fetched': result['last_fetched'][0]
        }

    def is_stale(
        self,
        symbol_id: int,
        price_table: str,
        max_age_days: int = 1
    ) -> bool:
        """Check if cached data is stale.

        Args:
            symbol_id: Symbol ID
            price_table: Table name
            max_age_days: Maximum age in days before considering stale

        Returns:
            True if data is stale or missing, False if fresh
        """
        coverage = self.get_cache_coverage(symbol_id, price_table)

        if coverage is None:
            return True  # No data = stale

        last_fetched = coverage.get('last_fetched')
        if last_fetched is None:
            return True

        # Parse datetime string (SQLite format: YYYY-MM-DD HH:MM:SS)
        last_fetched_dt = datetime.fromisoformat(last_fetched)
        age = datetime.now() - last_fetched_dt

        return age.days >= max_age_days

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed")

    def __del__(self):
        """Ensure connection is closed on deletion."""
        self.close()
