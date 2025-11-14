# ABOUTME: Futures contract with price-based return calculation
# ABOUTME: Used for SOFR futures, equity index futures, commodities priced as $/unit
"""
PriceFuture - Price-Based Futures Contract

Implements futures contract with percentage price returns:
    return = (P_t - P_{t-1}) / P_{t-1}

Used for:
- SOFR futures (priced as 100 - rate)
- Equity index futures (priced as index level)
- Commodity futures (priced as $/unit)

Does NOT handle:
- Automatic rolls (use RollableFuture instead)
- DV01 sensitivity (use YieldInstrument instead)
- Complex corporate actions

Stateless return calculation without corporate action handling.
"""

from datetime import date
from typing import Optional, Dict, Any

from Asset.Base import Asset, AssetTransition


class PriceFuture(Asset):
    """
    Futures contract with price-based returns.

    Calculates returns as percentage price change:
        r_t = (P_t - P_{t-1}) / P_{t-1}

    No corporate actions - user must handle rolls explicitly if needed.

    Attributes:
        contract: Contract identifier (e.g., 'SFRZ4')

    Example:
        >>> future = PriceFuture('SFRZ4')
        >>> future.calculate_return(prev_price=95.0, curr_price=95.10)
        0.0010526315789473684  # 0.105% return
    """

    def __init__(self, contract: str):
        """
        Initialize price future.

        Args:
            contract: Contract identifier (e.g., 'SFRZ4', 'ESZ24')

        Raises:
            ValueError: If contract is empty string
        """
        if not contract:
            raise ValueError("Contract identifier cannot be empty")
        self.contract = contract

    def get_identifier(self) -> str:
        """
        Return contract identifier.

        Returns:
            Contract string (e.g., 'SFRZ4')
        """
        return self.contract

    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Calculate simple price return.

        Formula: r = (P_t - P_{t-1}) / P_{t-1}

        Args:
            prev_price: Price at t-1
            curr_price: Price at t
            **kwargs: Ignored (for interface compatibility)

        Returns:
            Return as decimal (e.g., 0.01 for 1%)

        Edge cases:
            - prev_price <= 0: Returns 0.0
            - prev_price = curr_price: Returns 0.0
            - curr_price = 0: Returns -1.0 (total loss)

        Example:
            prev_price=95.00, curr_price=95.10
            → return = (95.10 - 95.00) / 95.00
                     = 0.10 / 95.00
                     = 0.001053  (0.105%)
        """
        if prev_price <= 0:
            # Can't calculate return from zero/negative price
            return 0.0

        return (curr_price - prev_price) / prev_price

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect corporate actions (always None for PriceFuture).

        PriceFuture has no automatic transitions. User must explicitly
        handle rolls or expiries at the portfolio level.

        Args:
            as_of: Current date (ignored)
            market_data: Market data (ignored)

        Returns:
            None (no automatic transitions)

        Note:
            Use RollableFuture if you need automatic roll handling.
        """
        return None
