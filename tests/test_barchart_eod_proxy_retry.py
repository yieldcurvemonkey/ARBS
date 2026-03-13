import asyncio
import datetime

import httpx

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher


class _SequencedEodClient:
    def __init__(self):
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        request = httpx.Request("GET", url, headers=headers)
        if self.calls == 1:
            return httpx.Response(401, request=request, content=b"unauthorized")
        return httpx.Response(
            200,
            request=request,
            content=b"ZNM25,2025-01-15,1,2,3,4,5,6\n",
        )


class _RetryAfterEodClient:
    def __init__(self):
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        request = httpx.Request("GET", url, headers=headers)
        if self.calls == 1:
            return httpx.Response(429, request=request, headers={"Retry-After": "2.5"}, content=b"")
        return httpx.Response(
            200,
            request=request,
            content=b"ZNM25,2025-01-15,1,2,3,4,5,6\n",
        )


def test_fetch_eod_retries_proxy_auth_after_socks5_failure(monkeypatch):
    fetcher = BarchartFetcher(debug_verbose=False, info_verbose=False, error_verbose=False)
    client = _SequencedEodClient()
    token_calls = []
    sleep_calls = []

    def _fake_get_shared_session_token(dummy_symbol="BTC", force_refresh=False):
        token_calls.append((dummy_symbol, force_refresh))
        if len(token_calls) == 1:
            return ("laravel-1", "xsrf-1")
        if len(token_calls) == 2:
            raise RuntimeError(
                "SOCKSHTTPSConnectionPool(host='www.barchart.com', port=443): "
                "Failed to establish a new connection: SOCKS5 authentication failed"
            )
        return ("laravel-2", "xsrf-2")

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        return None

    monkeypatch.setattr(fetcher, "_get_shared_session_token", _fake_get_shared_session_token)
    monkeypatch.setattr("MDP.STIRFutures.BARCHART.BarchartFetcher.asyncio.sleep", _fake_sleep)

    out_symbol, out_df = asyncio.run(
        fetcher._fetch_eod_timeseries(
            client=client,
            symbol="ZNM25",
            start_date=datetime.datetime(2025, 1, 15),
            end_date=datetime.datetime(2025, 1, 15),
            set_dt_index=False,
            max_retries=3,
            backoff_factor=0,
        )
    )

    assert out_symbol == "ZNM25"
    assert out_df is not None and not out_df.empty
    assert client.calls == 2
    assert token_calls == [
        ("ZNM25", False),
        ("ZNM25", True),
        ("ZNM25", True),
    ]
    assert 60 in sleep_calls


def test_fetch_eod_retries_429_with_retry_after_and_rate_limiter(monkeypatch):
    fetcher = BarchartFetcher(debug_verbose=False, info_verbose=False, error_verbose=False)
    client = _RetryAfterEodClient()
    sleep_calls = []

    class _Limiter:
        def __init__(self):
            self.calls = 0

        async def acquire(self):
            self.calls += 1

    limiter = _Limiter()

    async def _fake_sleep(seconds):
        sleep_calls.append(seconds)
        return None

    monkeypatch.setattr("MDP.STIRFutures.BARCHART.BarchartFetcher.asyncio.sleep", _fake_sleep)

    out_symbol, out_df = asyncio.run(
        fetcher._fetch_eod_timeseries(
            client=client,
            symbol="ZNM25",
            start_date=datetime.datetime(2025, 1, 15),
            end_date=datetime.datetime(2025, 1, 15),
            set_dt_index=False,
            max_retries=2,
            backoff_factor=0,
            session_token=("laravel-1", "xsrf-1"),
            rate_limiter=limiter,
        )
    )

    assert out_symbol == "ZNM25"
    assert out_df is not None and not out_df.empty
    assert client.calls == 2
    assert limiter.calls == 2
    assert sleep_calls == [2.5]
    assert fetcher.get_history_statuses()["ZNM25"] == {
        "status_code": 200,
        "reason": "ok",
        "saw_429": True,
    }
