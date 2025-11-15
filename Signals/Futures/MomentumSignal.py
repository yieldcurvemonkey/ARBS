# ABOUTME: Momentum signal (extends BaseSignal) calculator for futures using time-series price trends
# ABOUTME: Measures rate of price change over lookback period and standardizes to Z-scores
"""
MomentumSignal - Time-series momentum for futures

Calculates momentum based on price trends over a lookback period.

Momentum Calculation:
- Simple return: (P_t - P_{t-n}) / P_{t-n}
- Log return: log(P_t / P_{t-n})
- Annualized: momentum × (252 / lookback_days)

Interpretation:
- Positive momentum (uptrend): expect continuation → long
- Negative momentum (downtrend): expect continuation → short
- Momentum = 0 (sideways): no trend signal

Expected Performance:
- IC: 0.02-0.05 (moderate skill, trend-following)
- Halflife: 20-60 days (medium frequency)
- Works best in trending markets
- Performs poorly in mean-reverting environments

Research Insights (Moskowitz et al. 2012):
- Time-series momentum strong across asset classes
- 1-12 month lookback optimal for most futures
- Significant after transaction costs
- Low correlation with cross-sectional momentum

Example:
    >>> signal = MomentumSignal(lookback_days=60)
    >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    >>> signals
    {'SFRZ4': 1.5, 'SFRH5': -0.8}  # Z-scores
"""

from datetime import date, timedelta
from typing import Optional, Any, List, Dict
import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal
from Signals.Base.TimeSeriesSignalMixin import TimeSeriesSignalMixin


class MomentumSignal(BaseSignal, TimeSeriesSignalMixin):
    """
    Time-series momentum signal for futures.

    Measures price trend over a lookback period and converts to
    standardized Z-score for portfolio construction.

    Attributes:
        lookback_days (int): Number of days to look back for momentum
        method (str): 'simple' or 'log' returns
        annualize (bool): If True, annualize the momentum
        business_days_per_year (int): For annualization (default: 252)

    Methods:
        calculate: Generate momentum signals for multiple instruments
        _calculate_raw_signal: Calculate momentum for single instrument

    Example:
        >>> signal = MomentumSignal(lookback_days=60)
        >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    """

    def __init__(
        self,
        name: str = "futures_momentum",
        lookback_days: int = 60,
        method: str = "simple",
        annualize: bool = False,
        standardize: bool = True,
        business_days_per_year: int = 252,
        track_history: bool = True,
    ):
        """
        Initialize MomentumSignal.

        Args:
            name: Signal name
            lookback_days: Days to look back for momentum (default: 60)
            method: 'simple' or 'log' returns (default: 'simple')
            annualize: If True, annualize momentum (default: False)
            standardize: If True, return z-scored signals (default: True)
            business_days_per_year: Trading days per year (default: 252)
            track_history: If True, store signal history (default: True)

        Example:
            Short-term momentum (3 weeks):
            >>> signal = MomentumSignal(lookback_days=21)

            Medium-term momentum (3 months):
            >>> signal = MomentumSignal(lookback_days=60)

            Long-term momentum (1 year):
            >>> signal = MomentumSignal(lookback_days=252)
        """
        super().__init__(name=name, standardize=standardize, track_history=track_history)
        self.lookback_days = lookback_days
        self.method = method
        self.annualize = annualize
        self.business_days_per_year = business_days_per_year

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw momentum signal for a single instrument.

        Args:
            inst_data: Price history polars DataFrame with 'date' and 'price' columns
            market_data: Market data (unused for momentum)
            as_of: Calculation date

        Returns:
            Raw momentum value (return over lookback period)

        Formula:
            Simple: (P_t - P_{t-n}) / P_{t-n}
            Log: log(P_t / P_{t-n})

        Example:
            Price went from 100 to 105 over 60 days:
            >>> momentum = 0.05  # 5% gain = positive momentum
        """
        # Validate input data
        if inst_data is None or len(inst_data) == 0:
            return 0.0

        if 'price' not in inst_data.columns:
            return 0.0

        # Ensure we have date column
        if 'date' not in inst_data.columns:
            # Assume index is dates if no date column
            inst_data = inst_data.clone()
            inst_data = inst_data.with_row_index('date')

        # Convert date column to datetime if needed
        if inst_data['date'].dtype != pl.Date and inst_data['date'].dtype != pl.Datetime:
            inst_data = inst_data.clone()
            inst_data = inst_data.with_columns(
                pl.col('date').str.strptime(pl.Date, '%Y-%m-%d').cast(pl.Datetime)
            )

        # Sort by date
        inst_data = inst_data.sort('date')

        # Get current price
        current_price = inst_data['price'][-1]

        # Calculate lookback date (convert as_of to datetime for comparison)
        lookback_date = as_of - timedelta(days=self.lookback_days)

        # Find price at lookback date (or closest available)
        hist_data = inst_data.filter(pl.col('date') <= lookback_date)

        if len(hist_data) == 0:
            # Not enough history - use earliest available
            if len(inst_data) < 2:
                return 0.0
            lookback_price = inst_data['price'][0]
        else:
            lookback_price = hist_data['price'][-1]

        # Calculate momentum
        if lookback_price <= 0:
            return 0.0

        if self.method == 'log':
            momentum = np.log(current_price / lookback_price)
        else:  # 'simple'
            momentum = (current_price - lookback_price) / lookback_price

        # Annualize if requested
        if self.annualize:
            # Calculate actual days used
            end_date = inst_data['date'][-1]
            start_date = hist_data['date'][-1] if len(hist_data) > 0 else inst_data['date'][0]
            actual_days = (end_date - start_date).days
            if actual_days > 0:
                momentum = momentum * (self.business_days_per_year / actual_days)

        return float(momentum)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MomentumSignal(name='{self.name}', "
            f"lookback={self.lookback_days}, "
            f"method='{self.method}', "
            f"standardize={self.standardize})"
        )
