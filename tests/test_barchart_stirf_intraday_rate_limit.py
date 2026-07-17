"""Rate-limit handling for the intraday Barchart fetch path used by the STIRF backfill.

The MIX23 curve backfill fetches intraday futures ticks through
``STIRFutureMDP -> MDP.STIRFutures.BARCHART.BarchartFetcher.barchart_timeseries_api``
with ``interval=1``. Barchart publishes a hard budget on every response:

    x-ratelimit-limit: 60
    x-ratelimit-remaining: 0
    retry-after: 46
    x-ratelimit-reset: 1784268285

Historically the intraday branch was the *only* one not wired to the rate limiter,
and its retry loop special-cased solely 404 -- so a 429 fell through to a 1/2/4s
exponential backoff (inside a ~45s penalty window) and minted a fresh session token
on retry, so every 429 manufactured more requests. That turned 36 unique URLs into a
multi-thousand-request storm that never cleared. These tests pin the corrected
behaviour. All offline: no network, no real sleeping.
"""

import asyncio
import datetime

import httpx
import pytest

from MDP.STIRFutures.BARCHART.BarchartFetcher import AsyncRateLimiter, BarchartFetcher

CHICAGO = datetime.timezone(datetime.timedelta(hours=-5))


class _FakeResponse:
    def __init__(self, status_code, *, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        # httpx.Headers is case-insensitive, matching the real response object the
        # production code reads (`resp.headers.get("Retry-After")`).
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class _FakeClient:
    """Records every GET and replays a scripted sequence of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def get(self, url, headers=None):
        self.requests.append(url)
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


def _rate_limited_response(retry_after="46"):
    return _FakeResponse(
        429,
        content=b"<html>Too Many Requests</html>",
        headers={
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": "0",
            "retry-after": retry_after,
            "x-ratelimit-reset": "1784268285",
        },
    )


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """Capture asyncio.sleep durations instead of actually sleeping."""
    sleeps = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(seconds, *args, **kwargs):
        sleeps.append(float(seconds))
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    return sleeps


@pytest.fixture
def no_token_network(monkeypatch):
    """Fail loudly if the code fetches a session token (it should not on 429)."""
    calls = []

    async def _forbidden(self, *args, **kwargs):
        calls.append(kwargs.get("log_context", "token"))
        return ("laravel-refreshed", "xsrf-refreshed")

    monkeypatch.setattr(
        BarchartFetcher,
        "_get_shared_session_token_with_proxy_retry_async",
        _forbidden,
    )
    return calls


def _run_intraday_fetch(fetcher, client, **kwargs):
    snap = datetime.datetime(2026, 6, 1, 16, 0, tzinfo=CHICAGO)
    return asyncio.run(
        fetcher._fetch_intraday_timeseries(
            client=client,
            symbol="SQZ27",
            interval=1,
            start_date=snap - datetime.timedelta(minutes=11),
            end_date=snap + datetime.timedelta(minutes=1),
            session_token=("laravel-tok", "xsrf-tok"),
            **kwargs,
        )
    )


def test_429_sleeps_for_retry_after_not_exponential_backoff(recorded_sleeps, no_token_network):
    """A 429 must be honoured with the server's Retry-After, not a 1/2/4s guess."""
    fetcher = BarchartFetcher()
    client = _FakeClient([_rate_limited_response(retry_after="46")])

    _run_intraday_fetch(fetcher, client, max_retries=2, backoff_factor=1)

    assert recorded_sleeps, "expected the fetcher to back off on 429"
    assert all(s == pytest.approx(46.0) for s in recorded_sleeps), recorded_sleeps


def test_429_does_not_mint_new_session_tokens(recorded_sleeps, no_token_network):
    """A 429 is a rate-limit signal, not an auth failure.

    Minting a token costs an extra Barchart request from the same per-minute budget,
    so doing it on 429 makes the storm worse. Token refresh is reserved for 401/403.
    """
    fetcher = BarchartFetcher()
    client = _FakeClient([_rate_limited_response()])

    _run_intraday_fetch(fetcher, client, max_retries=3, backoff_factor=1)

    assert no_token_network == [], f"429 handling minted {len(no_token_network)} extra token request(s)"


def test_429_retries_are_bounded(recorded_sleeps, no_token_network):
    """A permanently rate-limited symbol must give up, not hammer forever."""
    fetcher = BarchartFetcher()
    client = _FakeClient([_rate_limited_response()])

    result = _run_intraday_fetch(fetcher, client, max_retries=2, backoff_factor=1)
    df = result[1]

    assert df is None
    assert len(client.requests) <= 2, f"issued {len(client.requests)} requests for max_retries=2"


def test_rate_limiter_is_applied_to_every_request(recorded_sleeps, no_token_network):
    """The limiter must gate each HTTP GET on the intraday path."""
    acquired = []

    class _CountingLimiter(AsyncRateLimiter):
        async def acquire(self):
            acquired.append(1)
            await super().acquire()

    fetcher = BarchartFetcher()
    limiter = _CountingLimiter(max_calls=60, period=60.0)
    client = _FakeClient([_FakeResponse(200, content=b"")])

    _run_intraday_fetch(fetcher, client, rate_limiter=limiter)

    assert len(acquired) == len(client.requests) == 1


def test_async_rate_limiter_enforces_budget_within_window():
    """max_calls within period: the (max_calls+1)-th call must wait for the window to roll."""

    async def _scenario():
        limiter = AsyncRateLimiter(max_calls=3, period=60.0)
        loop = asyncio.get_running_loop()
        start = loop.time()
        for _ in range(3):
            await limiter.acquire()
        assert loop.time() - start < 1.0  # first 3 are free

        waited = []
        real_sleep = asyncio.sleep

        async def _fake_sleep(seconds, *a, **k):
            waited.append(float(seconds))
            return await real_sleep(0)

        import unittest.mock

        with unittest.mock.patch.object(asyncio, "sleep", _fake_sleep):
            task = asyncio.ensure_future(limiter.acquire())
            await real_sleep(0)
            for _ in range(50):
                if waited:
                    break
                await real_sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert waited, "4th acquire did not wait"
        assert waited[0] > 50.0, f"expected ~60s wait, got {waited[0]}"

    asyncio.run(_scenario())


def test_default_intraday_rate_limit_matches_published_budget():
    """Barchart advertises x-ratelimit-limit: 60 per rolling minute on queryminutes."""
    assert BarchartFetcher._BARCHART_INTRADAY_RATE_LIMIT_MAX_CALLS <= 60
    assert BarchartFetcher._BARCHART_INTRADAY_RATE_LIMIT_PERIOD_SECONDS == 60.0


def test_barchart_timeseries_api_wires_limiter_into_intraday(monkeypatch):
    """End-to-end: the intraday branch of barchart_timeseries_api must build and pass
    a minute-windowed limiter down to each symbol fetch (regression for the bug where
    only the EOD branch was rate-limited)."""
    seen = {"limiters": []}

    async def _fake_intraday(self, *args, **kwargs):
        seen["limiters"].append(kwargs.get("rate_limiter"))
        return kwargs.get("symbol", args[1] if len(args) > 1 else "?"), None

    # Avoid all token/network machinery.
    def _fake_pool(self, size, dummy_symbol="BTC"):
        return [("laravel-tok", "xsrf-tok")]

    monkeypatch.setattr(BarchartFetcher, "_fetch_intraday_timeseries", _fake_intraday)
    monkeypatch.setattr(BarchartFetcher, "_get_shared_session_token_pool", _fake_pool)

    fetcher = BarchartFetcher()
    start = datetime.datetime(2026, 6, 1, 8, 0, tzinfo=CHICAGO)
    end = datetime.datetime(2026, 6, 1, 16, 0, tzinfo=CHICAGO)

    fetcher.barchart_timeseries_api(
        barchart_symbols=["SQZ27", "SQH27", "SQM27"],
        start_date=start,
        end_date=end,
        interval=1,
        one_df=True,
        show_tqdm=False,
        max_concurrent_tasks=4,
    )

    assert len(seen["limiters"]) == 3, seen["limiters"]
    assert all(isinstance(lim, AsyncRateLimiter) for lim in seen["limiters"]), seen["limiters"]
    # All symbols in one batch must SHARE a single limiter instance (one budget window).
    assert len({id(lim) for lim in seen["limiters"]}) == 1
    lim = seen["limiters"][0]
    assert lim.max_calls <= 60 and lim.period == 60.0
