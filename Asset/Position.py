# ABOUTME: Position class representing a holding in an asset with quantity and entry details
# ABOUTME: Tracks market value, P&L calculations for portfolio construction and backtesting
"""
Position - Holding in an Asset

Represents a position in an asset, tracking:
- What we own (asset)
- How much we own (quantity, can be fractional or negative for shorts)
- What we paid (entry_price)
- When we bought (entry_date)

Used by:
- Portfolio: to track constituent holdings
- Backtest: to track historical positions over time
- Risk: to calculate portfolio-level risk metrics

Key operations:
- market_value(): Current value at market prices
- pnl(): Absolute P&L since entry
- pnl_percent(): Percentage return since entry

Example:
    >>> asset = PriceFuture('SFRZ4')
    >>> pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))
    >>> pos.market_value(current_price=96.0)
    9600.0
    >>> pos.pnl(current_price=96.0)
    100.0
    >>> pos.pnl_percent(current_price=96.0)
    0.010526315789473684  # 1.05%
"""

from dataclasses import dataclass
from datetime import date

from Asset.Base import Asset


@dataclass
class Position:
    """
    Represents a holding in an asset.

    A position combines:
    - Asset (what we own)
    - Quantity (how much - can be fractional or negative)
    - Entry price (what we paid)
    - Entry date (when we bought)

    Attributes:
        asset: The underlying asset (implements Asset interface)
        quantity: Number of units held (fractional allowed, negative = short)
        entry_price: Price at which position was entered
        entry_date: Date when position was opened

    Quantity interpretation:
        - Positive: Long position (own the asset)
        - Negative: Short position (owe the asset)
        - Zero: Closed position (no holding)
        - Fractional: Partial units (e.g., 2.5 contracts)

    Example:
        Long position:
        >>> asset = PriceFuture('SFRZ4')
        >>> long_pos = Position(asset, 100.0, 95.0, date(2024, 11, 1))
        >>> long_pos.pnl(96.0)  # Price increased to 96
        100.0  # Profit of 100

        Short position:
        >>> short_pos = Position(asset, -100.0, 95.0, date(2024, 11, 1))
        >>> short_pos.pnl(94.0)  # Price decreased to 94
        100.0  # Profit of 100 (short gains from price decline)
    """

    asset: Asset
    quantity: float
    entry_price: float
    entry_date: date

    def market_value(self, current_price: float) -> float:
        """
        Calculate current market value of position.

        Market value = quantity × current_price

        Args:
            current_price: Current market price of the asset

        Returns:
            Current market value (can be negative for short positions)

        Example:
            >>> pos = Position(asset, quantity=100.0, entry_price=95.0, ...)
            >>> pos.market_value(current_price=96.0)
            9600.0

            Short position:
            >>> short = Position(asset, quantity=-50.0, entry_price=95.0, ...)
            >>> short.market_value(current_price=96.0)
            -4800.0
        """
        return self.quantity * current_price

    def pnl(self, current_price: float) -> float:
        """
        Calculate absolute P&L since entry.

        P&L = quantity × (current_price - entry_price)

        Args:
            current_price: Current market price of the asset

        Returns:
            Absolute P&L in currency units

        Sign interpretation:
            - Positive: Profitable position
            - Negative: Losing position
            - Zero: Breakeven

        Example:
            Long profit:
            >>> pos = Position(asset, 100.0, 95.0, ...)
            >>> pos.pnl(96.0)
            100.0  # 100 units × $1 gain

            Short profit:
            >>> short = Position(asset, -100.0, 95.0, ...)
            >>> short.pnl(94.0)
            100.0  # -100 units × -$1 change = $100 profit
        """
        return self.quantity * (current_price - self.entry_price)

    def pnl_percent(self, current_price: float) -> float:
        """
        Calculate percentage P&L since entry.

        P&L % = (current_price - entry_price) / entry_price

        Independent of quantity - represents return on investment.

        Args:
            current_price: Current market price of the asset

        Returns:
            P&L as decimal (e.g., 0.01 for 1%)

        Edge cases:
            - entry_price <= 0: Returns 0.0 (undefined)

        Example:
            >>> pos = Position(asset, 100.0, 95.0, ...)
            >>> pos.pnl_percent(96.0)
            0.010526315789473684  # 1.05% return

            Total loss:
            >>> pos.pnl_percent(0.0)
            -1.0  # -100% return

            Double:
            >>> pos = Position(asset, 100.0, 50.0, ...)
            >>> pos.pnl_percent(100.0)
            1.0  # 100% return
        """
        if self.entry_price <= 0:
            # Undefined for zero/negative entry price
            return 0.0

        return (current_price - self.entry_price) / self.entry_price

    def __repr__(self) -> str:
        """String representation for debugging."""
        direction = "LONG" if self.quantity >= 0 else "SHORT"
        return (f"Position({direction} {abs(self.quantity):.2f} × "
                f"{self.asset.get_identifier()} @ {self.entry_price:.2f})")
