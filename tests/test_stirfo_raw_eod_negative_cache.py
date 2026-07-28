"""Symbols the vendor has no data for are recorded, so they are not re-requested.

CME lists exercise prices out to +/-5.50 IMM Index points (Rulebook 460A01.E.1), but
Barchart only carries strikes that actually printed. A full listed ladder therefore asks
for dozens of symbols that return nothing - and because an absent symbol was never written
to the raw-EOD cache, every one of them was re-requested on every single call, producing a
steady flood of "No columns to parse from file" errors and wasted round-trips.
"""

import datetime
import time

import pandas as pd
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

IDX = pd.DatetimeIndex([pd.Timestamp("2026-07-24"), pd.Timestamp("2026-07-27")])
REAL = pd.DataFrame(
    {"Open": [0.05, 0.06], "High": [0.05, 0.06], "Low": [0.05, 0.06],
     "Close": [0.05, 0.06], "Volume": [10, 12], "Open Interest": [100, 110]},
    index=IDX,
)


@pytest.fixture
def mdp():
    m = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    # Isolate from any on-disk persistence: a plain dict is .get()/[key]= compatible.
    m._raw_eod_mem = {}
    m._raw_eod_disk_cache = {}
    return m


def _fetcher(mdp, monkeypatch, present):
    """Stub _run_eod_fetch so only `present` symbols come back with data."""
    calls = []

    def _run(symbols, start_dt, end_dt, show_tqdm, mc, mk, mr):
        calls.append(list(symbols))
        return {s: REAL for s in symbols if s in present}

    monkeypatch.setattr(mdp, "_run_eod_fetch", _run)
    return calls


def test_absent_symbols_are_recorded_and_not_refetched(mdp, monkeypatch):
    syms = ["SQZ26|9600C", "SQZ26|10137C", "SQZ26|9037P"]
    calls = _fetcher(mdp, monkeypatch, present={"SQZ26|9600C"})
    kw = dict(start=datetime.date(2026, 6, 27), end=datetime.date(2026, 8, 27),
              show_tqdm=False)

    first = mdp._fetch_barchart_eod_series(symbols=syms, **kw)
    assert set(first) == {"SQZ26|9600C"}
    assert sorted(calls[0]) == sorted(syms)

    second = mdp._fetch_barchart_eod_series(symbols=syms, **kw)
    assert set(second) == {"SQZ26|9600C"}
    assert len(calls) == 1, (
        f"the dead strikes were re-requested: {calls[1:]}"
    )


def test_force_refresh_still_retries_a_recorded_miss(mdp, monkeypatch):
    syms = ["SQZ26|10137C"]
    calls = _fetcher(mdp, monkeypatch, present=set())
    kw = dict(start=datetime.date(2026, 6, 27), end=datetime.date(2026, 8, 27),
              show_tqdm=False)
    mdp._raw_eod_cache_put("SQZ26|10137C", None, time.time(),
                           full_history=True, no_data=True)

    mdp._fetch_barchart_eod_series(symbols=syms, force_refresh=True, **kw)
    assert calls, "force_refresh must bypass a recorded miss"


def test_a_wholly_failed_batch_is_not_recorded_as_no_data(mdp, monkeypatch):
    """An outage, proxy failure or rate-limit wall returns nothing for everything.
    Recording misses from that would bake a transient failure into the cache."""
    syms = ["SQZ26|9600C", "SQZ26|9612C"]
    calls = _fetcher(mdp, monkeypatch, present=set())
    kw = dict(start=datetime.date(2026, 6, 27), end=datetime.date(2026, 8, 27),
              show_tqdm=False)

    mdp._fetch_barchart_eod_series(symbols=syms, **kw)
    for s in syms:
        ent = mdp._raw_eod_cache_get(s)
        assert ent is None or not ent.get("no_data"), (
            f"{s} was recorded as having no data after a wholly failed batch"
        )

    mdp._fetch_barchart_eod_series(symbols=syms, **kw)
    assert len(calls) == 2, "a failed batch must be retried, not cached as 'no data'"


def test_miss_coverage_is_rechecked_the_next_day(mdp):
    today = datetime.date.today()
    fresh = {"fetched_at": time.time(), "full_history": True, "no_data": True}
    stale = {"fetched_at": time.time() - 2 * 86400, "full_history": True, "no_data": True}
    window_end = today + datetime.timedelta(days=30)

    # attempted today -> do not retry today, even for a window running into the future
    assert mdp._raw_eod_cache_covers(fresh, today - datetime.timedelta(days=30), window_end) is True
    # attempted two days ago -> retry once
    assert mdp._raw_eod_cache_covers(stale, today - datetime.timedelta(days=30), window_end) is False
    # a purely historical window already answered by the older attempt stays covered
    assert mdp._raw_eod_cache_covers(
        stale, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)
    ) is True


def test_positive_entries_are_unaffected(mdp):
    now = time.time()
    positive = {"fetched_at": now - 5 * 86400, "full_history": True,
                "min_date": datetime.date(2024, 1, 1), "max_date": datetime.date(2026, 7, 27)}
    assert mdp._raw_eod_cache_covers(
        positive, datetime.date(2024, 6, 1), datetime.date(2024, 7, 1)
    ) is True
