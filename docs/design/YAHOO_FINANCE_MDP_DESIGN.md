# Yahoo Finance MDP Design Specification

**Author**: AGENT-03
**Date**: 2025-11-11
**Status**: Design Complete
**Parent Plan**: `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 1)

---

## Executive Summary

This document specifies the Yahoo Finance Market Data Provider (MDP) for equity data in ARBS. The design follows the existing `MarketDataProvider` pattern established by `IRSwapsMDP`, adapted for equity-specific requirements.

**Key Design Principles:**
1. **Polars-native**: NO pandas in return types (internal use only for yfinance compatibility)
2. **ZODB caching**: Persistent cache following `ZODBCacheMixin` pattern
3. **Rate limit resilience**: Exponential backoff, batch requests, aggressive caching
4. **Data quality**: Outlier detection, gap filling, staleness checks
5. **Sector support**: GICS Level 1 classification (11 sectors)

---

## 1. API Interface Specification

### 1.1 Class Structure

```python
# ABOUTME: Yahoo Finance data provider for equity prices, dividends, fundamentals
# ABOUTME: Implements MarketDataProvider interface with ZODB caching and rate limiting

from typing import List, Optional, Dict, Any
from datetime import date, timedelta
import polars as pl
import yfinance as yf
from MDP.MarketDataProvider import MarketDataProvider
from Caching.ZODBCacheMixin import ZODBCacheMixin

class YahooFinanceMDP(MarketDataProvider, ZODBCacheMixin):
    """
    Yahoo Finance market data provider for equities.

    Provides:
        - Price history (OHLCV)
        - Dividend/split adjustments
        - Fundamental data (P/E, ROE, etc.)
        - GICS sector classification

    Caching:
        - ZODB backend (persistent)
        - TTL-based expiration (soft)
        - Per-ticker + per-batch caching

    Rate Limiting:
        - Exponential backoff on 429 errors
        - Batch requests (max 100 tickers)
        - Request throttling (configurable)
    """

    def __init__(
        self,
        source: str = "yahoo_finance",
        cache_name: str = "yahoo_finance_cache",
        use_btree: bool = True,
        force_refresh: bool = False,
        **kwargs: Any,
    ):
        """
        Initialize Yahoo Finance MDP.

        Parameters:
            source: Data source identifier (default: "yahoo_finance")
            cache_name: ZODB cache identifier
            use_btree: Use BTree for cache (recommended for large datasets)
            force_refresh: Bypass cache (for debugging/refresh)
            **kwargs: Additional config (batch_size, retry_config, etc.)
        """
        MarketDataProvider.__init__(self, source=source, **kwargs)
        ZODBCacheMixin.__init__(self, use_btree=use_btree, force_refresh=force_refresh)

        self._cache_attr = cache_name
        self._cache_path = self.default_cache_path(cache_name)
        self._batch_size = kwargs.get("batch_size", 100)
        self._retry_config = kwargs.get("retry_config", DEFAULT_RETRY_CONFIG)

        # Open ZODB cache
        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._cache_path)
```

### 1.2 Core Methods

#### 1.2.1 Price Data

```python
def get_prices(
    self,
    tickers: List[str],
    start_date: date,
    end_date: date,
    adjusted: bool = True,
    interval: str = "1d",
) -> pl.DataFrame:
    """
    Fetch historical price data for tickers.

    Parameters:
        tickers: List of ticker symbols (e.g., ["AAPL", "MSFT"])
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        adjusted: Adjust for splits/dividends (default: True)
        interval: Data frequency ("1d", "1h", "1m")

    Returns:
        Polars DataFrame with schema:
            - ticker: str
            - date: date (or datetime for intraday)
            - open: float
            - high: float
            - low: float
            - close: float
            - volume: int64
            - dividends: float (if adjusted=True)
            - stock_splits: float (if adjusted=True)

    Raises:
        RateLimitError: If rate limit exceeded after retries
        DataQualityError: If data has >20% missing values

    Performance:
        - Cache hit: <0.5 sec (100 tickers)
        - Cache miss: <5 sec (100 tickers, network dependent)

    Example:
        >>> mdp = YahooFinanceMDP()
        >>> prices = mdp.get_prices(
        ...     tickers=["AAPL", "MSFT"],
        ...     start_date=date(2024, 1, 1),
        ...     end_date=date(2024, 12, 31),
        ... )
        >>> assert isinstance(prices, pl.DataFrame)
        >>> assert "ticker" in prices.columns
    """
    # Implementation details in Section 3 (Caching Strategy)
    pass
```

#### 1.2.2 Fundamental Data

```python
def get_fundamentals(
    self,
    tickers: List[str],
    fields: Optional[List[str]] = None,
    as_of_date: Optional[date] = None,
) -> pl.DataFrame:
    """
    Fetch fundamental data for tickers.

    Parameters:
        tickers: List of ticker symbols
        fields: Fundamental fields to fetch (None = all available)
        as_of_date: Reference date for fundamentals (None = latest)

    Available Fields:
        Financial Metrics:
            - pe_ratio: Price-to-earnings ratio (trailing 12 months)
            - forward_pe: Forward P/E ratio
            - pb_ratio: Price-to-book ratio
            - ps_ratio: Price-to-sales ratio
            - peg_ratio: PEG ratio (P/E / growth)

        Profitability:
            - roe: Return on equity (%)
            - roa: Return on assets (%)
            - profit_margin: Net profit margin (%)
            - operating_margin: Operating margin (%)

        Balance Sheet:
            - debt_to_equity: Debt-to-equity ratio
            - current_ratio: Current ratio
            - quick_ratio: Quick ratio
            - book_value: Book value per share

        Dividends:
            - dividend_yield: Dividend yield (%)
            - payout_ratio: Dividend payout ratio (%)
            - dividend_rate: Annual dividend per share

        Other:
            - beta: Beta vs market (5-year)
            - market_cap: Market capitalization (USD)
            - shares_outstanding: Shares outstanding

    Returns:
        Polars DataFrame with schema:
            - ticker: str
            - <field_1>: float (one column per requested field)
            - <field_2>: float
            - ...
            - data_date: date (when data was fetched)

    Missing Data Handling:
        - Missing fields → null
        - If >50% of fields missing for a ticker → log warning
        - Use sector median imputation (optional, see Section 5)

    Example:
        >>> mdp = YahooFinanceMDP()
        >>> fundamentals = mdp.get_fundamentals(
        ...     tickers=["AAPL", "MSFT"],
        ...     fields=["pe_ratio", "roe", "dividend_yield"],
        ... )
        >>> assert "pe_ratio" in fundamentals.columns
    """
    pass
```

#### 1.2.3 Sector Classification

```python
def get_sector_info(
    self,
    tickers: List[str],
) -> pl.DataFrame:
    """
    Fetch GICS sector classification for tickers.

    Parameters:
        tickers: List of ticker symbols

    Returns:
        Polars DataFrame with schema:
            - ticker: str
            - sector: str (GICS Level 1 - 11 sectors)
            - industry: str (GICS Level 2 - ~25 industries)
            - industry_group: str (GICS Level 3 - optional)

    GICS Level 1 Sectors (11 total):
        10 - Energy
        15 - Materials
        20 - Industrials
        25 - Consumer Discretionary
        30 - Consumer Staples
        35 - Health Care
        40 - Financials
        45 - Information Technology
        50 - Communication Services
        55 - Utilities
        60 - Real Estate

    Caching:
        - TTL: 90 days (sectors change infrequently)
        - Stored in separate ZODB key space

    Example:
        >>> mdp = YahooFinanceMDP()
        >>> sectors = mdp.get_sector_info(["AAPL", "JPM"])
        >>> assert sectors.filter(pl.col("ticker") == "AAPL")["sector"][0] == "Information Technology"
        >>> assert sectors.filter(pl.col("ticker") == "JPM")["sector"][0] == "Financials"
    """
    pass
```

#### 1.2.4 Unified Fetch (Recommended)

```python
def get_equity_data(
    self,
    tickers: List[str],
    start_date: date,
    end_date: date,
    include_fundamentals: bool = True,
    include_sectors: bool = True,
    fundamental_fields: Optional[List[str]] = None,
) -> pl.DataFrame:
    """
    Unified method: Fetch prices + fundamentals + sectors.

    This is the recommended entry point for most use cases.
    Combines get_prices(), get_fundamentals(), get_sector_info()
    with intelligent caching and minimal API calls.

    Parameters:
        tickers: List of ticker symbols
        start_date: Start date for price history
        end_date: End date for price history
        include_fundamentals: Include fundamental data (default: True)
        include_sectors: Include sector classification (default: True)
        fundamental_fields: Fields to fetch (None = default set)

    Returns:
        Polars DataFrame with schema:
            Price columns:
                - ticker: str
                - date: date
                - open, high, low, close, volume: float/int64

            Fundamental columns (if include_fundamentals=True):
                - pe_ratio, roe, dividend_yield, etc.: float

            Sector columns (if include_sectors=True):
                - sector: str
                - industry: str

    Performance:
        - Cache hit: <1 sec (100 tickers)
        - Cache miss: <10 sec (100 tickers, 1 year history)

    Example:
        >>> mdp = YahooFinanceMDP()
        >>> data = mdp.get_equity_data(
        ...     tickers=["AAPL", "MSFT", "JPM"],
        ...     start_date=date(2024, 1, 1),
        ...     end_date=date(2024, 12, 31),
        ... )
        >>> assert set(data.columns) >= {
        ...     "ticker", "date", "close", "volume",
        ...     "pe_ratio", "roe", "sector"
        ... }
    """
    pass
```

### 1.3 Compatibility with MarketDataProvider

```python
def get_pricer(self, request: dict) -> Any:
    """
    Implement MarketDataProvider.get_pricer() interface.

    Note: Equities don't have "pricers" like curves, but we maintain
    the interface for consistency. Returns EquityData object.

    Request Format:
        {
            "tickers": List[str],
            "start_date": date,
            "end_date": date,
            "include_fundamentals": bool (default: True),
            "include_sectors": bool (default: True),
        }

    Returns:
        EquityData object containing Polars DataFrame
    """
    tickers = request.pop("tickers")
    start_date = request.pop("start_date")
    end_date = request.pop("end_date")

    df = self.get_equity_data(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        **request,
    )

    return EquityData(data=df, metadata={"source": self.source})
```

---

## 2. Rate Limiting Strategy

### 2.1 Yahoo Finance Rate Limits (2025)

**Observed Behavior (Unofficial):**
- No official API documentation (yfinance scrapes web pages)
- Dynamic rate limiting by Yahoo's anti-scraping defenses
- 429 "Too Many Requests" errors common in 2025
- Limits vary by IP, time of day, request pattern

**Conservative Estimates:**
- ~2,000 requests/hour (safe threshold)
- ~48,000 requests/day (daily limit)
- Burst limit: ~100 requests/minute (then throttled)

**Triggers for Rate Limiting:**
- Rapid sequential requests from same IP
- Large batch requests (>200 tickers)
- Repeated requests for same ticker (without caching)
- Requests during peak hours (9:30 AM - 4:00 PM ET)

### 2.2 Mitigation Strategies

#### 2.2.1 Batch Requests

```python
def _batch_tickers(self, tickers: List[str], batch_size: int = 100) -> List[List[str]]:
    """
    Split tickers into batches for API calls.

    Yahoo Finance downloads can handle ~100 tickers per call.
    Larger batches risk timeouts or rate limits.

    Parameters:
        tickers: Full list of tickers
        batch_size: Max tickers per batch (default: 100)

    Returns:
        List of ticker batches

    Example:
        >>> tickers = ["AAPL", "MSFT", ...] * 50  # 100 tickers
        >>> batches = mdp._batch_tickers(tickers, batch_size=100)
        >>> assert len(batches) == 1
        >>> assert len(batches[0]) == 100
    """
    return [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
```

#### 2.2.2 Exponential Backoff

```python
DEFAULT_RETRY_CONFIG = {
    "max_retries": 4,
    "base_delay": 1.0,  # seconds
    "max_delay": 60.0,  # seconds
    "exponential_base": 2.0,
    "jitter": 0.1,  # ±10% randomization
}

def _fetch_with_retry(
    self,
    fetch_fn: Callable,
    retry_config: Optional[Dict] = None,
) -> Any:
    """
    Execute fetch with exponential backoff on rate limit errors.

    Retry Schedule (default config):
        Attempt 1: Immediate
        Attempt 2: 1.0s delay (+ jitter)
        Attempt 3: 2.0s delay
        Attempt 4: 4.0s delay
        Attempt 5: 8.0s delay
        (max 4 retries = 5 total attempts)

    Backoff Formula:
        delay = min(base_delay * (exponential_base ^ attempt), max_delay)
        delay += random.uniform(-jitter * delay, +jitter * delay)

    Errors to Retry:
        - HTTPError 429 (Too Many Requests)
        - HTTPError 503 (Service Unavailable)
        - Timeout errors
        - Connection errors

    Errors to Fail Immediately:
        - HTTPError 404 (Not Found - invalid ticker)
        - HTTPError 401 (Unauthorized)
        - Data parsing errors
    """
    import time
    import random
    from requests.exceptions import HTTPError, Timeout, ConnectionError

    config = retry_config or self._retry_config

    for attempt in range(config["max_retries"] + 1):
        try:
            return fetch_fn()
        except HTTPError as e:
            if e.response.status_code in [429, 503]:
                if attempt < config["max_retries"]:
                    delay = min(
                        config["base_delay"] * (config["exponential_base"] ** attempt),
                        config["max_delay"],
                    )
                    jitter = random.uniform(-config["jitter"] * delay, config["jitter"] * delay)
                    time.sleep(delay + jitter)
                    continue
            elif e.response.status_code == 404:
                raise TickerNotFoundError(f"Ticker not found: {e}")
            raise
        except (Timeout, ConnectionError) as e:
            if attempt < config["max_retries"]:
                delay = config["base_delay"] * (config["exponential_base"] ** attempt)
                time.sleep(delay)
                continue
            raise

    raise RateLimitError("Max retries exceeded")
```

#### 2.2.3 Request Throttling

```python
from threading import Lock
from time import time, sleep

class RequestThrottler:
    """
    Rate limiter using token bucket algorithm.

    Ensures we don't exceed conservative rate limits:
        - 2,000 requests/hour = ~0.56 requests/second
        - Safe margin: 0.5 requests/second (1 request per 2 seconds)
    """

    def __init__(self, requests_per_second: float = 0.5):
        self.rate = requests_per_second
        self.tokens = 1.0
        self.last_update = time()
        self.lock = Lock()

    def acquire(self):
        """Block until a token is available."""
        with self.lock:
            now = time()
            elapsed = now - self.last_update
            self.tokens = min(1.0, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1.0:
                sleep_time = (1.0 - self.tokens) / self.rate
                sleep(sleep_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0
```

### 2.3 Rate Limit Error Handling

```python
class RateLimitError(Exception):
    """Raised when rate limit exceeded after retries."""
    pass

class TickerNotFoundError(Exception):
    """Raised when ticker doesn't exist (404)."""
    pass

class DataQualityError(Exception):
    """Raised when data quality checks fail."""
    pass
```

---

## 3. Caching Strategy

### 3.1 ZODB Backend

Following the `ZODBCacheMixin` pattern established in ARBS.

**Advantages:**
- Persistent cache across sessions
- No external dependencies (Redis, etc.)
- Efficient for large datasets (BTree support)
- Transaction support (ACID guarantees)
- Already used throughout ARBS

**Cache Structure:**
```
~/.cache/arbs/zodb/dump/
    yahoo_finance_cache.fs       # Main cache database
    yahoo_finance_cache.fs.index # Index file
    yahoo_finance_cache.fs.lock  # Lock file
    yahoo_finance_cache.fs.tmp   # Temp file
```

### 3.2 Cache Key Design

```python
def _make_cache_key(
    self,
    data_type: str,  # "prices", "fundamentals", "sectors"
    tickers: List[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    fields: Optional[List[str]] = None,
) -> str:
    """
    Generate cache key for ZODB storage.

    Key Format:
        {data_type}::{ticker_hash}::{date_range}::{fields_hash}

    Examples:
        prices::aapl_msft::20240101_20241231::*
        fundamentals::aapl::*::pe_roe_div
        sectors::aapl_msft::*::*

    Design Considerations:
        - Short keys (ZODB keys are stored in memory)
        - Deterministic (same inputs → same key)
        - Collision-resistant (use hash for long ticker lists)
    """
    import hashlib

    # Sort tickers for deterministic key
    ticker_str = "_".join(sorted(tickers))

    # Hash if too long (>50 chars)
    if len(ticker_str) > 50:
        ticker_hash = hashlib.sha256(ticker_str.encode()).hexdigest()[:16]
    else:
        ticker_hash = ticker_str.lower()

    # Date range
    if start_date and end_date:
        date_range = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
    else:
        date_range = "*"

    # Fields hash
    if fields:
        fields_str = "_".join(sorted(fields))
        if len(fields_str) > 30:
            fields_hash = hashlib.sha256(fields_str.encode()).hexdigest()[:12]
        else:
            fields_hash = fields_str
    else:
        fields_hash = "*"

    return f"{data_type}::{ticker_hash}::{date_range}::{fields_hash}"
```

### 3.3 Cache TTL (Time-To-Live)

ZODB doesn't have built-in TTL, so we store timestamps and check on retrieval.

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class CachedData:
    """Wrapper for cached data with metadata."""
    data: pl.DataFrame
    cached_at: datetime
    data_type: str
    tickers: List[str]

# TTL configuration
TTL_CONFIG = {
    "prices": timedelta(days=1),        # Refresh daily (overnight)
    "fundamentals": timedelta(days=30), # Monthly refresh
    "sectors": timedelta(days=90),      # Quarterly refresh (sectors stable)
}

def _is_cache_valid(
    self,
    cached_data: CachedData,
    force_refresh: bool = False,
) -> bool:
    """
    Check if cached data is still valid.

    Validation Rules:
        1. force_refresh=True → always invalid
        2. Check TTL based on data type
        3. Special case: End date is today → always refresh (incomplete data)
    """
    if force_refresh:
        return False

    ttl = TTL_CONFIG.get(cached_data.data_type, timedelta(days=1))
    age = datetime.now() - cached_data.cached_at

    return age < ttl
```

### 3.4 Cache Access Pattern

```python
def _get_from_cache(
    self,
    cache_key: str,
    force_refresh: bool = False,
) -> Optional[pl.DataFrame]:
    """
    Retrieve data from ZODB cache.

    Returns:
        DataFrame if cache hit and valid, None otherwise
    """
    cache = getattr(self, self._cache_attr)

    if cache_key not in cache:
        return None

    cached_data: CachedData = cache[cache_key]

    if not self._is_cache_valid(cached_data, force_refresh):
        return None

    return cached_data.data

def _put_in_cache(
    self,
    cache_key: str,
    data: pl.DataFrame,
    data_type: str,
    tickers: List[str],
):
    """
    Store data in ZODB cache.

    Uses batched() context manager for transaction safety.
    """
    cache = getattr(self, self._cache_attr)

    cached_data = CachedData(
        data=data,
        cached_at=datetime.now(),
        data_type=data_type,
        tickers=tickers,
    )

    with self.batched():
        cache[cache_key] = cached_data
```

### 3.5 Cache Strategy by Data Type

| Data Type | TTL | Cache Level | Rationale |
|-----------|-----|-------------|-----------|
| **Prices** | 1 day | Per-ticker + per-batch | Daily EOD data, refresh overnight |
| **Fundamentals** | 30 days | Per-ticker | Quarterly updates, but API may lag |
| **Sectors** | 90 days | Per-ticker | Rarely change (GICS reclassification ~yearly) |
| **Dividends** | 7 days | Per-ticker | Ex-div dates matter, but infrequent |

**Cache Warming:**
- On first run, fetch all S&P 500 constituents
- Store in batch cache for fast retrieval
- Individual ticker caches for incremental updates

**Cache Eviction:**
- No automatic eviction (ZODB persistent)
- Manual cleanup via `clear_cache()` method
- Stale data filtered by TTL check

---

## 4. Error Handling

### 4.1 Error Categories

#### 4.1.1 Network Errors

```python
class NetworkError(Exception):
    """Base class for network-related errors."""
    pass

class RateLimitError(NetworkError):
    """Rate limit exceeded after retries."""
    pass

class TimeoutError(NetworkError):
    """Request timed out."""
    pass

class ConnectionError(NetworkError):
    """Connection to Yahoo Finance failed."""
    pass
```

**Handling:**
- Exponential backoff + retry (up to 4 attempts)
- Log warnings on each retry
- Raise exception after max retries
- Include context (ticker, date range) in error message

#### 4.1.2 Data Errors

```python
class DataError(Exception):
    """Base class for data-related errors."""
    pass

class TickerNotFoundError(DataError):
    """Ticker doesn't exist or is delisted."""
    pass

class MissingDataError(DataError):
    """Expected data not available (e.g., no fundamentals)."""
    pass

class DataQualityError(DataError):
    """Data fails quality checks (outliers, gaps, etc.)."""
    pass
```

**Handling:**
- TickerNotFoundError: Log warning, return null row (don't fail entire batch)
- MissingDataError: Log warning, impute with sector median (if enabled)
- DataQualityError: Log error, raise exception (user should investigate)

#### 4.1.3 Cache Errors

```python
class CacheError(Exception):
    """Base class for cache-related errors."""
    pass

class CacheCorruptionError(CacheError):
    """ZODB cache is corrupted."""
    pass
```

**Handling:**
- Cache miss: Proceed with API fetch (expected)
- Cache corruption: Log error, rebuild cache from API
- Lock errors: Fall back to read-only mode (DemoStorage)

### 4.2 Error Recovery Strategies

#### 4.2.1 Missing Tickers

```python
def _handle_missing_ticker(
    self,
    ticker: str,
    error: Exception,
) -> pl.DataFrame:
    """
    Handle ticker not found (404) or delisted.

    Strategy:
        1. Log warning with ticker and error
        2. Return null row (preserves schema)
        3. Mark ticker as invalid in cache (don't retry)

    Returns:
        DataFrame with null values for all columns
    """
    import logging

    logging.warning(f"Ticker not found: {ticker} ({error})")

    # Cache the failure (don't retry)
    cache_key = self._make_cache_key("invalid_tickers", [ticker])
    self._put_in_cache(cache_key, pl.DataFrame({"ticker": [ticker]}), "invalid_tickers", [ticker])

    # Return null row
    return pl.DataFrame({
        "ticker": [ticker],
        "date": [None],
        "open": [None],
        "high": [None],
        "low": [None],
        "close": [None],
        "volume": [None],
    })
```

#### 4.2.2 Stale Data Detection

```python
def _detect_stale_data(
    self,
    df: pl.DataFrame,
    end_date: date,
    max_staleness_days: int = 7,
) -> bool:
    """
    Detect if data is stale (last date too old).

    Stale Data Indicators:
        1. Last date > 7 business days before end_date
        2. No data in last month (ticker may be delisted)
        3. Data ends on weekend (should be Friday)

    Returns:
        True if stale, False otherwise
    """
    if df.is_empty():
        return True

    last_date = df["date"].max()

    # Check staleness
    if (end_date - last_date).days > max_staleness_days:
        return True

    return False
```

### 4.3 Graceful Degradation

```python
def get_prices(
    self,
    tickers: List[str],
    start_date: date,
    end_date: date,
    on_error: str = "warn",  # "raise", "warn", "skip"
) -> pl.DataFrame:
    """
    Fetch prices with configurable error handling.

    Parameters:
        on_error: Error handling strategy:
            - "raise": Raise exception on any error
            - "warn": Log warning, return partial data
            - "skip": Silently skip failed tickers

    Example (partial failure):
        >>> mdp = YahooFinanceMDP()
        >>> prices = mdp.get_prices(
        ...     tickers=["AAPL", "INVALID_TICKER", "MSFT"],
        ...     start_date=date(2024, 1, 1),
        ...     end_date=date(2024, 12, 31),
        ...     on_error="warn",
        ... )
        # WARNING: Ticker not found: INVALID_TICKER
        >>> assert set(prices["ticker"].unique()) == {"AAPL", "MSFT"}
    """
    results = []

    for ticker in tickers:
        try:
            data = self._fetch_ticker_prices(ticker, start_date, end_date)
            results.append(data)
        except TickerNotFoundError as e:
            if on_error == "raise":
                raise
            elif on_error == "warn":
                logging.warning(f"Ticker not found: {ticker}")
            # "skip": do nothing

    return pl.concat(results) if results else pl.DataFrame()
```

---

## 5. Data Quality Checks

### 5.1 Outlier Detection

```python
def _detect_outliers(
    self,
    df: pl.DataFrame,
    column: str = "close",
    method: str = "iqr",  # "iqr", "zscore", "mad"
    threshold: float = 3.0,
) -> pl.DataFrame:
    """
    Detect outliers in price data.

    Methods:
        IQR (Interquartile Range):
            outlier = (x < Q1 - 1.5*IQR) or (x > Q3 + 1.5*IQR)

        Z-Score:
            outlier = |z-score| > threshold (default: 3.0)

        MAD (Median Absolute Deviation):
            outlier = |x - median| > threshold * MAD

    Returns:
        DataFrame with "is_outlier" column (bool)

    Treatment:
        1. Flag outliers (don't remove automatically)
        2. Log warnings for manual review
        3. Option to interpolate or forward-fill
    """
    if method == "iqr":
        q1 = df[column].quantile(0.25)
        q3 = df[column].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        return df.with_columns(
            ((pl.col(column) < lower) | (pl.col(column) > upper)).alias("is_outlier")
        )

    elif method == "zscore":
        mean = df[column].mean()
        std = df[column].std()
        z_scores = (df[column] - mean) / std

        return df.with_columns(
            (z_scores.abs() > threshold).alias("is_outlier")
        )

    # ... other methods
```

### 5.2 Gap Filling

```python
def _fill_gaps(
    self,
    df: pl.DataFrame,
    method: str = "forward",  # "forward", "linear", "drop"
    max_gap_days: int = 5,
) -> pl.DataFrame:
    """
    Fill missing data gaps.

    Methods:
        forward: Forward-fill (carry last known value)
        linear: Linear interpolation
        drop: Drop rows with missing data

    Parameters:
        max_gap_days: Maximum gap to fill (larger gaps → warning)

    Gap Detection:
        1. Sort by date
        2. Compute date diffs
        3. Identify gaps > 1 business day
        4. Fill if gap <= max_gap_days, warn otherwise

    Example:
        Date       | Close | Filled
        -----------|-------|-------
        2024-01-01 | 100   | 100
        2024-01-02 | (missing) | 100 (forward fill)
        2024-01-03 | 102   | 102
    """
    # Sort by date
    df = df.sort("date")

    # Detect gaps
    date_diffs = df["date"].diff()
    gaps = date_diffs > timedelta(days=1)

    # Warn on large gaps
    large_gaps = gaps & (date_diffs > timedelta(days=max_gap_days))
    if large_gaps.any():
        logging.warning(f"Large data gaps detected (>{max_gap_days} days)")

    # Fill based on method
    if method == "forward":
        return df.with_columns(pl.col("close").forward_fill())
    elif method == "linear":
        return df.with_columns(pl.col("close").interpolate())
    elif method == "drop":
        return df.drop_nulls("close")

    return df
```

### 5.3 Data Validation

```python
def _validate_data(
    self,
    df: pl.DataFrame,
    data_type: str,
    min_coverage: float = 0.8,
) -> None:
    """
    Validate data quality before returning.

    Checks:
        1. Schema validation (required columns present)
        2. Coverage (% of non-null values >= min_coverage)
        3. Date range (covers requested start_date to end_date)
        4. Duplicate dates (should be unique per ticker)
        5. Negative prices (flag as suspicious)

    Raises:
        DataQualityError if validation fails

    Example:
        >>> mdp._validate_data(prices_df, "prices", min_coverage=0.8)
        # Raises if <80% of expected data present
    """
    # Schema check
    required_cols = {
        "prices": {"ticker", "date", "close"},
        "fundamentals": {"ticker", "pe_ratio"},
        "sectors": {"ticker", "sector"},
    }

    if not required_cols[data_type].issubset(df.columns):
        raise DataQualityError(f"Missing required columns: {required_cols[data_type] - set(df.columns)}")

    # Coverage check
    coverage = 1 - df.null_count().sum() / (df.shape[0] * df.shape[1])
    if coverage < min_coverage:
        raise DataQualityError(f"Coverage {coverage:.1%} < {min_coverage:.1%}")

    # Duplicate check (for prices)
    if data_type == "prices":
        duplicates = df.group_by(["ticker", "date"]).count().filter(pl.col("count") > 1)
        if not duplicates.is_empty():
            raise DataQualityError(f"Duplicate dates found: {duplicates}")

    # Price sanity checks
    if "close" in df.columns:
        negative_prices = df.filter(pl.col("close") < 0)
        if not negative_prices.is_empty():
            logging.warning(f"Negative prices detected: {negative_prices}")
```

### 5.4 Sector Median Imputation

```python
def _impute_missing_fundamentals(
    self,
    df: pl.DataFrame,
    sector_col: str = "sector",
    fields_to_impute: Optional[List[str]] = None,
) -> pl.DataFrame:
    """
    Impute missing fundamental data using sector medians.

    Strategy:
        1. Compute median for each field within each sector
        2. Fill missing values with sector median
        3. If sector median also missing, use global median
        4. Log imputation (for transparency)

    Example:
        Ticker | Sector | P/E  | Imputed P/E
        -------|--------|------|-------------
        AAPL   | Tech   | 25.0 | 25.0
        NVDA   | Tech   | null | 24.5 (sector median)
        MSFT   | Tech   | 24.0 | 24.0

    Returns:
        DataFrame with imputed values
    """
    if fields_to_impute is None:
        fields_to_impute = ["pe_ratio", "roe", "dividend_yield", "debt_to_equity"]

    for field in fields_to_impute:
        if field not in df.columns:
            continue

        # Compute sector medians
        sector_medians = df.group_by(sector_col).agg(
            pl.col(field).median().alias(f"{field}_median")
        )

        # Join and fill
        df = df.join(sector_medians, on=sector_col, how="left")

        df = df.with_columns(
            pl.when(pl.col(field).is_null())
            .then(pl.col(f"{field}_median"))
            .otherwise(pl.col(field))
            .alias(field)
        )

        # Drop temp column
        df = df.drop(f"{field}_median")

        # Log imputation count
        imputed_count = df.filter(pl.col(field).is_null()).shape[0]
        if imputed_count > 0:
            logging.info(f"Imputed {imputed_count} missing values for {field}")

    return df
```

---

## 6. Polars-Native Implementation

### 6.1 Conversion from yfinance (pandas) to Polars

```python
def _yfinance_to_polars(
    self,
    yf_data: pd.DataFrame,
    ticker: str,
) -> pl.DataFrame:
    """
    Convert yfinance pandas DataFrame to Polars.

    yfinance Output Format (pandas):
        Index: DatetimeIndex
        Columns: Open, High, Low, Close, Volume, Dividends, Stock Splits
        (or multi-index for multiple tickers)

    Polars Output Format:
        Columns:
            - ticker: str
            - date: date
            - open: float
            - high: float
            - low: float
            - close: float
            - volume: int64
            - dividends: float
            - stock_splits: float

    Notes:
        - yfinance uses pandas internally (no Polars support yet)
        - We convert immediately to Polars (no pandas leakage)
        - Column names normalized to lowercase
    """
    # Reset index (date → column)
    df_pd = yf_data.reset_index()

    # Convert to Polars
    df_pl = pl.from_pandas(df_pd)

    # Normalize column names
    df_pl = df_pl.rename({
        "Date": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Dividends": "dividends",
        "Stock Splits": "stock_splits",
    })

    # Add ticker column
    df_pl = df_pl.with_columns(pl.lit(ticker).alias("ticker"))

    # Cast types
    df_pl = df_pl.with_columns([
        pl.col("date").cast(pl.Date),
        pl.col("volume").cast(pl.Int64),
    ])

    # Reorder columns
    df_pl = df_pl.select([
        "ticker", "date", "open", "high", "low", "close", "volume",
        "dividends", "stock_splits",
    ])

    return df_pl
```

### 6.2 Fundamentals Extraction

```python
def _extract_fundamentals(
    self,
    ticker_obj: yf.Ticker,
    fields: List[str],
) -> Dict[str, float]:
    """
    Extract fundamental data from yfinance Ticker.info.

    yfinance .info Format:
        {
            "trailingPE": 25.3,
            "returnOnEquity": 0.493,
            "dividendYield": 0.0051,
            ...
        }

    Field Mapping:
        ARBS Name → yfinance Key
        ---------    -------------
        pe_ratio → trailingPE, trailingPE (TTM)
        forward_pe → forwardPE
        pb_ratio → priceToBook
        ps_ratio → priceToSalesTrailing12Months
        roe → returnOnEquity (decimal, not %)
        roa → returnOnAssets
        profit_margin → profitMargins
        debt_to_equity → debtToEquity
        dividend_yield → dividendYield (decimal)
        payout_ratio → payoutRatio
        beta → beta
        market_cap → marketCap

    Returns:
        Dict with ARBS field names as keys
    """
    info = ticker_obj.info

    # Field mapping
    field_map = {
        "pe_ratio": "trailingPE",
        "forward_pe": "forwardPE",
        "pb_ratio": "priceToBook",
        "ps_ratio": "priceToSalesTrailing12Months",
        "peg_ratio": "pegRatio",
        "roe": "returnOnEquity",
        "roa": "returnOnAssets",
        "profit_margin": "profitMargins",
        "operating_margin": "operatingMargins",
        "debt_to_equity": "debtToEquity",
        "current_ratio": "currentRatio",
        "quick_ratio": "quickRatio",
        "book_value": "bookValue",
        "dividend_yield": "dividendYield",
        "payout_ratio": "payoutRatio",
        "dividend_rate": "dividendRate",
        "beta": "beta",
        "market_cap": "marketCap",
        "shares_outstanding": "sharesOutstanding",
    }

    result = {}
    for arbs_field in fields:
        yf_field = field_map.get(arbs_field)
        if yf_field:
            result[arbs_field] = info.get(yf_field)

    return result
```

### 6.3 No Pandas in Public API

**Rule**: All public methods return `pl.DataFrame`, NEVER `pd.DataFrame`.

```python
# GOOD ✅
def get_prices(self, ...) -> pl.DataFrame:
    # Internal pandas usage OK (for yfinance compat)
    yf_data = yf.download(...)  # Returns pandas

    # Convert immediately
    pl_data = self._yfinance_to_polars(yf_data, ticker)

    # Return Polars
    return pl_data

# BAD ❌
def get_prices(self, ...) -> pd.DataFrame:
    # NEVER return pandas from public methods!
    return yf.download(...)
```

**Testing:**
```python
def test_polars_native_returns():
    """Ensure all public methods return Polars DataFrames."""
    mdp = YahooFinanceMDP()

    # Test all public methods
    prices = mdp.get_prices(["AAPL"], date(2024, 1, 1), date(2024, 12, 31))
    assert isinstance(prices, pl.DataFrame), "get_prices must return Polars DataFrame"

    fundamentals = mdp.get_fundamentals(["AAPL"])
    assert isinstance(fundamentals, pl.DataFrame), "get_fundamentals must return Polars DataFrame"

    sectors = mdp.get_sector_info(["AAPL"])
    assert isinstance(sectors, pl.DataFrame), "get_sector_info must return Polars DataFrame"
```

---

## 7. Performance Targets

### 7.1 Benchmarks

| Operation | Tickers | Date Range | Target (Cache Miss) | Target (Cache Hit) |
|-----------|---------|------------|---------------------|-------------------|
| get_prices | 10 | 1 year | <2 sec | <0.2 sec |
| get_prices | 100 | 1 year | <5 sec | <1 sec |
| get_prices | 500 | 1 year | <30 sec | <5 sec |
| get_fundamentals | 100 | Latest | <10 sec | <0.5 sec |
| get_sector_info | 500 | N/A | <5 sec | <0.1 sec |
| get_equity_data | 100 | 1 year | <10 sec | <1 sec |

### 7.2 Optimization Strategies

#### 7.2.1 Parallel Fetching

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _fetch_tickers_parallel(
    self,
    tickers: List[str],
    fetch_fn: Callable,
    max_workers: int = 5,
) -> List[pl.DataFrame]:
    """
    Fetch multiple tickers in parallel.

    Parameters:
        max_workers: Max concurrent requests (default: 5)
            Too high → risk of rate limiting
            Too low → slow performance

    Performance:
        Sequential: 100 tickers × 0.5s = 50s
        Parallel (5 workers): 100 tickers / 5 × 0.5s = 10s
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_fn, ticker): ticker for ticker in tickers}

        for future in as_completed(futures):
            ticker = futures[future]
            try:
                data = future.result()
                results.append(data)
            except Exception as e:
                logging.error(f"Failed to fetch {ticker}: {e}")

    return results
```

#### 7.2.2 Batch Caching

```python
def _cache_batch(
    self,
    tickers: List[str],
    data: pl.DataFrame,
):
    """
    Cache both individual tickers AND the full batch.

    Strategy:
        1. Cache full batch (for repeated full queries)
        2. Cache individual tickers (for incremental queries)

    Trade-off:
        - More storage (duplicate data)
        - Faster retrieval (no need to filter batch)
    """
    # Cache full batch
    batch_key = self._make_cache_key("prices", tickers, ...)
    self._put_in_cache(batch_key, data, "prices", tickers)

    # Cache individual tickers
    for ticker in tickers:
        ticker_data = data.filter(pl.col("ticker") == ticker)
        ticker_key = self._make_cache_key("prices", [ticker], ...)
        self._put_in_cache(ticker_key, ticker_data, "prices", [ticker])
```

#### 7.2.3 Lazy Loading

```python
class EquityData:
    """
    Lazy-loading wrapper for equity data.

    Only fetch data when accessed (not at construction).
    Useful for chaining operations without unnecessary fetches.
    """

    def __init__(self, mdp: YahooFinanceMDP, tickers: List[str], ...):
        self._mdp = mdp
        self._tickers = tickers
        self._prices = None
        self._fundamentals = None

    @property
    def prices(self) -> pl.DataFrame:
        """Fetch prices on first access."""
        if self._prices is None:
            self._prices = self._mdp.get_prices(self._tickers, ...)
        return self._prices

    @property
    def fundamentals(self) -> pl.DataFrame:
        """Fetch fundamentals on first access."""
        if self._fundamentals is None:
            self._fundamentals = self._mdp.get_fundamentals(self._tickers, ...)
        return self._fundamentals
```

### 7.3 Performance Testing

```python
import time
from typing import Callable

def benchmark(
    fn: Callable,
    name: str,
    target_seconds: float,
) -> None:
    """
    Benchmark function execution time.

    Example:
        >>> benchmark(
        ...     lambda: mdp.get_prices(["AAPL"], date(2024,1,1), date(2024,12,31)),
        ...     "get_prices (cache miss)",
        ...     target_seconds=2.0,
        ... )
    """
    start = time.time()
    result = fn()
    elapsed = time.time() - start

    status = "PASS" if elapsed < target_seconds else "FAIL"
    print(f"[{status}] {name}: {elapsed:.2f}s (target: {target_seconds:.2f}s)")

    assert elapsed < target_seconds, f"{name} too slow: {elapsed:.2f}s > {target_seconds:.2f}s"
```

---

## 8. Alternative Libraries Evaluation

### 8.1 Library Comparison

| Feature | yfinance | yahoo-fin | yahooquery |
|---------|----------|-----------|------------|
| **Data Source** | Web scraping | Web scraping | Unofficial API |
| **Speed** | Medium | Slow | Fast (async) |
| **Reliability** | Medium (breaks on Yahoo changes) | Low | Medium |
| **Maintenance** | Active (2025) | Active | Active |
| **Batch Support** | Yes (100+ tickers) | Limited | Excellent |
| **Fundamentals** | Via .info (dict) | Via balance_sheet() | Via Ticker.get_modules() |
| **Historical Prices** | Excellent | Good | Excellent |
| **Options Data** | Yes | Yes | Yes |
| **Resilience** | High (scraping-based) | High | Low (API changes break it) |

### 8.2 Recommendation

**Primary**: `yfinance`
- Most resilient (scraping-based, won't break on API changes)
- Well-maintained (active community)
- Good documentation
- Batch support adequate (100 tickers per call)

**Optional Fast Path**: `yahooquery`
- Use for large batch operations (500+ tickers)
- Fallback to yfinance on failure
- Async support for speed

**Not Recommended**: `yahoo-fin`
- Slower than alternatives
- Limited batch support
- More focused on current data (not historical)

### 8.3 Hybrid Implementation (Optional)

```python
def get_prices(
    self,
    tickers: List[str],
    start_date: date,
    end_date: date,
    prefer_yahooquery: bool = False,
) -> pl.DataFrame:
    """
    Fetch prices with optional yahooquery fast path.

    Strategy:
        1. If prefer_yahooquery=True and len(tickers) > 200:
            Try yahooquery (async batch)
        2. If yahooquery fails or unavailable:
            Fall back to yfinance
    """
    if prefer_yahooquery and len(tickers) > 200:
        try:
            from yahooquery import Ticker

            yq_tickers = Ticker(tickers)
            yq_data = yq_tickers.history(start=start_date, end=end_date)

            # Convert to Polars
            return self._yahooquery_to_polars(yq_data)

        except Exception as e:
            logging.warning(f"yahooquery failed, falling back to yfinance: {e}")

    # Default: yfinance
    return self._fetch_with_yfinance(tickers, start_date, end_date)
```

---

## 9. Implementation Checklist

### 9.1 Core Functionality
- [ ] `YahooFinanceMDP` class structure
- [ ] `get_prices()` method
- [ ] `get_fundamentals()` method
- [ ] `get_sector_info()` method
- [ ] `get_equity_data()` (unified method)
- [ ] `get_pricer()` (MarketDataProvider interface)

### 9.2 Caching
- [ ] ZODB integration via `ZODBCacheMixin`
- [ ] Cache key generation
- [ ] TTL validation
- [ ] Batch caching (per-ticker + full batch)
- [ ] Cache warming (S&P 500 constituents)

### 9.3 Rate Limiting
- [ ] Exponential backoff retry logic
- [ ] Request throttler (token bucket)
- [ ] Batch request splitting (100 tickers max)
- [ ] 429 error handling

### 9.4 Error Handling
- [ ] Network error classes
- [ ] Data error classes
- [ ] Graceful degradation (on_error parameter)
- [ ] Missing ticker handling
- [ ] Stale data detection

### 9.5 Data Quality
- [ ] Outlier detection (IQR/Z-score/MAD)
- [ ] Gap filling (forward/linear/drop)
- [ ] Data validation (schema, coverage, duplicates)
- [ ] Sector median imputation

### 9.6 Polars Integration
- [ ] yfinance → Polars conversion
- [ ] Fundamentals extraction (dict → DataFrame)
- [ ] No pandas in public API (enforce via tests)

### 9.7 Performance
- [ ] Parallel fetching (ThreadPoolExecutor)
- [ ] Lazy loading (EquityData wrapper)
- [ ] Performance benchmarks
- [ ] Profile and optimize hot paths

### 9.8 Testing
- [ ] Unit tests (30+ tests)
- [ ] Integration tests with live Yahoo Finance API
- [ ] Cache hit/miss tests
- [ ] Error handling tests
- [ ] Performance tests (benchmarks)
- [ ] Polars-native enforcement tests

### 9.9 Documentation
- [ ] API documentation (docstrings)
- [ ] Usage examples
- [ ] Performance tuning guide
- [ ] Troubleshooting guide (rate limits, etc.)

---

## 10. Future Enhancements (Not MVP)

### 10.1 Advanced Caching

- **Multi-tier cache**: Memory (LRU) → ZODB → API
- **Proactive refresh**: Background task to refresh expiring cache
- **Cache statistics**: Hit rate, miss rate, average fetch time

### 10.2 Data Quality Improvements

- **Corporate actions**: Handle mergers, acquisitions, ticker changes
- **Adjusted data validation**: Verify split adjustments are correct
- **Cross-validation**: Compare Yahoo Finance with other sources (Alpha Vantage, IEX)

### 10.3 Alternative Data Sources

- **Alpha Vantage**: Backup source for fundamentals
- **IEX Cloud**: Real-time data (for live trading)
- **SEC EDGAR**: Official filings (10-K, 10-Q)

### 10.4 Performance Optimization

- **HTTP/2 connection pooling**: Reduce connection overhead
- **Compression**: gzip responses (if Yahoo supports)
- **CDN caching**: Use Yahoo's CDN for static data

---

## 11. References

### 11.1 External Resources

**yfinance Documentation:**
- GitHub: https://github.com/ranaroussi/yfinance
- PyPI: https://pypi.org/project/yfinance/
- Rate Limiting Issues: https://github.com/ranaroussi/yfinance/issues/2125

**Alternative Libraries:**
- yahooquery: https://github.com/dpguthrie/yahooquery
- yahoo-fin: https://theautomatic.net/yahoo_fin-documentation/

**GICS Sector Classification:**
- MSCI GICS: https://www.msci.com/gics

### 11.2 ARBS Internal References

**Existing Patterns:**
- `MDP/MarketDataProvider.py`: Base class interface
- `MDP/IRSwaps/IRSwapsMDP.py`: Reference implementation
- `Caching/ZODBCacheMixin.py`: Caching infrastructure
- `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/_RLCurveCache.py`: Cache example

**Implementation Plan:**
- `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md`: Phase 1 requirements

---

## 12. Appendix

### 12.1 yfinance API Examples

```python
import yfinance as yf

# Single ticker
aapl = yf.Ticker("AAPL")
hist = aapl.history(start="2024-01-01", end="2024-12-31")
info = aapl.info  # Dict with fundamentals

# Multiple tickers (batch)
data = yf.download(
    tickers=["AAPL", "MSFT", "GOOGL"],
    start="2024-01-01",
    end="2024-12-31",
    group_by="ticker",
    threads=True,
)

# Fundamentals
pe_ratio = info.get("trailingPE")
roe = info.get("returnOnEquity")
sector = info.get("sector")
```

### 12.2 GICS Sector Mapping

```python
GICS_SECTORS = {
    10: "Energy",
    15: "Materials",
    20: "Industrials",
    25: "Consumer Discretionary",
    30: "Consumer Staples",
    35: "Health Care",
    40: "Financials",
    45: "Information Technology",
    50: "Communication Services",
    55: "Utilities",
    60: "Real Estate",
}

# S&P 500 sector distribution (approximate)
SECTOR_WEIGHTS = {
    "Information Technology": 0.28,
    "Financials": 0.13,
    "Health Care": 0.13,
    "Consumer Discretionary": 0.11,
    "Communication Services": 0.09,
    "Industrials": 0.08,
    "Consumer Staples": 0.07,
    "Energy": 0.04,
    "Utilities": 0.03,
    "Real Estate": 0.03,
    "Materials": 0.02,
}
```

---

**End of Yahoo Finance MDP Design Specification**
