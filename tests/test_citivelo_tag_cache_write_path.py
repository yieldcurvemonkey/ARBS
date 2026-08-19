r"""The tag-cache WRITE path, and the warm guard that reads it back.

Two nightly failures in ``scripts/daily_cache_warmer.py`` come from this seam,
and they are NOT the same bug even though the evidence made them look like one:

**1. ``os.replace`` over a target another handle holds open (WinError 5).**
   ``CitiVeloTagCache.write`` is already atomic in the right way - it writes a
   ``.tmp`` and ``os.replace``\ s it, never ``os.rename`` - so "the target exists"
   is not the problem. On Windows the problem is that the target is *open*:
   Python's ``open()`` does not pass ``FILE_SHARE_DELETE``, so any concurrent
   reader of the sidecar - another warm, the user's own session, Defender, the
   Search indexer - makes the replace raise ``PermissionError [WinError 5]``.
   Measured on this machine: a plain read-only ``open()`` of the target is
   sufficient. Observed once in ten nightly runs, on
   ``RATES.BOND.US912810QU51.ROLLCARRY.6M.meta.json``, and it killed the whole
   877-bond EOD warm at bond 48.

**2. "the transport is not writing to the tag cache" is a FALSE diagnosis.**
   ``citivelo_ust_universe_warm`` decides a batch failed when ``cached_tags``
   comes back zero. That guard cannot tell "rows were fetched and none were
   persisted" (the real bug it was written for) from "the window legitimately
   held no rows" - which is what an MI01 request for a bond that matured in 2016
   returns. 528 of the 877 bonds in the catalog are matured, and ``universe()``
   sorts by ISIN, so the first 22 are all dead: batch 0 is guaranteed to fetch
   nothing and the warm aborts 877 bonds at 0/877, every night, blaming the
   transport. Five of ten retained runs, each in 2.9-4.4 s.

Nothing here touches Excel, COM or the network. The cache root is ``tmp_path``
and the transport is a local fake, so the tests can be run on the fast gate.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import pathlib
import sys
import threading
from typing import Dict, Iterator, List, Mapping, Optional, Sequence

import pandas as pd
import pytest

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

_WINDOWS = sys.platform == "win32"

#: How long the TRANSIENT holder keeps the sidecar open. The retry budget in
#: ``write`` must exceed this, or the transient case is indistinguishable from
#: the permanent one - which is the whole contract these tests encode. Chosen
#: well under a second so the suite stays on the fast gate.
_TRANSIENT_HOLD = 0.3


@contextlib.contextmanager
def _held_open(path: pathlib.Path, *, release_after: Optional[float]) -> Iterator[None]:
    """Hold ``path`` open the way a concurrent reader does, and let go or not.

    ``release_after`` is the difference between the two faults this file
    separates. A number is the TRANSIENT case - Defender, the Search indexer,
    another warm reading the sidecar - which a bounded retry is supposed to ride
    out. ``None`` is the PERMANENT case, which must still raise.

    A read-only ``open()`` is enough: Python does not pass ``FILE_SHARE_DELETE``,
    so the handle blocks ``os.replace`` over the target. Measured on this
    machine, it reproduces the nightly ``[WinError 5] Access is denied`` on the
    ``.meta.json.tmp -> .meta.json`` step byte for byte, with no antivirus and no
    second process involved.
    """
    handle = open(path, "r", encoding="utf-8")  # noqa: SIM115 - held on purpose
    timer = None
    if release_after is not None:
        timer = threading.Timer(release_after, handle.close)
        timer.daemon = True
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()
        with contextlib.suppress(Exception):
            handle.close()


def _series(start: str, n: int, *, freq: str = "D", first: float = 1.0) -> pd.Series:
    idx = pd.date_range(start, periods=n, freq=freq, name="Date")
    return pd.Series([first + i for i in range(n)], index=idx, dtype="float64")


# --------------------------------------------------------------------------
# 1. os.replace over a held-open target
# --------------------------------------------------------------------------


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_writing_a_tag_whose_sidecar_is_held_open_does_not_lose_the_write(tmp_path):
    r"""The exact nightly failure, reproduced without Excel.

    A second reader holding the ``.meta.json`` open is enough to make
    ``os.replace`` raise ``PermissionError [WinError 5]``. On the current code
    that exception escapes ``write`` -> ``get`` -> ``quotes.frame`` -> the warm
    script's per-batch handler, which stops the run: measured 2026-08-12, the
    EOD universe warm died at bond 48 of 877 on exactly this.

    The holder here releases after ``_TRANSIENT_HOLD``, mid-call. That is what
    makes this a different STIMULUS from the permanent-lock test below rather
    than a contradictory demand on the same one: a bounded retry whose budget
    outlasts the hold rides this out and still raises on the permanent case.

    The PARQUET is written first and is what ``read`` needs, so a lost sidecar is
    not a lost series - but a raised sidecar write loses the other 829 bonds,
    which is the actual damage.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tag = "RATES.BOND.US912810QU51.ROLLCARRY.6M"

    # A first write, so the target sidecar EXISTS and can be held open.
    cache.write(tag, "DAILY", _series("2026-08-01", 5))
    meta = cache.meta_path(tag, "DAILY", "CLOSE")
    assert meta.is_file()

    with _held_open(meta, release_after=_TRANSIENT_HOLD):
        merged = cache.write(tag, "DAILY", _series("2026-08-06", 5, first=6.0))

    # The series is complete: both spans merged, nothing dropped.
    assert len(merged) == 10
    assert cache.read(tag, "DAILY", "CLOSE") is not None
    assert len(cache.read(tag, "DAILY", "CLOSE")) == 10
    # And no half-written temporary is left behind to be mistaken for a cache file.
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_a_permanently_locked_sidecar_still_raises_rather_than_being_swallowed(tmp_path):
    """The retry must not become a swallow.

    A holder that never lets go is a real fault - a read-only file, a wedged
    process - and it has to reach the operator. A write path that quietly
    returns on a failed replace is the transport-that-persists-nothing failure
    the whole warm guard exists to catch, reintroduced one layer lower.

    Paired with the transient test above, this pins the retry from both sides:
    a budget of zero fails that one, an unbounded retry or a swallow fails this
    one, and only "retry for longer than a transient holder, then raise" passes
    both.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tag = "RATES.BOND.US912810QU51.ROLLCARRY.6M"
    cache.write(tag, "DAILY", _series("2026-08-01", 5))
    meta = cache.meta_path(tag, "DAILY", "CLOSE")

    with _held_open(meta, release_after=None):
        with pytest.raises(OSError):
            cache.write(tag, "DAILY", _series("2026-08-06", 5, first=6.0))

    # ...and it takes its temporary with it. Nothing pinned this before, so the
    # unlink could be deleted and every test still passed. A ``.meta.json.tmp``
    # left in the tree is not inert: it is a partial file sharing a stem with a
    # real cache entry, and the next reader to glob the directory has to know to
    # ignore it. (The readers glob ``*.parquet``, so a stray ``.parquet.tmp`` is
    # invisible to them today - which is precisely why a leak here would go
    # unnoticed until something changed that glob.)
    assert list(tmp_path.rglob("*.tmp")) == [], (
        "the failed replace left its temporary behind: "
        f"{[str(p) for p in tmp_path.rglob('*.tmp')]}"
    )


@pytest.mark.skipif(not _WINDOWS, reason="POSIX rename over an open file succeeds by design")
def test_set_history_start_survives_a_held_open_sidecar(tmp_path):
    """``set_history_start`` uses the same replace and needs the same treatment.

    It is called once per tag from ``CitiVeloQuotes.metadata`` and from
    ``CitiVeloTagCache.get(history_starts=...)``, i.e. on the same hot path and
    against the same file, so leaving it unguarded just moves the WinError 5.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tag = "RATES.OIS.USD_SOFR.PAR.10Y"
    cache.set_history_start(tag, "DAILY", datetime.date(2020, 1, 2))
    meta = cache.meta_path(tag, "DAILY", "CLOSE")

    with _held_open(meta, release_after=_TRANSIENT_HOLD):
        cache.set_history_start(tag, "DAILY", datetime.date(2018, 6, 1))

    cov = cache.coverage(tag, "DAILY", "CLOSE")
    assert cov is not None and cov.history_start == pd.Timestamp("2018-06-01")


def test_a_write_failure_is_not_swallowed_per_item(tmp_path, monkeypatch):
    """``get`` must not report success for a batch whose writes all raised.

    This is the property that makes the warm guard's message meaningful: if
    ``get`` swallowed per-item failures, "fetched N tags and cached none" really
    would be the transport, and the fix would belong in the opposite place.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tags = ["RATES.BOND.US912810QU51.PRICE", "RATES.BOND.US912810QU51.YIELD"]

    def fetch(request, freq, start, end, price_point):
        return {t: _series("2026-08-01", 3) for t in request}

    def boom(*a, **k):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(CitiVeloTagCache, "write", boom)
    with pytest.raises(PermissionError):
        cache.get(tags, "DAILY", start="2026-08-01", end="2026-08-03", fetcher=fetch)


# --------------------------------------------------------------------------
# 2. the warm guard: "cached NONE" must mean "fetched rows and lost them"
# --------------------------------------------------------------------------


class _FakeBond:
    """Just enough of a ``BondResolution`` for the warm loop."""

    def __init__(self, isin: str, maturity: datetime.date):
        self.isin = isin
        self.maturity = maturity


class _FakeQuotes:
    """A cache-backed reader whose wire is a dict, so no Excel is reachable.

    ``rows`` maps tag -> series. A tag absent from it comes back with no rows,
    which is exactly what Velocity returns for an MI01 request against a bond
    that matured in 2016 - the case the nightly warm misreads.
    """

    def __init__(self, cache: CitiVeloTagCache, rows: Mapping[str, pd.Series], *, persist: bool = True):
        self._cache = cache
        self._rows = dict(rows)
        self._persist = persist
        self.calls: List[List[str]] = []

    def frame(self, tags, freq="DAILY", **kwargs) -> pd.DataFrame:
        wanted = [str(t) for t in tags]
        self.calls.append(wanted)
        served: Dict[str, pd.Series] = {t: self._rows[t] for t in wanted if t in self._rows}
        if self._persist:
            for tag, s in served.items():
                self._cache.write(tag, freq, s, price_point=kwargs.get("price_point", "CLOSE"))
        if not served:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        frame = pd.concat(served, axis=1)
        frame.index.name = "Date"
        return frame.sort_index()


class _FakeFetcher:
    def __init__(self, quotes: _FakeQuotes, values: Sequence[str]):
        self._quotes = quotes
        self._values = tuple(values)
        self.closed = False

    def quotes(self):
        return self._quotes

    def plan(self, resolutions, *, values=None):
        vals = tuple(values or self._values)
        return {
            r.isin: {"tags": {v: f"RATES.BOND.{r.isin}.{v}" for v in vals}}
            for r in resolutions
        }

    def close(self):
        self.closed = True


def _install_warm_fakes(monkeypatch, tmp_path, bonds, quotes, values=("PRICE", "YIELD")):
    """Point the warm script at a tmp cache and a fake transport.

    Every seam that could reach the user's Excel is replaced: the memory guard
    (which reads a live process), ``CitiVeloBondFetcher`` (whose ``quotes()`` is
    ``offline=False`` and connects on the first cache miss), and the module-level
    ``MANIFEST`` constant - which otherwise points at the REAL manifest the
    nightly run resumes from.
    """
    import scripts.citivelo_ust_universe_warm as W

    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(W, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(W, "universe", lambda: list(bonds))

    import MDP.CitiVelocityExcel.memory_guard as G

    monkeypatch.setattr(G, "assert_safe_to_connect", lambda *a, **k: 100.0)
    monkeypatch.setattr(G, "excel_memory_mb", lambda *a, **k: 100.0)

    import MDP.CitiVelocityExcel.bonds.fetcher as F

    fetcher = _FakeFetcher(quotes, values)
    monkeypatch.setattr(F, "CitiVeloBondFetcher", lambda *a, **k: fetcher)
    monkeypatch.setattr(F, "DEFAULT_BOND_VALUES", tuple(values), raising=False)
    return W, fetcher


def test_a_batch_of_matured_bonds_is_not_reported_as_a_broken_transport(tmp_path, monkeypatch):
    r"""The nightly 0/877 abort, reproduced with no Excel and no network.

    Eight matured bonds first (Velocity serves them no intraday rows), then eight
    live ones that do warm. The current code stops at batch 0 and calls it "the
    transport is not writing to the tag cache"; the run must instead skip the
    empty batch and warm the live bonds behind it.

    The bonds and the shape are the real ones: ``universe()`` sorts by ISIN, the
    22 lowest ISINs in the catalog all matured between 2016 and 2025, and
    ``DEFAULT_BATCH`` is 8 - so batch 0 is all-dead by construction, not by luck.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    dead = [
        _FakeBond("US912810DX38", datetime.date(2016, 11, 15)),
        _FakeBond("US912810DY11", datetime.date(2017, 5, 15)),
        _FakeBond("US912810DZ85", datetime.date(2017, 8, 15)),
        _FakeBond("US912810EA26", datetime.date(2018, 5, 15)),
        _FakeBond("US912810EB09", datetime.date(2018, 11, 15)),
        _FakeBond("US912810EC81", datetime.date(2019, 2, 15)),
        _FakeBond("US912810ED64", datetime.date(2019, 8, 15)),
        _FakeBond("US912810EE48", datetime.date(2020, 2, 15)),
    ]
    live = [_FakeBond(f"US91282CN{i:02d}", datetime.date(2030, 5, 15)) for i in range(8)]

    minutes = pd.Series(
        [100.0, 100.5, 101.0],
        index=pd.date_range("2026-08-18 09:30", periods=3, freq="1min", name="Date"),
    )
    rows = {
        f"RATES.BOND.{b.isin}.{v}": minutes for b in live for v in ("PRICE", "YIELD")
    }
    quotes = _FakeQuotes(cache, rows)
    W, _ = _install_warm_fakes(monkeypatch, tmp_path, dead + live, quotes)

    out = W.warm(
        "intraday",
        start=datetime.date(2026, 8, 16),
        end=datetime.date(2026, 8, 18),
        values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    # Deliberately NOT asserting an exact ``done``: a fix that records the dead
    # batch with the existing ``{"note": "serves none of these values"}`` idiom
    # and ``continue``\ s leaves ``done`` at 8, and that is a correct fix. What
    # must hold is that the run did not abort, that the live bonds are on disk,
    # and that every bond considered is in the manifest so it is not retried
    # forever.
    assert not out["stopped"], (
        f"the warm stopped at {out['done']}/{out['of']} bonds: {out.get('reason')!r}. "
        "A batch that legitimately holds no rows is not a broken transport."
    )
    assert W.cached_tags("MI01", [f"RATES.BOND.{b.isin}.PRICE" for b in live]) == 8

    import json

    book = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["intraday"]
    assert set(book) == {b.isin for b in dead + live}, (
        "every bond the warm walked past must be recorded, or the dead ones are "
        "re-requested from Velocity on every run for ever."
    )


def test_a_transport_that_fetches_rows_and_persists_none_still_stops_the_warm(tmp_path, monkeypatch):
    """The guard the previous test relaxes must still fire on the real fault.

    This is the mutation check for the fix: a transport that returns rows and
    writes nothing - the ``fetch_windowed`` bug that cost 349 bonds and 134 s on
    2026-08-08 - has to stop the run, or relaxing the empty-batch case has simply
    deleted the guard.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    live = [_FakeBond(f"US91282CN{i:02d}", datetime.date(2030, 5, 15)) for i in range(8)]
    minutes = pd.Series(
        [100.0, 100.5, 101.0],
        index=pd.date_range("2026-08-18 09:30", periods=3, freq="1min", name="Date"),
    )
    rows = {f"RATES.BOND.{b.isin}.{v}": minutes for b in live for v in ("PRICE", "YIELD")}
    quotes = _FakeQuotes(cache, rows, persist=False)  # returns data, caches nothing
    W, _ = _install_warm_fakes(monkeypatch, tmp_path, live, quotes)

    out = W.warm(
        "intraday",
        start=datetime.date(2026, 8, 16),
        end=datetime.date(2026, 8, 18),
        values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    assert out["stopped"], "a transport that persists nothing must stop the warm"
    assert out["done"] == 0
    assert "cach" in out["reason"].lower()


def test_the_manifest_never_marks_a_bond_done_that_the_cache_does_not_hold(tmp_path, monkeypatch):
    r"""Manifest and cache must not disagree about the same window.

    The manifest is the resume key and lives beside the cache but separately from
    it, so the two can drift - measured on the real cache, the intraday book held
    349 bonds at a window three weeks stale while 528 catalog bonds had never been
    warmed at any window at all. A bond that served no rows must be recorded as
    such rather than as a normal completion, so ``status`` can tell "warm" from
    "nothing to warm".
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    dead = [_FakeBond("US912810DX38", datetime.date(2016, 11, 15))]
    quotes = _FakeQuotes(cache, {})
    W, _ = _install_warm_fakes(monkeypatch, tmp_path, dead, quotes)

    W.warm(
        "intraday",
        start=datetime.date(2026, 8, 16),
        end=datetime.date(2026, 8, 18),
        values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    import json

    book = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["intraday"]
    entry = book.get("US912810DX38")
    assert entry is not None, "a bond the warm considered must appear in the manifest"
    assert entry.get("tags") == 0 or entry.get("note"), (
        f"{entry!r} claims a normal warm, but nothing was cached for this bond - "
        "the manifest and the cache now disagree about the same window."
    )
