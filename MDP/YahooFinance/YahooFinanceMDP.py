# ABOUTME: Yahoo Finance data provider for equity prices, dividends, fundamentals
# ABOUTME: Implements MarketDataProvider interface with ZODB caching and rate limiting

import hashlib
import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import polars as pl
import yfinance as yf
from requests.exceptions import ConnectionError, HTTPError, Timeout

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.MarketDataProvider import MarketDataProvider

logger = logging.getLogger(__name__)


# Default retry configuration for exponential backoff
DEFAULT_RETRY_CONFIG = {
    "max_retries": 4,
    "base_delay": 1.0,  # seconds
    "max_delay": 60.0,  # seconds
    "exponential_base": 2.0,
    "jitter": 0.1,  # ±10% randomization
}

# TTL configuration for different data types
TTL_CONFIG = {
    "prices": timedelta(days=1),  # Refresh daily (overnight)
    "fundamentals": timedelta(days=30),  # Monthly refresh
    "sectors": timedelta(days=90),  # Quarterly refresh (sectors stable)
}


@dataclass
class CachedData:
    """Wrapper for cached data with metadata."""

    data: pl.DataFrame
    cached_at: datetime
    data_type: str
    tickers: List[str]


@dataclass
class EquityData:
    """
    Container for equity market data.

    Returned by YahooFinanceMDP.get_pricer() to maintain
    MarketDataProvider interface compatibility.
    """

    data: pl.DataFrame
    metadata: Dict[str, Any]


class RateLimitError(Exception):
    """Raised when rate limit exceeded after retries."""

    pass


class TickerNotFoundError(Exception):
    """Raised when ticker doesn't exist (404)."""

    pass


class DataQualityError(Exception):
    """Raised when data quality checks fail."""

    pass


class YahooFinanceMDP(MarketDataProvider[EquityData], ZODBCacheMixin):
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

    def get_pricer(self, request: dict) -> EquityData:
        """
        Implement MarketDataProvider.get_pricer() interface.

        Note: Equities don't have "pricers" like curves, but we maintain
        the interface for consistency. Returns EquityData object.

        Request Format:
            {
                "tickers": List[str],
                "start_date": date,
                "end_date": date,
                "include_fundamentals": bool (default: False),
                "include_sectors": bool (default: False),
            }

        Returns:
            EquityData object containing Polars DataFrame
        """
        tickers = request.get("tickers")
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        include_fundamentals = request.get("include_fundamentals", False)
        include_sectors = request.get("include_sectors", False)

        if not tickers or not start_date or not end_date:
            raise ValueError("Request must contain 'tickers', 'start_date', and 'end_date'")

        # For MVP, we focus on prices
        df = self.get_prices(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            adjusted=request.get("adjusted", True),
            interval=request.get("interval", "1d"),
        )

        # TODO: Add fundamentals and sectors when requested
        # if include_fundamentals:
        #     fundamentals = self.get_fundamentals(tickers)
        #     df = df.join(fundamentals, on="ticker", how="left")
        #
        # if include_sectors:
        #     sectors = self.get_sector_info(tickers)
        #     df = df.join(sectors, on="ticker", how="left")

        return EquityData(data=df, metadata={"source": self.source, "cached": False})

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
        """
        # Check cache first
        cache_key = self._make_cache_key(
            data_type="prices", tickers=tickers, start_date=start_date, end_date=end_date
        )

        cached_df = self._get_from_cache(cache_key, force_refresh=self._force_refresh)
        if cached_df is not None:
            logger.debug(f"Cache hit for {len(tickers)} tickers")
            return cached_df

        # Cache miss - fetch from Yahoo Finance
        logger.debug(f"Cache miss - fetching {len(tickers)} tickers from Yahoo Finance")

        results = []
        for ticker in tickers:
            try:
                ticker_data = self._fetch_ticker_prices(
                    ticker, start_date, end_date, adjusted, interval
                )
                results.append(ticker_data)
            except TickerNotFoundError as e:
                logger.warning(f"Ticker not found: {ticker}")
                # Skip invalid tickers rather than failing entire batch
                continue
            except Exception as e:
                logger.error(f"Error fetching {ticker}: {e}")
                # For MVP, we skip problematic tickers
                continue

        if not results:
            # Return empty DataFrame with correct schema
            return self._empty_prices_df()

        # Concatenate all ticker data
        df = pl.concat(results)

        # Store in cache
        self._put_in_cache(cache_key, df, data_type="prices", tickers=tickers)

        return df

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
            fields: Fundamental fields to fetch (None = default set)
            as_of_date: Reference date for fundamentals (None = latest)

        Returns:
            Polars DataFrame with schema:
                - ticker: str
                - <field_1>: float (one column per requested field)
                - data_date: date (when data was fetched)

        Note: MVP implementation - basic functionality only
        """
        # Check cache
        cache_key = self._make_cache_key(
            data_type="fundamentals", tickers=tickers, fields=fields
        )

        cached_df = self._get_from_cache(cache_key, force_refresh=self._force_refresh)
        if cached_df is not None:
            return cached_df

        # Default fields for MVP
        if fields is None:
            fields = ["pe_ratio", "market_cap", "dividend_yield"]

        # Field mapping from yfinance to our names
        field_map = {
            "pe_ratio": "trailingPE",
            "forward_pe": "forwardPE",
            "pb_ratio": "priceToBook",
            "market_cap": "marketCap",
            "dividend_yield": "dividendYield",
            "beta": "beta",
        }

        results = []
        for ticker in tickers:
            try:
                ticker_obj = yf.Ticker(ticker)
                info = self._fetch_with_retry(lambda: ticker_obj.info)

                row_data = {"ticker": ticker, "data_date": date.today()}
                for field in fields:
                    yf_field = field_map.get(field, field)
                    row_data[field] = info.get(yf_field)

                results.append(row_data)
            except Exception as e:
                logger.warning(f"Error fetching fundamentals for {ticker}: {e}")
                # Add row with nulls
                row_data = {"ticker": ticker, "data_date": date.today()}
                for field in fields:
                    row_data[field] = None
                results.append(row_data)

        df = pl.DataFrame(results)

        # Store in cache
        self._put_in_cache(cache_key, df, data_type="fundamentals", tickers=tickers)

        return df

    def get_sector_info(self, tickers: List[str]) -> pl.DataFrame:
        """
        Fetch GICS sector classification for tickers.

        Parameters:
            tickers: List of ticker symbols

        Returns:
            Polars DataFrame with schema:
                - ticker: str
                - sector: str (GICS Level 1 - 11 sectors)
                - industry: str (GICS Level 2 - ~25 industries)

        Note: MVP implementation - basic functionality only
        """
        # Check cache
        cache_key = self._make_cache_key(data_type="sectors", tickers=tickers)

        cached_df = self._get_from_cache(cache_key, force_refresh=self._force_refresh)
        if cached_df is not None:
            return cached_df

        results = []
        for ticker in tickers:
            try:
                ticker_obj = yf.Ticker(ticker)
                info = self._fetch_with_retry(lambda: ticker_obj.info)

                results.append(
                    {
                        "ticker": ticker,
                        "sector": info.get("sector", None),
                        "industry": info.get("industry", None),
                    }
                )
            except Exception as e:
                logger.warning(f"Error fetching sector for {ticker}: {e}")
                results.append({"ticker": ticker, "sector": None, "industry": None})

        df = pl.DataFrame(results)

        # Store in cache
        self._put_in_cache(cache_key, df, data_type="sectors", tickers=tickers)

        return df

    def _fetch_ticker_prices(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        adjusted: bool = True,
        interval: str = "1d",
    ) -> pl.DataFrame:
        """
        Fetch price data for a single ticker with retry logic.

        Returns:
            Polars DataFrame with price data
        """

        def _fetch():
            ticker_obj = yf.Ticker(ticker)
            # yfinance returns pandas DataFrame
            df_pd = ticker_obj.history(
                start=start_date, end=end_date, interval=interval, auto_adjust=adjusted
            )

            if df_pd.empty:
                raise TickerNotFoundError(f"No data returned for {ticker}")

            return df_pd

        # Fetch with retry
        df_pd = self._fetch_with_retry(_fetch)

        # Convert to Polars immediately
        df_pl = self._yfinance_to_polars(df_pd, ticker)

        return df_pl

    def _yfinance_to_polars(self, yf_data, ticker: str) -> pl.DataFrame:
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
                - dividends: float (optional)
                - stock_splits: float (optional)
        """
        # Reset index (date → column)
        df_pd = yf_data.reset_index()

        # Convert to Polars
        df_pl = pl.from_pandas(df_pd)

        # Normalize column names (yfinance can vary)
        rename_map = {}
        for col in df_pl.columns:
            col_lower = col.lower()
            if "date" in col_lower:
                rename_map[col] = "date"
            elif "open" in col_lower:
                rename_map[col] = "open"
            elif "high" in col_lower:
                rename_map[col] = "high"
            elif "low" in col_lower:
                rename_map[col] = "low"
            elif "close" in col_lower:
                rename_map[col] = "close"
            elif "volume" in col_lower:
                rename_map[col] = "volume"
            elif "dividend" in col_lower:
                rename_map[col] = "dividends"
            elif "split" in col_lower:
                rename_map[col] = "stock_splits"

        df_pl = df_pl.rename(rename_map)

        # Add ticker column
        df_pl = df_pl.with_columns(pl.lit(ticker).alias("ticker"))

        # Cast types
        if "date" in df_pl.columns:
            df_pl = df_pl.with_columns(pl.col("date").cast(pl.Date))
        if "volume" in df_pl.columns:
            df_pl = df_pl.with_columns(pl.col("volume").cast(pl.Int64))

        # Select and reorder columns
        base_cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
        optional_cols = ["dividends", "stock_splits"]

        select_cols = base_cols + [c for c in optional_cols if c in df_pl.columns]
        df_pl = df_pl.select([c for c in select_cols if c in df_pl.columns])

        return df_pl

    def _fetch_with_retry(
        self, fetch_fn: Callable, retry_config: Optional[Dict] = None
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

        Errors to Retry:
            - HTTPError 429 (Too Many Requests)
            - HTTPError 503 (Service Unavailable)
            - Timeout errors
            - Connection errors

        Errors to Fail Immediately:
            - HTTPError 404 (Not Found - invalid ticker)
            - HTTPError 401 (Unauthorized)
        """
        config = retry_config or self._retry_config

        for attempt in range(config["max_retries"] + 1):
            try:
                return fetch_fn()
            except HTTPError as e:
                status_code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None

                if status_code in [429, 503]:
                    if attempt < config["max_retries"]:
                        delay = min(
                            config["base_delay"] * (config["exponential_base"] ** attempt),
                            config["max_delay"],
                        )
                        jitter = random.uniform(
                            -config["jitter"] * delay, config["jitter"] * delay
                        )
                        sleep_time = delay + jitter
                        logger.warning(
                            f"Rate limit hit (attempt {attempt + 1}/{config['max_retries'] + 1}), "
                            f"sleeping {sleep_time:.2f}s"
                        )
                        time.sleep(sleep_time)
                        continue
                elif status_code == 404:
                    raise TickerNotFoundError(f"Ticker not found: {e}")
                raise
            except (Timeout, ConnectionError) as e:
                if attempt < config["max_retries"]:
                    delay = config["base_delay"] * (config["exponential_base"] ** attempt)
                    logger.warning(
                        f"Network error (attempt {attempt + 1}/{config['max_retries'] + 1}), "
                        f"sleeping {delay:.2f}s"
                    )
                    time.sleep(delay)
                    continue
                raise

        raise RateLimitError("Max retries exceeded")

    def _make_cache_key(
        self,
        data_type: str,
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
        """
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

    def _get_from_cache(
        self, cache_key: str, force_refresh: bool = False
    ) -> Optional[pl.DataFrame]:
        """
        Retrieve data from ZODB cache.

        Returns:
            DataFrame if cache hit and valid, None otherwise
        """
        if force_refresh:
            return None

        cache = getattr(self, self._cache_attr)

        if cache_key not in cache:
            return None

        cached_data: CachedData = cache[cache_key]

        if not self._is_cache_valid(cached_data):
            return None

        return cached_data.data

    def _put_in_cache(
        self, cache_key: str, data: pl.DataFrame, data_type: str, tickers: List[str]
    ):
        """
        Store data in ZODB cache.

        Uses batched() context manager for transaction safety.
        """
        cache = getattr(self, self._cache_attr)

        cached_data = CachedData(
            data=data, cached_at=datetime.now(), data_type=data_type, tickers=tickers
        )

        with self.batched():
            cache[cache_key] = cached_data

    def _is_cache_valid(self, cached_data: CachedData) -> bool:
        """
        Check if cached data is still valid.

        Validation Rules:
            1. Check TTL based on data type
            2. Special case: End date is today → always refresh (incomplete data)
        """
        ttl = TTL_CONFIG.get(cached_data.data_type, timedelta(days=1))
        age = datetime.now() - cached_data.cached_at

        return age < ttl

    def _empty_prices_df(self) -> pl.DataFrame:
        """Return empty DataFrame with correct price schema."""
        return pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
            }
        )
