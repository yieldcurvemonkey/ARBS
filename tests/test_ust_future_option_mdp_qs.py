import datetime
import math

import pandas as pd
import pytest
import pytz

import MDP.USTFutures.USTFutureOptionMDP as ustfo_module
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolProductID import QuikVolProductID
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolTimeseriesQueryBuilder import QuikVolTimeseriesQueryBuilder
from MDP.STIRFutures.QuikStrikeSDK.core.types.QuikVolValueType import QuikVolValueType
from MDP.USTFutures.USTFutureOptionMDP import (
    USTFutureOptionSABRSmile,
    USTFutureOptionMDP,
)
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer


def _make_pricer(
    *,
    label: str,
    right: str,
    delta: int,
    quote_ts: datetime.datetime,
    iv_normal: float,
    forward: float = 112.90625,
    fv01: float = 0.08,
    underlying_symbol: str = "ZNH26",
    expiry_date: datetime.date = datetime.date(2026, 4, 3),
    globex_symbol: str = "TY_30",
) -> QLUSTFutureOptionPricer:
    return QLUSTFutureOptionPricer(
        symbol=f"{underlying_symbol}|{delta}{right}",
        right=right,
        underlying_symbol=underlying_symbol,
        strike=forward,
        quote_timestamp=quote_ts,
        expiry_date=expiry_date,
        market_price=1.0,
        model_price=1.0,
        iv_normal=iv_normal,
        delta=0.0,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
        forward=forward,
        discount=1.0,
        fv01=fv01,
        meta_data={
            "qs_series_label": label,
            "qs_query": {
                "delta": delta,
                "globex_symbol": globex_symbol,
                "qv_value_type": "Call" if right == "C" else "Put",
            },
        },
    )


def _make_qs_payload(as_of: datetime.date, *, globex_symbol: str = "TY_30"):
    ny = pytz.timezone("America/New_York")
    prev_dt = ny.localize(datetime.datetime.combine(as_of - datetime.timedelta(days=1), datetime.time(16, 0)))
    same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 0)))
    later_same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 5)))

    payload = {}
    call_vols = {
        5: 1.14,
        10: 1.04,
        15: 0.95,
        20: 0.88,
        25: 0.84,
        30: 0.815,
        35: 0.802,
        40: 0.786,
        45: 0.779,
        50: 0.774,
    }
    put_vols = {
        5: 0.79,
        10: 0.748,
        15: 0.727,
        20: 0.721,
        25: 0.724,
        30: 0.733,
        35: 0.745,
        40: 0.756,
        45: 0.766,
        50: 0.774,
    }

    for delta, vol in call_vols.items():
        label = f"{globex_symbol} {delta}D Call"
        payload[label] = [
            _make_pricer(label=label, right="C", delta=delta, quote_ts=prev_dt, iv_normal=vol * 0.98, globex_symbol=globex_symbol),
            _make_pricer(label=label, right="C", delta=delta, quote_ts=same_day, iv_normal=vol, globex_symbol=globex_symbol),
        ]
    payload[f"{globex_symbol} 25D Call"].append(
        _make_pricer(label=f"{globex_symbol} 25D Call", right="C", delta=25, quote_ts=later_same_day, iv_normal=0.845, globex_symbol=globex_symbol)
    )

    for delta, vol in put_vols.items():
        label = f"{globex_symbol} {delta}D Put"
        payload[label] = [
            _make_pricer(label=label, right="P", delta=delta, quote_ts=same_day, iv_normal=vol, globex_symbol=globex_symbol),
        ]
    return payload


class _DummyFuturePricer:
    def yield_to_maturity_from_price(self, future_price: float, curves=None) -> float:
        _ = curves
        return 0.12 - 0.00068 * float(future_price)


def test_fetch_sabr_smile_strict_source_split_rejections():
    with pytest.raises(NotImplementedError):
        USTFutureOptionMDP(source="QUIKSTRIKE_USTFO-QL").fetch_sabr_smile(
            {"globex_symbol": "TY_30", "as_of": datetime.date(2026, 3, 4)}
        )
    with pytest.raises(ValueError):
        USTFutureOptionMDP(source="BARCHART_USTFO-QL").fetch_sabr_smile(
            {"globex_symbol": "TY_30", "as_of": datetime.date(2026, 3, 4)}
        )


def test_fetch_sabr_smile_rejects_missing_as_of_and_non_cm_symbol():
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    with pytest.raises(ValueError):
        mdp.fetch_sabr_smile({"globex_symbol": "TY_30"})
    with pytest.raises(ValueError):
        mdp.fetch_sabr_smile({"globex_symbol": "TYM26", "as_of": datetime.date(2026, 3, 4)})


def test_fetch_sabr_smile_builds_qs_queries_and_returns_rich_model(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    seen = {}

    def _stub_qs(request):
        seen["request"] = request
        return _make_qs_payload(as_of)

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    smile = mdp.fetch_sabr_smile({"globex_symbol": "TY_30", "as_of": as_of, "force_refresh": True})

    assert seen["request"]["endpoint"] == "qs_timeseries"
    assert seen["request"]["options"] is True
    assert seen["request"]["start"] == as_of
    assert seen["request"]["end"] == as_of
    assert len(seen["request"]["queries"]) == 20
    assert [q["qv_value_type"] for q in seen["request"]["queries"][:10]] == ["Call"] * 10
    assert [q["qv_value_type"] for q in seen["request"]["queries"][10:]] == ["Put"] * 10
    assert [q["delta"] for q in seen["request"]["queries"][:10]] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

    assert smile.source == "USTFO_DUAL-QL"
    assert smile.globex_symbol == "TY_30"
    assert smile.underlying_contract == "ZNH26"
    assert smile.params.beta == pytest.approx(0.5)
    assert smile.params.forward_price == pytest.approx(112.90625)
    assert smile.params.forward_futures_ytm == pytest.approx(_DummyFuturePricer().yield_to_maturity_from_price(112.90625))
    assert len(smile.points) == 20
    assert isinstance(smile, USTFutureOptionSABRSmile)

    sorted_strikes = [pt.strike_price for pt in smile.points]
    assert sorted_strikes == sorted(sorted_strikes)

    call_25 = next(pt for pt in smile.points if pt.right == "C" and pt.delta_abs == 25.0)
    assert call_25.iv_normal_price == pytest.approx(0.845)

    probe_price = smile.points[len(smile.points) // 2].strike_price
    probe_ytm = smile.price_to_futures_ytm(probe_price)
    vol_price = smile.normal_vol(probe_price, strike_space="price", vol_units="price")
    vol_ytm = smile.normal_vol(probe_ytm, strike_space="futures_ytm", vol_units="price")

    assert math.isfinite(vol_price)
    assert vol_ytm == pytest.approx(vol_price, rel=1e-10)
    assert smile.normal_vol(probe_price, vol_units="bps") == pytest.approx(vol_price / smile.fv01, rel=1e-12)


def test_sabr_smile_cache_roundtrip_preserves_object_and_evaluator(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    monkeypatch.setattr(mdp, "_qs_timeseries", lambda request: _make_qs_payload(as_of))
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    smile = mdp.fetch_sabr_smile({"globex_symbol": "TY_30", "as_of": as_of})
    payload = mdp._serialize_get_data_result("sabr_smile", {"sabr_smile": [smile]})
    restored = mdp._deserialize_get_data_result(payload)

    assert isinstance(restored, dict)
    restored_smile = restored["sabr_smile"][0]
    assert isinstance(restored_smile, USTFutureOptionSABRSmile)

    probe = smile.points[3].strike_price
    assert restored_smile.normal_vol(probe) == pytest.approx(smile.normal_vol(probe), rel=1e-12)
    assert restored_smile.price_to_futures_ytm(probe) == pytest.approx(smile.price_to_futures_ytm(probe), rel=1e-12)


def test_fetch_sabr_smile_dual_seeds_single_symbol_option_snapshot_cache(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    seen = {"qs_calls": 0}

    def _stub_qs(request):
        seen["qs_calls"] += 1
        return _make_qs_payload(as_of, globex_symbol="TY_03")

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    smile = mdp.fetch_sabr_smile({"globex_symbol": "TY_03", "as_of": as_of, "force_refresh": True})
    assert smile.globex_symbol == "TY_03"
    assert seen["qs_calls"] == 1

    monkeypatch.setattr(
        mdp,
        "_option_snapshot",
        lambda request: (_ for _ in ()).throw(AssertionError("_option_snapshot should not run after SABR cache seeding")),
    )

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["TY_03|25DC"],
            "timestamp": as_of,
            "show_tqdm": False,
        }
    )

    assert "TY_03|25DC" in out
    assert out["TY_03|25DC"][0].iv_normal() == pytest.approx(0.845)


def test_fetch_sabr_smile_dual_cache_key_canonicalizes_zero_padded_cm_symbol(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    seen = {"qs_calls": 0}

    def _stub_qs(request):
        seen["qs_calls"] += 1
        return _make_qs_payload(as_of, globex_symbol="TY_03")

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    mdp.fetch_sabr_smile({"globex_symbol": "TY_03", "as_of": as_of, "force_refresh": True})
    cached = mdp.fetch_sabr_smile({"globex_symbol": "TY_3", "as_of": as_of})

    assert seen["qs_calls"] == 1
    assert cached.globex_symbol == "TY_03"


def test_quikvol_timeseries_query_builder_handles_short_dated_ust_cm_symbol():
    payload = QuikVolTimeseriesQueryBuilder.build_elements_dict(
        globex_symbol="TY_03",
        qv_value_type=QuikVolValueType.Call,
        delta=5,
    )

    assert payload["Elements"][0]["ProductId"] == QuikVolProductID.TY.value.underlying_pid


def test_qs_timeseries_to_pricers_normalizes_delta_from_series_label(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    ts = pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 4, 16, 0))
    df = pd.DataFrame(
        {
            "TY_30 10D Call": [1.04],
            "TY_30 5D Call": [1.14],
        },
        index=pd.DatetimeIndex([ts]),
    )
    query_meta = [
        {
            "globex_symbol": "TY_30",
            "barchart_contract": None,
            "kind": "cm",
            "root_globex": "TY",
            "cm_days": 30,
            "qv_value_type": "Call",
            "delta": 5,
            "strike": 0.0,
            "option_type": "Call",
        },
        {
            "globex_symbol": "TY_30",
            "barchart_contract": None,
            "kind": "cm",
            "root_globex": "TY",
            "cm_days": 30,
            "qv_value_type": "Call",
            "delta": 10,
            "strike": 0.0,
            "option_type": "Call",
        },
    ]
    underlying_idx = pd.DatetimeIndex([ts])
    underlying_data = {
        "ZNH26": pd.DataFrame({"Close": [112.90625]}, index=underlying_idx),
    }

    monkeypatch.setattr(
        ustfo_module,
        "_qs_front_barchart_contract_for_date",
        lambda root_globex, as_of: "ZNH26",
    )
    monkeypatch.setattr(
        mdp,
        "_discount_factor",
        lambda **kwargs: (1.0, None),
    )

    pricers = mdp._qs_timeseries_to_pricers(
        df=df,
        query_meta=query_meta,
        underlying_data=underlying_data,
        curve_name="USD-SOFR-1D-Q12xM12STIRT",
        curve_kwargs={},
        use_ql_calculator=False,
    )

    p10 = pricers["TY_30 10D Call"][0]
    p5 = pricers["TY_30 5D Call"][0]
    assert p10.meta()["qs_query"]["delta"] == pytest.approx(10.0)
    assert p5.meta()["qs_query"]["delta"] == pytest.approx(5.0)


def test_select_sabr_smile_pricers_prefers_series_label_delta():
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    ts = pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 4, 16, 0))
    pr = _make_pricer(label="TY_30 10D Call", right="P", delta=5, quote_ts=ts, iv_normal=1.04)
    pr._meta_data["qs_query"]["delta"] = 5
    pr._meta_data["qs_series_label"] = "TY_30 10D Call"

    selected = mdp._select_sabr_smile_pricers(
        pricers_by_series={
            "TY_30 10D Call": [pr],
            "TY_30 10D Put": [_make_pricer(label="TY_30 10D Put", right="P", delta=10, quote_ts=ts, iv_normal=0.75)],
        },
        as_of=datetime.date(2026, 3, 4),
        deltas=[10],
    )

    assert ("C", 10) in selected
    assert ("P", 10) in selected


def test_fetch_bulk_sabr_smile_qs_multi_symbol_multi_date_batches_conversion_pricers(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    ny = pytz.timezone("America/New_York")
    d1 = datetime.date(2026, 3, 4)
    d2 = datetime.date(2026, 3, 5)
    seen = {"qs_requests": [], "ustf_requests": []}

    call_vols = {5: 1.14, 10: 1.04, 15: 0.95, 20: 0.88, 25: 0.84, 30: 0.815, 35: 0.802, 40: 0.786, 45: 0.779, 50: 0.774}
    put_vols = {5: 0.79, 10: 0.748, 15: 0.727, 20: 0.721, 25: 0.724, 30: 0.733, 35: 0.745, 40: 0.756, 45: 0.766, 50: 0.774}

    def _append_payload(payload, *, globex_symbol, underlying_symbol, as_of, forward, call_shift=0.0, put_shift=0.0):
        same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 0)))
        later_same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 5)))
        for delta, vol in call_vols.items():
            label = f"{globex_symbol} {delta}D Call"
            payload.setdefault(label, []).append(
                _make_pricer(
                    label=label,
                    right="C",
                    delta=delta,
                    quote_ts=same_day,
                    iv_normal=vol + call_shift,
                    forward=forward,
                    underlying_symbol=underlying_symbol,
                    globex_symbol=globex_symbol,
                )
            )
        payload[f"{globex_symbol} 25D Call"].append(
            _make_pricer(
                label=f"{globex_symbol} 25D Call",
                right="C",
                delta=25,
                quote_ts=later_same_day,
                iv_normal=call_vols[25] + call_shift + 0.001,
                forward=forward,
                underlying_symbol=underlying_symbol,
                globex_symbol=globex_symbol,
            )
        )
        for delta, vol in put_vols.items():
            label = f"{globex_symbol} {delta}D Put"
            payload.setdefault(label, []).append(
                _make_pricer(
                    label=label,
                    right="P",
                    delta=delta,
                    quote_ts=same_day,
                    iv_normal=vol + put_shift,
                    forward=forward,
                    underlying_symbol=underlying_symbol,
                    globex_symbol=globex_symbol,
                )
            )

    def _stub_qs(request):
        seen["qs_requests"].append(request)
        payload = {}
        _append_payload(payload, globex_symbol="TY_03", underlying_symbol="ZNH26", as_of=d1, forward=112.90625)
        _append_payload(payload, globex_symbol="TY_03", underlying_symbol="ZNH26", as_of=d2, forward=112.87500, call_shift=0.01, put_shift=0.005)
        _append_payload(payload, globex_symbol="FV_10", underlying_symbol="ZFM26", as_of=d1, forward=108.50000, call_shift=0.02, put_shift=0.01)
        _append_payload(payload, globex_symbol="FV_10", underlying_symbol="ZFM26", as_of=d2, forward=108.43750, call_shift=0.03, put_shift=0.015)
        return payload

    class _DummyUSTFuturesMDP:
        def __init__(self, source):
            assert source == "BARCHART_USTF-RL"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def get_pricer(self, request):
            seen["ustf_requests"].append(request)
            return {symbol: _DummyFuturePricer() for symbol in request["symbols"]}

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(ustfo_module, "USTFuturesMDP", _DummyUSTFuturesMDP)

    out = mdp.fetch_bulk_sabr_smile(
        {
            "globex_symbols": ["TY_03", "FV_10"],
            "timestamps": [d1, d2],
            "force_refresh": True,
        }
    )

    assert len(seen["qs_requests"]) == 1
    assert seen["qs_requests"][0]["start"] == d1
    assert seen["qs_requests"][0]["end"] == d2
    assert len(seen["qs_requests"][0]["queries"]) == 40
    assert len(seen["ustf_requests"]) == 2
    assert {req["timestamp"] for req in seen["ustf_requests"]} == {d1, d2}
    assert all(len(req["symbols"]) == 2 for req in seen["ustf_requests"])
    assert set(out.keys()) == {"TY_03", "FV_10"}
    assert isinstance(out["TY_03"][d1], USTFutureOptionSABRSmile)
    assert out["FV_10"][d2].underlying_contract == "ZFM26"


def test_fetch_bulk_sabr_smile_qs_falls_back_to_missing_dates_for_short_cm(monkeypatch):
    mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")
    d1 = datetime.date(2026, 3, 4)
    d2 = datetime.date(2026, 3, 5)
    seen = {"requests": []}

    def _merge_payloads(*payloads):
        merged = {}
        for payload in payloads:
            for label, plist in payload.items():
                merged.setdefault(label, []).extend(plist)
        return merged

    def _stub_qs(request):
        seen["requests"].append(request)
        if request["start"] != request["end"]:
            return _merge_payloads(
                _make_qs_payload(d2, globex_symbol="TY_05"),
                _make_qs_payload(d2, globex_symbol="TY_07"),
            )
        return _merge_payloads(
            _make_qs_payload(request["start"], globex_symbol="TY_05"),
            _make_qs_payload(request["start"], globex_symbol="TY_07"),
        )

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(
        mdp,
        "_build_bulk_sabr_smile_conversion_pricers",
        lambda requirements, *, force_refresh: {
            (underlying_contract, as_of): _DummyFuturePricer()
            for underlying_contract, as_of in requirements
        },
    )

    out = mdp.fetch_bulk_sabr_smile(
        {
            "globex_symbols": ["TY_05", "TY_07"],
            "timestamps": [d1, d2],
            "force_refresh": True,
        }
    )

    assert len(seen["requests"]) == 2
    assert seen["requests"][0]["start"] == d1
    assert seen["requests"][0]["end"] == d2
    assert seen["requests"][1]["start"] == d1
    assert seen["requests"][1]["end"] == d1
    assert isinstance(out["TY_05"][d1], USTFutureOptionSABRSmile)
    assert isinstance(out["TY_07"][d2], USTFutureOptionSABRSmile)
