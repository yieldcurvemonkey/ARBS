# ABOUTME: Enumeration of currency structure types (outright, butterfly, spread, calendar)
# ABOUTME: Analogous to SINGLE, SECTOR_BASKET for equities

from enum import Enum


class CurrencyStructure(Enum):
    """
    Currency structure types for portfolio construction.

    Similar to futures structures but adapted for currency portfolios:
    - OUTRIGHT: Single tenor point position (e.g., USD 10Y)
    - BUTTERFLY: Curvature trade (e.g., 2s5s10s: 2*(5Y) - (2Y) - (10Y))
    - SPREAD: Slope trade (e.g., 2Y5Y spread: (5Y) - (2Y))
    - CALENDAR: Time spread (e.g., 3M forward 10Y vs spot 10Y)

    Butterfly is the most common relative value trade, analogous to
    sector basket trades in equities (expressing view on curvature).
    """

    OUTRIGHT = "outright"
    BUTTERFLY = "butterfly"
    SPREAD = "spread"
    CALENDAR = "calendar"
