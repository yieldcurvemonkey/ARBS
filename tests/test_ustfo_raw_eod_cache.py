import datetime
import time

import pandas as pd

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP

# Isolate the cache logic from UST price normalization (a separate, pre-existing concern).
_NORM_PATH = "MDP.USTFutures.USTFutureOptionMDP._normalize_barchart_quote_frame"


def _mdp():
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    mdp._raw_eod_mem = {}
    mdp._raw_eod_disk_cache = {}  # in-memory disk stand-in
    return mdp


def _full_history_frame():
    idx = pd.bdate_range("2019-01-01", "2026-05-29")
    return pd.DataFrame(
        {"Open": 110.5, "High": 110.5, "Low": 110.5, "Close": 110.5, "Volume": 0, "Open Interest": 0},
        index=idx,
    )


def test_ust_raw_eod_cache_dedupes_overlapping_windows(monkeypatch):
    mdp = _mdp()
    monkeypatch.setattr(_NORM_PATH, lambda sym, df: df)  # identity -> test the cache, not normalization
    calls = {"n": 0, "syms": []}

    def _fake_run(symbols, start_dt, end_dt, show_tqdm, mc, mk):
        calls["n"] += 1
        calls["syms"].append(list(symbols))
        return {s: _full_history_frame() for s in symbols}

    monkeypatch.setattr(mdp, "_run_eod_fetch", _fake_run)

    syms = ["ZNM26", "ZBM26", "ZNM26|C11000"]
    w1 = mdp._fetch_barchart_eod_series(symbols=syms, start=datetime.date(2024, 1, 1), end=datetime.date(2024, 3, 1), show_tqdm=False)
    assert calls["n"] == 1
    assert set(w1.keys()) == set(syms)
    assert w1["ZNM26"].index.max() <= pd.Timestamp("2024-03-01 23:59")

    # overlapping but different historical window -> served from cache, no refetch
    w2 = mdp._fetch_barchart_eod_series(symbols=syms, start=datetime.date(2024, 2, 1), end=datetime.date(2024, 4, 1), show_tqdm=False)
    assert calls["n"] == 1
    assert w2["ZNM26"].index.min() >= pd.Timestamp("2024-02-01")

    # new symbol only fetches the uncached one
    mdp._fetch_barchart_eod_series(symbols=["ZNM26", "TYM26"], start=datetime.date(2024, 2, 1), end=datetime.date(2024, 4, 1), show_tqdm=False)
    assert calls["n"] == 2
    assert calls["syms"][1] == ["TYM26"]

    # force_refresh bypasses the cache
    mdp._fetch_barchart_eod_series(symbols=["ZNM26"], start=datetime.date(2024, 2, 1), end=datetime.date(2024, 4, 1), show_tqdm=False, force_refresh=True)
    assert calls["n"] == 3
    assert calls["syms"][2] == ["ZNM26"]


def test_ust_raw_eod_cache_covers_freshness():
    mdp = _mdp()
    now = time.time()
    today = datetime.date.today()
    old = {"fetched_at": now - 5 * 86400}
    assert mdp._raw_eod_cache_covers(old, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is True
    assert mdp._raw_eod_cache_covers(old, today - datetime.timedelta(days=30), today) is False
    fresh = {"fetched_at": now - 60}
    assert mdp._raw_eod_cache_covers(fresh, today - datetime.timedelta(days=30), today) is True
    assert mdp._raw_eod_cache_covers({}, datetime.date(2024, 1, 1), datetime.date(2024, 2, 1)) is False


def test_ust_raw_eod_cache_disk_persists_across_instances():
    # Real disk path (no injected stand-in) -> regression for _acquire_cache resolution.
    stem = "USTFutureOptionRawEOD_DISKTEST"
    path = LayeredCacheMixin.default_cache_path(stem)
    LayeredCacheMixin._acquire_cache(path).clear()
    try:
        frame = _full_history_frame()
        a = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
        a._RAW_EOD_CACHE_STEM = stem
        a._raw_eod_mem = {}
        a._raw_eod_disk_cache = None
        a._raw_eod_cache_put("ZNM26", frame, time.time())

        b = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
        b._RAW_EOD_CACHE_STEM = stem
        b._raw_eod_mem = {}
        b._raw_eod_disk_cache = None
        ent = b._raw_eod_cache_get("ZNM26")
        assert ent is not None, "disk cache did not persist across instances"
        assert ent["frame"].equals(frame)
    finally:
        LayeredCacheMixin._acquire_cache(path).clear()
