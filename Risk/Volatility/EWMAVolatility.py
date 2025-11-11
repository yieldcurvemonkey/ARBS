# ABOUTME: EWMAVolatility estimator using exponentially weighted moving average
# ABOUTME: More responsive to recent volatility changes than RealizedVolatility
"""
EWMAVolatility - Exponentially Weighted Moving Average Volatility

Estimates volatility giving more weight to recent observations.

Formula:
    EWMA_t = λ × EWMA_{t-1} + (1-λ) × r_t^2
    Vol = √EWMA_t × √(annualization_factor)

    where λ = exp(-ln(2) / halflife)

Key differences from RealizedVolatility:
- More responsive to recent changes
- Decaying weights (recent periods matter more)
- Better for time-varying volatility regimes

Example:
    >>> vol_est = EWMAVolatility(halflife=30, annualization_factor=252)
    >>> returns = pd.DataFrame({'SFRZ4': daily_returns})
    >>> vols = vol_est.estimate(returns)
    >>> vols['SFRZ4']
    0.18  # Recent volatility weighted more

Use Cases:
- Regime changes (low vol → high vol)
- Risk management (respond quickly to vol spikes)
- Options pricing (implied vol estimation)
"""

import numpy as np
import pandas as pd
import polars as pl
from typing import Dict, Union

from Risk.Volatility.VolatilityEstimator import VolatilityEstimator


class EWMAVolatility(VolatilityEstimator):
    """
    Exponentially weighted moving average volatility estimator.

    Estimates volatility with exponentially decaying weights,
    giving more importance to recent observations.

    Attributes:
        halflife: Half-life in periods (higher = slower decay)
        annualization_factor: Factor to annualize volatility

    Methods:
        estimate: Calculate EWMA volatility for each asset

    Example:
        >>> vol_est = EWMAVolatility(halflife=30, annualization_factor=252)
        >>> returns = pd.DataFrame({
        ...     'SFRZ4': np.random.randn(100) * 0.01,
        ... })
        >>> vols = vol_est.estimate(returns)
        >>> vols['SFRZ4']
        0.162
    """

    def __init__(self, halflife: int = 30, annualization_factor: float = 252):
        """
        Initialize EWMA volatility estimator.

        Args:
            halflife: Half-life in periods (default: 30)
                     After `halflife` periods, weight decays to 50%
            annualization_factor: Annualization factor (default: 252 for daily)

        Example:
            Fast adaptation (halflife=10):
            >>> vol_est = EWMAVolatility(halflife=10, annualization_factor=252)

            Slow adaptation (halflife=60):
            >>> vol_est = EWMAVolatility(halflife=60, annualization_factor=252)
        """
        self.halflife = halflife
        self.annualization_factor = annualization_factor

    def estimate(self, returns: Union[pl.DataFrame, pd.DataFrame]) -> Dict[str, float]:
        """
        Calculate EWMA volatility from historical returns.

        Uses pandas ewm (exponentially weighted moment) with halflife.

        Formula:
            EWMA_std = returns.ewm(halflife=h).std()
            Vol = EWMA_std × √(annualization_factor)

        Args:
            returns: Historical returns DataFrame (pandas or polars)
                     Rows = time periods, Columns = assets

        Returns:
            Dict mapping asset → annualized EWMA volatility

        Example:
            >>> returns = pl.DataFrame({
            ...     'SFRZ4': [0.001] * 50 + list(np.random.randn(50) * 0.05)
            ... })
            >>> vol_est = EWMAVolatility(halflife=10, annualization_factor=252)
            >>> vols = vol_est.estimate(returns)
            >>> vols['SFRZ4']  # Higher due to recent high vol
            0.42

        Note:
            - More responsive than RealizedVolatility
            - Recent observations weighted exponentially more
            - Good for detecting regime changes
        """
        if len(returns) == 0:
            return {}

        # Convert polars to pandas for uniform handling
        if isinstance(returns, pl.DataFrame):
            returns = returns.to_pandas()

        # Calculate EWMA standard deviation
        ewm_std = returns.ewm(halflife=self.halflife).std()

        # Use last value (most recent estimate)
        latest_std = ewm_std.iloc[-1]

        # Annualize: Vol = EWMA_std × √T
        annualized_vols = latest_std * np.sqrt(self.annualization_factor)

        # Convert to dict, handling NaN
        vols = annualized_vols.fillna(0.0).to_dict()

        return vols
