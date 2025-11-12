# ABOUTME: Load S&P 500 data from Nasdaq Data Link (formerly Quandl)
# ABOUTME: Requires free API key from https://data.nasdaq.com/sign-up

"""
Nasdaq Data Link (Quandl) Loader

Sign up for free API key: https://data.nasdaq.com/sign-up
Free tier: Unlimited downloads from free datasets

Set API key:
  export NASDAQ_DATA_LINK_API_KEY="your_key_here"
  OR: pip install nasdaq-data-link
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import polars as pl
import os
import time

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


def download_quandl(ticker: str, api_key: str) -> pd.DataFrame:
    """
    Download from Nasdaq Data Link (Quandl).

    Uses WIKI dataset (historical prices) or EOD dataset.
    """
    try:
        import nasdaqdatalink as ndl
        ndl.ApiConfig.api_key = api_key

        # Try WIKI dataset first (free, historical)
        try:
            df = ndl.get(f"WIKI/{ticker}", start_date="2015-01-01", end_date="2023-12-31")
            return df
        except:
            pass

        # Try EOD dataset
        try:
            df = ndl.get(f"EOD/{ticker}", start_date="2015-01-01", end_date="2023-12-31")
            return df
        except:
            pass

        return None

    except ImportError:
        # Fallback to direct API call
        import requests
        url = f"https://data.nasdaq.com/api/v3/datasets/WIKI/{ticker}/data.csv"
        params = {
            "api_key": api_key,
            "start_date": "2015-01-01",
            "end_date": "2023-12-31",
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()

            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            return df
        except:
            return None


def load_data(api_key: str) -> pl.DataFrame:
    """Load S&P 500 data from Quandl."""
    print("="*80)
    print("NASDAQ DATA LINK (QUANDL) LOADER")
    print("="*80)
    print(f"\nAPI Key: {'*' * 10}{api_key[-4:]}")
    print(f"Dataset: WIKI (free historical prices)")
    print(f"Total tickers: {sum(len(v) for v in TICKERS.values())}\n")

    data_list = []

    for sector, tickers in TICKERS.items():
        print(f"[{sector}]")

        for ticker in tickers:
            df_pandas = download_quandl(ticker, api_key)

            if df_pandas is None or len(df_pandas) < 900:
                print(f"  ⚠ {ticker}: insufficient data")
                continue

            # Quandl format: Date, Open, High, Low, Close, Volume, etc.
            df_pandas = df_pandas.reset_index()

            # Find the close column (might be 'Adj. Close' or 'Close')
            close_col = 'Adj. Close' if 'Adj. Close' in df_pandas.columns else 'Close'

            # Calculate returns
            df_pandas = df_pandas.sort_values('Date')
            df_pandas['return'] = df_pandas[close_col].pct_change()

            # Convert to polars
            df_polars = pl.DataFrame({
                "ticker": ticker,
                "date": pd.to_datetime(df_pandas['Date']).dt.strftime('%Y-%m-%d').values,
                "close": df_pandas[close_col].values,
                "return": df_pandas['return'].values,
                "sector": sector,
            })

            data_list.append(df_polars)
            print(f"  ✓ {ticker}: {len(df_polars)} days")

            time.sleep(0.1)

    if not data_list:
        raise ValueError("No data loaded!")

    df = pl.concat(data_list).filter(pl.col("return").is_not_nan())

    print(f"\n{'='*80}")
    print(f"Loaded {df['ticker'].n_unique()} tickers, {len(df):,} observations")

    return df


if __name__ == "__main__":
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv("NASDAQ_DATA_LINK_API_KEY")

    if not api_key:
        print("ERROR: No API key provided!")
        print("Get free key: https://data.nasdaq.com/sign-up")
        print("\nUsage:")
        print("  export NASDAQ_DATA_LINK_API_KEY='your_key'")
        print("  python load_quandl.py")
        sys.exit(1)

    df = load_data(api_key)

    output_path = Path(__file__).parent / "sp500_real_data.parquet"
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
