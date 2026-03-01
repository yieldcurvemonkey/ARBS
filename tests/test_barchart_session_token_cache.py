import datetime

import pandas as pd

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher


def _proxy(host: str) -> dict:
    url = f"http://shared-user:shared-pass@{host}:8080"
    return {"http": url, "https": url}


def test_shared_session_token_cache_reused_across_instances(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    calls = {"count": 0}

    def _fake_new_token(self, dummy_symbol="BTC"):  # noqa: ARG001
        calls["count"] += 1
        return (f"laravel-{calls['count']}", f"xsrf-{calls['count']}")

    monkeypatch.setattr(BarchartFetcher, "_get_new_session_token", _fake_new_token)

    fetcher_a = BarchartFetcher(proxies=_proxy("atlanta.us.socks.nordhold.net"), session_token_ttl_seconds=60)
    fetcher_b = BarchartFetcher(proxies=_proxy("chicago.us.socks.nordhold.net"), session_token_ttl_seconds=60)

    fetcher_a._fetch_session_tokens(dummy_symbol="BTC")
    fetcher_b._fetch_session_tokens(dummy_symbol="ETH")

    assert fetcher_a._session_cache_key() == fetcher_b._session_cache_key()
    assert calls["count"] == 1
    assert fetcher_a._current_laravel_token == "laravel-1"
    assert fetcher_b._current_laravel_token == "laravel-1"

    BarchartFetcher.clear_shared_session_token_cache()


def test_shared_session_token_cache_ttl(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    calls = {"count": 0}
    now = {"t": 1_000.0}

    def _fake_time():
        return now["t"]

    def _fake_new_token(self, dummy_symbol="BTC"):  # noqa: ARG001
        calls["count"] += 1
        return (f"laravel-{calls['count']}", f"xsrf-{calls['count']}")

    monkeypatch.setattr("MDP.STIRFutures.BARCHART.BarchartFetcher.time.time", _fake_time)
    monkeypatch.setattr(BarchartFetcher, "_get_new_session_token", _fake_new_token)

    fetcher = BarchartFetcher(session_token_ttl_seconds=60)
    fetcher._fetch_session_tokens(dummy_symbol="BTC")
    assert calls["count"] == 1
    assert fetcher._current_laravel_token == "laravel-1"

    now["t"] += 30
    fetcher._fetch_session_tokens(dummy_symbol="ETH")
    assert calls["count"] == 1
    assert fetcher._current_laravel_token == "laravel-1"

    now["t"] += 31
    fetcher._fetch_session_tokens(dummy_symbol="BTC")
    assert calls["count"] == 2
    assert fetcher._current_laravel_token == "laravel-2"

    BarchartFetcher.clear_shared_session_token_cache()


def test_barchart_timeseries_uses_shared_token_pool(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    calls = []
    fetcher = BarchartFetcher()

    def _fake_pool(size: int, dummy_symbol: str = "BTC"):  # noqa: ARG001
        calls.append(size)
        return [("laravel", "xsrf")] * size

    async def _fake_intraday_with_sem(*args, **kwargs):  # noqa: ARG001
        symbol = kwargs["symbol"]
        dt = kwargs["start_date"]
        return symbol, pd.DataFrame({"Date": [dt], "Close": [96.5]})

    monkeypatch.setattr(fetcher, "_get_shared_session_token_pool", _fake_pool)
    monkeypatch.setattr(fetcher, "_fetch_intraday_timeseries_with_semaphore", _fake_intraday_with_sem)

    out = fetcher.barchart_timeseries_api(
        barchart_symbols=["SQH26", "SQM26"],
        start_date=datetime.datetime(2026, 2, 1),
        end_date=datetime.datetime(2026, 2, 2),
        interval=1,
        max_concurrent_tasks=7,
        show_tqdm=False,
        one_df=False,
    )

    assert calls == [7]
    assert set(out.keys()) == {"SQH26", "SQM26"}

    BarchartFetcher.clear_shared_session_token_cache()
