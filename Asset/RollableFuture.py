# ABOUTME: Futures contract with automatic roll detection and transition handling
# ABOUTME: Tracks current contract, next contract, and roll date for futures chains
"""
RollableFuture - Auto-Rolling Futures Contract

Implements futures contract that automatically detects rolls and generates
AssetTransition events for tracking P&L from calendar spreads.

Used for:
- Quarterly futures with defined roll schedule (ES, NQ, ZN, ZB)
- Monthly futures chains (SOFR, Eurodollar)
- Any futures with predictable roll dates

Roll Logic:
- Before roll_date: Holds current_contract
- On/after roll_date: Triggers AssetTransition from current → next
- P&L impact calculated from calendar spread

Key Difference from PriceFuture:
- PriceFuture: No automatic rolls, user handles explicitly
- RollableFuture: Detects rolls and generates transitions automatically

Example:
    >>> future = RollableFuture(
    ...     current_contract='SFRZ4',
    ...     next_contract='SFRH5',
    ...     roll_date=date(2024, 12, 10)
    ... )
    >>> market_data = {'price': 95.0, 'next_price': 94.95}
    >>> transition = future.detect_transition(date(2024, 12, 10), market_data)
    >>> transition.event_type
    'roll'
    >>> transition.pnl_impact  # (94.95 - 95.0) / 95.0
    -0.000526...
"""

from datetime import date
from typing import Optional, Dict, Any

from Asset.Base import Asset, AssetTransition


class RollableFuture(Asset):
    """
    Futures contract with automatic roll detection.

    Tracks current contract, next contract to roll into, and roll date.
    Generates AssetTransition when roll occurs, capturing P&L from
    calendar spread.

    Attributes:
        current_contract: Front month contract (e.g., 'SFRZ4')
        next_contract: Next contract to roll into (e.g., 'SFRH5')
        roll_date: Date to execute roll
        roll_days_before_expiry: Alternative: roll N days before expiry

    Roll P&L:
        - Backwardation (next < current): Positive carry, negative P&L impact
        - Contango (next > current): Negative carry, positive P&L impact
        - P&L = (next_price - current_price) / current_price

    Example:
        Current SFRZ4 at 95.00, next SFRH5 at 94.95
        → Backwardation: next is cheaper
        → Roll P&L = (94.95 - 95.00) / 95.00 = -0.000526 (-5.26bp cost)
    """

    def __init__(
        self,
        current_contract: str,
        next_contract: str,
        roll_date: date,
        roll_days_before_expiry: int = 5
    ):
        """
        Initialize rollable future.

        Args:
            current_contract: Current front contract identifier
            next_contract: Next contract to roll into
            roll_date: Date when roll occurs
            roll_days_before_expiry: Alternative roll timing (default 5 days)

        Example:
            RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        """
        if not current_contract:
            raise ValueError("current_contract cannot be empty")
        if not next_contract:
            raise ValueError("next_contract cannot be empty")

        self.current_contract = current_contract
        self.next_contract = next_contract
        self.roll_date = roll_date
        self.roll_days_before_expiry = roll_days_before_expiry

    def get_identifier(self) -> str:
        """
        Return current contract identifier.

        Always returns current_contract (front month).
        After roll is detected, user should update to next contract.

        Returns:
            Current contract string (e.g., 'SFRZ4')
        """
        return self.current_contract

    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Calculate return on current contract.

        Same logic as PriceFuture: simple price return.
        Roll handling is separate (via detect_transition).

        Args:
            prev_price: Price at t-1
            curr_price: Price at t
            **kwargs: Ignored

        Returns:
            Return as decimal

        Example:
            prev=95.0, curr=96.0 → return=0.0105263
        """
        if prev_price <= 0:
            return 0.0
        return (curr_price - prev_price) / prev_price

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect if roll occurs on this date.

        Checks if as_of >= roll_date. If so, generates AssetTransition
        describing the roll with P&L from calendar spread.

        Args:
            as_of: Current date to check
            market_data: Dict containing:
                - 'price': Current contract price (default 0.0)
                - 'next_price': Next contract price (defaults to price)

        Returns:
            AssetTransition if roll occurs, None otherwise

        AssetTransition fields:
            - event_type: 'roll'
            - date: as_of
            - from_asset: current_contract
            - to_asset: next_contract
            - pnl_impact: (next_price - current_price) / current_price
            - metadata: {'current_price', 'next_price', 'roll_spread'}

        Example:
            as_of=2024-12-10, roll_date=2024-12-10
            market_data={'price': 95.0, 'next_price': 94.95}
            → AssetTransition(
                event_type='roll',
                from_asset='SFRZ4',
                to_asset='SFRH5',
                pnl_impact=-0.000526,
                metadata={'current_price': 95.0, 'next_price': 94.95,
                         'roll_spread': -0.05}
            )
        """
        # Check if roll should occur
        if as_of < self.roll_date:
            return None

        # Roll occurring - extract prices
        curr_price = market_data.get('price', 0.0)
        next_price = market_data.get('next_price', curr_price)

        # Calculate P&L from roll spread
        if curr_price > 0:
            roll_pnl = (next_price - curr_price) / curr_price
        else:
            roll_pnl = 0.0

        # Calculate roll spread (basis points)
        roll_spread = next_price - curr_price

        return AssetTransition(
            event_type='roll',
            date=as_of,
            from_asset=self.current_contract,
            to_asset=self.next_contract,
            pnl_impact=roll_pnl,
            metadata={
                'current_price': curr_price,
                'next_price': next_price,
                'roll_spread': roll_spread
            }
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"RollableFuture('{self.current_contract}' → "
                f"'{self.next_contract}' on {self.roll_date})")
