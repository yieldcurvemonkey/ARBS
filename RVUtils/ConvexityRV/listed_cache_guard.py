"""Cache-only access to the listed-option MDPs.

``STIRFutureOptionMDP`` and ``USTFutureOptionMDP`` are demand-driven: a request
they cannot serve from disk goes to Barchart, one HTTP call per strike. Measured
on a single miss (``ZBZ24`` SABR smile, 2024-09-03) that is a 404 storm running
at roughly two calls a second across the whole strike ladder -- minutes per
symbol-date, and the payload does not exist anyway. Neither MDP has an offline
switch, and the cache keys are SHA-1 hashes, so there is no way to enumerate
what is present and no way to ask "is this cached?" without risking the fetch.

So the guard is imposed from outside: block outbound HTTP for the duration of
the call and let a miss raise immediately.

    with cache_only():
        out = mdp.get_data({"endpoint": "sabr_smile", "symbol": "SR3Z24", ...})

or, tolerantly::

    out = try_cached(mdp, {...})     # -> None on a miss, in microseconds

This is what makes an unattended harvest safe: the worst case for a wholly
uncached universe is a fast sweep of Nones rather than an overnight crawl
against a vendor. It is deliberately a blunt instrument -- it blackholes *all*
``requests`` and ``httpx`` traffic in the calling process, not just Barchart's --
because the alternative is guessing which of several fetcher classes and session
objects a 6,900-line MDP will reach for. That guess was in fact wrong once: the
Barchart STIR path is ``httpx.AsyncClient``, and until 2026-08-19 only the
``requests`` layer was patched, so the guarantee rested on the session-token
fetch raising first. It no longer does.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any, Dict, Optional

__all__ = ["CacheMissOffline", "cache_only", "try_cached", "network_calls_blocked"]


class CacheMissOffline(RuntimeError):
    """Raised in place of an outbound request while :func:`cache_only` is active."""


#: Incremented every time a call is blocked, so a harvest can report how much
#: network it would have done. Not thread-local: it is a global tally.
_BLOCKED = {"n": 0}
_LOCK = threading.Lock()


def network_calls_blocked() -> int:
    """How many outbound requests have been refused since import."""
    with _LOCK:
        return int(_BLOCKED["n"])


def _blocked(*args: Any, **kwargs: Any):
    with _LOCK:
        _BLOCKED["n"] += 1
    url = ""
    for a in args:
        if isinstance(a, str) and "://" in a:
            url = a
            break
    raise CacheMissOffline(
        f"outbound HTTP blocked by cache_only(){' for ' + url[:120] if url else ''}"
    )


async def _blocked_async(*args: Any, **kwargs: Any):
    """``httpx.AsyncClient.send`` is a coroutine; a sync stub would not await."""
    return _blocked(*args, **kwargs)


@contextlib.contextmanager
def cache_only(*, block: bool = True):
    """Refuse all outbound ``requests`` **and** ``httpx`` traffic inside the block.

    ``block=False`` makes this a no-op, so a caller can expose the behaviour as
    a config knob without branching at every call site.

    Patches the module-level helpers *and* ``Session.request`` /
    ``HTTPAdapter.send``: the MDPs use ``requests.get`` directly in some paths
    and a pooled ``Session`` in others, and the fetchers build their own
    sessions, so patching only one layer leaves a hole.

    **``httpx`` is patched too, and that is not belt-and-braces.** The Barchart
    data path is ``httpx.AsyncClient``
    (``MDP/STIRFutures/BARCHART/BarchartFetcher.py:1248, 1343-1347``), not
    ``requests``. Before 2026-08-19 this guard stopped a Barchart crawl only
    *indirectly* -- the session-token fetch goes through ``requests`` and raised
    first, so the httpx call was never reached. Measured at the time: 17 requests
    calls blocked, 0 httpx calls escaped. That guarantee held by accident of
    ordering; anything that memoised a token, or any future path reaching httpx
    without one, would have been unguarded. Both ``httpx.Client.send`` and
    ``httpx.AsyncClient.send`` are now blocked directly, so the guarantee is
    structural. ``httpx`` is optional: if it is not installed, nothing is patched
    and nothing breaks.
    """
    if not block:
        yield
        return

    import requests
    import requests.adapters

    saved = {
        "get": requests.get,
        "post": requests.post,
        "request": requests.request,
        "Session.request": requests.Session.request,
        "HTTPAdapter.send": requests.adapters.HTTPAdapter.send,
    }
    requests.get = _blocked
    requests.post = _blocked
    requests.request = _blocked
    requests.Session.request = _blocked
    requests.adapters.HTTPAdapter.send = _blocked

    try:
        import httpx
    except Exception:                                          # noqa: BLE001
        httpx = None
    hx_saved = {}
    if httpx is not None:
        hx_saved = {
            "Client.send": httpx.Client.send,
            "AsyncClient.send": httpx.AsyncClient.send,
        }
        httpx.Client.send = _blocked
        httpx.AsyncClient.send = _blocked_async

    try:
        yield
    finally:
        requests.get = saved["get"]
        requests.post = saved["post"]
        requests.request = saved["request"]
        requests.Session.request = saved["Session.request"]
        requests.adapters.HTTPAdapter.send = saved["HTTPAdapter.send"]
        if httpx is not None:
            httpx.Client.send = hx_saved["Client.send"]
            httpx.AsyncClient.send = hx_saved["AsyncClient.send"]


def try_cached(
    mdp: Any,
    request: Dict[str, Any],
    *,
    block: bool = True,
    swallow: tuple = (Exception,),
) -> Optional[Any]:
    """``mdp.get_data(request)`` if it is already on disk, else ``None``.

    Any exception is swallowed by design: a miss surfaces from these MDPs in
    several shapes (the guard's own error, a vendor parse failure on a partially
    cached payload, a KeyError deep in a smile calibration) and for a harvest
    they all mean the same thing -- not available offline, move on. The caller
    gets None and :func:`network_calls_blocked` to audit how often it happened.
    """
    with cache_only(block=block):
        try:
            return mdp.get_data(dict(request))
        except swallow:
            return None
