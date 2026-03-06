import datetime as dt

import pandas as pd

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMarketContext
from Query.IRSwaptions.IRSwaptionQuery import IRSwaptionQuery, IRSwaptionQueryWrapper
from TB.IRSwaptionsTB import IRSwaptionsTB


class _FakeMDP:
    def __init__(self):
        self.source = "FAKE"
        self.calls = 0

    def bulk_get_data(self, request):
        self.calls += 1
        out = {}
        for d in request["timestamps"]:
            out[d] = IRSwaptionMarketContext(
                curve_name=request["curve_name"],
                as_of_date=d,
                curve=None,
                curve_handle=None,
                swap_index=None,
                vol_handle=None,
                pricing_engine=None,
                provider="FAKE",
                engine="QL",
                surface_type="atmf_normal",
                source="FAKE-QL",
                metadata={},
            )
        return out


def test_tb_bulk_grouping_cache_and_wrapper_columns(monkeypatch):
    mdp = _FakeMDP()
    tb = IRSwaptionsTB(mdp=mdp, show_tqdm=False)

    monkeypatch.setattr(
        "TB.IRSwaptionsTB._build_row_for_query",
        lambda context, q, ref_dt: (ref_dt, q.col_name(), 1.0 if q.name == "A" else 2.0),
    )

    q1 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="5Y", name="A")
    q2 = IRSwaptionQuery(curve="USD-SOFR-1D", expiry="1Y", tail="10Y", name="B")
    w = IRSwaptionQueryWrapper([q1, q2], "A_plus_B")

    start = dt.date(2026, 3, 2)
    end = dt.date(2026, 3, 3)

    out1 = tb.get_timeseries(start, end, [q1, q2, w], ignore_cache=False)
    assert not out1.empty
    assert "A" in out1.columns
    assert "B" in out1.columns
    assert "A_plus_B" in out1.columns
    assert (out1["A_plus_B"] == 3.0).all()

    calls_after_first = mdp.calls
    out2 = tb.get_timeseries(start, end, [q1, q2, w], ignore_cache=False)
    assert not out2.empty
    assert mdp.calls == calls_after_first

    _ = tb.get_timeseries(start, end, [q1, q2], ignore_cache=True)
    assert mdp.calls > calls_after_first

