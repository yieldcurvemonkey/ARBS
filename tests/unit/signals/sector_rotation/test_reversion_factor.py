# ABOUTME: Unit tests for ReversionFactor calculation (TDD approach).
# ABOUTME: Tests REV_nD formula implementation before code exists.
"""
Test ReversionFactor - Short-term reversion factor calculator for sector rotation.

TDD Approach: These tests are written FIRST, before implementation.
They define the expected behavior of ReversionFactor.

Reversion Principle:
- Contrarian strategy: bet against recent trends
- Asset prices mean-revert in short term (1-2 months)
- REV_30D = -Σ(past 30 days returns)
- Recent winners become shorts, recent losers become longs
"""

import polars as pl
from datetime import date, timedelta


class TestReversionFactorConstruction:
    """Test mathematical correctness of reversion factor."""

    def test_rev_30d_calculation_formula(self):
        """
        Test REV_30D = -sum(past 30 days returns).

        Setup:
            - 30 days of returns: [0.01] * 15 + [-0.01] * 15
            - Sum = 15*0.01 + 15*(-0.01) = 0

        Expected:
            REV_30D = -0.0 = 0.0

        Assert:
            abs(calculated_rev - 0.0) < 1e-6
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_data = [0.01] * 15 + [-0.01] * 15

        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": returns_data
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        expected = 0.0
        assert abs(reversion_value - expected) < 1e-6

    def test_rev_negative_cumulative_return(self):
        """
        Test reversion factor negates cumulative return correctly.

        Setup:
            - Strong uptrend: [0.02] * 30
            - Cumulative = 0.60

        Expected:
            REV_30D = -0.60 (contrarian signal: bet against momentum)

        Assert:
            calculated_rev == -0.60
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.02] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        expected = -0.60
        assert abs(reversion_value - expected) < 1e-6

    def test_rev_positive_for_losers(self):
        """
        Test reversion gives positive signal for recent losers.

        Setup:
            - Downtrend: [-0.01] * 30
            - Cumulative = -0.30

        Expected:
            REV_30D = -(-0.30) = +0.30 (bullish contrarian signal)

        Logic:
            - Recent loser → positive reversion signal → bet on recovery
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        expected = 0.30
        assert abs(reversion_value - expected) < 1e-6
        assert reversion_value > 0  # Positive signal for loser

    def test_rev_lookback_periods_configurable(self):
        """
        Test different reversion lookback periods (5D-55D).

        Assert:
            - Each uses correct lookback window
            - No exclusion period (unlike momentum)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(60)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 60,
            "date": dates,
            "return": [0.01] * 60
        })

        # Test different lookback periods
        lookbacks = [5, 10, 20, 30, 50]
        results = {}

        for lb in lookbacks:
            rev_calc = ReversionFactor(lookback_days=lb)
            result_df = rev_calc.calculate(returns_df)
            rev_value = result_df.filter(
                pl.col("date") == dates[-1]
            )["reversion_factor"][0]
            results[lb] = rev_value

        # Longer lookbacks should have larger magnitude (more cumulative return)
        # All should be negative (positive returns → negative reversion)
        assert results[50] < results[30] < results[20] < results[10] < results[5]
        assert all(v < 0 for v in results.values())

    def test_rev_handles_multiple_sectors(self):
        """
        Test reversion calculated for multiple sectors simultaneously.

        Setup:
            - XLK: strong recent gains
            - XLE: strong recent losses

        Assert:
            - XLK gets negative reversion (bearish on winner)
            - XLE gets positive reversion (bullish on loser)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]

        # XLK: recent winner
        xlk_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.02] * 30  # +60% cumulative
        })

        # XLE: recent loser
        xle_df = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30  # -30% cumulative
        })

        returns_df = pl.concat([xlk_df, xle_df])

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        # Check both sectors present
        tickers = result_df["ticker"].unique().sort()
        assert tickers.to_list() == ["XLE", "XLK"]

        xlk_rev = result_df.filter(
            (pl.col("ticker") == "XLK") & (pl.col("date") == dates[-1])
        )["reversion_factor"][0]

        xle_rev = result_df.filter(
            (pl.col("ticker") == "XLE") & (pl.col("date") == dates[-1])
        )["reversion_factor"][0]

        # XLK (winner) should have negative reversion
        assert xlk_rev < 0

        # XLE (loser) should have positive reversion
        assert xle_rev > 0

        # XLE reversion should be MORE positive than XLK is negative
        assert xle_rev > abs(xlk_rev)


class TestReversionEdgeCases:
    """Test reversion factor edge cases."""

    def test_rev_all_zero_returns(self):
        """
        Test reversion when all returns are zero.

        Expected:
            REV = -0.0 = 0.0
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.0] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        assert abs(reversion_value - 0.0) < 1e-10

    def test_rev_extreme_drawdown(self):
        """
        Test reversion during extreme drawdown (>20% decline).

        Setup:
            - Daily -1% returns for 30 days
            - Cumulative ≈ -26%

        Expected:
            - Large positive reversion signal (bet on recovery)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLE"] * 30,
            "date": dates,
            "return": [-0.01] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        # Should be large positive value
        assert reversion_value > 0.25

    def test_rev_extreme_rally(self):
        """
        Test reversion during extreme rally (>20% gain).

        Setup:
            - Daily +1% returns for 30 days
            - Cumulative ≈ +35%

        Expected:
            - Large negative reversion signal (bet on pullback)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.01] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        reversion_value = result_df.filter(
            pl.col("date") == dates[-1]
        )["reversion_factor"][0]

        # Should be large negative value
        assert reversion_value < -0.25

    def test_rev_insufficient_history_raises_error(self):
        """
        Test reversion raises error when insufficient history.

        Setup:
            - Only 20 days of data
            - REV_30D requires 30 days

        Expected:
            - Raises ValueError with helpful message
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(20)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 20,
            "date": dates,
            "return": [0.01] * 20
        })

        rev_calc = ReversionFactor(lookback_days=30)

        # Test that ValueError is raised
        try:
            rev_calc.calculate(returns_df)
            raise AssertionError("Expected ValueError for insufficient history")
        except ValueError as e:
            assert "Insufficient history" in str(e)

    def test_rev_output_schema(self):
        """
        Test reversion output has correct schema.

        Expected columns:
            - ticker (str)
            - date (date)
            - reversion_factor (float)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(30)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 30,
            "date": dates,
            "return": [0.01] * 30
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        # Check schema
        assert "ticker" in result_df.columns
        assert "date" in result_df.columns
        assert "reversion_factor" in result_df.columns

        # Check types
        assert result_df["ticker"].dtype == pl.Utf8
        assert result_df["date"].dtype == pl.Date
        assert result_df["reversion_factor"].dtype == pl.Float64


class TestReversionRollingCalculation:
    """Test rolling reversion calculation over time."""

    def test_rev_rolling_over_multiple_dates(self):
        """
        Test reversion calculated for multiple observation dates.

        Setup:
            - 60 days of returns
            - Calculate reversion for last 30 days (rolling)

        Assert:
            - 30 reversion values returned
            - Each uses correct lookback window
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(60)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 60,
            "date": dates,
            "return": [0.01] * 60
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        # Should have reversion values for dates where sufficient history exists
        # 30 days needed, so last 31 days should have values
        assert len(result_df) >= 30

    def test_rev_contrarian_logic_over_time(self):
        """
        Test reversion exhibits contrarian behavior over time.

        Setup:
            - 30 days uptrend + 30 days downtrend
            - Calculate rolling REV_30D

        Assert:
            - Reversion negative during uptrend (bet against winners)
            - Reversion positive during downtrend (bet on recovery)
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        # 30 days uptrend + 30 days downtrend
        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(60)]
        returns_data = [0.02] * 30 + [-0.01] * 30

        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 60,
            "date": dates,
            "return": returns_data
        })

        rev_calc = ReversionFactor(lookback_days=30)
        result_df = rev_calc.calculate(returns_df)

        # Get first and last reversion values
        rev_values = result_df.sort("date")["reversion_factor"].to_list()

        # First value (during uptrend) should be negative
        assert rev_values[0] < 0

        # Last value (after downtrend) should be positive
        assert rev_values[-1] > 0

    def test_rev_paper_optimal_30d(self):
        """
        Test REV_30D is optimal lookback from paper.

        Paper Result:
            - REV_30D achieved Sharpe 0.87 (2002-2022)
            - Better than REV_25D (0.77) and REV_35D (0.13)

        This test just verifies 30D lookback is configurable correctly.
        """
        from Signals.SectorRotation.ReversionFactor import ReversionFactor

        dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(50)]
        returns_df = pl.DataFrame({
            "ticker": ["XLK"] * 50,
            "date": dates,
            "return": [0.01] * 50
        })

        # Paper's optimal lookback
        rev_calc = ReversionFactor(lookback_days=30)

        assert rev_calc.lookback_days == 30

        result_df = rev_calc.calculate(returns_df)

        # Should successfully calculate with 30-day lookback
        assert len(result_df) > 0
