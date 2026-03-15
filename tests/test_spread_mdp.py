import pytest
import datetime
from tests.conftest import MockMDP


class TestSpreadMDP:
    def test_get_pricer_returns_spread_pricer(self):
        from MDP.Spreads.SpreadMDP import SpreadMDP
        from MDP.Spreads.SpreadPricer import SpreadPricer

        mdp_a = MockMDP(source="A", base_rate=0.04)
        mdp_b = MockMDP(source="B", base_rate=0.05)

        def splitter(request):
            ts = request["timestamp"]
            return (
                {"curve_name": request["curve_a"], "timestamp": ts},
                {"curve_name": request["curve_b"], "timestamp": ts},
            )

        spread_mdp = SpreadMDP(
            mdp_a=mdp_a,
            mdp_b=mdp_b,
            request_splitter=splitter,
            source="TEST-SPREAD",
        )

        result = spread_mdp.get_pricer({
            "curve_a": "USD-SOFR-1D",
            "curve_b": "USD-FEDFUNDS",
            "timestamp": datetime.date(2026, 3, 15),
        })

        assert isinstance(result, SpreadPricer)
        assert result.pricer_a.curve_name == "USD-SOFR-1D"
        assert result.pricer_b.curve_name == "USD-FEDFUNDS"

    def test_meta_data_includes_source(self):
        from MDP.Spreads.SpreadMDP import SpreadMDP

        mdp_a = MockMDP(source="A")
        mdp_b = MockMDP(source="B")

        def splitter(request):
            return (
                {"curve_name": "C1", "timestamp": request["timestamp"]},
                {"curve_name": "C2", "timestamp": request["timestamp"]},
            )

        spread_mdp = SpreadMDP(mdp_a=mdp_a, mdp_b=mdp_b, request_splitter=splitter, source="SRC")
        result = spread_mdp.get_pricer({"timestamp": datetime.date(2026, 1, 1)})
        assert "source" in result.meta_data
        assert result.meta_data["source"] == "SRC"
