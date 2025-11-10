"""
Futures Structure Enum

Defines the types of futures structures that can be traded:
- OUTRIGHT: Single contract
- CALENDAR: Front - Back spread (e.g., Z4-H5)
- PACK: 4 consecutive quarterly contracts (Red, Green, Blue, Gold)
- BUNDLE: 8 consecutive quarterly contracts
- BASIS: Futures vs matched-maturity swap

Follows the pattern of IRSwapStructure for consistency.
"""

from enum import Enum, auto


class FuturesStructure(Enum):
    """
    Futures structure types.

    Examples:
        OUTRIGHT: Long 10 EDZ4 contracts
        CALENDAR: Long EDH5, Short EDZ4 (Mar 25 - Dec 24)
        PACK: Red pack = 4 consecutive contracts (H5, M5, U5, Z5)
        BUNDLE: 8 consecutive contracts
        BASIS: Long EDZ4 future, short matched 3M swap
    """
    OUTRIGHT = auto()    # Single contract
    CALENDAR = auto()    # Front - Back spread
    PACK = auto()        # 4 consecutive contracts
    BUNDLE = auto()      # 8 consecutive contracts
    BASIS = auto()       # Future vs Swap
