import datetime

import pandas as pd
import pytz
import pytest

from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP


class _DummyCurve:
    def __getitem__(self, key):
        _ = key
        return 0.99


class _DummyCurveBuilder:
    def build_curve(self, curve_name, timestamp, kwargs=None, curve_only=True):
        _ = curve_name, timestamp, kwargs, curve_only
        return _DummyCurve()


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
