import pytest
import datetime


class TestSpreadEnums:
    def test_spread_structure_members(self):
        from Query.Spreads.SpreadStructure import SpreadStructure
        assert hasattr(SpreadStructure, "OUTRIGHT")
        assert hasattr(SpreadStructure, "CURVE")
        assert hasattr(SpreadStructure, "FLY")

    def test_spread_value_members(self):
        from Query.Spreads.SpreadValue import SpreadValue
        assert hasattr(SpreadValue, "SPREAD_BPS")
        assert hasattr(SpreadValue, "SPREAD_RATE")
        assert hasattr(SpreadValue, "LEG_A_RATE")
        assert hasattr(SpreadValue, "LEG_B_RATE")
        assert hasattr(SpreadValue, "PV01")
        assert hasattr(SpreadValue, "NPV")
        assert hasattr(SpreadValue, "CVX_ADJ_EMPIRICAL")
        assert hasattr(SpreadValue, "CVX_ADJ_HW1F")


class TestSpreadQuery:
    def test_basic_construction(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.product == "IRSPREAD"
        assert q.structure == SpreadStructure.OUTRIGHT
        assert q.tenor == "5Y"

    def test_curve_structure_from_tenor(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="2Y/10Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.structure == SpreadStructure.CURVE

    def test_build_mdp_request(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        assert "curve_a" in req
        assert "curve_b" in req
        assert req["curve_a"] == "USD-SOFR-1D"
        assert req["curve_b"] == "USD-FEDFUNDS"
        assert req["timestamp"] == now.date()

    def test_build_mdp_request_accepts_live_literal(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )

        req = q.build_mdp_request("live")

        assert req["timestamp"] == "live"
        assert req["curve_a"] == "USD-SOFR-1D"
        assert req["curve_b"] == "USD-FEDFUNDS"

    def test_build_mdp_request_accepts_date_literal(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )

        as_of = datetime.date(2026, 3, 15)
        req = q.build_mdp_request(as_of)

        assert req["timestamp"] == as_of

    def test_col_name(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        col = q.col_name()
        assert "5Y" in col
        assert "SPREAD_BPS" in col
