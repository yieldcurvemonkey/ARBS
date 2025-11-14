# ABOUTME: Load S&P 500 data from manually downloaded CSV files
# ABOUTME: Works with data from Yahoo Finance, Google Finance, or any CSV export

"""
Manual CSV Data Loader

If automated downloads fail, you can:
1. Manually download data from finance.yahoo.com (Export > Download Data)
2. Or use Google Sheets + GOOGLEFINANCE() function
3. Or get data from your broker

Place CSV files in: tests/validation/data/
Format expected: Date,Open,High,Low,Close,Adj Close,Volume
Filename: {TICKER}.csv (e.g., AAPL.csv)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import polars as pl
from glob import glob

SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "GOOGL": "Technology", "META": "Technology",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials",
    # Healthcare
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary", "NKE": "Consumer Discretionary",
    # Industrials
    "UNP": "Industrials", "HON": "Industrials", "CAT": "Industrials",
    "BA": "Industrials", "RTX": "Industrials",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "WMT": "Consumer Staples", "COST": "Consumer Staples",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy", "EOG": "Energy",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities", "AEP": "Utilities",
}


def load_csv_file(filepath: Path) -> tuple:
    """Load single CSV file."""
    ticker = filepath.stem.upper()

    try:
        df = pl.read_csv(filepath)

        # Handle different date column names
        date_col = None
        for col in ['Date', 'date', 'DATE', 'Timestamp', 'timestamp']:
            if col in df.columns:
                date_col = col
                break

        if not date_col:
            print(f"  ⚠ {ticker}: No date column found")
            return None, None

        # Handle different close column names
        close_col = None
        for col in ['Adj Close', 'Adj. Close', 'Adjusted Close', 'Close', 'close']:
            if col in df.columns:
                close_col = col
                break

        if not close_col:
            print(f"  ⚠ {ticker}: No close price column found")
            return None, None

        # Parse dates and filter date range
        df = df.with_columns(
            pl.col(date_col).str.to_datetime().alias('date_parsed')
        ).filter(
            (pl.col('date_parsed') >= pl.datetime(2015, 1, 1)) &
            (pl.col('date_parsed') <= pl.datetime(2023, 12, 31))
        )

        if len(df) < 900:
            print(f"  ⚠ {ticker}: insufficient data ({len(df)} days)")
            return None, None

        # Calculate returns
        df = df.sort('date_parsed').with_columns(
            (pl.col(close_col) / pl.col(close_col).shift(1) - 1).alias('return')
        )

        # Create final DataFrame
        df_final = pl.DataFrame({
            "ticker": pl.lit(ticker),
            "date": df['date_parsed'].dt.strftime('%Y-%m-%d'),
            "close": df[close_col],
            "return": df['return'],
            "sector": pl.lit(SECTOR_MAP.get(ticker, "Unknown")),
        })

        return ticker, df_final

    except Exception as e:
        print(f"  ✗ {ticker}: {e}")
        return None, None


def load_data() -> pl.DataFrame:
    """Load all CSV files from data directory."""
    print("="*80)
    print("MANUAL CSV DATA LOADER")
    print("="*80)

    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(exist_ok=True)

    print(f"\nData directory: {data_dir}")
    print(f"Place CSV files here: {data_dir}/*.csv\n")

    # Find all CSV files
    csv_files = list(data_dir.glob("*.csv"))

    if not csv_files:
        print("⚠ No CSV files found!")
        print("\nTo use this loader:")
        print("1. Download data from finance.yahoo.com")
        print("2. Save as {TICKER}.csv (e.g., AAPL.csv)")
        print(f"3. Place in {data_dir}/")
        print("4. Run this script again")
        return None

    print(f"Found {len(csv_files)} CSV files")

    data_list = []

    for filepath in sorted(csv_files):
        ticker, df = load_csv_file(filepath)

        if df is not None:
            data_list.append(df)
            print(f"  ✓ {ticker}: {len(df)} days")

    if not data_list:
        raise ValueError("No valid data loaded!")

    df = pl.concat(data_list).filter(pl.col("return").is_not_nan())

    print(f"\n{'='*80}")
    print(f"Loaded {df['ticker'].n_unique()} tickers, {len(df):,} observations")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    return df


if __name__ == "__main__":
    df = load_data()

    if df is not None:
        output_path = Path(__file__).parent / "sp500_real_data.parquet"
        df.write_parquet(output_path)
        print(f"\n✓ Saved to {output_path}")
