# ABOUTME: Tests for Portfolio class implementing Asset interface as composite
# ABOUTME: Validates portfolio composition, return calculation, and nested portfolios
"""
Tests for Portfolio

Validates:
- Portfolio as Asset (implements interface)
- Portfolio composition with multiple positions
- Weighted return calculation
- Transition detection from constituents
- Nested portfolios (portfolios of portfolios)
- Weight validation and rebalancing
"""

import pytest
from datetime import date
from typing import Dict

from Asset import PriceFuture, RollableFuture, Position, Asset
from Asset.Portfolio import Portfolio


class TestPortfolioBasics:
    """Basic functionality and Asset interface compliance."""

    def test_can_import_portfolio(self):
        """Can import Portfolio from Asset module."""
        assert Portfolio is not None

    def test_can_create_portfolio_with_positions(self):
        """Can create Portfolio with list of positions."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')

        positions = [
            Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.4, 94.9, date(2024, 11, 1))
        ]

        port = Portfolio(identifier='TEST_PORT', positions=positions)
        assert port is not None
        assert port.identifier == 'TEST_PORT'
        assert len(port.positions) == 2

    def test_portfolio_is_asset(self):
        """Portfolio implements Asset interface."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('TEST_PORT', positions)

        assert isinstance(port, Asset)

    def test_get_identifier_returns_portfolio_name(self):
        """get_identifier() returns portfolio identifier."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('MY_PORTFOLIO', positions)

        assert port.get_identifier() == 'MY_PORTFOLIO'

    def test_get_asset_type_returns_portfolio(self):
        """get_asset_type() returns 'Portfolio'."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('TEST_PORT', positions)

        assert port.get_asset_type() == 'Portfolio'

    def test_weights_must_sum_to_one(self):
        """Weights must sum to 1.0 (or very close)."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')

        # Weights sum to 1.5 - should raise error
        positions = [
            Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.9, 94.9, date(2024, 11, 1))  # 0.6 + 0.9 = 1.5
        ]

        with pytest.raises(ValueError, match="sum to"):
            Portfolio('TEST_PORT', positions)

    def test_weights_close_to_one_accepted(self):
        """Weights very close to 1.0 accepted (rounding tolerance)."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')

        # Weights sum to 0.9999999 (within tolerance)
        positions = [
            Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.3999999, 94.9, date(2024, 11, 1))
        ]

        port = Portfolio('TEST_PORT', positions)
        assert port is not None


class TestReturnCalculation:
    """Return calculation as weighted sum of constituent returns."""

    def test_single_asset_portfolio_return(self):
        """Portfolio with single asset returns that asset's return."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('SINGLE_ASSET', positions)

        # Portfolio now accepts returns dict (not price dicts)
        returns = {'SFRZ4': 0.010526}  # (96-95)/95

        port_return = port.calculate_return(returns)

        assert abs(port_return - 0.010526) < 1e-6

    def test_two_asset_weighted_return(self):
        """Portfolio return is weighted average of constituent returns."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')

        positions = [
            Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.4, 94.0, date(2024, 11, 1))
        ]

        port = Portfolio('TWO_ASSET', positions)

        # Portfolio accepts returns dict (not prices)
        # SFRZ4: (96 - 95) / 95 = 0.010526
        # SFRH5: (94.5 - 94) / 94 = 0.005319
        r1 = (96.0 - 95.0) / 95.0
        r2 = (94.5 - 94.0) / 94.0
        returns = {'SFRZ4': r1, 'SFRH5': r2}

        port_return = port.calculate_return(returns)

        # Portfolio: 0.6 × 0.010526 + 0.4 × 0.005319 = 0.008444
        expected = 0.6 * r1 + 0.4 * r2

        assert abs(port_return - expected) < 1e-6

    def test_equal_weight_portfolio(self):
        """Equal-weight portfolio with 3 assets."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')
        asset3 = PriceFuture('SFRM5')

        w = 1.0 / 3.0
        positions = [
            Position(asset1, w, 95.0, date(2024, 11, 1)),
            Position(asset2, w, 94.9, date(2024, 11, 1)),
            Position(asset3, w, 94.8, date(2024, 11, 1))
        ]

        port = Portfolio('EQUAL_WEIGHT', positions)

        # Calculate returns from prices
        r1 = (96.0 - 95.0) / 95.0
        r2 = (95.2 - 94.9) / 94.9
        r3 = (95.0 - 94.8) / 94.8
        returns = {'SFRZ4': r1, 'SFRH5': r2, 'SFRM5': r3}

        port_return = port.calculate_return(returns)

        expected = (r1 + r2 + r3) / 3.0

        assert abs(port_return - expected) < 1e-6

    def test_missing_return_defaults_to_zero(self):
        """Missing return in dict defaults to 0."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('TEST_PORT', positions)

        returns = {}  # Missing SFRZ4 return

        port_return = port.calculate_return(returns)
        # Missing return defaults to 0
        assert port_return == 0.0


class TestTransitionDetection:
    """Transition detection delegated to constituents."""

    def test_no_transitions_from_price_futures(self):
        """Portfolio of PriceFutures has no transitions."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')

        positions = [
            Position(asset1, 0.5, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.5, 94.9, date(2024, 11, 1))
        ]

        port = Portfolio('NO_TRANSITIONS', positions)

        transition = port.detect_transition(date(2024, 12, 1), {})
        assert transition is None

    def test_transition_from_rollable_future(self):
        """Portfolio detects transition from RollableFuture."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = RollableFuture('SFRH5', 'SFRM5', roll_date=date(2024, 12, 10))

        positions = [
            Position(asset1, 0.5, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.5, 94.9, date(2024, 11, 1))
        ]

        port = Portfolio('WITH_ROLL', positions)

        market_data = {'price': 94.9, 'next_price': 94.85}
        transition = port.detect_transition(date(2024, 12, 10), market_data)

        assert transition is not None
        assert transition.event_type == 'roll'
        assert transition.from_asset == 'SFRH5'

    def test_get_all_transitions_returns_multiple(self):
        """get_all_transitions() returns all transitions from all constituents."""
        asset1 = RollableFuture('SFRZ4', 'SFRH5', roll_date=date(2024, 12, 10))
        asset2 = RollableFuture('SFRM5', 'SFRU5', roll_date=date(2024, 12, 10))

        positions = [
            Position(asset1, 0.5, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.5, 94.8, date(2024, 11, 1))
        ]

        port = Portfolio('MULTI_ROLL', positions)

        market_data = {'price': 95.0, 'next_price': 94.95}
        transitions = port.get_all_transitions(date(2024, 12, 10), market_data)

        assert len(transitions) == 2
        assert all(t.event_type == 'roll' for t in transitions)


class TestNestedPortfolios:
    """Portfolio of portfolios (recursive composition)."""

    def test_portfolio_can_contain_portfolio(self):
        """Portfolio can contain another Portfolio as constituent."""
        # Level 1: Sub-portfolio
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')
        sub_port = Portfolio(
            'SUB_PORT',
            [
                Position(asset1, 0.5, 95.0, date(2024, 11, 1)),
                Position(asset2, 0.5, 94.9, date(2024, 11, 1))
            ]
        )

        # Level 2: Main portfolio contains sub-portfolio
        asset3 = PriceFuture('SFRM5')
        main_port = Portfolio(
            'MAIN_PORT',
            [
                Position(sub_port, 0.7, 100.0, date(2024, 11, 1)),  # Portfolio as Asset!
                Position(asset3, 0.3, 94.8, date(2024, 11, 1))
            ]
        )

        assert len(main_port.positions) == 2
        assert main_port.positions[0].asset == sub_port

    def test_nested_portfolio_return_calculation(self):
        """Nested portfolio correctly calculates weighted return."""
        # Sub-portfolio: 50/50 SFRZ4 and SFRH5
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')
        sub_port = Portfolio(
            'SUB_PORT',
            [
                Position(asset1, 0.5, 95.0, date(2024, 11, 1)),
                Position(asset2, 0.5, 94.0, date(2024, 11, 1))
            ]
        )

        # Main portfolio: 60% sub-portfolio, 40% SFRM5
        asset3 = PriceFuture('SFRM5')
        main_port = Portfolio(
            'MAIN_PORT',
            [
                Position(sub_port, 0.6, 100.0, date(2024, 11, 1)),
                Position(asset3, 0.4, 94.8, date(2024, 11, 1))
            ]
        )

        # Calculate returns from prices
        r1 = (96.0 - 95.0) / 95.0  # 0.010526
        r2 = (94.5 - 94.0) / 94.0  # 0.005319
        r3 = (95.0 - 94.8) / 94.8  # 0.002110

        # Returns dict contains all underlying assets (not portfolio "returns")
        returns = {
            'SFRZ4': r1,
            'SFRH5': r2,
            'SFRM5': r3
        }

        # Calculate manually:
        # Sub-portfolio return:
        sub_return = 0.5 * r1 + 0.5 * r2  # 0.007923

        # Main portfolio return:
        # Using sub-portfolio return directly:
        main_return_expected = 0.6 * sub_return + 0.4 * r3

        main_return = main_port.calculate_return(returns)

        assert abs(main_return - main_return_expected) < 1e-6


class TestEmptyAndEdgeCases:
    """Empty portfolios and edge cases."""

    def test_empty_portfolio_zero_return(self):
        """Empty portfolio (no positions) returns 0."""
        port = Portfolio('EMPTY', [])

        # Should not raise error, just return 0
        port_return = port.calculate_return({})
        assert port_return == 0.0

    def test_empty_portfolio_weights_dont_need_to_sum(self):
        """Empty portfolio doesn't validate weight sum."""
        port = Portfolio('EMPTY', [])
        assert len(port.positions) == 0


class TestRepresentation:
    """String representation."""

    def test_repr_contains_identifier(self):
        """__repr__ contains portfolio identifier."""
        asset = PriceFuture('SFRZ4')
        positions = [Position(asset, 1.0, 95.0, date(2024, 11, 1))]
        port = Portfolio('MY_PORT', positions)

        repr_str = repr(port)
        assert 'MY_PORT' in repr_str

    def test_repr_contains_num_positions(self):
        """__repr__ shows number of positions."""
        asset1 = PriceFuture('SFRZ4')
        asset2 = PriceFuture('SFRH5')
        positions = [
            Position(asset1, 0.6, 95.0, date(2024, 11, 1)),
            Position(asset2, 0.4, 94.9, date(2024, 11, 1))
        ]
        port = Portfolio('TWO_ASSET', positions)

        repr_str = repr(port)
        assert '2' in repr_str or 'positions' in repr_str.lower()
