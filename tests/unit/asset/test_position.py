# ABOUTME: Tests for Position class representing holdings in an asset
# ABOUTME: Validates market value, P&L calculation, and position tracking
"""
Tests for Position

Validates:
- Position creation with asset, quantity, entry details
- Market value calculation
- P&L calculation (absolute and percentage)
- Edge cases (zero quantity, negative prices, etc.)
- Integration with different asset types
"""

import pytest
from datetime import date

from Asset import PriceFuture, RollableFuture
from Asset.Position import Position


class TestPositionBasics:
    """Basic functionality and instantiation."""

    def test_can_import_position(self):
        """Can import Position from Asset module."""
        assert Position is not None

    def test_can_create_position_with_asset(self):
        """Can create Position with asset, quantity, entry price, date."""
        asset = PriceFuture('SFRZ4')
        pos = Position(
            asset=asset,
            quantity=100.0,
            entry_price=95.0,
            entry_date=date(2024, 11, 1)
        )
        assert pos is not None
        assert pos.asset == asset
        assert pos.quantity == 100.0
        assert pos.entry_price == 95.0
        assert pos.entry_date == date(2024, 11, 1)

    def test_position_with_fractional_quantity(self):
        """Can create position with fractional quantity."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=2.5, entry_price=95.0, entry_date=date(2024, 11, 1))
        assert pos.quantity == 2.5

    def test_position_with_zero_quantity(self):
        """Can create position with zero quantity (closed position)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=0.0, entry_price=95.0, entry_date=date(2024, 11, 1))
        assert pos.quantity == 0.0

    def test_position_with_negative_quantity(self):
        """Can create position with negative quantity (short position)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=-50.0, entry_price=95.0, entry_date=date(2024, 11, 1))
        assert pos.quantity == -50.0


class TestMarketValue:
    """Market value calculation."""

    def test_market_value_basic(self):
        """Market value = quantity × current_price."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        mv = pos.market_value(current_price=96.0)
        assert mv == 100.0 * 96.0
        assert mv == 9600.0

    def test_market_value_fractional_quantity(self):
        """Market value with fractional quantity."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=2.5, entry_price=95.0, entry_date=date(2024, 11, 1))

        mv = pos.market_value(current_price=100.0)
        assert mv == 2.5 * 100.0
        assert mv == 250.0

    def test_market_value_zero_quantity(self):
        """Market value is zero for zero quantity."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=0.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        mv = pos.market_value(current_price=100.0)
        assert mv == 0.0

    def test_market_value_negative_quantity(self):
        """Market value for short position (negative quantity)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=-50.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        mv = pos.market_value(current_price=100.0)
        assert mv == -50.0 * 100.0
        assert mv == -5000.0

    def test_market_value_zero_price(self):
        """Market value is zero when price is zero (expired worthless)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        mv = pos.market_value(current_price=0.0)
        assert mv == 0.0


class TestPnL:
    """P&L calculation (absolute)."""

    def test_pnl_profit_long_position(self):
        """P&L positive for long position with price increase."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=96.0)
        expected = 100.0 * (96.0 - 95.0)
        assert pnl == expected
        assert pnl == 100.0

    def test_pnl_loss_long_position(self):
        """P&L negative for long position with price decrease."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=94.0)
        expected = 100.0 * (94.0 - 95.0)
        assert pnl == expected
        assert pnl == -100.0

    def test_pnl_profit_short_position(self):
        """P&L positive for short position with price decrease."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=-100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=94.0)
        expected = -100.0 * (94.0 - 95.0)
        assert pnl == expected
        assert pnl == 100.0  # Short profits from price decline

    def test_pnl_loss_short_position(self):
        """P&L negative for short position with price increase."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=-100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=96.0)
        expected = -100.0 * (96.0 - 95.0)
        assert pnl == expected
        assert pnl == -100.0  # Short loses from price increase

    def test_pnl_no_change(self):
        """P&L zero when price unchanged."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=95.0)
        assert pnl == 0.0

    def test_pnl_fractional_quantity(self):
        """P&L with fractional quantity."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=2.5, entry_price=100.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=102.0)
        expected = 2.5 * (102.0 - 100.0)
        assert abs(pnl - expected) < 1e-10
        assert abs(pnl - 5.0) < 1e-10

    def test_pnl_zero_quantity(self):
        """P&L zero for zero quantity."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=0.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl = pos.pnl(current_price=100.0)
        assert pnl == 0.0


class TestPnLPercent:
    """P&L percentage calculation."""

    def test_pnl_percent_profit(self):
        """P&L percent for profitable position."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=96.0)
        expected = (96.0 - 95.0) / 95.0
        assert abs(pnl_pct - expected) < 1e-10
        assert abs(pnl_pct - 0.010526) < 1e-5  # ~1.05%

    def test_pnl_percent_loss(self):
        """P&L percent for losing position."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=94.0)
        expected = (94.0 - 95.0) / 95.0
        assert abs(pnl_pct - expected) < 1e-10
        assert abs(pnl_pct - (-0.010526)) < 1e-5  # ~-1.05%

    def test_pnl_percent_independent_of_quantity(self):
        """P&L percent same regardless of quantity."""
        asset = PriceFuture('SFRZ4')
        pos1 = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))
        pos2 = Position(asset, quantity=10.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl_pct1 = pos1.pnl_percent(current_price=96.0)
        pnl_pct2 = pos2.pnl_percent(current_price=96.0)

        assert abs(pnl_pct1 - pnl_pct2) < 1e-10

    def test_pnl_percent_zero_entry_price(self):
        """P&L percent returns 0 for zero entry price (undefined)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=0.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=96.0)
        assert pnl_pct == 0.0

    def test_pnl_percent_negative_entry_price(self):
        """P&L percent returns 0 for negative entry price (invalid)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=-95.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=96.0)
        assert pnl_pct == 0.0

    def test_pnl_percent_total_loss(self):
        """P&L percent is -100% for total loss (price to zero)."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=0.0)
        assert abs(pnl_pct - (-1.0)) < 1e-10  # -100%

    def test_pnl_percent_double(self):
        """P&L percent is 100% when price doubles."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=50.0, entry_date=date(2024, 11, 1))

        pnl_pct = pos.pnl_percent(current_price=100.0)
        assert abs(pnl_pct - 1.0) < 1e-10  # 100%


class TestDifferentAssetTypes:
    """Position works with different asset types."""

    def test_position_with_price_future(self):
        """Position with PriceFuture asset."""
        asset = PriceFuture('SFRZ4')
        pos = Position(asset, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        assert pos.asset.get_identifier() == 'SFRZ4'
        assert pos.asset.get_asset_type() == 'PriceFuture'

    def test_position_with_rollable_future(self):
        """Position with RollableFuture asset."""
        asset = RollableFuture('SFRZ4', 'SFRH5', date(2024, 12, 10))
        pos = Position(asset, quantity=50.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        assert pos.asset.get_identifier() == 'SFRZ4'
        assert pos.asset.get_asset_type() == 'RollableFuture'

    def test_market_value_calculation_uses_asset(self):
        """Market value calculation doesn't depend on asset type."""
        future = PriceFuture('SFRZ4')
        pos = Position(future, quantity=100.0, entry_price=95.0, entry_date=date(2024, 11, 1))

        # Market value is simple quantity × price regardless of asset type
        mv = pos.market_value(current_price=96.0)
        assert mv == 9600.0
