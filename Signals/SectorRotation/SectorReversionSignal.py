# ABOUTME: Sector reversion signal wrapper integrating ReversionFactor with BaseSignal
# ABOUTME: Implements REV_30D contrarian strategy from Yang & Shi (2023) with IC tracking
"""
SectorReversionSignal - Short-term reversion signal for sector rotation.

Wraps ReversionFactor within BaseSignal framework to provide:
- Reversion factor calculation (REV_nD)
- Cross-sectional z-score standardization
- Information Coefficient (IC) tracking
- Signal history and metadata

Default Configuration: REV_30D (Yang & Shi 2023)
- Lookback: 30 days
- Contrarian logic: Negative cumulative return
- Target Sharpe: 0.87 (2002-2022) ← **BEST single factor!**

Contrarian Strategy:
- Recent winners (positive returns) → NEGATIVE signal (bet on pullback)
- Recent losers (negative returns) → POSITIVE signal (bet on recovery)
- Formula: REV_nD = -Σ(past n days returns)

Integration with Grinold-Kahn Framework:
1. Raw reversion values calculated per sector
2. Cross-sectional standardization (z-scores) via BaseSignal
3. IC tracking for alpha quality monitoring
4. Scaled by AlphaGenerator: α = IC × Vol × Z

Example:
    >>> signal = SectorReversionSignal(lookback_days=30)
    >>>
    >>> # Recent winner (XLK: +15% in 30 days)
    >>> xlk_data = pl.DataFrame({
    ...     "ticker": ["XLK"] * 30,
    ...     "date": [...],
    ...     "return": [0.005] * 30  # 0.5% daily
    ... })
    >>>
    >>> # Recent loser (XLE: -10% in 30 days)
    >>> xle_data = pl.DataFrame({
    ...     "ticker": ["XLE"] * 30,
    ...     "date": [...],
    ...     "return": [-0.0033] * 30  # -0.33% daily
    ... })
    >>>
    >>> # Generate signals (contrarian)
    >>> z_scores = signal.generate_batch(
    ...     inst_data_list=[xlk_data, xle_data],
    ...     market_data=None,
    ...     as_of=date(2023, 12, 31)
    ... )
    >>>
    >>> # XLK (winner) gets NEGATIVE z-score (short)
    >>> # XLE (loser) gets POSITIVE z-score (long)
    >>> # Bet: Winners pull back, losers recover
"""

from datetime import date
from typing import Optional
import polars as pl

from Signals.Base.BaseSignal import BaseSignal
from Signals.SectorRotation.ReversionFactor import ReversionFactor


class SectorReversionSignal(BaseSignal):
    """
    Sector reversion signal integrating ReversionFactor with BaseSignal.

    Calculates short-term reversion for sectors (contrarian strategy) and
    provides z-score standardization, IC tracking, and signal history.

    Attributes:
        lookback_days: Number of days for reversion calculation (default: 30)
        reversion_factor: Underlying ReversionFactor instance
    """

    def __init__(
        self,
        lookback_days: int = 30,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize sector reversion signal.

        Parameters:
            lookback_days: Number of days for cumulative return (default: 30)
                          Paper's optimal: 30 days (REV_30D)
                          Captures short-term reversion effects
            standardize: If True, return z-scored alphas (default: True)
            track_history: If True, store signal generation history (default: True)
        """
        # Initialize BaseSignal
        super().__init__(
            name="sector_reversion",
            standardize=standardize,
            track_history=track_history,
        )

        # Store parameters
        self.lookback_days = lookback_days

        # Initialize ReversionFactor
        self.reversion_factor = ReversionFactor(
            lookback_days=lookback_days
        )

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[any],
        as_of: date,
    ) -> float:
        """
        Calculate raw reversion signal for a single sector.

        This method is called by BaseSignal.generate() and generate_batch().
        It computes the reversion factor value for one sector.

        Parameters:
            inst_data: DataFrame with columns [ticker, date, return]
                      Must contain sufficient history for reversion calculation
            market_data: Not used for sector reversion (all data is sector-specific)
            as_of: Calculation date (must be last date in inst_data)

        Returns:
            Raw reversion value (before standardization)
            Formula: REV = -Σ(n days returns)
            Contrarian: Winners get negative, losers get positive

        Raises:
            ValueError: If insufficient history or invalid schema
        """
        # Calculate reversion factor
        reversion_df = self.reversion_factor.calculate(inst_data)

        # Filter to as_of date
        result = reversion_df.filter(pl.col("date") == as_of)

        if len(result) == 0:
            raise ValueError(
                f"No reversion value calculated for date {as_of}. "
                f"Ensure inst_data contains sufficient history "
                f"({self.reversion_factor.lookback_days} days required)."
            )

        # Extract reversion value
        reversion_value = result["reversion_factor"][0]

        return reversion_value

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"SectorReversionSignal("
            f"name='{self.name}', "
            f"lookback={self.lookback_days}D, "
            f"standardize={self.standardize}"
            f")"
        )
