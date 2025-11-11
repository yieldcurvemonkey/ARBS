# ABOUTME: Tests for ReturnsCalculator converting prices to returns
# ABOUTME: Validates percent returns, log returns, and edge cases
"""
Tests for ReturnsCalculator

Validates:
- Percent return calculation: (P_t - P_{t-1}) / P_{t-1}
- Log return calculation: log(P_t / P_{t-1})
- Edge cases: zero prices, missing prices, negative prices
- Multi-asset returns
"""

import pytest
import numpy as np
from typing import Dict

from Risk.Returns.ReturnsCalculator import ReturnsCalculator


class TestPercentReturns:
    """Test percent return calculation."""

    def test_can_import_returns_calculator(self):
        """Can import ReturnsCalculator."""
        assert ReturnsCalculator is not None

    def test_simple_percent_return(self):
        """Calculate simple percent return for single asset."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 105.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # (105 - 100) / 100 = 0.05 (5%)
        assert returns['SFRZ4'] == pytest.approx(0.05)

    def test_negative_return(self):
        """Negative return when price decreases."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 95.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # (95 - 100) / 100 = -0.05 (-5%)
        assert returns['SFRZ4'] == pytest.approx(-0.05)

    def test_zero_return_when_no_change(self):
        """Zero return when price unchanged."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 100.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns['SFRZ4'] == pytest.approx(0.0)

    def test_multiple_assets(self):
        """Calculate returns for multiple assets."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {
            'SFRZ4': 95.0,
            'SFRH5': 94.0,
            'SFRM5': 94.8
        }
        curr_prices = {
            'SFRZ4': 96.0,
            'SFRH5': 94.5,
            'SFRM5': 95.0
        }

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns['SFRZ4'] == pytest.approx((96.0 - 95.0) / 95.0)
        assert returns['SFRH5'] == pytest.approx((94.5 - 94.0) / 94.0)
        assert returns['SFRM5'] == pytest.approx((95.0 - 94.8) / 94.8)


class TestLogReturns:
    """Test log return calculation."""

    def test_simple_log_return(self):
        """Calculate log return for single asset."""
        calc = ReturnsCalculator(method="log")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 105.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # log(105 / 100) = log(1.05) ≈ 0.04879
        expected = np.log(105.0 / 100.0)
        assert returns['SFRZ4'] == pytest.approx(expected)

    def test_log_return_negative(self):
        """Log return when price decreases."""
        calc = ReturnsCalculator(method="log")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 95.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # log(95 / 100) = log(0.95) ≈ -0.05129
        expected = np.log(95.0 / 100.0)
        assert returns['SFRZ4'] == pytest.approx(expected)

    def test_log_return_zero_when_no_change(self):
        """Log return is zero when price unchanged."""
        calc = ReturnsCalculator(method="log")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 100.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # log(100 / 100) = log(1) = 0
        assert returns['SFRZ4'] == pytest.approx(0.0)

    def test_log_approximately_equals_percent_for_small_changes(self):
        """Log return ≈ percent return for small price changes."""
        calc_percent = ReturnsCalculator(method="percent")
        calc_log = ReturnsCalculator(method="log")

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 100.5}  # Small 0.5% change

        r_percent = calc_percent.calculate_returns(curr_prices, prev_prices)
        r_log = calc_log.calculate_returns(curr_prices, prev_prices)

        # For small changes, log(1+x) ≈ x
        # Difference should be < 0.0001 for 0.5% change
        assert abs(r_percent['SFRZ4'] - r_log['SFRZ4']) < 0.0001


class TestEdgeCases:
    """Edge cases: zero prices, missing assets, etc."""

    def test_zero_previous_price_returns_zero(self):
        """Zero previous price defaults to 0 return."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': 0.0}
        curr_prices = {'SFRZ4': 100.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # Undefined return → default to 0
        assert returns['SFRZ4'] == 0.0

    def test_negative_previous_price_returns_zero(self):
        """Negative previous price defaults to 0 return."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': -100.0}  # Invalid but handle gracefully
        curr_prices = {'SFRZ4': 100.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns['SFRZ4'] == 0.0

    def test_missing_previous_price_defaults_zero(self):
        """Missing previous price defaults to 0 return."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {}  # Missing SFRZ4
        curr_prices = {'SFRZ4': 100.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns['SFRZ4'] == 0.0

    def test_asset_only_in_current_prices(self):
        """New asset (not in previous prices) returns 0."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {'SFRZ4': 95.0}
        curr_prices = {'SFRZ4': 96.0, 'SFRH5': 94.0}  # SFRH5 is new

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns['SFRZ4'] == pytest.approx((96.0 - 95.0) / 95.0)
        assert returns['SFRH5'] == 0.0  # New asset

    def test_empty_prices_returns_empty(self):
        """Empty price dicts return empty returns."""
        calc = ReturnsCalculator(method="percent")

        prev_prices = {}
        curr_prices = {}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        assert returns == {}


class TestDefaultMethod:
    """Test default method selection."""

    def test_default_method_is_percent(self):
        """Default method is percent returns."""
        calc = ReturnsCalculator()  # No method specified

        prev_prices = {'SFRZ4': 100.0}
        curr_prices = {'SFRZ4': 105.0}

        returns = calc.calculate_returns(curr_prices, prev_prices)

        # Should be percent return by default
        assert returns['SFRZ4'] == pytest.approx(0.05)

    def test_invalid_method_raises_error(self):
        """Invalid method raises ValueError."""
        with pytest.raises(ValueError, match="method must be"):
            ReturnsCalculator(method="invalid")
