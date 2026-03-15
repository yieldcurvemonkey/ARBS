import pytest
import datetime
from tests.conftest import MockPricer
from MDP.Spreads.SpreadPricer import SpreadPricer


def _make_spread_pricer(rate_a=0.04, rate_b=0.05):
    pa = MockPricer("USD-SOFR-1D", datetime.date(2026, 3, 15), base_rate=rate_a)
    pb = MockPricer("USD-FEDFUNDS", datetime.date(2026, 3, 15), base_rate=rate_b)
    return SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"source": "TEST"})


class TestSpreadAdapter:
    def test_adapter_registered(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        adapter_cls = get_adapter("IRSPREAD")
        assert adapter_cls is not None

    def test_build_structure_map_outright(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        assert len(package) == 1
        assert len(weights) == 1

    def test_build_value_map_spread_bps(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")

        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)

    def test_leg_a_rate(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)

        leg_a = val_map.apply(SpreadValue.LEG_A_RATE)
        assert isinstance(leg_a, float)
        assert leg_a > 0
