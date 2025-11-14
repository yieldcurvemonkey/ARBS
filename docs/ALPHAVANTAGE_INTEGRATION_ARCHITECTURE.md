# AlphaVantage + SQLite Integration Architecture

**Status**: Architecture Design Phase
**Created**: 2025-11-14
**Target**: Integrate real market data (AlphaVantage) with local caching (SQLite) into existing Backtest system

---

## Executive Summary

This document defines the complete integration architecture for AlphaVantage + SQLite into the ARBS backtesting system. The design maintains **100% backward compatibility** with existing MinimalBacktest and FuturesAdapter while adding real market data capabilities.

**Core Principle**: Never hit AlphaVantage unnecessarily
- First check: SQLite cache (fast, local)
- If miss or stale: Fetch from AlphaVantage (rate-limited)
- Always update cache after fetch
- Graceful fallback to cached data when rate limited

---

## System Architecture Overview

### Component Diagram (Layered Architecture)

```
┌─────────────────────────────────────────────────────────────────────┐
│                          APPLICATION LAYER                          │
│  (User code: Backtest.run(), Backtest.run_from_dataframe())        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
┌───────▼────────────────┐        ┌──────────▼──────────────┐
│  QUERY-BASED WORKFLOW  │        │ DATAFRAME-BASED WORKFLOW│
│  (Futures/Swaps)       │        │ (Equities/ETFs)         │
│                        │        │                         │
│ Backtest.run()         │        │ Backtest.run_from_df()  │
│  ↓                     │        │  ↓                      │
│ Adapter.convert()      │        │ (Already has returns)   │
│  ↓                     │        │                         │
│ Query → DataFrame      │        │ Optional: DataProvider  │
└───────┬────────────────┘        └──────────┬──────────────┘
        │                                   │
        └──────────────────┬────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                          ADAPTER LAYER                              │
│  FuturesAdapter (existing)      EquityAdapter (NEW)                 │
│  MinimalBacktest compatible     DataProvider-aware                  │
│  Query → Signal-ready DataFrame                                     │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                       DATA PROVIDER LAYER (NEW)                     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │            DataProvider (Unified Interface)              │        │
│  │  - get_equity_prices(symbol, dates)                     │        │
│  │  - get_forex_rates(pair, dates)                         │        │
│  │  - get_futures_prices(contract, dates)                  │        │
│  │  - Cache-first strategy with fallback                   │        │
│  └──────────────┬──────────────────────┬──────────────────┘        │
│                 │                      │                            │
│  ┌──────────────▼────────┐  ┌──────────▼──────────────┐            │
│  │   SQLite Cache        │  │  AlphaVantage Client    │            │
│  │   (Local, Fast)       │  │  (Remote, Rate-limited) │            │
│  │                       │  │                         │            │
│  │ Tables:               │  │ ├─ get_daily_adjusted() │            │
│  │ - equity_prices       │  │ ├─ get_intraday()       │            │
│  │ - forex_rates         │  │ ├─ get_forex_daily()    │            │
│  │ - futures_prices      │  │ └─ _make_request()      │            │
│  │ - api_requests        │  │                         │            │
│  │ - cache_metadata      │  │ RateLimiter:            │            │
│  │                       │  │ - 5 requests/min        │            │
│  │ Methods:              │  │ - 25 requests/day       │            │
│  │ - get/store operations│  │                         │            │
│  │ - cache_coverage()    │  │ ErrorHandling:          │            │
│  │ - is_stale()          │  │ - Retry with backoff    │            │
│  │ - initialize_schema() │  │ - Fallback to cache     │            │
│  └───────────────────────┘  └─────────────────────────┘            │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                      SIGNAL PIPELINE LAYER                          │
│  (Existing: no changes)                                             │
│  Signals → AlphaGenerator → Risk → Optimizer → Weights              │
└──────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
/home/user/ARBS/
├── Data/ (NEW)
│   ├── __init__.py
│   ├── DataProvider.py              # Main unified interface
│   ├── config.py                    # Configuration settings
│   │
│   ├── Cache/ (NEW)
│   │   ├── __init__.py
│   │   ├── SQLiteCache.py           # SQLite implementation
│   │   └── migrations/
│   │       └── 001_initial_schema.sql
│   │
│   └── Providers/ (NEW)
│       ├── __init__.py
│       ├── AlphaVantageClient.py    # API client
│       ├── RateLimiter.py           # Rate limiting logic
│       └── errors.py                 # Provider-specific exceptions
│
├── Adapter/
│   ├── EquityAdapter.py (NEW)       # Equity data adapter
│   └── FuturesAdapter.py (MODIFIED) # Add optional DataProvider support
│
├── tests/
│   ├── unit/
│   │   ├── data/ (NEW)
│   │   │   ├── test_sqlite_cache.py
│   │   │   ├── test_alphavantage_client.py
│   │   │   ├── test_rate_limiter.py
│   │   │   └── test_data_provider.py
│   │   └── adapter/
│   │       └── test_equity_adapter.py (NEW)
│   │
│   ├── integration/ (NEW)
│   │   ├── test_alphavantage_live.py
│   │   ├── test_data_provider_live.py
│   │   └── test_equity_backtest.py
│   │
│   └── performance/ (NEW)
│       ├── test_cache_performance.py
│       └── test_api_performance.py
│
├── examples/ (NEW)
│   ├── run_backtest_with_real_data.py
│   ├── run_backtest_with_cache.py
│   └── cache_management.py
│
├── docs/
│   ├── ALPHAVANTAGE_INTEGRATION_ARCHITECTURE.md (THIS FILE)
│   ├── DATA_PIPELINE_SETUP.md (NEW)
│   └── DATA_PROVIDER_API.md (NEW)
│
├── market_data.db (GITIGNORED)
├── .env.example (NEW)
└── .gitignore (UPDATED)
```

---

## Detailed Component Design

### 1. SQLiteCache - Local Cache Layer

**File**: `/home/user/ARBS/Data/Cache/SQLiteCache.py`

```python
class SQLiteCache:
    """SQLite-based cache for market data."""

    def __init__(self, db_path: str = "market_data.db"):
        """Initialize cache with database path."""

    def initialize_schema(self) -> None:
        """
        Create all tables and indexes if they don't exist.
        Idempotent: safe to call multiple times.
        """

    # EQUITY PRICES OPERATIONS
    def get_equity_prices(
        self,
        symbol: str,
        start_date: date,
        end_date: date
    ) -> Optional[pl.DataFrame]:
        """
        Fetch equity prices from cache.

        Returns:
            DataFrame with columns [date, open, high, low, close, adjusted_close,
                                   volume, dividend_amount, split_coefficient]
            or None if not found
        """

    def store_equity_prices(
        self,
        symbol: str,
        df: pl.DataFrame
    ) -> None:
        """
        Store equity prices in cache.

        Args:
            df: DataFrame with columns [date, open, high, low, close, adjusted_close,
                                       volume, dividend_amount, split_coefficient]
        """

    def get_cache_coverage(
        self,
        table: str,
        symbol: str
    ) -> tuple[Optional[date], Optional[date]]:
        """
        Check what date range is cached for a symbol.

        Returns:
            (earliest_date, latest_date) or (None, None) if not cached
        """

    def is_stale(
        self,
        symbol: str,
        table: str,
        max_age_days: int = 1
    ) -> bool:
        """
        Check if cached data is older than threshold.

        Args:
            max_age_days: Consider stale if older than this many days
        """

    # FOREX RATES OPERATIONS
    def get_forex_rates(
        self,
        from_currency: str,
        to_currency: str,
        start_date: date,
        end_date: date
    ) -> Optional[pl.DataFrame]:
        """Fetch forex rates from cache."""

    def store_forex_rates(
        self,
        from_currency: str,
        to_currency: str,
        df: pl.DataFrame
    ) -> None:
        """Store forex rates in cache."""

    # FUTURES PRICES OPERATIONS
    def get_futures_prices(
        self,
        contract: str,
        start_date: date,
        end_date: date
    ) -> Optional[pl.DataFrame]:
        """Fetch futures prices from cache."""

    def store_futures_prices(
        self,
        contract: str,
        df: pl.DataFrame
    ) -> None:
        """Store futures prices in cache."""

    # METADATA OPERATIONS
    def update_cache_metadata(
        self,
        table: str,
        symbol: str,
        earliest_date: date,
        latest_date: date,
        record_count: int
    ) -> None:
        """Update cache metadata for faster lookups."""

    def get_cache_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            {
                'total_symbols': int,
                'total_records': int,
                'equity_prices': {'symbols': int, 'records': int, 'date_range': (date, date)},
                'forex_rates': {...},
                'futures_prices': {...},
                'db_size_mb': float,
                'last_updated': datetime,
            }
        """

    # CLEANUP OPERATIONS
    def clear_symbol(self, table: str, symbol: str) -> None:
        """Remove all cached data for a symbol."""

    def clear_old_data(
        self,
        table: str,
        older_than_days: int = 365
    ) -> int:
        """
        Remove cached data older than threshold.

        Returns:
            Number of records deleted
        """

    def _init_db_connection(self) -> None:
        """Open database connection with WAL mode for concurrency."""

    def _apply_migrations(self) -> None:
        """Run schema migrations if needed."""

    def close(self) -> None:
        """Close database connection."""
```

**Schema (SQL)**:
```sql
-- Migration: 001_initial_schema.sql

CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_prices (
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

CREATE TABLE IF NOT EXISTS forex_rates (
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

CREATE TABLE IF NOT EXISTS futures_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract TEXT NOT NULL,
    date DATE NOT NULL,
    price REAL,
    settlement_price REAL,
    volume INTEGER,
    open_interest INTEGER,
    source TEXT DEFAULT 'manual',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(contract, date)
);

CREATE TABLE IF NOT EXISTS api_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    symbol TEXT,
    request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_code INTEGER,
    cache_hit BOOLEAN DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS cache_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    earliest_date DATE,
    latest_date DATE,
    record_count INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, symbol)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_equity_prices_symbol_date
    ON equity_prices(symbol, date);
CREATE INDEX IF NOT EXISTS idx_equity_prices_fetched
    ON equity_prices(fetched_at);
CREATE INDEX IF NOT EXISTS idx_forex_rates_pair_date
    ON forex_rates(from_currency, to_currency, date);
CREATE INDEX IF NOT EXISTS idx_futures_prices_contract_date
    ON futures_prices(contract, date);
CREATE INDEX IF NOT EXISTS idx_api_requests_time
    ON api_requests(request_time);
```

---

### 2. RateLimiter - API Rate Limiting

**File**: `/home/user/ARBS/Data/Providers/RateLimiter.py`

```python
class RateLimiter:
    """
    Rate limiter using sliding window algorithm.

    Enforces:
    - 5 requests per minute
    - 25 requests per day
    """

    def __init__(
        self,
        max_requests_per_minute: int = 5,
        max_requests_per_day: int = 25
    ):
        """Initialize rate limiter."""

    def acquire(self) -> float:
        """
        Block until we can make a request.

        Returns:
            Wait time in seconds (0 if no wait needed)
        """

    def can_make_request(self) -> bool:
        """Check if we can make request now without blocking."""

    def wait_time(self) -> float:
        """
        How long to wait before next request.

        Returns:
            Seconds to wait (0 if can request now)
        """

    def record_request(self, success: bool = True) -> None:
        """
        Record a request in the log.

        Args:
            success: Whether request succeeded (failed requests don't count toward limit)
        """

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            {
                'requests_this_minute': int,
                'requests_this_day': int,
                'requests_remaining_today': int,
                'reset_time': datetime,
            }
        """

    def _cleanup_old_requests(self) -> None:
        """Remove requests older than 24 hours."""
```

---

### 3. AlphaVantageClient - API Client

**File**: `/home/user/ARBS/Data/Providers/AlphaVantageClient.py`

```python
class AlphaVantageClient:
    """Client for AlphaVantage API with rate limiting and error handling."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str,
        rate_limiter: Optional[RateLimiter] = None
    ):
        """
        Initialize AlphaVantage client.

        Args:
            api_key: AlphaVantage API key
            rate_limiter: Rate limiter instance (creates default if not provided)
        """

    def get_daily_adjusted(
        self,
        symbol: str,
        outputsize: str = "full"
    ) -> pl.DataFrame:
        """
        Fetch daily adjusted prices (with splits/dividends).

        Args:
            symbol: Stock ticker (e.g., 'AAPL')
            outputsize: 'full' (all history) or 'compact' (last 100 days)

        Returns:
            DataFrame with columns [date, open, high, low, close, adjusted_close,
                                   volume, dividend_amount, split_coefficient]

        Raises:
            RateLimitError: If rate limit exceeded
            APIKeyError: If API key invalid
            SymbolNotFoundError: If ticker not found
            NetworkError: If connection fails
        """

    def get_intraday(
        self,
        symbol: str,
        interval: str = "5min"
    ) -> pl.DataFrame:
        """
        Fetch intraday prices.

        Args:
            symbol: Stock ticker
            interval: '1min', '5min', '15min', '30min', '60min'

        Returns:
            DataFrame with [datetime, open, high, low, close, volume]
        """

    def get_forex_daily(
        self,
        from_currency: str,
        to_currency: str
    ) -> pl.DataFrame:
        """
        Fetch forex daily rates.

        Returns:
            DataFrame with [date, open, high, low, close]
        """

    def get_technical_indicator(
        self,
        symbol: str,
        indicator: str = "SMA",
        interval: str = "daily",
        time_period: int = 20
    ) -> pl.DataFrame:
        """
        Fetch technical indicator data.

        Args:
            symbol: Stock ticker
            indicator: 'SMA', 'EMA', 'RSI', 'MACD', etc.
            time_period: Lookback period for indicator
        """

    def _make_request(
        self,
        params: dict
    ) -> dict:
        """
        Make rate-limited API request with retry logic.

        Args:
            params: Request parameters to append to base URL

        Returns:
            Response JSON as dictionary

        Raises:
            RateLimitError: If rate limit exceeded
            APIError: If API returns error
            NetworkError: If connection fails after retries
        """

    def _check_rate_limit(self) -> None:
        """Check if we can make request, wait if needed."""

    def _parse_daily_adjusted_response(self, response: dict) -> pl.DataFrame:
        """Convert API response to standardized DataFrame format."""

    def _handle_api_error(self, response: dict) -> None:
        """Check response for API errors and raise appropriate exceptions."""

    def _retry_with_backoff(
        self,
        func,
        max_attempts: int = 3,
        base_delay: float = 1.0
    ) -> Any:
        """Retry function with exponential backoff."""
```

**Custom Exceptions**:
```python
class APIError(Exception):
    """Base class for API errors."""

class RateLimitError(APIError):
    """Rate limit exceeded."""

    def __init__(self, wait_time: float, requests_today: int):
        self.wait_time = wait_time
        self.requests_today = requests_today

class SymbolNotFoundError(APIError):
    """Symbol not found in AlphaVantage."""

class APIKeyError(APIError):
    """Invalid or missing API key."""

class NetworkError(APIError):
    """Network connection error."""
```

---

### 4. DataProvider - Unified Interface

**File**: `/home/user/ARBS/Data/DataProvider.py`

```python
class DataProvider:
    """
    Unified interface for market data with intelligent caching.

    Implements cache-first strategy:
    1. Check SQLite cache
    2. If miss or stale: fetch from AlphaVantage
    3. Update cache
    4. Return data

    Handles all error cases gracefully with fallbacks.
    """

    def __init__(
        self,
        cache: SQLiteCache,
        alphavantage: AlphaVantageClient,
        cache_staleness_days: int = 1
    ):
        """
        Initialize DataProvider.

        Args:
            cache: SQLiteCache instance
            alphavantage: AlphaVantageClient instance
            cache_staleness_days: Maximum age before refresh (default: 1)
        """

    # PRIMARY INTERFACE METHODS
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
        1. Check cache coverage for [start_date, end_date]
        2. If full coverage and not stale: return cached
        3. If partial coverage: fetch missing dates from API
        4. If no coverage or force_refresh: fetch all from API
        5. Merge cache + API data
        6. Update cache
        7. Return complete DataFrame

        Args:
            symbol: Stock ticker (e.g., 'AAPL')
            start_date: First date
            end_date: Last date
            force_refresh: Skip cache and fetch fresh data

        Returns:
            DataFrame with [date, open, high, low, close, adjusted_close, volume]

        Raises:
            SymbolNotFoundError: If ticker not found
            NetworkError: If all retries exhausted (falls back to cache)
        """

    def get_equity_returns(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date,
        return_type: str = "simple"
    ) -> pl.DataFrame:
        """
        Get equity returns (prices → returns).

        Returns:
            DataFrame with [date, ticker, return]

        Convenience method for backtesting (avoids need to compute returns).
        """

    def get_forex_rates(
        self,
        from_currency: str,
        to_currency: str,
        start_date: date,
        end_date: date,
        force_refresh: bool = False
    ) -> pl.DataFrame:
        """Get forex rates with caching."""

    def get_futures_prices(
        self,
        contract: str,
        start_date: date,
        end_date: date,
        force_refresh: bool = False
    ) -> pl.DataFrame:
        """
        Get futures prices.

        Note: Currently queries SQLite cache only.
        Manual upload or integration with dedicated futures API needed.
        """

    # HELPER METHODS
    def _fetch_and_cache_equity(
        self,
        symbol: str,
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """
        Fetch from API and update cache.

        Returns:
            DataFrame from API (not cached yet)
        """

    def _merge_cache_and_api(
        self,
        cached_df: Optional[pl.DataFrame],
        api_df: Optional[pl.DataFrame],
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """
        Merge cached and newly fetched data.

        Strategy:
        - Remove duplicates (API data overwrites older cache)
        - Filter to requested date range
        - Sort by date
        """

    def _should_refresh(
        self,
        symbol: str,
        latest_cached_date: Optional[date],
        end_date: date,
        force_refresh: bool
    ) -> bool:
        """
        Determine if we need to fetch from API.

        Conditions for refresh:
        - force_refresh=True
        - No cache
        - Cache doesn't cover end_date
        - Cache is stale
        """

    def get_cache_stats(self) -> dict:
        """Get overall cache statistics."""

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """
        Clear cache for symbol or all symbols.

        Args:
            symbol: Clear specific symbol, or all if None
        """

    def warm_cache(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date
    ) -> dict:
        """
        Pre-populate cache with data.

        Useful before backtesting to avoid API hits during testing.

        Returns:
            {
                'success': List[str],  # Successfully cached symbols
                'failed': {symbol: error_message},
                'api_requests': int,
                'cached_records': int,
            }
        """
```

---

### 5. EquityAdapter - Integration with Backtest

**File**: `/home/user/ARBS/Adapter/EquityAdapter.py`

```python
class EquityAdapter(BaseAdapter):
    """
    Adapter for equity data with optional DataProvider integration.

    Converts raw equity prices to signal-ready format for backtesting.
    Can use either:
    - Real data via DataProvider (AlphaVantage + SQLite)
    - Mock/existing data directly
    """

    def __init__(
        self,
        market_data_provider: Any,
        data_provider: Optional[DataProvider] = None
    ):
        """
        Initialize equity adapter.

        Args:
            market_data_provider: Existing MDP (for compatibility)
            data_provider: Optional DataProvider for AlphaVantage integration
        """

    def convert(
        self,
        queries: List[Any],  # EquityQuery, ETFQuery
        as_of_date: date
    ) -> pl.DataFrame:
        """
        Convert equity queries to signal-ready DataFrame.

        Returns:
            DataFrame with [ticker, date, close, return, sector, weight]
        """

    def get_returns(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """
        Convenience method: Get returns matrix for Backtest.run_from_dataframe().

        If data_provider set:
        - Fetch from DataProvider (cache-first)

        Otherwise:
        - Use existing MDP

        Returns:
            DataFrame with [date, ticker, return]

        Example usage:
            >>> adapter = EquityAdapter(mdp, data_provider)
            >>> returns_df = adapter.get_returns(['AAPL', 'MSFT'],
            ...                                  date(2024, 1, 1),
            ...                                  date(2024, 12, 31))
            >>> backtest = Backtest(signals=MomentumSignal())
            >>> result = backtest.run_from_dataframe(returns_df, dates=[...])
        """

    def _fetch_from_data_provider(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """Fetch using DataProvider (with caching)."""

    def _fetch_from_mdp(
        self,
        symbols: List[str],
        start_date: date,
        end_date: date
    ) -> pl.DataFrame:
        """Fetch using existing market data provider."""

    def _calculate_returns(
        self,
        prices_df: pl.DataFrame,
        return_type: str = "simple"
    ) -> pl.DataFrame:
        """Convert prices to returns."""
```

---

### 6. FuturesAdapter - Backwards Compatibility

**File**: `/home/user/ARBS/Adapter/FuturesAdapter.py` (MODIFIED)

**Changes** (minimal, backwards compatible):
- Add optional `data_provider` parameter
- If provided, can use real futures data
- Default behavior unchanged (mock data still works)

```python
class FuturesAdapter(BaseAdapter):
    """FuturesAdapter - unchanged interface, optional DataProvider support."""

    def __init__(
        self,
        market_data_provider: Any,
        roll_days_before_expiry: int = 5,
        data_provider: Optional[DataProvider] = None  # NEW, optional
    ):
        """
        Initialize futures adapter.

        Args:
            market_data_provider: Source of market prices/curves
            roll_days_before_expiry: Days before expiry to roll (default: 5)
            data_provider: Optional DataProvider for real futures data (default: None)
        """
        super().__init__(market_data_provider)
        self.roll_days_before_expiry = roll_days_before_expiry
        self.data_provider = data_provider  # NEW

    # Rest unchanged - existing convert(), _convert_outright(), etc.
    # If data_provider set, can optionally fetch real contract prices
    # Otherwise uses mock data as before
```

---

## Data Flow Diagrams

### Workflow 1: Query-Based (Futures/Swaps)

```
User Code:
    backtest = Backtest(mdp=mdp, adapter=FuturesAdapter(mdp), signals=CarrySignal())
    result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])
                │
                ├─→ Backtest.run()
                    ├─→ adapter.convert(queries, as_of_date)
                    │   │
                    │   └─→ FuturesAdapter._get_price(contract, as_of_date)
                    │       ├─ Check: data_provider set?
                    │       ├─ IF YES:
                    │       │   └─ DataProvider.get_futures_prices()
                    │       │       └─ SQLiteCache → AlphaVantageClient → SQLiteCache
                    │       ├─ IF NO (backwards compat):
                    │       │   └─ mdp.get_pricer().futures_price() [mock]
                    │       └─ DataFrame(price, next_price, roll_date, ...)
                    │
                    ├─→ Signal.generate() → signals
                    ├─→ AlphaGenerator.signals_to_alphas() → alphas
                    ├─→ Optimizer.optimize() → weights
                    └─→ BacktestResult(weights, returns, signals, ...)
```

### Workflow 2: DataFrame-Based (Equities/ETFs)

```
User Code:
    adapter = EquityAdapter(mdp, data_provider=DataProvider(...))
    returns_df = adapter.get_returns(['AAPL', 'MSFT'], start_date, end_date)
    backtest = Backtest(signals=MomentumSignal())
    result = backtest.run_from_dataframe(returns_df, dates=[...])
                │
                ├─→ EquityAdapter.get_returns()
                    ├─ IF data_provider set:
                    │   ├─→ DataProvider.get_equity_returns()
                    │       └─→ For each symbol:
                    │           ├─→ DataProvider.get_equity_prices()
                    │               ├─→ SQLiteCache.get_equity_prices()
                    │               │   ├─ IF cache hit & not stale:
                    │               │   │   └─ Return cached
                    │               │   ├─ IF cache miss or stale:
                    │               │   │   ├─→ RateLimiter.acquire()
                    │               │   │   ├─→ AlphaVantageClient.get_daily_adjusted()
                    │               │   │   ├─→ SQLiteCache.store_equity_prices()
                    │               │   │   └─ Return fresh data
                    │               │   └─ Merge & return
                    │               └─ Calculate returns from prices
                    └─ IF data_provider NOT set:
                        └─ Use existing mdp (backward compat)
                    │
                    └─ returns_df [date, ticker, return]
                            │
                ├─→ Backtest.run_from_dataframe()
                    ├─→ Signal.generate() → signals
                    ├─→ AlphaGenerator.signals_to_alphas() → alphas
                    ├─→ Optimizer.optimize() → weights
                    └─→ BacktestResult(...)
```

### Workflow 3: Cache Check Flow (Core Algorithm)

```
DataProvider.get_equity_prices(symbol='AAPL', start=2024-01-01, end=2024-12-31)
    │
    ├─→ Check SQLiteCache coverage:
    │   ├─ Cache.get_cache_coverage('equity_prices', 'AAPL')
    │   │   └─ Returns: (earliest_cached, latest_cached) or (None, None)
    │   │
    │   ├─ Analyze coverage:
    │   │   ├─ IF Cache.is_stale():
    │   │   │   └─ Decision: REFRESH_ALL (fetch from API)
    │   │   ├─ ELSE IF coverage == [2024-01-01, 2024-12-31]:
    │   │   │   └─ Decision: CACHE_HIT (return cached)
    │   │   ├─ ELSE IF coverage covers request range with recent dates:
    │   │   │   └─ Decision: CACHE_HIT (return cached)
    │   │   └─ ELSE:
    │   │       └─ Decision: PARTIAL_MISS (fetch new dates, merge)
    │   │
    │   └─ [Record decision]
    │
    ├─→ Handle decision:
    │   │
    │   ├─ CACHE_HIT:
    │   │   ├─→ cached = Cache.get_equity_prices(symbol, start, end)
    │   │   ├─→ Record: api_requests(cache_hit=1)
    │   │   └─ RETURN cached
    │   │
    │   ├─ PARTIAL_MISS:
    │   │   ├─→ cached = Cache.get_equity_prices(symbol, start, min(end, latest_cached))
    │   │   ├─→ new_start = max(start, latest_cached + 1 day)
    │   │   ├─→ api_df = API.get_daily_adjusted(symbol, 'compact')
    │   │   ├─→ merged = Merge(cached, api_df)
    │   │   ├─→ Cache.store_equity_prices(symbol, merged)
    │   │   ├─→ Record: api_requests(cache_hit=0)
    │   │   └─ RETURN merged
    │   │
    │   └─ REFRESH_ALL:
    │       ├─ TRY:
    │       │   ├─→ RateLimiter.acquire() [blocks if needed]
    │       │   ├─→ api_df = API.get_daily_adjusted(symbol, 'full')
    │       │   ├─→ Cache.store_equity_prices(symbol, api_df)
    │       │   ├─→ Record: api_requests(cache_hit=0)
    │       │   └─ RETURN api_df
    │       │
    │       └─ EXCEPT RateLimitError:
    │           ├─→ cached = Cache.get_equity_prices(symbol, start, end)
    │           ├─→ Log: "Rate limit hit, returning cached data (may be stale)"
    │           ├─→ Record: api_requests(cache_hit=1, error="rate_limit")
    │           └─ RETURN cached [with warning]
    │
    └─ [END]
```

---

## Integration Points with Existing Code

### Point 1: Backtest.run() - Query-Based Workflow

**Current flow**:
```python
# FuturesAdapter._get_price() uses mdp.get_pricer().futures_price()
pricer = self.mdp.get_pricer('USD', as_of_date)
price = pricer.futures_price(contract)
```

**New integration point**:
```python
# FuturesAdapter._get_price() (optional)
if self.data_provider is not None:
    try:
        df = self.data_provider.get_futures_prices(
            contract=contract,
            start_date=as_of_date,
            end_date=as_of_date
        )
        if not df.is_empty():
            return df['price'][0]
    except Exception:
        pass  # Fall back to mdp

# Fallback to existing behavior
pricer = self.mdp.get_pricer('USD', as_of_date)
price = pricer.futures_price(contract)
```

**Key**: Backwards compatible - if data_provider not set, works exactly as before.

---

### Point 2: Backtest.run_from_dataframe() - DataFrame Workflow

**Current flow**:
```python
# User provides returns_df with [date, ticker, return]
backtest = Backtest(signals=MomentumSignal())
result = backtest.run_from_dataframe(returns_df, dates=[...])
```

**New integration point**:
```python
# User can now fetch returns_df using DataProvider
adapter = EquityAdapter(mdp, data_provider=DataProvider(...))
returns_df = adapter.get_returns(['AAPL', 'MSFT', ...], start_date, end_date)

# Then use same Backtest.run_from_dataframe() as before
backtest = Backtest(signals=MomentumSignal())
result = backtest.run_from_dataframe(returns_df, dates=[...])
```

**No changes needed** to Backtest itself - just provides convenient returns_df generation.

---

### Point 3: Adapter Base Class - No Changes Needed

BaseAdapter.convert() interface remains unchanged:
```python
@abstractmethod
def convert(self, queries: List[Any], as_of_date: date) -> pl.DataFrame:
    """Existing interface - no changes"""
```

Both FuturesAdapter and EquityAdapter implement this interface as before.

---

### Point 4: Signal Pipeline - Completely Transparent

Signals receive DataFrames from adapters, work with them as before. Zero changes to:
- BaseSignal
- CarrySignal, MomentumSignal, etc.
- AlphaGenerator
- Risk models
- Optimizer

The pipeline is completely decoupled from data source (cache vs live).

---

## Backwards Compatibility Strategy

### Guarantee: Zero Breaking Changes

**MinimalBacktest**: Continues to work exactly as before
```python
# This still works (no changes):
backtest = MinimalBacktest(mdp=mdp)
result = backtest.run(contracts=['SFRZ4'], dates=[...])
```

**FuturesAdapter**: Backwards compatible with optional enhancement
```python
# Old code still works:
adapter = FuturesAdapter(mdp)
df = adapter.convert(queries, as_of_date)

# New optional data_provider parameter:
adapter = FuturesAdapter(mdp, data_provider=DataProvider(...))
df = adapter.convert(queries, as_of_date)  # Can now use real data
```

**Generic Backtest**: No changes to interface
```python
# Existing usage unchanged:
backtest = Backtest(mdp=mdp, adapter=adapter, signals=signal)
result = backtest.run(contracts, dates)

# Existing usage unchanged:
backtest = Backtest(signals=signal)
result = backtest.run_from_dataframe(returns_df, dates)
```

### Migration Path for Users

**Option 1: Stay with Mock Data** (no changes)
```python
# Use existing mock data forever
backtest = Backtest(mdp=mock_mdp, adapter=FuturesAdapter(mock_mdp))
```

**Option 2: Gradually Add Real Data** (minimal changes)
```python
# Create DataProvider once
from Data.DataProvider import DataProvider
from Data.Cache.SQLiteCache import SQLiteCache
from Data.Providers.AlphaVantageClient import AlphaVantageClient

cache = SQLiteCache()
client = AlphaVantageClient(api_key="QLGCJCCK8X4ZY6VC")
provider = DataProvider(cache, client)

# Use with EquityAdapter for equities
adapter = EquityAdapter(mdp, data_provider=provider)
returns_df = adapter.get_returns(['AAPL', 'MSFT'], start_date, end_date)

# Use with FuturesAdapter (futures still use mock)
futures_adapter = FuturesAdapter(mdp)  # Optional: add data_provider later
```

**Option 3: Full Migration** (when ready)
```python
# Use DataProvider everywhere
provider = DataProvider(cache, client)

# Equities
equity_returns = provider.get_equity_returns(['AAPL', 'MSFT', ...], s, e)

# Forex
forex_df = provider.get_forex_rates('EUR', 'USD', s, e)

# Backtest with real data
backtest = Backtest(signals=signal)
result = backtest.run_from_dataframe(equity_returns, dates)
```

---

## Error Handling and Fallback Strategy

### Hierarchy of Error Handling

```
Level 1: AlphaVantageClient (API Layer)
    ├─ Network Error
    │   ├─ Retry with exponential backoff (3 attempts)
    │   ├─ Wait: 1s, 2s, 4s
    │   └─ If all fail → Raise NetworkError
    │
    ├─ Rate Limit Error
    │   ├─ RateLimiter.acquire() blocks
    │   ├─ If daily limit exceeded → Raise RateLimitError
    │   └─ DataProvider catches and returns cached
    │
    ├─ API Key Error
    │   └─ Raise immediately (no retry)
    │
    ├─ Symbol Not Found
    │   ├─ Log warning
    │   └─ Raise SymbolNotFoundError
    │
    └─ Malformed Response
        ├─ Log error
        └─ Raise APIError

Level 2: DataProvider (Cache Layer)
    ├─ TRY get from cache
    │   └─ IF hit & valid → RETURN
    │
    ├─ TRY get from API (with rate limiter)
    │   ├─ IF success → cache + RETURN
    │   ├─ IF RateLimitError:
    │   │   ├─ Log "Rate limit, returning stale cache"
    │   │   └─ RETURN cached (even if stale) with warning
    │   └─ IF NetworkError after 3 retries:
    │       ├─ Log "Network error, returning stale cache"
    │       └─ RETURN cached (even if stale) with warning
    │
    └─ IF no cache & API fails:
        └─ Raise DataNotAvailableError

Level 3: Adapter (Conversion Layer)
    ├─ TRY DataProvider.get_equity_prices()
    │   └─ IF success → convert to signal format
    │
    ├─ EXCEPT SymbolNotFoundError:
    │   ├─ Log warning
    │   └─ Return empty DataFrame for this symbol
    │
    └─ EXCEPT (any error):
        ├─ Log error
        └─ Return empty DataFrame (graceful degradation)

Level 4: Backtest (Application Layer)
    ├─ TRY backtest.run() or run_from_dataframe()
    │   └─ IF signal/risk/optimizer fails → log & use equal weights
    │
    └─ Return BacktestResult (even if partial/degraded)
```

### Specific Error Scenarios

**Scenario 1: Rate Limit Exceeded**
```
User tries to backtest 20 symbols, but limit is 25 requests/day.

1. First 5 symbols fetched successfully (5/25 budget)
2. Attempt 6th symbol → AlphaVantageClient detects limit would be exceeded
3. RateLimiter.acquire() blocks
4. After investigation: Daily limit exhausted
5. RateLimitError raised
6. DataProvider catches: Returns last cached data (may be stale)
7. Warning logged: "Rate limit reached, using cached data from [date]"
8. Backtest proceeds with stale data

Result: Backtest runs, but with older data. Better than failure!
```

**Scenario 2: Network Failure During Backtest**
```
DataProvider.get_equity_prices('AAPL', start, end):

1. Cache miss detected
2. AlphaVantageClient attempts API call
3. Network timeout (connection refused)
4. Retry 1: Wait 1s, retry → timeout
5. Retry 2: Wait 2s, retry → timeout
6. Retry 3: Wait 4s, retry → timeout
7. NetworkError raised
8. DataProvider catches:
   - IF cache exists: Return stale cached data with warning
   - ELSE: Raise DataNotAvailableError
9. Adapter catches: Return empty DataFrame for that symbol
10. Backtest continues with remaining symbols

Result: Partial backtest (missing that symbol)
```

**Scenario 3: Invalid Symbol**
```
User requests 'INVALID_TICKER'

1. AlphaVantageClient.get_daily_adjusted('INVALID_TICKER')
2. API response: "symbol does not match any items in our database"
3. SymbolNotFoundError raised
4. DataProvider propagates (can't cache invalid data)
5. Adapter catches: Logs warning, returns empty DataFrame for symbol
6. Backtest ignores that symbol, continues with others

Result: Backtest runs, just skips invalid symbol
```

**Scenario 4: Database Corruption**
```
SQLiteCache operations fail due to corrupt database:

1. SQLiteCache.get_equity_prices() raises DatabaseError
2. DataProvider catches:
   - Logs error
   - Attempts to fetch fresh from API
   - Stores in new database
3. If API also fails: Returns empty DataFrame

Result: Self-healing - fetches fresh data instead of using corrupt cache
```

### Fallback Configuration

```python
# DataProvider configuration for error resilience
provider = DataProvider(
    cache=cache,
    alphavantage=client,
    cache_staleness_days=1  # How old before we refresh
)

# In error handling logic:
# - If rate limit: use cached data (any age)
# - If network error: use cached data (any age)
# - If symbol not found: skip that symbol
# - If database error: fetch fresh (or fail gracefully)

# User can configure acceptable staleness:
# provider = DataProvider(cache, client, cache_staleness_days=7)  # Weekly refresh
# provider = DataProvider(cache, client, cache_staleness_days=30)  # Monthly refresh
```

---

## Testing Strategy

### Unit Tests (No External Dependencies)

**File**: `/home/user/ARBS/tests/unit/data/test_sqlite_cache.py`
```
Test Coverage:
- Initialization & schema creation ✓
- Table creation (idempotent) ✓
- CRUD operations (create, read, update, delete) ✓
- Uniqueness constraints ✓
- Foreign key relationships ✓
- Index performance ✓
- Date range queries ✓
- Cache coverage checks ✓
- Staleness determination ✓
- Cache statistics ✓
- Cleanup operations ✓
- Concurrent access (WAL mode) ✓
- Migration application ✓

Target: 25-30 tests
```

**File**: `/home/user/ARBS/tests/unit/data/test_rate_limiter.py`
```
Test Coverage:
- Initialization ✓
- can_make_request() - basic cases ✓
- acquire() - blocking behavior ✓
- wait_time() - calculation ✓
- Rate limits enforced (5/min, 25/day) ✓
- Sliding window logic ✓
- Cleanup of old requests ✓
- Edge cases (midnight crossing, etc.) ✓

Target: 15-20 tests
```

**File**: `/home/user/ARBS/tests/unit/data/test_alphavantage_client.py`
```
Test Coverage:
- Initialization ✓
- Mock API responses ✓
- Response parsing (daily adjusted) ✓
- Error handling (bad key, invalid symbol) ✓
- Rate limiting integration ✓
- Retry logic with backoff ✓
- DataFrame conversion ✓
- Edge cases (missing fields, etc.) ✓

Target: 20-25 tests (mostly mocked)
```

**File**: `/home/user/ARBS/tests/unit/data/test_data_provider.py`
```
Test Coverage:
- Initialization ✓
- Cache hit scenario ✓
- Cache miss scenario ✓
- Partial cache scenario ✓
- Stale cache refresh ✓
- Force refresh ✓
- Merge logic (cache + API) ✓
- Error scenarios (symbol not found, network) ✓
- Graceful fallback to stale cache ✓
- get_equity_returns() ✓
- get_cache_stats() ✓
- warm_cache() ✓
- clear_cache() ✓

Target: 30-40 tests
```

**File**: `/home/user/ARBS/tests/unit/adapter/test_equity_adapter.py`
```
Test Coverage:
- Initialization ✓
- convert() with mock MDP ✓
- convert() with DataProvider ✓
- get_returns() ✓
- Price → return conversion ✓
- Missing data handling ✓
- Multiple tickers ✓
- Column ordering ✓
- Empty DataFrame handling ✓

Target: 20-25 tests
```

**Total Unit Tests**: ~130-140 tests (fast, <5 seconds)

---

### Integration Tests (With Real API)

**File**: `/home/user/ARBS/tests/integration/test_alphavantage_live.py`
```
Test Coverage (marked @pytest.mark.integration):
- Real API connection ✓
- Fetch AAPL daily prices ✓
- Parse response correctly ✓
- Volume and adjusted close present ✓
- Date range coverage ✓
- Rate limiter in practice ✓

Configuration:
- Uses env var: ALPHAVANTAGE_API_KEY
- Limited to 1-2 symbols to respect rate limits
- Skip if API key not set
- Require 25 requests/day to be available

Target: 5-8 tests (slower, ~30-60 seconds)
```

**File**: `/home/user/ARBS/tests/integration/test_data_provider_live.py`
```
Test Coverage (marked @pytest.mark.integration):
- Cache-first strategy end-to-end ✓
- First request (cache miss) ✓
- Second request (cache hit) ✓
- Partial update scenario ✓
- Force refresh ✓
- Stale data refresh ✓
- Rate limiting in practice ✓
- Error recovery (network simulation) ✓

Target: 10-12 tests
```

**File**: `/home/user/ARBS/tests/integration/test_equity_backtest.py`
```
Test Coverage (end-to-end):
- Full backtest with real equity data ✓
- Cache warm-up → fast backtest ✓
- MultiSignal with equity data ✓
- Performance metrics calculated correctly ✓
- Portfolio returns compound correctly ✓

Target: 3-5 tests (slower, ~2 minutes)
```

**Total Integration Tests**: ~20-25 tests (slower, run separately)

---

### Performance Tests

**File**: `/home/user/ARBS/tests/performance/test_cache_performance.py`
```
Benchmarks:
- Cache retrieval (1 symbol): <10ms ✓
- Cache retrieval (100 symbols): <100ms ✓
- Database insert (1000 records): <500ms ✓
- Database query (100k records): <50ms ✓
- Index effectiveness ✓

Target: Pass all benchmarks
```

**File**: `/home/user/ARBS/tests/performance/test_api_performance.py`
```
Benchmarks:
- Rate limiter overhead: <1ms per acquire() ✓
- API request (first symbol): 12-15 seconds (rate limited) ✓
- API request (cached): <50ms ✓
- Warm cache (10 symbols): ~120 seconds (rate limited) ✓

Target: Verify rate limiting works correctly
```

---

### Test Execution Strategy

```bash
# Fast unit tests (always run)
pytest tests/unit/ -v

# Unit + cache tests
pytest tests/unit/data/ tests/unit/adapter/ -v

# Integration tests (separate, slower)
pytest tests/integration/ -v -m integration

# Performance tests (optional)
pytest tests/performance/ -v --benchmark-only

# Full test suite (CI/CD)
pytest tests/ -v --tb=short

# With coverage report
pytest tests/unit/ --cov=Data --cov=Adapter --cov-report=html
```

**Coverage Target**: >90% for core Data layer

---

### Testing Configuration

**File**: `pytest.ini` (UPDATED)
```ini
[pytest]
markers =
    integration: integration tests (require API key, slower)
    performance: performance benchmarks
    smoke: smoke tests (quick validation)

testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

---

## Configuration Management

### Environment Variables

**File**: `.env.example`
```bash
# AlphaVantage API Configuration
ALPHAVANTAGE_API_KEY=QLGCJCCK8X4ZY6VC
ALPHAVANTAGE_BASE_URL=https://www.alphavantage.co/query

# Database Configuration
MARKET_DATA_DB_PATH=market_data.db
MARKET_DATA_DB_TIMEOUT=30

# Cache Configuration
CACHE_STALENESS_DAYS=1
CACHE_ENABLED=true

# Rate Limiting
ALPHAVANTAGE_MAX_PER_MINUTE=5
ALPHAVANTAGE_MAX_PER_DAY=25

# Error Handling
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY=1.0
RETRY_MAX_DELAY=30.0

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/data_provider.log
```

### Configuration Module

**File**: `/home/user/ARBS/Data/config.py`
```python
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class DataConfig:
    """Data pipeline configuration."""

    # AlphaVantage
    alphavantage_api_key: str
    alphavantage_base_url: str = "https://www.alphavantage.co/query"

    # Database
    db_path: str = "market_data.db"
    db_timeout: int = 30

    # Cache
    cache_staleness_days: int = 1
    cache_enabled: bool = True

    # Rate limiting
    max_requests_per_minute: int = 5
    max_requests_per_day: int = 25

    # Retry logic
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0

    @classmethod
    def from_env(cls):
        """Load configuration from environment variables."""
        return cls(
            alphavantage_api_key=os.getenv(
                "ALPHAVANTAGE_API_KEY",
                "QLGCJCCK8X4ZY6VC"
            ),
            alphavantage_base_url=os.getenv(
                "ALPHAVANTAGE_BASE_URL",
                "https://www.alphavantage.co/query"
            ),
            db_path=os.getenv("MARKET_DATA_DB_PATH", "market_data.db"),
            db_timeout=int(os.getenv("MARKET_DATA_DB_TIMEOUT", "30")),
            cache_staleness_days=int(os.getenv("CACHE_STALENESS_DAYS", "1")),
            cache_enabled=os.getenv("CACHE_ENABLED", "true").lower() == "true",
            max_requests_per_minute=int(
                os.getenv("ALPHAVANTAGE_MAX_PER_MINUTE", "5")
            ),
            max_requests_per_day=int(
                os.getenv("ALPHAVANTAGE_MAX_PER_DAY", "25")
            ),
            retry_max_attempts=int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
            retry_base_delay=float(os.getenv("RETRY_BASE_DELAY", "1.0")),
            retry_max_delay=float(os.getenv("RETRY_MAX_DELAY", "30.0")),
        )

    @classmethod
    def for_testing(cls):
        """Configuration for unit tests (in-memory DB)."""
        return cls(
            alphavantage_api_key="TEST_KEY",
            db_path=":memory:",  # In-memory SQLite
            cache_staleness_days=1,
            cache_enabled=True,
            max_requests_per_minute=5,
            max_requests_per_day=25,
        )
```

---

## Git Ignore Updates

**File**: `.gitignore` (UPDATED)
```
# Market data cache
market_data.db
market_data.db-journal
*.db
*.db-journal

# Environment variables
.env
.env.local

# Logs
logs/
*.log

# Downloaded data
data/raw/
data/cache/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Python
__pycache__/
*.pyc
.pytest_cache/
.coverage
htmlcov/
```

---

## Key Design Decisions

### Decision 1: SQLite vs PostgreSQL

**Choice**: SQLite

**Rationale**:
- Single-user development environment
- No server setup needed
- Sufficient for 100k+ records
- Can migrate to PostgreSQL later
- ACID transactions for data safety
- Concurrent access via WAL mode

**Tradeoff**:
- Won't scale to 100M+ records or multi-user
- Fine for MVP, can upgrade later

---

### Decision 2: Aggressive Caching vs Always-Fresh

**Choice**: Cache-first with configurable staleness

**Rationale**:
- Respects AlphaVantage rate limits (free tier: 25/day)
- Common data (e.g., AAPL) cached after first fetch
- Second backtest on same symbols: instant
- Prevents accidental API exhaustion

**Tradeoff**:
- Data may be up to N days old
- Configurable via cache_staleness_days
- Can force refresh when needed

---

### Decision 3: Graceful Degradation vs Fail-Fast

**Choice**: Graceful degradation (return stale data if API fails)

**Rationale**:
- Better UX: backtest runs even if API down
- Common pattern: "better stale data than no data"
- User can still analyze results
- Warning logged so user knows

**Tradeoff**:
- Results may be based on old data
- User must be aware of freshness

---

### Decision 4: Component Injection vs Hard Dependencies

**Choice**: Dependency injection (loose coupling)

**Rationale**:
- Easy to test (mock SQLiteCache, AlphaVantageClient)
- Can swap implementations (PostgreSQL instead of SQLite)
- Can add new adapters without modifying Backtest
- Follows SOLID principles

**Tradeoff**:
- More boilerplate (passing components around)
- Requires careful initialization

---

## Success Criteria

### Functional
✓ SQLite cache stores/retrieves data correctly
✓ AlphaVantage API client works with rate limiting
✓ DataProvider implements cache-first strategy
✓ EquityAdapter converts prices → returns format
✓ FuturesAdapter backwards compatible
✓ Full backtest runs with real data
✓ All error scenarios handled gracefully

### Performance
✓ Cache retrieval: <10ms
✓ API fetch (first time): 12-15s (rate limited)
✓ API fetch (cached): <50ms
✓ 100 symbols in cache: <500ms query

### Testing
✓ >130 unit tests (fast)
✓ >20 integration tests (slower)
✓ >90% code coverage (Data layer)
✓ All edge cases documented

### Compatibility
✓ MinimalBacktest unchanged
✓ FuturesAdapter backwards compatible
✓ Backtest.run() works as before
✓ Backtest.run_from_dataframe() unchanged
✓ Migration path for users clear

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
1. SQLiteCache implementation + schema
2. RateLimiter implementation
3. Unit tests for both

**Output**: Fast, reliable cache layer

### Phase 2: API Integration (Week 1-2)
4. AlphaVantageClient implementation
5. Error handling + retry logic
6. Integration tests with real API

**Output**: Working API client with rate limiting

### Phase 3: Unified Interface (Week 2)
7. DataProvider implementation
8. Cache-first strategy implementation
9. Comprehensive tests

**Output**: Unified data interface

### Phase 4: Backtest Integration (Week 2-3)
10. EquityAdapter implementation
11. FuturesAdapter backwards-compatible update
12. Integration tests with Backtest

**Output**: Real data flows through Backtest

### Phase 5: Documentation & Examples (Week 3)
13. Setup guide
14. API reference
15. Working examples
16. Troubleshooting guide

**Output**: Users can self-serve

### Phase 6: Validation (Week 3-4)
17. Real backtest with real data
18. Performance benchmarking
19. Stress testing (cache size, API limits)

**Output**: Production-ready system

---

## Summary

This architecture provides:

1. **Cache-first data pipeline**: Never hit API unnecessarily
2. **Graceful degradation**: Works even when API down
3. **Zero breaking changes**: Existing code continues working
4. **Flexible integration**: Component injection for testing
5. **Comprehensive testing**: Unit + integration + performance
6. **Clear error handling**: User knows what failed and why
7. **Scalable design**: Can add PostgreSQL, Quandl, Yahoo Finance later

The system is designed for **minimal initial complexity** while remaining **extensible for future needs**.

---

## Appendix: Example Code Snippets

### Example 1: Backtest with Real Equity Data (Simplest)

```python
from datetime import date
from Data.DataProvider import DataProvider
from Data.Cache.SQLiteCache import SQLiteCache
from Data.Providers.AlphaVantageClient import AlphaVantageClient
from Adapter.EquityAdapter import EquityAdapter
from Backtest.Backtest import Backtest
from Signals.Futures.MomentumSignal import MomentumSignal

# Setup (one-time)
cache = SQLiteCache()
client = AlphaVantageClient(api_key="QLGCJCCK8X4ZY6VC")
provider = DataProvider(cache, client)
adapter = EquityAdapter(mdp=None, data_provider=provider)

# Get returns (with caching)
symbols = ['AAPL', 'MSFT', 'GOOGL']
returns_df = adapter.get_returns(
    symbols=symbols,
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31)
)

# Run backtest
backtest = Backtest(signals=MomentumSignal(lookback=20))
result = backtest.run_from_dataframe(
    returns_df=returns_df,
    dates=[date(2024, 3, 31), date(2024, 6, 30), date(2024, 12, 31)]
)

print(f"Sharpe: {result.sharpe_ratio:.2f}")
print(f"Return: {result.total_return:.2%}")
```

### Example 2: Cache Warm-up Before Backtests

```python
# Warm cache once with many symbols
symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', ...]
stats = provider.warm_cache(
    symbols=symbols,
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31)
)

print(f"Cached {stats['cached_records']} records")
print(f"Used {stats['api_requests']} API requests")
print(f"Failed: {stats['failed']}")

# Now all subsequent backtests use cache (fast)
for backtest_params in all_strategies:
    # This uses cache, no API calls
    result = run_backtest_with_params(**backtest_params)
```

### Example 3: Backwards Compatibility

```python
# Old code still works (uses mock data)
from MDP import MockMDP
from Adapter.FuturesAdapter import FuturesAdapter
from Backtest.MinimalBacktest import MinimalBacktest

mdp = MockMDP()
backtest = MinimalBacktest(mdp)
result = backtest.run(contracts=['SFRZ4'], dates=[...])
```

---

**Created**: 2025-11-14
**Status**: Ready for Implementation
**Next Step**: Execute Phase 1 (SQLiteCache + RateLimiter)
