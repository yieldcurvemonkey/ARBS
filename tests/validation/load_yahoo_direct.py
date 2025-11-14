#!/usr/bin/env python3
# ABOUTME: Loads S&P 500 stock data directly from Yahoo Finance API
# ABOUTME: Creates cached parquet file for portfolio validation

"""
Direct Yahoo Finance API Data Loader

Uses Yahoo Finance chart API directly without yfinance dependency.
Implements proper batching and rate limiting to avoid 429 errors.
"""

import time
import json
import requests
import polars as pl
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Yahoo Finance API endpoints
CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# S&P 500 tickers by sector (subset for faster loading)
TICKERS_BY_SECTOR = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META"],
    "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
    "Healthcare": ["UNH", "JNJ", "LLY", "ABBV", "MRK"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "Industrials": ["UNP", "HON", "CAT", "BA", "RTX"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT", "COST"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP"],
}

# Date range
START_DATE = "2015-01-01"
END_DATE = "2023-12-31"

# Rate limiting
REQUESTS_PER_BATCH = 10
DELAY_BETWEEN_BATCHES = 3.0  # seconds
DELAY_BETWEEN_REQUESTS = 0.5  # seconds


def get_yahoo_data(ticker: str, start_date: str, end_date: str) -> Optional[Dict]:
    """
    Fetch historical price data from Yahoo Finance API.

    Args:
        ticker: Stock ticker symbol
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Dictionary with dates, closes, or None if failed
    """
    # Convert dates to Unix timestamps
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp())

    url = CHART_API.format(ticker=ticker)
    params = {
        "period1": start_ts,
        "period2": end_ts,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Extract data from response
        chart = data.get("chart", {})
        result = chart.get("result", [])

        if not result:
            return None

        result = result[0]
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        closes = quotes.get("close", [])

        if not timestamps or not closes:
            return None

        # Convert timestamps to dates
        dates = [datetime.fromtimestamp(ts).strftime("%Y-%m-%d") for ts in timestamps]

        return {"dates": dates, "closes": closes}

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"  ⚠ Rate limited on {ticker}, waiting 10s...")
            time.sleep(10)
            return None
        else:
            print(f"  ✗ HTTP error for {ticker}: {e}")
            return None
    except Exception as e:
        print(f"  ✗ Error for {ticker}: {e}")
        return None


def calculate_returns(closes: List[float]) -> List[Optional[float]]:
    """Calculate daily returns from close prices."""
    returns = [None]  # First return is null (no previous price)

    for i in range(1, len(closes)):
        if closes[i] is not None and closes[i-1] is not None:
            ret = (closes[i] / closes[i-1]) - 1.0
            returns.append(ret)
        else:
            returns.append(None)

    return returns


def load_all_tickers() -> pl.DataFrame:
    """
    Load data for all tickers with proper rate limiting.

    Returns:
        Polars DataFrame with columns [ticker, date, close, return, sector]
    """
    all_data = []
    request_count = 0

    print("\nYAHOO FINANCE DIRECT LOADER")
    print("=" * 80)
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Total tickers: {sum(len(tickers) for tickers in TICKERS_BY_SECTOR.values())}")
    print(f"Rate limiting: {REQUESTS_PER_BATCH} requests per batch, {DELAY_BETWEEN_BATCHES}s delay\n")

    for sector, tickers in TICKERS_BY_SECTOR.items():
        print(f"[{sector}]")

        for ticker in tickers:
            # Rate limiting - pause between batches
            if request_count > 0 and request_count % REQUESTS_PER_BATCH == 0:
                print(f"  → Batch complete, waiting {DELAY_BETWEEN_BATCHES}s...")
                time.sleep(DELAY_BETWEEN_BATCHES)

            # Small delay between individual requests
            if request_count > 0:
                time.sleep(DELAY_BETWEEN_REQUESTS)

            # Fetch data
            data = get_yahoo_data(ticker, START_DATE, END_DATE)
            request_count += 1

            if data is None:
                print(f"  ✗ {ticker}: Failed to fetch data")
                continue

            dates = data["dates"]
            closes = data["closes"]
            returns = calculate_returns(closes)

            # Create records
            for date, close, ret in zip(dates, closes, returns):
                if close is not None:  # Skip null prices
                    all_data.append({
                        "ticker": ticker,
                        "date": date,
                        "close": close,
                        "return": ret,
                        "sector": sector,
                    })

            print(f"  ✓ {ticker}: {len(dates)} days")

        print()  # Blank line between sectors

    # Convert to DataFrame
    df = pl.DataFrame(all_data)

    # Sort by ticker and date
    df = df.sort(["ticker", "date"])

    return df


def main():
    """Main entry point."""
    output_file = Path(__file__).parent / "sp500_real_data.parquet"

    print("\n" + "=" * 80)
    print("LOADING S&P 500 DATA FROM YAHOO FINANCE")
    print("=" * 80)

    # Load data
    start_time = time.time()
    df = load_all_tickers()
    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 80)
    print("DATA SUMMARY")
    print("=" * 80)
    print(f"Total observations: {len(df):,}")
    print(f"Tickers: {df['ticker'].n_unique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Sectors: {df['sector'].n_unique()}")
    print(f"Loading time: {elapsed:.1f}s")

    # Save to parquet
    df.write_parquet(output_file)
    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    print(f"\n✓ Saved to {output_file}")
    print(f"  File size: {file_size_mb:.2f} MB")

    # Show sample
    print("\n" + "=" * 80)
    print("SAMPLE DATA (first 10 rows)")
    print("=" * 80)
    print(df.head(10))

    print("\n" + "=" * 80)
    print("✓ DATA LOADING COMPLETE")
    print("=" * 80)
    print(f"\nNext step: python tests/validation/validate_on_real_data.py")


if __name__ == "__main__":
    main()
