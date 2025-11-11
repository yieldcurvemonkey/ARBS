# ABOUTME: TearSheet class for strategy performance analysis and visualization
# ABOUTME: Generates metrics (Sharpe, drawdown) and plots (cumulative returns, heatmap)
"""
TearSheet - Strategy Performance Analysis

Generates comprehensive performance analysis including:
- Summary statistics (returns, Sharpe, drawdown, volatility)
- Drawdown analysis (max drawdown, recovery periods)
- Cumulative returns
- Monthly/annual aggregation

Inspired by pyfolio tear sheets but tailored for futures/swaps strategies.

Example:
    >>> returns = pd.Series([0.01, -0.01, 0.02, ...])
    >>> tear_sheet = TearSheet(returns, periods_per_year=252)
    >>> metrics = tear_sheet.calculate_metrics()
    >>> print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
    >>> print(f"Max DD: {metrics.max_drawdown:.2%}")

    >>> # Generate plots
    >>> tear_sheet.plot_cumulative_returns()
    >>> tear_sheet.plot_drawdowns()
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class TearSheetMetrics:
    """
    Summary metrics from tear sheet analysis.

    Attributes:
        total_return: Cumulative return over entire period
        annual_return: Annualized return (geometric mean)
        annual_volatility: Annualized volatility (std dev)
        sharpe_ratio: Risk-adjusted return (annualized)
        max_drawdown: Maximum peak-to-trough decline
        calmar_ratio: Annual return / abs(max drawdown)
    """
    total_return: float
    annual_return: float
    annual_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float

    def __str__(self) -> str:
        """Format metrics for display."""
        return f"""
Performance Metrics
===================
Total Return:      {self.total_return:>8.2%}
Annual Return:     {self.annual_return:>8.2%}
Annual Volatility: {self.annual_volatility:>8.2%}
Sharpe Ratio:      {self.sharpe_ratio:>8.2f}
Max Drawdown:      {self.max_drawdown:>8.2%}
Calmar Ratio:      {self.calmar_ratio:>8.2f}
        """.strip()


class TearSheet:
    """
    Strategy performance tear sheet generator.

    Analyzes return series and generates performance metrics,
    drawdown analysis, and visualization plots.

    Attributes:
        returns: Return series (indexed by date)
        periods_per_year: Periods per year for annualization (252=daily, 52=weekly)

    Methods:
        calculate_metrics: Compute summary statistics
        calculate_drawdowns: Compute drawdown series
        calculate_cumulative_returns: Compute cumulative return series
        aggregate_monthly_returns: Aggregate to monthly returns
        aggregate_annual_returns: Aggregate to annual returns

    Example:
        >>> tear_sheet = TearSheet(returns, periods_per_year=252)
        >>> metrics = tear_sheet.calculate_metrics()
        >>> print(metrics)
        >>> drawdowns = tear_sheet.calculate_drawdowns()
    """

    def __init__(
        self,
        returns: pd.Series,
        periods_per_year: int = 252,
        risk_free_rate: float = 0.0
    ):
        """
        Initialize tear sheet analyzer.

        Args:
            returns: Return series (decimal, e.g., 0.01 = 1%)
            periods_per_year: Annualization factor (252=daily, 52=weekly, 12=monthly)
            risk_free_rate: Risk-free rate for Sharpe calculation (annualized)

        Example:
            Daily returns:
            >>> tear_sheet = TearSheet(returns, periods_per_year=252)

            Weekly returns:
            >>> tear_sheet = TearSheet(returns, periods_per_year=52)
        """
        self.returns = returns
        self.periods_per_year = periods_per_year
        self.risk_free_rate = risk_free_rate

    def calculate_metrics(self) -> TearSheetMetrics:
        """
        Calculate summary performance metrics.

        Returns:
            TearSheetMetrics with all performance statistics

        Example:
            >>> metrics = tear_sheet.calculate_metrics()
            >>> print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
        """
        if len(self.returns) == 0:
            return TearSheetMetrics(
                total_return=np.nan,
                annual_return=np.nan,
                annual_volatility=np.nan,
                sharpe_ratio=np.nan,
                max_drawdown=np.nan,
                calmar_ratio=np.nan,
            )

        # Total return (compounded)
        total_return = (1 + self.returns).prod() - 1

        # Annualized return (geometric mean)
        if len(self.returns) > 1:
            n_periods = len(self.returns)
            annual_return = (1 + total_return) ** (self.periods_per_year / n_periods) - 1
        else:
            annual_return = total_return * self.periods_per_year

        # Annualized volatility
        annual_volatility = self.returns.std() * np.sqrt(self.periods_per_year)

        # Sharpe ratio (annualized, using arithmetic mean)
        # Sharpe uses arithmetic mean, not geometric
        if annual_volatility > 0:
            arithmetic_annual_return = self.returns.mean() * self.periods_per_year
            sharpe_ratio = (arithmetic_annual_return - self.risk_free_rate) / annual_volatility
        else:
            sharpe_ratio = np.nan

        # Max drawdown
        drawdowns = self.calculate_drawdowns()
        if len(drawdowns) > 0:
            max_drawdown = drawdowns.min()
        else:
            max_drawdown = 0.0

        # Calmar ratio
        if max_drawdown < 0:
            calmar_ratio = annual_return / abs(max_drawdown)
        else:
            calmar_ratio = np.nan

        return TearSheetMetrics(
            total_return=total_return,
            annual_return=annual_return,
            annual_volatility=annual_volatility,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            calmar_ratio=calmar_ratio,
        )

    def calculate_drawdowns(self) -> pd.Series:
        """
        Calculate drawdown series (distance from running peak).

        Drawdown = (current_value - peak_value) / peak_value

        Returns:
            Series of drawdowns (negative values, 0 at peaks)

        Example:
            >>> drawdowns = tear_sheet.calculate_drawdowns()
            >>> max_dd = drawdowns.min()
            >>> print(f"Max drawdown: {max_dd:.2%}")
        """
        if len(self.returns) == 0:
            return pd.Series(dtype=float)

        # Calculate cumulative returns (wealth index)
        wealth_index = (1 + self.returns).cumprod()

        # Calculate running peak
        running_peak = wealth_index.expanding().max()

        # Drawdown = (current - peak) / peak
        drawdowns = (wealth_index - running_peak) / running_peak

        return drawdowns

    def calculate_cumulative_returns(self) -> pd.Series:
        """
        Calculate cumulative return series (starting from 0).

        Returns:
            Series of cumulative returns (decimal)

        Example:
            >>> cum_returns = tear_sheet.calculate_cumulative_returns()
            >>> print(f"Final return: {cum_returns.iloc[-1]:.2%}")
        """
        if len(self.returns) == 0:
            return pd.Series(dtype=float)

        # Cumulative product - 1 (to start from 0, not 1)
        cum_returns = (1 + self.returns).cumprod() - 1

        return cum_returns

    def aggregate_monthly_returns(self) -> pd.Series:
        """
        Aggregate returns to monthly frequency.

        Returns:
            Monthly return series (Period index)

        Example:
            >>> monthly = tear_sheet.aggregate_monthly_returns()
            >>> print(monthly.head())
        """
        if len(self.returns) == 0 or not isinstance(self.returns.index, pd.DatetimeIndex):
            return pd.Series(dtype=float)

        # Convert to period index (monthly)
        monthly_returns = self.returns.copy()
        monthly_returns.index = monthly_returns.index.to_period('M')

        # Compound returns within each month
        monthly = (1 + monthly_returns).groupby(level=0).prod() - 1

        return monthly

    def aggregate_annual_returns(self) -> pd.Series:
        """
        Aggregate returns to annual frequency.

        Returns:
            Annual return series (year index)

        Example:
            >>> annual = tear_sheet.aggregate_annual_returns()
            >>> print(annual)
        """
        if len(self.returns) == 0 or not isinstance(self.returns.index, pd.DatetimeIndex):
            return pd.Series(dtype=float)

        # Extract year from index
        annual_returns = self.returns.copy()
        annual_returns.index = annual_returns.index.year

        # Compound returns within each year
        annual = (1 + annual_returns).groupby(level=0).prod() - 1

        return annual
