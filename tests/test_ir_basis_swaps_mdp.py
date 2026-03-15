import pytest
import datetime
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestIRBasisSwapsMDP:
    def test_construction(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP
        mdp = IRBasisSwapsMDP()
        assert mdp.source == "IRBASIS_BARCHART_STIRF-RL"

    def test_get_pricer_with_mock(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP
        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )
        result = mdp.get_pricer({"tenor": "5Y", "timestamp": datetime.date(2026, 3, 15)})
        assert isinstance(result, SpreadPricer)

    def test_default_curves(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP
        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )
        result = mdp.get_pricer({"timestamp": datetime.date(2026, 3, 15)})
        assert isinstance(result, SpreadPricer)
        assert result.pricer_a.curve_name == "USD-SOFR-1D-Q12STIRT"
        assert result.pricer_b.curve_name == "USD-FEDFUNDS"
