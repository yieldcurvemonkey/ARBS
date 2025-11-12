# ABOUTME: Load S&P 500 data for validation against paper claims
# ABOUTME: Uses YahooFinanceMDP to fetch real market data with proper caching

"""
S&P 500 Data Loader

Loads real market data to validate paper claims:
- Paper 1 (García-Medina): Used S&P 500 constituents
- Paper 2 (Žignić): Used top p US stocks (1995-2017)

This script loads comparable data for validation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import date
import polars as pl
import yfinance as yf
from tqdm import tqdm


def get_sp500_tickers() -> list[str]:
    """
    Get S&P 500 ticker list.

    For initial validation, we'll use a representative subset
    of large-cap stocks across major sectors.
    """
    # Representative S&P 500 stocks across sectors
    # Selected for liquidity and sector diversity
    return [
        # Technology
        "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ADBE", "CRM", "ORCL", "INTC",
        # Financials
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "USB",
        # Healthcare
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY", "AMGN",
        # Consumer Discretionary
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG", "CMG",
        # Communication Services
        "GOOG", "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "CHTR", "EA", "TTWO",
        # Industrials
        "UNP", "HON", "CAT", "BA", "RTX", "UPS", "DE", "LMT", "GE", "MMM",
        # Consumer Staples
        "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "MDLZ", "KHC",
        # Energy
        "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
        # Utilities
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "PEG", "XEL", "ED",
        # Real Estate
        "PLD", "AMT", "EQIX", "PSA", "WELL", "SPG", "O", "DLR", "CBRE", "AVB",
    ]


def load_sp500_data(
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    min_history_days: int = 900,
) -> pl.DataFrame:
    """
    Load S&P 500 data for validation.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        min_history_days: Minimum trading days required

    Returns:
        DataFrame with [ticker, date, return, sector, close]
    """
    tickers = get_sp500_tickers()

    print(f"Loading {len(tickers)} S&P 500 stocks...")
    print(f"Period: {start_date} to {end_date}")
    print(f"Minimum history: {min_history_days} days")
    print()

    data_list = []
    failed_tickers = []

    for ticker in tqdm(tickers, desc="Downloading"):
        try:
            stock = yf.Ticker(ticker)

            # Get price history
            hist = stock.history(start=start_date, end=end_date, auto_adjust=True)

            if len(hist) < min_history_days:
                print(f"  ⚠ Skipping {ticker}: insufficient history ({len(hist)} days)")
                failed_tickers.append((ticker, f"Only {len(hist)} days"))
                continue

            # Calculate returns
            returns = hist["Close"].pct_change()

            # Get sector
            try:
                info = stock.info
                sector = info.get("sector", "Unknown")
                if not sector or sector == "Unknown":
                    print(f"  ⚠ Skipping {ticker}: no sector info")
                    failed_tickers.append((ticker, "No sector"))
                    continue
            except Exception as e:
                print(f"  ⚠ Skipping {ticker}: error getting sector - {e}")
                failed_tickers.append((ticker, "Sector error"))
                continue

            # Build DataFrame
            df_ticker = pl.DataFrame({
                "ticker": ticker,
                "date": [d.strftime("%Y-%m-%d") for d in hist.index],
                "close": hist["Close"].values,
                "return": returns.values,
                "sector": sector,
            })

            data_list.append(df_ticker)

        except Exception as e:
            print(f"  ✗ Failed {ticker}: {e}")
            failed_tickers.append((ticker, str(e)))
            continue

    if not data_list:
        raise ValueError("No data loaded successfully!")

    print(f"\n✓ Loaded {len(data_list)} tickers successfully")
    if failed_tickers:
        print(f"✗ Failed {len(failed_tickers)} tickers")

    # Combine all
    df = pl.concat(data_list)

    # Remove NaN returns (first row per ticker)
    df = df.filter(pl.col("return").is_not_nan())

    print(f"\n=== Data Summary ===")
    print(f"Total observations: {len(df)}")
    print(f"Unique tickers: {df['ticker'].n_unique()}")
    print(f"Unique dates: {df['date'].n_unique()}")
    print(f"Sectors: {df['sector'].n_unique()}")
    print(f"\nSector breakdown:")
    sector_counts = df.group_by("sector").agg(
        pl.col("ticker").n_unique().alias("n_tickers")
    ).sort("n_tickers", descending=True)
    print(sector_counts)

    return df


def save_data(df: pl.DataFrame, filename: str = "sp500_validation_data.parquet"):
    """Save data to parquet for caching."""
    output_path = Path(__file__).parent / filename
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    # Load data matching paper time periods
    # Paper 2 used 1995-2017, we'll use recent 5 years for validation
    df = load_sp500_data(
        start_date="2019-01-01",
        end_date="2024-12-31",
        min_history_days=900,  # ~4 years of trading days
    )

    save_data(df)

    print("\n✓ Data ready for validation!")
