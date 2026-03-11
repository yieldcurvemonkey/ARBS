import datetime as dt

import QuantLib as ql

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.backends.quantlib.ql_pricer import build_ql_irswap


def test_bulk_get_data_falls_back_one_by_one_for_eris_ql(monkeypatch):
    mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-QL_BASIC")
    d1 = dt.date(2026, 2, 13)
    d2 = dt.date(2026, 2, 16)
    seen = []

    def _stub_get_data(request):
        seen.append((request["curve_name"], request["timestamp"], request.get("ignore_cache")))
        if request["timestamp"] == d2:
            raise AssertionError("synthetic holiday failure")
        return {"curve": request["timestamp"]}

    monkeypatch.setattr(mdp, "get_data", _stub_get_data)

    out = mdp.bulk_get_data(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "ignore_cache": True,
        }
    )

    assert seen == [
        ("USD-SOFR-1D", d1, True),
        ("USD-SOFR-1D", d2, True),
    ]
    assert out == {d1: {"curve": d1}}


def test_build_ql_irswap_explicit_date_ois_uses_forward_schedule():
    as_of = dt.date(2026, 3, 3)
    ql_date = ql.Date(as_of.day, as_of.month, as_of.year)
    ql.Settings.instance().evaluationDate = ql_date
    curve_handle = ql.YieldTermStructureHandle(ql.FlatForward(ql_date, 0.04, ql.Actual360()))

    swap = build_ql_irswap(
        curve="USD-SOFR-1D",
        curve_handle=curve_handle,
        effective_date=dt.date(2026, 4, 3),
        maturity_date=dt.date(2033, 4, 4),
        fixed_rate=-0.0,
        notional=1.0,
    )

    schedule = swap.fixedSchedule()
    assert schedule[0] == ql.Date(3, 4, 2026)
    assert schedule[1] == ql.Date(5, 4, 2027)
    assert swap.startDate() == ql.Date(3, 4, 2026)
    assert swap.maturityDate() == ql.Date(4, 4, 2033)
    assert swap.fairRate() > 0.0
