import datetime as dt

import QuantLib as ql
import pytest

from definitions.IRSwaptions import EXPIRY_LABELS, TAIL_LABELS
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP


@pytest.fixture(autouse=True)
def _restore_registries():
    """Put ``VOL_PROVIDERS`` / ``ENGINE_FACTORIES`` back after every test here.

    They are CLASS attributes, so ``mdp.ENGINE_FACTORIES[...] = fake`` mutates
    them for the whole session, not for one instance. Several tests below do
    exactly that, and one of them replaces ``ENGINE_FACTORIES["QL"]`` - the real
    ``ql.BachelierSwaptionEngine`` factory - with a local stub that returns a bare
    ``object()``. Every later test in the session then priced with that stub.

    It stayed invisible because pytest collects files alphabetically and every
    other swaption test file sorts before this one. It surfaced the moment
    ``test_citivelo_swaption_provider.py`` asserted the engine's TYPE and the two
    files were named in the other order on a command line. A test that only
    passes because of collection order is not passing for a reason.
    """
    providers = dict(IRSwaptionMDP.VOL_PROVIDERS)
    engines = dict(IRSwaptionMDP.ENGINE_FACTORIES)
    try:
        yield
    finally:
        IRSwaptionMDP.VOL_PROVIDERS.clear()
        IRSwaptionMDP.VOL_PROVIDERS.update(providers)
        IRSwaptionMDP.ENGINE_FACTORIES.clear()
        IRSwaptionMDP.ENGINE_FACTORIES.update(engines)


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
    monkeypatch.setitem(IRSwaptionMDP.VOL_PROVIDERS, "TESTPROV", _provider)
    monkeypatch.setitem(IRSwaptionMDP.ENGINE_FACTORIES, "TESTENG", _engine)

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
    monkeypatch.setitem(IRSwaptionMDP.VOL_PROVIDERS, "PARTIALPROV", _provider)
    monkeypatch.setitem(IRSwaptionMDP.ENGINE_FACTORIES, "PARTIALENG", _engine)

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


def test_constructor_data_dir_flows_to_monkeycube_and_partitions_cache(monkeypatch):
    mdp = IRSwaptionMDP(
        source="MONKEYCUBE-QL",
        curve_source="ERIS_EOD_LIVE-QL_BASIC",
        data_dir=r"C:\cube\one",
    )

    provider_calls = []

    def _bulk_curve(req):
        ts = req["timestamps"]
        return {d: _FakeCurve(d) for d in ts}

    def _provider(*, curve_name, dates, surface_type, **kwargs):
        _ = curve_name, surface_type
        provider_calls.append(dict(kwargs))
        return {d: _make_vol_handle(d) for d in dates}

    def _engine(**kwargs):
        _ = kwargs
        return object()

    monkeypatch.setattr(mdp._curve_mdp, "bulk_get_data", _bulk_curve)
    monkeypatch.setitem(IRSwaptionMDP.VOL_PROVIDERS, "MONKEYCUBE", _provider)
    monkeypatch.setitem(IRSwaptionMDP.ENGINE_FACTORIES, "QL", _engine)

    d = dt.date(2026, 3, 6)
    base_req = {
        "endpoint": "swaption_snapshot",
        "curve_name": "USD-SOFR-1D",
        "timestamp": d,
    }

    ctx1 = mdp.get_data(dict(base_req))
    assert provider_calls[-1]["data_dir"] == r"C:\cube\one"
    assert ctx1.metadata["data_dir"] == r"C:\cube\one"

    _ = mdp.get_data(dict(base_req))
    assert len(provider_calls) == 1

    ctx2 = mdp.get_data({**base_req, "data_dir": r"C:\cube\two"})
    assert provider_calls[-1]["data_dir"] == r"C:\cube\two"
    assert ctx2.metadata["data_dir"] == r"C:\cube\two"
    assert len(provider_calls) == 2

    _ = mdp.get_data({**base_req, "data_dir": r"C:\cube\two"})
    assert len(provider_calls) == 2


def test_enhanced_provider_uses_option_dates_for_gsquant_atm_lookup(monkeypatch):
    import MDP.IRSwaptions.GSQUANT.ql.grid as gsquant_grid
    import MDP.IRSwaptions.GSQUANT_MC_ENHANCED.provider as enhanced_provider
    import MDP.IRSwaptions.MONKEYCUBE.provider as monkeycube_provider

    d = dt.date(2026, 3, 6)

    class _RecordingHandle:
        def __init__(self):
            self.option_date_calls: list[ql.Period] = []
            self.volatility_calls: list[tuple[ql.Date, ql.Period, float, bool]] = []

        def optionDateFromTenor(self, tenor: ql.Period) -> ql.Date:
            self.option_date_calls.append(tenor)
            return ql.Date(d.day, d.month, d.year)

        def volatility(
            self,
            option_date: ql.Date,
            swap_tenor: ql.Period,
            strike: float,
            extrapolate: bool = False,
        ) -> float:
            assert isinstance(option_date, ql.Date)
            assert isinstance(swap_tenor, ql.Period)
            self.volatility_calls.append((option_date, swap_tenor, strike, extrapolate))
            return 0.01

    class _DummyEnhancedCube:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    handle = _RecordingHandle()
    cube = object()

    monkeypatch.setattr(
        gsquant_grid,
        "get_atmf_grid",
        lambda curve, dates, surface_type: {d: handle},
    )
    monkeypatch.setattr(
        monkeycube_provider,
        "get_sabr_vol_surfaces",
        lambda **kwargs: {d: object()},
    )
    monkeypatch.setattr(
        monkeycube_provider,
        "get_cached_cube",
        lambda curve_name, as_of: cube if curve_name == "USD-SOFR-1D" and as_of == d else None,
    )
    monkeypatch.setattr(enhanced_provider, "EnhancedSabrVolCube", _DummyEnhancedCube)

    enhanced_provider.clear_enhanced_cube_cache()
    out = enhanced_provider.get_enhanced_vol_surfaces(
        curve_name="USD-SOFR-1D",
        dates=[d],
        surface_type="atmf_normal",
        data_dir=r"C:\cube\one",
    )

    assert out[d] is handle
    assert len(handle.option_date_calls) == len(EXPIRY_LABELS)
    assert len(handle.volatility_calls) == len(EXPIRY_LABELS) * len(TAIL_LABELS)
    assert all(call[2] == 0.0 for call in handle.volatility_calls)
    assert all(call[3] is True for call in handle.volatility_calls)
    assert enhanced_provider.get_cached_enhanced_cube("USD-SOFR-1D", d) is not None
