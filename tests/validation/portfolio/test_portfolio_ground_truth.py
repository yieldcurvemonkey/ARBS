# ABOUTME: Validation tests for Portfolio return calculations using ground truth
# ABOUTME: Hand-calculated examples prove Portfolio correctly computes weighted returns
"""
Validation Test: Portfolio - Ground Truth

Component: Portfolio
Method: Hand-calculated returns
Created: 2025-11-16

Validates that Portfolio correctly calculates returns using hand-calculated
ground truth examples. Each test includes explicit arithmetic showing the
expected result.
"""

from datetime import date

from Asset import Position, PriceFuture
from Asset.Portfolio import Portfolio


class TestPortfolioGroundTruth:
    """Ground truth validation for portfolio return calculations."""

    def test_simple_return_calculation(self):
        """
        Test portfolio returns with hand-calculated example.

        Simple case:
        - 2 assets with equal weights (50% each)
        - Asset A: 10% return
        - Asset B: 5% return
        - Portfolio return should be: 0.5×0.10 + 0.5×0.05 = 7.5%
        """
        # Create portfolio with equal weights
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.5, 100.0, date(2024, 1, 1)), Position(asset_b, 0.5, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="TEST", positions=positions)

        # Asset returns
        returns = {"A": 0.10, "B": 0.05}  # 10% return  # 5% return

        # Calculate portfolio return
        portfolio_return = portfolio.calculate_return(returns)

        # Expected: 0.5 × 0.10 + 0.5 × 0.05 = 0.075
        expected = 0.075

        assert abs(portfolio_return - expected) < 1e-10, f"Expected {expected}, got {portfolio_return}"

    def test_single_asset_portfolio(self):
        """Portfolio with single asset should match asset return exactly."""
        asset_a = PriceFuture("A")

        positions = [Position(asset_a, 1.0, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="SINGLE", positions=positions)

        # Test with positive return
        returns_pos = {"A": 0.05}
        port_return_pos = portfolio.calculate_return(returns_pos)
        assert abs(port_return_pos - 0.05) < 1e-10

        # Test with negative return
        returns_neg = {"A": -0.02}
        port_return_neg = portfolio.calculate_return(returns_neg)
        assert abs(port_return_neg - (-0.02)) < 1e-10

    def test_three_asset_equal_weight(self):
        """
        Three assets with equal weights (33.33% each).

        Calculation:
        - Asset A: 6% return
        - Asset B: 9% return
        - Asset C: 3% return
        - Weights: 1/3 each
        - Portfolio return = (1/3)×0.06 + (1/3)×0.09 + (1/3)×0.03
        -                   = (0.06 + 0.09 + 0.03) / 3
        -                   = 0.18 / 3 = 0.06 = 6%
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")
        asset_c = PriceFuture("C")

        w = 1.0 / 3.0
        positions = [
            Position(asset_a, w, 100.0, date(2024, 1, 1)),
            Position(asset_b, w, 100.0, date(2024, 1, 1)),
            Position(asset_c, w, 100.0, date(2024, 1, 1)),
        ]

        portfolio = Portfolio(identifier="EQUAL_WEIGHT", positions=positions)

        returns = {"A": 0.06, "B": 0.09, "C": 0.03}

        portfolio_return = portfolio.calculate_return(returns)

        # Expected: (0.06 + 0.09 + 0.03) / 3 = 0.06
        expected = 0.06

        assert abs(portfolio_return - expected) < 1e-10

    def test_unequal_weights(self):
        """
        Test with unequal weights that sum to 1.0.

        Portfolio:
        - Asset A: weight=0.6, return=10%
        - Asset B: weight=0.3, return=5%
        - Asset C: weight=0.1, return=15%

        Expected return:
        = 0.6 × 0.10 + 0.3 × 0.05 + 0.1 × 0.15
        = 0.06 + 0.015 + 0.015
        = 0.09 = 9%
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")
        asset_c = PriceFuture("C")

        positions = [
            Position(asset_a, 0.6, 100.0, date(2024, 1, 1)),
            Position(asset_b, 0.3, 100.0, date(2024, 1, 1)),
            Position(asset_c, 0.1, 100.0, date(2024, 1, 1)),
        ]

        portfolio = Portfolio(identifier="UNEQUAL", positions=positions)

        returns = {"A": 0.10, "B": 0.05, "C": 0.15}

        portfolio_return = portfolio.calculate_return(returns)

        # Expected: 0.06 + 0.015 + 0.015 = 0.09
        expected = 0.09

        assert abs(portfolio_return - expected) < 1e-10

    def test_negative_returns(self):
        """
        Portfolio should handle negative returns correctly.

        Portfolio:
        - Asset A: weight=0.6, return=-10%
        - Asset B: weight=0.4, return=-5%

        Expected:
        = 0.6 × (-0.10) + 0.4 × (-0.05)
        = -0.06 + (-0.02)
        = -0.08 = -8%
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.6, 100.0, date(2024, 1, 1)), Position(asset_b, 0.4, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="NEGATIVE", positions=positions)

        returns = {"A": -0.10, "B": -0.05}

        portfolio_return = portfolio.calculate_return(returns)
        expected = -0.08

        assert abs(portfolio_return - expected) < 1e-10

    def test_mixed_positive_negative_returns(self):
        """
        Portfolio with mix of positive and negative returns.

        Portfolio:
        - Asset A: weight=0.5, return=+8%
        - Asset B: weight=0.5, return=-4%

        Expected:
        = 0.5 × 0.08 + 0.5 × (-0.04)
        = 0.04 + (-0.02)
        = 0.02 = 2%
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.5, 100.0, date(2024, 1, 1)), Position(asset_b, 0.5, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="MIXED", positions=positions)

        returns = {"A": 0.08, "B": -0.04}

        portfolio_return = portfolio.calculate_return(returns)
        expected = 0.02

        assert abs(portfolio_return - expected) < 1e-10

    def test_zero_weight_asset(self):
        """
        Zero weight assets should not affect portfolio return.

        Portfolio:
        - Asset A: weight=0.7, return=10%
        - Asset B: weight=0.0, return=50% (high return but zero weight)
        - Asset C: weight=0.3, return=5%

        Expected:
        = 0.7 × 0.10 + 0.0 × 0.50 + 0.3 × 0.05
        = 0.07 + 0.0 + 0.015
        = 0.085 = 8.5%
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")
        asset_c = PriceFuture("C")

        positions = [
            Position(asset_a, 0.7, 100.0, date(2024, 1, 1)),
            Position(asset_b, 0.0, 100.0, date(2024, 1, 1)),
            Position(asset_c, 0.3, 100.0, date(2024, 1, 1)),
        ]

        portfolio = Portfolio(identifier="ZERO_WEIGHT", positions=positions)

        returns = {"A": 0.10, "B": 0.50, "C": 0.05}  # High return but zero weight

        portfolio_return = portfolio.calculate_return(returns)
        expected = 0.085

        assert abs(portfolio_return - expected) < 1e-10

    def test_realistic_futures_example(self):
        """
        Realistic futures carry portfolio example.

        3-month Eurodollar futures carry trade:
        - Long front contract (SFRZ4): weight=0.6, return=+0.53%
        - Short back contract (SFRH5): weight=0.4, return=-0.31%

        Expected:
        = 0.6 × 0.0053 + 0.4 × (-0.0031)
        = 0.00318 + (-0.00124)
        = 0.00194 = 0.194%

        Note: This mimics a real carry trade where you go long
        the cheaper contract and short the expensive one.
        """
        front_contract = PriceFuture("SFRZ4")
        back_contract = PriceFuture("SFRH5")

        positions = [
            Position(front_contract, 0.6, 95.0, date(2024, 11, 1)),
            Position(back_contract, 0.4, 94.9, date(2024, 11, 1)),
        ]

        portfolio = Portfolio(identifier="CARRY_TRADE", positions=positions)

        # Realistic single-day returns for Eurodollar futures
        returns = {"SFRZ4": 0.0053, "SFRH5": -0.0031}  # +0.53% on long position  # -0.31% on short position

        portfolio_return = portfolio.calculate_return(returns)

        # Expected: 0.6 × 0.0053 + 0.4 × (-0.0031) = 0.00194
        expected = 0.6 * 0.0053 + 0.4 * (-0.0031)

        assert abs(portfolio_return - expected) < 1e-10


class TestPortfolioEdgeCases:
    """Edge cases and boundary conditions."""

    def test_missing_return_defaults_to_zero(self):
        """
        Missing return in dict should default to 0.

        If a constituent's return is not in the returns dict,
        Portfolio should treat it as 0% return.
        """
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.5, 100.0, date(2024, 1, 1)), Position(asset_b, 0.5, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="MISSING", positions=positions)

        # Only provide return for asset A
        returns = {"A": 0.10}  # B is missing

        portfolio_return = portfolio.calculate_return(returns)

        # Expected: 0.5 × 0.10 + 0.5 × 0.0 = 0.05
        expected = 0.05

        assert abs(portfolio_return - expected) < 1e-10

    def test_empty_returns_dict(self):
        """All missing returns should result in 0% portfolio return."""
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.5, 100.0, date(2024, 1, 1)), Position(asset_b, 0.5, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="EMPTY", positions=positions)

        # Empty returns dict
        returns = {}

        portfolio_return = portfolio.calculate_return(returns)

        # Expected: all zeros
        assert portfolio_return == 0.0

    def test_all_zero_returns(self):
        """Portfolio with all zero returns should return 0."""
        asset_a = PriceFuture("A")
        asset_b = PriceFuture("B")

        positions = [Position(asset_a, 0.6, 100.0, date(2024, 1, 1)), Position(asset_b, 0.4, 100.0, date(2024, 1, 1))]

        portfolio = Portfolio(identifier="ZEROS", positions=positions)

        returns = {"A": 0.0, "B": 0.0}

        portfolio_return = portfolio.calculate_return(returns)

        assert portfolio_return == 0.0


"""
VALIDATION REPORT
=================
Component: Portfolio (Asset/Portfolio.py)
Method: Ground Truth (Hand-calculated returns)
Date: 2025-11-16

Tests: 11 total
  Core Return Calculation (8 tests):
  - test_simple_return_calculation: Basic 50/50 weighted average
  - test_single_asset_portfolio: Single asset edge case (100% weight)
  - test_three_asset_equal_weight: Equal weight with 3 assets
  - test_unequal_weights: Asymmetric weights (60/30/10)
  - test_negative_returns: Portfolio with losses
  - test_mixed_positive_negative_returns: Mix of gains and losses
  - test_zero_weight_asset: Zero weight should contribute zero
  - test_realistic_futures_example: Real carry trade scenario

  Edge Cases (3 tests):
  - test_missing_return_defaults_to_zero: Missing asset returns
  - test_empty_returns_dict: All returns missing
  - test_all_zero_returns: All returns are zero

Formula Validated:
  r_portfolio = Σ(w_i × r_i)
  where:
    w_i = weight of asset i (position.quantity)
    r_i = return of asset i
    Σw_i = 1.0 (budget constraint)

Expected: All tests passing
Confidence: 95% (return calculations are straightforward arithmetic)

Key Validations:
1. Weighted sum calculation is correct
2. Single asset edge case works (no averaging error)
3. Negative returns handled correctly
4. Zero weights contribute zero (not NaN or error)
5. Missing returns default to zero (graceful degradation)
6. Realistic futures scenario matches hand calculation
"""
