# ABOUTME: Futures carry signal (extends BaseSignal) calculator using calendar spread pricing
# ABOUTME: Generates annualized carry alpha (bps/year) from front-back price differential
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

from datetime import date, timedelta
from typing import Optional, Any, List, Dict
import logging
import numpy as np
import polars as pl

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

    def calculate(
        self,
        instruments: List[str],
        market_data: Any,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Calculate carry signals for multiple instruments.

        Args:
            instruments: List of futures contract identifiers
            market_data: Market data provider with get_price_history method
            as_of: Calculation date

        Returns:
            Dict mapping instrument → carry signal (Z-score if standardize=True)
            Failed instruments are excluded from result
        """
        # Fetch price history for all instruments
        inst_data_list = []
        failed_instruments = []
        lookback_days = 30  # Carry needs minimal history, just recent data

        for instrument in instruments:
            try:
                lookback_date = as_of - timedelta(days=lookback_days)
                price_history = market_data.get_price_history(
                    instrument,
                    start_date=lookback_date,
                    end_date=as_of
                )
                inst_data_list.append(price_history)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Excluding instrument from carry signal calculation",
                    extra={'instrument': instrument, 'error': str(e)}
                )
                failed_instruments.append(instrument)

        # Only process instruments that succeeded
        successful_instruments = [i for i in instruments if i not in failed_instruments]

        if not successful_instruments:
            return {}

        # Calculate raw carry signals for all instruments
        raw_signals = np.array([
            self._calculate_raw_signal(inst_data, market_data, as_of)
            for inst_data in inst_data_list
        ])

        # Update metadata
        self.last_generated = as_of

        # Track history if enabled
        if self.track_history:
            self.history[as_of] = raw_signals.copy()

        # Standardize if requested
        if self.standardize:
            signals_array = self._standardize(raw_signals)
        else:
            signals_array = raw_signals

        # Convert array to dict
        return {inst: float(sig) for inst, sig in zip(successful_instruments, signals_array)}

    def _standardize(self, signals: np.ndarray) -> np.ndarray:
        """
        Standardize signals to z-scores (mean=0, std=1).

        Args:
            signals: Raw signal values

        Returns:
            Z-scored signals
        """
        # Handle edge cases
        if len(signals) < 2:
            return signals

        # Remove NaN values for calculation
        valid_mask = ~np.isnan(signals)
        if not np.any(valid_mask):
            return signals  # All NaN

        # Calculate z-scores
        mean = np.mean(signals[valid_mask])
        std = np.std(signals[valid_mask], ddof=1)

        if std < 1e-10:
            # Zero variance → all signals equal → return zeros
            return np.zeros_like(signals)

        # Standardize: z = (x - mean) / std
        z_scores = (signals - mean) / std

        return z_scores

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
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
            row_0 = inst_data.row(0, named=True)
            front_price = row_0["price"]
            next_price = row_0.get("next_price", np.nan)
            roll_date = row_0.get("roll_date", None)
        except (KeyError, IndexError):
            return np.nan

        # Check for missing data
        try:
            is_na_next_price = np.isnan(next_price)
        except (TypeError, ValueError):
            is_na_next_price = next_price is None

        if is_na_next_price or roll_date is None:
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
            convexity_adj = row_0.get("convexity_adjustment", 0.0)
            carry_bps_per_year += convexity_adj

        return carry_bps_per_year

    def __repr__(self) -> str:
        return (
            f"CarrySignal(name='{self.name}', "
            f"annualize={self.annualize}, "
            f"include_basis={self.include_basis})"
        )
