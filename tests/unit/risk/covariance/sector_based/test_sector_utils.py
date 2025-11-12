# ABOUTME: Tests for sector-based covariance utilities
# ABOUTME: Validates data conversion, sector extraction, and block-diagonal construction
"""
Tests for Sector-Based Covariance Utilities

Tests the common utility functions used by all sector-based covariance estimators.
"""

import pytest
import polars as pl
import numpy as np
from datetime import date

from Risk.Covariance.SectorBased.sector_utils import (
    validate_sector_data,
    long_to_wide,
    extract_sector_mapping,
    get_sectors_list,
    group_tickers_by_sector,
    create_block_diagonal_matrix,
)


class TestValidateSectorData:
    """Tests for validate_sector_data function."""

    def test_validates_correct_data(self):
        """Test that valid data passes validation."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT", "JPM"],
            "date": [date(2024, 1, 1)] * 3,
            "return": [0.01, 0.02, -0.01],
            "sector": ["Technology", "Technology", "Financials"],
        })

        # Should not raise
        validate_sector_data(df)

    def test_raises_on_missing_columns(self):
        """Test that missing columns raise ValueError."""
        df = pl.DataFrame({
            "ticker": ["AAPL"],
            "date": [date(2024, 1, 1)],
            "return": [0.01],
            # Missing 'sector' column
        })

        with pytest.raises(ValueError, match="Missing required columns"):
            validate_sector_data(df)

    def test_raises_on_null_sectors(self):
        """Test that null sectors raise ValueError."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2024, 1, 1)] * 2,
            "return": [0.01, 0.02],
            "sector": ["Technology", None],
        })

        with pytest.raises(ValueError, match="null sector"):
            validate_sector_data(df)

    def test_raises_on_null_returns(self):
        """Test that null returns raise ValueError."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "date": [date(2024, 1, 1)] * 2,
            "return": [0.01, None],
            "sector": ["Technology", "Technology"],
        })

        with pytest.raises(ValueError, match="null return"):
            validate_sector_data(df)


class TestLongToWide:
    """Tests for long_to_wide conversion."""

    def test_converts_long_to_wide_format(self):
        """Test conversion from long to wide format."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT", "AAPL", "MSFT"],
            "date": [date(2024, 1, 1), date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 2)],
            "return": [0.01, 0.02, -0.01, 0.03],
            "sector": ["Technology"] * 4,
        })

        wide_df, tickers = long_to_wide(df)

        assert wide_df.shape == (2, 2)  # 2 dates, 2 tickers
        assert set(tickers) == {"AAPL", "MSFT"}
        assert "date" not in wide_df.columns

    def test_preserves_ticker_order(self):
        """Test that ticker order is preserved."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT", "JPM"] * 2,
            "date": [date(2024, 1, 1)] * 3 + [date(2024, 1, 2)] * 3,
            "return": [0.01, 0.02, 0.03, -0.01, 0.02, -0.02],
            "sector": ["Technology", "Technology", "Financials"] * 2,
        })

        wide_df, tickers = long_to_wide(df)

        assert len(tickers) == 3
        # Tickers should be in some consistent order (polars sorts them)


class TestExtractSectorMapping:
    """Tests for extract_sector_mapping function."""

    def test_extracts_sector_mapping(self):
        """Test extraction of ticker → sector mapping."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT", "JPM", "BAC"] * 2,
            "date": [date(2024, 1, 1)] * 4 + [date(2024, 1, 2)] * 4,
            "return": [0.01] * 8,
            "sector": ["Technology", "Technology", "Financials", "Financials"] * 2,
        })

        sector_map = extract_sector_mapping(df)

        assert sector_map["AAPL"] == "Technology"
        assert sector_map["MSFT"] == "Technology"
        assert sector_map["JPM"] == "Financials"
        assert sector_map["BAC"] == "Financials"

    def test_handles_single_ticker(self):
        """Test with single ticker."""
        df = pl.DataFrame({
            "ticker": ["AAPL"] * 3,
            "date": [date(2024, 1, i) for i in range(1, 4)],
            "return": [0.01, 0.02, -0.01],
            "sector": ["Technology"] * 3,
        })

        sector_map = extract_sector_mapping(df)

        assert len(sector_map) == 1
        assert sector_map["AAPL"] == "Technology"


class TestGetSectorsList:
    """Tests for get_sectors_list function."""

    def test_gets_unique_sectors_sorted(self):
        """Test that unique sectors are returned sorted."""
        df = pl.DataFrame({
            "ticker": ["AAPL", "MSFT", "JPM", "XOM"],
            "date": [date(2024, 1, 1)] * 4,
            "return": [0.01] * 4,
            "sector": ["Technology", "Technology", "Financials", "Energy"],
        })

        sectors = get_sectors_list(df)

        assert len(sectors) == 3
        assert sectors == sorted(["Technology", "Financials", "Energy"])


class TestGroupTickersBySector:
    """Tests for group_tickers_by_sector function."""

    def test_groups_tickers_correctly(self):
        """Test grouping of tickers by sector."""
        ticker_sector_map = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "GOOGL": "Technology",
            "JPM": "Financials",
            "BAC": "Financials",
            "XOM": "Energy",
        }

        groups = group_tickers_by_sector(ticker_sector_map)

        assert len(groups) == 3
        assert set(groups["Technology"]) == {"AAPL", "MSFT", "GOOGL"}
        assert set(groups["Financials"]) == {"JPM", "BAC"}
        assert set(groups["Energy"]) == {"XOM"}


class TestCreateBlockDiagonalMatrix:
    """Tests for create_block_diagonal_matrix function."""

    def test_creates_block_diagonal_structure(self):
        """Test creation of block-diagonal matrix."""
        # Setup: 2 sectors with 2 tickers each
        ticker_order = ["AAPL", "MSFT", "JPM", "BAC"]
        ticker_sector_map = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "JPM": "Financials",
            "BAC": "Financials",
        }

        # Create 2x2 blocks
        blocks = {
            "Technology": np.array([[1.0, 0.5], [0.5, 1.0]]),
            "Financials": np.array([[2.0, 1.0], [1.0, 2.0]]),
        }

        cov_matrix = create_block_diagonal_matrix(blocks, ticker_order, ticker_sector_map)

        # Check shape
        assert cov_matrix.shape == (4, 4)

        # Check that off-block elements are zero
        assert cov_matrix[0, 2] == 0.0  # AAPL-JPM (cross-sector)
        assert cov_matrix[0, 3] == 0.0  # AAPL-BAC (cross-sector)
        assert cov_matrix[1, 2] == 0.0  # MSFT-JPM (cross-sector)
        assert cov_matrix[1, 3] == 0.0  # MSFT-BAC (cross-sector)

        # Check that within-block elements are correct
        assert cov_matrix[0, 0] == 1.0  # AAPL-AAPL
        assert cov_matrix[0, 1] == 0.5  # AAPL-MSFT
        assert cov_matrix[2, 2] == 2.0  # JPM-JPM
        assert cov_matrix[2, 3] == 1.0  # JPM-BAC

    def test_raises_on_missing_block(self):
        """Test that missing sector block raises error."""
        ticker_order = ["AAPL", "JPM"]
        ticker_sector_map = {
            "AAPL": "Technology",
            "JPM": "Financials",
        }

        blocks = {
            "Technology": np.array([[1.0]]),
            # Missing 'Financials' block
        }

        with pytest.raises(ValueError, match="Missing covariance block"):
            create_block_diagonal_matrix(blocks, ticker_order, ticker_sector_map)

    def test_handles_single_sector(self):
        """Test with single sector (degenerate case)."""
        ticker_order = ["AAPL", "MSFT"]
        ticker_sector_map = {
            "AAPL": "Technology",
            "MSFT": "Technology",
        }

        blocks = {
            "Technology": np.array([[1.0, 0.5], [0.5, 1.0]]),
        }

        cov_matrix = create_block_diagonal_matrix(blocks, ticker_order, ticker_sector_map)

        assert cov_matrix.shape == (2, 2)
        np.testing.assert_array_equal(cov_matrix, blocks["Technology"])
