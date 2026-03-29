import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.interpolate import make_interp_spline

from Query.Base.query_resolution import resolve_query
import Query.FixedRateBonds.FixedRateBondValue as frb_value_module
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds import carry_roll as carry_roll_module


@dataclass
class _BondInstrument:
    cusip: str
    issue_date: dt.date
    maturity_date: dt.date
    cpn: float
    notional: float


class _CarryRollBondPricer:
    def __init__(self, cusip: str, *, as_of: dt.date, ttm: float, ytm: float, dirty_price: float, mdur: float, coupon: float = 5.0):
        self._cusip = cusip
        self._as_of = as_of
        self._ttm = float(ttm)
        self._ytm = float(ytm)
        self._dirty_price = float(dirty_price)
        self._mdur = float(mdur)
        self._coupon = float(coupon)
        self._meta = {
            "cusip": cusip,
            "ttm": float(ttm),
            "coupon": float(coupon),
            "timestamp": as_of.isoformat(),
        }

    def id(self) -> str:
        return "USTS"

    def reference_date(self) -> dt.date:
        return self._as_of

    def meta(self):
        return dict(self._meta)

    def issue_date(self) -> dt.date:
        return self._as_of - dt.timedelta(days=365)

    def maturity_date(self) -> dt.date:
        return self._as_of + dt.timedelta(days=int(round(self._ttm * 365)))

    def coupon(self) -> float:
        return self._coupon

    def ytm(self) -> float:
        return self._ytm

    def clean_price(self) -> float:
        return self._dirty_price - 0.25

    def dirty_price(self, notional=None) -> float:
        return self._dirty_price

    def mod_duration(self) -> float:
        return self._mdur

    def pv01(self, notional=None) -> float:
        effective_notional = 1_000_000.0 if notional is None else float(notional)
        return effective_notional * 0.0001

    def npv(self, notional=None) -> float:
        effective_notional = 1_000_000.0 if notional is None else float(notional)
        return effective_notional * self.clean_price() / 100.0

    def convexity(self) -> float:
        return 1.0

    def time_to_maturity(self) -> float:
        return self._ttm

    def calendar_advance(self, dt1: dt.date, tenor: str) -> dt.date:
        day_map = {"1M": 30, "2M": 60, "3M": 90, "6M": 180}
        return dt1 + dt.timedelta(days=day_map[str(tenor).upper()])

    def build_pricable(
        self,
        *,
        cusip: str,
        issue_date: dt.date,
        maturity_date: dt.date,
        cpn: float,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> _BondInstrument:
        resolved_notional = notional
        if resolved_notional is None:
            if bpv is not None:
                resolved_notional = float(bpv) / self.pv01(1.0)
            else:
                resolved_notional = 1_000_000.0

        return _BondInstrument(
            cusip=cusip,
            issue_date=issue_date,
            maturity_date=maturity_date,
            cpn=float(cpn),
            notional=float(resolved_notional),
        )

    def notional(self, instrument: _BondInstrument) -> float:
        return float(instrument.notional)


def _make_pricers(as_of: dt.date) -> dict[str, _CarryRollBondPricer]:
    points = [
        ("C2", 2.0, 2.0, 100.0, 5.0),
        ("C3", 3.0, 2.5, 100.0, 5.0),
        ("C4", 4.0, 3.0, 100.0, 5.0),
        ("C5", 5.0, 3.5, 100.0, 5.0),
    ]
    return {
        cusip: _CarryRollBondPricer(cusip, as_of=as_of, ttm=ttm, ytm=ytm, dirty_price=dirty, mdur=mdur)
        for cusip, ttm, ytm, dirty, mdur in points
    }


def _expected_carry_bps(days: int) -> float:
    coupon_accrual = 5.0 * (days / 365.0)
    financing_cost = 100.0 * 0.05 * (days / 360.0)
    dv01 = 5.0 * 100.0 / 10_000.0
    return (coupon_accrual - financing_cost) / dv01


def test_build_mdp_request_expands_universe_for_carry_roll(monkeypatch) -> None:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    ref_df = pd.DataFrame(
        [
            {"cusip": "C2", "ttm": 2.0},
            {"cusip": "C3", "ttm": 3.0},
            {"cusip": "C4", "ttm": 4.0},
            {"cusip": "C5", "ttm": 5.0},
        ]
    )

    monkeypatch.setattr(FixedRateBondsMDP, "get_bond_reference_data", lambda self, as_of_date: ref_df.copy())

    query = FixedRateBondQuery(
        cusip="CT10",
        value=FixedRateBondValue.CARRY_BPS_RUNNING,
        value_kwargs={"min_ttm": 1.0},
    )

    request = query.build_mdp_request(dt.datetime(2026, 3, 20, 12, 0))

    assert request["timestamp"] == dt.date(2026, 3, 20)
    assert request["cusips"] == ["C2", "C3", "C4", "C5"]


def test_load_us_treasury_gc_fixing_pct_prefers_sofr_then_falls_back_to_fedfunds(monkeypatch) -> None:
    calls: list[tuple[dt.date, str]] = []

    def _fake_fetch_fixings(*, as_of_date, curve_name):
        calls.append((as_of_date, curve_name))
        if curve_name == "USD-SOFR-1D":
            if as_of_date <= dt.date(2017, 12, 31):
                return {}
            return {
                dt.date(2026, 3, 18): 0.049,
                dt.date(2026, 3, 19): 0.051,
            }
        if curve_name == "USD-FEDFUNDS":
            return {
                dt.date(2017, 12, 28): 0.0125,
                dt.date(2017, 12, 29): 0.0130,
            }
        raise AssertionError(f"unexpected curve {curve_name}")

    monkeypatch.setattr("MDP.IRSwaps.fixings_cache.fixings_cache._fetch_fixings", _fake_fetch_fixings)

    sofr_first = carry_roll_module.load_us_treasury_gc_fixing_pct(dt.date(2026, 3, 20))
    fedfunds_fallback = carry_roll_module.load_us_treasury_gc_fixing_pct(dt.date(2018, 1, 2))

    assert sofr_first == pytest.approx(5.1)
    assert fedfunds_fallback == pytest.approx(1.3)
    assert calls == [
        (dt.date(2026, 3, 20), "USD-SOFR-1D"),
        (dt.date(2018, 1, 2), "USD-SOFR-1D"),
        (dt.date(2018, 1, 2), "USD-FEDFUNDS"),
    ]


def test_build_mdp_request_filters_to_off_runs_and_requested_legs(monkeypatch) -> None:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    ref_df = pd.DataFrame(
        [
            {"cusip": "RUN0", "ttm": 2.0, "rank": 0},
            {"cusip": "RUN1", "ttm": 2.5, "rank": 1},
            {"cusip": "RUN2", "ttm": 3.0, "rank": 2},
            {"cusip": "OLD3", "ttm": 3.5, "rank": 3},
            {"cusip": "OLD4", "ttm": 4.0, "rank": 4},
            {"cusip": "ACT10", "ttm": 10.0, "rank": 0},
        ]
    )

    monkeypatch.setattr(FixedRateBondsMDP, "get_bond_reference_data", lambda self, as_of_date: ref_df.copy())
    monkeypatch.setattr(
        FixedRateBondQuery,
        "resolve_query",
        lambda self, ref_dt, pricer_or_curve: SimpleNamespace(cusip="ACT10"),
    )

    query = FixedRateBondQuery(
        cusip="CT10",
        value=FixedRateBondValue.ROLL_BPS_RUNNING,
        value_kwargs={"min_ttm": 1.0},
    )

    request = query.build_mdp_request(dt.date(2026, 3, 20))

    assert request["cusips"] == ["OLD3", "OLD4", "ACT10"]


def test_resolve_package_picks_requested_outright_from_expanded_universe() -> None:
    as_of = dt.date(2026, 3, 20)
    pricers = _make_pricers(as_of)
    query = FixedRateBondQuery(cusip="C4", value=FixedRateBondValue.CARRY_BPS_RUNNING, structure_kwargs={"bpv": 10_000})

    resolved = resolve_query(query, timestamp=dt.datetime(2026, 3, 20, 12, 0), pricer_or_curve=pricers)
    package, risk_weights = resolved.resolve_package(pricer_or_curve=pricers)

    assert resolved.cusip == "C4"
    assert [leg.cusip for leg in package] == ["C4"]
    assert risk_weights == [1.0]


def test_carry_roll_value_map_supports_horizons_and_3m_alias(monkeypatch) -> None:
    carry_roll_module.clear_roll_spline_cache()
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    as_of = dt.date(2026, 3, 20)
    pricers = _make_pricers(as_of)
    query = FixedRateBondQuery(cusip="C5", value=FixedRateBondValue.CARRY_BPS_RUNNING, structure_kwargs={"bpv": 10_000})

    resolved = resolve_query(query, timestamp=dt.datetime(2026, 3, 20, 12, 0), pricer_or_curve=pricers)
    package, risk_weights = resolved.resolve_package(pricer_or_curve=pricers)
    vmap = resolved.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=risk_weights)

    assert vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING) == pytest.approx(vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="3M"))
    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING) == pytest.approx(vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="3M"))
    assert vmap.apply(FixedRateBondValue.CARRY_AND_ROLL_BPS_RUNNING) == pytest.approx(
        vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="3M")
        + vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="3M")
    )

    assert vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="1M") == pytest.approx(_expected_carry_bps(30))
    assert vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="2m") == pytest.approx(_expected_carry_bps(60))
    assert vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="6M") == pytest.approx(_expected_carry_bps(180))

    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="1M") == pytest.approx(4.1666666667)
    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="2M") == pytest.approx(8.3333333333)
    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="3M") == pytest.approx(12.5)
    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="6M") == pytest.approx(25.0)


def test_curve_carry_roll_aggregates_by_risk_weight(monkeypatch) -> None:
    carry_roll_module.clear_roll_spline_cache()
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    as_of = dt.date(2026, 3, 20)
    pricers = _make_pricers(as_of)
    query = FixedRateBondQuery(
        cusip="C4/C5",
        value=FixedRateBondValue.CARRY_BPS_RUNNING,
        structure_kwargs={"bpv": 10_000},
    )

    resolved = resolve_query(query, timestamp=dt.datetime(2026, 3, 20, 12, 0), pricer_or_curve=pricers)
    package, risk_weights = resolved.resolve_package(pricer_or_curve=pricers)
    vmap = resolved.build_value_map(pricer_or_curve=pricers, package=package, risk_weights=risk_weights)

    expected = (-1.0 * _expected_carry_bps(90)) + (1.0 * _expected_carry_bps(90))
    assert [leg.cusip for leg in package] == ["C4", "C5"]
    assert risk_weights == [-1.0, 1.0]
    assert vmap.apply(FixedRateBondValue.CARRY_BPS_RUNNING, horizon="3M") == pytest.approx(expected)


def test_roll_value_expands_universe_when_initial_handle_is_too_narrow(monkeypatch) -> None:
    carry_roll_module.clear_roll_spline_cache()
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    as_of = dt.date(2026, 3, 20)
    full_pricers = _make_pricers(as_of)
    narrow_pricers = {"C5": full_pricers["C5"]}

    monkeypatch.setattr(
        frb_value_module,
        "expand_pricer_universe_for_carry_roll",
        lambda *, pricers, as_of_date, min_ttm: full_pricers,
    )

    query = FixedRateBondQuery(cusip="C5", value=FixedRateBondValue.CLEAN_PRICE, structure_kwargs={"bpv": 10_000})
    resolved = resolve_query(query, timestamp=dt.datetime(2026, 3, 20, 12, 0), pricer_or_curve=narrow_pricers)
    package, risk_weights = resolved.resolve_package(pricer_or_curve=narrow_pricers)
    vmap = resolved.build_value_map(pricer_or_curve=narrow_pricers, package=package, risk_weights=risk_weights)

    assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="3M") == pytest.approx(12.5)


def test_roll_spline_is_cached_by_date(monkeypatch, tmp_path) -> None:
    import Caching.supabase_engine as supabase_engine

    monkeypatch.setenv("ARBS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(carry_roll_module, "_ROLL_SPLINE_DISK_CACHE", None)
    monkeypatch.setattr(supabase_engine, "SUPABASE_ENABLED", False)
    carry_roll_module.clear_roll_spline_cache(include_persistent=True)

    class _CountingInterpolator:
        calls = 0

        def __init__(self, x, y):
            _CountingInterpolator.calls += 1
            self._x = pd.Series(x, dtype=float).to_numpy(dtype=float)
            self._y = pd.Series(y, dtype=float).to_numpy(dtype=float)

        def b_spline1_interpolation(self, k, return_func=True):
            assert return_func is True
            return make_interp_spline(self._x, self._y, k=k)

    monkeypatch.setattr(carry_roll_module, "GeneralCurveInterpolator", _CountingInterpolator)
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    as_of = dt.date(2026, 3, 20)
    full_pricers = _make_pricers(as_of)
    narrow_pricers = {"C5": full_pricers["C5"]}

    carry_roll_module.compute_carry_roll_frame(pricers=full_pricers, as_of_date=as_of)
    carry_roll_module.compute_carry_roll_frame(pricers=narrow_pricers, as_of_date=as_of)

    assert _CountingInterpolator.calls == 1


def test_roll_value_reuses_cached_spline_across_different_narrow_bonds(monkeypatch, tmp_path) -> None:
    import Caching.supabase_engine as supabase_engine

    monkeypatch.setenv("ARBS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(carry_roll_module, "_ROLL_SPLINE_DISK_CACHE", None)
    monkeypatch.setattr(supabase_engine, "SUPABASE_ENABLED", False)
    carry_roll_module.clear_roll_spline_cache(include_persistent=True)
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    expansion_calls = {"count": 0}

    class _CountingInterpolator:
        calls = 0

        def __init__(self, x, y):
            _CountingInterpolator.calls += 1
            self._x = pd.Series(x, dtype=float).to_numpy(dtype=float)
            self._y = pd.Series(y, dtype=float).to_numpy(dtype=float)

        def b_spline1_interpolation(self, k, return_func=True):
            assert return_func is True
            return make_interp_spline(self._x, self._y, k=k)

    monkeypatch.setattr(carry_roll_module, "GeneralCurveInterpolator", _CountingInterpolator)

    as_of = dt.date(2026, 3, 20)
    full_pricers = _make_pricers(as_of)

    def _expand(*, pricers, as_of_date, min_ttm):
        expansion_calls["count"] += 1
        return full_pricers

    monkeypatch.setattr(frb_value_module, "expand_pricer_universe_for_carry_roll", _expand)

    for cusip in ("C5", "C2"):
        narrow_pricers = {cusip: full_pricers[cusip]}
        query = FixedRateBondQuery(cusip=cusip, value=FixedRateBondValue.CLEAN_PRICE, structure_kwargs={"bpv": 10_000})
        resolved = resolve_query(query, timestamp=dt.datetime(2026, 3, 20, 12, 0), pricer_or_curve=narrow_pricers)
        package, risk_weights = resolved.resolve_package(pricer_or_curve=narrow_pricers)
        vmap = resolved.build_value_map(pricer_or_curve=narrow_pricers, package=package, risk_weights=risk_weights)

        assert vmap.apply(FixedRateBondValue.ROLL_BPS_RUNNING, horizon="3M") == pytest.approx(12.5)

    assert expansion_calls["count"] == 1
    assert _CountingInterpolator.calls == 1


def test_roll_spline_persistent_cache_survives_memory_clear(monkeypatch, tmp_path) -> None:
    import Caching.supabase_engine as supabase_engine

    monkeypatch.setenv("ARBS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(carry_roll_module, "_ROLL_SPLINE_DISK_CACHE", None)
    monkeypatch.setattr(supabase_engine, "SUPABASE_ENABLED", False)
    carry_roll_module.clear_roll_spline_cache(include_persistent=True)
    monkeypatch.setattr(carry_roll_module, "load_sofr_fixing_pct", lambda as_of_date: 5.0)
    monkeypatch.setattr(
        carry_roll_module,
        "coupon_accrual_price_per_100",
        lambda *, coupon_pct, start_date, end_date, **kwargs: float(coupon_pct) * ((end_date - start_date).days / 365.0),
    )

    as_of = dt.date(2026, 3, 20)
    full_pricers = _make_pricers(as_of)
    narrow_pricers = {"C5": full_pricers["C5"]}

    warm = carry_roll_module.compute_carry_roll_frame(pricers=full_pricers, as_of_date=as_of)
    assert warm["roll_3m_bps"].notna().any()

    carry_roll_module.clear_roll_spline_cache(include_persistent=False)
    monkeypatch.setattr(carry_roll_module, "fit_roll_spline", lambda ttm, ytm: (_ for _ in ()).throw(AssertionError("unexpected refit")))

    cold = carry_roll_module.compute_carry_roll_frame(pricers=narrow_pricers, as_of_date=as_of)

    assert cold.loc[cold["cusip"] == "C5", "roll_3m_bps"].iloc[0] == pytest.approx(12.5)


def test_roll_spline_cache_uses_core_layered_proxy_when_supabase_enabled(monkeypatch, tmp_path) -> None:
    import Caching.supabase_engine as supabase_engine

    monkeypatch.setenv("ARBS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(carry_roll_module, "_ROLL_SPLINE_DISK_CACHE", None)
    monkeypatch.setattr(supabase_engine, "SUPABASE_ENABLED", True)

    captured: dict[str, object] = {}

    class _FakeLayeredDictProxy(dict):
        def __init__(self, l1, cache_ns, *, l2_read, l2_write, ttl_seconds):
            super().__init__()
            captured["l1"] = l1
            captured["cache_ns"] = cache_ns
            captured["l2_read"] = l2_read
            captured["l2_write"] = l2_write
            captured["ttl_seconds"] = ttl_seconds

    monkeypatch.setattr(carry_roll_module, "LayeredDictProxy", _FakeLayeredDictProxy)

    cache = carry_roll_module._get_roll_spline_disk_cache()

    assert isinstance(cache, _FakeLayeredDictProxy)
    assert captured["cache_ns"] == carry_roll_module._ROLL_SPLINE_CORE_CACHE_NS
    assert captured["l2_read"] is True
    assert captured["l2_write"] is True


def test_expand_pricer_universe_uses_off_runs_plus_requested_legs(monkeypatch) -> None:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    requested: dict[str, object] = {}
    ref_df = pd.DataFrame(
        [
            {"cusip": "RUN0", "ttm": 2.0, "rank": 0},
            {"cusip": "RUN1", "ttm": 2.5, "rank": 1},
            {"cusip": "RUN2", "ttm": 3.0, "rank": 2},
            {"cusip": "OLD3", "ttm": 3.5, "rank": 3},
            {"cusip": "OLD4", "ttm": 4.0, "rank": 4},
            {"cusip": "ACT10", "ttm": 10.0, "rank": 0},
        ]
    )

    monkeypatch.setattr(FixedRateBondsMDP, "get_bond_reference_data", lambda self, as_of_date: ref_df.copy())

    def _fake_get_pricer(self, request):
        requested["request"] = dict(request)
        return {"ACT10": _CarryRollBondPricer("ACT10", as_of=dt.date(2026, 3, 20), ttm=10.0, ytm=4.0, dirty_price=100.0, mdur=7.0)}

    monkeypatch.setattr(FixedRateBondsMDP, "get_pricer", _fake_get_pricer)

    base = {"ACT10": _CarryRollBondPricer("ACT10", as_of=dt.date(2026, 3, 20), ttm=10.0, ytm=4.0, dirty_price=100.0, mdur=7.0)}
    carry_roll_module.expand_pricer_universe_for_carry_roll(pricers=base, as_of_date=dt.date(2026, 3, 20), min_ttm=1.0)

    assert requested["request"]["cusips"] == ["OLD3", "OLD4", "ACT10"]


def test_fit_roll_spline_linearizes_long_end_tail() -> None:
    x = pd.Series([1.939284, 2.978082, 4.936986, 6.936986, 9.901033, 19.901370, 29.901033], dtype=float).to_numpy()
    y = pd.Series([3.841, 3.850, 3.956, 4.147, 4.340, 4.938, 4.914], dtype=float).to_numpy()

    func = carry_roll_module.fit_roll_spline(x, y)

    assert func is not None

    y_now = float(func(29.901033))
    y_prev = float(func(29.651033))
    roll_bps = (y_now - y_prev) * 100.0
    expected_tail_roll = ((y[-1] - y[-2]) / (x[-1] - x[-2])) * 0.25 * 100.0

    assert roll_bps == pytest.approx(expected_tail_roll)
    assert roll_bps == pytest.approx(-0.060002, abs=1e-5)
