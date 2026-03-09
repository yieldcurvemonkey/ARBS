import datetime
import math

import pandas as pd
import pytest
import pytz

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionSABRSmile,
    STIRFutureOptionMDP,
    QuikVolProductID,
    QuikVolValueType,
    _format_strike4,
)
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer


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


def _make_pricer(
    *,
    label: str,
    right: str,
    delta: int,
    quote_ts: datetime.datetime,
    iv_normal: float,
    forward: float = 96.25,
    underlying_symbol: str = "SFRM26",
    expiry_date: datetime.date = datetime.date(2026, 6, 17),
) -> QLSTIRFutureOptionPricer:
    return QLSTIRFutureOptionPricer(
        symbol=f"{underlying_symbol}|{9600 + delta:04d}{right}",
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
        meta_data={
            "qs_series_label": label,
            "qs_query": {
                "delta": delta,
                "globex_symbol": "SR3_60",
                "qv_value_type": "Call" if right == "C" else "Put",
            },
        },
    )


def _make_qs_payload(as_of: datetime.date):
    ny = pytz.timezone("America/New_York")
    prev_dt = ny.localize(datetime.datetime.combine(as_of - datetime.timedelta(days=1), datetime.time(16, 0)))
    same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 0)))
    later_same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 5)))

    payload = {}
    call_vols = {
        5: 0.24,
        10: 0.21,
        15: 0.19,
        20: 0.175,
        25: 0.165,
        30: 0.157,
        35: 0.151,
        40: 0.147,
        45: 0.144,
        50: 0.142,
    }
    put_vols = {
        5: 0.155,
        10: 0.148,
        15: 0.144,
        20: 0.141,
        25: 0.140,
        30: 0.140,
        35: 0.141,
        40: 0.143,
        45: 0.145,
        50: 0.142,
    }

    for delta, vol in call_vols.items():
        label = f"SR3_60 {delta}D Call"
        payload[label] = [
            _make_pricer(label=label, right="C", delta=delta, quote_ts=prev_dt, iv_normal=vol * 0.98),
            _make_pricer(label=label, right="C", delta=delta, quote_ts=same_day, iv_normal=vol),
        ]
    payload["SR3_60 25D Call"].append(
        _make_pricer(label="SR3_60 25D Call", right="C", delta=25, quote_ts=later_same_day, iv_normal=0.166)
    )

    for delta, vol in put_vols.items():
        label = f"SR3_60 {delta}D Put"
        payload[label] = [_make_pricer(label=label, right="P", delta=delta, quote_ts=same_day, iv_normal=vol)]
    return payload


def _make_strike_pricer(
    *,
    label: str,
    right: str,
    strike: float,
    quote_ts: datetime.datetime,
    iv_normal: float,
    delta: float,
    forward: float = 96.61,
    underlying_symbol: str = "SFRU26",
    globex_symbol: str = "SR3U26",
    expiry_date: datetime.date = datetime.date(2026, 9, 16),
) -> QLSTIRFutureOptionPricer:
    return QLSTIRFutureOptionPricer(
        symbol=f"{underlying_symbol}|{_format_strike4(strike, contract=underlying_symbol)}{right}",
        right=right,
        underlying_symbol=underlying_symbol,
        strike=strike,
        quote_timestamp=quote_ts,
        expiry_date=expiry_date,
        market_price=1.0,
        model_price=1.0,
        iv_normal=iv_normal,
        delta=delta,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
        forward=forward,
        discount=1.0,
        meta_data={
            "qs_series_label": label,
            "qs_query": {
                "globex_symbol": globex_symbol,
                "qv_value_type": "VolByStrike",
                "strike": strike,
                "option_type": "Call" if right == "C" else "Put",
            },
        },
    )


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


def test_fetch_sabr_smile_strict_source_split_rejections():
    with pytest.raises(NotImplementedError):
        STIRFutureOptionMDP(source="QUIKSTRIKE_STIRFO-QL").fetch_sabr_smile(
            {"globex_symbol": "SR3_60", "as_of": datetime.date(2026, 3, 19)}
        )
    with pytest.raises(ValueError):
        STIRFutureOptionMDP(source="BARCHART_STIRFO-QL").fetch_sabr_smile(
            {"globex_symbol": "SR3_60", "as_of": datetime.date(2026, 3, 19)}
        )


def test_fetch_sabr_smile_rejects_missing_as_of_and_invalid_symbol():
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    with pytest.raises(ValueError):
        mdp.fetch_sabr_smile({"globex_symbol": "SR3_60"})
    with pytest.raises(ValueError):
        mdp.fetch_sabr_smile({"globex_symbol": "TY_30", "as_of": datetime.date(2026, 3, 19)})


def test_fetch_sabr_smile_builds_qs_queries_and_returns_rich_model(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 19)
    seen = {}

    def _stub_qs(request):
        seen["request"] = request
        return _make_qs_payload(as_of)

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)

    smile = mdp.fetch_sabr_smile({"globex_symbol": "SR3_60", "as_of": as_of, "force_refresh": True})

    assert seen["request"]["endpoint"] == "qs_timeseries"
    assert seen["request"]["options"] is True
    assert seen["request"]["start"] == as_of
    assert seen["request"]["end"] == as_of
    assert len(seen["request"]["queries"]) == 20
    assert [q["qv_value_type"] for q in seen["request"]["queries"][:10]] == ["Call"] * 10
    assert [q["qv_value_type"] for q in seen["request"]["queries"][10:]] == ["Put"] * 10
    assert [q["delta"] for q in seen["request"]["queries"][:10]] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

    assert smile.source == "STIRFO_DUAL-QL"
    assert smile.symbol == "SR3_60"
    assert smile.underlying_contract == "SFRM26"
    assert smile.params.beta == pytest.approx(0.5)
    assert smile.params.forward_price == pytest.approx(96.25)
    assert smile.params.forward_rate == pytest.approx(3.75)
    assert len(smile.points) == 20
    assert isinstance(smile, STIRFutureOptionSABRSmile)

    sorted_strikes = [pt.strike_price for pt in smile.points]
    assert sorted_strikes == sorted(sorted_strikes)

    call_25 = next(pt for pt in smile.points if pt.right == "C" and pt.delta_abs == 25.0)
    assert call_25.iv_normal_price == pytest.approx(0.166)
    assert call_25.label == "SR3_60 25D Call"

    probe_price = smile.points[len(smile.points) // 2].strike_price
    probe_rate = smile.price_to_rate(probe_price)
    vol_price = smile.normal_vol(probe_price, strike_space="price", vol_units="price")
    vol_rate = smile.normal_vol(probe_rate, strike_space="rate", vol_units="price")

    assert math.isfinite(vol_price)
    assert vol_rate == pytest.approx(vol_price, rel=1e-10)
    assert smile.normal_vol(probe_price, vol_units="bps") == pytest.approx(vol_price * 100.0, rel=1e-12)

    delta_strike, delta_vol = smile.normal_vol_for_deltas(25, "C", strike_space_out="price", vol_units="bps")
    assert delta_vol == pytest.approx(smile.normal_vol(delta_strike, strike_space="price", vol_units="bps"), rel=1e-12)


def test_fetch_sabr_smile_offset_mode_uses_vol_by_strike_and_sets_atm_offsets(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    ny = pytz.timezone("America/New_York")
    seen = {}

    monkeypatch.setattr(
        mdp,
        "_resolve_sabr_smile_underlying_forward",
        lambda **kwargs: ("SFRU26", 96.61),
    )

    def _stub_qs(request):
        seen["request"] = request
        quote_ts = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 0)))
        payload = {}
        for query in request["queries"]:
            right = "C" if query["option_type"] == "Call" else "P"
            strike = float(query["strike"])
            delta = 0.50 if abs(strike - 96.625) < 1e-10 and right == "C" else (
                -0.50 if abs(strike - 96.625) < 1e-10 and right == "P" else (0.30 if right == "C" else -0.30)
            )
            label = f"{query['globex_symbol']} {strike:.4f} {query['option_type']}"
            payload[label] = [
                _make_strike_pricer(
                    label=label,
                    right=right,
                    strike=strike,
                    quote_ts=quote_ts,
                    iv_normal=0.14 + abs(96.625 - strike) * 0.10,
                    delta=delta,
                )
            ]
        return payload

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)

    smile = mdp.fetch_sabr_smile(
        {
            "globex_symbol": "SR3U26",
            "as_of": as_of,
            "strike_offsets_bps": [6.25, 12.5],
            "force_refresh": True,
        }
    )

    assert all(query["qv_value_type"] == "VolByStrike" for query in seen["request"]["queries"])
    assert len(seen["request"]["queries"]) == 6
    assert {round(float(query["strike"]), 8) for query in seen["request"]["queries"]} == {
        96.5,
        96.5625,
        96.625,
        96.6875,
        96.75,
    }

    offsets = sorted(point.atm_offset_bps for point in smile.points)
    assert offsets == pytest.approx([-12.5, -6.25, 0.0, 0.0, 6.25, 12.5])
    assert smile.points[0].strike_price <= smile.points[-1].strike_price


def test_sabr_smile_cache_roundtrip_preserves_object_and_evaluator(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 19)
    monkeypatch.setattr(mdp, "_qs_timeseries", lambda request: _make_qs_payload(as_of))

    smile = mdp.fetch_sabr_smile({"globex_symbol": "SR3_60", "as_of": as_of})
    payload = mdp._serialize_get_data_result("sabr_smile", {"sabr_smile": [smile]})
    restored = mdp._deserialize_get_data_result(payload)

    assert isinstance(restored, dict)
    restored_smile = restored["sabr_smile"][0]
    assert isinstance(restored_smile, STIRFutureOptionSABRSmile)

    probe = smile.points[3].strike_price
    assert restored_smile.normal_vol(probe) == pytest.approx(smile.normal_vol(probe), rel=1e-12)
    assert restored_smile.price_to_rate(probe) == pytest.approx(smile.price_to_rate(probe), rel=1e-12)


def test_qs_sabr_smile_common_cache_aliases_delta_and_offset_requests(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    as_of = datetime.date(2026, 3, 4)
    ny = pytz.timezone("America/New_York")
    cache_store = {}

    monkeypatch.setattr(
        mdp,
        "_resolve_sabr_smile_underlying_forward",
        lambda **kwargs: ("SFRU26", 96.61),
    )
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: cache_store.__setitem__(key, value))

    def _stub_qs(request):
        quote_ts = ny.localize(datetime.datetime.combine(request["start"], datetime.time(16, 0)))
        payload = {}
        for query in request["queries"]:
            if query["qv_value_type"] == "VolByStrike":
                right = "C" if query["option_type"] == "Call" else "P"
                strike = float(query["strike"])
                label = f"{query['globex_symbol']} {strike:.4f} {query['option_type']}"
                if strike == 96.625:
                    delta = 0.50 if right == "C" else -0.50
                elif strike == 96.5625:
                    delta = 0.25 if right == "C" else -0.25
                elif strike == 96.5:
                    delta = 0.40 if right == "C" else -0.40
                else:
                    delta = 0.25 if right == "C" else -0.25
                payload[label] = [
                    _make_strike_pricer(
                        label=label,
                        right=right,
                        strike=strike,
                        quote_ts=quote_ts,
                        iv_normal=0.14 + abs(96.625 - strike) * 0.10,
                        delta=delta,
                    )
                ]
                continue

            delta = int(query["delta"])
            right = "C" if query["option_type"] == "Call" else "P"
            if delta == 50:
                strike = 96.625
                delta_value = 0.50 if right == "C" else -0.50
            elif delta == 40:
                strike = 96.5 if right == "C" else 96.75
                delta_value = 0.40 if right == "C" else -0.40
            else:
                strike = 96.5625 if right == "C" else 96.6875
                delta_value = 0.25 if right == "C" else -0.25
            label = f"{query['globex_symbol']} {delta}D {query['option_type']}"
            pr = _make_strike_pricer(
                label=label,
                right=right,
                strike=strike,
                quote_ts=quote_ts,
                iv_normal=0.14 + abs(96.625 - strike) * 0.10,
                delta=delta_value,
            )
            pr._meta_data["qs_query"] = {
                "globex_symbol": query["globex_symbol"],
                "qv_value_type": query["qv_value_type"],
                "delta": delta,
                "option_type": query["option_type"],
            }
            payload[label] = [pr]
        return payload

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)

    delta_request = {
        "endpoint": "sabr_smile",
        "globex_symbol": "SR3U26",
        "as_of": as_of,
        "deltas": [25, 40, 50],
        "force_refresh": True,
    }
    offset_request = {
        "endpoint": "sabr_smile",
        "globex_symbol": "SR3U26",
        "as_of": as_of,
        "strike_offsets_bps": [6.25, 12.5],
    }

    delta_smile = mdp.get_data(delta_request)["sabr_smile"][0]
    offset_smile = mdp.get_data(offset_request)["sabr_smile"][0]

    common_keys = [key for key in cache_store if key.startswith("STIRFO_SABR_COMMON::")]
    assert len(common_keys) == 1
    assert offset_smile.points == delta_smile.points

    offset_cache_key = mdp._build_get_data_cache_key("sabr_smile", offset_request)
    assert offset_cache_key in cache_store


def test_select_sabr_smile_pricers_prefers_series_label_delta():
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    ts = pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 19, 16, 0))
    pr = _make_pricer(label="SR3_60 10D Call", right="P", delta=5, quote_ts=ts, iv_normal=0.21)
    pr._meta_data["qs_query"]["delta"] = 5
    pr._meta_data["qs_series_label"] = "SR3_60 10D Call"

    selected = mdp._select_sabr_smile_pricers(
        pricers_by_series={
            "SR3_60 10D Call": [pr],
            "SR3_60 10D Put": [_make_pricer(label="SR3_60 10D Put", right="P", delta=10, quote_ts=ts, iv_normal=0.148)],
        },
        as_of=datetime.date(2026, 3, 19),
        deltas=[10],
    )

    assert ("C", 10) in selected
    assert ("P", 10) in selected


def test_fetch_bulk_sabr_smile_qs_multi_symbol_multi_date_single_call_and_get_bulk_shape(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    ny = pytz.timezone("America/New_York")
    d1 = datetime.date(2026, 3, 19)
    d2 = datetime.date(2026, 3, 20)
    seen = {"requests": []}

    call_vols = {5: 0.24, 10: 0.21, 15: 0.19, 20: 0.175, 25: 0.165, 30: 0.157, 35: 0.151, 40: 0.147, 45: 0.144, 50: 0.142}
    put_vols = {5: 0.155, 10: 0.148, 15: 0.144, 20: 0.141, 25: 0.140, 30: 0.140, 35: 0.141, 40: 0.143, 45: 0.145, 50: 0.142}

    def _append_payload(payload, *, globex_symbol, underlying_symbol, as_of, forward, call_shift=0.0, put_shift=0.0):
        same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 0)))
        later_same_day = ny.localize(datetime.datetime.combine(as_of, datetime.time(16, 5)))
        for delta, vol in call_vols.items():
            label = f"{globex_symbol} {delta}D Call"
            pr = _make_pricer(
                label=label,
                right="C",
                delta=delta,
                quote_ts=same_day,
                iv_normal=vol + call_shift,
                forward=forward,
                underlying_symbol=underlying_symbol,
            )
            pr._meta_data["qs_query"]["globex_symbol"] = globex_symbol
            payload.setdefault(label, []).append(pr)
        later_pr = _make_pricer(
            label=f"{globex_symbol} 25D Call",
            right="C",
            delta=25,
            quote_ts=later_same_day,
            iv_normal=call_vols[25] + call_shift + 0.001,
            forward=forward,
            underlying_symbol=underlying_symbol,
        )
        later_pr._meta_data["qs_query"]["globex_symbol"] = globex_symbol
        payload[f"{globex_symbol} 25D Call"].append(later_pr)
        for delta, vol in put_vols.items():
            label = f"{globex_symbol} {delta}D Put"
            pr = _make_pricer(
                label=label,
                right="P",
                delta=delta,
                quote_ts=same_day,
                iv_normal=vol + put_shift,
                forward=forward,
                underlying_symbol=underlying_symbol,
            )
            pr._meta_data["qs_query"]["globex_symbol"] = globex_symbol
            payload.setdefault(label, []).append(pr)

    def _stub_qs(request):
        seen["requests"].append(request)
        payload = {}
        _append_payload(payload, globex_symbol="SR3_60", underlying_symbol="SFRM26", as_of=d1, forward=96.25)
        _append_payload(payload, globex_symbol="SR3_60", underlying_symbol="SFRM26", as_of=d2, forward=96.20, call_shift=0.004, put_shift=0.002)
        _append_payload(payload, globex_symbol="SR3_90", underlying_symbol="SFRU26", as_of=d1, forward=95.90, call_shift=0.006, put_shift=0.003)
        _append_payload(payload, globex_symbol="SR3_90", underlying_symbol="SFRU26", as_of=d2, forward=95.85, call_shift=0.009, put_shift=0.004)
        return payload

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)

    out = mdp.fetch_bulk_sabr_smile(
        {
            "globex_symbols": ["SR3_60", "SR3_90"],
            "timestamps": [d1, d2],
            "force_refresh": True,
        }
    )

    assert len(seen["requests"]) == 1
    assert seen["requests"][0]["start"] == d1
    assert seen["requests"][0]["end"] == d2
    assert len(seen["requests"][0]["queries"]) == 40
    assert set(out.keys()) == {"SR3_60", "SR3_90"}
    assert isinstance(out["SR3_60"][d1], STIRFutureOptionSABRSmile)
    assert out["SR3_60"][d1].underlying_contract == "SFRM26"
    assert out["SR3_90"][d2].underlying_contract == "SFRU26"

    bulk_out = mdp.get_bulk_data(
        {
            "endpoint": "sabr_smile",
            "globex_symbols": ["SR3_60", "SR3_90"],
            "timestamps": [d1, d2],
        }
    )

    assert len(seen["requests"]) == 1
    assert isinstance(bulk_out[d1]["SR3_60"][0], STIRFutureOptionSABRSmile)
    assert isinstance(bulk_out[d2]["SR3_90"][0], STIRFutureOptionSABRSmile)


def test_fetch_bulk_sabr_smile_qs_only_fetches_uncached_dates(monkeypatch):
    mdp = STIRFutureOptionMDP(source="STIRFO_DUAL-QL")
    d1 = datetime.date(2026, 3, 24)
    d2 = datetime.date(2026, 3, 25)
    seen = {"requests": []}
    cache_store = {}

    def _stub_qs(request):
        seen["requests"].append(request)
        return _make_qs_payload(request["start"])

    monkeypatch.setattr(mdp, "_qs_timeseries", _stub_qs)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: cache_store.__setitem__(key, value))

    seeded = mdp.fetch_sabr_smile({"globex_symbol": "SR3_60", "as_of": d1, "force_refresh": True})
    assert seeded.symbol == "SR3_60"
    cache_key = mdp._build_get_data_cache_key("sabr_smile", {"globex_symbol": "SR3_60", "as_of": d1})
    mdp._threadsafe_cache_put(
        cache_key,
        mdp._serialize_get_data_result("sabr_smile", {"sabr_smile": [seeded]}),
    )
    seen["requests"].clear()

    out = mdp.fetch_bulk_sabr_smile(
        {
            "globex_symbol": "SR3_60",
            "timestamps": [d1, d2],
        }
    )

    assert len(seen["requests"]) == 1
    assert seen["requests"][0]["start"] == d2
    assert seen["requests"][0]["end"] == d2
    assert d1 in out["SR3_60"]
    assert d2 in out["SR3_60"]
