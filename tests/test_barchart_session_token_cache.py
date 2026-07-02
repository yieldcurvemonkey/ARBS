import datetime
import threading
import time

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

    fetcher_a = BarchartFetcher(proxies=_proxy("atlanta.us.socks.nordhold.net"), session_token_ttl_seconds=60, session_token_scope="shared")
    fetcher_b = BarchartFetcher(proxies=_proxy("chicago.us.socks.nordhold.net"), session_token_ttl_seconds=60, session_token_scope="shared")

    fetcher_a._fetch_session_tokens(dummy_symbol="BTC")
    fetcher_b._fetch_session_tokens(dummy_symbol="ETH")

    assert fetcher_a._session_cache_key() == fetcher_b._session_cache_key()
    assert calls["count"] == 3

    rotated = [
        fetcher_a._get_shared_session_token()[0],
        fetcher_b._get_shared_session_token()[0],
        fetcher_a._get_shared_session_token()[0],
        fetcher_b._get_shared_session_token()[0],
    ]
    assert rotated == ["laravel-1", "laravel-2", "laravel-3", "laravel-1"]
    assert calls["count"] == 3

    BarchartFetcher.clear_shared_session_token_cache()


def test_shared_session_token_cache_ttl(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    # Pool warming fetches cold slots concurrently, so completion order (and thus
    # which laravel-N lands in which slot / becomes "current") is non-deterministic.
    # The contract that matters is the *count* of distinct fetches under the TTL and
    # that "current" is one of the freshly-warmed tokens -- assert those, not ordering.
    lock = threading.Lock()
    calls = {"count": 0}
    now = {"t": 1_000.0}

    def _fake_time():
        return now["t"]

    def _fake_new_token(self, dummy_symbol="BTC"):  # noqa: ARG001
        with lock:
            calls["count"] += 1
            n = calls["count"]
        return (f"laravel-{n}", f"xsrf-{n}")

    monkeypatch.setattr("MDP.STIRFutures.BARCHART.BarchartFetcher.time.time", _fake_time)
    monkeypatch.setattr(BarchartFetcher, "_get_new_session_token", _fake_new_token)

    fetcher = BarchartFetcher(session_token_ttl_seconds=60)
    fetcher._fetch_session_tokens(dummy_symbol="BTC")
    assert calls["count"] == 3
    assert fetcher._current_laravel_token in {"laravel-1", "laravel-2", "laravel-3"}

    now["t"] += 30
    fetcher._fetch_session_tokens(dummy_symbol="ETH")
    assert calls["count"] == 3  # still within TTL -> no new tokens
    assert fetcher._current_laravel_token in {"laravel-1", "laravel-2", "laravel-3"}

    now["t"] += 31
    fetcher._fetch_session_tokens(dummy_symbol="BTC")
    assert calls["count"] == 6  # TTL expired -> exactly pool_size fresh tokens
    assert fetcher._current_laravel_token in {"laravel-4", "laravel-5", "laravel-6"}

    BarchartFetcher.clear_shared_session_token_cache()


def test_proxy_auth_retries_zero_fails_fast_no_sleep(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    sleeps = []
    monkeypatch.setattr("MDP.STIRFutures.BARCHART.BarchartFetcher.time.sleep", lambda s: sleeps.append(s))

    def _socks_fail(self, dummy_symbol="BTC"):  # noqa: ARG001
        raise RuntimeError("SOCKS5 authentication failed")

    monkeypatch.setattr(BarchartFetcher, "_get_new_session_token", _socks_fail)

    # Fan-out worker style: 0 retries -> raise instantly, never sleep 60s.
    fast = BarchartFetcher(proxy_auth_retries=0)
    t0 = time.perf_counter()
    raised = False
    try:
        fast._get_new_session_token_with_proxy_retry("BTC")
    except RuntimeError:
        raised = True
    assert raised
    assert sleeps == []
    assert time.perf_counter() - t0 < 1.0

    # Single-proxy default: one 60s heal-and-retry is preserved.
    sleeps.clear()
    healer = BarchartFetcher(proxy_auth_retries=1)
    try:
        healer._get_new_session_token_with_proxy_retry("BTC")
    except RuntimeError:
        pass
    assert sleeps == [60]
    BarchartFetcher.clear_shared_session_token_cache()


def test_pool_warm_fetches_concurrently_and_exact(monkeypatch):
    BarchartFetcher.clear_shared_session_token_cache()
    lock = threading.Lock()
    calls = {"count": 0, "active": 0, "max_concurrent": 0}

    def _fake_new_token(self, dummy_symbol="BTC"):  # noqa: ARG001
        with lock:
            calls["count"] += 1
            calls["active"] += 1
            calls["max_concurrent"] = max(calls["max_concurrent"], calls["active"])
            n = calls["count"]
        time.sleep(0.15)
        with lock:
            calls["active"] -= 1
        return (f"laravel-{n}", f"xsrf-{n}")

    monkeypatch.setattr(BarchartFetcher, "_get_new_session_token", _fake_new_token)

    fetcher = BarchartFetcher(session_token_pool_size=8, session_token_ttl_seconds=60)
    t0 = time.perf_counter()
    pool = fetcher._get_shared_session_token_pool(8, "BTC")
    elapsed = time.perf_counter() - t0

    assert calls["count"] == 8  # exactly pool_size; no over-fetch under concurrency
    assert calls["max_concurrent"] >= 4  # genuinely parallel, not serialized
    assert elapsed < 0.15 * 8 * 0.5  # far below sequential wall time (~1.2s)
    assert len(pool) == 8
    assert all(isinstance(tp, tuple) and len(tp) == 2 for tp in pool)

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
