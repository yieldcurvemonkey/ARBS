# ABOUTME: Unit tests for CrossSectionalNeutralizer (TDD approach).
# ABOUTME: Tests z-score normalization formula before implementation.
"""
Test CrossSectionalNeutralizer - Cross-sectional factor normalization.

TDD Approach: These tests are written FIRST, before implementation.

Purpose:
- Normalize factors to z-scores (mean=0, std=1) within each time period
- Makes factors comparable across different sectors and time periods
- Critical for combining momentum, reversion, and fundamental factors

Formula:
    Z_i,t = (X_i,t - μ_t) / σ_t

Where:
    - X_i,t = raw factor value for sector i at time t
    - μ_t = cross-sectional mean at time t (across all sectors)
    - σ_t = cross-sectional std at time t (across all sectors)
    - Z_i,t = normalized factor (z-score)

Properties:
    - Preserves ranking (highest stays highest)
    - Removes level effects (absolute factor values don't matter)
    - Standardizes scale (all factors on same scale for combining)
"""

import polars as pl
import numpy as np
from datetime import date, timedelta


class TestCrossSectionalNeutralization:
    """Test factor neutralization produces correct statistics."""

    def test_neutralization_formula(self):
        """
        Test Z = (X - mean(X)) / std(X).

        Setup:
            - 11 sectors with factor values: [10, 12, 8, 15, 9, 11, 13, 7, 14, 10, 11]

        Expected:
            - Mean of neutralized ≈ 0.0
            - Std of neutralized ≈ 1.0

        Assert:
            abs(mean(Z)) < 1e-6
            abs(std(Z) - 1.0) < 1e-6
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"],
            "date": [date(2023, 1, 1)] * 11,
            "momentum": [10.0, 12.0, 8.0, 15.0, 9.0, 11.0, 13.0, 7.0, 14.0, 10.0, 11.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["momentum"])

        # Check neutralized values
        z_scores = result_df["momentum_neutral"].to_numpy()

        mean_z = np.mean(z_scores)
        std_z = np.std(z_scores, ddof=1)  # Sample std (n-1)

        assert abs(mean_z) < 1e-6, f"Mean should be ~0, got {mean_z}"
        assert abs(std_z - 1.0) < 1e-6, f"Std should be ~1, got {std_z}"

    def test_neutralization_preserves_ranking(self):
        """
        Test neutralization preserves relative ranking.

        Setup:
            - Original: [5, 10, 15, 20]
            - Neutralized: Z-scores

        Assert:
            - rank(original) == rank(neutralized)
            - Highest value stays highest after neutralization
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["A", "B", "C", "D"],
            "date": [date(2023, 1, 1)] * 4,
            "factor": [5.0, 10.0, 15.0, 20.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        # Original ranking
        original_rank = factor_df.with_columns(
            pl.col("factor").rank().alias("rank")
        )["rank"].to_list()

        # Neutralized ranking
        neutral_rank = result_df.with_columns(
            pl.col("factor_neutral").rank().alias("rank")
        )["rank"].to_list()

        assert original_rank == neutral_rank

    def test_neutralization_per_time_period(self):
        """
        Test neutralization applied separately per time period.

        Setup:
            - Q1: 11 sectors with factor values
            - Q2: Same 11 sectors with different values

        Assert:
            - Q1 neutralized has mean=0, std=1
            - Q2 neutralized has mean=0, std=1
            - Q1 and Q2 treated independently
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        sectors = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"]

        # Q1 data
        q1_df = pl.DataFrame({
            "ticker": sectors,
            "date": [date(2023, 1, 1)] * 11,
            "factor": [10.0, 12.0, 8.0, 15.0, 9.0, 11.0, 13.0, 7.0, 14.0, 10.0, 11.0]
        })

        # Q2 data (different values)
        q2_df = pl.DataFrame({
            "ticker": sectors,
            "date": [date(2023, 4, 1)] * 11,
            "factor": [5.0, 8.0, 12.0, 6.0, 15.0, 9.0, 7.0, 10.0, 11.0, 8.0, 9.0]
        })

        factor_df = pl.concat([q1_df, q2_df])

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        # Check Q1 neutralization
        q1_neutral = result_df.filter(pl.col("date") == date(2023, 1, 1))["factor_neutral"].to_numpy()
        assert abs(np.mean(q1_neutral)) < 1e-6
        assert abs(np.std(q1_neutral, ddof=1) - 1.0) < 1e-6

        # Check Q2 neutralization
        q2_neutral = result_df.filter(pl.col("date") == date(2023, 4, 1))["factor_neutral"].to_numpy()
        assert abs(np.mean(q2_neutral)) < 1e-6
        assert abs(np.std(q2_neutral, ddof=1) - 1.0) < 1e-6

    def test_neutralization_multiple_factors(self):
        """
        Test neutralizing multiple factors simultaneously.

        Setup:
            - DataFrame with momentum, reversion, and fundamental factors
            - Neutralize all three at once

        Assert:
            - Each factor has mean=0, std=1
            - Different factors can have different z-scores for same sector
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"],
            "date": [date(2023, 1, 1)] * 11,
            "momentum": [10.0, 12.0, 8.0, 15.0, 9.0, 11.0, 13.0, 7.0, 14.0, 10.0, 11.0],
            "reversion": [-0.05, 0.02, -0.01, 0.08, -0.03, 0.01, 0.04, -0.06, 0.05, -0.02, 0.0],
            "fundamental": [0.6, 0.7, 0.5, 0.9, 0.4, 0.65, 0.75, 0.3, 0.8, 0.55, 0.6]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(
            factor_df,
            factor_columns=["momentum", "reversion", "fundamental"]
        )

        # Check all factors neutralized
        for factor_name in ["momentum", "reversion", "fundamental"]:
            neutral_col = f"{factor_name}_neutral"
            assert neutral_col in result_df.columns

            z_scores = result_df[neutral_col].to_numpy()
            assert abs(np.mean(z_scores)) < 1e-6
            assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-6


class TestNeutralizationEdgeCases:
    """Test neutralization edge cases."""

    def test_constant_factor_values(self):
        """
        Test neutralization when all sectors have same value.

        Setup:
            - All sectors: factor = 15.0

        Expected:
            - std = 0, cannot divide by zero
            - Should handle gracefully (return zeros or raise error)

        Assert:
            - Raises ValueError with helpful message
            - OR returns all zeros (valid z-score for zero variance)
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"],
            "date": [date(2023, 1, 1)] * 11,
            "factor": [15.0] * 11
        })

        neutralizer = CrossSectionalNeutralizer()

        # Should either raise error or return zeros
        try:
            result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])
            # If it doesn't raise error, should return all zeros
            z_scores = result_df["factor_neutral"].to_numpy()
            assert np.allclose(z_scores, 0.0)
        except ValueError as e:
            # Raising error is also acceptable
            assert "zero variance" in str(e).lower() or "constant" in str(e).lower()

    def test_single_outlier(self):
        """
        Test neutralization with one extreme outlier.

        Setup:
            - Values: [10, 11, 12, 11, 10, 11, 12, 11, 10, 11, 100]
            - Last value is extreme outlier

        Assert:
            - Outlier gets extreme z-score (>3)
            - Other values get reasonable z-scores (<2)
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"],
            "date": [date(2023, 1, 1)] * 11,
            "factor": [10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 100.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        z_scores = result_df["factor_neutral"].to_numpy()

        # Outlier should have extreme z-score
        outlier_z = z_scores[-1]
        assert abs(outlier_z) > 3.0

        # Other values should be reasonable
        other_z = z_scores[:-1]
        assert all(abs(z) < 2.0 for z in other_z)

    def test_two_sector_minimum(self):
        """
        Test neutralization requires at least 2 sectors.

        Setup:
            - Only 1 sector value

        Assert:
            - Raises error (can't compute std from n=1)
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLK"],
            "date": [date(2023, 1, 1)],
            "factor": [10.0]
        })

        neutralizer = CrossSectionalNeutralizer(min_sectors=2)

        try:
            neutralizer.neutralize(factor_df, factor_columns=["factor"])
            raise AssertionError("Expected error for single sector")
        except ValueError as e:
            assert "at least 2" in str(e).lower() or "insufficient" in str(e).lower()

    def test_missing_values_handled(self):
        """
        Test neutralization handles missing values (NaN).

        Setup:
            - Some sectors have NaN factor values

        Assert:
            - NaN values excluded from mean/std calculation
            - NaN values remain NaN in output
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"],
            "date": [date(2023, 1, 1)] * 11,
            "factor": [10.0, 12.0, None, 15.0, 9.0, 11.0, None, 7.0, 14.0, 10.0, 11.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        # NaN values should remain NaN
        neutral_values = result_df["factor_neutral"]
        assert neutral_values.null_count() == 2

        # Non-NaN values should be normalized
        valid_z = neutral_values.drop_nulls().to_numpy()
        assert abs(np.mean(valid_z)) < 1e-5
        assert abs(np.std(valid_z, ddof=1) - 1.0) < 1e-5


class TestNeutralizationOutput:
    """Test neutralization output format and naming."""

    def test_output_column_naming(self):
        """
        Test neutralized columns follow naming convention.

        Input: "momentum" → Output: "momentum_neutral"
        Input: "reversion" → Output: "reversion_neutral"
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLK", "XLE"],
            "date": [date(2023, 1, 1)] * 2,
            "momentum": [10.0, 12.0],
            "reversion": [-0.05, 0.02]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(
            factor_df,
            factor_columns=["momentum", "reversion"]
        )

        # Check neutralized column names
        assert "momentum_neutral" in result_df.columns
        assert "reversion_neutral" in result_df.columns

        # Original columns should still be present
        assert "momentum" in result_df.columns
        assert "reversion" in result_df.columns

    def test_output_preserves_metadata(self):
        """
        Test output preserves ticker and date columns.

        Assert:
            - ticker, date columns present in output
            - Values unchanged from input
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLK", "XLE", "XLF"],
            "date": [date(2023, 1, 1)] * 3,
            "factor": [10.0, 12.0, 8.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        # Check metadata preserved
        assert result_df["ticker"].to_list() == ["XLK", "XLE", "XLF"]
        assert result_df["date"].to_list() == [date(2023, 1, 1)] * 3

    def test_output_schema(self):
        """
        Test output schema has correct types.

        Expected:
            - ticker: Utf8
            - date: Date
            - factor_neutral: Float64
        """
        from Signals.SectorRotation.CrossSectionalNeutralizer import CrossSectionalNeutralizer

        factor_df = pl.DataFrame({
            "ticker": ["XLK", "XLE"],
            "date": [date(2023, 1, 1)] * 2,
            "factor": [10.0, 12.0]
        })

        neutralizer = CrossSectionalNeutralizer()
        result_df = neutralizer.neutralize(factor_df, factor_columns=["factor"])

        assert result_df["ticker"].dtype == pl.Utf8
        assert result_df["date"].dtype == pl.Date
        assert result_df["factor_neutral"].dtype == pl.Float64
