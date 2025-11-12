"""
Test suite for SectorLongShortPortfolio.

Tests the long/short portfolio constructor for sector rotation.
TDD approach: tests written BEFORE implementation.
"""

import numpy as np
import polars as pl


class TestSectorLongShortPortfolio:
    """Test SectorLongShortPortfolio construction from signals."""

    def test_portfolio_initialization(self):
        """Test portfolio initializes with correct default parameters."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio()

        # Check default parameters from paper
        assert portfolio.n_long == 3  # Long top 3
        assert portfolio.n_short == 3  # Short bottom 3
        assert portfolio.leverage == 1.0  # 100% long, 100% short

    def test_portfolio_custom_parameters(self):
        """Test portfolio with custom long/short counts."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(
            n_long=2,
            n_short=2,
            leverage=0.5
        )

        assert portfolio.n_long == 2
        assert portfolio.n_short == 2
        assert portfolio.leverage == 0.5

    def test_construct_weights_basic(self):
        """Test basic weight construction from signals."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)

        # 11 sectors with different z-scores
        tickers = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"]
        z_scores = np.array([
            -1.5,  # XLE (worst)
            -1.0,  # XLB
            -0.5,  # XLI
            0.0,   # XLY
            0.2,   # XLP
            0.4,   # XLV
            0.6,   # XLF
            0.8,   # XLK
            1.0,   # XLC
            1.2,   # XLU
            1.5,   # XLRE (best)
        ])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Check weight dictionary keys
        assert set(weights.keys()) == set(tickers)

        # Check long positions (top 3: XLRE, XLU, XLC)
        assert weights["XLRE"] > 0  # Long
        assert weights["XLU"] > 0   # Long
        assert weights["XLC"] > 0   # Long

        # Check short positions (bottom 3: XLE, XLB, XLI)
        assert weights["XLE"] < 0  # Short
        assert weights["XLB"] < 0  # Short
        assert weights["XLI"] < 0  # Short

        # Check middle positions are zero
        for ticker in ["XLY", "XLP", "XLV", "XLF", "XLK"]:
            assert weights[ticker] == 0.0

    def test_equal_weighting_within_buckets(self):
        """Test that long and short positions are equal-weighted within buckets."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)

        tickers = ["A", "B", "C", "D", "E", "F"]
        z_scores = np.array([2.0, 1.0, 0.5, -0.5, -1.0, -2.0])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Top 3 (A, B, C) should be equal-weighted longs
        long_weights = [weights["A"], weights["B"], weights["C"]]
        assert all(w > 0 for w in long_weights)
        assert abs(long_weights[0] - long_weights[1]) < 1e-10
        assert abs(long_weights[1] - long_weights[2]) < 1e-10

        # Bottom 3 (D, E, F) should be equal-weighted shorts
        short_weights = [weights["D"], weights["E"], weights["F"]]
        assert all(w < 0 for w in short_weights)
        assert abs(short_weights[0] - short_weights[1]) < 1e-10
        assert abs(short_weights[1] - short_weights[2]) < 1e-10

    def test_dollar_neutral(self):
        """Test that portfolio is dollar-neutral (sum weights = 0)."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)

        tickers = ["A", "B", "C", "D", "E", "F", "G"]
        z_scores = np.array([2.0, 1.5, 1.0, 0.0, -1.0, -1.5, -2.0])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Sum of all weights should be zero (dollar-neutral)
        total_weight = sum(weights.values())
        assert abs(total_weight) < 1e-10

    def test_leverage_default_100_percent(self):
        """Test that default leverage is 100% long, 100% short."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3, leverage=1.0)

        tickers = ["A", "B", "C", "D", "E", "F"]
        z_scores = np.array([2.0, 1.0, 0.5, -0.5, -1.0, -2.0])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Long side should sum to 1.0 (100%)
        long_sum = sum(w for w in weights.values() if w > 0)
        assert abs(long_sum - 1.0) < 1e-10

        # Short side should sum to -1.0 (100%)
        short_sum = sum(w for w in weights.values() if w < 0)
        assert abs(short_sum - (-1.0)) < 1e-10

    def test_ranking_preserved(self):
        """Test that signal ranking determines long/short selection."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)

        tickers = ["Winner1", "Winner2", "Mid", "Loser1", "Loser2"]
        z_scores = np.array([1.5, 1.0, 0.0, -1.0, -1.5])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Top 2 should be long
        assert weights["Winner1"] > 0
        assert weights["Winner2"] > 0

        # Middle should be zero
        assert weights["Mid"] == 0.0

        # Bottom 2 should be short
        assert weights["Loser1"] < 0
        assert weights["Loser2"] < 0

    def test_handle_ties_in_signals(self):
        """Test portfolio handles tied signals gracefully."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)

        # Two sectors with identical z-scores
        tickers = ["A", "B", "C", "D"]
        z_scores = np.array([1.0, 1.0, -1.0, -1.0])

        weights = portfolio.construct_weights(tickers, z_scores)

        # Should still select exactly 2 long and 2 short
        long_count = sum(1 for w in weights.values() if w > 0)
        short_count = sum(1 for w in weights.values() if w < 0)

        assert long_count == 2
        assert short_count == 2

    def test_insufficient_sectors_error(self):
        """Test error when fewer sectors than required for long+short."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)

        # Only 4 sectors, but need at least 6 (3 long + 3 short)
        tickers = ["A", "B", "C", "D"]
        z_scores = np.array([1.0, 0.5, -0.5, -1.0])

        try:
            portfolio.construct_weights(tickers, z_scores)
            raise AssertionError("Expected ValueError for insufficient sectors")
        except ValueError as e:
            assert "insufficient sectors" in str(e).lower()

    def test_weights_to_dataframe(self):
        """Test conversion of weights dict to DataFrame."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        portfolio = SectorLongShortPortfolio(n_long=2, n_short=2)

        tickers = ["A", "B", "C", "D"]
        z_scores = np.array([1.5, 1.0, -1.0, -1.5])

        weights = portfolio.construct_weights(tickers, z_scores)
        weights_df = portfolio.weights_to_dataframe(weights)

        # Check DataFrame structure
        assert "ticker" in weights_df.columns
        assert "weight" in weights_df.columns
        assert len(weights_df) == 4

        # Check weights match
        for row in weights_df.iter_rows(named=True):
            assert weights[row["ticker"]] == row["weight"]

    def test_paper_configuration(self):
        """Test paper's exact configuration (long 3, short 3)."""
        from Signals.SectorRotation.SectorLongShortPortfolio import SectorLongShortPortfolio

        # Paper: Long top 3, short bottom 3
        portfolio = SectorLongShortPortfolio(n_long=3, n_short=3)

        # 11 GICS sectors
        tickers = ["XLE", "XLB", "XLI", "XLY", "XLP", "XLV", "XLF", "XLK", "XLC", "XLU", "XLRE"]
        # Arbitrary z-scores (would come from signals in practice)
        z_scores = np.linspace(-2, 2, 11)

        weights = portfolio.construct_weights(tickers, z_scores)

        # Check exactly 3 long, 3 short, 5 zero
        long_count = sum(1 for w in weights.values() if w > 0)
        short_count = sum(1 for w in weights.values() if w < 0)
        zero_count = sum(1 for w in weights.values() if w == 0)

        assert long_count == 3
        assert short_count == 3
        assert zero_count == 5


if __name__ == "__main__":
    # Run tests
    test = TestSectorLongShortPortfolio()

    print("Running SectorLongShortPortfolio tests...")

    test.test_portfolio_initialization()
    print("✓ test_portfolio_initialization")

    test.test_portfolio_custom_parameters()
    print("✓ test_portfolio_custom_parameters")

    test.test_construct_weights_basic()
    print("✓ test_construct_weights_basic")

    test.test_equal_weighting_within_buckets()
    print("✓ test_equal_weighting_within_buckets")

    test.test_dollar_neutral()
    print("✓ test_dollar_neutral")

    test.test_leverage_default_100_percent()
    print("✓ test_leverage_default_100_percent")

    test.test_ranking_preserved()
    print("✓ test_ranking_preserved")

    test.test_handle_ties_in_signals()
    print("✓ test_handle_ties_in_signals")

    test.test_insufficient_sectors_error()
    print("✓ test_insufficient_sectors_error")

    test.test_weights_to_dataframe()
    print("✓ test_weights_to_dataframe")

    test.test_paper_configuration()
    print("✓ test_paper_configuration")

    print("\n✅ All SectorLongShortPortfolio tests passed!")
