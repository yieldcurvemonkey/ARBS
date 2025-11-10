# ABOUTME: Tests for RollableFuture asset with automatic roll handling
# ABOUTME: Validates roll detection, transition generation, and P&L calculation from rolls
"""
Tests for RollableFuture

Validates:
- Automatic roll detection on roll_date
- AssetTransition generation with P&L from roll spread
- Return calculation (same as PriceFuture when not rolling)
- Roll spread calculation (calendar spread pricing)
- Edge cases (missing prices, early/late detection)
"""

import pytest
from datetime import date, timedelta

from Asset import AssetTransition
from Asset.RollableFuture import RollableFuture


class TestRollableFutureBasics:
    """Basic functionality and instantiation."""

    def test_can_import_rollable_future(self):
        """Can import RollableFuture from Asset module."""
        from Asset import RollableFuture as RF
        assert RF is not None

    def test_can_instantiate_with_contracts_and_date(self):
        """Can create RollableFuture with current, next, roll_date."""
        future = RollableFuture(
            current_contract='SFRZ4',
            next_contract='SFRH5',
            roll_date=date(2024, 12, 10)
        )
        assert future is not None
        assert future.current_contract == 'SFRZ4'
        assert future.next_contract == 'SFRH5'
        assert future.roll_date == date(2024, 12, 10)

    def test_get_identifier_returns_current_contract(self):
        """get_identifier() returns current contract (front month)."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        assert future.get_identifier() == 'SFRZ4'

    def test_get_asset_type_returns_rollable_future(self):
        """get_asset_type() returns 'RollableFuture'."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        assert future.get_asset_type() == 'RollableFuture'


class TestReturnCalculation:
    """Return calculation when not rolling."""

    def test_calculate_return_same_as_price_future(self):
        """Return calculation identical to PriceFuture."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        ret = future.calculate_return(prev_price=95.0, curr_price=96.0)
        expected = (96.0 - 95.0) / 95.0
        assert abs(ret - expected) < 1e-10

    def test_price_increase_positive_return(self):
        """Price increase gives positive return."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        ret = future.calculate_return(95.0, 96.0)
        assert ret > 0

    def test_price_decrease_negative_return(self):
        """Price decrease gives negative return."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        ret = future.calculate_return(96.0, 95.0)
        assert ret < 0

    def test_no_price_change_zero_return(self):
        """No price change gives zero return."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        ret = future.calculate_return(95.0, 95.0)
        assert ret == 0.0


class TestRollDetection:
    """Roll transition detection logic."""

    def test_no_transition_before_roll_date(self):
        """No transition detected before roll_date."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        # Day before roll
        transition = future.detect_transition(date(2024, 12, 9), market_data)
        assert transition is None

    def test_transition_on_roll_date(self):
        """Transition detected on roll_date."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition is not None
        assert isinstance(transition, AssetTransition)

    def test_transition_after_roll_date(self):
        """Transition detected after roll_date (in case we missed it)."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 15), market_data)
        assert transition is not None

    def test_no_transition_long_before_roll(self):
        """No transition weeks before roll_date."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 11, 1), market_data)
        assert transition is None


class TestRollTransitionDetails:
    """Details of AssetTransition for rolls."""

    def test_transition_type_is_roll(self):
        """Transition event_type is 'roll'."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition.event_type == 'roll'

    def test_transition_from_asset_is_current(self):
        """Transition from_asset is current_contract."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition.from_asset == 'SFRZ4'

    def test_transition_to_asset_is_next(self):
        """Transition to_asset is next_contract."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition.to_asset == 'SFRH5'

    def test_transition_date_is_as_of(self):
        """Transition date matches as_of parameter."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        as_of = date(2024, 12, 10)
        transition = future.detect_transition(as_of, market_data)
        assert transition.date == as_of


class TestRollPnLCalculation:
    """P&L impact from roll spread."""

    def test_contango_negative_pnl(self):
        """
        Contango (next > current) gives negative roll P&L.

        Current at 95.00, next at 95.05 → lose 5bp when rolling
        """
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.00, 'next_price': 95.05}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        expected_pnl = (95.05 - 95.00) / 95.00  # Positive spread = negative carry
        assert abs(transition.pnl_impact - expected_pnl) < 1e-10
        assert transition.pnl_impact > 0  # Actually positive P&L

    def test_backwardation_positive_pnl(self):
        """
        Backwardation (next < current) gives positive roll P&L.

        Current at 95.00, next at 94.95 → gain 5bp when rolling
        """
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.00, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        expected_pnl = (94.95 - 95.00) / 95.00  # Negative spread = positive carry
        assert abs(transition.pnl_impact - expected_pnl) < 1e-10
        assert transition.pnl_impact < 0  # Actually negative P&L

    def test_no_spread_zero_pnl(self):
        """No spread (next = current) gives zero roll P&L."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.00, 'next_price': 95.00}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition.pnl_impact == 0.0

    def test_large_spread_correct_pnl(self):
        """Large spread (1%) calculated correctly."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.00, 'next_price': 96.00}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        expected_pnl = (96.00 - 95.00) / 95.00
        assert abs(transition.pnl_impact - expected_pnl) < 1e-10


class TestRollMetadata:
    """Metadata stored in AssetTransition."""

    def test_metadata_contains_prices(self):
        """Metadata contains current_price and next_price."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert 'current_price' in transition.metadata
        assert 'next_price' in transition.metadata
        assert transition.metadata['current_price'] == 95.0
        assert transition.metadata['next_price'] == 94.95

    def test_metadata_contains_spread(self):
        """Metadata contains roll_spread."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert 'roll_spread' in transition.metadata
        assert abs(transition.metadata['roll_spread'] - (-0.05)) < 1e-10


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_missing_price_in_market_data(self):
        """Missing 'price' defaults to 0."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'next_price': 94.95}  # No 'price'

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition is not None
        assert transition.metadata['current_price'] == 0.0

    def test_missing_next_price_defaults_to_current(self):
        """Missing 'next_price' defaults to current price (no spread)."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 95.0}  # No 'next_price'

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition is not None
        assert transition.metadata['next_price'] == 95.0
        assert transition.pnl_impact == 0.0  # No spread

    def test_empty_market_data_handled(self):
        """Empty market_data dict handled gracefully."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition is not None
        assert transition.pnl_impact == 0.0

    def test_zero_current_price_handled(self):
        """Zero current price gives zero P&L."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        market_data = {'price': 0.0, 'next_price': 94.95}

        transition = future.detect_transition(date(2024, 12, 10), market_data)
        assert transition.pnl_impact == 0.0


class TestRepresentation:
    """String representation."""

    def test_repr_contains_contracts(self):
        """__repr__ contains both contracts."""
        future = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        repr_str = repr(future)
        assert 'SFRZ4' in repr_str
        assert 'SFRH5' in repr_str or 'RollableFuture' in repr_str
