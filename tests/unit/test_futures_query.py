# ABOUTME: Tests for futures query infrastructure
# ABOUTME: Validates FuturesQuery, helper functions, and contract specifications
"""
Unit tests for Futures query objects.

Tests cover:
- FuturesStructure enum
- FuturesValue enum
- FuturesQuery dataclass
- Contract parsing and expiry calculation
- Query arithmetic (spreads, butterflies)

Following TDD: These tests are written BEFORE implementing Query/Futures/*.
"""

import pytest
from datetime import date
from dataclasses import FrozenInstanceError


# =============================================================================
# Test FuturesStructure Enum
# =============================================================================

class TestFuturesStructure:
    """Test FuturesStructure enum."""

    def test_futures_structure_enum_exists(self):
        """Test that FuturesStructure enum can be imported."""
        from Query.Futures.FuturesStructure import FuturesStructure

        assert FuturesStructure is not None

    def test_futures_structure_has_required_values(self):
        """Test that FuturesStructure has all required structure types."""
        from Query.Futures.FuturesStructure import FuturesStructure

        # Required structures
        assert hasattr(FuturesStructure, 'OUTRIGHT')
        assert hasattr(FuturesStructure, 'CALENDAR')
        assert hasattr(FuturesStructure, 'PACK')
        assert hasattr(FuturesStructure, 'BUNDLE')
        assert hasattr(FuturesStructure, 'BASIS')

    def test_futures_structure_values_are_unique(self):
        """Test that structure values are distinct."""
        from Query.Futures.FuturesStructure import FuturesStructure

        values = [
            FuturesStructure.OUTRIGHT,
            FuturesStructure.CALENDAR,
            FuturesStructure.PACK,
            FuturesStructure.BUNDLE,
            FuturesStructure.BASIS,
        ]

        assert len(values) == len(set(values))


# =============================================================================
# Test FuturesValue Enum
# =============================================================================

class TestFuturesValue:
    """Test FuturesValue enum."""

    def test_futures_value_enum_exists(self):
        """Test that FuturesValue enum can be imported."""
        from Query.Futures.FuturesValue import FuturesValue

        assert FuturesValue is not None

    def test_futures_value_has_required_values(self):
        """Test that FuturesValue has all required value types."""
        from Query.Futures.FuturesValue import FuturesValue

        # Required values
        assert hasattr(FuturesValue, 'PRICE')
        assert hasattr(FuturesValue, 'NPV')
        assert hasattr(FuturesValue, 'DV01')
        assert hasattr(FuturesValue, 'MARGIN')
        assert hasattr(FuturesValue, 'BASIS')
        assert hasattr(FuturesValue, 'CONVEXITY_ADJ')
        assert hasattr(FuturesValue, 'IMPLIED_RATE')
        assert hasattr(FuturesValue, 'CARRY')


# =============================================================================
# Test FuturesQuery Dataclass
# =============================================================================

class TestFuturesQuery:
    """Test FuturesQuery dataclass."""

    def test_futures_query_creation(self):
        """Test creating a basic Futures query."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4",
            currency="USD"
        )

        assert query.structure == FuturesStructure.OUTRIGHT
        assert query.value == FuturesValue.PRICE
        assert query.contract == "SFRZ4"
        assert query.currency == "USD"

    def test_futures_query_is_frozen(self):
        """Test that FuturesQuery is immutable (frozen)."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4"
        )

        with pytest.raises(FrozenInstanceError):
            query.contract = "SFRH5"

    def test_futures_query_defaults(self):
        """Test FuturesQuery default values."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4"
        )

        # Check defaults
        assert query.currency == "USD"
        assert query.product_type == "STIR"
        assert query.multiplier == 2500.0
        assert query.tick_size == 0.0025  # 0.25bp for SFR

    def test_futures_query_contract_parsing(self):
        """Test that contract code is parsed correctly."""
        from Query.Futures.FuturesQuery import FuturesQuery, parse_futures_contract
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        # Test various contract codes
        test_cases = [
            ("SFRZ4", "SFR", "Z", "4", 2024, 12),  # Eurodollar Dec 2024
            ("SFRH5", "SFR", "H", "5", 2025, 3),   # Eurodollar Mar 2025
            ("SFRM5", "SFR", "M", "5", 2025, 6),   # Eurodollar Jun 2025
            ("SFRU5", "SFR", "U", "5", 2025, 9),   # Eurodollar Sep 2025
        ]

        for contract, prefix, month_code, year_digit, expected_year, expected_month in test_cases:
            result = parse_futures_contract(contract)
            assert result['prefix'] == prefix
            assert result['month_code'] == month_code
            assert result['year_digit'] == year_digit
            assert result['year'] == expected_year
            assert result['month'] == expected_month

    def test_futures_query_expiry_calculation(self):
        """Test that expiry is calculated correctly from contract code."""
        from Query.Futures.FuturesQuery import FuturesQuery, get_contract_expiry
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        # SFRZ4 = December 2024 = third Wednesday
        expiry = get_contract_expiry("SFRZ4")

        assert expiry.year == 2024
        assert expiry.month == 12
        assert expiry.weekday() == 2  # Wednesday
        # Should be the third Wednesday
        assert 15 <= expiry.day <= 21

    def test_futures_query_with_explicit_expiry(self):
        """Test creating query with explicit expiry date."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        expiry = date(2024, 12, 18)

        query = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4",
            expiry=expiry
        )

        assert query.expiry == expiry


# =============================================================================
# Test Query Arithmetic
# =============================================================================

class TestFuturesQueryArithmetic:
    """Test arithmetic operations on Futures queries."""

    def test_futures_query_addition(self):
        """Test adding two futures queries creates a spread."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        q1 = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4"
        )

        q2 = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRH5"
        )

        # Adding should create a composite query or raise not implemented
        # For now, we expect this to work once implemented
        result = q1 + q2

        assert result is not None

    def test_futures_query_subtraction(self):
        """Test subtracting futures queries creates a spread."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        q1 = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRH5"
        )

        q2 = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4"
        )

        # H5 - Z4 = calendar spread
        result = q1 - q2

        assert result is not None

    def test_futures_query_multiplication(self):
        """Test multiplying futures query by scalar."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        q1 = FuturesQuery(
            structure=FuturesStructure.OUTRIGHT,
            value=FuturesValue.PRICE,
            contract="SFRZ4",
            quantity=1.0
        )

        # Multiply by 10
        result = q1 * 10

        assert result.quantity == 10.0


# =============================================================================
# Test Calendar Spread Query
# =============================================================================

class TestCalendarSpreadQuery:
    """Test calendar spread queries."""

    def test_calendar_spread_creation(self):
        """Test creating a calendar spread query."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.CALENDAR,
            value=FuturesValue.PRICE,
            front_contract="SFRZ4",
            back_contract="SFRH5"
        )

        assert query.structure == FuturesStructure.CALENDAR
        assert query.front_contract == "SFRZ4"
        assert query.back_contract == "SFRH5"


# =============================================================================
# Test Pack Query
# =============================================================================

class TestPackQuery:
    """Test pack queries (4 consecutive contracts)."""

    def test_pack_creation(self):
        """Test creating a pack query."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        # Red pack = next 4 quarterly contracts
        query = FuturesQuery(
            structure=FuturesStructure.PACK,
            value=FuturesValue.PRICE,
            pack_color="RED",  # or could be first_contract="SFRH5"
            currency="USD"
        )

        assert query.structure == FuturesStructure.PACK
        assert query.pack_color == "RED"


# =============================================================================
# Test Bundle Query
# =============================================================================

class TestBundleQuery:
    """Test bundle queries (8 consecutive contracts)."""

    def test_bundle_creation(self):
        """Test creating a bundle query."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.BUNDLE,
            value=FuturesValue.PRICE,
            bundle_start_contract="SFRH5"
        )

        assert query.structure == FuturesStructure.BUNDLE


# =============================================================================
# Test Basis Query (Futures vs Swap)
# =============================================================================

class TestBasisQuery:
    """Test basis queries (futures vs swap)."""

    def test_basis_creation(self):
        """Test creating a basis query (future vs swap)."""
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure
        from Query.Futures.FuturesValue import FuturesValue

        query = FuturesQuery(
            structure=FuturesStructure.BASIS,
            value=FuturesValue.BASIS,
            contract="SFRZ4",
            swap_tenor="3M"  # 3-month swap to match Eurodollar
        )

        assert query.structure == FuturesStructure.BASIS
        assert query.swap_tenor == "3M"


# =============================================================================
# Test Helper Functions
# =============================================================================

class TestFuturesHelpers:
    """Test helper functions for futures."""

    def test_get_next_imm_contract(self):
        """Test getting next IMM contract."""
        from Query.Futures.FuturesQuery import get_next_imm_contract

        # From Dec 2024, next is Mar 2025
        next_contract = get_next_imm_contract("SFRZ4")
        assert next_contract == "SFRH5"

        # From Mar 2025, next is Jun 2025
        next_contract = get_next_imm_contract("SFRH5")
        assert next_contract == "SFRM5"

        # From Jun 2025, next is Sep 2025
        next_contract = get_next_imm_contract("SFRM5")
        assert next_contract == "SFRU5"

        # From Sep 2025, next is Dec 2025
        next_contract = get_next_imm_contract("SFRU5")
        assert next_contract == "SFRZ5"

    def test_get_contract_chain(self):
        """Test getting a chain of contracts."""
        from Query.Futures.FuturesQuery import get_contract_chain

        # Get 4 contracts starting from SFRZ4
        chain = get_contract_chain("SFRZ4", count=4)

        assert len(chain) == 4
        assert chain[0] == "SFRZ4"
        assert chain[1] == "SFRH5"
        assert chain[2] == "SFRM5"
        assert chain[3] == "SFRU5"

    def test_pack_colors(self):
        """Test pack color definitions."""
        from Query.Futures.FuturesQuery import PACK_COLORS

        # Standard pack colors
        assert "WHITE" in PACK_COLORS or "white" in PACK_COLORS
        assert "RED" in PACK_COLORS or "red" in PACK_COLORS
        assert "GREEN" in PACK_COLORS or "green" in PACK_COLORS
        assert "BLUE" in PACK_COLORS or "blue" in PACK_COLORS
        assert "GOLD" in PACK_COLORS or "gold" in PACK_COLORS
