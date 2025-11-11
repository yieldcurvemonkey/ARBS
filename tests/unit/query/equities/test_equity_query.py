# ABOUTME: Unit tests for EquityQuery class
# ABOUTME: Tests query construction, validation, and MDP request building

import pytest
from datetime import date, timedelta
from Query.Equities.EquityQuery import EquityQuery
from Query.Equities.EquityStructure import EquityStructure
from Query.Equities.EquityValue import EquityValue


class TestEquityQuery:
    """Test suite for EquityQuery."""

    def test_create_basic_equity_query(self):
        """Test creating a basic equity query."""
        query = EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.PRICE,
        )

        assert query.ticker == "AAPL"
        assert query.sector == "Information Technology"
        assert query.structure == EquityStructure.SINGLE
        assert query.value == EquityValue.PRICE
        assert query.lookback_days == 252  # default
        assert query.weight == 1.0  # default

    def test_create_query_with_custom_params(self):
        """Test creating query with custom parameters."""
        query = EquityQuery(
            ticker="MSFT",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.RETURN,
            lookback_days=126,  # 6 months
            weight=0.05,
        )

        assert query.ticker == "MSFT"
        assert query.lookback_days == 126
        assert query.weight == 0.05

    def test_build_mdp_request(self):
        """Test building market data provider request."""
        query = EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.PRICE,
            lookback_days=252,
        )

        as_of_date = date(2024, 12, 31)
        request = query.build_mdp_request(as_of_date)

        assert request["ticker"] == "AAPL"
        assert request["end_date"] == as_of_date
        assert request["start_date"] == as_of_date - timedelta(days=252)
        assert "price" in request["fields"]
        assert "volume" in request["fields"]
        assert request["adjusted"] is True

    def test_build_mdp_request_with_fundamentals(self):
        """Test MDP request includes fundamentals for yield values."""
        query = EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.DIVIDEND_YIELD,
        )

        request = query.build_mdp_request(date(2024, 12, 31))

        assert "dividend" in request["fields"]

    def test_validation_empty_ticker(self):
        """Test validation fails for empty ticker."""
        with pytest.raises(ValueError, match="Ticker cannot be empty"):
            EquityQuery(
                ticker="",
                sector="Information Technology",
                structure=EquityStructure.SINGLE,
                value=EquityValue.PRICE,
            )

    def test_validation_negative_lookback(self):
        """Test validation fails for negative lookback days."""
        with pytest.raises(ValueError, match="Lookback days must be positive"):
            EquityQuery(
                ticker="AAPL",
                sector="Information Technology",
                structure=EquityStructure.SINGLE,
                value=EquityValue.PRICE,
                lookback_days=-10,
            )

    def test_validation_missing_sector(self):
        """Test validation fails for missing sector."""
        with pytest.raises(ValueError, match="Sector must be specified"):
            EquityQuery(
                ticker="AAPL",
                sector="",
                structure=EquityStructure.SINGLE,
                value=EquityValue.PRICE,
            )

    def test_metadata_field(self):
        """Test metadata field can store additional info."""
        query = EquityQuery(
            ticker="AAPL",
            sector="Information Technology",
            structure=EquityStructure.SINGLE,
            value=EquityValue.PRICE,
            metadata={"signal": "momentum", "rank": 1},
        )

        assert query.metadata["signal"] == "momentum"
        assert query.metadata["rank"] == 1

    def test_multiple_structures(self):
        """Test different structure types."""
        structures = [
            EquityStructure.SINGLE,
            EquityStructure.SECTOR_BASKET,
            EquityStructure.LONG_SHORT,
            EquityStructure.MARKET_NEUTRAL,
        ]

        for structure in structures:
            query = EquityQuery(
                ticker="AAPL",
                sector="Information Technology",
                structure=structure,
                value=EquityValue.PRICE,
            )
            assert query.structure == structure

    def test_multiple_value_types(self):
        """Test different value types."""
        values = [
            EquityValue.PRICE,
            EquityValue.RETURN,
            EquityValue.LOG_RETURN,
            EquityValue.DIVIDEND_YIELD,
            EquityValue.EARNINGS_YIELD,
            EquityValue.VOLATILITY,
        ]

        for value_type in values:
            query = EquityQuery(
                ticker="AAPL",
                sector="Information Technology",
                structure=EquityStructure.SINGLE,
                value=value_type,
            )
            assert query.value == value_type
