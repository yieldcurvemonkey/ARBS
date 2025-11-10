# ABOUTME: Abstract base class for all backtest implementations
# ABOUTME: Defines standard interface for run() method and result handling
"""
BaseBacktest - Abstract base class for backtesting

All backtests should inherit from this class and implement
the run() method to execute the backtest loop.

Input format:
- contracts: List of contract codes
- dates: List of backtest dates
- market_data_provider: Source of prices

Output format:
- BacktestResult with:
  - weights: DataFrame of portfolio weights over time
  - returns: Series of portfolio returns
  - ic: Information coefficient
  - sharpe_ratio: Sharpe ratio
  - total_return: Cumulative return
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, List
import pandas as pd


@dataclass
class BacktestResult:
    """
    Results from a backtest run.

    Attributes:
        weights: DataFrame of portfolio weights (dates × contracts)
        returns: Series of portfolio returns
        signals: DataFrame of signal values over time
        prices: DataFrame of prices over time
        ic: Information coefficient (correlation of forecasts vs actuals)
        sharpe_ratio: Return / volatility (annualized)
        total_return: Cumulative return over backtest period
    """
    weights: pd.DataFrame
    returns: pd.Series
    signals: pd.DataFrame
    prices: pd.DataFrame
    ic: float
    sharpe_ratio: float
    total_return: float


class BaseBacktest(ABC):
    """
    Abstract base class for backtests.

    All backtests must implement run() which executes the
    backtest loop and returns a BacktestResult.
    """

    def __init__(self, market_data_provider: Any):
        """
        Initialize backtest.

        Args:
            market_data_provider: Source of market prices/curves
        """
        self.mdp = market_data_provider

    @abstractmethod
    def run(
        self,
        contracts: List[str],
        dates: List[date],
    ) -> BacktestResult:
        """
        Run backtest over specified dates.

        Args:
            contracts: List of contract codes to trade
            dates: List of backtest dates

        Returns:
            BacktestResult with performance metrics

        Example:
            >>> contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
            >>> dates = pd.date_range('2024-01-01', '2024-12-31', freq='W')
            >>> result = backtest.run(contracts, dates.tolist())
            >>> print(f"Sharpe: {result.sharpe_ratio:.2f}, IC: {result.ic:.3f}")
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(mdp={self.mdp})"
