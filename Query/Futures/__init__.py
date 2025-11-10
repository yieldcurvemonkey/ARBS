# ABOUTME: Futures query module for backtesting infrastructure
# ABOUTME: Provides FuturesQuery, FuturesStructure (outright/calendar/pack/bundle), and FuturesValue (price/DV01/NPV)
"""
Futures Query Module

Provides product adapter for futures backtesting:
- FuturesQuery: Main query object
- FuturesStructure: Structure types (outright, calendar, pack, bundle, basis)
- FuturesValue: Value metrics (price, DV01, margin, carry, basis)

Follows the same pattern as Query/IRSwaps for consistency.
"""

from Query.Futures.FuturesQuery import FuturesQuery
from Query.Futures.FuturesStructure import FuturesStructure
from Query.Futures.FuturesValue import FuturesValue

__all__ = [
    "FuturesQuery",
    "FuturesStructure",
    "FuturesValue",
]
