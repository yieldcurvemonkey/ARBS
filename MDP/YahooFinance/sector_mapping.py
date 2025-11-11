# ABOUTME: GICS sector classification and SPDR ETF mapping for equity MVP
# ABOUTME: Provides sector lookup for tickers and S&P 500 sector weight reference data

"""
GICS Sector Mapping and Reference Data

This module provides GICS Level 1 sector classification data for equity analysis:
- 11 GICS sectors with official codes
- SPDR Select Sector ETF mapping (1:1 correspondence)
- Approximate S&P 500 sector weights
- Ticker-to-sector lookup for MVP testing

Data Sources:
- GICS classification: MSCI/S&P Global
- SPDR ETFs: State Street Select Sector SPDRs
- Sector weights: Approximate S&P 500 composition (2025)

For detailed research, see: docs/research/SECTOR_ETF_MAPPING.md
"""

from typing import Optional

# GICS Level 1 Sectors (code → name)
# Source: MSCI GICS Structure (2025)
GICS_SECTORS = {
    10: "Energy",
    15: "Materials",
    20: "Industrials",
    25: "Consumer Discretionary",
    30: "Consumer Staples",
    35: "Health Care",
    40: "Financials",
    45: "Information Technology",
    50: "Communication Services",
    55: "Utilities",
    60: "Real Estate",
}

# SPDR Select Sector ETFs (sector name → ticker)
# Source: State Street Select Sector SPDRs
# Note: Perfect 1:1 mapping to GICS Level 1 sectors
SECTOR_ETFS = {
    "Energy": "XLE",
    "Materials": "XLB",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Information Technology": "XLK",
    "Communication Services": "XLC",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
}

# Reverse mapping: ticker → sector name
ETF_TO_SECTOR = {ticker: sector for sector, ticker in SECTOR_ETFS.items()}

# Approximate S&P 500 sector weights (%)
# Source: S&P 500 composition as of November 2025 (approximate)
# Note: Weights fluctuate with market movements
SP500_SECTOR_WEIGHTS = {
    "Information Technology": 29.5,
    "Financials": 13.2,
    "Health Care": 12.8,
    "Consumer Discretionary": 10.4,
    "Communication Services": 9.1,
    "Industrials": 8.3,
    "Consumer Staples": 6.1,
    "Energy": 4.2,
    "Utilities": 2.4,
    "Real Estate": 2.3,
    "Materials": 2.2,
}

# Hardcoded ticker-to-sector mapping for MVP testing
# Note: This is a small sample (~20 stocks) for initial development
# Production implementation should use comprehensive GICS classification data
# or fetch from data provider (e.g., Yahoo Finance industry field)
TICKER_TO_SECTOR = {
    # Information Technology (29.5%)
    "AAPL": "Information Technology",
    "MSFT": "Information Technology",
    "GOOGL": "Information Technology",
    "NVDA": "Information Technology",

    # Financials (13.2%)
    "JPM": "Financials",
    "BAC": "Financials",
    "GS": "Financials",
    "WFC": "Financials",

    # Health Care (12.8%)
    "JNJ": "Health Care",
    "UNH": "Health Care",
    "PFE": "Health Care",
    "ABBV": "Health Care",

    # Consumer Discretionary (10.4%)
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary",

    # Energy (4.2%)
    "XOM": "Energy",
    "CVX": "Energy",

    # Sector ETFs (include for unified handling)
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLI": "Industrials",
    "XLU": "Utilities",
    "XLP": "Consumer Staples",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}


def get_sector_for_ticker(ticker: str) -> Optional[str]:
    """
    Get GICS Level 1 sector name for a ticker symbol.

    Args:
        ticker: Stock or ETF ticker symbol (e.g., "AAPL", "XLK")

    Returns:
        Sector name (e.g., "Information Technology") or None if unknown

    Examples:
        >>> get_sector_for_ticker("AAPL")
        'Information Technology'
        >>> get_sector_for_ticker("XLK")
        'Information Technology'
        >>> get_sector_for_ticker("UNKNOWN")
        None

    Notes:
        - For MVP, uses hardcoded mapping of ~20 well-known tickers
        - Production should integrate with comprehensive GICS data source
        - Consider using Yahoo Finance industry classification or other data provider
    """
    return TICKER_TO_SECTOR.get(ticker.upper())


def get_sector_etf(sector_name: str) -> Optional[str]:
    """
    Get SPDR Select Sector ETF ticker for a GICS sector name.

    Args:
        sector_name: GICS Level 1 sector name (e.g., "Information Technology")

    Returns:
        ETF ticker (e.g., "XLK") or None if unknown sector

    Examples:
        >>> get_sector_etf("Information Technology")
        'XLK'
        >>> get_sector_etf("Financials")
        'XLF'

    Notes:
        - 1:1 mapping between 11 GICS sectors and 11 SPDR ETFs
        - All ETFs have 0.08% expense ratio and high liquidity
        - See docs/research/SECTOR_ETF_MAPPING.md for details
    """
    return SECTOR_ETFS.get(sector_name)


def get_etf_sector(ticker: str) -> Optional[str]:
    """
    Get GICS sector for a SPDR Select Sector ETF ticker.

    Args:
        ticker: ETF ticker symbol (e.g., "XLK", "XLF")

    Returns:
        Sector name (e.g., "Information Technology") or None if not a sector ETF

    Examples:
        >>> get_etf_sector("XLK")
        'Information Technology'
        >>> get_etf_sector("XLF")
        'Financials'
        >>> get_etf_sector("SPY")
        None
    """
    return ETF_TO_SECTOR.get(ticker.upper())


def get_gics_code(sector_name: str) -> Optional[int]:
    """
    Get GICS code for a sector name.

    Args:
        sector_name: GICS Level 1 sector name (e.g., "Information Technology")

    Returns:
        GICS code (e.g., 45) or None if unknown sector

    Examples:
        >>> get_gics_code("Information Technology")
        45
        >>> get_gics_code("Energy")
        10
    """
    for code, name in GICS_SECTORS.items():
        if name == sector_name:
            return code
    return None


def get_sector_weight(sector_name: str) -> Optional[float]:
    """
    Get approximate S&P 500 weight for a sector.

    Args:
        sector_name: GICS Level 1 sector name

    Returns:
        Approximate weight in S&P 500 (%) or None if unknown

    Examples:
        >>> get_sector_weight("Information Technology")
        29.5
        >>> get_sector_weight("Energy")
        4.2

    Notes:
        - Weights are approximate and fluctuate with market movements
        - Based on S&P 500 composition as of November 2025
        - Sum of all weights equals 100%
    """
    return SP500_SECTOR_WEIGHTS.get(sector_name)


def validate_sector_mapping() -> bool:
    """
    Validate that sector mapping data is internally consistent.

    Returns:
        True if all validations pass

    Raises:
        AssertionError if any validation fails

    Checks:
        - All 11 GICS sectors have ETF mappings
        - All 11 GICS sectors have weight assignments
        - Sector weights sum to approximately 100%
        - Reverse ETF mapping is consistent
    """
    # Check all GICS sectors have ETF mappings
    for sector_name in GICS_SECTORS.values():
        assert sector_name in SECTOR_ETFS, f"Missing ETF for sector: {sector_name}"

    # Check all GICS sectors have weight assignments
    for sector_name in GICS_SECTORS.values():
        assert sector_name in SP500_SECTOR_WEIGHTS, f"Missing weight for sector: {sector_name}"

    # Check sector weights sum to ~100%
    total_weight = sum(SP500_SECTOR_WEIGHTS.values())
    assert 99.0 < total_weight < 101.0, f"Sector weights sum to {total_weight}%, expected ~100%"

    # Check reverse ETF mapping is consistent
    assert len(ETF_TO_SECTOR) == len(SECTOR_ETFS), "ETF reverse mapping size mismatch"
    for ticker, sector in ETF_TO_SECTOR.items():
        assert SECTOR_ETFS[sector] == ticker, f"Inconsistent reverse mapping for {ticker}"

    return True


# Validate on module import
validate_sector_mapping()


# Extension Guide for Production
"""
To extend this module for production use with comprehensive ticker coverage:

1. **Integrate with Data Provider**:
   - Use Yahoo Finance 'sector' field from yfinance
   - Use Bloomberg GICS classification
   - Use other vendor GICS data (FactSet, Refinitiv, etc.)

2. **Dynamic Lookup Function**:
   ```python
   import yfinance as yf

   def get_sector_from_yahoo(ticker: str) -> Optional[str]:
       try:
           stock = yf.Ticker(ticker)
           info = stock.info
           # Yahoo Finance uses different sector names, map to GICS
           yahoo_sector = info.get('sector')
           return map_yahoo_to_gics(yahoo_sector)
       except:
           return None
   ```

3. **Caching Strategy**:
   - Build comprehensive ticker → sector mapping on first use
   - Cache results to avoid repeated API calls
   - Refresh periodically (quarterly GICS rebalances)

4. **Handling Edge Cases**:
   - Newly listed companies (may not have GICS classification immediately)
   - Delisted companies (use historical classification)
   - ETFs and other non-equity instruments (return None or specific handling)

5. **Validation**:
   - Cross-check against multiple data sources
   - Flag discrepancies for manual review
   - Maintain audit trail of classification changes

For MVP, the hardcoded mapping of ~20 tickers is sufficient for testing
the core backtesting architecture.
"""
