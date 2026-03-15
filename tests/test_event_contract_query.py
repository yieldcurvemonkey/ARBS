import pytest
import datetime
import pandas as pd


class TestEventContractEnums:
    def test_structure_members(self):
        from Query.EventContracts.EventContractStructure import EventContractStructure
        assert hasattr(EventContractStructure, "OUTRIGHT")
        assert hasattr(EventContractStructure, "SPREAD")

    def test_value_members(self):
        from Query.EventContracts.EventContractValue import EventContractValue
        assert hasattr(EventContractValue, "PRICE")
        assert hasattr(EventContractValue, "PROBABILITY")
        assert hasattr(EventContractValue, "VOLUME")
        assert hasattr(EventContractValue, "OPEN_INTEREST")


class TestEventContractQuery:
    def test_basic_construction(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue
        q = EventContractQuery(ticker="KXFED-26MAR19", value=EventContractValue.PRICE)
        assert q.product == "EVENT"
        assert q.ticker == "KXFED-26MAR19"

    def test_build_mdp_request(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue
        q = EventContractQuery(ticker="KXFED-26MAR19", value=EventContractValue.PRICE)
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        assert req["ticker"] == "KXFED-26MAR19"

    def test_col_name(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue
        q = EventContractQuery(ticker="KXFED-26MAR19", value=EventContractValue.PRICE)
        col = q.col_name()
        assert "KXFED" in col


class TestEventContractAdapter:
    def test_adapter_registered(self):
        from Query.Base.product_adapter import get_adapter
        import Query.EventContracts.adapter  # noqa: F401
        adapter_cls = get_adapter("EVENT")
        assert adapter_cls is not None

    def test_value_map_price(self):
        from Query.Base.product_adapter import get_adapter
        import Query.EventContracts.adapter  # noqa: F401
        from Query.EventContracts.EventContractValue import EventContractValue
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        data = pd.DataFrame({"price": [0.55, 0.60]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})
        adapter = get_adapter("EVENT")()
        val_map = adapter.build_value_map(pricer_or_curve=pricer, package=[], risk_weights=[])
        price = val_map.apply(EventContractValue.PRICE)
        assert price == pytest.approx(0.60)
