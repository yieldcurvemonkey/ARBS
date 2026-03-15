import pytest
from tests.conftest import MockPricer
import datetime


def _make_pricer(curve_name: str, base_rate: float) -> MockPricer:
    return MockPricer(curve_name=curve_name, as_of_date=datetime.date(2026, 3, 15), base_rate=base_rate)


class TestSpreadPricer:
    def test_holds_both_pricers(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("USD-SOFR-1D", 0.04)
        pb = _make_pricer("USD-FEDFUNDS", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"id": "test"})
        assert sp.pricer_a is pa
        assert sp.pricer_b is pb

    def test_meta_data(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("A", 0.04)
        pb = _make_pricer("B", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"id": "spread-test", "timestamp": "2026-03-15"})
        assert sp.meta_data["id"] == "spread-test"

    def test_spread_rate_delegates_to_legs(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("A", 0.04)
        pb = _make_pricer("B", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={})
        inst_a = pa.build_irswap(tenor="5Y")
        inst_b = pb.build_irswap(tenor="5Y")
        rate_a = pa.fair_rate(inst_a)
        rate_b = pb.fair_rate(inst_b)
        assert sp.pricer_a.fair_rate(inst_a) == rate_a
        assert sp.pricer_b.fair_rate(inst_b) == rate_b
