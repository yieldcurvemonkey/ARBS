# ABOUTME: Enumeration of currency value types (yield, carry, returns, DV01)
# ABOUTME: Defines what data to retrieve from market data provider

from enum import Enum


class CurrencyValue(Enum):
    """
    Currency value types for data retrieval.

    Specifies what type of data to fetch:
    - YIELD: Zero-coupon yield (spot rate)
    - CARRY: Carry = forward_rate - spot_rate (analogous to dividend yield)
    - RETURN: Simple returns on bond position
    - DV01: Dollar value of 1 basis point (risk measure)
    - FORWARD_RATE: Forward rate implied by curve
    - VOLATILITY: Realized interest rate volatility

    Carry is the primary signal for currency strategies, analogous to
    momentum in equity sectors.
    """

    YIELD = "yield"
    CARRY = "carry"
    RETURN = "return"
    DV01 = "dv01"
    FORWARD_RATE = "forward_rate"
    VOLATILITY = "volatility"
