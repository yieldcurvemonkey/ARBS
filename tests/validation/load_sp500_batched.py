# ABOUTME: Efficient S&P 500 data loader with batching and rate limiting
# ABOUTME: Uses pandas_datareader batch API and adds delays to avoid 429 errors

"""
Efficient S&P 500 Data Loader

Downloads real market data with proper rate limiting:
- Batch downloads (multiple tickers per request)
- Delays between batches
- Retry logic with exponential backoff
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import polars as pl
import numpy as np
from datetime import datetime
import time

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


def download_batch_yahoo(tickers: list[str], start_date: str, end_date: str) -> dict:
    """
    Download multiple tickers at once using pandas_datareader.

    Args:
        tickers: List of stock tickers
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dict mapping ticker -> DataFrame
    """
    try:
        from pandas_datareader import data as pdr
        import yfinance as yf
        yf.pdr_override()

        # Download all at once
        data = pdr.get_data_yahoo(tickers, start=start_date, end=end_date)

        # Split into per-ticker dataframes
        result = {}
        if len(tickers) == 1:
            result[tickers[0]] = data
        else:
            for ticker in tickers:
                try:
                    result[ticker] = data.xs(ticker, level=1, axis=1)
                except:
                    # Ticker might not exist or have no data
                    pass

        return result

    except Exception as e:
        print(f"  ✗ Batch download failed: {e}")
        return {}


def download_single_yahoo(ticker: str, start_date: str, end_date: str, retry: int = 0) -> pl.DataFrame:
    """
    Download single ticker with retry logic.
    """
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp())

    url = (
        f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d&events=history"
    )

    try:
        df = pl.read_csv(url)
        return df
    except Exception as e:
        if retry < 3 and "429" in str(e):
            # Rate limited - wait and retry
            wait_time = 2 ** retry
            print(f"  ⚠ Rate limited, waiting {wait_time}s...")
            time.sleep(wait_time)
            return download_single_yahoo(ticker, start_date, end_date, retry + 1)
        else:
            print(f"  ✗ Error downloading {ticker}: {e}")
            return None


def load_sp500_data(
    start_date: str = "2019-01-01",
    end_date: str = "2024-12-31",
    batch_size: int = 5,
    delay_between_batches: float = 2.0,
) -> pl.DataFrame:
    """
    Load S&P 500 data with intelligent batching.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        batch_size: Number of tickers per batch
        delay_between_batches: Seconds to wait between batches

    Returns:
        Polars DataFrame with [ticker, date, return, sector, close]
    """
    print(f"Loading S&P 500 data from Yahoo Finance...")
    print(f"Period: {start_date} to {end_date}")
    print(f"Batch size: {batch_size}, Delay: {delay_between_batches}s\n")

    data_list = []

    for sector, tickers in TICKERS.items():
        print(f"[{sector}] {len(tickers)} tickers")

        # Process in batches
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            print(f"  Batch {i//batch_size + 1}: {', '.join(batch)}")

            # Try batch download first
            batch_data = download_batch_yahoo(batch, start_date, end_date)

            if not batch_data:
                # Fallback to individual downloads
                print(f"  Falling back to individual downloads...")
                for ticker in batch:
                    time.sleep(0.5)  # Small delay between individual requests
                    df = download_single_yahoo(ticker, start_date, end_date)

                    if df is not None and len(df) >= 900:
                        batch_data[ticker] = df

            # Process successful downloads
            for ticker, df_data in batch_data.items():
                if len(df_data) < 900:
                    print(f"    ⚠ {ticker}: insufficient data ({len(df_data)} days)")
                    continue

                # Convert to polars if pandas (from external API)
                if hasattr(df_data, 'to_numpy'):  # pandas DataFrame
                    df_polars = pl.from_pandas(df_data)
                else:  # already polars
                    df_polars = df_data

                # Calculate returns
                close_col = 'Adj Close' if 'Adj Close' in df_polars.columns else 'Close'
                df_polars = df_polars.with_columns([
                    (pl.col(close_col) / pl.col(close_col).shift(1) - pl.lit(1)).alias('return')
                ])

                # Get date as string
                if 'Date' in df_polars.columns:
                    dates = df_polars['Date'].cast(pl.Utf8)
                else:
                    # If Date is in index (from pandas), it should be in columns after from_pandas
                    dates = df_polars.select(pl.first()).to_series().cast(pl.Utf8)

                # Build final dataframe
                df_final = pl.DataFrame({
                    "ticker": [ticker] * len(df_polars),
                    "date": dates,
                    "close": df_polars[close_col],
                    "return": df_polars['return'],
                    "sector": [sector] * len(df_polars),
                })

                data_list.append(df_final)
                print(f"    ✓ {ticker}: {len(df_final)} days")

            # Delay between batches
            if i + batch_size < len(tickers):
                print(f"  Waiting {delay_between_batches}s before next batch...")
                time.sleep(delay_between_batches)

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
    df = load_sp500_data(
        batch_size=5,  # Download 5 tickers at a time
        delay_between_batches=2.0,  # Wait 2s between batches
    )
    save_data(df)
    print("\n✓ Real data ready for validation!")
