# ABOUTME: Tests for BT/accounting.py conventions
# ABOUTME: Validates settlement, margin, and roll convention implementations
"""
Unit tests for generic accounting abstractions.

Tests cover:
- SettlementConvention (abstract and concrete implementations)
- MarginConvention (abstract and concrete implementations)
- RollConvention (abstract and concrete implementations)
- CashFlow dataclass

Following TDD: These tests are written BEFORE implementing the accounting module.
"""

import pytest
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import List


# =============================================================================
# Test CashFlow Dataclass
# =============================================================================

class TestCashFlow:
    """Test the CashFlow dataclass."""

    def test_cashflow_creation(self):
        """Test creating a basic cash flow."""
        from BT.accounting import CashFlow

        cf = CashFlow(
            date=date(2024, 1, 15),
            amount=1000.0,
            description="Test cash flow"
        )

        assert cf.date == date(2024, 1, 15)
        assert cf.amount == 1000.0
        assert cf.description == "Test cash flow"

    def test_cashflow_defaults(self):
        """Test cash flow with minimal arguments."""
        from BT.accounting import CashFlow

        cf = CashFlow(date=date(2024, 1, 15), amount=500.0)

        assert cf.date == date(2024, 1, 15)
        assert cf.amount == 500.0
        assert cf.description == ""  # Default empty string


# =============================================================================
# Test SettlementConvention Abstract Base Class
# =============================================================================

class TestSettlementConvention:
    """Test the SettlementConvention abstract base class."""

    def test_settlement_convention_is_abstract(self):
        """Test that SettlementConvention cannot be instantiated directly."""
        from BT.accounting import SettlementConvention

        with pytest.raises(TypeError):
            SettlementConvention()

    def test_standard_settlement_t_plus_2(self, mock_position_irs, mock_pricer):
        """Test standard T+2 settlement convention."""
        from BT.accounting import StandardSettlement

        settlement = StandardSettlement(days=2)

        t0 = date(2024, 1, 15)
        t1 = date(2024, 1, 16)

        cash_flows = settlement.calculate_cash_flows(
            position=mock_position_irs,
            pricer=mock_pricer,
            t0=t0,
            t1=t1
        )

        # Standard settlement has no cash flows between t0 and t1
        # (only at inception and maturity)
        assert isinstance(cash_flows, list)

    def test_daily_settlement(self, mock_position_irs, mock_pricer):
        """Test daily settlement convention (for futures)."""
        from BT.accounting import DailySettlement

        settlement = DailySettlement()

        t0 = date(2024, 1, 15)
        t1 = date(2024, 1, 16)

        # Mock position needs previous price
        mock_position_irs.prev_price = 100.0
        mock_position_irs.curr_price = 101.5

        cash_flows = settlement.calculate_cash_flows(
            position=mock_position_irs,
            pricer=mock_pricer,
            t0=t0,
            t1=t1
        )

        assert isinstance(cash_flows, list)
        if len(cash_flows) > 0:
            assert cash_flows[0].date == t1
            # Should have variation margin cash flow
            assert "variation" in cash_flows[0].description.lower() or "settlement" in cash_flows[0].description.lower()


# =============================================================================
# Test MarginConvention Abstract Base Class
# =============================================================================

class TestMarginConvention:
    """Test the MarginConvention abstract base class."""

    def test_margin_convention_is_abstract(self):
        """Test that MarginConvention cannot be instantiated directly."""
        from BT.accounting import MarginConvention

        with pytest.raises(TypeError):
            MarginConvention()

    def test_no_margin_convention(self, mock_position_irs, mock_pricer):
        """Test no margin convention (for swaps)."""
        from BT.accounting import NoMargin

        margin_conv = NoMargin()

        im = margin_conv.initial_margin(mock_position_irs, mock_pricer)
        assert im == 0.0

        vm = margin_conv.variation_margin(
            mock_position_irs,
            mock_pricer,
            prev_price=100.0
        )
        assert vm == 0.0

    def test_simple_margin_convention(self, mock_position_irs, mock_pricer):
        """Test simple percentage-of-notional margin."""
        from BT.accounting import SimpleMargin

        # 2% initial margin, 1% maintenance margin
        margin_conv = SimpleMargin(initial_rate=0.02, maintenance_rate=0.01)

        im = margin_conv.initial_margin(mock_position_irs, mock_pricer)
        assert im > 0.0
        # Should be roughly 2% of notional
        expected_im = abs(mock_position_irs.quantity) * 0.02
        assert abs(im - expected_im) < 1000  # Within $1000

    def test_futures_margin_convention(self, mock_position_irs, mock_pricer):
        """Test futures-style margin (initial + daily variation)."""
        from BT.accounting import FuturesMargin

        margin_conv = FuturesMargin(initial_rate=0.03)

        im = margin_conv.initial_margin(mock_position_irs, mock_pricer)
        assert im > 0.0

        # Variation margin based on price change
        prev_price = 95.0
        curr_price = 95.5  # 0.5 point gain

        mock_pricer.futures_price = lambda contract: curr_price

        vm = margin_conv.variation_margin(
            mock_position_irs,
            mock_pricer,
            prev_price=prev_price
        )

        # VM should reflect price change
        assert isinstance(vm, float)


# =============================================================================
# Test RollConvention Abstract Base Class
# =============================================================================

class TestRollConvention:
    """Test the RollConvention abstract base class."""

    def test_roll_convention_is_abstract(self):
        """Test that RollConvention cannot be instantiated directly."""
        from BT.accounting import RollConvention

        with pytest.raises(TypeError):
            RollConvention()

    def test_no_roll_convention(self, mock_position_irs):
        """Test no roll convention (hold to maturity)."""
        from BT.accounting import NoRoll

        roll_conv = NoRoll()

        should_roll = roll_conv.should_roll(
            mock_position_irs,
            current_date=date(2024, 12, 1)
        )

        assert should_roll is False

        # get_roll_target should return None
        target = roll_conv.get_roll_target(
            mock_position_irs,
            current_date=date(2024, 12, 1)
        )
        assert target is None

    def test_days_before_expiry_roll(self, mock_position_irs):
        """Test roll N days before expiry."""
        from BT.accounting import DaysBeforeExpiryRoll

        # Roll 5 days before expiry
        roll_conv = DaysBeforeExpiryRoll(days_before_expiry=5)

        # Add expiry to mock position
        mock_position_irs.expiry = date(2024, 3, 20)  # March 20, 2024

        # Test far from expiry - should not roll
        should_roll = roll_conv.should_roll(
            mock_position_irs,
            current_date=date(2024, 1, 15)
        )
        assert should_roll is False

        # Test exactly 5 days before expiry - should roll
        should_roll = roll_conv.should_roll(
            mock_position_irs,
            current_date=date(2024, 3, 15)
        )
        assert should_roll is True

        # Test 4 days before expiry - should roll
        should_roll = roll_conv.should_roll(
            mock_position_irs,
            current_date=date(2024, 3, 16)
        )
        assert should_roll is True

        # Test past expiry - should roll
        should_roll = roll_conv.should_roll(
            mock_position_irs,
            current_date=date(2024, 3, 21)
        )
        assert should_roll is True

    def test_quarterly_roll(self):
        """Test quarterly roll convention (for futures)."""
        from BT.accounting import QuarterlyRoll

        roll_conv = QuarterlyRoll(days_before_expiry=5)

        # Create mock futures position with March expiry
        @dataclass
        class MockFuturesPosition:
            contract: str = "EDH4"  # March 2024
            expiry: date = date(2024, 3, 20)

        position = MockFuturesPosition()

        # Should roll 5 days before March expiry
        should_roll = roll_conv.should_roll(position, date(2024, 3, 15))
        assert should_roll is True

        # Get roll target (should be June contract)
        target = roll_conv.get_roll_target(position, date(2024, 3, 15))

        # Target should be next quarterly contract
        assert target is not None
        # Could be a new query or contract spec


# =============================================================================
# Integration Tests for Conventions
# =============================================================================

@pytest.mark.integration
class TestConventionIntegration:
    """Integration tests for conventions working together."""

    def test_futures_position_with_all_conventions(self, mock_pricer):
        """Test a futures position with settlement, margin, and roll."""
        from BT.accounting import (
            DailySettlement,
            FuturesMargin,
            DaysBeforeExpiryRoll,
        )

        @dataclass
        class MockFuturesPosition:
            contract: str = "SFRZ4"
            quantity: float = 10.0
            multiplier: float = 2500.0
            expiry: date = date(2024, 12, 18)
            prev_price: float = 94.50
            curr_price: float = 94.75

        position = MockFuturesPosition()

        # Setup conventions
        settlement = DailySettlement()
        margin = FuturesMargin(initial_rate=0.03)
        roll = DaysBeforeExpiryRoll(days_before_expiry=5)

        # Test initial margin
        im = margin.initial_margin(position, mock_pricer)
        assert im > 0.0

        # Test settlement cash flows
        cash_flows = settlement.calculate_cash_flows(
            position, mock_pricer, date(2024, 1, 15), date(2024, 1, 16)
        )
        assert isinstance(cash_flows, list)

        # Test roll logic
        should_roll_early = roll.should_roll(position, date(2024, 11, 1))
        assert should_roll_early is False

        should_roll_near = roll.should_roll(position, date(2024, 12, 13))
        assert should_roll_near is True

    def test_swap_position_with_all_conventions(self, mock_position_irs, mock_pricer):
        """Test a swap position with appropriate conventions."""
        from BT.accounting import StandardSettlement, NoMargin, NoRoll

        # Swaps typically have standard settlement, no margin, no roll
        settlement = StandardSettlement(days=2)
        margin = NoMargin()
        roll = NoRoll()

        # Attach conventions to position
        mock_position_irs.settlement_convention = settlement
        mock_position_irs.margin_convention = margin
        mock_position_irs.roll_convention = roll

        # Test that conventions are accessible
        assert mock_position_irs.settlement_convention is not None
        assert mock_position_irs.margin_convention is not None
        assert mock_position_irs.roll_convention is not None

        # Test margin is zero
        im = mock_position_irs.margin_convention.initial_margin(
            mock_position_irs, mock_pricer
        )
        assert im == 0.0

        # Test no roll
        should_roll = mock_position_irs.roll_convention.should_roll(
            mock_position_irs, date(2024, 12, 1)
        )
        assert should_roll is False
