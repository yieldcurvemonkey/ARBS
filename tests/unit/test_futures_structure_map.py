"""
Tests for FuturesStructureFunctionMap

Verifies that FuturesQuery structures are correctly resolved into
priceable STIR futures objects.

Test structure:
- Phase 1: OUTRIGHT (single contract)
- Phase 2: CALENDAR (front-back spread)
- Phase 3: PACK (4 consecutive contracts)
- Phase 4: BUNDLE (8 consecutive contracts)
"""

import pytest
from datetime import date
from Query.Futures.FuturesStructure import FuturesStructure


class TestFuturesStructureMapBasics:
    """Test basic structure map functionality."""

    def test_structure_map_can_be_imported(self):
        """Verify FuturesStructureFunctionMap exists and can be imported."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap
        assert FuturesStructureFunctionMap is not None

    def test_structure_map_can_be_instantiated(self, mock_usd_curve):
        """Verify structure map can be created with a curve."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)
        assert structure_map is not None


class TestOutrightStructure:
    """Test OUTRIGHT structure (single contract)."""

    def test_outright_builds_single_contract(self, mock_usd_curve):
        """OUTRIGHT structure should build a single futures contract."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        # Build single contract SFRZ4
        package, risk_weights = structure_map.apply(
            FuturesStructure.OUTRIGHT,
            contract="SFRZ4",
            quantity=1.0,
        )

        assert isinstance(package, list)
        assert len(package) == 1
        assert isinstance(risk_weights, list)
        assert len(risk_weights) == 1
        assert risk_weights[0] == 1.0  # Long position

    def test_outright_contract_has_correct_expiry(self, mock_usd_curve):
        """Outright contract should have correct IMM expiry date."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.OUTRIGHT,
            contract="SFRZ4",
            quantity=1.0,
        )

        # SFRZ4 = December 2024
        # Third Wednesday of Dec 2024 is Dec 18
        fut = package[0]

        # Check that the future has an expiry attribute
        assert hasattr(fut, 'expiry') or hasattr(fut, 'maturity_date')
        assert fut.expiry == date(2024, 12, 18)  # Third Wednesday of Dec 2024

    def test_outright_contract_has_correct_specs(self, mock_usd_curve):
        """Outright SFR contract should have correct multiplier and tick size."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.OUTRIGHT,
            contract="SFRZ4",
            quantity=1.0,
        )

        fut = package[0]

        # SFR specs: $2500 multiplier, 0.0025 tick
        assert fut.multiplier == 2500.0
        assert fut.tick_size == 0.0025
        assert fut.currency == "USD"
        assert fut.contract == "SFRZ4"


class TestCalendarStructure:
    """Test CALENDAR structure (front-back spread)."""

    def test_calendar_builds_two_contracts(self, mock_usd_curve):
        """CALENDAR structure should build front and back contracts."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.CALENDAR,
            front_contract="SFRZ4",
            back_contract="SFRH5",
            quantity=1.0,
        )

        assert isinstance(package, list)
        assert len(package) == 2
        assert package[0].contract == "SFRZ4"
        assert package[1].contract == "SFRH5"

    def test_calendar_risk_weights(self, mock_usd_curve):
        """Calendar spread should return risk weights [+1, -1]."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        # Calendar spread: Buy front, sell back
        package, risk_weights = structure_map.apply(
            FuturesStructure.CALENDAR,
            front_contract="SFRZ4",
            back_contract="SFRH5",
            quantity=1.0,
        )

        assert len(package) == 2
        assert len(risk_weights) == 2
        assert risk_weights == [1.0, -1.0]  # Long front, short back


class TestPackStructure:
    """Test PACK structure (4 consecutive contracts)."""

    def test_pack_builds_four_contracts(self, mock_usd_curve):
        """PACK structure should build 4 consecutive quarterly contracts."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.PACK,
            contract="SFRZ4",  # Base contract
            pack_color="WHITE",
            quantity=1.0,
        )

        assert isinstance(package, list)
        assert len(package) == 4
        assert len(risk_weights) == 4
        assert risk_weights == [0.25, 0.25, 0.25, 0.25]  # Equal weighted

    def test_pack_white_starts_at_base(self, mock_usd_curve):
        """WHITE pack should start at the base contract."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap
        from Query.Futures.FuturesQuery import get_contract_chain

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.PACK,
            contract="SFRZ4",
            pack_color="WHITE",
            quantity=1.0,
        )

        # WHITE pack from SFRZ4: [SFRZ4, SFRH5, SFRM5, SFRU5]
        expected_chain = get_contract_chain("SFRZ4", 4)
        assert len(package) == 4
        actual_contracts = [fut.contract for fut in package]
        assert actual_contracts == expected_chain

    def test_pack_red_skips_first_contract(self, mock_usd_curve):
        """RED pack should skip the first contract (offset=1)."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap
        from Query.Futures.FuturesQuery import get_contract_chain

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.PACK,
            contract="SFRZ4",
            pack_color="RED",
            quantity=1.0,
        )

        # RED pack from SFRZ4: [SFRH5, SFRM5, SFRU5, SFRZ5]
        expected_chain = get_contract_chain("SFRZ4", 5)  # Need 5 to skip first
        expected_red = expected_chain[1:5]  # Skip first, take next 4

        assert len(package) == 4
        actual_contracts = [fut.contract for fut in package]
        assert actual_contracts == expected_red


class TestBundleStructure:
    """Test BUNDLE structure (8 consecutive contracts)."""

    def test_bundle_builds_eight_contracts(self, mock_usd_curve):
        """BUNDLE structure should build 8 consecutive quarterly contracts."""
        from Query.Futures.FuturesStructureFunctionMap import FuturesStructureFunctionMap

        structure_map = FuturesStructureFunctionMap(curve=mock_usd_curve)

        package, risk_weights = structure_map.apply(
            FuturesStructure.BUNDLE,
            bundle_start_contract="SFRZ4",
            quantity=1.0,
        )

        assert isinstance(package, list)
        assert len(package) == 8
        assert len(risk_weights) == 8
        assert risk_weights == [0.125] * 8  # Equal weighted
