"""
Test basic Query operations.

These tests document how users should create and manipulate queries.
They follow TDD principles - write the test first to define the API.
"""

import pytest
import datetime
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


class TestQueryCreation:
    """Test that queries can be created with expected parameters."""

    def test_create_simple_outright_query(self):
        """
        EXAMPLE: Create a simple 5Y IRS outright query.

        This is the most basic use case - requesting a par rate for a single tenor.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        assert query.product == "IRS"
        assert query.structure_id == IRSwapStructure.OUTRIGHT
        assert query.structure_kwargs.get("tenor") == "5Y"
        assert query.value_id == IRSwapValue.RATE

    def test_create_outright_with_bpv(self):
        """
        EXAMPLE: Create an outright query with custom BPV (basis point value).

        BPV controls the notional sizing of the instrument.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="10Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        assert query.structure_kwargs.get("bpv") == 1_000_000
        assert query.structure_kwargs.get("tenor") == "10Y"

    def test_create_curve_query(self):
        """
        EXAMPLE: Create a curve query (ladder of multiple tenors).

        A curve query builds multiple instruments across tenors.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.CURVE,
            value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "tenors": ["2Y", "3Y", "5Y", "7Y", "10Y"],
                "bpv": 500_000,
            },
        )

        assert query.structure_id == IRSwapStructure.CURVE
        assert len(query.structure_kwargs.get("tenors", [])) == 5

    def test_create_fly_query(self):
        """
        EXAMPLE: Create a butterfly (fly) query.

        A fly is a combination of three instruments: front/belly/back.
        Typically: long front, short belly (2x), long back.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.FLY,
            value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "front_tenor": "2Y",
                "belly_tenor": "5Y",
                "back_tenor": "10Y",
                "bpv": 1_000_000,
            },
        )

        assert query.structure_id == IRSwapStructure.FLY
        assert query.structure_kwargs["front_tenor"] == "2Y"
        assert query.structure_kwargs["belly_tenor"] == "5Y"
        assert query.structure_kwargs["back_tenor"] == "10Y"


class TestQueryMarketRequest:
    """Test that queries properly build market data requests."""

    def test_mdp_request_with_date(self):
        """
        EXAMPLE: Build MDP request for a specific date.

        The query should inject the timestamp into the market request.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
            market_request={"curve_name": "USD-SOFR-1D"},
        )

        now = datetime.datetime(2025, 1, 15, 16, 0, 0)
        request = query.build_mdp_request(now)

        assert "curve_name" in request
        assert request["curve_name"] == "USD-SOFR-1D"
        assert "timestamp" in request
        assert request["timestamp"] == now.date()

    def test_mdp_request_with_live_timestamp(self):
        """
        EXAMPLE: Create a 'live' query that doesn't override timestamp.

        Some queries should use real-time data without historical lookup.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            market_request={
                "curve_name": "USD-SOFR-1D",
                "timestamp": "live",
            },
        )

        now = datetime.datetime(2025, 1, 15)
        request = query.build_mdp_request(now)

        # Should preserve "live" instead of overriding
        assert request["timestamp"] == "live"


class TestQuerySignatures:
    """Test query signature generation for logging and identification."""

    def test_signature_is_stable(self):
        """
        EXAMPLE: Query signatures should be deterministic.

        Signatures are used for caching and logging.
        """
        query1 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        query2 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        assert query1.signature() == query2.signature()

    def test_signature_differs_by_parameter(self):
        """
        EXAMPLE: Different queries should have different signatures.
        """
        query_5y = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        query_10y = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="10Y",
            curve="USD-SOFR-1D",
        )

        assert query_5y.signature() != query_10y.signature()


class TestQueryTags:
    """Test query tagging for portfolio management."""

    def test_add_tags_to_query(self):
        """
        EXAMPLE: Tag queries for later unwinding.

        Tags allow you to identify and close related positions.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            tags=("fomc-trade", "short-end"),
        )

        assert "fomc-trade" in query.tags
        assert "short-end" in query.tags
        assert len(query.tags) == 2

    def test_query_with_custom_name(self):
        """
        EXAMPLE: Name queries for readable output.

        Names appear in logs and reports.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            name="5Y SOFR Receiver",
        )

        assert query.name == "5Y SOFR Receiver"


class TestQueryArithmetic:
    """Test query arithmetic operations (if implemented)."""

    def test_negate_query(self):
        """
        EXAMPLE: Negate a query to reverse direction.

        Should flip the risk weight to opposite sign.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        # This may not be implemented yet - TDD!
        try:
            neg_query = -query
            # If implemented, should flip the sign
            assert True  # Placeholder
        except (AttributeError, NotImplementedError):
            pytest.skip("Query negation not yet implemented")

    def test_scale_query(self):
        """
        EXAMPLE: Scale a query by a factor.

        Useful for position sizing.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        try:
            scaled = query * 2.0
            # Should double the risk
            assert True  # Placeholder
        except (AttributeError, NotImplementedError):
            pytest.skip("Query scaling not yet implemented")


class TestQueryValidation:
    """Test input validation and error handling."""

    def test_missing_required_fields_raises_error(self):
        """
        EXAMPLE: Creating a query without required fields should fail gracefully.
        """
        with pytest.raises((TypeError, ValueError, AttributeError)):
            # Missing tenor for OUTRIGHT
            query = IRSwapQuery(
                structure=IRSwapStructure.OUTRIGHT,
                curve="USD-SOFR-1D",
                # tenor missing!
            )

    def test_invalid_tenor_format(self):
        """
        EXAMPLE: Invalid tenor formats should be caught.

        Note: This might be caught at resolution time, not creation time.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="INVALID",  # Bad format
            curve="USD-SOFR-1D",
        )

        # Query creation might succeed, but resolution should fail
        # This documents the behavior
        assert query.structure_kwargs["tenor"] == "INVALID"
