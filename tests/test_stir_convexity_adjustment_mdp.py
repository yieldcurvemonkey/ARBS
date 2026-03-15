# tests/test_stir_convexity_adjustment_mdp.py
import pytest
import datetime
import math
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestHW1FModel:
    def test_convexity_adjustment(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        a = 0.03
        sigma = 0.01
        T1 = 1.0
        T2 = 1.25
        result = hw1f_convexity_adjustment(a=a, sigma=sigma, T1=T1, T2=T2)
        expected = (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))
        assert abs(result - expected) < 1e-12

    def test_zero_mean_reversion_raises(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        with pytest.raises(ValueError):
            hw1f_convexity_adjustment(a=0.0, sigma=0.01, T1=1.0, T2=1.25)

    def test_convexity_increases_with_maturity(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment
        adj_short = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=0.25, T2=0.5)
        adj_long = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=5.0, T2=5.25)
        assert adj_long > adj_short


class TestSTIRConvexityAdjustmentMDP:
    def test_construction(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        assert mdp.source == "STIRCVX_EMPIRICAL"

    def test_get_pricer_returns_spread_pricer(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        result = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": datetime.date(2026, 3, 15)})
        assert isinstance(result, SpreadPricer)
