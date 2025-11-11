# ABOUTME: RealizedVolatility estimator using historical standard deviation
# ABOUTME: Implements simple realized volatility with lookback window and annualization
"""
RealizedVolatility - Historical Standard Deviation

Estimates volatility as standard deviation of historical returns.

Formula:
    Vol_i = StdDev(returns_i[-lookback:]) × √(annualization_factor)

Where:
- returns_i = historical returns for asset i
- lookback = number of periods to use
- annualization_factor = scaling factor (252 for daily, 52 for weekly)

Example:
    Daily returns, 60-day lookback:
    >>> vol_est = RealizedVolatility(lookback=60, annualization_factor=252)
    >>> returns = pd.DataFrame({'SFRZ4': daily_returns})
    >>> vols = vol_est.estimate(returns)
    >>> vols['SFRZ4']
    0.15  # 15% annualized volatility

    Weekly returns, 52-week lookback:
    >>> vol_est = RealizedVolatility(lookback=52, annualization_factor=52)
    >>> returns = pd.DataFrame({'SFRZ4': weekly_returns})
    >>> vols = vol_est.estimate(returns)
"""

import numpy as np
import pandas as pd
from typing import Dict

from Risk.Volatility.VolatilityEstimator import VolatilityEstimator


class RealizedVolatility(VolatilityEstimator):
    """
    Realized volatility estimator.

    Calculates volatility as standard deviation of historical returns
    over a lookback window, then annualizes.

    Attributes:
        lookback: Number of periods to use for calculation
        annualization_factor: Factor to annualize volatility

    Methods:
        estimate: Calculate realized volatility for each asset

    Example:
        >>> vol_est = RealizedVolatility(lookback=60, annualization_factor=252)
        >>> returns = pd.DataFrame({
        ...     'SFRZ4': np.random.randn(100) * 0.01,
        ...     'SFRH5': np.random.randn(100) * 0.015
        ... })
        >>> vols = vol_est.estimate(returns)
        >>> vols['SFRZ4']  # Annualized volatility
        0.158
    """

    def __init__(self, lookback: int = 60, annualization_factor: float = 252):
        """
        Initialize realized volatility estimator.

        Args:
            lookback: Number of periods to use (default: 60)
            annualization_factor: Annualization factor (default: 252 for daily)

        Example:
            Daily data (252 trading days/year):
            >>> vol_est = RealizedVolatility(lookback=60, annualization_factor=252)

            Weekly data (52 weeks/year):
            >>> vol_est = RealizedVolatility(lookback=52, annualization_factor=52)
        """
        self.lookback = lookback
        self.annualization_factor = annualization_factor

    def estimate(self, returns: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate realized volatility from historical returns.

        Formula:
            Vol = StdDev(returns[-lookback:]) × √(annualization_factor)

        Args:
            returns: Historical returns DataFrame
                     Rows = time periods, Columns = assets

        Returns:
            Dict mapping asset → annualized volatility

        Example:
            >>> returns = pd.DataFrame({
            ...     'SFRZ4': [0.01, -0.01, 0.02, -0.02, 0.01],
            ...     'SFRH5': [0.005, -0.005, 0.01, -0.01, 0.005]
            ... })
            >>> vol_est = RealizedVolatility(lookback=5, annualization_factor=252)
            >>> vols = vol_est.estimate(returns)
            >>> vols['SFRZ4']  # Annualized from 5 daily returns
            0.238

        Note:
            - Uses last `lookback` periods (or all available if less)
            - Annualizes by multiplying by √(annualization_factor)
            - Returns 0 for constant returns (zero variance)
        """
        if len(returns) == 0:
            return {}

        # Use last `lookback` periods (or all if insufficient data)
        recent_returns = returns.tail(self.lookback)

        # Calculate standard deviation for each asset
        std_devs = recent_returns.std()

        # Annualize: Vol = Std × √T
        annualized_vols = std_devs * np.sqrt(self.annualization_factor)

        # Convert to dict, handling NaN
        vols = annualized_vols.fillna(0.0).to_dict()

        return vols
