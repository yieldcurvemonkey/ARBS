# ABOUTME: Load S&P 500 data from Alpha Vantage API
# ABOUTME: Requires free API key from https://www.alphavantage.co/support/#api-key

"""
Alpha Vantage Data Loader

Sign up for free API key: https://www.alphavantage.co/support/#api-key
Free tier: 5 API calls/minute, 500 calls/day

Set API key:
  export ALPHAVANTAGE_API_KEY="your_key_here"
  OR pass as argument: python load_alphavantage.py YOUR_KEY
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import polars as pl
import requests
import time
import os

# Same tickers as other scripts
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


def download_alphavantage(ticker: str, api_key: str) -> pd.DataFrame:
    """
    Download data from Alpha Vantage.

    Free tier limits:
    - 5 calls per minute
    - 500 calls per day
    """
    url = f"https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": ticker,
        "outputsize": "full",  # Get full history (20+ years)
        "apikey": api_key,
        "datatype": "csv",
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        # Parse CSV
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))

        # Check if we got an error message
        if 'Error Message' in df.columns or len(df) < 100:
            print(f"  ✗ {ticker}: API error or insufficient data")
            return None

        return df

    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return None


def load_data(api_key: str) -> pl.DataFrame:
    """Load S&P 500 data from Alpha Vantage."""
    print("="*80)
    print("ALPHA VANTAGE DATA LOADER")
    print("="*80)
    print(f"\nAPI Key: {'*' * 10}{api_key[-4:]}")
    print(f"Free tier: 5 calls/min, 500 calls/day")
    print(f"Total tickers: {sum(len(v) for v in TICKERS.values())}")
    print(f"Estimated time: ~10 minutes (with rate limiting)\n")

    data_list = []
    call_count = 0

    for sector, tickers in TICKERS.items():
        print(f"[{sector}]")

        for ticker in tickers:
            # Rate limiting: 5 calls per minute
            if call_count > 0 and call_count % 5 == 0:
                print(f"  Rate limit: waiting 60s...")
                time.sleep(60)

            df_pandas = download_alphavantage(ticker, api_key)
            call_count += 1

            if df_pandas is None:
                continue

            # Filter to our date range (2015-2023)
            df_pandas['timestamp'] = pd.to_datetime(df_pandas['timestamp'])
            df_pandas = df_pandas[
                (df_pandas['timestamp'] >= '2015-01-01') &
                (df_pandas['timestamp'] <= '2023-12-31')
            ]

            if len(df_pandas) < 900:
                print(f"  ⚠ {ticker}: insufficient data ({len(df_pandas)} days)")
                continue

            # Calculate returns
            df_pandas = df_pandas.sort_values('timestamp')
            df_pandas['return'] = df_pandas['adjusted_close'].pct_change()

            # Convert to polars
            df_polars = pl.DataFrame({
                "ticker": ticker,
                "date": df_pandas['timestamp'].dt.strftime('%Y-%m-%d').values,
                "close": df_pandas['adjusted_close'].values,
                "return": df_pandas['return'].values,
                "sector": sector,
            })

            data_list.append(df_polars)
            print(f"  ✓ {ticker}: {len(df_polars)} days")

            time.sleep(0.5)  # Small delay between requests

    if not data_list:
        raise ValueError("No data loaded!")

    df = pl.concat(data_list).filter(pl.col("return").is_not_nan())

    print(f"\n{'='*80}")
    print(f"Loaded {df['ticker'].n_unique()} tickers, {len(df):,} observations")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    return df


if __name__ == "__main__":
    # Get API key from env or command line
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ALPHAVANTAGE_API_KEY")

    if not api_key:
        print("ERROR: No API key provided!")
        print("Get free key: https://www.alphavantage.co/support/#api-key")
        print("\nUsage:")
        print("  export ALPHAVANTAGE_API_KEY='your_key'")
        print("  python load_alphavantage.py")
        print("\nOR:")
        print("  python load_alphavantage.py YOUR_KEY")
        sys.exit(1)

    df = load_data(api_key)

    output_path = Path(__file__).parent / "sp500_real_data.parquet"
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
