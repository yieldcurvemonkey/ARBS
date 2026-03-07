import datetime

import MDP.STIRFutures.STIRFutureOptionMDP as stirfo_module
import pandas as pd
import pytz
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import QLSTIRFutureOptionPricer


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
    iv_normal: float = 0.14,
    forward: float = 96.25,
    delta: float = 0.0,
    underlying_symbol: str = "SFRZ30",
) -> QLSTIRFutureOptionPricer:
    right = symbol[-1].upper()
    return QLSTIRFutureOptionPricer(
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
        meta_data={},
    )


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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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


def test_live_delta_alias_prices_candidates_instead_of_vendor_call_delta(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 6, 11, 0))

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 95.5625, "lastPrice": 1.1725, "delta": 0.047433, "tradeTime": 1772797200},
                    {"strikePrice": 97.6250, "lastPrice": 0.0650, "delta": 0.947050, "tradeTime": 1772797200},
                    {"strikePrice": 98.1875, "lastPrice": 0.0350, "delta": 0.971772, "tradeTime": 1772797200},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"SQZ26": {"call": call_df, "put": put_df}}

    def _stub_build_pricer_from_row(**kwargs):
        sym = kwargs["canonical_symbol"]
        delta_map = {
            "SFRZ26|9556C": 0.9770,
            "SFRZ26|9762C": 0.1423,
            "SFRZ26|9818C": 0.0744,
        }
        if sym not in delta_map:
            return None
        return _mk_option_pricer(
            symbol=sym,
            quote_timestamp=quote_ts,
            expiry_date=datetime.date(2026, 12, 16),
            iv_normal=0.10,
            forward=96.67,
            delta=delta_map[sym],
            underlying_symbol="SFRZ26",
        )

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())
    monkeypatch.setattr(mdp, "_fetch_barchart_intraday_prices", lambda **kwargs: {"SQZ26": 96.67})
    monkeypatch.setattr(mdp, "_build_pricer_from_row", _stub_build_pricer_from_row)

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ26|5DC"],
            "timestamp": "live",
            "show_tqdm": False,
            "use_ql_calculator": True,
            "force_refresh": True,
        }
    )

    assert out["SFRZ26|5DC"][0].symbol() == "SFRZ26|9818C"


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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBCDelta())
    out_delta = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ30|25DC"],
            "timestamp": datetime.date(2026, 2, 27),
            "show_tqdm": False,
        }
    )
    p_delta = out_delta["SFRZ30|25DC"][0]
    assert p_delta.symbol() in {"SFRZ30|9625C", "SFRZ30|9650C"}


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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())

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
    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: dummy)

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


def test_barchart_pricer_window_force_refresh_bypasses_cached_window(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    target_date = datetime.date(2026, 2, 27)
    ny = pytz.timezone("America/New_York")

    cached = {
        "SFRZ30|9700C": {
            target_date: _mk_option_pricer(
                symbol="SFRZ30|9700C",
                quote_timestamp=ny.localize(datetime.datetime(2026, 2, 27, 17, 0)),
                expiry_date=datetime.date(2026, 12, 16),
                iv_normal=0.10,
                forward=96.25,
                delta=0.20,
                underlying_symbol="SFRZ30",
            )
        }
    }
    rebuilt = {
        "SFRZ30|9700C": {
            target_date: _mk_option_pricer(
                symbol="SFRZ30|9700C",
                quote_timestamp=ny.localize(datetime.datetime(2026, 2, 27, 17, 0)),
                expiry_date=datetime.date(2026, 12, 16),
                iv_normal=0.20,
                forward=96.25,
                delta=0.35,
                underlying_symbol="SFRZ30",
            )
        }
    }

    seen = {"builds": 0}
    cached_payload = mdp._serialize_pricer_window(cached)

    monkeypatch.setattr(mdp, "_historical_prefetch_window", lambda start, end: (start, end))
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: cached_payload)
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, value: None)
    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", lambda **kwargs: {})

    def _stub_build(**kwargs):
        seen["builds"] += 1
        return rebuilt

    monkeypatch.setattr(mdp, "_build_pricers_from_eod_window", _stub_build)

    hit = mdp._get_or_build_barchart_pricer_window(
        leg_symbols=["SFRZ30|9700C"],
        cache_symbols=["SFRZ30|9700C"],
        request_start=target_date,
        request_end=target_date,
        show_tqdm=False,
        price_mode="mid_then_fallback",
        curve_name="USD-SOFR-1D-Q12xM12STIRT",
        curve_kwargs={},
        use_ql_calculator=True,
        source="BARCHART_EOD_WINDOW",
        force_refresh=False,
    )
    assert hit["SFRZ30|9700C"][target_date].iv_normal() == pytest.approx(0.10)
    assert seen["builds"] == 0

    refreshed = mdp._get_or_build_barchart_pricer_window(
        leg_symbols=["SFRZ30|9700C"],
        cache_symbols=["SFRZ30|9700C"],
        request_start=target_date,
        request_end=target_date,
        show_tqdm=False,
        price_mode="mid_then_fallback",
        curve_name="USD-SOFR-1D-Q12xM12STIRT",
        curve_kwargs={},
        use_ql_calculator=True,
        source="BARCHART_EOD_WINDOW",
        force_refresh=True,
    )
    assert refreshed["SFRZ30|9700C"][target_date].iv_normal() == pytest.approx(0.20)
    assert seen["builds"] == 1


def test_historical_delta_alias_uses_listed_sofr_strike_tokens(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQU26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 96.1875, "delta": 0.31},
                    {"strikePrice": 96.3750, "delta": 0.29},
                    {"strikePrice": 96.4375, "delta": 0.25},
                    {"strikePrice": 96.6250, "delta": 0.11},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"SQU26": {"call": call_df, "put": put_df}}

    seen = {}
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 4, 17, 0))
    target_date = datetime.date(2026, 3, 4)

    def _stub_fetch_eod_series(*, symbols, start, end, show_tqdm):
        _ = start, end, show_tqdm
        idx = pd.DatetimeIndex([pd.Timestamp("2026-03-04")])
        out = {}
        for sym in symbols:
            if sym == "SQU26":
                out[sym] = pd.DataFrame({"Open": [96.61], "High": [96.62], "Low": [96.60], "Close": [96.61]}, index=idx)
        return out

    def _stub_pricer_window(**kwargs):
        seen["leg_symbols"] = list(kwargs["leg_symbols"])
        return {
            "SFRU26|9643C": {
                target_date: _mk_option_pricer(
                    symbol="SFRU26|9643C",
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 9, 16),
                    iv_normal=0.55,
                    forward=96.61,
                    delta=0.25,
                    underlying_symbol="SFRU26",
                )
            }
        }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())
    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", _stub_fetch_eod_series)
    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_pricer_window)

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRU26|25DC"],
            "timestamp": target_date,
            "show_tqdm": False,
            "use_ql_calculator": True,
            "force_refresh": True,
        }
    )

    assert out["SFRU26|25DC"][0].symbol() == "SFRU26|9643C"
    assert "SFRU26|9638C" not in seen["leg_symbols"]
    assert "SFRU26|9619C" not in seen["leg_symbols"]
    assert "SFRU26|9644C" not in seen["leg_symbols"]
    assert "SFRU26|9643C" in seen["leg_symbols"]
    assert "SFRU26|9637C" in seen["leg_symbols"]
    assert "SFRU26|9662C" in seen["leg_symbols"]


def test_historical_delta_alias_keeps_far_otm_call_candidates(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    seen = {}
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 5, 17, 0))
    target_date = datetime.date(2026, 3, 5)

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ26"]
            call_df = pd.DataFrame(
                [
                    {"strikePrice": 95.5625, "delta": 0.047433},
                    {"strikePrice": 97.6250, "delta": 0.947050},
                    {"strikePrice": 98.1875, "delta": 0.971772},
                ]
            )
            put_df = pd.DataFrame(columns=call_df.columns)
            return {"SQZ26": {"call": call_df, "put": put_df}}

    def _stub_fetch_eod_series(*, symbols, start, end, show_tqdm):
        _ = start, end, show_tqdm
        idx = pd.DatetimeIndex([pd.Timestamp("2026-03-05")])
        out = {}
        for sym in symbols:
            if sym == "SQZ26":
                out[sym] = pd.DataFrame({"Open": [96.67], "High": [96.68], "Low": [96.66], "Close": [96.67]}, index=idx)
        return out

    def _stub_pricer_window(**kwargs):
        seen["leg_symbols"] = list(kwargs["leg_symbols"])
        return {
            "SFRZ26|9762C": {
                target_date: _mk_option_pricer(
                    symbol="SFRZ26|9762C",
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 12, 16),
                    iv_normal=0.11,
                    forward=96.67,
                    delta=0.1423,
                    underlying_symbol="SFRZ26",
                )
            },
            "SFRZ26|9818C": {
                target_date: _mk_option_pricer(
                    symbol="SFRZ26|9818C",
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 12, 16),
                    iv_normal=0.10,
                    forward=96.67,
                    delta=0.0744,
                    underlying_symbol="SFRZ26",
                )
            },
        }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())
    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", _stub_fetch_eod_series)
    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_pricer_window)

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ26|5DC"],
            "timestamp": target_date,
            "show_tqdm": False,
            "use_ql_calculator": True,
            "force_refresh": True,
        }
    )

    assert "SFRZ26|9818C" in seen["leg_symbols"]
    assert out["SFRZ26|5DC"][0].symbol() == "SFRZ26|9818C"


def test_historical_delta_alias_wide_forward_slice_keeps_distinct_otm_puts(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _DummyCurveBuilder())

    class _DummyBC:
        def get_option_quotes(self, symbols, **kwargs):
            _ = kwargs
            assert symbols == ["SQZ26"]
            call_df = pd.DataFrame(columns=["strikePrice", "delta"])
            put_df = pd.DataFrame(
                [
                    {"strikePrice": 97.1250, "delta": -0.29},
                    {"strikePrice": 97.2500, "delta": -0.25},
                    {"strikePrice": 97.3750, "delta": -0.08},
                ]
            )
            return {"SQZ26": {"call": call_df, "put": put_df}}

    seen = {}
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 5, 17, 0))
    target_date = datetime.date(2026, 3, 5)

    def _stub_fetch_eod_series(*, symbols, start, end, show_tqdm):
        _ = start, end, show_tqdm
        idx = pd.DatetimeIndex([pd.Timestamp("2026-03-05")])
        out = {}
        for sym in symbols:
            if sym == "SQZ26":
                out[sym] = pd.DataFrame({"Open": [96.67], "High": [96.68], "Low": [96.66], "Close": [96.67]}, index=idx)
        return out

    def _stub_pricer_window(**kwargs):
        seen["leg_symbols"] = list(kwargs["leg_symbols"])
        return {
            "SFRZ26|9600P": {
                target_date: _mk_option_pricer(
                    symbol="SFRZ26|9600P",
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 12, 16),
                    iv_normal=0.63,
                    forward=96.67,
                    delta=-0.10,
                    underlying_symbol="SFRZ26",
                )
            },
            "SFRZ26|9637P": {
                target_date: _mk_option_pricer(
                    symbol="SFRZ26|9637P",
                    quote_timestamp=quote_ts,
                    expiry_date=datetime.date(2026, 12, 16),
                    iv_normal=0.64,
                    forward=96.67,
                    delta=-0.25,
                    underlying_symbol="SFRZ26",
                )
            },
        }

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda **kwargs: _DummyBC())
    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", _stub_fetch_eod_series)
    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_pricer_window)

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRZ26|10DP", "SFRZ26|25DP"],
            "timestamp": target_date,
            "show_tqdm": False,
            "use_ql_calculator": True,
            "force_refresh": True,
        }
    )

    assert out["SFRZ26|10DP"][0].symbol() == "SFRZ26|9600P"
    assert out["SFRZ26|25DP"][0].symbol() == "SFRZ26|9637P"
    assert "SFRZ26|9600P" in seen["leg_symbols"]


def test_fetch_sabr_smile_barchart_uses_option_snapshot(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    as_of = datetime.date(2026, 3, 19)
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 19, 17, 0))
    expiry = datetime.date(2026, 12, 16)
    seen = {}

    call_vols = {5: 0.24, 10: 0.21, 15: 0.19, 20: 0.175, 25: 0.165, 30: 0.157, 35: 0.151, 40: 0.147, 45: 0.144, 50: 0.142}
    put_vols = {5: 0.155, 10: 0.148, 15: 0.144, 20: 0.141, 25: 0.140, 30: 0.140, 35: 0.141, 40: 0.143, 45: 0.145, 50: 0.142}

    def _stub_snapshot(request):
        seen["request"] = request
        out = {}
        for delta, vol in call_vols.items():
            out[f"SR3Z30|{delta}DC"] = [
                _mk_option_pricer(
                    symbol=f"SFRZ30|{9600 + delta:04d}C",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                    underlying_symbol="SFRZ30",
                )
            ]
        for delta, vol in put_vols.items():
            out[f"SR3Z30|{delta}DP"] = [
                _mk_option_pricer(
                    symbol=f"SFRZ30|{9600 + delta:04d}P",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                    underlying_symbol="SFRZ30",
                )
            ]
        return out

    monkeypatch.setattr(mdp, "_option_snapshot", _stub_snapshot)

    smile = mdp.fetch_sabr_smile({"symbol": "SR3Z30", "as_of": as_of, "force_refresh": True})

    assert seen["request"]["endpoint"] == "option_snapshot"
    assert seen["request"]["timestamp"] == as_of
    assert seen["request"]["use_ql_calculator"] is True
    assert seen["request"]["delta_ignore_deep_itm"] is True
    assert len(seen["request"]["symbols"]) == 20
    assert seen["request"]["symbols"][:3] == ["SR3Z30|5DC", "SR3Z30|10DC", "SR3Z30|15DC"]
    assert smile.source == "BARCHART_STIRFO-QL"
    assert smile.symbol == "SR3Z30"
    assert smile.underlying_contract == "SFRZ30"
    assert smile.params.beta == pytest.approx(0.5)
    assert len(smile.points) == 20

    call_25 = next(pt for pt in smile.points if pt.right == "C" and pt.delta_abs == 25.0)
    assert call_25.label == "SR3Z30|25DC"
    assert call_25.iv_normal_price == pytest.approx(call_vols[25])
    assert call_25.strike_rate == pytest.approx(100.0 - call_25.strike_price)


def test_fetch_sabr_smile_barchart_seeds_single_symbol_option_snapshot_cache(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    as_of = datetime.date(2026, 3, 19)
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 3, 19, 17, 0))
    expiry = datetime.date(2026, 12, 16)
    seen = {"calls": 0}

    call_vols = {5: 0.24, 10: 0.21, 15: 0.19, 20: 0.175, 25: 0.165, 30: 0.157, 35: 0.151, 40: 0.147, 45: 0.144, 50: 0.142}
    put_vols = {5: 0.155, 10: 0.148, 15: 0.144, 20: 0.141, 25: 0.140, 30: 0.140, 35: 0.141, 40: 0.143, 45: 0.145, 50: 0.142}

    def _stub_snapshot(request):
        seen["calls"] += 1
        out = {}
        for delta, vol in call_vols.items():
            out[f"SFRU26|{delta}DC"] = [
                _mk_option_pricer(
                    symbol=f"SFRU26|{9600 + delta:04d}C",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                    underlying_symbol="SFRU26",
                )
            ]
        for delta, vol in put_vols.items():
            out[f"SFRU26|{delta}DP"] = [
                _mk_option_pricer(
                    symbol=f"SFRU26|{9600 + delta:04d}P",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=vol,
                    underlying_symbol="SFRU26",
                )
            ]
        return out

    monkeypatch.setattr(mdp, "_option_snapshot", _stub_snapshot)

    smile = mdp.fetch_sabr_smile({"symbol": "SFRU26", "as_of": as_of, "force_refresh": True})
    assert len(smile.points) == 20
    assert seen["calls"] == 1

    out = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRU26|25DC"],
            "timestamp": as_of,
            "show_tqdm": False,
            "use_ql_calculator": True,
        }
    )

    assert seen["calls"] == 1
    assert "SFRU26|25DC" in out
    assert out["SFRU26|25DC"][0].iv_normal() == pytest.approx(call_vols[25])


def test_fetch_sabr_smile_barchart_cm_alias_uses_option_snapshot(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    as_of = datetime.date(2026, 2, 27)
    ny = pytz.timezone("America/New_York")
    quote_ts = ny.localize(datetime.datetime(2026, 2, 27, 17, 0))
    expiry = datetime.date(2026, 6, 17)
    seen = {}

    def _stub_snapshot(request):
        seen["request"] = request
        out = {}
        for delta in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
            out[f"SFRCM1|{delta}DC"] = [
                _mk_option_pricer(
                    symbol=f"SFRH26|{9600 + delta:04d}C",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=0.13 + delta * 0.001,
                    underlying_symbol="SFRH26",
                )
            ]
            out[f"SFRCM1|{delta}DP"] = [
                _mk_option_pricer(
                    symbol=f"SFRH26|{9600 + delta:04d}P",
                    quote_timestamp=quote_ts,
                    expiry_date=expiry,
                    iv_normal=0.12 + delta * 0.0005,
                    underlying_symbol="SFRH26",
                )
            ]
        return out

    monkeypatch.setattr(mdp, "_option_snapshot", _stub_snapshot)

    smile = mdp.fetch_sabr_smile({"symbol": "SFRCM1", "as_of": as_of, "force_refresh": True})

    assert seen["request"]["symbols"][:3] == ["SFRCM1|5DC", "SFRCM1|10DC", "SFRCM1|15DC"]
    assert seen["request"]["delta_ignore_deep_itm"] is True
    assert smile.symbol == "SFRCM1"
    assert smile.underlying_contract == "SFRH26"
    assert len(smile.points) == 20
    call_25 = next(pt for pt in smile.points if pt.right == "C" and pt.delta_abs == 25.0)
    assert call_25.label == "SFRCM1|25DC"
    assert call_25.strike_rate == pytest.approx(100.0 - call_25.strike_price)


def test_fetch_bulk_sabr_smile_barchart_reuses_shared_window_and_seeds_cache(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    d1 = datetime.date(2026, 3, 19)
    d2 = datetime.date(2026, 3, 20)
    ny = pytz.timezone("America/New_York")
    seen = {"eod_calls": 0, "window_calls": 0}

    monkeypatch.setattr(stirfo_module, "_cme_listed_strikes_for_contract_forward", lambda contract, forward, as_of: [96.25] if contract == "SFRU26" else [95.75])

    bc_u = stirfo_module._contract_to_barchart_contract("SFRU26")
    bc_z = stirfo_module._contract_to_barchart_contract("SFRZ26")

    def _stub_eod_series(symbols, start, end, show_tqdm):
        _ = symbols, start, end, show_tqdm
        seen["eod_calls"] += 1
        idx = pd.DatetimeIndex([pd.Timestamp(d1), pd.Timestamp(d2)])
        return {
            bc_u: pd.DataFrame({"Close": [96.25, 96.20]}, index=idx),
            bc_z: pd.DataFrame({"Close": [95.75, 95.70]}, index=idx),
        }

    def _stub_window(**kwargs):
        _ = kwargs
        seen["window_calls"] += 1
        expiry = datetime.date(2026, 12, 16)
        ts1 = ny.localize(datetime.datetime.combine(d1, datetime.time(17, 0)))
        ts2 = ny.localize(datetime.datetime.combine(d2, datetime.time(17, 0)))
        return {
            "SFRU26|9625C": {
                d1: _mk_option_pricer(symbol="SFRU26|9625C", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.165, underlying_symbol="SFRU26"),
                d2: _mk_option_pricer(symbol="SFRU26|9625C", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.167, underlying_symbol="SFRU26"),
            },
            "SFRU26|9625P": {
                d1: _mk_option_pricer(symbol="SFRU26|9625P", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.140, underlying_symbol="SFRU26"),
                d2: _mk_option_pricer(symbol="SFRU26|9625P", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.141, underlying_symbol="SFRU26"),
            },
            "SFRZ26|9575C": {
                d1: _mk_option_pricer(symbol="SFRZ26|9575C", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.172, forward=95.75, underlying_symbol="SFRZ26"),
                d2: _mk_option_pricer(symbol="SFRZ26|9575C", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.174, forward=95.70, underlying_symbol="SFRZ26"),
            },
            "SFRZ26|9575P": {
                d1: _mk_option_pricer(symbol="SFRZ26|9575P", quote_timestamp=ts1, expiry_date=expiry, iv_normal=0.146, forward=95.75, underlying_symbol="SFRZ26"),
                d2: _mk_option_pricer(symbol="SFRZ26|9575P", quote_timestamp=ts2, expiry_date=expiry, iv_normal=0.148, forward=95.70, underlying_symbol="SFRZ26"),
            },
        }

    monkeypatch.setattr(mdp, "_fetch_barchart_eod_series", _stub_eod_series)
    monkeypatch.setattr(mdp, "_get_or_build_barchart_pricer_window", _stub_window)

    out = mdp.fetch_bulk_sabr_smile(
        {
            "symbols": ["SFRU26", "SFRZ26"],
            "timestamps": [d1, d2],
            "force_refresh": True,
        }
    )

    assert seen["eod_calls"] == 1
    assert seen["window_calls"] == 1
    assert set(out.keys()) == {"SFRU26", "SFRZ26"}
    assert out["SFRU26"][d1].underlying_contract == "SFRU26"
    assert out["SFRZ26"][d2].underlying_contract == "SFRZ26"

    monkeypatch.setattr(
        mdp,
        "_option_snapshot",
        lambda request: (_ for _ in ()).throw(AssertionError("_option_snapshot should not run after bulk SABR cache seeding")),
    )
    cached = mdp.get_data(
        {
            "endpoint": "option_snapshot",
            "symbols": ["SFRU26|25DC"],
            "timestamp": d1,
            "show_tqdm": False,
            "use_ql_calculator": True,
        }
    )

    assert "SFRU26|25DC" in cached
    assert cached["SFRU26|25DC"][0].iv_normal() == pytest.approx(0.165)
