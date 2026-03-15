import pytest
import datetime
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestIRSwapSpreadsMDP:
    def test_construction(self):
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        mdp = IRSwapSpreadsMDP(source_a="MOCK_A", source_b="MOCK_B")
        assert mdp.source == "IRSWAP_SPREAD"

    def test_get_pricer_with_mock(self):
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        mdp = IRSwapSpreadsMDP(
            source_a="MOCK_A", source_b="MOCK_B",
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )
        result = mdp.get_pricer({
            "curve_a": "USD-SOFR-1D",
            "curve_b": "USD-OIS",
            "timestamp": datetime.date(2026, 3, 15),
        })
        assert isinstance(result, SpreadPricer)
        assert result.pricer_a.curve_name == "USD-SOFR-1D"
        assert result.pricer_b.curve_name == "USD-OIS"
