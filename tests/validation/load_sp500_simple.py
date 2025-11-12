# ABOUTME: Simple S&P 500 data loader using pandas and direct Yahoo Finance API
# ABOUTME: Avoids yfinance dependency issues by using direct HTTP requests

"""
Simple S&P 500 Data Loader

Downloads real market data directly from Yahoo Finance without yfinance library.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import polars as pl
import numpy as np
from datetime import datetime

# S&P 500 representative tickers across sectors
TICKERS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Healthcare": ["UNH", "JNJ", "LLY", "ABBV", "MRK"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "Industrials": ["UNP", "HON", "CAT", "BA", "RTX"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP"],
}


def download_yahoo_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Download data directly from Yahoo Finance using pandas.

    Args:
        ticker: Stock ticker
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        pandas DataFrame with OHLCV data
    """
    # Convert dates to Unix timestamps
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp())

    # Yahoo Finance URL
    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d&events=history"
    )

    try:
        df = pd.read_csv(url)
        return df
    except Exception as e:
        print(f"  ✗ Error downloading {ticker}: {e}")
        return None


def load_sp500_data(
    start_date: str = "2019-01-01",
    end_date: str = "2024-12-31",
) -> pl.DataFrame:
    """
    Load S&P 500 data for validation.

    Returns:
        Polars DataFrame with [ticker, date, return, sector, close]
    """
    print(f"Loading S&P 500 data from Yahoo Finance...")
    print(f"Period: {start_date} to {end_date}")
    print(f"Tickers: {sum(len(v) for v in TICKERS.values())} across {len(TICKERS)} sectors\n")

    data_list = []

    for sector, tickers in TICKERS.items():
        print(f"[{sector}]")
        for ticker in tickers:
            df_pandas = download_yahoo_data(ticker, start_date, end_date)

            if df_pandas is None or len(df_pandas) < 900:
                print(f"  ⚠ Skipping {ticker}: insufficient data")
                continue

            # Calculate returns
            df_pandas['Return'] = df_pandas['Adj Close'].pct_change()

            # Convert to polars
            df_polars = pl.DataFrame({
                "ticker": ticker,
                "date": df_pandas['Date'].astype(str).values,
                "close": df_pandas['Adj Close'].values,
                "return": df_pandas['Return'].values,
                "sector": sector,
            })

            data_list.append(df_polars)
            print(f"  ✓ {ticker}: {len(df_polars)} days")

    if not data_list:
        raise ValueError("No data loaded!")

    # Combine
    df = pl.concat(data_list)

    # Remove NaN returns
    df = df.filter(pl.col("return").is_not_nan())

    print(f"\n=== Summary ===")
    print(f"Total observations: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].n_unique()}")
    print(f"Unique dates: {df['date'].n_unique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    sector_summary = df.group_by("sector").agg([
        pl.col("ticker").n_unique().alias("n_tickers"),
        pl.count().alias("n_obs"),
    ]).sort("n_tickers", descending=True)
    print(f"\nSector breakdown:")
    print(sector_summary)

    return df


def save_data(df: pl.DataFrame, filename: str = "sp500_real_data.parquet"):
    """Save to parquet."""
    output_path = Path(__file__).parent / filename
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    df = load_sp500_data()
    save_data(df)
    print("\n✓ Real data ready for validation!")
