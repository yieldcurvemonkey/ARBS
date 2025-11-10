"""
Futures Value Enum

Defines the types of values that can be calculated for futures:
- PRICE: Futures price (e.g., 94.50)
- IMPLIED_RATE: 100 - Price (e.g., 5.50%)
- NPV: Mark-to-market in dollars
- DV01: Dollar value of 1bp move
- MARGIN: Margin requirement (initial or variation)
- BASIS: Futures vs swap basis in bps
- CONVEXITY_ADJ: Convexity adjustment (futures vs FRA)
- CARRY: Expected carry over roll period

Follows the pattern of IRSwapValue for consistency.
"""

from enum import Enum, auto


class FuturesValue(Enum):
    """
    Futures value metrics.

    Examples:
        PRICE: 94.50 (Eurodollar futures price)
        IMPLIED_RATE: 5.50% (100 - 94.50)
        NPV: $1,250 (price change * multiplier * quantity)
        DV01: $25 per contract per bp for Eurodollar
        MARGIN: $1,500 per contract (initial margin)
        BASIS: 5.2 bps (futures implied rate - swap rate)
        CONVEXITY_ADJ: 2.5 bps (futures-FRA convexity)
        CARRY: 3.1 bps (expected carry over 1 month)
    """
    PRICE = auto()           # Futures price (e.g., 94.50)
    IMPLIED_RATE = auto()    # 100 - Price (e.g., 5.50%)
    NPV = auto()             # Mark-to-market in dollars
    DV01 = auto()            # Dollar value of 1bp move
    GAMMA = auto()           # Second-order sensitivity
    MARGIN = auto()          # Margin requirement
    BASIS = auto()           # vs equivalent swap (in bps)
    CONVEXITY_ADJ = auto()   # Futures-FRA convexity adjustment
    CARRY = auto()           # Expected carry over period
