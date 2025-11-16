"""
Test suite for FundamentalProcessor.

Tests the processor that validates and prepares fundamental data for neural network.
TDD approach: tests written BEFORE implementation.
"""

from datetime import date, timedelta
import polars as pl


class TestFundamentalProcessor:
    """Test FundamentalProcessor for fundamental data preparation."""

    def test_processor_initialization(self):
        """Test processor initializes with correct factor list."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Check 11 fundamental factors from paper
        expected_factors = [
            "pe_ratio",          # Price-to-Earnings
            "pb_ratio",          # Price-to-Book
            "ev_sales",          # EV / Sales
            "ev_ebit",           # EV / EBIT
            "ev_ebitda",         # EV / EBITDA
            "dividend_yield",    # Dividend Yield
            "gross_margin",      # Gross Margin
            "operating_margin",  # Operating Margin
            "profit_margin",     # Profit Margin
            "roa",               # Return on Assets
            "roe",               # Return on Equity
        ]

        assert processor.factor_columns == expected_factors
        assert len(processor.factor_columns) == 11

    def test_validate_schema_valid_data(self):
        """Test schema validation passes with correct columns."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Create valid fundamental data
        fundamental_df = pl.DataFrame({
            "ticker": ["XLK", "XLE", "XLF"],
            "date": [date(2023, 3, 31)] * 3,
            "pe_ratio": [25.0, 15.0, 12.0],
            "pb_ratio": [3.5, 1.2, 1.0],
            "ev_sales": [4.0, 2.0, 2.5],
            "ev_ebit": [18.0, 8.0, 10.0],
            "ev_ebitda": [15.0, 6.0, 8.0],
            "dividend_yield": [0.01, 0.04, 0.03],
            "gross_margin": [0.45, 0.20, 0.35],
            "operating_margin": [0.25, 0.10, 0.20],
            "profit_margin": [0.18, 0.08, 0.15],
            "roa": [0.12, 0.05, 0.08],
            "roe": [0.25, 0.10, 0.15],
        })

        # Should not raise
        processor.validate_schema(fundamental_df)

    def test_validate_schema_missing_columns(self):
        """Test schema validation fails with missing columns."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Missing 'roa' and 'roe' columns
        incomplete_df = pl.DataFrame({
            "ticker": ["XLK"],
            "date": [date(2023, 3, 31)],
            "pe_ratio": [25.0],
            "pb_ratio": [3.5],
            "ev_sales": [4.0],
            "ev_ebit": [18.0],
            "ev_ebitda": [15.0],
            "dividend_yield": [0.01],
            "gross_margin": [0.45],
            "operating_margin": [0.25],
            "profit_margin": [0.18],
        })

        try:
            processor.validate_schema(incomplete_df)
            raise AssertionError("Expected ValueError for missing columns")
        except ValueError as e:
            assert "missing required columns" in str(e).lower()
            assert "roa" in str(e) and "roe" in str(e)

    def test_handle_missing_values_forward_fill(self):
        """Test forward fill for quarterly fundamental data."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Create data with missing values (None)
        dates = [
            date(2023, 3, 31),  # Q1
            date(2023, 6, 30),  # Q2
            date(2023, 9, 30),  # Q3
        ]

        fundamental_df = pl.DataFrame({
            "ticker": ["XLK"] * 3 + ["XLE"] * 3,
            "date": dates * 2,
            "pe_ratio": [25.0, None, 27.0, 15.0, 16.0, None],
            "pb_ratio": [3.5, 3.6, None, 1.2, None, 1.3],
            "ev_sales": [4.0, None, None, 2.0, 2.1, 2.2],
            "ev_ebit": [18.0] * 3 + [8.0] * 3,
            "ev_ebitda": [15.0] * 3 + [6.0] * 3,
            "dividend_yield": [0.01] * 3 + [0.04] * 3,
            "gross_margin": [0.45] * 3 + [0.20] * 3,
            "operating_margin": [0.25] * 3 + [0.10] * 3,
            "profit_margin": [0.18] * 3 + [0.08] * 3,
            "roa": [0.12] * 3 + [0.05] * 3,
            "roe": [0.25] * 3 + [0.10] * 3,
        })

        filled_df = processor.handle_missing_values(fundamental_df)

        # Check XLK pe_ratio: Q2 should be forward-filled from Q1
        xlk_q2_pe = filled_df.filter(
            (pl.col("ticker") == "XLK") & (pl.col("date") == dates[1])
        )["pe_ratio"][0]
        assert xlk_q2_pe == 25.0  # Forward-filled from Q1

        # Check XLK pb_ratio: Q3 should be forward-filled from Q2
        xlk_q3_pb = filled_df.filter(
            (pl.col("ticker") == "XLK") & (pl.col("date") == dates[2])
        )["pb_ratio"][0]
        assert xlk_q3_pb == 3.6  # Forward-filled from Q2

    def test_get_factors_for_date(self):
        """Test extracting factors for specific date."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Create quarterly data
        dates = [
            date(2023, 3, 31),
            date(2023, 6, 30),
            date(2023, 9, 30),
        ]

        fundamental_df = pl.DataFrame({
            "ticker": ["XLK", "XLE"] * 3,
            "date": [dates[0]] * 2 + [dates[1]] * 2 + [dates[2]] * 2,
            "pe_ratio": [25.0, 15.0, 26.0, 16.0, 27.0, 17.0],
            "pb_ratio": [3.5, 1.2, 3.6, 1.3, 3.7, 1.4],
            "ev_sales": [4.0, 2.0] * 3,
            "ev_ebit": [18.0, 8.0] * 3,
            "ev_ebitda": [15.0, 6.0] * 3,
            "dividend_yield": [0.01, 0.04] * 3,
            "gross_margin": [0.45, 0.20] * 3,
            "operating_margin": [0.25, 0.10] * 3,
            "profit_margin": [0.18, 0.08] * 3,
            "roa": [0.12, 0.05] * 3,
            "roe": [0.25, 0.10] * 3,
        })

        # Get Q2 data
        q2_df = processor.get_factors_for_date(fundamental_df, dates[1])

        assert len(q2_df) == 2  # XLK and XLE
        xlk_pe = q2_df.filter(pl.col("ticker") == "XLK")["pe_ratio"][0]
        assert xlk_pe == 26.0  # Q2 value

    def test_factor_count_validation(self):
        """Test that exactly 11 factors are required."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Paper specifies 11 fundamental factors
        assert len(processor.factor_columns) == 11

    def test_quarterly_frequency_handling(self):
        """Test processor works with quarterly frequency data."""
        from Signals.SectorRotation.FundamentalProcessor import FundamentalProcessor

        processor = FundamentalProcessor()

        # Quarterly dates
        q_dates = [
            date(2022, 12, 31),  # Q4 2022
            date(2023, 3, 31),   # Q1 2023
            date(2023, 6, 30),   # Q2 2023
            date(2023, 9, 30),   # Q3 2023
        ]

        fundamental_df = pl.DataFrame({
            "ticker": ["XLK"] * 4,
            "date": q_dates,
            "pe_ratio": [24.0, 25.0, 26.0, 27.0],
            "pb_ratio": [3.4, 3.5, 3.6, 3.7],
            "ev_sales": [4.0] * 4,
            "ev_ebit": [18.0] * 4,
            "ev_ebitda": [15.0] * 4,
            "dividend_yield": [0.01] * 4,
            "gross_margin": [0.45] * 4,
            "operating_margin": [0.25] * 4,
            "profit_margin": [0.18] * 4,
            "roa": [0.12] * 4,
            "roe": [0.25] * 4,
        })

        processed_df = processor.process(fundamental_df)

        # Should preserve quarterly structure
        assert len(processed_df) == 4
        assert processed_df["date"].to_list() == q_dates


if __name__ == "__main__":
    # Run tests
    test = TestFundamentalProcessor()

    print("Running FundamentalProcessor tests...")

    test.test_processor_initialization()
    print("✓ test_processor_initialization")

    test.test_validate_schema_valid_data()
    print("✓ test_validate_schema_valid_data")

    test.test_validate_schema_missing_columns()
    print("✓ test_validate_schema_missing_columns")

    test.test_handle_missing_values_forward_fill()
    print("✓ test_handle_missing_values_forward_fill")

    test.test_get_factors_for_date()
    print("✓ test_get_factors_for_date")

    test.test_factor_count_validation()
    print("✓ test_factor_count_validation")

    test.test_quarterly_frequency_handling()
    print("✓ test_quarterly_frequency_handling")

    print("\n✅ All FundamentalProcessor tests passed!")
