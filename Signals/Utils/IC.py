# ABOUTME: Information Coefficient (IC) calculation utilities for alpha signal evaluation
# ABOUTME: Provides Pearson/Spearman IC, significance testing, time-series stability, and decay analysis
"""
Information Coefficient (IC) Calculation Utilities

IC is the fundamental measure of signal quality in the Grinold-Kahn framework.
It measures the correlation between alpha forecasts and actual returns.

IC Benchmarks (from 2025 research):
- IC > 0.05: Good predictive power
- IC > 0.10: Very good predictive power
- IC > 0.15: Exceptional (rare in practice)

Statistical significance:
- Need T > 60 for IC > 0.05 @ 95% confidence
- p-value < 0.05 indicates statistical significance

IC decay (halflife):
- < 20 days: High frequency signal
- 20-60 days: Medium frequency
- > 60 days: Low frequency
"""

from typing import Tuple

import numpy as np
import polars as pl
from scipy import stats


def calculate_ic(forecasts: np.ndarray, actuals: np.ndarray) -> float:
    """
    Calculate Information Coefficient (Pearson correlation).

    IC measures the linear correlation between signal forecasts and
    actual returns.

    Args:
        forecasts: Alpha signal values
        actuals: Actual returns

    Returns:
        IC (Pearson correlation coefficient)

    Example:
        >>> forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        >>> actuals = np.array([1.1, 2.2, 2.9, 4.1, 4.8])
        >>> ic = calculate_ic(forecasts, actuals)
        >>> print(f"IC: {ic:.3f}")  # Should be close to 1.0
    """
    # Remove NaN values
    valid_mask = ~(np.isnan(forecasts) | np.isnan(actuals))
    if not np.any(valid_mask):
        return float("nan")

    forecasts_clean = forecasts[valid_mask]
    actuals_clean = actuals[valid_mask]

    # Need at least 2 points for correlation
    if len(forecasts_clean) < 2:
        return float("nan")

    # Check for zero variance (causes NaN in correlation)
    if np.std(forecasts_clean) < 1e-10 or np.std(actuals_clean) < 1e-10:
        # Zero variance → no correlation possible
        return 0.0

    # Calculate Pearson correlation
    ic = np.corrcoef(forecasts_clean, actuals_clean)[0, 1]

    # Handle NaN from correlation calculation
    if np.isnan(ic):
        return 0.0

    return float(ic)


def calculate_rank_ic(forecasts: np.ndarray, actuals: np.ndarray) -> float:
    """
    Calculate Rank Information Coefficient (Spearman correlation).

    Rank IC uses rank correlation instead of linear correlation,
    making it more robust to outliers.

    From 2025 research: Rank IC is preferred when returns have
    heavy tails or extreme outliers.

    Args:
        forecasts: Alpha signal values
        actuals: Actual returns

    Returns:
        Rank IC (Spearman correlation coefficient)

    Example:
        >>> forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        >>> actuals = np.array([10, 20, 30, 40, 1000])  # Last is outlier
        >>> rank_ic = calculate_rank_ic(forecasts, actuals)
        >>> print(f"Rank IC: {rank_ic:.3f}")  # Should be 1.0 (ranks preserved)
    """
    # Remove NaN values
    valid_mask = ~(np.isnan(forecasts) | np.isnan(actuals))
    if not np.any(valid_mask):
        return float("nan")

    forecasts_clean = forecasts[valid_mask]
    actuals_clean = actuals[valid_mask]

    # Need at least 2 points for correlation
    if len(forecasts_clean) < 2:
        return float("nan")

    # Calculate Spearman correlation
    rank_ic, _ = stats.spearmanr(forecasts_clean, actuals_clean)

    return float(rank_ic)


def calculate_ic_significance(
    forecasts: np.ndarray,
    actuals: np.ndarray,
) -> Tuple[float, float]:
    """
    Calculate IC and its statistical significance (p-value).

    Tests the null hypothesis that IC = 0 (no correlation).

    From 2025 research:
    - IC > 0.05 with p < 0.05 indicates significant predictive power
    - Need T > 60 observations for IC > 0.05 @ 95% confidence

    Args:
        forecasts: Alpha signal values
        actuals: Actual returns

    Returns:
        Tuple of (IC, p_value)

    Example:
        >>> np.random.seed(42)
        >>> forecasts = np.random.randn(100)
        >>> actuals = 0.3 * forecasts + 0.7 * np.random.randn(100)
        >>> ic, p_value = calculate_ic_significance(forecasts, actuals)
        >>> print(f"IC: {ic:.3f}, p-value: {p_value:.4f}")
    """
    # Remove NaN values
    valid_mask = ~(np.isnan(forecasts) | np.isnan(actuals))
    if not np.any(valid_mask):
        return np.nan, np.nan

    forecasts_clean = forecasts[valid_mask]
    actuals_clean = actuals[valid_mask]

    # Need at least 3 points for significance test
    if len(forecasts_clean) < 3:
        return np.nan, np.nan

    # Calculate Pearson correlation and p-value
    ic, p_value = stats.pearsonr(forecasts_clean, actuals_clean)

    return ic, p_value


def calculate_ic_time_series(
    forecasts: pl.Series,
    actuals: pl.Series,
    window: int = 20,
) -> pl.Series:
    """
    Calculate rolling IC over time.

    This measures IC stability, one of the AlphaEval framework's
    five dimensions for alpha quality.

    Args:
        forecasts: Time series of forecasts (indexed by date)
        actuals: Time series of actuals (indexed by date)
        window: Rolling window size (default: 20 days)

    Returns:
        Time series of rolling IC values

    Example:
        >>> dates = pl.datetime_range('2025-01-01', periods=100, interval='1d')
        >>> forecasts = pl.Series(np.random.randn(100))
        >>> actuals = pl.Series(0.2 * forecasts + 0.8 * np.random.randn(100))
        >>> ic_series = calculate_ic_time_series(forecasts, actuals, window=20)
        >>> print(f"IC stability (std): {ic_series.std():.3f}")
    """
    # Align forecasts and actuals (no index needed - polars is index-free)
    aligned = pl.DataFrame(
        {
            "forecast": forecasts,
            "actual": actuals,
        }
    ).drop_nulls()

    if len(aligned) < window:
        return pl.Series(dtype=pl.Float64)

    # Calculate rolling correlation
    # Use rolling window to compute correlation at each position
    ic_values = []
    for i in range(len(aligned) - window + 1):
        window_forecast = aligned["forecast"][i : i + window].to_numpy()
        window_actual = aligned["actual"][i : i + window].to_numpy()
        ic = calculate_ic(window_forecast, window_actual)
        ic_values.append(ic)

    # Return series of IC values (caller manages alignment if needed)
    result = pl.Series(ic_values)
    return result.drop_nulls()


def calculate_ic_decay(
    forecasts: pl.Series,
    actuals: pl.Series,
    max_lag: int = 60,
) -> float:
    """
    Calculate IC decay (halflife in days).

    IC decay measures how quickly a signal's predictive power deteriorates.
    From 2025 research:
    - Halflife < 20 days: High frequency (requires fast execution)
    - Halflife 20-60 days: Medium frequency (most carry/value signals)
    - Halflife > 60 days: Low frequency (macro/fundamental)

    Args:
        forecasts: Time series of forecasts
        actuals: Time series of actuals
        max_lag: Maximum lag to test (default: 60 days)

    Returns:
        Halflife in days (time for IC to decay to 50% of initial)

    Example:
        >>> dates = pl.datetime_range('2025-01-01', periods=100, interval='1d')
        >>> forecasts = pl.Series(np.random.randn(100))
        >>> # Create signal with 20-day halflife
        >>> days = np.arange(100)
        >>> decay = np.exp(-days / 20)
        >>> actuals = pl.Series(decay * forecasts + (1-decay) * np.random.randn(100))
        >>> halflife = calculate_ic_decay(forecasts, actuals)
        >>> print(f"Halflife: {halflife:.1f} days")  # Should be ~20
    """
    # Calculate IC at different lags
    ic_at_lags = []

    for lag in range(0, min(max_lag, len(forecasts) - 10)):
        # Shift actuals by lag
        actuals_lagged = actuals.shift(-lag)

        # Calculate IC
        ic = calculate_ic(forecasts.to_numpy(), actuals_lagged.to_numpy())

        if not np.isnan(ic):
            ic_at_lags.append((lag, abs(ic)))  # Use absolute IC

    if len(ic_at_lags) < 3:
        return float("nan")

    # Convert to DataFrame
    ic_df = pl.DataFrame(ic_at_lags, schema=["lag", "ic"])

    # Initial IC (at lag 0)
    ic_0 = ic_df.filter(pl.col("lag") == 0).select("ic")[0, 0]

    if ic_0 < 0.01:
        # IC too small to measure decay
        return float("nan")

    # Find halflife: lag where IC drops to 50% of initial
    target_ic = ic_0 * 0.5

    # Find first lag where IC < target
    below_target = ic_df.filter(pl.col("ic") < target_ic)

    if len(below_target) == 0:
        # IC hasn't decayed to 50% within max_lag
        return float(max_lag)

    # Get exact halflife (first lag where IC drops below target)
    halflife = below_target.row(0)[0]  # Get 'lag' value from first row

    return float(halflife)


def calculate_ic_statistics(
    forecasts: pl.Series,
    actuals: pl.Series,
    window: int = 20,
) -> dict:
    """
    Calculate comprehensive IC statistics.

    Returns all key IC metrics in one call:
    - IC (mean)
    - Rank IC (mean)
    - IC stability (std of rolling IC)
    - IC decay (halflife)
    - Statistical significance (p-value)

    This implements the AlphaEval framework's predictive power
    and stability dimensions.

    Args:
        forecasts: Time series of forecasts
        actuals: Time series of actuals
        window: Rolling window for IC time series

    Returns:
        Dictionary with IC statistics

    Example:
        >>> dates = pl.datetime_range('2025-01-01', periods=100, interval='1d')
        >>> forecasts = pl.Series(np.random.randn(100))
        >>> actuals = pl.Series(0.3 * forecasts + 0.7 * np.random.randn(100))
        >>> stats = calculate_ic_statistics(forecasts, actuals)
        >>> print(f"IC: {stats['ic']:.3f}, Stability: {stats['ic_stability']:.3f}")
    """
    # Overall IC
    ic, p_value = calculate_ic_significance(forecasts.to_numpy(), actuals.to_numpy())

    # Rank IC (robust to outliers)
    rank_ic = calculate_rank_ic(forecasts.to_numpy(), actuals.to_numpy())

    # IC time series (stability)
    ic_series = calculate_ic_time_series(forecasts, actuals, window=window)
    ic_stability = ic_series.std() if len(ic_series) > 0 else np.nan

    # IC decay (halflife)
    ic_decay = calculate_ic_decay(forecasts, actuals)

    return {
        "ic": ic,
        "rank_ic": rank_ic,
        "ic_stability": ic_stability,
        "ic_decay_halflife": ic_decay,
        "p_value": p_value,
        "n_observations": len(forecasts),
    }
