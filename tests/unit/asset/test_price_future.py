# ABOUTME: Tests for PriceFuture asset with simple price-based return calculation
# ABOUTME: Validates return calculation, edge cases, and interface compliance
"""
Tests for PriceFuture

Validates:
- Simple price return calculation
- Edge cases (zero price, negative price, total loss)
- Interface compliance (Asset abstract base class)
- No transitions (PriceFuture doesn't auto-roll)
"""

import pytest
from datetime import date

from Asset import PriceFuture, Asset


class TestPriceFutureBasics:
    """Basic functionality and interface compliance."""

    def test_can_import_price_future(self):
        """Can import PriceFuture from Asset module."""
        assert PriceFuture is not None

    def test_can_instantiate_with_contract(self):
        """Can create PriceFuture with contract identifier."""
        future = PriceFuture('SFRZ4')
        assert future is not None
        assert future.contract == 'SFRZ4'

    def test_empty_contract_raises_error(self):
        """Empty contract identifier raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            PriceFuture('')

    def test_is_subclass_of_asset(self):
        """PriceFuture is subclass of Asset."""
        future = PriceFuture('SFRZ4')
        assert isinstance(future, Asset)

    def test_get_identifier_returns_contract(self):
        """get_identifier() returns contract string."""
        future = PriceFuture('SFRZ4')
        assert future.get_identifier() == 'SFRZ4'

    def test_get_asset_type_returns_class_name(self):
        """get_asset_type() returns 'PriceFuture'."""
        future = PriceFuture('SFRZ4')
        assert future.get_asset_type() == 'PriceFuture'

    def test_has_calculate_return_method(self):
        """Has calculate_return method."""
        future = PriceFuture('SFRZ4')
        assert hasattr(future, 'calculate_return')
        assert callable(future.calculate_return)

    def test_has_detect_transition_method(self):
        """Has detect_transition method."""
        future = PriceFuture('SFRZ4')
        assert hasattr(future, 'detect_transition')
        assert callable(future.detect_transition)


class TestReturnCalculation:
    """Return calculation logic and correctness."""

    def test_price_increase_positive_return(self):
        """Price increase from 95 to 96 gives positive return."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=95.0, curr_price=96.0)
        expected = (96.0 - 95.0) / 95.0
        assert abs(ret - expected) < 1e-10
        assert ret > 0

    def test_price_decrease_negative_return(self):
        """Price decrease from 96 to 95 gives negative return."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=96.0, curr_price=95.0)
        expected = (95.0 - 96.0) / 96.0
        assert abs(ret - expected) < 1e-10
        assert ret < 0

    def test_no_price_change_zero_return(self):
        """No price change gives zero return."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=95.0, curr_price=95.0)
        assert ret == 0.0

    def test_small_price_change_correct(self):
        """Small price change (1 bp) calculated correctly."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=95.00, curr_price=95.01)
        expected = 0.01 / 95.00
        assert abs(ret - expected) < 1e-10

    def test_large_price_change_correct(self):
        """Large price change (10%) calculated correctly."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=100.0, curr_price=110.0)
        expected = 0.10
        assert abs(ret - expected) < 1e-10

    def test_return_formula_matches_percentage_change(self):
        """Return matches (new - old) / old formula."""
        future = PriceFuture('SFRZ4')
        prev, curr = 95.50, 96.25
        ret = future.calculate_return(prev_price=prev, curr_price=curr)
        expected = (curr - prev) / prev
        assert abs(ret - expected) < 1e-10


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_zero_previous_price_returns_zero(self):
        """Previous price = 0 returns 0 (undefined return)."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=0.0, curr_price=95.0)
        assert ret == 0.0

    def test_negative_previous_price_returns_zero(self):
        """Negative previous price returns 0 (invalid)."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=-10.0, curr_price=95.0)
        assert ret == 0.0

    def test_zero_current_price_total_loss(self):
        """Current price = 0 gives -100% return (total loss)."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=95.0, curr_price=0.0)
        assert abs(ret - (-1.0)) < 1e-10

    def test_very_small_prev_price_stable(self):
        """Very small previous price doesn't cause overflow."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(prev_price=0.001, curr_price=0.002)
        expected = (0.002 - 0.001) / 0.001
        assert abs(ret - expected) < 1e-10

    def test_kwargs_ignored(self):
        """Extra kwargs are ignored (interface compatibility)."""
        future = PriceFuture('SFRZ4')
        ret = future.calculate_return(
            prev_price=95.0,
            curr_price=96.0,
            dv01=8.5,  # Ignored
            notional=100  # Ignored
        )
        expected = (96.0 - 95.0) / 95.0
        assert abs(ret - expected) < 1e-10


class TestTransitions:
    """Corporate action detection."""

    def test_no_transitions_detected(self):
        """PriceFuture never detects transitions."""
        future = PriceFuture('SFRZ4')
        transition = future.detect_transition(
            as_of=date(2024, 12, 1),
            market_data={}
        )
        assert transition is None

    def test_transitions_none_with_roll_data(self):
        """Even with roll data in market_data, no transition."""
        future = PriceFuture('SFRZ4')
        market_data = {
            'price': 95.0,
            'next_price': 94.95,
            'roll_date': date(2024, 12, 10)
        }
        transition = future.detect_transition(
            as_of=date(2024, 12, 10),
            market_data=market_data
        )
        assert transition is None

    def test_transitions_none_on_any_date(self):
        """No transitions regardless of date."""
        future = PriceFuture('SFRZ4')
        dates = [date(2024, 1, 1), date(2024, 12, 31), date(2025, 3, 15)]
        for d in dates:
            assert future.detect_transition(d, {}) is None


class TestRepresentation:
    """String representation and debugging."""

    def test_repr_contains_contract(self):
        """__repr__ contains contract identifier."""
        future = PriceFuture('SFRZ4')
        repr_str = repr(future)
        assert 'SFRZ4' in repr_str

    def test_repr_contains_type(self):
        """__repr__ contains type name."""
        future = PriceFuture('SFRZ4')
        repr_str = repr(future)
        assert 'PriceFuture' in repr_str


class TestMultipleContracts:
    """Using multiple PriceFuture instances."""

    def test_different_contracts_independent(self):
        """Different contracts have independent returns."""
        future1 = PriceFuture('SFRZ4')
        future2 = PriceFuture('SFRH5')

        ret1 = future1.calculate_return(95.0, 96.0)
        ret2 = future2.calculate_return(94.0, 95.0)

        # Different price levels give different returns
        assert abs(ret1 - (96.0 - 95.0) / 95.0) < 1e-10
        assert abs(ret2 - (95.0 - 94.0) / 94.0) < 1e-10
        assert ret1 != ret2

    def test_identical_prices_same_return(self):
        """Same price changes give same return regardless of contract."""
        future1 = PriceFuture('SFRZ4')
        future2 = PriceFuture('SFRH5')

        ret1 = future1.calculate_return(95.0, 96.0)
        ret2 = future2.calculate_return(95.0, 96.0)

        assert abs(ret1 - ret2) < 1e-10
