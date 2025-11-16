# ABOUTME: Generate trading signals from correlation-volatility divergence (extends BaseSignal)
# ABOUTME: Exploits IV/RV ratio convergence for highly correlated asset pairs
"""
CorrelationVolatilitySignal - Volatility Dispersion Trading

Generates signals from correlation-volatility arbitrage opportunities using BaseSignal framework.

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

Integration with Grinold-Kahn Framework:
    1. Raw signal = correlation-weighted z-score for each pair
    2. Cross-sectional standardization via BaseSignal
    3. IC tracking for signal quality monitoring
    4. Scaled by AlphaGenerator: α = IC × Vol × Z

Example:
    >>> signal = CorrelationVolatilitySignal(min_correlation=0.85, lookback=60, z_threshold=2.0)
    >>>
    >>> # Define pairs to monitor
    >>> pairs = [('AAPL', 'MSFT'), ('XLK', 'XLF')]
    >>> signal.set_pairs(pairs)
    >>>
    >>> # Generate signals via BaseSignal interface
    >>> pair_data_list = [
    ...     {'returns': returns_df, 'vol_ratios': vol_ratios_df, 'pair': ('AAPL', 'MSFT')},
    ...     {'returns': returns_df, 'vol_ratios': vol_ratios_df, 'pair': ('XLK', 'XLF')},
    ... ]
    >>> z_scores = signal.generate_batch(
    ...     inst_data_list=pair_data_list,
    ...     market_data=None,
    ...     as_of=date(2023, 12, 31)
    ... )
    >>> # z_scores shape: (N,) for N pairs, z-scored across pairs
"""

import polars as pl
import numpy as np
from datetime import date
from typing import List, Tuple, Dict, Optional, Any

from Signals.Base.BaseSignal import BaseSignal


class CorrelationVolatilitySignal(BaseSignal):
    """
    Generate signals from correlation-volatility arbitrage using BaseSignal framework.

    Extends BaseSignal to provide z-score standardization, IC tracking, and
    integration with AlphaGenerator for volatility dispersion strategies.

    Attributes:
        min_correlation: Minimum correlation to consider (default: 0.85)
        lookback: Rolling window for z-score calculation (default: 60)
        z_threshold: Minimum |z_score| to generate signal (default: 2.0)
        pairs: List of (asset_A, asset_B) tuples to monitor
    """

    def __init__(
        self,
        min_correlation: float = 0.85,
        lookback: int = 60,
        z_threshold: float = 2.0,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize correlation-volatility signal.

        Args:
            min_correlation: Minimum correlation to consider pairs (0.0 to 1.0)
            lookback: Number of periods for z-score calculation
            z_threshold: Minimum |z_score| to generate trade signal
            standardize: If True, return z-scored signals (default: True)
            track_history: If True, track signal generation history (default: True)
        """
        super().__init__(
            name="correlation_volatility",
            standardize=standardize,
            track_history=track_history,
        )

        self.min_correlation = min_correlation
        self.lookback = lookback
        self.z_threshold = z_threshold
        self.pairs: List[Tuple[str, str]] = []

    def set_pairs(self, pairs: List[Tuple[str, str]]) -> None:
        """
        Set the asset pairs to monitor for arbitrage opportunities.

        Args:
            pairs: List of (asset_A, asset_B) tuples to monitor

        Example:
            >>> signal.set_pairs([('AAPL', 'MSFT'), ('XLK', 'XLF')])
        """
        self.pairs = pairs

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw arbitrage signal for a single asset pair.

        This method is called by BaseSignal.generate() and generate_batch().
        It computes the correlation-weighted z-score for one pair.

        Args:
            inst_data: DataFrame with columns for one pair:
                      - 'returns': Historical returns for both assets
                      - 'vol_ratios': IV/RV ratios from VolatilityRatioCalculator
                      - 'pair': Tuple of (asset_A, asset_B)
                      OR dictionary with these keys
            market_data: Not used (all data is pair-specific)
            as_of: Calculation date

        Returns:
            Raw signal value (before standardization)
            Formula: signal = |z_score| × correlation × sign(z_score)
                    where z_score = (spread - mean) / std

        Raises:
            ValueError: If missing required data or invalid schema
        """
        # Extract pair information from inst_data
        # Support both DataFrame and dict formats
        if isinstance(inst_data, dict):
            returns = inst_data['returns']
            vol_ratios = inst_data['vol_ratios']
            pair = inst_data['pair']
        elif isinstance(inst_data, pl.DataFrame):
            # Expect columns: asset_A, asset_B, returns_A, returns_B, ratio_A, ratio_B
            if 'pair' in inst_data.columns:
                pair_str = inst_data['pair'][0]
                asset_A, asset_B = pair_str.split('/')
                pair = (asset_A, asset_B)
            else:
                raise ValueError("inst_data must contain 'pair' column or be a dict with 'pair' key")

            returns = inst_data
            vol_ratios = inst_data
        else:
            raise ValueError("inst_data must be DataFrame or dict")

        asset_A, asset_B = pair

        # Calculate correlation
        corr = self._calculate_correlation(returns, asset_A, asset_B)

        # Filter by minimum correlation
        if corr < self.min_correlation:
            return 0.0

        # Get IV/RV ratios for latest date (as_of)
        ratio_A = self._get_ratio_for_asset(vol_ratios, asset_A, as_of)
        ratio_B = self._get_ratio_for_asset(vol_ratios, asset_B, as_of)

        if ratio_A is None or ratio_B is None:
            return 0.0

        # Calculate spread (B - A)
        spread = ratio_B - ratio_A

        # Calculate z-score (simplified: assumes mean=0, std=0.2)
        # In production, use historical spread statistics
        z_score = self._calculate_z_score_simple(spread)

        # Signal strength = |z_score| × correlation, preserve sign
        signal_strength = abs(z_score) * corr * np.sign(z_score)

        # Filter by threshold (using absolute value)
        if abs(signal_strength) < self.z_threshold:
            return 0.0

        return signal_strength

    def calculate(
        self,
        returns: pl.DataFrame,
        vol_ratios: pl.DataFrame,
        pairs: List[Tuple[str, str]],
    ) -> pl.DataFrame:
        """
        Calculate signals for asset pairs (backward compatible API).

        This method maintains backward compatibility with existing code
        while the new BaseSignal interface is available via generate_batch().

        Args:
            returns: Historical returns with [date, ticker, return]
            vol_ratios: IV/RV ratios from VolatilityRatioCalculator
            pairs: List of (asset_A, asset_B) pairs to analyze

        Returns:
            DataFrame with [pair, asset_A, asset_B, correlation, spread, z_score, signal, direction]
        """
        return self.calculate_batch_detailed(returns, vol_ratios, pairs, as_of=None)

    def calculate_batch_detailed(
        self,
        returns: pl.DataFrame,
        vol_ratios: pl.DataFrame,
        pairs: Optional[List[Tuple[str, str]]] = None,
        as_of: Optional[date] = None,
    ) -> pl.DataFrame:
        """
        Calculate signals for multiple pairs with detailed output.

        This is a convenience method that returns detailed DataFrames
        instead of just the z-scored signal array.

        Args:
            returns: Historical returns with columns [date, ticker, return]
            vol_ratios: IV/RV ratios from VolatilityRatioCalculator
                       Columns: [ticker, date, RV, IV, IV_RV_ratio]
            pairs: List of (asset_A, asset_B) pairs to analyze
                  If None, uses self.pairs
            as_of: Calculation date (if None, uses latest date in data)

        Returns:
            DataFrame with columns [pair, correlation, spread, z_score, signal, direction]

        Example:
            >>> signals = signal.calculate_batch_detailed(returns, vol_ratios, pairs)
            >>> print(signals)
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
        if pairs is None:
            pairs = self.pairs

        if not pairs:
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

        # Determine as_of date
        if as_of is None:
            as_of = returns['date'].max()

        signals = []

        for asset_A, asset_B in pairs:
            # Calculate correlation
            corr = self._calculate_correlation(returns, asset_A, asset_B)

            # Filter by minimum correlation
            if corr < self.min_correlation:
                continue

            # Get IV/RV ratios
            ratio_A = self._get_ratio_for_asset(vol_ratios, asset_A, as_of)
            ratio_B = self._get_ratio_for_asset(vol_ratios, asset_B, as_of)

            # Check if both assets exist
            if ratio_A is None or ratio_B is None:
                continue

            # Calculate spread (B - A)
            spread = ratio_B - ratio_A

            # Calculate z-score
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

    def _get_ratio_for_asset(
        self,
        vol_ratios: pl.DataFrame,
        asset: str,
        as_of: date,
    ) -> Optional[float]:
        """
        Get IV/RV ratio for an asset at a specific date.

        Args:
            vol_ratios: DataFrame with [ticker, date, IV_RV_ratio]
            asset: Asset ticker
            as_of: Date to get ratio for

        Returns:
            IV/RV ratio or None if not found
        """
        # Filter to asset and date
        filtered = vol_ratios.filter(
            (pl.col('ticker') == asset) & (pl.col('date') == as_of)
        )

        if filtered.height == 0:
            # Try without date filter (use latest)
            filtered = vol_ratios.filter(pl.col('ticker') == asset)
            if filtered.height == 0:
                return None

        return filtered['IV_RV_ratio'][0]

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

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"CorrelationVolatilitySignal("
            f"name='{self.name}', "
            f"min_correlation={self.min_correlation}, "
            f"lookback={self.lookback}, "
            f"z_threshold={self.z_threshold}, "
            f"n_pairs={len(self.pairs)}, "
            f"standardize={self.standardize}"
            f")"
        )
