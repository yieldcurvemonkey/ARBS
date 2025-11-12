# ABOUTME: Abstract base class for volatility estimation from returns
# ABOUTME: Defines interface for RealizedVolatility, EWMAVolatility, and other estimators
"""
VolatilityEstimator - Abstract Base Class

Estimates asset volatilities from historical returns.

Key insight: Volatility is estimated from RETURNS (not prices).
Returns are stationary, prices are not.

Volatility is needed for:
1. Alpha generation: α = IC × Vol × Z (Grinold-Kahn)
2. Covariance: Cov = Corr × Vol_i × Vol_j
3. Risk decomposition

Formula (Realized):
    Vol_i = StdDev(returns_i) × √T
    where T = annualization factor (252 for daily, 52 for weekly)

Example:
    >>> vol_est = RealizedVolatility(lookback=60)
    >>> returns = pl.DataFrame({'SFRZ4': [0.01, -0.01, 0.02, ...]})
    >>> vols = vol_est.estimate(returns)
    >>> vols['SFRZ4']
    0.15  # 15% annualized volatility
"""

from abc import ABC, abstractmethod
import polars as pl
from typing import Dict


class VolatilityEstimator(ABC):
    """
    Abstract base class for volatility estimation.

    Estimates volatility for each asset from historical returns.

    Attributes:
        annualization_factor: Factor to annualize volatility
                              (252 for daily, 52 for weekly, 12 for monthly)

    Methods:
        estimate: Calculate volatility for each asset

    Example:
        >>> class MyVolEstimator(VolatilityEstimator):
        ...     def estimate(self, returns):
        ...         return returns.std() * np.sqrt(self.annualization_factor)
    """

    @abstractmethod
    def estimate(self, returns: pl.DataFrame) -> Dict[str, float]:
        """
        Estimate volatility for each asset.

        Args:
            returns: Historical returns (DataFrame)
                     Rows = time periods, Columns = assets
                     Values = returns (decimal, e.g., 0.01 = 1%)

        Returns:
            Map from asset → annualized volatility

        Formula:
            Vol = f(returns) × √(annualization_factor)

        Example:
            >>> returns = pl.DataFrame({
            ...     'SFRZ4': [0.01, -0.01, 0.02, -0.02],
            ...     'SFRH5': [0.005, -0.005, 0.01, -0.01]
            ... })
            >>> vols = vol_est.estimate(returns)
            >>> vols
            {'SFRZ4': 0.24, 'SFRH5': 0.15}  # Annualized volatilities

        Note:
            This is an abstract method - subclasses must implement it.
            Different estimators use different formulas:
            - RealizedVolatility: simple historical std dev
            - EWMAVolatility: exponentially weighted std dev
            - GARCHVolatility: conditional volatility from GARCH
        """
        pass
