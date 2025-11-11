# ABOUTME: Abstract base class for all tradable assets with polymorphic return calculation
# ABOUTME: Defines interface for calculating returns and detecting corporate actions (rolls, expiries)
"""
Asset Abstraction

Provides polymorphic interface for different asset types to calculate returns
and handle corporate actions.

Key concepts:
- Polymorphism: Each asset type encapsulates its own return logic
- Corporate actions: Rolls, expiries, dividends handled via AssetTransition
- Composition: Backtest composes Asset objects without hardcoding logic

Design principles:
- Single Responsibility: Each asset knows only its own behavior
- Open/Closed: New assets added without modifying backtest
- Liskov Substitution: All Asset subclasses are interchangeable
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, Any


@dataclass
class AssetTransition:
    """
    Represents a corporate action or lifecycle event.

    Used to track:
    - Futures rolls (SFRZ4 → SFRH5)
    - Contract expiries
    - Dividends, splits, etc.

    Attributes:
        event_type: Type of event ('roll', 'expiry', 'dividend')
        date: Date when event occurs
        from_asset: Original asset identifier
        to_asset: New asset identifier (None if expiry)
        pnl_impact: P&L impact from the transition (decimal)
        metadata: Additional event-specific data

    Example:
        Roll from SFRZ4 to SFRH5:
        AssetTransition(
            event_type='roll',
            date=date(2024, 12, 10),
            from_asset='SFRZ4',
            to_asset='SFRH5',
            pnl_impact=-0.000526,  # -5.26bp roll cost
            metadata={'spread': -0.05, 'reason': 'quarterly_roll'}
        )
    """
    event_type: str
    date: date
    from_asset: str
    to_asset: Optional[str]
    pnl_impact: float
    metadata: Dict[str, Any]


class Asset(ABC):
    """
    Abstract base class for all tradable assets.

    Each asset type encapsulates:
    1. Return calculation from price changes
    2. Corporate action detection (rolls, expiries)
    3. Metadata (identifier, type, properties)

    Design:
    - Abstract methods enforce interface contract
    - Subclasses implement asset-specific logic
    - Backtest uses polymorphism to handle all asset types uniformly

    Subclasses:
    - PriceFuture: Simple price-based returns
    - RollableFuture: Automatic roll handling
    - YieldInstrument: DV01-based returns for bonds/swaps
    """

    @abstractmethod
    def get_identifier(self) -> str:
        """
        Return unique identifier for this asset.

        Used as key in portfolios, DataFrames, etc.

        Returns:
            Unique string identifier

        Examples:
            - Futures: 'SFRZ4', 'ESH25'
            - Swaps: 'USD_IRS_10Y'
            - Bonds: 'UST_10Y_4.5_2034'
        """
        pass

    @abstractmethod
    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Calculate return from price change.

        Each asset type implements its own return calculation:
        - Price futures: (P_t - P_{t-1}) / P_{t-1}
        - Yield instruments: -(Y_t - Y_{t-1}) × DV01 / notional
        - Custom logic for complex instruments

        Args:
            prev_price: Price/yield at t-1
            curr_price: Price/yield at t
            **kwargs: Asset-specific parameters (DV01, notional, etc.)

        Returns:
            Return as decimal (e.g., 0.01 for 1%)

        Raises:
            ValueError: If prices are invalid

        Examples:
            Price future:
                prev=95.0, curr=96.0 → return=0.0105263 (1.05%)

            Yield instrument (DV01=8.5):
                prev=5.0%, curr=5.1% → return=-0.0085 (-0.85%)
        """
        pass

    @abstractmethod
    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect if corporate action occurs on this date.

        Checks if asset has lifecycle event (roll, expiry, etc.) and
        returns AssetTransition describing the event.

        Args:
            as_of: Current date to check
            market_data: Dict with prices, next contracts, etc.
                        Contents depend on asset type

        Returns:
            AssetTransition if event occurs, None otherwise

        Examples:
            RollableFuture on roll_date:
                → AssetTransition(event_type='roll', ...)

            PriceFuture (no transitions):
                → None

            Expired contract:
                → AssetTransition(event_type='expiry', to_asset=None)
        """
        pass

    def get_asset_type(self) -> str:
        """
        Return asset type name.

        Returns:
            Class name as string (e.g., 'PriceFuture')

        Used for:
        - Logging and debugging
        - Type-specific behavior in backtest
        - Reporting and analytics
        """
        return self.__class__.__name__

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.get_asset_type()}('{self.get_identifier()}')"
