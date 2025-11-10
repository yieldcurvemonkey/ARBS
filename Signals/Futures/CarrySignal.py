"""
CarrySignal - Futures carry alpha signal

Calculates carry for STIR futures based on calendar spread pricing.

Carry Calculation:
- Raw carry = front_price - back_price (in price points)
- Annualized carry (bps/year) = (raw_carry / days_to_roll) * 10000 * 252

Interpretation:
- Positive carry (backwardation): front > back → expect to profit from roll
- Negative carry (contango): front < back → expect to lose from roll

Expected Performance (from historical data):
- IC: 0.05-0.10 (good to very good)
- Halflife: 60-90 days (medium frequency)
- Works best in stable rate environments

Futures-Swap Basis:
- Futures prices differ from swaps due to convexity
- Adjustment: ~1bp per quarter for SOFR futures
- Can be included via include_basis parameter
"""

from datetime import date
from typing import Optional, Any
import numpy as np
import pandas as pd

from Signals.Base.BaseSignal import BaseSignal


class CarrySignal(BaseSignal):
    """
    Carry signal for STIR futures.

    Measures expected return from holding a futures contract until roll date,
    based on the calendar spread (front - back).

    Attributes:
        annualize (bool): If True, return annualized carry in bps/year
        include_basis (bool): If True, include futures-swap basis adjustment
        business_days_per_year (int): Used for annualization (default: 252)
    """

    def __init__(
        self,
        name: str = "futures_carry",
        standardize: bool = True,
        annualize: bool = True,
        include_basis: bool = False,
        business_days_per_year: int = 252,
        track_history: bool = True,
    ):
        """
        Initialize CarrySignal.

        Args:
            name: Signal name
            standardize: If True, return z-scored alphas
            annualize: If True, annualize carry to bps/year
            include_basis: If True, adjust for futures-swap basis
            business_days_per_year: Trading days per year (default: 252)
            track_history: If True, store signal history
        """
        super().__init__(name=name, standardize=standardize, track_history=track_history)
        self.annualize = annualize
        self.include_basis = include_basis
        self.business_days_per_year = business_days_per_year

    def _calculate_raw_signal(
        self,
        inst_data: pd.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw carry signal for a single futures contract.

        Args:
            inst_data: DataFrame with columns:
                - price: Front contract price (e.g., 94.50)
                - next_price: Back contract price (e.g., 94.45)
                - roll_date: Roll date for front contract
                - [optional] convexity_adjustment: Futures-swap basis (bps)
            market_data: Not used for carry (calendar spread is self-contained)
            as_of: Calculation date

        Returns:
            Carry in bps/year (if annualize=True) or raw spread (if annualize=False)
        """
        # Extract required fields
        try:
            front_price = inst_data.iloc[0]["price"]
            next_price = inst_data.iloc[0].get("next_price", np.nan)
            roll_date = inst_data.iloc[0].get("roll_date", None)
        except (KeyError, IndexError):
            return np.nan

        # Check for missing data
        if pd.isna(next_price) or roll_date is None:
            return np.nan

        # Calculate calendar spread (front - back)
        # Positive = backwardation (front > back)
        # Negative = contango (front < back)
        calendar_spread = front_price - next_price

        # Handle zero spread (flat curve)
        if abs(calendar_spread) < 1e-10:
            return 0.0

        # If not annualizing, return raw spread
        if not self.annualize:
            return calendar_spread

        # Annualize carry
        days_to_roll = (roll_date - as_of).days

        # Handle edge case: near or past roll date
        if days_to_roll <= 0:
            # Already at or past roll → carry not meaningful
            return 0.0

        if days_to_roll == 1:
            # 1 day to roll → very high annualized carry
            # Cap at reasonable value to avoid numerical issues
            return np.sign(calendar_spread) * 5000.0  # Cap at 5000 bps/year

        # Annualized carry (bps/year)
        # Formula: (spread / days) * 10000 * 252
        # - spread is in price points (e.g., 0.05)
        # - * 10000 converts to basis points
        # - * 252 annualizes
        carry_bps_per_year = (
            calendar_spread / days_to_roll
        ) * 10000 * self.business_days_per_year

        # Apply basis adjustment if requested
        if self.include_basis:
            convexity_adj = inst_data.iloc[0].get("convexity_adjustment", 0.0)
            carry_bps_per_year += convexity_adj

        return carry_bps_per_year

    def __repr__(self) -> str:
        return (
            f"CarrySignal(name='{self.name}', "
            f"annualize={self.annualize}, "
            f"include_basis={self.include_basis})"
        )
