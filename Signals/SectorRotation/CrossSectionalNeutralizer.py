# ABOUTME: Normalizes factors cross-sectionally for sector rotation.
# ABOUTME: Implements z-score transformation with mean=0, std=1.
"""
CrossSectionalNeutralizer - Cross-sectional factor normalization (z-scores).

Implements z-score normalization:
    Z_i,t = (X_i,t - μ_t) / σ_t

Where:
    - X_i,t = raw factor value for sector i at time t
    - μ_t = cross-sectional mean at time t (across all sectors)
    - σ_t = cross-sectional std deviation at time t
    - Z_i,t = normalized factor (z-score)

Purpose:
    - Make factors comparable across different time periods
    - Standardize scale for combining multiple factors
    - Remove level effects (absolute values don't matter)
    - Preserve relative ranking (highest stays highest)

Critical for Sector Rotation:
    - Paper uses cross-sectional normalization for all factors
    - Momentum, reversion, and fundamental factors all normalized
    - Enables fair comparison: which sector is RELATIVELY strong?

Properties of Z-Scores:
    - Mean = 0 (centered)
    - Std = 1 (unit variance)
    - Preserves ranking
    - Dimensionless (no units)
    - Outliers get extreme values (|Z| > 3)

Integration with BaseSignal:
    BaseSignal._standardize() does the same thing!
    This class is for factors before they become signals.

Example:
    >>> neutralizer = CrossSectionalNeutralizer()
    >>> factors_df = pl.DataFrame({
    ...     "ticker": ["XLK", "XLE", "XLF", ...],
    ...     "date": [date(2023, 1, 1), ...],
    ...     "momentum": [12.5, -3.2, 8.1, ...],
    ...     "reversion": [-0.05, 0.08, -0.02, ...]
    ... })
    >>> neutral_df = neutralizer.neutralize(
    ...     factors_df,
    ...     factor_columns=["momentum", "reversion"]
    ... )
    >>> # Output: [ticker, date, momentum, reversion, momentum_neutral, reversion_neutral]
    >>> # Where momentum_neutral and reversion_neutral have mean=0, std=1 per date
"""

import polars as pl
from typing import List


class CrossSectionalNeutralizer:
    """
    Cross-sectional factor neutralization (z-score normalization).

    Normalizes factors to mean=0, std=1 within each time period.
    Preserves ranking while making factors comparable.

    Attributes:
        min_sectors: Minimum sectors required for normalization (default: 2)
    """

    def __init__(self, min_sectors: int = 2):
        """
        Initialize neutralizer.

        Parameters:
            min_sectors: Minimum sectors required for normalization (default: 2)
                        Cannot compute std with n=1, so minimum is 2
        """
        if min_sectors < 2:
            raise ValueError("min_sectors must be at least 2 (cannot compute std with n=1)")

        self.min_sectors = min_sectors

    def neutralize(
        self,
        factor_df: pl.DataFrame,
        factor_columns: List[str]
    ) -> pl.DataFrame:
        """
        Neutralize factors cross-sectionally.

        Applies z-score normalization to specified factor columns:
            Z = (X - mean(X)) / std(X)

        Normalization is done separately for each date (cross-sectional).

        Parameters:
            factor_df: DataFrame with columns [ticker, date, factor1, factor2, ...]
            factor_columns: List of column names to neutralize

        Returns:
            DataFrame with original columns plus neutralized versions
            Neutralized columns named: "{factor_name}_neutral"
            Properties per date:
                - mean(factor_neutral) ≈ 0
                - std(factor_neutral) ≈ 1

        Raises:
            ValueError: If insufficient sectors or invalid schema
        """
        # Validate input
        self._validate_schema(factor_df, factor_columns)
        self._validate_sufficient_sectors(factor_df)

        # Start with original DataFrame
        result_df = factor_df.clone()

        # Neutralize each factor column
        for factor_col in factor_columns:
            neutral_col = f"{factor_col}_neutral"

            # Calculate cross-sectional mean and std per date
            # Then compute z-scores
            result_df = result_df.with_columns([
                # Z-score: (X - mean) / std
                (
                    (pl.col(factor_col) - pl.col(factor_col).mean().over("date"))
                    / pl.col(factor_col).std().over("date")
                ).alias(neutral_col)
            ])

        # Handle edge cases
        result_df = self._handle_zero_variance(result_df, factor_columns)

        return result_df

    def _validate_schema(self, df: pl.DataFrame, factor_columns: List[str]) -> None:
        """
        Validate input DataFrame has required columns.

        Parameters:
            df: Input DataFrame
            factor_columns: List of factor column names

        Raises:
            ValueError: If required columns missing or wrong types
        """
        # Check for ticker and date columns
        if "ticker" not in df.columns:
            raise ValueError("Missing required column: 'ticker'")

        if "date" not in df.columns:
            raise ValueError("Missing required column: 'date'")

        # Check for factor columns
        for col in factor_columns:
            if col not in df.columns:
                raise ValueError(
                    f"Factor column '{col}' not found in DataFrame. "
                    f"Available columns: {df.columns}"
                )

            # Check factor column is numeric
            if not df[col].dtype.is_numeric():
                raise ValueError(
                    f"Factor column '{col}' must be numeric, got {df[col].dtype}"
                )

    def _validate_sufficient_sectors(self, df: pl.DataFrame) -> None:
        """
        Validate each date has sufficient sectors for normalization.

        Parameters:
            df: Input DataFrame

        Raises:
            ValueError: If any date has fewer sectors than min_sectors
        """
        # Count sectors per date
        sectors_per_date = df.group_by("date").agg(
            pl.col("ticker").n_unique().alias("n_sectors")
        )

        # Check for insufficient sectors
        insufficient = sectors_per_date.filter(
            pl.col("n_sectors") < self.min_sectors
        )

        if len(insufficient) > 0:
            dates_list = insufficient["date"].to_list()
            min_count = insufficient["n_sectors"].min()

            raise ValueError(
                f"Insufficient sectors for normalization. "
                f"Required: {self.min_sectors}, "
                f"Found: {min_count} for dates: {dates_list[:5]}"
                + (" ..." if len(dates_list) > 5 else "")
            )

    def _handle_zero_variance(
        self,
        df: pl.DataFrame,
        factor_columns: List[str]
    ) -> pl.DataFrame:
        """
        Handle zero variance case (all sectors have same value).

        When std = 0, z-score = (X - mean) / 0 = NaN or Inf.
        Solution: Replace NaN/Inf with 0.0 (valid z-score for zero variance).

        Parameters:
            df: DataFrame with neutralized columns
            factor_columns: List of original factor column names

        Returns:
            DataFrame with NaN/Inf replaced by 0.0 in neutralized columns
        """
        result_df = df

        for factor_col in factor_columns:
            neutral_col = f"{factor_col}_neutral"

            # Replace NaN and Inf with 0.0
            # (Happens when std=0, meaning all values are equal)
            result_df = result_df.with_columns([
                pl.when(pl.col(neutral_col).is_nan() | pl.col(neutral_col).is_infinite())
                .then(0.0)
                .otherwise(pl.col(neutral_col))
                .alias(neutral_col)
            ])

        return result_df

    def __repr__(self) -> str:
        """Return string representation."""
        return f"CrossSectionalNeutralizer(min_sectors={self.min_sectors})"
