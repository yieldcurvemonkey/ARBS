"""Known-answer tests for the cache-only network guard.

The guard exists to make an unattended listed-option harvest safe, so the thing
that must be proved is not that it usually works but that there is no hole: the
MDPs reach the network through ``requests.get``, through a pooled
``Session.request``, and through fetcher-owned sessions that bottom out in
``HTTPAdapter.send``. A patch on one layer leaves the others live, and the
failure mode of a hole is an overnight crawl against a vendor.

Every test here uses a URL that would be a real outbound call if the guard
leaked, and asserts it raised instead.
"""

import pytest
import requests

from RVUtils.ConvexityRV.listed_cache_guard import (
    CacheMissOffline,
    cache_only,
    network_calls_blocked,
    try_cached,
)

URL = "https://www.barchart.com/futures/quotes/ZBZ24%7C1450C/interactive-chart"


def test_module_level_get_is_blocked():
    with cache_only():
        with pytest.raises(CacheMissOffline):
            requests.get(URL, timeout=1)


def test_module_level_post_and_request_are_blocked():
    with cache_only():
        with pytest.raises(CacheMissOffline):
            requests.post(URL, timeout=1)
        with pytest.raises(CacheMissOffline):
            requests.request("GET", URL, timeout=1)


def test_session_request_is_blocked():
    """The pooled-session path -- a patch on requests.get alone misses this."""
    s = requests.Session()
    with cache_only():
        with pytest.raises(CacheMissOffline):
            s.get(URL, timeout=1)


def test_adapter_send_is_blocked():
    """The lowest layer, which fetcher-owned sessions bottom out in."""
    a = requests.adapters.HTTPAdapter()
    req = requests.Request("GET", URL).prepare()
    with cache_only():
        with pytest.raises(CacheMissOffline):
            a.send(req)


def test_everything_is_restored_afterwards():
    before = (requests.get, requests.post, requests.request,
              requests.Session.request, requests.adapters.HTTPAdapter.send)
    with cache_only():
        pass
    after = (requests.get, requests.post, requests.request,
             requests.Session.request, requests.adapters.HTTPAdapter.send)
    assert before == after


def test_restored_even_when_the_body_raises():
    before = requests.get
    with pytest.raises(ValueError):
        with cache_only():
            raise ValueError("boom")
    assert requests.get is before


def test_block_false_is_a_no_op():
    """The knob must not half-apply: with block=False nothing is patched."""
    before = requests.get
    with cache_only(block=False):
        assert requests.get is before


def test_blocked_calls_are_counted():
    start = network_calls_blocked()
    with cache_only():
        for _ in range(3):
            with pytest.raises(CacheMissOffline):
                requests.get(URL, timeout=1)
    assert network_calls_blocked() == start + 3


def test_try_cached_returns_none_instead_of_raising():
    class _MDP:
        def get_data(self, request):
            return requests.get(URL, timeout=1)

    start = network_calls_blocked()
    assert try_cached(_MDP(), {"endpoint": "sabr_smile"}) is None
    assert network_calls_blocked() == start + 1


def test_try_cached_passes_a_real_hit_through():
    class _MDP:
        def get_data(self, request):
            return {"sabr_smile": ["payload"]}

    assert try_cached(_MDP(), {"endpoint": "sabr_smile"}) == {"sabr_smile": ["payload"]}


def test_try_cached_does_not_mutate_the_callers_request():
    seen = {}

    class _MDP:
        def get_data(self, request):
            request["injected"] = True
            seen.update(request)
            return {"ok": 1}

    req = {"endpoint": "sabr_smile", "symbol": "SR3Z24"}
    try_cached(_MDP(), req)
    assert "injected" not in req, "the guard must hand the MDP a copy"
    assert seen.get("injected") is True
