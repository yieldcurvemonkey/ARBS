import pytest
import datetime
import pandas as pd


class TestEventContractPricer:
    def test_pricer_holds_data(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        data = pd.DataFrame({"price": [0.5, 0.6]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})
        assert len(pricer.data) == 2
        assert pricer.meta_data["ticker"] == "TEST"

    def test_latest_price(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        data = pd.DataFrame({"price": [0.5, 0.65]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={})
        assert pricer.latest_price() == pytest.approx(0.65)


class TestEventContractsMDP:
    def test_construction_kalshi(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        mdp = EventContractsMDP(source="KALSHI")
        assert mdp.source == "KALSHI"

    def test_construction_polymarket(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        mdp = EventContractsMDP(source="POLYMARKET")
        assert mdp.source == "POLYMARKET"

    def test_invalid_source(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP
        with pytest.raises(ValueError, match="source must be"):
            EventContractsMDP(source="INVALID")
