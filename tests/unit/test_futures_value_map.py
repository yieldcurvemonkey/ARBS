"""
Tests for FuturesValueFunctionMap

Verifies that futures value metrics are correctly calculated.

Test structure:
- Phase 1: Basic value calculations (PRICE, IMPLIED_RATE, NPV, DV01)
- Phase 2: Structure-specific calculations (pack averaging, calendar spreads)
- Phase 3: Advanced metrics (CARRY, MARGIN) - deferred

Tier 1 (Essential - Implement Now):
- PRICE: Futures price (e.g., 94.50)
- IMPLIED_RATE: 100 - Price (e.g., 5.50%)
- NPV: Mark-to-market in dollars
- DV01: Dollar value of 1bp move ($25 per contract for SFR)
"""

import pytest
from datetime import date
from Query.Futures.FuturesValue import FuturesValue


class TestFuturesValueMapBasics:
    """Test basic value map functionality."""

    def test_value_map_can_be_imported(self):
        """Verify FuturesValueFunctionMap exists and can be imported."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        assert FuturesValueFunctionMap is not None

    def test_value_map_can_be_instantiated(self, mock_usd_curve, mock_futures_pricer):
        """Verify value map can be created with curve and package."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # Create simple package with one contract
        package = [MockFuture(
            contract="SFRZ4",
            expiry=date(2024, 12, 18),
            multiplier=2500.0,
            tick_size=0.0025,
            currency="USD",
            quantity=1.0,
        )]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )
        assert value_map is not None


class TestPriceCalculation:
    """Test PRICE value calculation."""

    def test_price_for_single_contract(self, mock_futures_pricer):
        """PRICE should return the futures price for a single contract."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        package = [MockFuture(
            contract="SFRZ4",
            expiry=date(2024, 12, 18),
            multiplier=2500.0,
            tick_size=0.0025,
            currency="USD",
            quantity=1.0,
        )]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        price = value_map.apply(FuturesValue.PRICE)

        # Mock pricer should return a price around 94.50
        assert isinstance(price, float)
        assert 90.0 < price < 100.0  # Reasonable SOFR price range

    def test_price_for_calendar_spread(self, mock_futures_pricer):
        """PRICE for calendar should be front - back (weighted sum)."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # Calendar: long SFRZ4, short SFRH5
        package = [
            MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0),
            MockFuture("SFRH5", date(2025, 3, 19), 2500.0, 0.0025, "USD", 1.0),
        ]
        risk_weights = [1.0, -1.0]  # Long front, short back

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        spread_price = value_map.apply(FuturesValue.PRICE)

        # Should be difference: price_front - price_back
        # Typically negative (front cheaper than back in normal curve)
        assert isinstance(spread_price, float)


class TestImpliedRateCalculation:
    """Test IMPLIED_RATE value calculation."""

    def test_implied_rate_for_single_contract(self, mock_futures_pricer):
        """IMPLIED_RATE should be 100 - Price."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        package = [MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0)]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        price = value_map.apply(FuturesValue.PRICE)
        implied_rate = value_map.apply(FuturesValue.IMPLIED_RATE)

        # IMPLIED_RATE = 100 - PRICE
        assert abs(implied_rate - (100.0 - price)) < 0.001


class TestNPVCalculation:
    """Test NPV (Net Present Value) calculation."""

    def test_npv_for_single_contract(self, mock_futures_pricer):
        """NPV should return mark-to-market value in dollars."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        package = [MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0)]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        npv = value_map.apply(FuturesValue.NPV)

        # NPV should be a dollar amount
        assert isinstance(npv, float)
        # For futures, NPV depends on entry price vs current price
        # Mock pricer should return some reasonable value

    def test_npv_for_calendar_spread(self, mock_futures_pricer):
        """NPV for calendar spread should aggregate both legs."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        package = [
            MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0),
            MockFuture("SFRH5", date(2025, 3, 19), 2500.0, 0.0025, "USD", 1.0),
        ]
        risk_weights = [1.0, -1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        npv = value_map.apply(FuturesValue.NPV)

        # NPV should be net of both legs
        assert isinstance(npv, float)


class TestDV01Calculation:
    """Test DV01 (Dollar Value of 01) calculation."""

    def test_dv01_for_single_sfr_contract(self, mock_futures_pricer):
        """DV01 for single SFR contract should be $25 per contract."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        package = [MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0)]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        dv01 = value_map.apply(FuturesValue.DV01)

        # SFR: $2500 multiplier, 1bp = 0.01 price change
        # DV01 = $2500 * 0.01 = $25
        assert abs(dv01 - 25.0) < 0.01

    def test_dv01_for_multiple_contracts(self, mock_futures_pricer):
        """DV01 should scale with quantity."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # 10 contracts
        package = [MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 10.0)]
        risk_weights = [1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        dv01 = value_map.apply(FuturesValue.DV01)

        # 10 contracts × $25 = $250
        assert abs(dv01 - 250.0) < 0.1

    def test_dv01_for_calendar_spread(self, mock_futures_pricer):
        """DV01 for calendar spread should be net of both legs."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # Calendar: +1 SFRZ4, -1 SFRH5 (both same size)
        package = [
            MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 1.0),
            MockFuture("SFRH5", date(2025, 3, 19), 2500.0, 0.0025, "USD", 1.0),
        ]
        risk_weights = [1.0, -1.0]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        dv01 = value_map.apply(FuturesValue.DV01)

        # Calendar spread: Long front ($25) + Short back (-$25) = $0 net DV01
        # (This is the point of a duration-neutral spread)
        assert abs(dv01) < 0.1  # Should be close to zero

    def test_dv01_for_pack(self, mock_futures_pricer):
        """DV01 for pack should sum all 4 contracts."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # Pack: 4 contracts, each 0.25 quantity
        package = [
            MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRH5", date(2025, 3, 19), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRM5", date(2025, 6, 18), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRU5", date(2025, 9, 17), 2500.0, 0.0025, "USD", 0.25),
        ]
        risk_weights = [0.25, 0.25, 0.25, 0.25]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        dv01 = value_map.apply(FuturesValue.DV01)

        # 4 contracts × 0.25 qty × $25 = $25 total
        assert abs(dv01 - 25.0) < 0.1


class TestPackPriceAveraging:
    """Test pack price averaging with rounding."""

    def test_pack_price_averages_four_contracts(self, mock_futures_pricer):
        """Pack price should average 4 contract prices."""
        from Query.Futures.FuturesValueFunctionMap import FuturesValueFunctionMap
        from Query.Futures.FuturesStructureFunctionMap import MockFuture

        # Pack with explicit prices (via mock)
        package = [
            MockFuture("SFRZ4", date(2024, 12, 18), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRH5", date(2025, 3, 19), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRM5", date(2025, 6, 18), 2500.0, 0.0025, "USD", 0.25),
            MockFuture("SFRU5", date(2025, 9, 17), 2500.0, 0.0025, "USD", 0.25),
        ]
        risk_weights = [0.25, 0.25, 0.25, 0.25]

        value_map = FuturesValueFunctionMap(
            curve=mock_futures_pricer,
            package=package,
            risk_weights=risk_weights,
        )

        pack_price = value_map.apply(FuturesValue.PRICE, round_pack_to_tick=False)

        # Pack price = (P1 + P2 + P3 + P4) / 4
        assert isinstance(pack_price, float)
        assert 90.0 < pack_price < 100.0
