import asyncio
import datetime

import pandas as pd
import pytz
import pytest

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher

try:
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
except Exception:  # pragma: no cover - optional dependency guard for local envs
    STIRFutureMDP = None


class _DummyResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.status_code = 200

    def raise_for_status(self):
        return None


class _DummyClient:
    def __init__(self, content: bytes):
        self.content = content
        self.urls = []

    async def get(self, url, headers=None):  # noqa: ARG002
        self.urls.append(url)
        return _DummyResponse(self.content)


def test_barchart_fetcher_parses_intraday_as_central_and_returns_request_tz():
    fetcher = BarchartFetcher(debug_verbose=False, error_verbose=True)
    client = _DummyClient(
        b"2025-01-02 10:30,0,95.00,95.10,94.90,95.05,100\n"
    )

    ny = pytz.timezone("America/New_York")
    request_ts = ny.localize(datetime.datetime(2025, 1, 2, 11, 30))
    out_symbol, out_df = asyncio.run(
        fetcher._fetch_intraday_timeseries(
            client=client,
            symbol="SQH26",
            interval=1,
            start_date=request_ts,
            end_date=request_ts,
            set_dt_index=True,
            session_token=("laravel", "xsrf"),
        )
    )

    assert out_symbol == "SQH26"
    assert out_df is not None and not out_df.empty
    assert "end=202501021030" in client.urls[0]
    assert out_df.index[0] == pd.Timestamp(request_ts)


@pytest.mark.skipif(STIRFutureMDP is None, reason="STIRFutureMDP optional dependencies not available")
def test_stir_mdp_fetch_window_is_central_for_non_central_request(monkeypatch):
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    captured = {}

    class _DummyFetcher:
        def barchart_timeseries_api(self, **kwargs):
            captured.update(kwargs)
            return pd.DataFrame(
                {"SQH26": [95.05]},
                index=pd.DatetimeIndex([kwargs["end_date"]]),
            )

    monkeypatch.setattr(mdp, "_get_barchart_fetcher", lambda: _DummyFetcher())

    ny = pytz.timezone("America/New_York")
    ts_ny = ny.localize(datetime.datetime(2025, 1, 2, 11, 30))
    out = mdp._fetch_barchart_timeseries(
        tickers=["SR3H26"],
        ts_dt=ts_ny,
        show_tqdm=False,
        interval=1,
        window_minutes=2,
        full_day_intraday=False,
    )

    start = captured["start_date"]
    end = captured["end_date"]

    assert getattr(start.tzinfo, "zone", None) == "America/Chicago"
    assert getattr(end.tzinfo, "zone", None) == "America/Chicago"
    assert (start.hour, start.minute) == (10, 28)
    assert (end.hour, end.minute) == (10, 32)
    assert list(out.columns) == ["SR3H26"]


@pytest.mark.skipif(STIRFutureMDP is None, reason="STIRFutureMDP optional dependencies not available")
def test_stir_mdp_matches_central_quote_for_eastern_timestamp(monkeypatch):
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    mem_cache = {}

    monkeypatch.setattr(mdp, "_ensure_pricer_cache", lambda: None)
    monkeypatch.setattr(mdp, "_threadsafe_cache_get", lambda key: mem_cache.get(key))
    monkeypatch.setattr(mdp, "_threadsafe_cache_put", lambda key, val: mem_cache.__setitem__(key, val))
    monkeypatch.setattr(mdp, "_build_pricer_from_args", lambda args, fixings_memo=None: args)

    chi = pytz.timezone("America/Chicago")
    idx = pd.DatetimeIndex(
        [
            chi.localize(datetime.datetime(2025, 1, 2, 10, 29)),
            chi.localize(datetime.datetime(2025, 1, 2, 10, 30)),
            chi.localize(datetime.datetime(2025, 1, 2, 10, 31)),
        ]
    )
    px_df = pd.DataFrame({"SR3H26": [95.00, 95.10, 95.20]}, index=idx)
    monkeypatch.setattr(mdp, "_fetch_barchart_timeseries", lambda *args, **kwargs: px_df)

    ny = pytz.timezone("America/New_York")
    ts_ny = ny.localize(datetime.datetime(2025, 1, 2, 11, 30))
    out = mdp._get_data_for_timestamp(
        symbols=["SR3H26"],
        timestamp=ts_ny,
        show_tqdm=False,
        force_refresh=True,
    )

    chosen = out["SR3H26"][0]
    assert chosen["price"] == 95.10
    assert chosen["timestamp"] == "2025-01-02T16:30:00+00:00"
