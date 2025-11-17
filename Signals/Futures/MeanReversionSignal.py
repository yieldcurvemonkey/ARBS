# ABOUTME: Mean reversion signal (extends BaseSignal) calculator for futures using Ornstein-Uhlenbeck process
# ABOUTME: Measures deviation from mean and generates signals expecting price reversion
"""
MeanReversionSignal - Mean reversion signal for futures

Calculates mean reversion signal based on price deviation from mean.

Mean Reversion Calculation:
- Deviation: (P_t - mean(P)) / std(P)
- Negative deviation: price below mean → expect reversion up → long
- Positive deviation: price above mean → expect reversion down → short
- Signal is inverted from momentum (negative deviation = positive signal)

Interpretation:
- Price below mean: expect reversion up → long
- Price above mean: expect reversion down → short
- Price at mean: no signal

Expected Performance:
- IC: 0.02-0.05 (moderate skill, mean-reversion)
- Halflife: 10-30 days (high frequency)
- Works best in ranging markets
- Performs poorly in trending environments

Research Insights:
- Mean reversion strong in short-term (days to weeks)
- Works better for highly liquid markets
- Complements momentum (negative correlation)
- Half-life varies by asset class and market regime

Example:
    >>> signal = MeanReversionSignal(lookback_days=30)
    >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    >>> signals
    {'SFRZ4': -1.5, 'SFRH5': 0.8}  # Z-scores (negative = below mean)
"""

from datetime import date, timedelta
from typing import Optional, Any, List, Dict
import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal
from Signals.Base.TimeSeriesSignalMixin import TimeSeriesSignalMixin


class MeanReversionSignal(BaseSignal, TimeSeriesSignalMixin):
    """
    Mean reversion signal for futures.

    Measures price deviation from historical mean and generates signals
    expecting reversion to the mean.

    Attributes:
        lookback_days (int): Number of days for mean calculation
        method (str): 'zscore' or 'deviation' (default: 'zscore')
        standardize (bool): If True, return z-scored signals (default: True)
        business_days_per_year (int): For potential annualization (default: 252)

    Methods:
        calculate: Generate mean reversion signals for multiple instruments
        _calculate_raw_signal: Calculate mean reversion for single instrument

    Example:
        >>> signal = MeanReversionSignal(lookback_days=30)
        >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    """

    def __init__(
        self,
        name: str = "futures_mean_reversion",
        lookback_days: int = 20,
        method: str = "zscore",
        standardize: bool = True,
        business_days_per_year: int = 252,
        track_history: bool = True,
    ):
        """
        Initialize MeanReversionSignal.

        Args:
            name: Signal name
            lookback_days: Days to look back for mean calculation (default: 20)
            method: 'zscore' or 'deviation' (default: 'zscore')
            standardize: If True, return z-scored signals (default: True)
            business_days_per_year: Trading days per year (default: 252)
            track_history: If True, store signal history (default: True)

        Example:
            Short-term mean reversion (2 weeks):
            >>> signal = MeanReversionSignal(lookback_days=10)

            Medium-term mean reversion (1 month):
            >>> signal = MeanReversionSignal(lookback_days=30)

            Long-term mean reversion (3 months):
            >>> signal = MeanReversionSignal(lookback_days=60)
        """
        super().__init__(name=name, standardize=standardize, track_history=track_history)
        self.lookback_days = lookback_days
        self.method = method
        self.business_days_per_year = business_days_per_year

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw mean reversion signal for a single instrument.

        Args:
            inst_data: Price history Polars DataFrame with 'date' and 'price' columns
            market_data: Market data (unused for mean reversion)
            as_of: Calculation date

        Returns:
            Raw mean reversion value (negative = below mean = bullish)

        Formula:
            zscore: -1 × (P_t - mean(P)) / std(P)
            (negative sign: price below mean → positive signal)

        Example:
            Price is 1 std dev below mean:
            >>> signal = -1.0  # Bullish (expect reversion up)

            Price is 1 std dev above mean:
            >>> signal = 1.0  # Bearish (expect reversion down)
        """
        # Extract price window using shared helper
        try:
            current_price, past_prices, actual_days = self._get_price_window(
                inst_data, as_of, self.lookback_days, return_series=True, market_data=market_data
            )
        except ValueError:
            # Insufficient data
            return 0.0

        # Calculate mean from past prices
        mean_price = np.mean(past_prices)

        # For std, need at least 2 data points
        if len(past_prices) < 2:
            # If only 1 historical price, use simple deviation without std
            if abs(current_price - mean_price) < 1e-10:
                return 0.0
            # Use absolute deviation normalized by mean
            deviation = (current_price - mean_price) / abs(mean_price) if abs(mean_price) > 1e-10 else 0.0
            return float(-1.0 * deviation)

        std_price = np.std(past_prices, ddof=1)

        # Handle zero variance
        if std_price < 1e-10:
            # No variation in past prices
            if abs(current_price - mean_price) < 1e-10:
                # Current also at mean → no signal
                return 0.0
            # Current differs from flat historical mean → max signal
            # Return +/-1 based on direction
            return -1.0 if current_price > mean_price else 1.0

        # Calculate signal based on method
        if self.method == 'zscore':
            # Z-score: (current - mean) / std
            # Invert sign: negative deviation (below mean) → positive signal
            deviation = (current_price - mean_price) / std_price
            # Invert: below mean → positive signal (expect reversion up)
            signal = -1.0 * deviation
        else:  # 'deviation'
            # Simple deviation
            deviation = (current_price - mean_price) / mean_price if abs(mean_price) > 1e-10 else 0.0
            signal = -1.0 * deviation

        return float(signal)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MeanReversionSignal(name='{self.name}', "
            f"lookback={self.lookback_days}, "
            f"method='{self.method}', "
            f"standardize={self.standardize})"
        )
