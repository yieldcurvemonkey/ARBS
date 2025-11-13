# ABOUTME: Unit tests for CurrencyQuery class
# ABOUTME: Tests query construction, validation, and abstract method implementations

import pytest
from datetime import date
from Query.Currencies.CurrencyQuery import CurrencyQuery
from Query.Currencies.CurrencyStructure import CurrencyStructure
from Query.Currencies.CurrencyValue import CurrencyValue


class TestCurrencyQuery:
    """Test suite for CurrencyQuery."""

    def test_create_basic_currency_query(self):
        """Test creating a basic currency query."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
            value=CurrencyValue.YIELD,
        )

        assert query.currency == "USD"
        assert query.tenor == "10Y"
        assert query.structure == CurrencyStructure.OUTRIGHT
        assert query.value == CurrencyValue.YIELD
        assert query.weight == 1.0  # default

    def test_create_query_with_custom_params(self):
        """Test creating query with custom parameters."""
        query = CurrencyQuery(
            currency="EUR",
            tenor="5Y",
            structure=CurrencyStructure.BUTTERFLY,
            value=CurrencyValue.CARRY,
            weight=0.05,
            metadata={"signal": "carry", "rank": 1},
        )

        assert query.currency == "EUR"
        assert query.tenor == "5Y"
        assert query.weight == 0.05
        assert query.metadata["signal"] == "carry"

    def test_return_query_returns_self(self):
        """Test return_query returns list containing self."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
        )

        result = query.return_query()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] is query

    def test_col_name_formatting(self):
        """Test col_name returns properly formatted string."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
        )

        col_name = query.col_name()
        assert col_name == "USD_10Y"

    def test_col_name_with_structure_types(self):
        """Test col_name includes structure for complex types."""
        query_butterfly = CurrencyQuery(
            currency="EUR",
            tenor="5Y",
            structure=CurrencyStructure.BUTTERFLY,
        )

        col_name = query_butterfly.col_name()
        assert "EUR" in col_name
        assert "5Y" in col_name

    def test_eval_expression_outright(self):
        """Test eval_expression for OUTRIGHT structure."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
        )

        expr = query.eval_expression()
        assert "USD" in expr
        assert "10Y" in expr

    def test_eval_expression_butterfly(self):
        """Test eval_expression for BUTTERFLY structure."""
        query = CurrencyQuery(
            currency="EUR",
            tenor="5Y",
            structure=CurrencyStructure.BUTTERFLY,
        )

        expr = query.eval_expression()
        # Butterfly should reference 2Y, 5Y, 10Y
        # Formula: 2*(5Y) - (2Y) - (10Y)
        assert "EUR" in expr
        assert "5Y" in expr

    def test_eval_expression_calendar(self):
        """Test eval_expression for CALENDAR structure."""
        query = CurrencyQuery(
            currency="GBP",
            tenor="5Y",
            structure=CurrencyStructure.CALENDAR,
        )

        expr = query.eval_expression()
        assert "GBP" in expr
        assert "5Y" in expr

    def test_validation_empty_currency(self):
        """Test validation fails for empty currency."""
        with pytest.raises(ValueError, match="Currency cannot be empty"):
            CurrencyQuery(
                currency="",
                tenor="10Y",
                structure=CurrencyStructure.OUTRIGHT,
            )

    def test_validation_empty_tenor(self):
        """Test validation fails for empty tenor."""
        with pytest.raises(ValueError, match="Tenor cannot be empty"):
            CurrencyQuery(
                currency="USD",
                tenor="",
                structure=CurrencyStructure.OUTRIGHT,
            )

    def test_validation_invalid_currency(self):
        """Test validation fails for invalid currency."""
        with pytest.raises(ValueError, match="Invalid currency"):
            CurrencyQuery(
                currency="INVALID",
                tenor="10Y",
                structure=CurrencyStructure.OUTRIGHT,
            )

    def test_validation_invalid_tenor(self):
        """Test validation fails for invalid tenor."""
        with pytest.raises(ValueError, match="Invalid tenor"):
            CurrencyQuery(
                currency="USD",
                tenor="99Y",
                structure=CurrencyStructure.OUTRIGHT,
            )

    def test_multiple_structures(self):
        """Test different structure types."""
        structures = [
            CurrencyStructure.OUTRIGHT,
            CurrencyStructure.BUTTERFLY,
            CurrencyStructure.SPREAD,
            CurrencyStructure.CALENDAR,
        ]

        for structure in structures:
            query = CurrencyQuery(
                currency="USD",
                tenor="5Y",
                structure=structure,
            )
            assert query.structure == structure

    def test_multiple_value_types(self):
        """Test different value types."""
        values = [
            CurrencyValue.YIELD,
            CurrencyValue.CARRY,
            CurrencyValue.RETURN,
            CurrencyValue.DV01,
            CurrencyValue.FORWARD_RATE,
        ]

        for value_type in values:
            query = CurrencyQuery(
                currency="USD",
                tenor="10Y",
                structure=CurrencyStructure.OUTRIGHT,
                value=value_type,
            )
            assert query.value == value_type

    def test_multiple_currencies(self):
        """Test all supported currencies."""
        currencies = ["USD", "EUR", "GBP", "CHF", "JPY", "AUD", "CAD"]

        for currency in currencies:
            query = CurrencyQuery(
                currency=currency,
                tenor="10Y",
                structure=CurrencyStructure.OUTRIGHT,
            )
            assert query.currency == currency

    def test_multiple_tenors(self):
        """Test all supported tenors."""
        tenors = ["2Y", "5Y", "10Y", "30Y"]

        for tenor in tenors:
            query = CurrencyQuery(
                currency="USD",
                tenor=tenor,
                structure=CurrencyStructure.OUTRIGHT,
            )
            assert query.tenor == tenor

    def test_metadata_field(self):
        """Test metadata field can store additional info."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
            metadata={"signal": "carry", "rank": 1, "ic": 0.15},
        )

        assert query.metadata["signal"] == "carry"
        assert query.metadata["rank"] == 1
        assert query.metadata["ic"] == 0.15

    def test_butterfly_structure_uses_three_tenors(self):
        """Test butterfly structure implies three tenor points."""
        query = CurrencyQuery(
            currency="EUR",
            tenor="5Y",  # belly of butterfly
            structure=CurrencyStructure.BUTTERFLY,
        )

        # Butterfly should be: 2*(5Y) - (2Y) - (10Y)
        expr = query.eval_expression()

        # Should contain references to wings
        assert query.structure == CurrencyStructure.BUTTERFLY

    def test_spread_structure(self):
        """Test spread structure (e.g., 2Y5Y spread)."""
        query = CurrencyQuery(
            currency="USD",
            tenor="5Y",  # long end
            structure=CurrencyStructure.SPREAD,
        )

        expr = query.eval_expression()
        assert "USD" in expr
        assert query.structure == CurrencyStructure.SPREAD

    def test_calendar_structure(self):
        """Test calendar structure (time spread)."""
        query = CurrencyQuery(
            currency="GBP",
            tenor="10Y",
            structure=CurrencyStructure.CALENDAR,
        )

        assert query.structure == CurrencyStructure.CALENDAR
        expr = query.eval_expression()
        assert "GBP" in expr

    def test_weight_default(self):
        """Test weight defaults to 1.0."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
        )

        assert query.weight == 1.0

    def test_weight_custom(self):
        """Test custom weight values."""
        weights = [0.01, 0.05, 0.10, 0.50, 1.0, 2.0]

        for weight in weights:
            query = CurrencyQuery(
                currency="USD",
                tenor="10Y",
                structure=CurrencyStructure.OUTRIGHT,
                weight=weight,
            )
            assert query.weight == weight

    def test_query_is_frozen_dataclass(self):
        """Test that CurrencyQuery is immutable (frozen dataclass)."""
        query = CurrencyQuery(
            currency="USD",
            tenor="10Y",
            structure=CurrencyStructure.OUTRIGHT,
        )

        # Attempting to modify should raise an error
        with pytest.raises(Exception):  # FrozenInstanceError in dataclasses
            query.currency = "EUR"
