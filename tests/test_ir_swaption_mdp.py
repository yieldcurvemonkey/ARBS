import datetime as dt

import QuantLib as ql
import pytest

from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP


def _make_vol_handle(as_of: dt.date) -> ql.SwaptionVolatilityStructureHandle:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    ql.Settings.instance().evaluationDate = ql.Date(as_of.day, as_of.month, as_of.year)
    expiries = ql.PeriodVector()
    expiries.append(ql.Period("1Y"))
    expiries.append(ql.Period("2Y"))
    tails = ql.PeriodVector()
    tails.append(ql.Period("5Y"))
    tails.append(ql.Period("10Y"))
    vols = ql.Matrix(2, 2)
    vols[0][0] = 0.0080
    vols[0][1] = 0.0082
    vols[1][0] = 0.0081
    vols[1][1] = 0.0083
    surf = ql.SwaptionVolatilityMatrix(
        cal,
        ql.ModifiedFollowing,
        expiries,
        tails,
        vols,
        ql.Actual365Fixed(),
        False,
        ql.Normal,
    )
    return ql.SwaptionVolatilityStructureHandle(surf)


class _FakeCurve:
    def __init__(self, as_of: dt.date):
        ql_date = ql.Date(as_of.day, as_of.month, as_of.year)
        ql.Settings.instance().evaluationDate = ql_date
        curve = ql.FlatForward(ql_date, 0.04, ql.Actual365Fixed())
        self._handle = ql.YieldTermStructureHandle(curve)
        self._index = ql.Sofr(self._handle)

    def handle(self):
        return self._handle

    def index(self):
        return self._index

    @staticmethod
    def daycounter():
        return ql.Actual365Fixed()


def test_request_validation_errors():
    mdp = IRSwaptionMDP(source="GSQUANT-QL")
    with pytest.raises(ValueError):
        mdp.get_data({"endpoint": "swaption_snapshot", "timestamp": dt.date(2026, 3, 5)})
    with pytest.raises(ValueError):
        mdp.bulk_get_data({"endpoint": "swaption_snapshot", "curve_name": "USD-SOFR-1D"})
    with pytest.raises(NotImplementedError):
        mdp.get_data({"endpoint": "unknown", "curve_name": "USD-SOFR-1D", "timestamp": dt.date(2026, 3, 5)})


def test_single_and_bulk_shapes_provider_engine_dispatch_and_cache(monkeypatch):
    mdp = IRSwaptionMDP(source="GSQUANT-QL")

    curve_calls = {"n": 0}
    provider_calls = {"n": 0}
    engine_calls = {"n": 0}

    def _bulk_curve(req):
        curve_calls["n"] += 1
        ts = req["timestamps"]
        return {d: _FakeCurve(d) for d in ts}

    def _provider(*, curve_name, dates, surface_type, **kwargs):
        _ = curve_name, surface_type, kwargs
        provider_calls["n"] += 1
        return {d: _make_vol_handle(d) for d in dates}

    def _engine(**kwargs):
        _ = kwargs
        engine_calls["n"] += 1
        return object()

    monkeypatch.setattr(mdp._curve_mdp, "bulk_get_data", _bulk_curve)
    mdp.VOL_PROVIDERS["TESTPROV"] = _provider
    mdp.ENGINE_FACTORIES["TESTENG"] = _engine

    d1 = dt.date(2026, 3, 4)
    d2 = dt.date(2026, 3, 5)

    single = mdp.get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": "USD-SOFR-1D",
            "timestamp": d1,
            "surface_type": "atmf_normal",
            "source": "TESTPROV-TESTENG",
        }
    )
    assert single.as_of_date == d1
    assert single.provider == "TESTPROV"
    assert single.engine == "TESTENG"

    bulk = mdp.bulk_get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "surface_type": "atmf_normal",
            "source": "TESTPROV-TESTENG",
        }
    )
    assert set(bulk.keys()) == {d1, d2}
    assert all(ctx.curve_name == "USD-SOFR-1D" for ctx in bulk.values())

    provider_before = provider_calls["n"]
    _ = mdp.get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": "USD-SOFR-1D",
            "timestamp": d1,
            "surface_type": "atmf_normal",
            "source": "TESTPROV-TESTENG",
        }
    )
    assert provider_calls["n"] == provider_before

    _ = mdp.get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": "USD-SOFR-1D",
            "timestamp": d1,
            "surface_type": "atmf_normal",
            "ignore_cache": True,
            "source": "TESTPROV-TESTENG",
        }
    )
    assert provider_calls["n"] > provider_before
    assert curve_calls["n"] >= 2
    assert engine_calls["n"] >= 2


def test_bulk_get_data_skips_single_date_curve_failures(monkeypatch):
    mdp = IRSwaptionMDP(source="GSQUANT-QL")

    d1 = dt.date(2026, 2, 13)
    d2 = dt.date(2026, 2, 16)

    def _bulk_curve(req):
        raise RuntimeError("synthetic bulk curve failure")

    def _single_curve(req):
        if req["timestamp"] == d2:
            raise AssertionError("synthetic holiday failure")
        return _FakeCurve(req["timestamp"])

    def _provider(*, curve_name, dates, surface_type, **kwargs):
        _ = curve_name, surface_type, kwargs
        if len(dates) > 1 and d2 in dates:
            raise ValueError("synthetic bulk vol failure")
        return {d: _make_vol_handle(d) for d in dates if d != d2}

    def _engine(**kwargs):
        _ = kwargs
        return object()

    monkeypatch.setattr(mdp._curve_mdp, "bulk_get_data", _bulk_curve)
    monkeypatch.setattr(mdp._curve_mdp, "get_data", _single_curve)
    mdp.VOL_PROVIDERS["PARTIALPROV"] = _provider
    mdp.ENGINE_FACTORIES["PARTIALENG"] = _engine

    out = mdp.bulk_get_data(
        {
            "endpoint": "swaption_snapshot",
            "curve_name": "USD-SOFR-1D",
            "timestamps": [d1, d2],
            "surface_type": "atmf_normal",
            "source": "PARTIALPROV-PARTIALENG",
        }
    )

    assert set(out.keys()) == {d1}
