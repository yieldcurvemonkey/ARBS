# ABOUTME: Generate trading signals from correlation-volatility divergence
# ABOUTME: Exploits IV/RV ratio convergence for highly correlated asset pairs
"""
CorrelationVolatilitySignal - Volatility Dispersion Trading

Generates signals from correlation-volatility arbitrage opportunities.

Key insight: When correlation is high between assets, their IV/RV ratios should converge.
Divergence creates arbitrage opportunities.

Strategy:
    1. Find highly correlated asset pairs (ρ > 0.85)
    2. Calculate spread: IV_RV_B - IV_RV_A
    3. Z-score the spread over rolling window
    4. Signal = |z_score| × correlation
    5. When |z_score| > threshold, generate trade signal

Trade execution:
    - If z_score > 0: B's ratio is too high → sell B vol, buy A vol
    - If z_score < 0: A's ratio is too high → sell A vol, buy B vol

Example:
    >>> signal = CorrelationVolatilitySignal(min_correlation=0.85, lookback=60, z_threshold=2.0)
    >>> pairs = [('AAPL', 'MSFT'), ('XLK', 'XLF')]
    >>> signals = signal.calculate(returns, vol_ratios, pairs)
    >>> signals
    shape: (2, 6)
    ┌─────────────┬─────────────┬─────────┬──────────┬────────┬──────────────┐
    │ pair        │ correlation │ spread  │ z_score  │ signal │ direction    │
    │ ---         │ ---         │ ---     │ ---      │ ---    │ ---          │
    │ str         │ f64         │ f64     │ f64      │ f64    │ str          │
    ╞═════════════╪═════════════╪═════════╪══════════╪════════╪══════════════╡
    │ AAPL/MSFT   │ 0.92        │ 0.15    │ 2.3      │ 2.12   │ sell_B_vol   │
    │ XLK/XLF     │ 0.88        │ -0.12   │ -2.1     │ 1.85   │ sell_A_vol   │
    └─────────────┴─────────────┴─────────┴──────────┴────────┴──────────────┘
"""

import polars as pl
import numpy as np
from typing import List, Tuple, Dict


class CorrelationVolatilitySignal:
    """
    Generate signals from correlation-volatility arbitrage.

    Attributes:
        min_correlation: Minimum correlation to consider (default: 0.85)
        lookback: Rolling window for z-score calculation (default: 60)
        z_threshold: Minimum |z_score| to generate signal (default: 2.0)
    """

    def __init__(
        self,
        min_correlation: float = 0.85,
        lookback: int = 60,
        z_threshold: float = 2.0
    ):
        """
        Initialize signal generator.

        Args:
            min_correlation: Minimum correlation to consider pairs (0.0 to 1.0)
            lookback: Number of periods for z-score calculation
            z_threshold: Minimum |z_score| to generate trade signal
        """
        self.min_correlation = min_correlation
        self.lookback = lookback
        self.z_threshold = z_threshold

    def calculate(
        self,
        returns: pl.DataFrame,
        vol_ratios: pl.DataFrame,
        pairs: List[Tuple[str, str]]
    ) -> pl.DataFrame:
        """
        Calculate arbitrage signals for asset pairs.

        Args:
            returns: Historical returns with columns [date, ticker, return]
            vol_ratios: IV/RV ratios from VolatilityRatioCalculator
                       Columns: [ticker, date, RV, IV, IV_RV_ratio]
            pairs: List of (asset_A, asset_B) pairs to analyze

        Returns:
            DataFrame with columns [pair, correlation, spread, z_score, signal, direction]

        Example:
            >>> returns = pl.DataFrame({
            ...     'date': dates * 2,
            ...     'ticker': ['AAPL'] * 60 + ['MSFT'] * 60,
            ...     'return': returns_data
            ... })
            >>> vol_ratios = pl.DataFrame({
            ...     'ticker': ['AAPL', 'MSFT'],
            ...     'IV_RV_ratio': [1.33, 1.67]
            ... })
            >>> pairs = [('AAPL', 'MSFT')]
            >>> signals = signal.calculate(returns, vol_ratios, pairs)
        """
        if len(pairs) == 0:
            return pl.DataFrame({
                'pair': [],
                'asset_A': [],
                'asset_B': [],
                'correlation': [],
                'spread': [],
                'z_score': [],
                'signal': [],
                'direction': []
            })

        signals = []

        for asset_A, asset_B in pairs:
            # Calculate correlation
            corr = self._calculate_correlation(returns, asset_A, asset_B)

            # Filter by minimum correlation
            if corr < self.min_correlation:
                continue

            # Get IV/RV ratios
            ratio_A_df = vol_ratios.filter(pl.col('ticker') == asset_A)
            ratio_B_df = vol_ratios.filter(pl.col('ticker') == asset_B)

            # Check if both assets exist
            if ratio_A_df.height == 0 or ratio_B_df.height == 0:
                continue

            ratio_A = ratio_A_df['IV_RV_ratio'][0]
            ratio_B = ratio_B_df['IV_RV_ratio'][0]

            # Calculate spread (B - A)
            spread = ratio_B - ratio_A

            # For time-series z-score, we need historical spreads
            # For now, use a simplified approach with current spread only
            # In production, this should use rolling historical spreads
            z_score = self._calculate_z_score_simple(spread)

            # Signal strength = |z_score| × correlation
            signal_strength = abs(z_score) * corr

            # Filter by threshold
            if signal_strength < self.z_threshold:
                continue

            # Determine direction
            direction = 'sell_B_vol' if z_score > 0 else 'sell_A_vol'

            signals.append({
                'pair': f"{asset_A}/{asset_B}",
                'asset_A': asset_A,
                'asset_B': asset_B,
                'correlation': corr,
                'spread': spread,
                'z_score': z_score,
                'signal': signal_strength,
                'direction': direction
            })

        if signals:
            return pl.DataFrame(signals)
        else:
            return pl.DataFrame({
                'pair': [],
                'asset_A': [],
                'asset_B': [],
                'correlation': [],
                'spread': [],
                'z_score': [],
                'signal': [],
                'direction': []
            })

    def _calculate_correlation(
        self,
        returns: pl.DataFrame,
        asset_A: str,
        asset_B: str
    ) -> float:
        """
        Calculate correlation between two assets.

        Args:
            returns: DataFrame with [date, ticker, return]
            asset_A: First asset ticker
            asset_B: Second asset ticker

        Returns:
            Pearson correlation coefficient
        """
        # Filter returns for each asset
        ret_A = returns.filter(pl.col('ticker') == asset_A).sort('date')['return']
        ret_B = returns.filter(pl.col('ticker') == asset_B).sort('date')['return']

        # Ensure same length
        min_len = min(len(ret_A), len(ret_B))
        if min_len < 2:
            return 0.0

        ret_A = ret_A.to_numpy()[:min_len]
        ret_B = ret_B.to_numpy()[:min_len]

        # Calculate Pearson correlation
        if len(ret_A) < 2 or len(ret_B) < 2:
            return 0.0

        corr_matrix = np.corrcoef(ret_A, ret_B)
        return corr_matrix[0, 1]

    def _calculate_z_score(self, spread: pl.Series) -> pl.Series:
        """
        Calculate z-score of spread using rolling window.

        Args:
            spread: Time series of IV/RV ratio spreads

        Returns:
            Z-scored spread

        Formula:
            z = (x - rolling_mean) / rolling_std
        """
        if len(spread) < self.lookback:
            # Not enough data for full lookback, use all available
            mean = spread.mean()
            std = spread.std()
        else:
            # Use rolling statistics
            mean = spread.rolling_mean(window_size=self.lookback)
            std = spread.rolling_std(window_size=self.lookback)

        # Calculate z-scores
        z_scores = (spread - mean) / std

        # Replace NaN/inf with 0
        z_scores = z_scores.fill_nan(0.0)
        z_scores = z_scores.fill_null(0.0)

        return z_scores

    def _calculate_z_score_simple(self, spread: float) -> float:
        """
        Calculate z-score for a single spread value.

        This is a simplified version that assumes historical mean=0 and std=1.
        In production, this should use historical spread statistics.

        Args:
            spread: Current IV/RV ratio spread

        Returns:
            Z-score (assuming mean=0, std varies by magnitude)
        """
        # Simplified: assume historical mean = 0, std = 0.2 (typical for IV/RV spreads)
        # In production, use actual historical statistics
        typical_std = 0.2
        z_score = spread / typical_std

        return z_score

    def calculate_timeseries(
        self,
        returns: pl.DataFrame,
        vol_ratios_ts: pl.DataFrame,
        pairs: List[Tuple[str, str]]
    ) -> pl.DataFrame:
        """
        Calculate signals over time using rolling windows.

        Args:
            returns: Historical returns with [date, ticker, return]
            vol_ratios_ts: Time series of IV/RV ratios
                          Columns: [ticker, date, RV, IV, IV_RV_ratio]
            pairs: List of (asset_A, asset_B) pairs

        Returns:
            DataFrame with [date, pair, correlation, spread, z_score, signal, direction]

        Example:
            >>> vol_ratios_ts = calc.calculate_ratios_timeseries(returns, implied_vols)
            >>> signals_ts = signal.calculate_timeseries(returns, vol_ratios_ts, pairs)
        """
        all_signals = []

        # Get unique dates from vol_ratios_ts
        dates = sorted(vol_ratios_ts['date'].unique().to_list())

        for date_val in dates:
            # Filter vol_ratios for this date
            vol_ratios_date = vol_ratios_ts.filter(pl.col('date') == date_val)

            # Filter returns up to this date
            returns_date = returns.filter(pl.col('date') <= date_val)

            # Calculate signals for this date
            signals_date = self.calculate(returns_date, vol_ratios_date, pairs)

            # Add date column
            if signals_date.height > 0:
                signals_date = signals_date.with_columns([
                    pl.lit(date_val).alias('date')
                ])
                all_signals.append(signals_date)

        if all_signals:
            result = pl.concat(all_signals)
            # Reorder columns to put date first
            cols = ['date'] + [c for c in result.columns if c != 'date']
            result = result.select(cols)
            return result
        else:
            return pl.DataFrame({
                'date': [],
                'pair': [],
                'asset_A': [],
                'asset_B': [],
                'correlation': [],
                'spread': [],
                'z_score': [],
                'signal': [],
                'direction': []
            })
