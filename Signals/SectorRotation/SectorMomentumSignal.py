# ABOUTME: Sector momentum signal wrapper integrating MomentumFactor with BaseSignal
# ABOUTME: Implements MOM_7M strategy from Yang & Shi (2023) with IC tracking
"""
SectorMomentumSignal - Momentum signal for sector rotation strategies.

Wraps MomentumFactor within BaseSignal framework to provide:
- Momentum factor calculation (MOM_nM)
- Cross-sectional z-score standardization
- Information Coefficient (IC) tracking
- Signal history and metadata

Default Configuration: MOM_7M (Yang & Shi 2023)
- Lookback: 7 months (147 trading days)
- Exclusion: Recent 10% (15 days)
- Target Sharpe: 0.62 (2017-2022 period)

Integration with Grinold-Kahn Framework:
1. Raw momentum values calculated per sector
2. Cross-sectional standardization (z-scores) via BaseSignal
3. IC tracking for alpha quality monitoring
4. Scaled by AlphaGenerator: α = IC × Vol × Z

Example:
    >>> signal = SectorMomentumSignal(lookback_months=7)
    >>>
    >>> # Generate signals for all sectors
    >>> sector_data_list = [xlk_returns, xle_returns, xlf_returns, ...]
    >>> z_scores = signal.generate_batch(
    ...     inst_data_list=sector_data_list,
    ...     market_data=None,
    ...     as_of=date(2023, 12, 31)
    ... )
    >>>
    >>> # z_scores shape: (11,) for 11 sectors
    >>> # Properties: mean=0, std=1, ranking preserved
    >>>
    >>> # Calculate IC (forecasting skill)
    >>> forecasts = pl.Series(z_scores)
    >>> actuals = pl.Series(next_period_returns)
    >>> ic = signal.calculate_ic(forecasts, actuals)
    >>> # Target: IC > 0.05 (good), IC > 0.10 (very good)
"""

from datetime import date
from typing import Optional
import polars as pl

from Signals.Base.BaseSignal import BaseSignal
from Signals.SectorRotation.MomentumFactor import MomentumFactor


class SectorMomentumSignal(BaseSignal):
    """
    Sector momentum signal integrating MomentumFactor with BaseSignal.

    Calculates momentum for sectors and provides z-score standardization,
    IC tracking, and signal history.

    Attributes:
        lookback_months: Number of months for momentum calculation (default: 7)
        exclusion_pct: Percentage of recent period to exclude (default: 0.10)
        momentum_factor: Underlying MomentumFactor instance
    """

    def __init__(
        self,
        lookback_months: int = 7,
        exclusion_pct: float = 0.10,
        trading_days_per_month: int = 21,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize sector momentum signal.

        Parameters:
            lookback_months: Number of months for cumulative return (default: 7)
                            Paper's optimal: 7 months (MOM_7M)
            exclusion_pct: Percentage of recent period to exclude (default: 0.10)
                          Excludes short-term reversion effects
            trading_days_per_month: Trading days per month (default: 21)
            standardize: If True, return z-scored alphas (default: True)
            track_history: If True, store signal generation history (default: True)
        """
        # Initialize BaseSignal
        super().__init__(
            name="sector_momentum",
            standardize=standardize,
            track_history=track_history,
        )

        # Store parameters
        self.lookback_months = lookback_months
        self.exclusion_pct = exclusion_pct
        self.trading_days_per_month = trading_days_per_month

        # Initialize MomentumFactor
        self.momentum_factor = MomentumFactor(
            lookback_months=lookback_months,
            exclusion_pct=exclusion_pct,
            trading_days_per_month=trading_days_per_month,
        )

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[any],
        as_of: date,
    ) -> float:
        """
        Calculate raw momentum signal for a single sector.

        This method is called by BaseSignal.generate() and generate_batch().
        It computes the momentum factor value for one sector.

        Parameters:
            inst_data: DataFrame with columns [ticker, date, return]
                      Must contain sufficient history for momentum calculation
            market_data: Not used for sector momentum (all data is sector-specific)
            as_of: Calculation date (must be last date in inst_data)

        Returns:
            Raw momentum value (before standardization)
            Formula: MOM = Σ(n months) - Σ(recent 10%)

        Raises:
            ValueError: If insufficient history or invalid schema
        """
        # Calculate momentum factor
        momentum_df = self.momentum_factor.calculate(inst_data)

        # Filter to as_of date
        result = momentum_df.filter(pl.col("date") == as_of)

        if len(result) == 0:
            raise ValueError(
                f"No momentum value calculated for date {as_of}. "
                f"Ensure inst_data contains sufficient history "
                f"({self.momentum_factor.total_lookback_days} days required)."
            )

        # Extract momentum value
        momentum_value = result["momentum_factor"][0]

        return momentum_value

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"SectorMomentumSignal("
            f"name='{self.name}', "
            f"lookback={self.lookback_months}M, "
            f"exclusion={self.exclusion_pct:.1%}, "
            f"standardize={self.standardize}"
            f")"
        )
