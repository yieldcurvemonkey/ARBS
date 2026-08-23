"""FedInvest's runner is called from a thread pool, once per timestamp.

``FixedRateBondsMDP._process_one`` is dispatched per timestamp into a
``ThreadPoolExecutor``, and each worker calls ``FedInvestFetcher.runner``, which
calls ``asyncio.run`` - so a multi-date request opens one event loop per worker.

That deadlocked. On 2026-08-22 the Saturday ``--backfill 7`` was still alive 24
hours later with two ``frb-mdp`` workers wedged in ``asyncio.run`` ->
``ProactorEventLoop._poll``, 306 threads, CPU flat at 159.1 s across a 40-minute
gap between two py-spy dumps with byte-identical stacks. Sixteen of eighteen
jobs never started and the process went on holding an Excel it had launched that
morning. Nothing timed out: the 10 s httpx timeout is scheduled on the loop that
is stuck.

The cause was an ``httpx.AsyncHTTPTransport`` built in ``__init__`` and mounted
on every client - its anyio pool binds to the loop that first drives it.

These tests are hermetic. The network layer is replaced, so what is exercised is
the loop/threading contract, which is where the defect was.
"""

import asyncio
import datetime
import threading

import pandas as pd
import pytest

from MDP.FixedRateBonds.FEDINVEST import FedInvestFetcher as fedinvest_module
from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher


COLS = ["cusip", "type", "coupon", "offer_price", "bid_price", "eod_price"]


def _frame(day):
    return pd.DataFrame(
        [[f"91282C{day.day:02d}0", "MARKET BASED NOTE", 4.0, 99.5, 99.4, 99.45]],
        columns=COLS,
    )


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    """A fetcher whose transport layer is a stub and whose cache is a dict."""
    f = FedInvestDataFetcher()

    async def _fake_fetch(*, client, date, cusips=None, uid=None, **kwargs):
        # A real await, so the loop actually runs rather than completing inline.
        await asyncio.sleep(0.01)
        return (date, _frame(date)) if uid is None else (date, _frame(date), uid)

    monkeypatch.setattr(f, "_fetch_cusip_prices_fedinvest", _fake_fetch)

    store = {}
    monkeypatch.setattr(f, "_ensure_cache", lambda: setattr(f, f._FEDINVEST_CACHE, store)
                        if not hasattr(f, f._FEDINVEST_CACHE) else None)
    monkeypatch.setattr(f, "close_cache", lambda *a, **k: None)
    setattr(f, f._FEDINVEST_CACHE, store)
    return f


# ── the contract ─────────────────────────────────────────────────────

def test_transports_are_not_shared_between_clients():
    """The pool binds to the loop that first drives it, so it cannot be shared."""
    f = FedInvestDataFetcher()
    assert f._httpx_proxies is None, (
        "a transport built in __init__ is the shared state that deadlocked"
    )
    first, second = f._build_mounts(), f._build_mounts()
    if first is None:
        assert second is None  # no proxy configured: httpx uses its own default
    else:
        assert first is not second
        assert first["https://"] is not second["https://"]


def test_a_proxied_fetcher_still_gets_its_mounts():
    f = FedInvestDataFetcher(proxies={"http": "http://p:8080", "https": "http://p:8080"})
    mounts = f._build_mounts()
    assert mounts is not None and set(mounts) == {"http://", "https://"}


def test_the_module_holds_a_lock_over_asyncio_run():
    assert isinstance(fedinvest_module._FEDINVEST_LOOP_LOCK, type(threading.Lock()))


# ── the failure it prevents ──────────────────────────────────────────

def test_eight_worker_threads_each_running_their_own_loop_all_finish(fetcher):
    """The exact shape of `--backfill 7`: one runner call per date, per thread.

    Without the lock this is where two loops overlap. The assertion that matters
    is that it TERMINATES - a deadlock here does not fail, it hangs, so the
    thread join carries a timeout and a hang is reported as one.
    """
    from concurrent.futures import ThreadPoolExecutor

    days = [datetime.datetime(2026, 8, d) for d in range(10, 18)]
    results = {}
    errors = []

    def _one(day):
        try:
            results[day] = fetcher.runner(dates=[day])
        except Exception as exc:  # noqa: BLE001
            errors.append((day, exc))

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="frb-mdp") as pool:
        futures = [pool.submit(_one, d) for d in days]
        for fut in futures:
            fut.result(timeout=60)

    assert not errors, errors
    assert len(results) == len(days)
    for day in days:
        frame = results[day][day]
        assert not frame.empty
        assert list(frame.columns) == COLS


def test_only_one_event_loop_exists_at_a_time(fetcher, monkeypatch):
    """The lock's actual job, observed rather than assumed."""
    from concurrent.futures import ThreadPoolExecutor

    live = 0
    peak = 0
    guard = threading.Lock()
    real_run = asyncio.run

    def _counting_run(coro, **kwargs):
        nonlocal live, peak
        with guard:
            live += 1
            peak = max(peak, live)
        try:
            return real_run(coro, **kwargs)
        finally:
            with guard:
                live -= 1

    monkeypatch.setattr(fedinvest_module.asyncio, "run", _counting_run)

    days = [datetime.datetime(2026, 8, d) for d in range(10, 18)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for fut in [pool.submit(fetcher.runner, dates=[d]) for d in days]:
            fut.result(timeout=60)

    assert peak == 1, f"{peak} concurrent event loops - the lock is not holding"


def test_a_second_thread_asking_for_a_cached_date_never_reaches_the_loop(fetcher, monkeypatch):
    """Why serialising costs almost nothing: the cache is consulted first."""
    day = datetime.datetime(2026, 8, 11)
    fetcher.runner(dates=[day])

    calls = []
    real_run = asyncio.run
    monkeypatch.setattr(fedinvest_module.asyncio, "run",
                        lambda c, **k: (calls.append(1), real_run(c, **k))[1])

    fetcher.runner(dates=[day])
    assert calls == [], "a cached date must not open an event loop at all"
