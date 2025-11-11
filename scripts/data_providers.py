# ABOUTME: ETL interfaces and implementations for futures returns data using Polars
# ABOUTME: Provides DataProvider abstraction allowing easy swap between synthetic and real data
"""
Futures Returns Data Providers (Polars Implementation)

ETL system for loading futures returns with clean interface.
Swap synthetic → real data by changing one line.

Uses Polars for high-performance data operations.

Usage:
    from scripts.data_providers import SyntheticFuturesProvider, RealFuturesProvider

    # For testing/development
    provider = SyntheticFuturesProvider()

    # For production (when you have real data)
    provider = RealFuturesProvider(data_path="path/to/futures_prices.csv")

    # Same interface regardless of source
    returns = provider.get_returns(
        currencies=["USD", "EUR", "GBP"],
        maturities=["3M", "6M", "1Y", "2Y"],
        start_date="2023-01-01",
        end_date="2024-12-31"
    )
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime, timedelta
import polars as pl
import numpy as np


class FuturesDataProvider(ABC):
    """
    Abstract base class for futures data providers.

    Enforces consistent interface for synthetic and real data sources.
    """

    @abstractmethod
    def get_returns(
        self,
        currencies: List[str],
        maturities: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d"
    ) -> pl.DataFrame:
        """
        Get futures returns DataFrame.

        Args:
            currencies: List of currencies (e.g., ["USD", "EUR", "GBP"])
            maturities: List of maturities (e.g., ["3M", "6M", "1Y", "2Y"])
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            frequency: Data frequency ("1d" for daily, "1w" for weekly)

        Returns:
            Polars DataFrame with:
                - Column "date": Date (pl.Date)
                - Columns "{currency}_{maturity}": Returns (f64)
                - Values: Returns (decimal, e.g., 0.001 for 10bp daily return)
        """
        pass


class SyntheticFuturesProvider(FuturesDataProvider):
    """
    Generates realistic synthetic futures returns for testing.

    Models proper correlation structure:
    - Within-currency (same maturity): 95% correlation
    - Within-currency (different maturity): 85-95% correlation
    - Cross-currency (same maturity): 40% correlation
    - Cross-currency (different maturity): 30% correlation
    """

    def __init__(
        self,
        within_currency_corr: float = 0.92,
        cross_currency_corr: float = 0.40,
        volatility: float = 0.0005,  # ~8bp daily vol
        seed: Optional[int] = 42
    ):
        """
        Initialize synthetic data generator.

        Args:
            within_currency_corr: Correlation between instruments in same currency
            cross_currency_corr: Correlation between different currencies
            volatility: Daily return volatility (std dev)
            seed: Random seed for reproducibility
        """
        self.within_currency_corr = within_currency_corr
        self.cross_currency_corr = cross_currency_corr
        self.volatility = volatility
        self.seed = seed

    def get_returns(
        self,
        currencies: List[str],
        maturities: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d"
    ) -> pl.DataFrame:
        """Generate synthetic futures returns with block correlation structure."""

        # Parse dates
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        # Create date range
        date_range = pl.date_range(start, end, interval=frequency, eager=True)
        n_periods = len(date_range)

        # Build column names
        columns = [f"{curr}_{mat}" for curr in currencies for mat in maturities]
        n_instruments = len(columns)

        # Set seed for reproducibility
        if self.seed is not None:
            np.random.seed(self.seed)

        # Build block covariance matrix
        cov_matrix = self._build_block_covariance(currencies, maturities)

        # Generate correlated returns using Cholesky decomposition
        L = np.linalg.cholesky(cov_matrix)
        uncorrelated = np.random.randn(n_periods, n_instruments)
        correlated_returns = uncorrelated @ L.T

        # Create Polars DataFrame
        data_dict = {"date": date_range}
        for i, col_name in enumerate(columns):
            data_dict[col_name] = correlated_returns[:, i]

        returns_df = pl.DataFrame(data_dict)

        return returns_df

    def _build_block_covariance(
        self,
        currencies: List[str],
        maturities: List[str]
    ) -> np.ndarray:
        """
        Build covariance matrix with block structure.

        Structure:
            [  USD block   ] [  USD-EUR  ] [  USD-GBP  ]
            [  EUR-USD     ] [  EUR block ] [  EUR-GBP  ]
            [  GBP-USD     ] [  GBP-EUR  ] [  GBP block ]

        Within-block: High correlation (90-95%)
        Cross-block: Medium correlation (30-50%)
        """
        n_currencies = len(currencies)
        n_maturities = len(maturities)
        n_instruments = n_currencies * n_maturities

        # Initialize correlation matrix
        corr = np.zeros((n_instruments, n_instruments))

        # Fill correlation matrix
        for i in range(n_instruments):
            curr_i = i // n_maturities  # Which currency (0, 1, 2,...)
            mat_i = i % n_maturities     # Which maturity within currency

            for j in range(n_instruments):
                curr_j = j // n_maturities
                mat_j = j % n_maturities

                if i == j:
                    # Diagonal: perfect correlation with self
                    corr[i, j] = 1.0
                elif curr_i == curr_j:
                    # Same currency: high correlation
                    # Slightly lower if maturities are far apart
                    maturity_distance = abs(mat_i - mat_j)
                    decay = 0.02 * maturity_distance  # 2% decay per maturity step
                    corr[i, j] = max(0.85, self.within_currency_corr - decay)
                else:
                    # Different currency: medium correlation
                    corr[i, j] = self.cross_currency_corr

        # Convert correlation to covariance (all instruments have same vol)
        cov = corr * (self.volatility ** 2)

        return cov


class RealFuturesProvider(FuturesDataProvider):
    """
    Loads real futures data from CSV/Parquet files.

    Expected data format:
        CSV with columns: date, contract, price (or return)

        Example:
            date,contract,price
            2023-01-03,USD_3M,99.150
            2023-01-03,USD_6M,98.920
            2023-01-03,EUR_3M,97.450
            ...

    Or price DataFrame format:
        Columns: date, USD_3M, USD_6M, EUR_3M, EUR_6M, ...
        Values: prices
    """

    def __init__(
        self,
        data_path: str,
        price_column: str = "price",
        contract_column: str = "contract",
        date_column: str = "date",
        file_format: str = "csv"
    ):
        """
        Initialize real data provider.

        Args:
            data_path: Path to data file (CSV or Parquet)
            price_column: Name of price column (if long format)
            contract_column: Name of contract column (if long format)
            date_column: Name of date column
            file_format: "csv", "parquet", or "wide" (wide format CSV)
        """
        self.data_path = data_path
        self.price_column = price_column
        self.contract_column = contract_column
        self.date_column = date_column
        self.file_format = file_format
        self._prices = None  # Cache loaded data

    def get_returns(
        self,
        currencies: List[str],
        maturities: List[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d"
    ) -> pl.DataFrame:
        """Load real futures returns from file."""

        # Load prices if not cached
        if self._prices is None:
            self._load_prices()

        # Filter to requested instruments
        columns = [f"{curr}_{mat}" for curr in currencies for mat in maturities]
        available_columns = [col for col in columns if col in self._prices.columns]

        if len(available_columns) == 0:
            raise ValueError(
                f"No matching instruments found. "
                f"Requested: {columns}, Available: {list(self._prices.columns)}"
            )

        # Select date column + available price columns
        prices = self._prices.select(["date"] + available_columns)

        # Filter dates
        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        prices = prices.filter(
            (pl.col("date") >= start_dt) & (pl.col("date") <= end_dt)
        )

        # Resample if needed (Polars groupby_dynamic)
        if frequency != "1d":
            prices = prices.group_by_dynamic(
                "date",
                every=frequency
            ).agg([pl.col(col).last() for col in available_columns])

        # Calculate returns (pct_change equivalent)
        returns = prices.with_columns([
            ((pl.col(col) / pl.col(col).shift(1)) - 1.0).alias(col)
            for col in available_columns
        ]).drop_nulls()

        return returns

    def _load_prices(self):
        """Load price data from file."""

        if self.file_format == "csv":
            df = pl.read_csv(self.data_path)
            self._prices = self._pivot_long_to_wide(df)

        elif self.file_format == "parquet":
            df = pl.read_parquet(self.data_path)
            self._prices = self._pivot_long_to_wide(df)

        elif self.file_format == "wide":
            # Already in wide format
            df = pl.read_csv(self.data_path)
            # Ensure date column is parsed
            self._prices = df.with_columns(
                pl.col(self.date_column).str.to_date().alias("date")
            )

        else:
            raise ValueError(f"Unknown file format: {self.file_format}")

    def _pivot_long_to_wide(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Convert long format to wide format.

        From:
            date, contract, price
        To:
            date, USD_3M, USD_6M, EUR_3M, ...
        """
        # Parse date column
        df = df.with_columns(
            pl.col(self.date_column).str.to_date().alias("date")
        )

        # Pivot to wide format
        wide = df.pivot(
            values=self.price_column,
            index="date",
            on=self.contract_column
        )

        # Sort by date
        wide = wide.sort("date")

        return wide


# =============================================================================
# Quick Usage Examples
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("Futures Data Provider Examples (Polars)")
    print("="*70)
    print()

    # Example 1: Synthetic data
    print("Example 1: Synthetic Data")
    print("-" * 70)

    synthetic_provider = SyntheticFuturesProvider(seed=42)

    returns = synthetic_provider.get_returns(
        currencies=["USD", "EUR", "GBP"],
        maturities=["3M", "6M", "1Y", "2Y"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        frequency="1d"
    )

    print(f"Shape: {returns.shape}")
    print(f"Columns: {returns.columns}")
    print(f"Date range: {returns['date'].min()} to {returns['date'].max()}")
    print()
    print("First 5 rows:")
    print(returns.head())
    print()
    print("Schema:")
    print(returns.schema)
    print()

    # Example 2: Real data (template - will error without actual file)
    print("Example 2: Real Data (Template)")
    print("-" * 70)
    print("To use real data:")
    print()
    print("# Uncomment and modify:")
    print("# real_provider = RealFuturesProvider(")
    print("#     data_path='data/futures_prices.csv',")
    print("#     file_format='csv'  # or 'parquet' or 'wide'")
    print("# )")
    print("# returns = real_provider.get_returns(...)")
    print()
    print("="*70)
