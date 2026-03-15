"""
Integration test: full spread MDP flow through the backtester query pattern.
Uses MockMDP/MockPricer from conftest to avoid real market data dependencies.
"""
import pytest
import datetime
from tests.conftest import MockMDP, MockPricer
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestSpreadMDPIntegration:
    def test_full_flow_irswap_spread(self):
        """End-to-end: IRSwapSpreadsMDP -> SpreadQuery -> resolve_package -> build_value_map -> apply"""
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = IRSwapSpreadsMDP(
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )

        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        assert isinstance(pricer, SpreadPricer)

        package, weights = q.resolve_package(pricer_or_curve=pricer)
        assert len(package) == 1

        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)

        leg_a = val_map.apply(SpreadValue.LEG_A_RATE)
        leg_b = val_map.apply(SpreadValue.LEG_B_RATE)
        assert isinstance(leg_a, float)
        assert isinstance(leg_b, float)

    def test_full_flow_basis(self):
        """End-to-end: IRBasisSwapsMDP -> SpreadQuery -> value"""
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            product_key="IRBASIS",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread, float)

    def test_full_flow_cvx_adjustment(self):
        """End-to-end: STIRConvexityAdjustmentMDP -> SpreadQuery -> CVX_ADJ_EMPIRICAL"""
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.CVX_ADJ_EMPIRICAL,
            product_key="STIRCVX",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        cvx = val_map.apply(SpreadValue.CVX_ADJ_EMPIRICAL)
        assert isinstance(cvx, float)

    def test_curve_structure_spread(self):
        """Test 2Y/10Y spread-of-spread (CURVE structure)."""
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue
        from Query.Spreads.SpreadStructure import SpreadStructure

        mdp = IRSwapSpreadsMDP(
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )

        q = SpreadQuery(
            tenor="2Y/10Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.structure == SpreadStructure.CURVE

        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        assert len(package) == 2
        assert len(weights) == 2

        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)


class TestEventContractIntegration:
    def test_query_to_value_map(self):
        """End-to-end: EventContractQuery -> adapter -> value_map -> PRICE"""
        import pandas as pd
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue

        data = pd.DataFrame({"price": [0.55, 0.60, 0.65]}, index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})

        q = EventContractQuery(ticker="TEST", value=EventContractValue.PRICE)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        price = val_map.apply(EventContractValue.PRICE)
        assert price == pytest.approx(0.65)
