# ABOUTME: ReturnsCalculator converts prices to returns at data layer
# ABOUTME: Supports percent returns and log returns with proper edge case handling
"""
ReturnsCalculator - Price to Return Conversion

Converts price changes to returns ONCE at data layer.
All downstream components work with returns, not prices.

Key insight: Prices are levels (non-stationary), returns are differences (stationary).
Portfolio mathematics requires stationary data:
- Covariance of prices is meaningless
- Covariance of returns is well-defined
- Portfolio return = Σ w_i × r_i (weighted sum of RETURNS)

Return Types:
1. Percent returns: r = (P_t - P_{t-1}) / P_{t-1}
   - Scale-free (comparable across assets)
   - Additive for portfolios
   - Standard in Grinold-Kahn framework

2. Log returns: r = log(P_t / P_{t-1})
   - Time-additive: r_0→t = Σ r_i
   - Approximately equal to percent for small changes
   - Better statistical properties (more normal)

Example:
    Percent returns (default):
    >>> calc = ReturnsCalculator(method="percent")
    >>> prev = {'SFRZ4': 95.0, 'SFRH5': 94.0}
    >>> curr = {'SFRZ4': 96.0, 'SFRH5': 94.5}
    >>> returns = calc.calculate_returns(curr, prev)
    >>> returns
    {'SFRZ4': 0.010526, 'SFRH5': 0.005319}

    Log returns:
    >>> calc = ReturnsCalculator(method="log")
    >>> returns = calc.calculate_returns(curr, prev)
    >>> returns
    {'SFRZ4': 0.010471, 'SFRH5': 0.005305}
"""

import numpy as np
from typing import Dict


class ReturnsCalculator:
    """
    Convert prices to returns at data layer.

    Performs price → return conversion ONCE, enabling all downstream
    components to work with stationary data (returns).

    Attributes:
        method: Return calculation method ('percent' or 'log')

    Methods:
        calculate_returns: Convert price dicts → return dict

    Example:
        >>> calc = ReturnsCalculator(method="percent")
        >>> prev_prices = {'SFRZ4': 95.0, 'SFRH5': 94.0}
        >>> curr_prices = {'SFRZ4': 96.0, 'SFRH5': 94.5}
        >>> returns = calc.calculate_returns(curr_prices, prev_prices)
        >>> returns['SFRZ4']
        0.010526315789473684
    """

    def __init__(self, method: str = "percent"):
        """
        Initialize returns calculator.

        Args:
            method: Calculation method ('percent' or 'log')
                    Default: 'percent' (standard for Grinold-Kahn)

        Raises:
            ValueError: If method not in {'percent', 'log'}

        Example:
            >>> calc = ReturnsCalculator(method="percent")
            >>> calc.method
            'percent'
        """
        if method not in {"percent", "log"}:
            raise ValueError(f"method must be 'percent' or 'log', got '{method}'")
        self.method = method

    def calculate_returns(
        self,
        curr_prices: Dict[str, float],
        prev_prices: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Calculate returns from price changes.

        Converts prices → returns ONCE at data layer.
        Downstream components work with returns, not prices.

        Args:
            curr_prices: Current prices (map: asset → price)
            prev_prices: Previous prices (map: asset → price)

        Returns:
            Returns for each asset (map: asset → return)

        Formula:
            Percent: r = (P_t - P_{t-1}) / P_{t-1}
            Log:     r = log(P_t / P_{t-1})

        Edge Cases:
            - Missing previous price → return = 0
            - Zero previous price → return = 0
            - Negative previous price → return = 0

        Example:
            >>> calc = ReturnsCalculator(method="percent")
            >>> prev = {'SFRZ4': 95.0, 'SFRH5': 94.0}
            >>> curr = {'SFRZ4': 96.0, 'SFRH5': 94.5}
            >>> calc.calculate_returns(curr, prev)
            {'SFRZ4': 0.010526, 'SFRH5': 0.005319}

        Note:
            For percent returns with portfolio weights w:
                r_portfolio = Σ w_i × r_i
            This is the foundation of Grinold-Kahn portfolio math.
        """
        returns = {}

        for asset, curr_price in curr_prices.items():
            prev_price = prev_prices.get(asset, 0.0)

            # Edge case: invalid previous price → return 0
            if prev_price <= 0:
                returns[asset] = 0.0
                continue

            # Calculate return based on method
            if self.method == "percent":
                returns[asset] = (curr_price - prev_price) / prev_price
            elif self.method == "log":
                returns[asset] = np.log(curr_price / prev_price)

        return returns
