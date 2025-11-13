# ABOUTME: Calculate implied/realized volatility ratios for volatility dispersion trading
# ABOUTME: Supports single-point and time-series calculations with configurable lookback and annualization
"""
VolatilityRatioCalculator - IV/RV Ratio Calculation

Calculates implied volatility / realized volatility ratios for assets.

Key insight: When correlation is high between assets, their IV/RV ratios should converge.
Divergence creates arbitrage opportunities.

Formulas:
    RV = StdDev(returns) × √(annualization_factor)
    IV/RV ratio = implied_vol / RV

Usage:
    >>> calc = VolatilityRatioCalculator(lookback=30, annualization=252)
    >>> returns_df = pl.DataFrame({
    ...     'date': dates,
    ...     'ticker': tickers,
    ...     'return': returns
    ... })
    >>> implied_vols = {'AAPL': 0.25, 'MSFT': 0.30}
    >>> ratios = calc.calculate_ratios(returns_df, implied_vols)
    >>> ratios
    shape: (2, 5)
    ┌────────┬────────────┬──────┬──────┬──────────────┐
    │ ticker │ date       │ RV   │ IV   │ IV_RV_ratio  │
    │ ---    │ ---        │ ---  │ ---  │ ---          │
    │ str    │ date       │ f64  │ f64  │ f64          │
    ╞════════╪════════════╪══════╪══════╪══════════════╡
    │ AAPL   │ 2024-01-30 │ 0.15 │ 0.25 │ 1.67         │
    │ MSFT   │ 2024-01-30 │ 0.20 │ 0.30 │ 1.50         │
    └────────┴────────────┴──────┴──────┴──────────────┘
"""

import polars as pl
import numpy as np
from typing import Dict, Optional
from datetime import date


class VolatilityRatioCalculator:
    """
    Calculate implied/realized volatility ratios.

    Attributes:
        lookback: Number of periods for RV calculation
        annualization: Annualization factor (252 for daily, 52 for weekly, 12 for monthly)
    """

    def __init__(
        self,
        lookback: int = 30,
        annualization: int = 252
    ):
        """
        Initialize calculator.

        Args:
            lookback: Number of periods to use for RV calculation
            annualization: Factor to annualize volatility
                          - 252 for daily data
                          - 52 for weekly data
                          - 12 for monthly data
        """
        self.lookback = lookback
        self.annualization = annualization

    def calculate_realized_volatility(
        self,
        returns: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate realized volatility for each asset.

        Args:
            returns: DataFrame with columns [date, ticker, return]

        Returns:
            DataFrame with columns [ticker, date, RV]

        Formula:
            RV = std(returns) × √(annualization_factor)
        """
        # Group by ticker and calculate std dev
        result = returns.group_by('ticker').agg([
            pl.col('date').last().alias('date'),
            (pl.col('return').std(ddof=1) * np.sqrt(self.annualization)).alias('RV')
        ])

        return result

    def calculate_ratios(
        self,
        returns: pl.DataFrame,
        implied_vols: Dict[str, float]
    ) -> pl.DataFrame:
        """
        Calculate IV/RV ratios for latest date.

        Args:
            returns: DataFrame with columns [date, ticker, return]
            implied_vols: Dict mapping ticker → implied volatility

        Returns:
            DataFrame with columns [ticker, date, RV, IV, IV_RV_ratio]

        Example:
            >>> returns = pl.DataFrame({
            ...     'date': [date(2024, 1, i) for i in range(1, 31)],
            ...     'ticker': ['AAPL'] * 30,
            ...     'return': np.random.normal(0, 0.01, 30)
            ... })
            >>> implied_vols = {'AAPL': 0.25}
            >>> calc = VolatilityRatioCalculator(lookback=30)
            >>> ratios = calc.calculate_ratios(returns, implied_vols)
        """
        # Calculate RV
        rv_df = self.calculate_realized_volatility(returns)

        # Create IV DataFrame
        iv_data = []
        for ticker, iv in implied_vols.items():
            iv_data.append({'ticker': ticker, 'IV': iv})

        if iv_data:
            iv_df = pl.DataFrame(iv_data)
        else:
            # No implied vols provided
            iv_df = pl.DataFrame({'ticker': [], 'IV': []})

        # Join RV with IV
        if iv_df.height > 0:
            result = rv_df.join(iv_df, on='ticker', how='left')
        else:
            # No IV data, add empty IV column
            result = rv_df.with_columns([
                pl.lit(None, dtype=pl.Float64).alias('IV')
            ])

        # Calculate IV/RV ratio
        result = result.with_columns([
            (pl.col('IV') / pl.col('RV')).alias('IV_RV_ratio')
        ])

        # Select and order columns
        result = result.select(['ticker', 'date', 'RV', 'IV', 'IV_RV_ratio'])

        return result

    def calculate_ratios_timeseries(
        self,
        returns: pl.DataFrame,
        implied_vols: Dict[str, float]
    ) -> pl.DataFrame:
        """
        Calculate IV/RV ratios over time using rolling windows.

        Args:
            returns: DataFrame with columns [date, ticker, return]
            implied_vols: Dict mapping ticker → implied volatility
                         (assumed constant over time for now)

        Returns:
            DataFrame with columns [ticker, date, RV, IV, IV_RV_ratio]
            One row per ticker per date (where lookback is satisfied)

        Example:
            >>> returns = pl.DataFrame({
            ...     'date': [date(2024, 1, 1) + timedelta(days=i) for i in range(60)],
            ...     'ticker': ['AAPL'] * 60,
            ...     'return': np.random.normal(0, 0.01, 60)
            ... })
            >>> implied_vols = {'AAPL': 0.25}
            >>> calc = VolatilityRatioCalculator(lookback=30)
            >>> ts = calc.calculate_ratios_timeseries(returns, implied_vols)
            >>> ts.height  # Should be ~30 rows (60 days - 30 lookback)
            31
        """
        # Sort by ticker and date
        returns = returns.sort(['ticker', 'date'])

        # Calculate rolling RV for each ticker
        result_dfs = []

        for ticker in returns['ticker'].unique().to_list():
            ticker_returns = returns.filter(pl.col('ticker') == ticker)

            # Calculate rolling std dev
            ticker_result = ticker_returns.with_columns([
                pl.col('return')
                .rolling_std(window_size=self.lookback)
                .mul(np.sqrt(self.annualization))
                .alias('RV')
            ])

            # Add IV (constant over time for now)
            iv = implied_vols.get(ticker, None)
            ticker_result = ticker_result.with_columns([
                pl.lit(iv, dtype=pl.Float64).alias('IV')
            ])

            # Calculate IV/RV ratio
            ticker_result = ticker_result.with_columns([
                (pl.col('IV') / pl.col('RV')).alias('IV_RV_ratio')
            ])

            # Drop rows where RV is null (not enough data for lookback)
            ticker_result = ticker_result.filter(pl.col('RV').is_not_null())

            result_dfs.append(ticker_result)

        # Combine all tickers
        if result_dfs:
            result = pl.concat(result_dfs)
        else:
            # No data
            result = pl.DataFrame({
                'ticker': [],
                'date': [],
                'return': [],
                'RV': [],
                'IV': [],
                'IV_RV_ratio': []
            })

        # Select relevant columns
        result = result.select(['ticker', 'date', 'RV', 'IV', 'IV_RV_ratio'])

        return result
