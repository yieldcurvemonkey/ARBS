import datetime

import pandas as pd
import pytest
import pytz

pytest.importorskip("rateslib")
pytest.importorskip("QuantLib")
import rateslib as rl

import MDP.STIRFutures.FXForwardMDP as fx_module
from MDP.STIRFutures.FXForwardMDP import FXForwardMDP
from Query.FXForwards.backends.rateslib.RLFXForwardPricer import RLFXForwardPricer


def _ny_ts(year=2026, month=2, day=27, hour=10, minute=30, second=0):
    return pytz.timezone("America/New_York").localize(datetime.datetime(year, month, day, hour, minute, second))


def _chi_ts(year=2026, month=2, day=27, hour=9, minute=30, second=0):
    return pytz.timezone("America/Chicago").localize(datetime.datetime(year, month, day, hour, minute, second))


def _simple_curve(ref_date: datetime.date, calendar: str = "nyc", convention: str = "act360", modifier: str = "mf", end_df: float = 0.85):
    left = rl.dt(ref_date.year, ref_date.month, ref_date.day)
    right = rl.add_tenor(left, "5y", modifier=modifier, calendar=calendar)
    return rl.Curve(nodes={left: 1.0, right: end_df}, convention=convention, calendar=calendar, modifier=modifier)


def _setup_memory_cache(monkeypatch, mdp: FXForwardMDP):
    mem = {}
    monkeypatch.setattr(mdp, "_ensure_pricer_cache", lambda: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: mem.get(key))
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, val: mem.__setitem__(key, val))
    return mem


def test_alias_parsing_and_pair_strip_expansion():
    asof = datetime.date(2026, 2, 27)
    aliases = fx_module._resolve_aliases_bulk(["USDCAD", "USDCAD:1W", "EURUSD:SPOT", "USDCAD.B"], asof)

    assert aliases["USDCAD"][0] == "USDCAD.O"
    assert aliases["USDCAD"][-1] == "USDCAD.3"
    assert len(aliases["USDCAD"]) == len(fx_module._PAIR_STRIP_CODES)
    assert aliases["USDCAD:1W"] == ["USDCAD.B"]
    assert aliases["EURUSD:SPOT"] == ["EURUSD.S"]
    assert aliases["USDCAD.B"] == ["USDCAD.B"]


def test_tenor_map_correctness_and_core6_rejection():
    assert fx_module._map_tenor_to_suffix("ON") == "O"
    assert fx_module._map_tenor_to_suffix("TN") == "A"
    assert fx_module._map_tenor_to_suffix("SPOT") == "S"
    assert fx_module._map_tenor_to_suffix("11M") == "X"
    assert fx_module._map_tenor_to_suffix("3Y") == "3"

    with pytest.raises(ValueError, match="Core6"):
        fx_module._resolve_aliases_bulk(["USDNOK"], datetime.date(2026, 2, 27))


def test_date_only_string_keeps_calendar_day_in_chicago():
    assert fx_module._as_date("2026-02-17") == datetime.date(2026, 2, 17)


def test_points_scaling_jpy_vs_non_jpy():
    assert fx_module._points_scale("USDJPY") == 1e2
    assert fx_module._points_scale("USDCAD") == 1e4


def test_basis_sign_multiplier_usd_orientation():
    assert fx_module._basis_sign_multiplier("EURUSD") == 1.0
    assert fx_module._basis_sign_multiplier("USDCAD") == -1.0
    assert fx_module._basis_sign_multiplier("EURCAD") == 1.0


def test_outright_conversion_uses_spot_symbol_and_curve_fail_open(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    _setup_memory_cache(monkeypatch, mdp)

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("curve build boom")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())

    ts = _ny_ts()
    df = pd.DataFrame(
        {
            "^USDCAD": [1.3500],
            "USDCAD.B": [25.0],
        },
        index=pd.DatetimeIndex([ts]),
    )
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: df)

    out = mdp._get_data_for_timestamp(
        symbols=["USDCAD:1W"],
        timestamp=ts,
        show_tqdm=False,
        force_refresh=True,
    )

    pr = out["USDCAD:1W"][0]
    assert pr.spot() == pytest.approx(1.35)
    assert pr.points_raw() == pytest.approx(25.0)
    assert pr.points_decimal() == pytest.approx(0.0025)
    assert pr.forward_rate() == pytest.approx(1.3525)
    assert pr.basis_bps() is None
    assert pr.fx_rates() is None
    assert pr.fx_forwards() is None
    assert pr.meta().get("curve_error") is not None


def test_spot_lag_rules_and_settlement_dates():
    trade_date = datetime.date(2026, 2, 27)

    assert fx_module._spot_lag_bdays("USDCAD") == 1
    assert fx_module._spot_lag_bdays("EURUSD") == 2

    usdcad_spot = fx_module._spot_settlement_date(trade_date, "USDCAD")
    eurusd_spot = fx_module._spot_settlement_date(trade_date, "EURUSD")

    assert usdcad_spot == datetime.date(2026, 3, 2)
    assert eurusd_spot == datetime.date(2026, 3, 3)


def test_eurusd_curve_profile_required_and_validated():
    with pytest.raises(ValueError, match="curve_profile_key is required"):
        fx_module._curve_configs_for_pair("EURUSD", None)

    with pytest.raises(ValueError, match="Unknown curve_profile_key"):
        fx_module._curve_configs_for_pair("USDEUR", "bad_profile")


def test_profile_selection_wiring_for_three_eurusd_presets(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    _setup_memory_cache(monkeypatch, mdp)

    calls = []
    ts = _ny_ts()

    class _DummyCurveBuilder:
        def build_curve(self, curve_name, timestamp, kwargs=None, curve_only=True):
            _ = timestamp, kwargs, curve_only
            calls.append(curve_name)
            if "EUR" in curve_name:
                return _simple_curve(ts.date(), calendar="tgt", convention="act360", modifier="mf", end_df=0.88)
            if "CAD" in curve_name:
                return _simple_curve(ts.date(), calendar="tro", convention="act365f", modifier="mf", end_df=0.87)
            return _simple_curve(ts.date(), calendar="nyc", convention="act360", modifier="mf", end_df=0.86)

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    cols = {"^EURUSD": [1.1000]}
    for i, suffix in enumerate(fx_module._PAIR_STRIP_CODES):
        cols[f"EURUSD.{suffix}"] = [-20.0 - i]
    df = pd.DataFrame(cols, index=pd.DatetimeIndex([ts]))
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: df)

    profiles = {
        "eurusd_ois_mix23_estr_ldn": ("USD-OIS-Q12xM12STIRT-MIX23", "EUR-ESTR-LONDON-Q12STIRT"),
        "eurusd_ois_mix23_estr_nyc": ("USD-OIS-Q12xM12STIRT-MIX23", "EUR-ESTR-NYC-Q12STIRT"),
        "eurusd_sofr_estr_ldn": ("USD-SOFR-1D-Q12xM12STIRT", "EUR-ESTR-LONDON-Q12STIRT"),
    }

    for profile_key, expected in profiles.items():
        calls.clear()
        out = mdp._get_data_for_timestamp(
            symbols=["EURUSD"],
            timestamp=ts,
            curve_profile_key=profile_key,
            force_refresh=True,
        )
        first = out["EURUSD"][0]
        curve_names = first.meta()["curve_names"]
        assert curve_names["USD"] == expected[0]
        assert curve_names["EUR"] == expected[1]
        assert expected[0] in calls
        assert expected[1] in calls


def test_bootstrap_formula_and_basis_sign_convention():
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")

    trade_date = datetime.date(2026, 2, 27)
    spot = 1.35

    dom_curve = _simple_curve(trade_date, calendar="tro", convention="act365f", modifier="mf", end_df=0.90)
    for_curve = _simple_curve(trade_date, calendar="nyc", convention="act360", modifier="mf", end_df=0.95)

    curve_map = {
        "USD-SOFR-1D-Q12xM12STIRT": for_curve,
        "CAD-CORRA-Q8STIRT": dom_curve,
    }

    quotes = {}
    raw_points = {
        "B": -60.0,
        "C": -62.0,
        "D": -64.0,
        "E": -66.0,
        "G": -70.0,
        "H": -74.0,
    }
    for suffix, pts in raw_points.items():
        settlement = fx_module._settlement_date_for_suffix(trade_date, "USDCAD", suffix)
        points_decimal = pts / fx_module._points_scale("USDCAD")
        fwd = spot + points_decimal
        quotes[suffix] = {
            "settlement_date": settlement,
            "forward_rate": fwd,
            "points_raw": pts,
            "points_decimal": points_decimal,
            "quote_timestamp": _ny_ts(),
        }

    ctx = mdp._build_pair_curve_context(
        pair="USDCAD",
        trade_date=trade_date,
        spot=spot,
        quotes_by_suffix=quotes,
        curve_config_by_ccy={
            "USD": "USD-SOFR-1D-Q12xM12STIRT",
            "CAD": "CAD-CORRA-Q8STIRT",
        },
        curve_getter=lambda name: curve_map[name],
    )

    assert ctx["curve_error"] is None
    assert ctx["fx_forwards"] is not None
    ffyy_curve = ctx["fx_forwards"].fx_curves["usdcad"]

    for suffix, q in quotes.items():
        settle_rl = fx_module._to_rl_dt(q["settlement_date"])
        expected_df = q["forward_rate"] * float(dom_curve[settle_rl]) / spot
        assert float(ffyy_curve[settle_rl]) == pytest.approx(expected_df)

    check_suffix = "H"
    settle_rl = fx_module._to_rl_dt(quotes[check_suffix]["settlement_date"])
    spot_settle_rl = fx_module._to_rl_dt(ctx["spot_settlement"])
    r_ffyy = float(ffyy_curve.rate(spot_settle_rl, settle_rl, modifier="mf"))
    r_ffff = float(for_curve.rate(spot_settle_rl, settle_rl, modifier="mf"))

    raw_basis = (r_ffyy - r_ffff) * 100.0
    expected_basis = raw_basis * fx_module._basis_sign_multiplier("USDCAD")
    assert ctx["basis_by_suffix"][check_suffix] == pytest.approx(expected_basis)
    assert ctx["basis_by_suffix"][check_suffix] < 0.0


def test_missing_tenors_are_dropped_and_min_nodes_enforced():
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    trade_date = datetime.date(2026, 2, 27)

    dom_curve = _simple_curve(trade_date, calendar="tro", convention="act365f", modifier="mf", end_df=0.90)
    for_curve = _simple_curve(trade_date, calendar="nyc", convention="act360", modifier="mf", end_df=0.95)

    curve_map = {
        "USD-SOFR-1D-Q12xM12STIRT": for_curve,
        "CAD-CORRA-Q8STIRT": dom_curve,
    }

    quotes = {}
    for suffix in ["B", "C", "D", "E", "G"]:
        settle = fx_module._settlement_date_for_suffix(trade_date, "USDCAD", suffix)
        quotes[suffix] = {
            "settlement_date": settle,
            "forward_rate": 1.34,
            "points_raw": -100.0,
            "points_decimal": -0.01,
            "quote_timestamp": _ny_ts(),
        }

    ctx = mdp._build_pair_curve_context(
        pair="USDCAD",
        trade_date=trade_date,
        spot=1.35,
        quotes_by_suffix=quotes,
        curve_config_by_ccy={
            "USD": "USD-SOFR-1D-Q12xM12STIRT",
            "CAD": "CAD-CORRA-Q8STIRT",
        },
        curve_getter=lambda name: curve_map[name],
    )

    assert ctx["fx_forwards"] is None
    assert "need >=6" in ctx["curve_error"]


def test_cache_hit_miss_and_nearest_timestamp(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    _setup_memory_cache(monkeypatch, mdp)

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("curve build boom")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())

    fetch_calls = {"n": 0}
    req_ts = _ny_ts(second=50)
    idx = pd.DatetimeIndex(
        [
            _ny_ts(minute=29),
            _ny_ts(minute=31),
        ]
    )
    df = pd.DataFrame(
        {
            "^USDCAD": [1.3500, 1.3500],
            "USDCAD.B": [20.0, 40.0],
        },
        index=idx,
    )

    def _fetch(*args, **kwargs):
        fetch_calls["n"] += 1
        return df

    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", _fetch)

    out1 = mdp._get_data_for_timestamp(["USDCAD:1W"], req_ts, force_refresh=True)
    assert out1["USDCAD:1W"][0].points_raw() == pytest.approx(40.0)
    assert fetch_calls["n"] == 1

    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: pytest.fail("unexpected fetch on cache hit"))
    out2 = mdp._get_data_for_timestamp(["USDCAD:1W"], req_ts, force_refresh=False)

    assert out2["USDCAD:1W"][0].points_raw() == pytest.approx(40.0)


def test_chicago_market_timestamps_align_and_quote_timestamp_is_utc(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    _setup_memory_cache(monkeypatch, mdp)

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("curve build boom")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())

    req_ts_ny = _ny_ts(hour=10, minute=30, second=10)
    idx_chi = pd.DatetimeIndex(
        [
            _chi_ts(hour=9, minute=29, second=0),
            _chi_ts(hour=9, minute=31, second=0),
        ]
    )
    df = pd.DataFrame(
        {
            "^USDCAD": [1.3500, 1.3500],
            "USDCAD.B": [20.0, 40.0],
        },
        index=idx_chi,
    )

    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: df)

    out = mdp._get_data_for_timestamp(["USDCAD:1W"], req_ts_ny, force_refresh=True)
    pr = out["USDCAD:1W"][0]

    assert pr.points_raw() == pytest.approx(40.0)
    assert pr.quote_timestamp().tzinfo is not None
    assert pr.quote_timestamp().utcoffset() == datetime.timedelta(0)
    assert pr.quote_timestamp() == _chi_ts(hour=9, minute=31, second=0).astimezone(pytz.UTC)


def test_graceful_degradation_when_curve_build_fails(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")
    _setup_memory_cache(monkeypatch, mdp)

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("synthetic curve failure")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())

    ts = _ny_ts()
    df = pd.DataFrame(
        {
            "^USDCAD": [1.3500],
            "USDCAD.B": [30.0],
        },
        index=pd.DatetimeIndex([ts]),
    )
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: df)

    out = mdp._get_data_for_timestamp(["USDCAD:1W"], ts, force_refresh=True)
    pr = out["USDCAD:1W"][0]

    assert isinstance(pr, RLFXForwardPricer)
    assert pr.basis_bps() is None
    assert pr.fx_rates() is None
    assert pr.fx_forwards() is None
    assert "curve_error" in pr.meta()
    assert "failure" in str(pr.meta()["curve_error"])


def test_bulk_request_shape_and_deterministic_structure(monkeypatch):
    mdp = FXForwardMDP(source="BARCHART_FXFWD-RL")

    def _stub_get_data_for_timestamp(symbols, timestamp, **kwargs):
        _ = kwargs
        ts = fx_module._as_datetime(timestamp)
        return {
            "USDCAD:1W": [
                RLFXForwardPricer(
                    pair="USDCAD",
                    symbol="USDCAD.B",
                    tenor="1W",
                    settlement_date=ts.date(),
                    quote_timestamp=ts,
                    spot=1.35,
                    points_raw=25.0,
                    points_decimal=0.0025,
                    forward_rate=1.3525,
                    basis_bps=None,
                    fx_rates=None,
                    fx_forwards=None,
                    meta_data={"symbols": symbols},
                )
            ]
        }

    monkeypatch.setattr(mdp, "_get_data_for_timestamp", _stub_get_data_for_timestamp)

    ts1 = datetime.date(2026, 2, 26)
    ts2 = datetime.date(2026, 2, 27)

    out = mdp.get_bulk_data(
        {
            "symbols": ["USDCAD:1W"],
            "timestamps": [ts1, ts2],
            "max_workers": 2,
        }
    )

    assert set(out.keys()) == {ts1, ts2}
    assert set(out[ts1].keys()) == {"USDCAD:1W"}
    assert set(out[ts2].keys()) == {"USDCAD:1W"}
