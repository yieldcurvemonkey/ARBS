import datetime
import time

import pandas as pd

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP


def _mdp():
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    # Isolate from any on-disk persistence: a plain dict is .get()/[key]= compatible.
    mdp._raw_eod_mem = {}
    mdp._raw_eod_disk_cache = {}
    return mdp


def _full_history_frame():
    idx = pd.bdate_range("2019-01-01", "2026-05-29")
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 2.0, "Volume": 0, "Open Interest": 0},
        index=idx,
    )


def test_raw_eod_cache_dedupes_overlapping_windows(monkeypatch):
    mdp = _mdp()
    calls = {"n": 0, "syms": []}

    def _fake_run(symbols, start_dt, end_dt, show_tqdm, mc, mk, mr):
        calls["n"] += 1
        calls["syms"].append(list(symbols))
        return {s: _full_history_frame() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch", _fake_run)

    w1 = mdp._fetch_barchart_eod_series(
        symbols=["SQM26", "SQZ26|9600C"],
        start=datetime.date(2024, 1, 1),
        end=datetime.date(2024, 3, 1),
        show_tqdm=False,
    )
    assert calls["n"] == 1
    assert set(w1.keys()) == {"SQM26", "SQZ26|9600C"}
    assert w1["SQM26"].index.min() >= pd.Timestamp("2024-01-01")
    assert w1["SQM26"].index.max() <= pd.Timestamp("2024-03-01 23:59")

    # Overlapping but different *historical* window -> fully served from cache, no refetch.
    w2 = mdp._fetch_barchart_eod_series(
        symbols=["SQM26", "SQZ26|9600C"],
        start=datetime.date(2024, 2, 1),
        end=datetime.date(2024, 4, 1),
        show_tqdm=False,
    )
    assert calls["n"] == 1  # <-- the whole point: zero re-downloads
    assert w2["SQM26"].index.min() >= pd.Timestamp("2024-02-01")
    assert w2["SQM26"].index.max() <= pd.Timestamp("2024-04-01 23:59")

    # Adding one new symbol fetches ONLY the uncached one.
    w3 = mdp._fetch_barchart_eod_series(
        symbols=["SQM26", "SQU26"],
        start=datetime.date(2024, 2, 1),
        end=datetime.date(2024, 4, 1),
        show_tqdm=False,
    )
    assert calls["n"] == 2
    assert calls["syms"][1] == ["SQU26"]

    # force_refresh bypasses the cache and refetches.
    mdp._fetch_barchart_eod_series(
        symbols=["SQM26"],
        start=datetime.date(2024, 2, 1),
        end=datetime.date(2024, 4, 1),
        show_tqdm=False,
        force_refresh=True,
    )
    assert calls["n"] == 3
    assert calls["syms"][2] == ["SQM26"]


def test_raw_eod_cache_covers_freshness():
    mdp = _mdp()
    now = time.time()
    today = datetime.date.today()

    # Fetched 5 days ago; purely-historical window -> covered (data is immutable).
    old = {"fetched_at": now - 5 * 86400, "full_history": True}
    assert mdp._raw_eod_cache_covers(old, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is True

    # Window reaching today but fetched 5 days ago -> stale -> NOT covered.
    assert mdp._raw_eod_cache_covers(old, today - datetime.timedelta(days=30), today) is False

    # Window reaching today, fetched 1 min ago -> fresh -> covered.
    fresh = {"fetched_at": now - 60, "full_history": True}
    assert mdp._raw_eod_cache_covers(fresh, today - datetime.timedelta(days=30), today) is True

    # No fetch timestamp -> never covered.
    assert mdp._raw_eod_cache_covers({}, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is False


def test_raw_eod_cache_does_not_claim_coverage_for_a_narrow_frame():
    """The "historical windows are immutable" shortcut is only sound for the wide-window
    snapshot the fetcher stores. An entry written from a narrow frame answers every later
    window from a slice that silently returns nothing - which is how a stray one-bar
    SQZ30 entry came to report that it covered a January window and yield zero rows,
    leaving option_timeseries with no underlying and an empty result."""
    mdp = _mdp()
    now = time.time()
    # The real poisoned shape: one bar, dated after the requested window starts.
    poisoned = {"fetched_at": now - 5 * 86400, "min_date": datetime.date(2026, 2, 27),
                "max_date": datetime.date(2026, 2, 27)}
    assert mdp._raw_eod_cache_covers(poisoned, datetime.date(2026, 1, 2), datetime.date(2026, 1, 3)) is False
    # An entry carrying no date bounds at all cannot prove anything either.
    assert mdp._raw_eod_cache_covers({"fetched_at": now - 5 * 86400},
                                     datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is False


def test_raw_eod_cache_keeps_legacy_full_history_entries():
    """Entries written before the full_history flag existed must not all be discarded -
    there are thousands of them and refetching every one would hammer Barchart. A legacy
    entry whose stored history begins on or before the requested start is what a wide
    fetch produces, so it is honoured."""
    mdp = _mdp()
    now = time.time()
    legacy = {
        "fetched_at": now - 5 * 86400,
        "min_date": datetime.date(2021, 1, 4),
        "max_date": datetime.date(2026, 7, 24),
    }
    assert mdp._raw_eod_cache_covers(legacy, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is True
    # Prefetch windows run a month past the last available bar. Reaching beyond the fetch
    # day still requires a fresh fetch (the current bar is still settling), but the legacy
    # date check must not be what rejects it -- a fresh legacy entry is honoured.
    fresh_legacy = {**legacy, "fetched_at": time.time() - 60}
    assert mdp._raw_eod_cache_covers(
        fresh_legacy, datetime.date(2026, 6, 24), datetime.date(2026, 8, 24)
    ) is True
    # A flagged entry is trusted without the date check.
    flagged = {"fetched_at": now - 5 * 86400, "full_history": True}
    assert mdp._raw_eod_cache_covers(flagged, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is True


def test_raw_eod_cache_put_records_full_history_only_when_told():
    mdp = _mdp()
    frame = _full_history_frame()
    mdp._raw_eod_cache_put("SQM26", frame, time.time())
    assert mdp._raw_eod_cache_get("SQM26")["full_history"] is False
    mdp._raw_eod_cache_put("SQU26", frame, time.time(), full_history=True)
    assert mdp._raw_eod_cache_get("SQU26")["full_history"] is True


def test_raw_eod_cache_disk_persists_across_instances():
    # Exercises the REAL disk path (no injected _raw_eod_disk_cache): a frame written by one
    # instance must be readable by a fresh instance. Regression for _acquire_cache resolution.
    stem = "STIRFutureOptionRawEOD_DISKTEST"
    path = LayeredCacheMixin.default_cache_path(stem)
    LayeredCacheMixin._acquire_cache(path).clear()
    try:
        frame = _full_history_frame()
        a = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
        a._RAW_EOD_CACHE_STEM = stem
        a._raw_eod_mem = {}
        a._raw_eod_disk_cache = None  # force the real diskcache, not a stand-in
        a._raw_eod_cache_put("SQM26", frame, time.time())

        b = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")  # fresh instance, empty in-proc mem
        b._RAW_EOD_CACHE_STEM = stem
        b._raw_eod_mem = {}
        b._raw_eod_disk_cache = None
        ent = b._raw_eod_cache_get("SQM26")
        assert ent is not None, "disk cache did not persist across instances"
        assert ent["frame"].equals(frame)
    finally:
        LayeredCacheMixin._acquire_cache(path).clear()


def test_raw_eod_cache_disabled_passthrough(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    mdp._raw_eod_cache_enabled = False
    calls = {"n": 0}

    def _fake_run(symbols, start_dt, end_dt, show_tqdm, mc, mk, mr):
        calls["n"] += 1
        # Disabled path passes the *requested* window straight through (no wide fetch).
        assert start_dt == datetime.datetime(2024, 1, 1, 0, 0)
        assert end_dt == datetime.datetime(2024, 3, 1, 23, 59)
        return {s: _full_history_frame() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch", _fake_run)
    out = mdp._fetch_barchart_eod_series(
        symbols=["SQM26"],
        start=datetime.date(2024, 1, 1),
        end=datetime.date(2024, 3, 1),
        show_tqdm=False,
    )
    assert calls["n"] == 1
    assert "SQM26" in out
