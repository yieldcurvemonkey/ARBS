# ABOUTME: Enumeration of equity structure types (single stock, baskets, long/short)
# ABOUTME: Analogous to OUTRIGHT, CALENDAR, FLY for futures

from enum import Enum


class EquityStructure(Enum):
    """
    Equity structure types for portfolio construction.

    Similar to futures structures but adapted for equity portfolios:
    - SINGLE: Individual stock position
    - SECTOR_BASKET: Equal-weight basket within a sector
    - LONG_SHORT: Pairs trade (long one stock, short another)
    - MARKET_NEUTRAL: Long stocks, short market/sector ETF
    """

    SINGLE = "single"
    SECTOR_BASKET = "sector_basket"
    LONG_SHORT = "long_short"
    MARKET_NEUTRAL = "market_neutral"
