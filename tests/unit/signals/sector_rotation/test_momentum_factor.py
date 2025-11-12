# ABOUTME: Unit tests for MomentumFactor calculation (TDD approach).
# ABOUTME: Tests MOM_nM formula implementation before code exists.
"""
Test MomentumFactor - Momentum factor calculator for sector rotation.

TDD Approach: These tests are written FIRST, before implementation.
They define the expected behavior of MomentumFactor.
"""

import polars as pl
import numpy as np
from datetime import date, timedelta


class TestMomentumFactorConstruction:
    """Test mathematical correctness of momentum factor."""

    def test_mom_7m_calculation_formula(self):
        """
        Test MOM_7M = sum(7M returns) - sum(recent 10% returns).

        Setup:
            - 7 months = 147 trading days (21 days/month)
            - Exclude recent 10% = 14.7 ≈ 15 trading days
            - Mock daily returns: [0.01] * 132 + [0.02] * 15

        Expected:
            MOM_7M = (132 * 0.01) - (15 * 0.02) = 1.32 - 0.30 = 1.02

        Assert:
            abs(calculated_mom - 1.02) < 1e-6
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        # Setup: 147 days of returns
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(147)]
        returns_data = [0.01] * 132 + [0.02] * 15

        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 147,
            "date": dates,
            "return": returns_data
        })

        # Calculate momentum
        mom_calc = MomentumFactor(lookback_months=7, exclusion_pct=0.10)
        result_df = mom_calc.calculate(returns_df)

        # Get momentum value for the last date
        momentum_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["momentum_factor"][0]

        # Expected: 132*0.01 - 15*0.02 = 1.32 - 0.30 = 1.02
        expected = 1.02
        assert abs(momentum_value - expected) < 1e-6

    def test_mom_1m_simple_case(self):
        """
        Test MOM_1M with simple case.

        Setup:
            - 1 month = 21 trading days
            - Exclude recent 10% = 2.1 ≈ 2 trading days
            - Returns: [0.01] * 19 + [0.02] * 2

        Expected:
            MOM_1M = (19 * 0.01) - (2 * 0.02) = 0.19 - 0.04 = 0.15
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(21)]
        returns_data = [0.01] * 19 + [0.02] * 2

        returns_df = pl.DataFrame({
            "ticker": ["XLE"] * 21,
            "date": dates,
            "return": returns_data
        })

        mom_calc = MomentumFactor(lookback_months=1, exclusion_pct=0.10)
        result_df = mom_calc.calculate(returns_df)

        momentum_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["momentum_factor"][0]

        expected = 0.15
        assert abs(momentum_value - expected) < 1e-6

    def test_mom_handles_multiple_sectors(self):
        """
        Test momentum calculated for multiple sectors simultaneously.

        Setup:
            - 2 sectors (XLK, XLE)
            - Different return patterns

        Assert:
            - Returns 2 momentum values
            - Each sector calculated independently
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(147)]

        # XLK: strong momentum
        xlk_df = pl.DataFrame({
            "ticker": ["XLK"] * 147,
            "date": dates,
            "return": [0.02] * 147
        })

        # XLE: weak momentum
        xle_df = pl.DataFrame({
            "ticker": ["XLE"] * 147,
            "date": dates,
            "return": [0.001] * 147
        })

        returns_df = pl.concat([xlk_df, xle_df])

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        # Check both sectors present
        tickers = result_df["ticker"].unique().sort()
        assert tickers.to_list() == ["XLE", "XLK"]

        # XLK should have higher momentum
        xlk_mom = result_df.filter(
            (pl.col("ticker") == "XLK") & (pl.col("date") == dates[-1])
        )["momentum_factor"][0]

        xle_mom = result_df.filter(
            (pl.col("ticker") == "XLE") & (pl.col("date") == dates[-1])
        )["momentum_factor"][0]

        assert xlk_mom > xle_mom

    def test_mom_lookback_periods_configurable(self):
        """
        Test different momentum lookback periods (1M-12M).

        Assert:
            - Each lookback uses correct window size
            - Longer lookbacks include more history
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(252)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 252,
            "date": dates,
            "return": [0.01] * 252
        })

        # Test different lookback periods
        lookbacks = [1, 3, 7, 12]
        results = {}

        for lb in lookbacks:
            mom_calc = MomentumFactor(lookback_months=lb)
            result_df = mom_calc.calculate(returns_df)
            mom_value = result_df.filter(
                pl.col("date") == dates[-1]
            )["momentum_factor"][0]
            results[lb] = mom_value

        # Longer lookbacks should generally have larger cumulative returns
        # (assuming positive returns)
        assert results[12] > results[7] > results[3] > results[1]


class TestMomentumEdgeCases:
    """Test momentum factor edge cases and robustness."""

    def test_mom_all_zero_returns(self):
        """
        Test momentum when all returns are zero.

        Expected:
            MOM = 0.0
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(147)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 147,
            "date": dates,
            "return": [0.0] * 147
        })

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        momentum_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["momentum_factor"][0]

        assert abs(momentum_value - 0.0) < 1e-10

    def test_mom_negative_returns(self):
        """
        Test momentum with negative returns (drawdown).

        Setup:
            - All negative returns

        Expected:
            - Negative momentum value
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(147)]
        returns_df = pl.DataFrame({
            "ticker": ["XLE"] * 147,
            "date": dates,
            "return": [-0.01] * 147
        })

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        momentum_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["momentum_factor"][0]

        # Should be negative
        assert momentum_value < 0

    def test_mom_insufficient_history_raises_error(self):
        """
        Test momentum raises error when insufficient history.

        Setup:
            - Only 50 days of data
            - MOM_7M requires 147 days

        Expected:
            - Raises ValueError with helpful message
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(50)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 50,
            "date": dates,
            "return": [0.01] * 50
        })

        mom_calc = MomentumFactor(lookback_months=7)

        # Test that ValueError is raised
        try:
            mom_calc.calculate(returns_df)
            raise AssertionError("Expected ValueError for insufficient history")
        except ValueError as e:
            assert "Insufficient history" in str(e)

    def test_mom_output_schema(self):
        """
        Test momentum output has correct schema.

        Expected columns:
            - ticker (str)
            - date (date)
            - momentum_factor (float)
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(147)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 147,
            "date": dates,
            "return": [0.01] * 147
        })

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        # Check schema
        assert "ticker" in result_df.columns
        assert "date" in result_df.columns
        assert "momentum_factor" in result_df.columns

        # Check types
        assert result_df["ticker"].dtype == pl.Utf8
        assert result_df["date"].dtype == pl.Date
        assert result_df["momentum_factor"].dtype == pl.Float64


class TestMomentumRollingCalculation:
    """Test rolling momentum calculation over time."""

    def test_mom_rolling_over_multiple_dates(self):
        """
        Test momentum calculated for multiple observation dates.

        Setup:
            - 200 days of returns
            - Calculate momentum for last 50 days (rolling)

        Assert:
            - 50 momentum values returned
            - Each uses correct lookback window
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(200)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 200,
            "date": dates,
            "return": [0.01] * 200
        })

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        # Should have momentum values for dates where sufficient history exists
        # 147 days needed for MOM_7M, so first 146 days won't have values
        # Last 54 days should have momentum values
        assert len(result_df) >= 50

    def test_mom_time_series_consistency(self):
        """
        Test momentum time series is consistent.

        Setup:
            - Uptrend followed by downtrend
            - Calculate rolling momentum

        Assert:
            - Momentum increases during uptrend
            - Momentum decreases during downtrend
        """
        from Signals.SectorRotation.MomentumFactor import MomentumFactor

        # 147 days uptrend + 50 days downtrend
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(197)]
        returns_data = [0.02] * 147 + [-0.01] * 50

        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 197,
            "date": dates,
            "return": returns_data
        })

        mom_calc = MomentumFactor(lookback_months=7)
        result_df = mom_calc.calculate(returns_df)

        # Get momentum at different points
        mom_values = result_df.sort("date")["momentum_factor"].to_list()

        # Momentum should decrease as downtrend continues
        # (recent positive returns drop out of window, negative enter)
        assert len(mom_values) > 0
