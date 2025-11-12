# ABOUTME: Integration tests for real market data acquisition and quality validation
# ABOUTME: Tests data loading, sector mapping, and data quality checks for sector covariance models
"""
Real Data Loading and Quality Tests

Tests for loading and validating real market data for sector-based covariance estimation.
"""

import pytest
import polars as pl
import numpy as np
from datetime import datetime, timedelta


def load_real_market_data(
    universe: str = "dow30",
    start_date: str = "2020-01-01",
    end_date: str = "2024-01-01",
    min_history_days: int = 500,
) -> pl.DataFrame:
    """
    Load real market data for validation.

    Args:
        universe: Market universe ('sp500', 'dow30', 'nasdaq100')
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        min_history_days: Minimum trading days required

    Returns:
        DataFrame with columns [ticker, date, return, sector, close]

    Raises:
        ValueError: If universe is unknown or data cannot be loaded
    """
    import yfinance as yf
    from tqdm import tqdm

    # Define universes
    universes = {
        "dow30": _get_dow30_tickers(),
        "sp500": _get_sp500_tickers(),
        "nasdaq100": _get_nasdaq100_tickers(),
    }

    if universe not in universes:
        raise ValueError(
            f"Unknown universe: {universe}. "
            f"Available: {', '.join(universes.keys())}"
        )

    tickers = universes[universe]

    # Download data
    print(f"Downloading {len(tickers)} tickers from {universe}...")
    data_list = []

    for ticker in tqdm(tickers, desc="Downloading"):
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start_date, end=end_date, auto_adjust=True)

            if len(hist) < min_history_days:
                print(f"  Skipping {ticker}: insufficient history ({len(hist)} days)")
                continue

            # Calculate returns
            returns = hist["Close"].pct_change()

            # Get sector info
            try:
                sector = stock.info.get("sector", "Unknown")
            except:
                sector = "Unknown"

            # Build dataframe
            df_ticker = pl.DataFrame({
                "ticker": ticker,
                "date": hist.index,
                "close": hist["Close"].values,
                "return": returns.values,
                "sector": sector,
            })

            data_list.append(df_ticker)

        except Exception as e:
            print(f"  Error loading {ticker}: {e}")
            continue

    if not data_list:
        raise ValueError(f"No data loaded for universe: {universe}")

    # Combine all tickers
    df = pl.concat(data_list)

    # Remove first row (NaN returns)
    df = df.filter(pl.col("return").is_not_nan())

    # Remove tickers without sector info
    df = df.filter(pl.col("sector") != "Unknown")

    print(f"Loaded {df['ticker'].n_unique()} tickers with {len(df)} observations")
    print(f"Sectors: {sorted(df['sector'].unique().to_list())}")

    return df


def _get_dow30_tickers() -> list[str]:
    """Get Dow 30 tickers."""
    # Dow 30 as of 2024
    return [
        "AAPL", "MSFT", "JPM", "V", "UNH", "HD", "PG", "JNJ", "CVX", "MRK",
        "ABBV", "KO", "PEP", "CSCO", "MCD", "WMT", "IBM", "DIS", "NKE", "CAT",
        "AXP", "GS", "BA", "HON", "MMM", "TRV", "VZ", "AMGN", "CRM", "DOW",
    ]


def _get_sp500_tickers() -> list[str]:
    """Get S&P 500 tickers (subset for testing)."""
    # For testing, use a manageable subset
    # In production, fetch from Wikipedia or other source
    return _get_dow30_tickers()  # Start with Dow 30


def _get_nasdaq100_tickers() -> list[str]:
    """Get NASDAQ 100 tickers (subset for testing)."""
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "AVGO", "COST", "ASML",
    ]


def get_sector_mapping(tickers: list[str]) -> dict[str, str]:
    """
    Map tickers to GICS sectors.

    Args:
        tickers: List of ticker symbols

    Returns:
        Dictionary mapping ticker -> sector

    Example:
        >>> mapping = get_sector_mapping(['AAPL', 'JPM'])
        >>> mapping['AAPL']
        'Technology'
        >>> mapping['JPM']
        'Financials'
    """
    import yfinance as yf

    mapping = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            sector = stock.info.get("sector", "Unknown")
            mapping[ticker] = sector
        except:
            mapping[ticker] = "Unknown"

    return mapping


def validate_data_quality(df: pl.DataFrame) -> dict[str, any]:
    """
    Validate data quality for covariance estimation.

    Args:
        df: DataFrame with columns [ticker, date, return, sector]

    Returns:
        Dictionary with quality metrics

    Raises:
        ValueError: If data quality is insufficient
    """
    metrics = {}

    # Check required columns
    required_cols = ["ticker", "date", "return", "sector"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Count metrics
    metrics["n_tickers"] = df["ticker"].n_unique()
    metrics["n_observations"] = len(df)
    metrics["n_sectors"] = df["sector"].n_unique()

    # Check for missing values (both null and NaN)
    metrics["missing_returns"] = df["return"].is_null().sum() + df["return"].is_nan().sum()
    metrics["missing_sectors"] = df["sector"].is_null().sum()

    # Check date coverage
    dates = df.select("date").unique().sort("date")
    metrics["start_date"] = dates["date"].min()
    metrics["end_date"] = dates["date"].max()
    metrics["n_dates"] = len(dates)

    # Check for extreme returns (possible data errors)
    returns = df["return"].drop_nulls()
    metrics["max_return"] = returns.max()
    metrics["min_return"] = returns.min()
    metrics["extreme_returns"] = ((returns.abs() > 0.5).sum())

    # Validate data quality
    if metrics["n_tickers"] < 10:
        raise ValueError(f"Too few tickers: {metrics['n_tickers']} (minimum: 10)")

    if metrics["n_sectors"] < 3:
        raise ValueError(f"Too few sectors: {metrics['n_sectors']} (minimum: 3)")

    if metrics["missing_returns"] > 0:
        raise ValueError(f"Found {metrics['missing_returns']} missing returns")

    if metrics["extreme_returns"] > metrics["n_observations"] * 0.01:
        raise ValueError(
            f"Too many extreme returns: {metrics['extreme_returns']} "
            f"({metrics['extreme_returns'] / metrics['n_observations']:.1%})"
        )

    return metrics


# ===== TESTS =====


class TestRealDataLoading:
    """Tests for real market data loading."""

    def test_load_dow30_data(self):
        """Test loading Dow 30 data."""
        # Use a short date range for testing
        df = load_real_market_data(
            universe="dow30",
            start_date="2023-01-01",
            end_date="2024-01-01",
            min_history_days=200,
        )

        # Validate structure
        assert "ticker" in df.columns
        assert "date" in df.columns
        assert "return" in df.columns
        assert "sector" in df.columns
        assert "close" in df.columns

        # Validate content
        assert df["ticker"].n_unique() >= 10  # At least 10 tickers
        assert len(df) > 1000  # At least 1000 observations
        assert df["sector"].n_unique() >= 5  # At least 5 sectors

        # Validate returns
        assert df["return"].is_null().sum() == 0  # No missing returns
        assert df["return"].abs().max() < 0.5  # No extreme returns

    def test_invalid_universe(self):
        """Test error on invalid universe."""
        with pytest.raises(ValueError, match="Unknown universe"):
            load_real_market_data(universe="invalid")

    def test_sector_mapping(self):
        """Test sector mapping function."""
        tickers = ["AAPL", "JPM", "PG"]
        mapping = get_sector_mapping(tickers)

        assert len(mapping) == 3
        assert mapping["AAPL"] in ["Technology", "Information Technology"]
        assert mapping["JPM"] in ["Financials", "Financial Services"]
        assert mapping["PG"] in ["Consumer Staples", "Consumer Defensive"]


class TestDataQuality:
    """Tests for data quality validation."""

    def test_validate_data_quality(self):
        """Test data quality validation on real data."""
        # Load data
        df = load_real_market_data(
            universe="dow30",
            start_date="2023-01-01",
            end_date="2024-01-01",
            min_history_days=200,
        )

        # Validate quality
        metrics = validate_data_quality(df)

        # Check metrics
        assert metrics["n_tickers"] >= 10
        assert metrics["n_sectors"] >= 5
        assert metrics["missing_returns"] == 0
        assert metrics["missing_sectors"] == 0
        assert metrics["extreme_returns"] == 0

    def test_validate_insufficient_tickers(self):
        """Test error on insufficient tickers."""
        # Create small dataset
        df = pl.DataFrame({
            "ticker": ["AAPL"] * 100,
            "date": [datetime(2023, 1, 1) + timedelta(days=i) for i in range(100)],
            "return": np.random.randn(100) * 0.01,
            "sector": ["Technology"] * 100,
        })

        with pytest.raises(ValueError, match="Too few tickers"):
            validate_data_quality(df)

    def test_validate_insufficient_sectors(self):
        """Test error on insufficient sectors."""
        # Create dataset with 10 tickers but only 2 sectors
        tickers = [f"TICK{i}" for i in range(10)]
        dates = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(100)]
        df = pl.DataFrame({
            "ticker": [t for t in tickers for _ in range(100)],
            "date": dates * 10,
            "return": np.random.randn(1000) * 0.01,
            "sector": (["Technology"] * 500 + ["Financials"] * 500),
        })

        with pytest.raises(ValueError, match="Too few sectors"):
            validate_data_quality(df)

    def test_validate_missing_returns(self):
        """Test error on missing returns."""
        tickers = [f"TICK{i}" for i in range(10)]
        dates = [datetime(2023, 1, 1) + timedelta(days=i) for i in range(100)]
        sectors = ["Technology", "Financials", "Healthcare", "Energy", "Consumer"]

        returns = np.random.randn(1000) * 0.01
        returns[:10] = np.nan  # Add missing values

        df = pl.DataFrame({
            "ticker": [t for t in tickers for _ in range(100)],
            "date": dates * 10,
            "return": returns,
            "sector": [sectors[i % 5] for i in range(10) for _ in range(100)],
        })

        with pytest.raises(ValueError, match="missing returns"):
            validate_data_quality(df)


if __name__ == "__main__":
    # Quick test
    print("Testing data loading...")
    df = load_real_market_data(
        universe="dow30",
        start_date="2023-01-01",
        end_date="2024-01-01",
        min_history_days=200,
    )
    print(f"\nLoaded {df['ticker'].n_unique()} tickers")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Sectors: {sorted(df['sector'].unique().to_list())}")

    metrics = validate_data_quality(df)
    print("\nQuality Metrics:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
