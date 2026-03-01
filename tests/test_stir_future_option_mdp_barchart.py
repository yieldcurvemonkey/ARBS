import datetime

import pandas as pd
import pytz
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


class _DummyCurve:
    def __getitem__(self, key):
        _ = key
        return 0.99


class _DummyCurveBuilder:
    def build_curve(self, curve_name, timestamp, kwargs=None, curve_only=True):
        _ = curve_name, timestamp, kwargs, curve_only
        return _DummyCurve()


def test_live_snapshot_mid_and_last_fallback(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ30"]
            call_df = pd.DataFrame(
                [
                    {
                        "strikePrice": 97.0,
                        "bidPrice": 0.10,
                        "askPrice": 0.12,
                        "lastPrice": 0.11,
                        "tradeTime": 1760000000,
                    },
                    {
                        "strikePrice": 98.0,
                        "bidPrice": 0.0,
                        "askPrice": 0.0,
                        "lastPrice": 0.05,
                        "tradeTime": 1760000000,
                    },
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"SQZ30": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["interval"] == 1
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 1, 2, 10, 30))])
            return {"SQZ30": pd.DataFrame({"Open": [96.90], "High": [97.10], "Low": [96.80], "Close": [97.00]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SR3Z30|9700C", "SR3Z30|9800C"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    p1 = out["SR3Z30|9700C"][0]
    p2 = out["SR3Z30|9800C"][0]
    assert p1.price() == 0.11  # mid from bid/ask
    assert p2.price() == 0.05  # last fallback


def test_option_timeseries_underlying_alignment_and_straddle_synthesis(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def barchart_timeseries_api(self, **kwargs):
            _ = kwargs
            idx = pd.DatetimeIndex([pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")])
            return {
                "SQZ30|9700C": pd.DataFrame(
                    {
                        "Open": [0.10, 0.12],
                        "High": [0.11, 0.13],
                        "Low": [0.09, 0.11],
                        "Close": [0.10, 0.12],
                        "Volume": [10, 12],
                        "Open Interest": [100, 102],
                    },
                    index=idx,
                ),
                "SQZ30|9700P": pd.DataFrame(
                    {
                        "Open": [0.07, 0.06],
                        "High": [0.08, 0.07],
                        "Low": [0.06, 0.05],
                        "Close": [0.07, 0.06],
                        "Volume": [9, 11],
                        "Open Interest": [90, 91],
                    },
                    index=idx,
                ),
                "SQZ30": pd.DataFrame(
                    {
                        "Open": [96.00, 96.10],
                        "High": [96.05, 96.15],
                        "Low": [95.95, 96.05],
                        "Close": [96.00, 96.10],
                        "Volume": [1000, 1200],
                        "Open Interest": [50000, 50010],
                    },
                    index=idx,
                ),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_timeseries",
            "symbols": ["SR3Z30|9700S"],
            "start": datetime.date(2026, 1, 2),
            "end": datetime.date(2026, 1, 3),
            "show_tqdm": False,
        }
    )

    series = out["SR3Z30|9700S"]
    assert len(series) == 2
    assert series[0].price() == 0.17
    assert series[1].price() == 0.18
    assert series[0].forward() == 96.00
    assert series[1].forward() == 96.10


def test_live_snapshot_atm_and_25d_aliases(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ30"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 95.75, "bidPrice": 0.18, "askPrice": 0.20, "lastPrice": 0.19, "delta": 0.52, "tradeTime": 1760000000},
                    {"strikePrice": 96.00, "bidPrice": 0.15, "askPrice": 0.17, "lastPrice": 0.16, "delta": 0.50, "tradeTime": 1760000000},
                    {"strikePrice": 96.25, "bidPrice": 0.11, "askPrice": 0.13, "lastPrice": 0.12, "delta": 0.24, "tradeTime": 1760000000},
                ]
            )
            put_df = pd.DataFrame(
                [
                    {"strikePrice": 95.75, "bidPrice": 0.07, "askPrice": 0.09, "lastPrice": 0.08, "delta": -0.48, "tradeTime": 1760000000},
                    {"strikePrice": 96.00, "bidPrice": 0.10, "askPrice": 0.12, "lastPrice": 0.11, "delta": -0.50, "tradeTime": 1760000000},
                    {"strikePrice": 96.25, "bidPrice": 0.16, "askPrice": 0.18, "lastPrice": 0.17, "delta": -0.76, "tradeTime": 1760000000},
                ]
            )
            return {"SQZ30": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["interval"] == 1
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 1, 2, 10, 30))])
            return {"SQZ30": pd.DataFrame({"Open": [95.95], "High": [96.05], "Low": [95.90], "Close": [96.00]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ30|ATMS", "SFRZ30|25DC"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    atm = out["SFRZ30|ATMS"][0]
    d25 = out["SFRZ30|25DC"][0]
    assert atm.symbol() == "SFRZ30|9600S"
    assert atm.price() == pytest.approx(0.27)  # 0.16 call + 0.11 put
    assert d25.symbol() == "SFRZ30|9625C"


def test_historical_snapshot_atm_alias_and_delta_rejection(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def barchart_timeseries_api(self, **kwargs):
            symbols = kwargs["barchart_symbols"]
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])
            out = {}
            for sym in symbols:
                if sym == "SQZ30":
                    out[sym] = pd.DataFrame({"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]}, index=idx)
                elif sym == "SQZ30|9625C":
                    out[sym] = pd.DataFrame({"Open": [0.11], "High": [0.12], "Low": [0.10], "Close": [0.11]}, index=idx)
                elif sym == "SQZ30|9625P":
                    out[sym] = pd.DataFrame({"Open": [0.08], "High": [0.09], "Low": [0.07], "Close": [0.08]}, index=idx)
                else:
                    out[sym] = pd.DataFrame(index=idx)
            return out

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ30|ATMS"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )
    p = out["SFRZ30|ATMS"][0]
    assert p.symbol() == "SFRZ30|9625S"
    assert p.price() == pytest.approx(0.19)

    class _DummyBCDelta:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ30"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 96.00, "delta": 0.45},
                    {"strikePrice": 96.25, "delta": 0.24},
                    {"strikePrice": 96.50, "delta": 0.12},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"SQZ30": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            symbols = sorted(kwargs["barchart_symbols"])
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])
            out = {}
            for sym in symbols:
                if sym == "SQZ30":
                    out[sym] = pd.DataFrame({"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]}, index=idx)
                elif sym == "SQZ30|9600C":
                    out[sym] = pd.DataFrame({"Open": [0.20], "High": [0.21], "Low": [0.19], "Close": [0.20], "delta": [0.45]}, index=idx)
                elif sym == "SQZ30|9625C":
                    out[sym] = pd.DataFrame({"Open": [0.12], "High": [0.13], "Low": [0.11], "Close": [0.12], "delta": [0.25]}, index=idx)
                elif sym == "SQZ30|9650C":
                    out[sym] = pd.DataFrame({"Open": [0.06], "High": [0.07], "Low": [0.05], "Close": [0.06], "delta": [0.12]}, index=idx)
                else:
                    out[sym] = pd.DataFrame(index=idx)
            return out

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBCDelta())
    out_delta = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ30|25DC"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )
    p_delta = out_delta["SFRZ30|25DC"][0]
    assert p_delta.symbol() == "SFRZ30|9625C"


def test_midcurve_live_snapshot_uses_sfr_underlying_forward(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            # 0Q maps to MMA option root.
            assert symbols == ["MMAH26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 97.0, "bidPrice": 0.10, "askPrice": 0.12, "lastPrice": 0.11, "tradeTime": 1760000000},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"MMAH26": {"call": call_df, "put": put_df}}

        def barchart_timeseries_api(self, **kwargs):
            assert kwargs["interval"] == 1
            # 0QH26 underlying should be SFRH27 -> SQH27
            assert kwargs["barchart_symbols"] == ["SQH27"]
            idx = pd.DatetimeIndex([pytz.timezone("America/Chicago").localize(datetime.datetime(2026, 1, 2, 10, 30))])
            return {"SQH27": pd.DataFrame({"Open": [96.90], "High": [97.10], "Low": [96.80], "Close": [97.00]}, index=idx)}

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["0QH26|9700C"],
            "timestamp": "live",
            "show_tqdm": False,
        }
    )

    p = out["0QH26|9700C"][0]
    assert p.symbol() == "0QH26|9700C"
    assert p.underlying_symbol() == "SFRH27"
    assert p.forward() == pytest.approx(97.0)


def test_constant_maturity_alias_snapshot_resolves_contract(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def barchart_timeseries_api(self, **kwargs):
            symbols = sorted(kwargs["barchart_symbols"])
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])

            # First call: underlying probe for CM resolution.
            if symbols == ["SQH26"]:
                return {
                    "SQH26": pd.DataFrame(
                        {"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]},
                        index=idx,
                    )
                }

            # Second call: options + underlying for pricing.
            assert symbols == ["SQH26", "SQH26|9625C", "SQH26|9625P"]
            return {
                "SQH26|9625C": pd.DataFrame({"Open": [0.11], "High": [0.12], "Low": [0.10], "Close": [0.11]}, index=idx),
                "SQH26|9625P": pd.DataFrame({"Open": [0.08], "High": [0.09], "Low": [0.07], "Close": [0.08]}, index=idx),
                "SQH26": pd.DataFrame({"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]}, index=idx),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRCM1|ATMS"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )

    p = out["SFRCM1|ATMS"][0]
    assert p.symbol() == "SFRH26|9625S"
    assert p.underlying_symbol() == "SFRH26"
    assert p.price() == pytest.approx(0.19)


def test_midcurve_constant_maturity_alias_snapshot_resolves_contract(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def barchart_timeseries_api(self, **kwargs):
            symbols = sorted(kwargs["barchart_symbols"])
            idx = pd.DatetimeIndex([pd.Timestamp("2026-02-27")])

            # First call: underlying probe for CM resolution.
            # S0CM1 -> internal canonical 0QH26 -> underlying SFRH27 -> SQH27.
            if symbols == ["SQH27"]:
                return {
                    "SQH27": pd.DataFrame(
                        {"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]},
                        index=idx,
                    )
                }

            # Second call: options + underlying for pricing.
            assert symbols == ["MMAH26|9625C", "MMAH26|9625P", "SQH27"]
            return {
                "MMAH26|9625C": pd.DataFrame({"Open": [0.11], "High": [0.12], "Low": [0.10], "Close": [0.11]}, index=idx),
                "MMAH26|9625P": pd.DataFrame({"Open": [0.08], "High": [0.09], "Low": [0.07], "Close": [0.08]}, index=idx),
                "SQH27": pd.DataFrame({"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]}, index=idx),
            }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyBC())

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["S0CM1|ATMS"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )

    p = out["S0CM1|ATMS"][0]
    # S0 alias is normalized to 0Q internally.
    assert p.symbol() == "0QH26|9625S"
    assert p.underlying_symbol() == "SFRH27"
    assert p.price() == pytest.approx(0.19)


def test_historical_option_snapshot_request_cache_reuses_result(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
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
                if sym == "SQZ31":
                    out[sym] = pd.DataFrame({"Open": [96.23], "High": [96.25], "Low": [96.20], "Close": [96.24]}, index=idx)
                elif sym == "SQZ31|9700C":
                    out[sym] = pd.DataFrame({"Open": [0.11], "High": [0.12], "Low": [0.10], "Close": [0.11]}, index=idx)
                else:
                    out[sym] = pd.DataFrame(index=idx)
            return out

    dummy = _DummyBC()
    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: dummy)

    req = {
        "endpoint": "option_snapshot",
        "symbols": ["SFRZ31|9700C"],
        "timestamp": datetime.date(2026, 2, 27),
        "show_tqdm": False,
        "curve_kwargs": {"cache_test_tag": "hist_snapshot_cache"},
    }

    out1 = mdp.get_data(dict(req, force_refresh=True))
    calls_after_first = dummy.calls
    assert calls_after_first > 0
    assert "SFRZ31|9700C" in out1

    out2 = mdp.get_data(req)
    assert "SFRZ31|9700C" in out2
    assert dummy.calls == calls_after_first
