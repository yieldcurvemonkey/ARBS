# ABOUTME: Load real S&P 500 data matching paper methodology
# ABOUTME: Single batch download of all tickers for the full date range

"""
Real S&P 500 Data Loader

Replicates paper methodology:
- Paper 2 (Žignić): Top US stocks by market cap (1995-2017)
- We use: S&P 500 constituents (2015-2023) - 8 years similar to paper

ONE BATCH DOWNLOAD - ALL TICKERS, FULL DATE RANGE
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import polars as pl
from datetime import datetime

# S&P 500 representative sample across all sectors
# Selected for: high liquidity, sector diversity, complete data history
ALL_TICKERS = [
    # Technology (10)
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ADBE", "CRM", "ORCL", "INTC",
    # Financials (10)
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "USB",
    # Healthcare (10)
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN",
    # Consumer Discretionary (10)
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG", "CMG",
    # Communication Services (10)
    "GOOG", "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO",
    # Industrials (10)
    "UNP", "HON", "CAT", "BA", "RTX", "UPS", "DE", "LMT", "GE", "MMM",
    # Consumer Staples (10)
    "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "KHC",
    # Energy (10)
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
    # Utilities (5)
    "NEE", "DUK", "SO", "D", "AEP",
    # Real Estate (5)
    "PLD", "AMT", "EQIX", "PSA", "WELL",
]

# Sector mapping (Yahoo Finance GICS sectors)
SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "META": "Technology", "AVGO": "Technology",
    "ADBE": "Technology", "CRM": "Technology", "ORCL": "Technology", "INTC": "Technology",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "C": "Financials",
    "BLK": "Financials", "SCHW": "Financials", "AXP": "Financials", "USB": "Financials",
    # Healthcare
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "TMO": "Healthcare",
    "ABT": "Healthcare", "DHR": "Healthcare", "BMY": "Healthcare", "AMGN": "Healthcare",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "LOW": "Consumer Discretionary", "TJX": "Consumer Discretionary",
    "BKNG": "Consumer Discretionary", "CMG": "Consumer Discretionary",
    # Communication Services
    "GOOG": "Communication Services", "DIS": "Communication Services",
    "NFLX": "Communication Services", "CMCSA": "Communication Services",
    "T": "Communication Services", "VZ": "Communication Services",
    "TMUS": "Communication Services", "CHTR": "Communication Services",
    "EA": "Communication Services", "TTWO": "Communication Services",
    # Industrials
    "UNP": "Industrials", "HON": "Industrials", "CAT": "Industrials",
    "BA": "Industrials", "RTX": "Industrials", "UPS": "Industrials",
    "DE": "Industrials", "LMT": "Industrials", "GE": "Industrials", "MMM": "Industrials",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "CL": "Consumer Staples", "MDLZ": "Consumer Staples", "KHC": "Consumer Staples",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy", "EOG": "Energy",
    "MPC": "Energy", "PSX": "Energy", "VLO": "Energy", "OXY": "Energy", "HAL": "Energy",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities", "AEP": "Utilities",
    # Real Estate
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "PSA": "Real Estate", "WELL": "Real Estate",
}

# Date range matching paper methodology
START_DATE = "2015-01-01"  # 8 years of data
END_DATE = "2023-12-31"


def download_all_data_batch() -> pl.DataFrame:
    """
    Download ALL tickers in ONE batch request.

    This is the RIGHT way - not 100 individual requests.
    """
    print("="*80)
    print("DOWNLOADING S&P 500 DATA")
    print("="*80)
    print(f"\nTickers: {len(ALL_TICKERS)}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Method: SINGLE BATCH DOWNLOAD\n")

    # Use pandas_datareader for batch download
    try:
        from pandas_datareader import data as pdr
        import yfinance as yf
        yf.pdr_override()

        print("Downloading all tickers in one batch...")
        data = pdr.get_data_yahoo(ALL_TICKERS, start=START_DATE, end=END_DATE)
        print(f"✓ Downloaded {len(data)} days of data")

    except ImportError:
        # Fallback to direct pandas read if pandas_datareader not available
        print("Using direct pandas download (fallback)...")

        all_data = []
        for i, ticker in enumerate(ALL_TICKERS):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(ALL_TICKERS)}")

            start_ts = int(datetime.strptime(START_DATE, "%Y-%m-%d").timestamp())
            end_ts = int(datetime.strptime(END_DATE, "%Y-%m-%d").timestamp())

            url = (
                f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
                f"?period1={start_ts}&period2={end_ts}&interval=1d&events=history"
            )

            try:
                df = pd.read_csv(url)
                df['Ticker'] = ticker
                all_data.append(df)
            except Exception as e:
                print(f"  ✗ Failed {ticker}: {e}")
                continue

        if not all_data:
            raise ValueError("No data downloaded!")

        # Combine all
        data = pd.concat(all_data, ignore_index=True)
        print(f"✓ Downloaded {len(data)} total observations")

    # Convert to long format
    print("\nConverting to long format...")
    data_list = []

    for ticker in ALL_TICKERS:
        try:
            # Get this ticker's data
            if 'Ticker' in data.columns:
                ticker_data = data[data['Ticker'] == ticker].copy()
            else:
                # Multi-index from pandas_datareader
                ticker_data = data.xs(ticker, level=1, axis=1, drop_level=False)

            # Get adjusted close
            if 'Adj Close' in ticker_data.columns:
                close_col = 'Adj Close'
            elif ('Adj Close', ticker) in ticker_data.columns:
                close_col = ('Adj Close', ticker)
            else:
                close_col = 'Close'

            closes = ticker_data[close_col]
            dates = closes.index

            # Calculate returns
            returns = closes.pct_change()

            # Get sector
            sector = SECTOR_MAP.get(ticker, "Unknown")

            # Build DataFrame
            df_ticker = pl.DataFrame({
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in dates],
                "close": closes.values,
                "return": returns.values,
                "sector": sector,
            })

            data_list.append(df_ticker)
            print(f"  ✓ {ticker}: {len(df_ticker)} days")

        except Exception as e:
            print(f"  ✗ Skipping {ticker}: {e}")
            continue

    if not data_list:
        raise ValueError("No data processed!")

    # Combine all
    df = pl.concat(data_list)

    # Remove NaN returns
    df = df.filter(pl.col("return").is_not_nan())

    # Print summary
    print("\n" + "="*80)
    print("DATA SUMMARY")
    print("="*80)
    print(f"Total observations: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].n_unique()}")
    print(f"Unique dates: {df['date'].n_unique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Unique sectors: {df['sector'].n_unique()}")

    sector_summary = df.group_by("sector").agg([
        pl.col("ticker").n_unique().alias("n_tickers"),
        pl.count().alias("n_obs"),
    ]).sort("n_tickers", descending=True)
    print(f"\nSector breakdown:")
    print(sector_summary)

    return df


def save_data(df: pl.DataFrame):
    """Save to parquet."""
    output_path = Path(__file__).parent / "sp500_real_data.parquet"
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    return output_path


if __name__ == "__main__":
    df = download_all_data_batch()
    path = save_data(df)
    print(f"\n✓ Real S&P 500 data ready for validation!")
    print(f"✓ Use this file: {path}")
