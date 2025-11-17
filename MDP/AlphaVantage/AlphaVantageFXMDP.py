# ABOUTME: AlphaVantage FX market data provider for spot rates and interest rates
# ABOUTME: Implements MarketDataProvider interface with ZODB caching and rate limiting

import hashlib
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import polars as pl
import requests
from io import StringIO

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.MarketDataProvider import MarketDataProvider

logger = logging.getLogger(__name__)


# Default retry configuration for exponential backoff
DEFAULT_RETRY_CONFIG = {
    "max_retries": 4,
    "base_delay": 2.0,  # seconds
    "max_delay": 120.0,  # seconds
    "exponential_base": 2.0,
    "jitter": 0.1,  # ±10% randomization
}

# TTL configuration for different data types
TTL_CONFIG = {
    "fx_daily": timedelta(days=1),  # Refresh daily
    "fx_intraday": timedelta(hours=1),  # Refresh hourly
    "interest_rates": timedelta(days=7),  # Weekly refresh (central bank rates change slowly)
}

# AlphaVantage API rate limits
# Free tier: 5 API calls per minute, 500 calls per day
# Premium tier: 30 calls per minute, 1200 calls per day
RATE_LIMITS = {
    "free": {"calls_per_minute": 5, "calls_per_day": 500},
    "premium": {"calls_per_minute": 30, "calls_per_day": 1200},
}

# EM FX currency pairs (vs USD)
EM_CURRENCY_PAIRS = {
    "BRL": "USD/BRL",  # Brazilian Real
    "TRY": "USD/TRY",  # Turkish Lira
    "ZAR": "USD/ZAR",  # South African Rand
    "MXN": "USD/MXN",  # Mexican Peso
    "RUB": "USD/RUB",  # Russian Ruble
    "INR": "USD/INR",  # Indian Rupee
    "IDR": "USD/IDR",  # Indonesian Rupiah
    "CLP": "USD/CLP",  # Chilean Peso
    "COP": "USD/COP",  # Colombian Peso
    "ARS": "USD/ARS",  # Argentine Peso
    "THB": "USD/THB",  # Thai Baht
    "PLN": "USD/PLN",  # Polish Zloty
    "HUF": "USD/HUF",  # Hungarian Forint
    "CZK": "USD/CZK",  # Czech Koruna
}

# Central bank policy rates (approximate - need to be updated periodically)
# These are baseline estimates - actual rates should be fetched from economic APIs
DEFAULT_INTEREST_RATES = {
    "BRL": 0.1375,  # Brazil SELIC
    "TRY": 0.2500,  # Turkey CBRT
    "ZAR": 0.0850,  # South Africa SARB
    "MXN": 0.1100,  # Mexico Banxico
    "RUB": 0.1600,  # Russia CBR
    "INR": 0.0650,  # India RBI
    "IDR": 0.0600,  # Indonesia BI
    "CLP": 0.0650,  # Chile BCCh
    "COP": 0.1300,  # Colombia BanRep
    "ARS": 0.4000,  # Argentina BCRA (very high, volatile)
    "THB": 0.0250,  # Thailand BOT
    "PLN": 0.0575,  # Poland NBP
    "HUF": 0.0650,  # Hungary MNB
    "CZK": 0.0475,  # Czechia CNB
    "USD": 0.0550,  # US Fed Funds
}


@dataclass
class CachedFXData:
    """Wrapper for cached FX data with metadata."""

    data: pl.DataFrame
    cached_at: datetime
    data_type: str
    currencies: List[str]


@dataclass
class FXData:
    """
    Container for FX market data.

    Returned by AlphaVantageFXMDP.get_pricer() to maintain
    MarketDataProvider interface compatibility.
    """

    data: pl.DataFrame
    metadata: Dict[str, Any]


class RateLimitError(Exception):
    """Raised when rate limit exceeded after retries."""

    pass


class APIKeyError(Exception):
    """Raised when API key is missing or invalid."""

    pass


class CurrencyNotFoundError(Exception):
    """Raised when currency pair doesn't exist."""

    pass


class DataQualityError(Exception):
    """Raised when data quality checks fail."""

    pass


class AlphaVantageFXMDP(MarketDataProvider[FXData], ZODBCacheMixin):
    """
    AlphaVantage FX market data provider for EM currencies.

    Provides:
        - FX spot rates (daily and intraday)
        - Interest rate data (central bank policy rates)
        - Historical time series for carry trade analysis

    API Documentation:
        - FX Daily: https://www.alphavantage.co/documentation/#fx-daily
        - FX Intraday: https://www.alphavantage.co/documentation/#fx-intraday
        - Interest Rates: Uses default rates (can be extended with FRED API)

    Caching:
        - ZODB backend (persistent)
        - TTL-based expiration (daily for FX, weekly for rates)
        - Per-currency pair caching

    Rate Limiting:
        - Free tier: 5 calls/minute, 500 calls/day
        - Premium tier: 30 calls/minute, 1200 calls/day
        - Exponential backoff on 429 errors
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        source: str = "alphavantage_fx",
        cache_name: str = "alphavantage_fx_cache",
        use_btree: bool = True,
        force_refresh: bool = False,
        tier: str = "free",  # "free" or "premium"
        **kwargs: Any,
    ):
        """
        Initialize AlphaVantage FX MDP.

        Parameters:
            api_key: AlphaVantage API key (get free key at https://www.alphavantage.co/support/#api-key)
                    If None, will try to read from ALPHAVANTAGE_API_KEY env var
            source: Data source identifier (default: "alphavantage_fx")
            cache_name: ZODB cache identifier
            use_btree: Use BTree for cache (recommended for large datasets)
            force_refresh: Bypass cache (for debugging/refresh)
            tier: API tier - "free" or "premium" (affects rate limits)
            **kwargs: Additional config (retry_config, etc.)
        """
        MarketDataProvider.__init__(self, source=source, **kwargs)
        ZODBCacheMixin.__init__(self, use_btree=use_btree, force_refresh=force_refresh)

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv("ALPHAVANTAGE_API_KEY")
        if not self.api_key:
            raise APIKeyError(
                "AlphaVantage API key required. "
                "Get free key at https://www.alphavantage.co/support/#api-key\n"
                "Set via ALPHAVANTAGE_API_KEY env var or pass api_key parameter."
            )

        self._cache_attr = cache_name
        self._cache_path = self.default_cache_path(cache_name)
        self._retry_config = kwargs.get("retry_config", DEFAULT_RETRY_CONFIG)
        self._tier = tier
        self._rate_limits = RATE_LIMITS[tier]

        # Rate limiting state
        self._call_timestamps = []

        # Open ZODB cache
        self.zodb_open_cache(cache_attr=self._cache_attr, path=self._cache_path)

    def get_pricer(self, request: dict) -> FXData:
        """
        Implement MarketDataProvider.get_pricer() interface.

        Request Format:
            {
                "currencies": List[str],  # e.g., ["BRL", "TRY", "MXN"]
                "start_date": date,
                "end_date": date,
                "include_interest_rates": bool (default: True),
                "interval": str (default: "daily")  # "daily" or "intraday"
            }

        Returns:
            FXData object containing Polars DataFrame with schema:
                - currency: str
                - date: date
                - fx_rate: float (spot rate vs USD)
                - interest_rate: float (optional, annual policy rate)
                - usd_rate: float (optional, US policy rate)
        """
        currencies = request.get("currencies")
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        include_interest_rates = request.get("include_interest_rates", True)
        interval = request.get("interval", "daily")

        if not currencies or not start_date or not end_date:
            raise ValueError("Request must contain 'currencies', 'start_date', and 'end_date'")

        # Fetch FX spot rates
        df = self.get_fx_rates(
            currencies=currencies, start_date=start_date, end_date=end_date, interval=interval
        )

        # Add interest rates if requested
        if include_interest_rates:
            rates_df = self.get_interest_rates(currencies=currencies, as_of_date=end_date)
            df = df.join(rates_df, on="currency", how="left")

        return FXData(data=df, metadata={"source": self.source, "tier": self._tier})

    def get_fx_rates(
        self,
        currencies: List[str],
        start_date: date,
        end_date: date,
        interval: str = "daily",
    ) -> pl.DataFrame:
        """
        Fetch FX spot rates for EM currencies.

        Parameters:
            currencies: List of currency codes (e.g., ["BRL", "TRY", "MXN"])
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            interval: Data frequency ("daily" or "intraday")

        Returns:
            Polars DataFrame with schema:
                - currency: str
                - date: date (or datetime for intraday)
                - fx_rate: float (spot rate vs USD, e.g., 5.0 for USD/BRL)
                - open: float (optional, for daily data)
                - high: float (optional)
                - low: float (optional)
                - close: float (same as fx_rate)

        Raises:
            RateLimitError: If rate limit exceeded after retries
            CurrencyNotFoundError: If currency not supported
            DataQualityError: If data has >20% missing values
        """
        # Check cache first
        cache_key = self._make_cache_key(
            data_type=f"fx_{interval}",
            currencies=currencies,
            start_date=start_date,
            end_date=end_date,
        )

        cached_df = self._get_from_cache(cache_key, force_refresh=self._force_refresh)
        if cached_df is not None:
            logger.debug(f"Cache hit for {len(currencies)} currencies")
            return cached_df

        # Cache miss - fetch from AlphaVantage
        logger.debug(f"Cache miss - fetching {len(currencies)} currencies from AlphaVantage")

        results = []
        for currency in currencies:
            try:
                # Rate limiting
                self._enforce_rate_limit()

                currency_data = self._fetch_fx_pair(currency, interval, start_date, end_date)
                results.append(currency_data)

            except CurrencyNotFoundError as e:
                logger.warning(f"Currency not found: {currency}")
                continue
            except Exception as e:
                logger.error(f"Error fetching {currency}: {e}")
                continue

        if not results:
            return self._empty_fx_df()

        # Concatenate all currency data
        df = pl.concat(results)

        # Filter to date range
        df = df.filter((pl.col("date") >= start_date) & (pl.col("date") <= end_date))

        # Store in cache
        self._put_in_cache(cache_key, df, data_type=f"fx_{interval}", currencies=currencies)

        return df

    def get_interest_rates(
        self, currencies: List[str], as_of_date: Optional[date] = None
    ) -> pl.DataFrame:
        """
        Get central bank policy rates for EM currencies.

        For MVP, uses hardcoded default rates from DEFAULT_INTEREST_RATES.
        Can be extended to fetch real-time rates from FRED, central bank APIs, etc.

        Parameters:
            currencies: List of currency codes (e.g., ["BRL", "TRY", "MXN"])
            as_of_date: Reference date for rates (None = latest)

        Returns:
            Polars DataFrame with schema:
                - currency: str
                - interest_rate: float (annual policy rate as decimal, e.g., 0.1375 for 13.75%)
                - usd_rate: float (US policy rate as decimal)
                - data_date: date (when data was fetched)
        """
        # Check cache
        cache_key = self._make_cache_key(data_type="interest_rates", currencies=currencies)

        cached_df = self._get_from_cache(cache_key, force_refresh=self._force_refresh)
        if cached_df is not None:
            return cached_df

        # Use default rates (MVP implementation)
        # TODO: Extend with FRED API or central bank scraping
        data_date = as_of_date or date.today()
        usd_rate = DEFAULT_INTEREST_RATES["USD"]

        results = []
        for currency in currencies:
            rate = DEFAULT_INTEREST_RATES.get(currency)
            if rate is None:
                logger.warning(
                    f"No interest rate data for {currency}, using 0.0. "
                    f"Add to DEFAULT_INTEREST_RATES or extend with real API."
                )
                rate = 0.0

            results.append(
                {
                    "currency": currency,
                    "interest_rate": rate,
                    "usd_rate": usd_rate,
                    "data_date": data_date,
                }
            )

        df = pl.DataFrame(results)

        # Store in cache
        self._put_in_cache(cache_key, df, data_type="interest_rates", currencies=currencies)

        return df

    def _fetch_fx_pair(
        self, currency: str, interval: str, start_date: date, end_date: date
    ) -> pl.DataFrame:
        """
        Fetch FX data for a single currency pair.

        Uses AlphaVantage FX_DAILY or FX_INTRADAY endpoint.

        Returns:
            Polars DataFrame with FX data
        """
        # Get currency pair (from_currency/to_currency)
        if currency not in EM_CURRENCY_PAIRS:
            raise CurrencyNotFoundError(f"Currency {currency} not in EM_CURRENCY_PAIRS")

        from_currency = "USD"
        to_currency = currency

        # Determine AlphaVantage function
        if interval == "daily":
            function = "FX_DAILY"
            outputsize = "full"  # Get full history
        elif interval == "intraday":
            function = "FX_INTRADAY"
            outputsize = "full"
        else:
            raise ValueError(f"Invalid interval: {interval}. Must be 'daily' or 'intraday'.")

        def _fetch():
            url = "https://www.alphavantage.co/query"
            params = {
                "function": function,
                "from_symbol": from_currency,
                "to_symbol": to_currency,
                "outputsize": outputsize,
                "apikey": self.api_key,
                "datatype": "csv",
            }

            if interval == "intraday":
                params["interval"] = "60min"  # 1-hour bars

            response = requests.get(url, params=params)
            response.raise_for_status()

            # Check for API error messages
            if "Error Message" in response.text or "Invalid API call" in response.text:
                raise CurrencyNotFoundError(f"AlphaVantage error for {currency}: {response.text[:200]}")

            return response.text

        # Fetch with retry
        csv_data = self._fetch_with_retry(_fetch)

        # Parse CSV
        df = pl.read_csv(StringIO(csv_data))

        # Check if we got data
        if len(df) < 10:
            raise DataQualityError(f"Insufficient data for {currency}: {len(df)} rows")

        # Convert to standard format
        df = self._alphavantage_to_polars(df, currency)

        return df

    def _alphavantage_to_polars(self, av_data: pl.DataFrame, currency: str) -> pl.DataFrame:
        """
        Convert AlphaVantage CSV to standardized Polars format.

        AlphaVantage FX_DAILY Output Format:
            Columns: timestamp, open, high, low, close
            Example:
                timestamp,open,high,low,close
                2024-01-15,5.0123,5.0456,4.9890,5.0234

        Polars Output Format:
            Columns:
                - currency: str
                - date: date
                - fx_rate: float (close price)
                - open: float
                - high: float
                - low: float
                - close: float
        """
        # Normalize column names (lowercase)
        df = av_data.rename({col: col.lower() for col in av_data.columns})

        # Parse date
        if "timestamp" in df.columns:
            df = df.with_columns(pl.col("timestamp").str.strptime(pl.Date, format="%Y-%m-%d").alias("date"))
            df = df.drop("timestamp")

        # Add currency column
        df = df.with_columns(pl.lit(currency).alias("currency"))

        # Rename close to fx_rate for clarity
        if "close" in df.columns:
            df = df.with_columns(pl.col("close").alias("fx_rate"))

        # Select and reorder columns
        base_cols = ["currency", "date", "fx_rate"]
        optional_cols = ["open", "high", "low", "close"]

        select_cols = base_cols + [c for c in optional_cols if c in df.columns]
        df = df.select([c for c in select_cols if c in df.columns])

        # Sort by date descending (most recent first)
        df = df.sort("date", descending=True)

        return df

    def _enforce_rate_limit(self):
        """
        Enforce AlphaVantage API rate limits.

        Free tier: 5 calls per minute, 500 calls per day
        Premium tier: 30 calls per minute, 1200 calls per day

        Sleeps if necessary to avoid hitting rate limits.
        """
        now = time.time()

        # Clean old timestamps (>1 minute old)
        self._call_timestamps = [ts for ts in self._call_timestamps if now - ts < 60]

        # Check if we've hit the per-minute limit
        calls_per_minute = len(self._call_timestamps)

        if calls_per_minute >= self._rate_limits["calls_per_minute"]:
            # Calculate sleep time to next available slot
            oldest_call = min(self._call_timestamps)
            sleep_time = 60 - (now - oldest_call) + 0.5  # Add 0.5s buffer

            if sleep_time > 0:
                logger.info(
                    f"Rate limit: {calls_per_minute}/{self._rate_limits['calls_per_minute']} calls/min. "
                    f"Sleeping {sleep_time:.1f}s..."
                )
                time.sleep(sleep_time)

        # Record this call
        self._call_timestamps.append(time.time())

    def _fetch_with_retry(
        self, fetch_fn: Callable, retry_config: Optional[Dict] = None
    ) -> Any:
        """
        Execute fetch with exponential backoff on rate limit errors.

        Retry Schedule (default config):
            Attempt 1: Immediate
            Attempt 2: 2.0s delay (+ jitter)
            Attempt 3: 4.0s delay
            Attempt 4: 8.0s delay
            Attempt 5: 16.0s delay
            (max 4 retries = 5 total attempts)

        Errors to Retry:
            - HTTPError 429 (Too Many Requests)
            - HTTPError 503 (Service Unavailable)
            - Timeout errors
            - Connection errors

        Errors to Fail Immediately:
            - HTTPError 404 (Not Found)
            - HTTPError 401 (Unauthorized - bad API key)
        """
        config = retry_config or self._retry_config

        for attempt in range(config["max_retries"] + 1):
            try:
                return fetch_fn()
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else None

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
                elif status_code == 401:
                    raise APIKeyError(f"Invalid API key: {e}")
                elif status_code == 404:
                    raise CurrencyNotFoundError(f"Currency not found: {e}")
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
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
        currencies: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> str:
        """
        Generate cache key for ZODB storage.

        Key Format:
            {data_type}::{currency_hash}::{date_range}

        Examples:
            fx_daily::brl_try_mxn::20240101_20241231
            interest_rates::brl_try::*
        """
        # Sort currencies for deterministic key
        currency_str = "_".join(sorted(currencies))

        # Hash if too long (>50 chars)
        if len(currency_str) > 50:
            currency_hash = hashlib.sha256(currency_str.encode()).hexdigest()[:16]
        else:
            currency_hash = currency_str.lower()

        # Date range
        if start_date and end_date:
            date_range = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        else:
            date_range = "*"

        return f"{data_type}::{currency_hash}::{date_range}"

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

        cached_data: CachedFXData = cache[cache_key]

        if not self._is_cache_valid(cached_data):
            return None

        return cached_data.data

    def _put_in_cache(
        self, cache_key: str, data: pl.DataFrame, data_type: str, currencies: List[str]
    ):
        """
        Store data in ZODB cache.

        Uses batched() context manager for transaction safety.
        """
        cache = getattr(self, self._cache_attr)

        cached_data = CachedFXData(
            data=data, cached_at=datetime.now(), data_type=data_type, currencies=currencies
        )

        with self.batched():
            cache[cache_key] = cached_data

    def _is_cache_valid(self, cached_data: CachedFXData) -> bool:
        """
        Check if cached data is still valid.

        Validation Rules:
            1. Check TTL based on data type
            2. FX data: Refresh daily
            3. Interest rates: Refresh weekly
        """
        ttl = TTL_CONFIG.get(cached_data.data_type, timedelta(days=1))
        age = datetime.now() - cached_data.cached_at

        return age < ttl

    def _empty_fx_df(self) -> pl.DataFrame:
        """Return empty DataFrame with correct FX schema."""
        return pl.DataFrame(
            schema={
                "currency": pl.Utf8,
                "date": pl.Date,
                "fx_rate": pl.Float64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
            }
        )
