import datetime

import pandas as pd
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionMDP,
    QuikVolProductID,
    QuikVolValueType,
)


class _DummyQS:
    def __init__(self):
        self.pids = None
        self.start = None
        self.end = None
        self.queries = None
        self.timeseries_df = pd.DataFrame({"v": [1.23]}, index=pd.DatetimeIndex([pd.Timestamp("2026-01-02")]))

    def fetch_latest_atm_term_structures(self, qv_pids):
        self.pids = qv_pids
        return {"SR3_atm_vol_term_structure": ("OK", {"SR3H6": 45.2})}

    def fetch_quikvol_timeseries(self, start_date, end_date, queries):
        self.start = start_date
        self.end = end_date
        self.queries = queries
        return self.timeseries_df


def test_qs_atm_term_structure_fetches_sr3(monkeypatch):
    mdp = STIRFutureOptionMDP(source="QUIKSTRIKE_STIRFO-QL")
    dummy = _DummyQS()
    monkeypatch.setattr(mdp, "_quikstrike_client", lambda force_refresh=False: dummy)

    out = mdp.get_data({"endpoint": "qs_atm_term_structure"})
    assert dummy.pids == [QuikVolProductID.SR3]
    assert "qs_atm_term_structure" in out
    assert out["qs_atm_term_structure"][0]["SR3_atm_vol_term_structure"][1]["SR3H6"] == 45.2


def test_qs_timeseries_query_translation_and_root_enforcement(monkeypatch):
    mdp = STIRFutureOptionMDP(source="QUIKSTRIKE_STIRFO-QL")
    dummy = _DummyQS()
    monkeypatch.setattr(mdp, "_quikstrike_client", lambda force_refresh=False: dummy)

    out = mdp.get_data(
        {
            "endpoint": "qs_timeseries",
            "start": datetime.date(2026, 1, 2),
            "end": datetime.date(2026, 1, 10),
            "queries": [
                {"globex_symbol": "SQZ26", "qv_value_type": "ABPV"},
                {"globex_symbol": "SFRH27", "qv_value_type": "Call", "delta": 25, "option_type": "Call"},
            ],
        }
    )

    assert out["qs_timeseries"][0].equals(dummy.timeseries_df)
    assert dummy.queries[0].globex_symbol == "SR3Z26"
    assert dummy.queries[0].qv_value_type == QuikVolValueType.ABPV
    assert dummy.queries[1].globex_symbol == "SR3H27"
    assert dummy.queries[1].qv_value_type == QuikVolValueType.Call
    assert dummy.queries[1].delta == 25
    assert dummy.queries[1].option_type == "Call"

    with pytest.raises(ValueError):
        mdp.get_data(
            {
                "endpoint": "qs_timeseries",
                "start": datetime.date(2026, 1, 2),
                "end": datetime.date(2026, 1, 10),
                "queries": [{"globex_symbol": "TYZ26", "qv_value_type": "ABPV"}],
            }
        )


def test_strict_source_split_rejections():
    mdp_barchart = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    with pytest.raises(NotImplementedError):
        mdp_barchart.get_data({"endpoint": "qs_atm_term_structure"})

    mdp_qs = STIRFutureOptionMDP(source="QUIKSTRIKE_STIRFO-QL")
    with pytest.raises(NotImplementedError):
        mdp_qs.get_data({"endpoint": "option_snapshot", "symbols": ["SR3Z30|9700C"]})
