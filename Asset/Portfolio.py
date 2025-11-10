# ABOUTME: Portfolio class implementing Asset interface as composite for nested portfolios
# ABOUTME: Enables portfolio composition using Composite Pattern with polymorphic return calculation
"""
Portfolio - Composite Asset

Implements Asset interface as composite containing multiple positions.

Key insight: Portfolio IS-A Asset, enabling:
- Uniform treatment (Portfolio and PriceFuture both are Assets)
- Composition (Portfolio contains Positions which contain Assets)
- Recursion (Portfolio can contain Portfolio)
- Nesting (arbitrary depth: Portfolio → Portfolio → Asset)

Return calculation:
- Portfolio return = Σ(weight_i × return_i)
- Delegates to constituent assets via polymorphism
- Works recursively for nested portfolios

Architecture:
```
Portfolio (implements Asset)
├── Position 1 → Asset A (PriceFuture)
├── Position 2 → Asset B (RollableFuture)
└── Position 3 → Asset C (Portfolio!)  ← Recursion
                  ├── Position → Asset D
                  └── Position → Asset E
```

Example:
    Simple portfolio:
    >>> asset1 = PriceFuture('SFRZ4')
    >>> asset2 = PriceFuture('SFRH5')
    >>> port = Portfolio('CARRY_PORT', [
    ...     Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
    ...     Position(asset2, 0.4, 94.9, date(2024, 11, 1))
    ... ])
    >>> prev = {'SFRZ4': 95.0, 'SFRH5': 94.9}
    >>> curr = {'SFRZ4': 96.0, 'SFRH5': 95.2}
    >>> port.calculate_return(prev, curr)
    0.008444...

    Nested portfolio:
    >>> sub_port = Portfolio('EQUITY', [...])
    >>> main_port = Portfolio('BALANCED', [
    ...     Position(sub_port, 0.6, 100.0, ...),  # Portfolio as Asset!
    ...     Position(bond_asset, 0.4, 100.0, ...)
    ... ])
"""

from typing import List, Dict, Any, Optional
from datetime import date

from Asset.Base import Asset, AssetTransition
from Asset.Position import Position


class Portfolio(Asset):
    """
    Composite asset containing multiple positions.

    Portfolio implements Asset interface, enabling:
    - Use wherever Asset is expected
    - Nested portfolios (portfolios of portfolios)
    - Polymorphic return calculation
    - Uniform treatment with atomic assets

    Attributes:
        identifier: Portfolio name (e.g., 'BALANCED_60_40')
        positions: List of Position objects (holdings)
        rebalance_frequency: Optional rebalancing schedule

    Constraints:
        - Weights must sum to 1.0 (within tolerance of 1e-6)
        - Positions can contain any Asset (including Portfolio)

    Return Calculation:
        r_portfolio = Σ(w_i × r_i)
        where r_i = position[i].asset.calculate_return(prev, curr)

    Example:
        60/40 equity/bonds:
        >>> equity_port = Portfolio('EQUITY', equity_positions)
        >>> bond_port = Portfolio('BONDS', bond_positions)
        >>> balanced = Portfolio('BALANCED_60_40', [
        ...     Position(equity_port, 0.6, 100.0, date(2024, 11, 1)),
        ...     Position(bond_port, 0.4, 100.0, date(2024, 11, 1))
        ... ])
    """

    def __init__(
        self,
        identifier: str,
        positions: List[Position],
        rebalance_frequency: Optional[str] = None
    ):
        """
        Initialize portfolio with positions.

        Args:
            identifier: Portfolio name/ID
            positions: List of Position objects
            rebalance_frequency: Optional ('daily', 'monthly', 'quarterly', None)

        Raises:
            ValueError: If weights don't sum to 1.0 (within tolerance)

        Example:
            >>> asset1 = PriceFuture('SFRZ4')
            >>> asset2 = PriceFuture('SFRH5')
            >>> port = Portfolio('CARRY', [
            ...     Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            ...     Position(asset2, 0.4, 94.9, date(2024, 11, 1))
            ... ])
        """
        self.identifier = identifier
        self.positions = positions
        self.rebalance_frequency = rebalance_frequency

        # Validate weights sum to 1.0 (if not empty)
        if len(positions) > 0:
            total_weight = sum(p.quantity for p in positions)
            if abs(total_weight - 1.0) > 1e-6:
                raise ValueError(
                    f"Position weights must sum to 1.0, got {total_weight:.10f}"
                )

    def get_identifier(self) -> str:
        """
        Return portfolio identifier.

        Returns:
            Portfolio name string

        Example:
            >>> port = Portfolio('MY_PORTFOLIO', [...])
            >>> port.get_identifier()
            'MY_PORTFOLIO'
        """
        return self.identifier

    def calculate_return(
        self,
        prev_prices: Dict[str, float],
        curr_prices: Dict[str, float],
        **kwargs
    ) -> float:
        """
        Calculate portfolio return as weighted sum of constituent returns.

        Delegates to each constituent asset's calculate_return() method,
        then combines with portfolio weights.

        Args:
            prev_prices: Map from asset ID → previous price
            curr_prices: Map from asset ID → current price
            **kwargs: Passed to constituent calculate_return() calls

        Returns:
            Portfolio return as decimal

        Formula:
            r_portfolio = Σ(w_i × r_i)
            where:
                w_i = position[i].quantity (weight)
                r_i = position[i].asset.calculate_return(prev, curr)

        Example:
            60% SFRZ4, 40% SFRH5:
            >>> prev = {'SFRZ4': 95.0, 'SFRH5': 94.0}
            >>> curr = {'SFRZ4': 96.0, 'SFRH5': 94.5}
            >>> port.calculate_return(prev, curr)
            # = 0.6 × (96-95)/95 + 0.4 × (94.5-94)/94
            # = 0.6 × 0.0105 + 0.4 × 0.0053
            # = 0.0084

        Nested Portfolio:
            Automatically handles recursion - sub-portfolio's
            calculate_return() is called, which recursively calculates
            its own constituents' returns.
        """
        portfolio_return = 0.0

        for position in self.positions:
            asset = position.asset
            weight = position.quantity

            # Check if asset is a Portfolio (nested)
            if isinstance(asset, Portfolio):
                # For nested portfolios, pass price dicts through
                # (not individual prices - portfolio needs all constituent prices)
                asset_return = asset.calculate_return(prev_prices, curr_prices, **kwargs)
            else:
                # For atomic assets (PriceFuture, etc.), extract prices
                asset_id = asset.get_identifier()
                prev_price = prev_prices.get(asset_id, 0.0)
                curr_price = curr_prices.get(asset_id, 0.0)
                asset_return = asset.calculate_return(prev_price, curr_price, **kwargs)

            # Add weighted contribution
            portfolio_return += weight * asset_return

        return portfolio_return

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect transition from first constituent that has one.

        Checks each constituent asset for transitions (rolls, expiries, etc.)
        and returns the first one found.

        Args:
            as_of: Current date
            market_data: Market data for all constituents

        Returns:
            First AssetTransition found, or None if no transitions

        Note:
            For all transitions, use get_all_transitions() instead.

        Example:
            Portfolio with rollable future:
            >>> transition = port.detect_transition(date(2024, 12, 10), market_data)
            >>> if transition:
            ...     print(f"Roll: {transition.from_asset} → {transition.to_asset}")
        """
        for position in self.positions:
            asset = position.asset
            transition = asset.detect_transition(as_of, market_data)
            if transition:
                return transition
        return None

    def get_all_transitions(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> List[AssetTransition]:
        """
        Get all transitions from all constituents.

        Unlike detect_transition() which returns first transition,
        this collects and returns ALL transitions from the portfolio.

        Args:
            as_of: Current date
            market_data: Market data for all constituents

        Returns:
            List of AssetTransition objects (may be empty)

        Example:
            Multiple rolls on same date:
            >>> transitions = port.get_all_transitions(date(2024, 12, 10), data)
            >>> for trans in transitions:
            ...     print(f"{trans.from_asset} → {trans.to_asset}")
            SFRZ4 → SFRH5
            SFRM5 → SFRU5
        """
        transitions = []
        for position in self.positions:
            asset = position.asset
            transition = asset.detect_transition(as_of, market_data)
            if transition:
                transitions.append(transition)
        return transitions

    def __repr__(self) -> str:
        """String representation for debugging."""
        n_pos = len(self.positions)
        return f"Portfolio('{self.identifier}', {n_pos} positions)"
