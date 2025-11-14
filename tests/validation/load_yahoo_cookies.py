# ABOUTME: Load S&P 500 data from Yahoo Finance using browser cookies
# ABOUTME: Bypasses rate limits by using authenticated session

"""
Yahoo Finance with Cookies

This approach uses your browser's session cookies to authenticate.
Yahoo allows more requests for authenticated users.

Steps:
1. Visit finance.yahoo.com in your browser
2. Export cookies (use browser extension like "Get cookies.txt")
3. Save to cookies.txt in this directory
4. Run this script

OR use selenium to get fresh cookies automatically.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import polars as pl
import requests
from datetime import datetime
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


def load_cookies(cookie_file: Path) -> dict:
    """Load cookies from Netscape format file."""
    cookies = {}

    if not cookie_file.exists():
        return cookies

    with open(cookie_file) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue

            parts = line.strip().split('\t')
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]

    return cookies


def download_with_session(ticker: str, session: requests.Session) -> pl.DataFrame:
    """Download using authenticated session."""
    start_ts = int(datetime.strptime("2015-01-01", "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime("2023-12-31", "%Y-%m-%d").timestamp())

    url = f"https://query1.finance.yahoo.com/v7/finance/download/{ticker}"
    params = {
        "period1": start_ts,
        "period2": end_ts,
        "interval": "1d",
        "events": "history",
    }

    # Add crumb if we have it
    if hasattr(session, 'crumb'):
        params['crumb'] = session.crumb

    try:
        response = session.get(url, params=params)
        response.raise_for_status()

        from io import StringIO
        df = pl.read_csv(StringIO(response.text))
        return df

    except Exception as e:
        return None


def get_crumb(session: requests.Session) -> str:
    """Get Yahoo Finance crumb for authenticated requests."""
    try:
        response = session.get("https://finance.yahoo.com/quote/AAPL")
        # Extract crumb from page source
        text = response.text

        # Look for crumb in various places
        import re
        match = re.search(r'"crumb":"([^"]+)"', text)
        if match:
            return match.group(1)

        match = re.search(r',"crumb":"([^"]+)",', text)
        if match:
            return match.group(1)

    except:
        pass

    return None


def load_data() -> pl.DataFrame:
    """Load data using session with cookies."""
    print("="*80)
    print("YAHOO FINANCE WITH COOKIES")
    print("="*80)

    # Set up session
    session = requests.Session()

    # Try to load cookies
    cookie_file = Path(__file__).parent / "cookies.txt"
    cookies = load_cookies(cookie_file)

    if cookies:
        print(f"✓ Loaded {len(cookies)} cookies from {cookie_file}")
        for name, value in cookies.items():
            session.cookies.set(name, value)

        # Get crumb
        crumb = get_crumb(session)
        if crumb:
            print(f"✓ Got crumb: {crumb[:10]}...")
            session.crumb = crumb
    else:
        print("⚠ No cookies file found, using unauthenticated session")

    # Set headers
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })

    data_list = []

    for sector, tickers in TICKERS.items():
        print(f"\n[{sector}]")

        for ticker in tickers:
            df = download_with_session(ticker, session)

            if df is None or len(df) < 900:
                print(f"  ⚠ {ticker}: insufficient data")
                continue

            df_final = pl.DataFrame({
                "ticker": pl.lit(ticker),
                "date": df['Date'].cast(pl.Utf8),
                "close": df['Adj Close'],
                "return": df['Adj Close'] / df['Adj Close'].shift(1) - 1,
                "sector": pl.lit(sector),
            })

            data_list.append(df_final)
            print(f"  ✓ {ticker}: {len(df_final)} days")

            time.sleep(0.3)  # Small delay

    if not data_list:
        raise ValueError("No data loaded!")

    df = pl.concat(data_list).filter(pl.col("return").is_not_nan())

    print(f"\n{'='*80}")
    print(f"Loaded {df['ticker'].n_unique()} tickers, {len(df):,} observations")

    return df


if __name__ == "__main__":
    df = load_data()

    output_path = Path(__file__).parent / "sp500_real_data.parquet"
    df.write_parquet(output_path)
    print(f"\n✓ Saved to {output_path}")
