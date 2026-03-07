import datetime

import MDP.USTFutures.USTFutureOptionMDP as ustfo_module
import pandas as pd
import pytz
import pytest

from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP
from Query.USTFutureOptions.backends.quantlib.QLUSTFutureOptionPricer import QLUSTFutureOptionPricer


class _DummyCurve:
    def __getitem__(self, key):
        _ = key
        return 0.99


class _DummyCurveBuilder:
    def build_curve(self, curve_name, timestamp, kwargs=None, curve_only=True):
        _ = curve_name, timestamp, kwargs, curve_only
        return _DummyCurve()


def _mk_option_pricer(
    *,
    symbol: str,
    quote_timestamp: datetime.datetime,
    expiry_date: datetime.date,
    iv_normal: float = 0.8,
    forward: float = 112.90625,
    fv01: float = 0.08,
    delta: float = 0.0,
    underlying_symbol: str = "ZNM26",
) -> QLUSTFutureOptionPricer:
    right = symbol[-1].upper()
    return QLUSTFutureOptionPricer(
        symbol=symbol,
        right=right,
        underlying_symbol=underlying_symbol,
        strike=forward,
        quote_timestamp=quote_timestamp,
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
        fv01=fv01,
        meta_data={},
    )


def test_live_snapshot_mid_and_last_fallback(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["ZNM26"]
            call_df = pd.DataFrame(
                [
                    {
                        "strikePrice": 112.5,
                        "bidPrice": 1.20,
                        "askPrice": 1.24,
                        "lastPrice": 1.22,
                        "tradeTime": 1760000000,
                    },
                    {
                        "strikePrice": 113.0,
                        "bidPrice": 0.0,
                        "askPrice": 0.0,
                        "lastPrice": 0.80,
                        "tradeTime": 1760000000,
                    },
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"ZNM26": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["interval"] == 1
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 3, 4, 10, 30))])
            return {"ZNM26": pd.DataFrame({"Open": [112.4], "High": [112.6], "Low": [112.3], "Close": [112.5]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["ZNM26|1125C", "ZNM26|1130C"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    p1 = out["ZNM26|1125C"][0]
    p2 = out["ZNM26|1130C"][0]
    assert p1.price() == 1.22  # mid from bid/ask
    assert p2.price() == 0.80  # last fallback


def test_option_timeseries_underlying_alignment_and_straddle_synthesis(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def barchart_timeseries_api(self, **kwargs):
            _ = kwargs
            idx = pd.DatetimeIndex([pd.Timestamp("2026-03-03"), pd.Timestamp("2026-03-04")])
            return {
                "ZNM26|1125C": pd.DataFrame(
                    {
                        "Open": [1.20, 1.25],
                        "High": [1.22, 1.27],
                        "Low": [1.18, 1.23],
                        "Close": [1.20, 1.25],
                        "Volume": [10, 12],
                        "Open Interest": [100, 102],
                    },
                    index=idx,
                ),
                "ZNM26|1125P": pd.DataFrame(
                    {
                        "Open": [0.70, 0.72],
                        "High": [0.72, 0.74],
                        "Low": [0.68, 0.70],
                        "Close": [0.70, 0.72],
                        "Volume": [9, 11],
                        "Open Interest": [90, 91],
                    },
                    index=idx,
                ),
                "ZNM26": pd.DataFrame(
                    {
                        "Open": [112.40, 112.50],
                        "High": [112.45, 112.55],
                        "Low": [112.35, 112.45],
                        "Close": [112.40, 112.50],
                        "Volume": [1000, 1200],
                        "Open Interest": [50000, 50010],
                    },
                    index=idx,
                ),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_timeseries",
            "symbols": ["ZNM26|1125S"],
            "start": datetime.date(2026, 3, 3),
            "end": datetime.date(2026, 3, 4),
            "show_tqdm": False,
        }
    )

    series = out["ZNM26|1125S"]
    assert len(series) == 2
    assert series[0].price() == 1.90
    assert series[1].price() == 1.97
    assert series[0].forward() == 112.40
    assert series[1].forward() == 112.50


def test_live_snapshot_atm_and_25d_aliases(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["ZNM26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 112.0, "bidPrice": 1.55, "askPrice": 1.60, "lastPrice": 1.57, "delta": 0.74, "tradeTime": 1760000000},
                    {"strikePrice": 112.5, "bidPrice": 1.20, "askPrice": 1.24, "lastPrice": 1.22, "delta": 0.50, "tradeTime": 1760000000},
                    {"strikePrice": 113.0, "bidPrice": 0.85, "askPrice": 0.89, "lastPrice": 0.87, "delta": 0.24, "tradeTime": 1760000000},
                ]
            )
            put_df = pd.DataFrame(
                [
                    {"strikePrice": 112.0, "bidPrice": 0.40, "askPrice": 0.44, "lastPrice": 0.42, "delta": -0.26, "tradeTime": 1760000000},
                    {"strikePrice": 112.5, "bidPrice": 0.70, "askPrice": 0.74, "lastPrice": 0.72, "delta": -0.50, "tradeTime": 1760000000},
                    {"strikePrice": 113.0, "bidPrice": 1.10, "askPrice": 1.14, "lastPrice": 1.12, "delta": -0.76, "tradeTime": 1760000000},
                ]
            )
            return {"ZNM26": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["interval"] == 1
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 3, 4, 10, 30))])
            return {"ZNM26": pd.DataFrame({"Open": [112.45], "High": [112.55], "Low": [112.40], "Close": [112.50]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["ZNM26|ATMS", "ZNM26|25DC"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    atm = out["ZNM26|ATMS"][0]
    d25 = out["ZNM26|25DC"][0]
    assert atm.symbol() == "ZNM26|1125S"
    assert atm.price() == pytest.approx(1.94)  # 1.22 call + 0.72 put
    assert d25.symbol() == "ZNM26|1130C"


def test_weekly_symbol_handling_and_underlying_mapping(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["BN1H26"]
            call_df = pd.DataFrame(
                [{"strikePrice": 112.75, "bidPrice": 1.10, "askPrice": 1.14, "lastPrice": 1.12, "tradeTime": 1760000000}]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"BN1H26": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["barchart_symbols"] == ["ZNM26"]
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 3, 4, 10, 30))])
            return {"ZNM26": pd.DataFrame({"Open": [112.70], "High": [112.80], "Low": [112.60], "Close": [112.75]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["BN1H26|11270C"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    p = out["BN1H26|11270C"][0]
    assert p.symbol() == "BN1H26|11270C"
    assert p.underlying_symbol() == "ZNM26"
    assert p.forward() == pytest.approx(112.75)


def test_historical_snapshot_atm_alias_and_delta_resolution(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["ZNM26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 112.0, "delta": 0.45},
                    {"strikePrice": 112.5, "delta": 0.32},
                    {"strikePrice": 113.0, "delta": 0.18},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"ZNM26": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            symbols = sorted(kwargs["barchart_symbols"])
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])
            out = {}
            for sym in symbols:
                if sym == "ZNM26":
                    out[sym] = pd.DataFrame({"Open": [112.52], "High": [112.54], "Low": [112.50], "Close": [112.52]}, index=idx)
                elif sym == "ZNM26|1125C":
                    out[sym] = pd.DataFrame({"Open": [1.20], "High": [1.22], "Low": [1.18], "Close": [1.20]}, index=idx)
                elif sym == "ZNM26|1125P":
                    out[sym] = pd.DataFrame({"Open": [0.70], "High": [0.72], "Low": [0.68], "Close": [0.70]}, index=idx)
                elif sym == "ZNM26|1120C":
                    out[sym] = pd.DataFrame({"Open": [1.55], "High": [1.58], "Low": [1.52], "Close": [1.55]}, index=idx)
                elif sym == "ZNM26|1130C":
                    out[sym] = pd.DataFrame({"Open": [0.85], "High": [0.88], "Low": [0.82], "Close": [0.85]}, index=idx)
                else:
                    out[sym] = pd.DataFrame(index=idx)
            return out

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    out_atm = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["ZNM26|ATMS"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )
    p_atm = out_atm["ZNM26|ATMS"][0]
    assert p_atm.symbol() == "ZNM26|1125S"
    assert p_atm.price() == pytest.approx(1.90)

    out_delta = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["ZNM26|25DC"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
            "force_refresh": True,
        }
    )
    p_delta = out_delta["ZNM26|25DC"][0]
    assert p_delta.symbol() in {"ZNM26|1125C", "ZNM26|1130C", "ZNM26|1120C"}


def test_historical_option_snapshot_request_cache_reuses_result(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def __init__(self):
            self.calls = 0

        def barchart_timeseries_api(self, **kwargs):
            self.calls += 1
            symbols = kwargs["barchart_symbols"]
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])
            out = {}
            for sym in symbols:
                if sym == "ZNM26":
                    out[sym] = pd.DataFrame({"Open": [112.52], "High": [112.54], "Low": [112.50], "Close": [112.52]}, index=idx)
                elif sym == "ZNM26|1125C":
                    out[sym] = pd.DataFrame({"Open": [1.20], "High": [1.22], "Low": [1.18], "Close": [1.20]}, index=idx)
                else:
                    out[sym] = pd.DataFrame(index=idx)
            return out

    dummy = _DummyBC()
    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: dummy)

    req = {
        "endpoint": "option_snapshot",
        "symbols": ["ZNM26|1125C"],
        "timestamp": datetime.date(2026, 2, 27),
        "show_tqdm": False,
        "curve_kwargs": {"cache_test_tag": "ust_hist_snapshot_cache"},
    }

    out1 = mdp.get_data(dict(req, force_refresh=True))
    calls_after_first = dummy.calls
    assert calls_after_first > 0
    assert "ZNM26|1125C" in out1

    out2 = mdp.get_data(req)
    assert "ZNM26|1125C" in out2
    assert dummy.calls == calls_after_first


def test_fetch_sabr_smile_barchart_uses_option_snapshot(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    as_of = datetime.date(2026, 3, 5)
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 5, 17, 0))
    expiry = datetime.date(2026, 4, 24)
    seen = {}

    call_vols = {5: 1.14, 10: 1.04, 15: 0.95, 20: 0.88, 25: 0.84, 30: 0.815, 35: 0.802, 40: 0.786, 45: 0.779, 50: 0.774}
    put_vols = {5: 0.79, 10: 0.748, 15: 0.727, 20: 0.721, 25: 0.724, 30: 0.733, 35: 0.745, 40: 0.756, 45: 0.766, 50: 0.774}

    def _stub_snapshot(request):
        seen["request"] = request
        out = {}
        for delta, vol in call_vols.items():
            out[f"TYM26|{delta}DC"] = [
                _mk_option_pricer(
                    symbol=f"ZNM26|{1120 + delta:04d}C",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                )
            ]
        for delta, vol in put_vols.items():
            out[f"TYM26|{delta}DP"] = [
                _mk_option_pricer(
                    symbol=f"ZNM26|{1120 + delta:04d}P",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                )
            ]
        return out

    class _DummyFuturePricer:
        def yield_to_maturity_from_price(self, future_price: float, curves=None) -> float:
            _ = curves
            return 0.12 - 0.00068 * float(future_price)

    monkeypatch.setattr(mdp, "_option_snapshot", _stub_snapshot)
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    smile = mdp.fetch_sabr_smile({"symbol": "TYM26", "as_of": as_of, "force_refresh": True})

    assert seen["request"]["endpoint"] == "option_snapshot"
    assert seen["request"]["timestamp"] == as_of
    assert seen["request"]["use_ql_calculator"] is True
    assert len(seen["request"]["symbols"]) == 20
    assert seen["request"]["symbols"][:3] == ["TYM26|5DC", "TYM26|10DC", "TYM26|15DC"]
    assert smile.source == "BARCHART_USTFO-QL"
    assert smile.globex_symbol == "TYM26"
    assert smile.underlying_contract == "ZNM26"
    assert smile.params.beta == pytest.approx(0.5)
    assert len(smile.points) == 20

    call_25 = next(pt for pt in smile.points if pt.right == "C" and pt.delta_abs == 25.0)
    assert call_25.label == "TYM26|25DC"
    assert call_25.iv_normal_price == pytest.approx(call_vols[25])


def test_fetch_sabr_smile_barchart_seeds_single_symbol_option_snapshot_cache(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    as_of = datetime.date(2026, 3, 5)
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 5, 17, 0))
    expiry = datetime.date(2026, 4, 24)
    seen = {"calls": 0}

    call_vols = {5: 1.14, 10: 1.04, 15: 0.95, 20: 0.88, 25: 0.84, 30: 0.815, 35: 0.802, 40: 0.786, 45: 0.779, 50: 0.774}
    put_vols = {5: 0.79, 10: 0.748, 15: 0.727, 20: 0.721, 25: 0.724, 30: 0.733, 35: 0.745, 40: 0.756, 45: 0.766, 50: 0.774}

    def _stub_snapshot(request):
        seen["calls"] += 1
        out = {}
        for delta, vol in call_vols.items():
            out[f"TYM26|{delta}DC"] = [
                _mk_option_pricer(
                    symbol=f"ZNM26|{1120 + delta:04d}C",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                )
            ]
        for delta, vol in put_vols.items():
            out[f"TYM26|{delta}DP"] = [
                _mk_option_pricer(
                    symbol=f"ZNM26|{1120 + delta:04d}P",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                )
            ]
        return out

    class _DummyFuturePricer:
        def yield_to_maturity_from_price(self, future_price: float, curves=None) -> float:
            _ = curves
            return 0.12 - 0.00068 * float(future_price)

    monkeypatch.setattr(mdp, "_option_snapshot", _stub_snapshot)
    monkeypatch.setattr(mdp, "_build_sabr_smile_conversion_pricer", lambda **kwargs: _DummyFuturePricer())

    smile = mdp.fetch_sabr_smile({"symbol": "TYM26", "as_of": as_of, "force_refresh": True})
    assert len(smile.points) == 20
    assert seen["calls"] == 1

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["TYM26|25DC"],
            "timestamp": as_of,
            "show_tqdm": False,
            "use_ql_calculator": True,
        }
    )

    assert seen["calls"] == 1
    assert "TYM26|25DC" in out
    assert out["TYM26|25DC"][0].iv_normal() == pytest.approx(call_vols[25])


def test_historical_delta_alias_resolution_uses_cme_strike_rules_for_monthly_contracts(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    seen = {}

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            seen["chain_symbols"] = list(symbols)
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 116.0, "delta": 0.11},
                    {"strikePrice": 117.0, "delta": 0.06},
                    {"strikePrice": 118.0, "delta": 0.03},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"ZBM26": {"call": call_df, "put": put_df}}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

    idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])
    monkeypatch.setattr(
        mdp,
        "_fetch_barchart_eod_series",
        lambda **kwargs: {"ZBM26": pd.DataFrame({"Open": [117.25], "High": [117.50], "Low": [117.00], "Close": [117.25]}, index=idx)},
    )

    def _stub_resolve(*, candidate_symbols, **kwargs):
        seen["candidate_symbols"] = list(candidate_symbols)
        return candidate_symbols[0]

    monkeypatch.setattr(mdp, "_resolve_historical_delta_from_pricers", _stub_resolve)

    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 2, 27, 17, 0))

    def _stub_window(*, leg_symbols, **kwargs):
        return {
            sym: {
                datetime.date(2026, 2, 27): _mk_option_pricer(
                    symbol=sym,
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 4, 24),
                    iv_normal=0.85,
                )
            }
            for sym in leg_symbols
        }

    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_window)

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["USM26|5DC"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
            "force_refresh": True,
        }
    )

    assert "USM26|5DC" in out
    assert seen["chain_symbols"] == ["ZBM26"]
    assert len(seen["candidate_symbols"]) == 5
    assert "ZBM26|11700C" in seen["candidate_symbols"]
    assert "ZBM26|11800C" in seen["candidate_symbols"]
    assert "ZBM26|11750C" not in seen["candidate_symbols"]
    strikes = [int(sym.split("|", 1)[1][:-1]) for sym in seen["candidate_symbols"]]
    assert max(strikes) - min(strikes) == 400
    assert all(strike % 100 == 0 for strike in strikes)


def test_fetch_bulk_sabr_smile_barchart_reuses_shared_window_and_seeds_cache(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    d1 = datetime.date(2026, 3, 4)
    d2 = datetime.date(2026, 3, 5)
    ny = pytz.timezone("America/New_York")
    seen = {"eod_calls": 0, "window_calls": 0, "conversion_calls": 0}

    class _DummyFuturePricer:
        def yield_to_maturity_from_price(self, future_price: float, curves=None) -> float:
            _ = curves
            return 0.12 - 0.00068 * float(future_price)

    monkeypatch.setattr(ustfo_module, "_cme_listed_strikes_for_contract_forward", lambda contract, forward, as_of: [112.5] if contract == "ZNM26" else [117.0])

    bc_ty = ustfo_module._contract_to_barchart_contract("ZNM26")
    bc_us = ustfo_module._contract_to_barchart_contract("ZBM26")
    ty_strike = ustfo_module._format_strike4(112.5, contract="ZNM26")
    us_strike = ustfo_module._format_strike4(117.0, contract="ZBM26")

    def _stub_eod_series(symbols, start, end, show_tqdm):
        _ = symbols, start, end, show_tqdm
        seen["eod_calls"] += 1
        idx = pd.DatetimeIndex([pd.Timestamp(d1), pd.Timestamp(d2)])
        return {
            bc_ty: pd.DataFrame({"Close": [112.5, 112.4375]}, index=idx),
            bc_us: pd.DataFrame({"Close": [117.0, 116.9375]}, index=idx),
        }

    def _stub_window(**kwargs):
        _ = kwargs
        seen["window_calls"] += 1
        expiry = datetime.date(2026, 4, 24)
        ts1 = ny.localize(datetime.datetime.combine(d1, datetime.time(17, 0)))
        ts2 = ny.localize(datetime.datetime.combine(d2, datetime.time(17, 0)))
        return {
            f"ZNM26|{ty_strike}C": {
                d1: _mk_option_pricer(symbol=f"ZNM26|{ty_strike}C", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.84, underlying_symbol="ZNM26"),
                d2: _mk_option_pricer(symbol=f"ZNM26|{ty_strike}C", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.845, forward=112.4375, underlying_symbol="ZNM26"),
            },
            f"ZNM26|{ty_strike}P": {
                d1: _mk_option_pricer(symbol=f"ZNM26|{ty_strike}P", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.724, underlying_symbol="ZNM26"),
                d2: _mk_option_pricer(symbol=f"ZNM26|{ty_strike}P", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.726, forward=112.4375, underlying_symbol="ZNM26"),
            },
            f"ZBM26|{us_strike}C": {
                d1: _mk_option_pricer(symbol=f"ZBM26|{us_strike}C", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.92, forward=117.0, fv01=0.16, underlying_symbol="ZBM26"),
                d2: _mk_option_pricer(symbol=f"ZBM26|{us_strike}C", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.925, forward=116.9375, fv01=0.16, underlying_symbol="ZBM26"),
            },
            f"ZBM26|{us_strike}P": {
                d1: _mk_option_pricer(symbol=f"ZBM26|{us_strike}P", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.79, forward=117.0, fv01=0.16, underlying_symbol="ZBM26"),
                d2: _mk_option_pricer(symbol=f"ZBM26|{us_strike}P", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.795, forward=116.9375, fv01=0.16, underlying_symbol="ZBM26"),
            },
        }

    def _stub_conversion(requirements, *, force_refresh):
        _ = force_refresh
        seen["conversion_calls"] += 1
        return {(underlying_contract, as_of): _DummyFuturePricer() for underlying_contract, as_of in requirements}

    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", _stub_eod_series)
    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_window)
    monkeypatch.setattr(mdp, "_build_bulk_sabr_smile_conversion_pricers", _stub_conversion)

    out = mdp.fetch_bulk_sabr_smile(
        {
            "symbols": ["TYM26", "USM26"],
            "timestamps": [d1, d2],
            "force_refresh": True,
        }
    )

    assert seen["eod_calls"] == 1
    assert seen["window_calls"] == 1
    assert seen["conversion_calls"] == 1
    assert set(out.keys()) == {"TYM26", "USM26"}
    assert out["TYM26"][d1].underlying_contract == "ZNM26"
    assert out["USM26"][d2].underlying_contract == "ZBM26"

    monkeypatch.setattr(
        mdp,
        "_option_snapshot",
        lambda request: (_ for _ in ()).throw(AssertionError("_option_snapshot should not run after bulk SABR cache seeding")),
    )
    cached = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["TYM26|25DC"],
            "timestamp": d1,
            "show_tqdm": False,
            "use_ql_calculator": True,
        }
    )

    assert "TYM26|25DC" in cached
    assert cached["TYM26|25DC"][0].iv_normal() == pytest.approx(0.84)
