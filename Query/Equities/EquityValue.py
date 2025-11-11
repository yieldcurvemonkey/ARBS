# ABOUTME: Enumeration of equity value types (price, returns, yields, fundamentals)
# ABOUTME: Defines what data to retrieve from market data provider

from enum import Enum


class EquityValue(Enum):
    """
    Equity value types for data retrieval.

    Specifies what type of data to fetch:
    - PRICE: Stock price (adjusted for splits/dividends)
    - RETURN: Simple returns
    - LOG_RETURN: Log returns (for geometric compounding)
    - DIVIDEND_YIELD: Dividend yield (annual dividends / price)
    - EARNINGS_YIELD: E/P ratio (inverse of P/E)
    - VOLATILITY: Realized volatility
    """

    PRICE = "price"
    RETURN = "return"
    LOG_RETURN = "log_return"
    DIVIDEND_YIELD = "dividend_yield"
    EARNINGS_YIELD = "earnings_yield"
    VOLATILITY = "volatility"
