# ABOUTME: Yahoo Finance market data provider package for equity data
# ABOUTME: Includes sector mapping and GICS classification utilities

"""
Yahoo Finance Market Data Provider

This package provides Yahoo Finance integration for equity market data:
- Sector classification (GICS Level 1)
- SPDR Select Sector ETF mapping
- Future: YahooFinanceMDP class for price/returns data
"""

from .sector_mapping import (
    GICS_SECTORS,
    SECTOR_ETFS,
    ETF_TO_SECTOR,
    SP500_SECTOR_WEIGHTS,
    TICKER_TO_SECTOR,
    get_sector_for_ticker,
    get_sector_etf,
    get_etf_sector,
    get_gics_code,
    get_sector_weight,
    validate_sector_mapping,
)

__all__ = [
    "GICS_SECTORS",
    "SECTOR_ETFS",
    "ETF_TO_SECTOR",
    "SP500_SECTOR_WEIGHTS",
    "TICKER_TO_SECTOR",
    "get_sector_for_ticker",
    "get_sector_etf",
    "get_etf_sector",
    "get_gics_code",
    "get_sector_weight",
    "validate_sector_mapping",
]
