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
    >>> import polars as pl
    >>> returns = pl.Series([0.01, -0.01, 0.02, ...])
    >>> tear_sheet = TearSheet(returns, periods_per_year=252)
    >>> metrics = tear_sheet.calculate_metrics()
    >>> print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
    >>> print(f"Max DD: {metrics.max_drawdown:.2%}")

    >>> # Generate plots
    >>> tear_sheet.plot_cumulative_returns()
    >>> tear_sheet.plot_drawdowns()
"""

from dataclasses import dataclass
from typing import Optional, Union
import numpy as np
import polars as pl
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
        returns: Return series (polars Series)
        periods_per_year: Periods per year for annualization (252=daily, 52=weekly)
        dates: Optional date series for aggregation methods

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
        returns: Union[pd.Series, pl.Series, pl.DataFrame],
        periods_per_year: int = 252,
        risk_free_rate: float = 0.0,
        dates: Optional[Union[pd.Series, pl.Series]] = None
    ):
        """
        Initialize tear sheet analyzer.

        Args:
            returns: Return series (decimal, e.g., 0.01 = 1%) or DataFrame with 'date' and returns columns
            periods_per_year: Annualization factor (252=daily, 52=weekly, 12=monthly)
            risk_free_rate: Risk-free rate for Sharpe calculation (annualized)
            dates: Optional date series for aggregation methods (if returns is a Series without dates)

        Example:
            Daily returns:
            >>> tear_sheet = TearSheet(returns, periods_per_year=252)

            Weekly returns:
            >>> tear_sheet = TearSheet(returns, periods_per_year=52)
        """
        # Handle DataFrame or Series with dates
        if isinstance(returns, pl.DataFrame):
            self.dates = returns['date']
            self.returns = returns.select(pl.exclude('date')).to_series()
        else:
            self.returns = returns
            self.dates = dates

        self.periods_per_year = periods_per_year
        self.risk_free_rate = risk_free_rate

    def _to_polars(self, series: Union[pd.Series, pl.Series]) -> pl.Series:
        """Convert pandas Series to polars Series if needed."""
        if isinstance(series, pd.Series):
            return pl.Series(series.values)
        return series

    def _to_pandas(self, series: pl.Series, index=None) -> pd.Series:
        """Convert polars Series to pandas Series."""
        return pd.Series(series.to_list(), index=index)

    def calculate_metrics(self) -> TearSheetMetrics:
        """
        Calculate summary performance metrics.

        Returns:
            TearSheetMetrics with all performance statistics

        Example:
            >>> metrics = tear_sheet.calculate_metrics()
            >>> print(f"Sharpe: {metrics.sharpe_ratio:.2f}")
        """
        returns_pl = self._to_polars(self.returns)

        if len(returns_pl) == 0:
            return TearSheetMetrics(
                total_return=np.nan,
                annual_return=np.nan,
                annual_volatility=np.nan,
                sharpe_ratio=np.nan,
                max_drawdown=np.nan,
                calmar_ratio=np.nan,
            )

        # Total return (compounded)
        returns_array = returns_pl.to_numpy()
        total_return = float(np.prod(1 + returns_array) - 1)

        # Annualized return (geometric mean)
        if len(returns_pl) > 1:
            n_periods = len(returns_pl)
            annual_return = (1 + total_return) ** (self.periods_per_year / n_periods) - 1
        else:
            annual_return = total_return * self.periods_per_year

        # Annualized volatility
        std_val = returns_pl.std()
        if std_val is None or np.isnan(std_val):
            std = 0.0
        else:
            std = float(std_val)
        annual_volatility = std * np.sqrt(self.periods_per_year)

        # Sharpe ratio (annualized, using arithmetic mean)
        # Sharpe uses arithmetic mean, not geometric
        if annual_volatility > 0:
            mean = float(returns_pl.mean())
            arithmetic_annual_return = mean * self.periods_per_year
            sharpe_ratio = (arithmetic_annual_return - self.risk_free_rate) / annual_volatility
        else:
            sharpe_ratio = np.nan

        # Max drawdown
        drawdowns = self.calculate_drawdowns()
        if len(drawdowns) > 0:
            drawdowns_pl = self._to_polars(drawdowns)
            max_drawdown = float(drawdowns_pl.min())
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

    def calculate_drawdowns(self) -> Union[pd.Series, pl.Series]:
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
        returns_pl = self._to_polars(self.returns)

        if len(returns_pl) == 0:
            if isinstance(self.returns, pd.Series):
                return pd.Series(dtype=float)
            return pl.Series(values=[], dtype=pl.Float64)

        # Calculate cumulative returns (wealth index) using numpy
        returns_array = returns_pl.to_numpy()
        wealth_index_array = np.cumprod(1 + returns_array)

        # Calculate running peak using numpy's maximum.accumulate
        running_peak_array = np.maximum.accumulate(wealth_index_array)

        # Drawdown = (current - peak) / peak
        drawdowns_array = (wealth_index_array - running_peak_array) / running_peak_array

        # Return in same format as input
        if isinstance(self.returns, pd.Series):
            return pd.Series(drawdowns_array, index=self.returns.index)
        return pl.Series(values=drawdowns_array, dtype=pl.Float64)

    def calculate_cumulative_returns(self) -> Union[pd.Series, pl.Series]:
        """
        Calculate cumulative return series (starting from 0).

        Returns:
            Series of cumulative returns (decimal)

        Example:
            >>> cum_returns = tear_sheet.calculate_cumulative_returns()
            >>> print(f"Final return: {cum_returns.iloc[-1]:.2%}")
        """
        returns_pl = self._to_polars(self.returns)

        if len(returns_pl) == 0:
            if isinstance(self.returns, pd.Series):
                return pd.Series(dtype=float)
            return pl.Series(values=[], dtype=pl.Float64)

        # Cumulative product - 1 (to start from 0, not 1)
        returns_array = returns_pl.to_numpy()
        cum_returns_array = np.cumprod(1 + returns_array) - 1

        # Return in same format as input
        if isinstance(self.returns, pd.Series):
            return pd.Series(cum_returns_array, index=self.returns.index)
        return pl.Series(values=cum_returns_array, dtype=pl.Float64)

    def aggregate_monthly_returns(self) -> Union[pd.Series, pl.Series]:
        """
        Aggregate returns to monthly frequency.

        Returns:
            Monthly return series (Period index)

        Example:
            >>> monthly = tear_sheet.aggregate_monthly_returns()
            >>> print(monthly.head())
        """
        # Handle polars Series case
        if isinstance(self.returns, pl.Series):
            if len(self.returns) == 0 or self.dates is None:
                return pl.Series(values=[], dtype=pl.Float64)

            dates_pl = self._to_polars(self.dates)
            returns_pl = self.returns

            # Create DataFrame with dates and returns
            df = pl.DataFrame({
                'date': dates_pl,
                'returns': returns_pl
            })

            # Extract year-month
            df = df.with_columns(
                pl.col('date').dt.strftime('%Y-%m').alias('month')
            )

            # Compound returns within each month
            monthly = (
                df.group_by('month')
                .agg(((1 + pl.col('returns')).product() - 1).alias('returns'))
                .sort('month')
            )

            return monthly.select(pl.col('returns')).to_series()

        # Handle pandas Series case
        if len(self.returns) == 0 or not isinstance(self.returns.index, pd.DatetimeIndex):
            return pd.Series(dtype=float)

        # Convert to period index (monthly)
        monthly_returns = self.returns.copy()
        monthly_returns.index = monthly_returns.index.to_period('M')

        # Compound returns within each month
        monthly = (1 + monthly_returns).groupby(level=0).prod() - 1

        return monthly

    def aggregate_annual_returns(self) -> Union[pd.Series, pl.Series]:
        """
        Aggregate returns to annual frequency.

        Returns:
            Annual return series (year index)

        Example:
            >>> annual = tear_sheet.aggregate_annual_returns()
            >>> print(annual)
        """
        # Handle polars Series case
        if isinstance(self.returns, pl.Series):
            if len(self.returns) == 0 or self.dates is None:
                return pl.Series(values=[], dtype=pl.Float64)

            dates_pl = self._to_polars(self.dates)
            returns_pl = self.returns

            # Create DataFrame with dates and returns
            df = pl.DataFrame({
                'date': dates_pl,
                'returns': returns_pl
            })

            # Extract year
            df = df.with_columns(
                pl.col('date').dt.strftime('%Y').alias('year')
            )

            # Compound returns within each year
            annual = (
                df.group_by('year')
                .agg(((1 + pl.col('returns')).product() - 1).alias('returns'))
                .sort('year')
            )

            return annual.select(pl.col('returns')).to_series()

        # Handle pandas Series case
        if len(self.returns) == 0 or not isinstance(self.returns.index, pd.DatetimeIndex):
            return pd.Series(dtype=float)

        # Extract year from index
        annual_returns = self.returns.copy()
        annual_returns.index = annual_returns.index.year

        # Compound returns within each year
        annual = (1 + annual_returns).groupby(level=0).prod() - 1

        return annual
