r"""The UST universe warm: the guards that stop it lying about what it cached.

``scripts/citivelo_ust_universe_warm.py`` walks the 349-bond Citi UST universe
into the tag cache — 2,302 EOD tags, or 698 intraday ones — across as many
sessions as it takes, because the Velocity add-in's memory only ever grows and
only a human restart gives it back. Three things make that safe to leave
unattended, and each of them is one line that would be invisible if it broke:

**The resume key.** ``_key(mode, start, end, values)`` is the entire definition
of "already done". Drop ``end`` from it and a run that widened the window from
two days to a month reads the manifest, sees every bond at the right key, and
warms nothing. Drop the value set and the same thing happens when someone adds
``DV01``. The failure is silent in both directions: the manifest says 349/349.

**The cached-nothing guard.** The FIRST version of this script fetched 349 bonds
intraday, "succeeded" in 134 s, left **zero** ``MI01`` parquets on disk, and
recorded 349/349 done — because the transport it used (``CitiVeloBondFetcher.
fetch`` → ``fetch_windowed``) talks to the COM client directly and never touches
the tag cache. A warm that reports success and caches nothing is worse than one
that fails, because the next scheduled value job falls through to live Excel at
3 a.m. ``warm()`` therefore asks the CACHE, at the frequency it just warmed,
before it marks anything done. Both halves matter: the count, and the frequency
it counts at.

**The memory gate.** Excel wedged at 5,249 MB on 2026-08-07 and was measured at
13,884 MB the next day. The gate must stop at the ceiling and must FAIL CLOSED
when the probe cannot be read, because "could not tell" and "nothing running"
are different facts and a wedged 13 GB add-in is what the second one hides.

Hermetic by construction
------------------------
Nothing here connects to Excel, and that is not incidental — EXCEL.EXE on this
machine sits near its ceiling and only a human restart shrinks it. The real
:class:`CitiVeloBondFetcher` is used (its ``plan`` is pure, builds real
``RATES.BOND.<ISIN>.<value>`` tags, and reads the committed coverage harvest),
but it is constructed around a fake reader, so ``quotes()`` returns the fake and
``client()`` is never reached. ``excel_memory_mb`` is stubbed in the shared
fixture for every test that calls ``warm()``: the real probe shells out to
PowerShell against the live process, which is the thing under test, not a
dependency of it. The tag cache is redirected to ``tmp_path`` through
``CITIVELO_EXCEL_CACHE_DIR`` and the manifest to ``tmp_path`` directly, so no
test can read or write the committed one.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import pathlib
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from MDP.CitiVelocityExcel import memory_guard as MG
from MDP.CitiVelocityExcel.bonds import fetcher as BF
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache, default_cache_dir
from MDP.CitiVelocityExcel.windowed import MAX_SPAN

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "citivelo_ust_universe_warm.py"


def _script():
    """Import the script by path, once. It is not in a package."""
    name = "_citivelo_ust_universe_warm_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


WARM = _script()


# ── the fake transport ───────────────────────────────────────────────────


class FakeQuotes:
    """A ``CitiVeloQuotes``-shaped reader that never opens anything.

    ``offline = True`` is load-bearing: ``CitiVeloBondFetcher`` reconciles the
    flag against an injected reader and raises on a contradiction, and it is also
    what would select the offline intraday transport if anything reached for it.

    ``writes_at`` is the whole point of the fake. ``None`` reproduces the
    original defect — a fetch that returns cleanly and persists nothing — and a
    frequency token reproduces a working transport, through the REAL
    :class:`CitiVeloTagCache`, so a positive test also proves the cache layout
    and :func:`cached_tags` still agree about where a warmed tag lives.

    It RETURNS the rows it served, and that is not decoration. The two halves of
    the defect this fake exists for are "rows came back" and "nothing was
    persisted", and an earlier version of this fake modelled only the second: it
    wrote to the cache as a side effect and always returned an empty frame. That
    was harmless while the warm's guard looked at nothing but the cache, and
    became actively misleading once the guard had to tell a transport that lost
    698 tags from a window that legitimately holds none — a matured bond asked
    for MI01 — because under the old fake those two are the same object. A fake
    that cannot express the difference the code under test turns on is a fake
    that will agree with whatever the code does.

    ``reports`` is the third thing it has to be able to express, added
    2026-08-20 for the same reason ``writes_at`` was. "Velocity served nothing
    for this window" and "Velocity said nothing at all" are DIFFERENT
    observations - the first comes with a per-tag reason, the second does not -
    and until the warm could tell them apart every test that meant the first one
    modelled the second, because the fake had no way to say a reason. Pass
    ``reports="empty"`` for a matured bond and leave it ``None`` for the silent
    transport that is the fault.
    """

    offline = True

    def __init__(self, *, writes_at="same", raise_on=None, watch_manifest=None,
                 reports=None, reports_for=None):
        self.writes_at = writes_at
        self.raise_on = raise_on
        self.watch_manifest = watch_manifest
        self.reports = reports
        self.reports_for = reports_for
        self.calls = []
        self.manifest_seen = []
        self.closed = False

    def frame(self, tags, freq="DAILY", **kwargs):
        self.calls.append(
            SimpleNamespace(
                tags=list(tags),
                freq=freq,
                start=kwargs.get("start"),
                end=kwargs.get("end"),
                force_refresh=kwargs.get("force_refresh"),
            )
        )
        if self.watch_manifest is not None:
            self.manifest_seen.append(len(_book(self.watch_manifest, "eod")))
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise RuntimeError("Excel went away mid-batch")
        failures = kwargs.get("failures")
        if failures is not None and self.reports is not None:
            for tag in tags:
                if self.reports_for is None or self.reports_for(str(tag)):
                    failures[str(tag)] = self.reports
        target = freq if self.writes_at == "same" else self.writes_at
        index = pd.date_range("2026-08-01", periods=2, freq="D")
        served = {str(t): pd.Series([1.0, 2.0], index=index) for t in tags}
        if target is not None:
            cache = CitiVeloTagCache(base_dir=default_cache_dir())
            for tag, series in served.items():
                cache.write(tag, target, series)
        if not served:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        frame = pd.concat(served, axis=1)
        frame.index.name = "Date"
        return frame.sort_index()

    def close(self):
        self.closed = True


def _install_fetcher(monkeypatch, quotes, *, plan_raises_on=None):
    """Put the REAL fetcher, wrapped around ``quotes``, where ``warm()`` looks.

    The real ``plan`` is kept because it is pure and is what decides which tags
    exist at all; only the transport is faked. ``close()`` on a fetcher with an
    injected reader is a no-op by design, so nothing here can close a live
    client that was never opened.
    """
    real_cls = BF.CitiVeloBondFetcher
    made = []

    class _Wrapper:
        def __init__(self):
            self._inner = real_cls(quotes=quotes)
            self.plan_calls = 0
            self.closed = False

        def quotes(self):
            return self._inner.quotes()

        def plan(self, resolutions, *, values=None):
            self.plan_calls += 1
            if plan_raises_on is not None and self.plan_calls == plan_raises_on:
                raise RuntimeError("the add-in dropped the session between batches")
            return self._inner.plan(resolutions, values=values)

        def close(self):
            self.closed = True
            self._inner.close()

    def _factory(*args, **kwargs):
        wrapper = _Wrapper()
        made.append(wrapper)
        return wrapper

    monkeypatch.setattr(BF, "CitiVeloBondFetcher", _factory)
    return made


def _book(path, mode):
    """One mode's book straight off disk, ``{}`` before the first save."""
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(mode, {})


def _isins_requested(quotes):
    """Which ISINs actually went out, read back out of the tag strings."""
    out = set()
    for call in quotes.calls:
        for tag in call.tags:
            parts = str(tag).split(".")
            if len(parts) >= 3:
                out.add(parts[2])
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect the cache, the manifest and the memory probe. No Excel, no repo.

    ``excel_memory_mb`` is stubbed here rather than per test because the real one
    runs ``Get-Process EXCEL`` once per batch. Probing the live process is the
    hazard this suite exists downstream of, and the real reading on this machine
    (~2,965 MB) is under the ceiling, so an unstubbed probe would not even fail
    visibly — it would just quietly shell out 44 times per warm.

    ``refresh`` is stubbed for a harder reason than tidiness: it CONNECTS. Only
    five of this file's twenty-two ``warm()`` calls pass ``do_refresh=False``,
    and ``warm()`` defaults it to True, so the other seventeen ran
    ``refresh()`` -> ``assert_safe_to_connect`` (which the 100 MB stub above
    lets straight through) -> ``CitiVeloQuotes()`` -> ``refresh_universe`` ->
    ``quotes.client()``. That is a real COM attach to whatever Excel the user
    has open, from a unit test, on a machine where another workflow may be
    mid-backfill. Stubbed at the fixture rather than fixed at seventeen call
    sites so a test added later cannot reintroduce it by forgetting a keyword.
    """
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(WARM, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 100.0)
    refreshes = []
    monkeypatch.setattr(WARM, "refresh", lambda **kwargs: refreshes.append(kwargs) or {})
    return SimpleNamespace(mod=WARM, tmp=tmp_path, manifest=tmp_path / "manifest.json",
                           refreshes=refreshes)


# ══════════════════════════════════════════════════════════════════════════
# 1. THE RESUME KEY
# ══════════════════════════════════════════════════════════════════════════


def test_the_same_request_produces_the_same_key():
    """Without this the manifest never matches and every run re-warms everything."""
    a = WARM._key("eod", datetime.date(2026, 1, 1), datetime.date(2026, 8, 8), ("PRICE", "YIELD"))
    b = WARM._key("eod", datetime.date(2026, 1, 1), datetime.date(2026, 8, 8), ("PRICE", "YIELD"))
    assert a == b


@pytest.mark.parametrize(
    "label,start,end,values",
    [
        ("a deeper history", datetime.date(2021, 1, 1), datetime.date(2026, 8, 8), ("PRICE", "YIELD")),
        ("a later end", datetime.date(2026, 1, 1), datetime.date(2026, 8, 9), ("PRICE", "YIELD")),
        ("an added value", datetime.date(2026, 1, 1), datetime.date(2026, 8, 8), ("PRICE", "YIELD", "DV01")),
        ("a removed value", datetime.date(2026, 1, 1), datetime.date(2026, 8, 8), ("PRICE",)),
    ],
)
def test_a_different_window_or_value_set_is_a_different_key(label, start, end, values):
    """"Already done" must mean done AT THIS WINDOW AND VALUE SET.

    Every one of these is a request the manifest has NOT answered. A key that
    collapses any of them makes a resumed run skip work it never did — the
    widened window comes back reporting 349/349 warm with the extra years, or the
    extra value, missing from disk and no record that they are.
    """
    base = WARM._key("eod", datetime.date(2026, 1, 1), datetime.date(2026, 8, 8), ("PRICE", "YIELD"))
    assert WARM._key("eod", start, end, values) != base, label


def test_value_order_does_not_change_the_key():
    """``--values YIELD PRICE`` is the same request as ``--values PRICE YIELD``.

    Sorted on purpose: an order-sensitive key would re-warm the whole universe
    because someone typed the same seven values in a different order, which costs
    hours of Excel budget for nothing.
    """
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    forward = WARM._key("eod", start, end, ("PRICE", "YIELD", "DV01"))
    shuffled = WARM._key("eod", start, end, ("DV01", "YIELD", "PRICE"))
    assert forward == shuffled
    # ... and it is genuinely the same SET, not everything collapsing to one key.
    assert forward != WARM._key("eod", start, end, ("PRICE", "YIELD"))


def test_the_key_survives_a_json_round_trip():
    """It is stored in the manifest, so it has to come back out as itself."""
    key = WARM._key("intraday", datetime.date(2026, 8, 6), datetime.date(2026, 8, 8), ("PRICE", "YIELD"))
    assert json.loads(json.dumps({"key": key}))["key"] == key


# ══════════════════════════════════════════════════════════════════════════
# 2. THE CACHED-NOTHING GUARD
# ══════════════════════════════════════════════════════════════════════════


def test_a_fetch_that_caches_nothing_stops_and_records_nothing(env, monkeypatch):
    """The 134-second lie, pinned.

    The first version of this script fetched 349 bonds and 698 tags intraday
    without a single error, left ZERO parquets on disk, and wrote 349/349 done to
    the manifest. Everything downstream then believed the cache was warm, so the
    next unattended value job went to live Excel instead. A warm is the file on
    disk, not the call returning.
    """
    quotes = FakeQuotes(writes_at=None)          # succeeds, persists nothing
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 8, 8),
        values=("PRICE", "YIELD"),
        batch=4,
        limit=8,
    )

    # It really did fetch — so the stop came from the cache check and not from an
    # earlier gate that would have made this test pass for the wrong reason.
    assert quotes.calls, "nothing was fetched; this test is not exercising the guard"
    assert out["stopped"] is True
    assert "cach" in out["reason"].lower(), out["reason"]
    assert out["done"] == 0
    assert _book(env.manifest, "eod") == {}, (
        "bonds were recorded done by a fetch that cached nothing — this is exactly "
        "the 349/349 report that made the original run look like a success"
    )


def test_the_cache_is_checked_at_the_frequency_that_was_warmed(env, monkeypatch):
    """An MI01 warm that only lands DAILY files is the original defect exactly.

    The transport in the first version wrote nothing at all, but the same report
    comes back from a transport that writes to the WRONG frequency, and a check
    that always looks at ``DAILY`` cannot tell the two apart — a universe already
    warm at EOD would mark every intraday batch done off its own EOD parquets.
    ``DAILY`` and ``MI01`` are different keys in this cache and are never mixed;
    the guard has to ask at the frequency it just warmed.
    """
    quotes = FakeQuotes(writes_at="DAILY")       # right tags, wrong frequency
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday",
        start=datetime.date(2026, 8, 6),
        end=datetime.date(2026, 8, 8),
        values=("PRICE", "YIELD"),
        batch=4,
        limit=8,
    )

    assert quotes.calls and quotes.calls[0].freq == "MI01"
    # The DAILY files really are there: the only thing missing is MI01.
    daily = sorted((env.tmp / "cache" / "DAILY").rglob("*.parquet"))
    assert daily, "the fake did not write the DAILY files this test contrasts against"
    assert not (env.tmp / "cache" / "MI01").exists()
    assert out["stopped"] is True
    assert "cach" in out["reason"].lower(), out["reason"]
    assert _book(env.manifest, "intraday") == {}


def test_a_fetch_that_does_cache_is_recorded_done(env, monkeypatch):
    """The positive control: the guard must not refuse a warm that worked.

    Also an end-to-end check that the real ``CitiVeloTagCache`` writes where
    ``cached_tags`` looks. If those two ever disagreed, the guard above would
    stop every run on its first batch and the universe could never be warmed at
    all.
    """
    quotes = FakeQuotes()                        # writes at whatever it was asked for
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod",
        start=datetime.date(2026, 1, 1),
        end=datetime.date(2026, 8, 8),
        values=("PRICE", "YIELD"),
        batch=4,
        limit=8,
    )

    assert out["stopped"] is False
    assert out["done"] == 8
    book = _book(env.manifest, "eod")
    assert len(book) == 8
    assert all(entry["tags"] > 0 for entry in book.values())


# ══════════════════════════════════════════════════════════════════════════
# 3. cached_tags READS THE DISK
# ══════════════════════════════════════════════════════════════════════════


def _touch(root, freq, tag):
    path = pathlib.Path(root) / freq / "CLOSE" / f"{tag}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_cached_tags_counts_only_what_is_on_disk(env):
    """Counting the request instead of the disk is how the original bug hid."""
    root = env.tmp / "cache"
    tags = [f"RATES.BOND.US91282CNJ6{i}.PRICE" for i in range(4)]
    for tag in tags[:3]:
        _touch(root, "DAILY", tag)

    assert WARM.cached_tags("DAILY", tags) == 3
    assert WARM.cached_tags("DAILY", tags[:1]) == 1
    assert WARM.cached_tags("DAILY", tags[3:]) == 0


def test_a_tag_cached_at_daily_does_not_count_at_mi01(env):
    """One minute and one day are different data and are never the same key.

    Counting across frequencies would let an EOD-warm universe mark every
    intraday batch done without a single MI01 row being fetched — which is the
    698-tag, 1.2 GB half of this job silently skipped.
    """
    root = env.tmp / "cache"
    tag = "RATES.BOND.US912810EX29.PRICE"
    _touch(root, "DAILY", tag)

    assert WARM.cached_tags("DAILY", [tag]) == 1
    assert WARM.cached_tags("MI01", [tag]) == 0


def test_cached_tags_is_zero_when_the_frequency_directory_does_not_exist(env):
    """A cold cache must count zero, not raise: that is the first batch of every run."""
    assert WARM.cached_tags("MI01", ["RATES.BOND.US912810EX29.PRICE"]) == 0


def test_cached_tags_finds_what_the_real_cache_actually_writes(env):
    """The two halves have to agree about the layout, or the guard is a wall.

    ``CitiVeloTagCache`` writes ``<base>/<FREQ>/<PRICE_POINT>/<tag>.parquet``;
    ``cached_tags`` globs under ``<base>/<FREQ>``. Pinned against the real writer
    rather than against a hand-built path, because a change to either one alone
    turns every warm into an immediate stop.
    """
    tag = "RATES.BOND.US912810EX29.YIELD"
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    cache.write(tag, "MI01", pd.Series([1.0], index=pd.to_datetime(["2026-08-08 12:00"])))

    assert WARM.cached_tags("MI01", [tag]) == 1
    assert WARM.cached_tags("DAILY", [tag]) == 0


# ══════════════════════════════════════════════════════════════════════════
# 4. EVERY INTRADAY REQUEST STAYS UNDER THE SIX-DAY CLIFF
# ══════════════════════════════════════════════════════════════════════════


class _Recorder:
    """Records what it was asked for. It cannot fetch and does not pretend to."""

    offline = True

    def __init__(self):
        self.windows = []

    def frame(self, tags, freq="DAILY", **kwargs):
        self.windows.append((freq, kwargs.get("start"), kwargs.get("end")))
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))


def _spans(rec):
    return [end - start for _, start, end in rec.windows]


def test_a_short_intraday_range_is_one_request():
    """Nothing under the cliff should be split: windows cost an Excel worksheet each."""
    rec = _Recorder()
    WARM._warm_intraday(
        rec, ["RATES.BOND.US912810EX29.PRICE"],
        start=datetime.date(2026, 8, 6), end=datetime.date(2026, 8, 8),
    )
    assert len(rec.windows) == 1
    assert rec.windows[0][0] == "MI01"
    assert _spans(rec)[0] <= MAX_SPAN["MI01"]


def test_a_long_intraday_range_is_chunked_under_the_cliff_with_no_gap():
    """``CVTSHIST`` downsamples by requested SPAN, silently.

    Measured 2026-08-07: ``MI01`` over 6 days is 1-minute data, over 7 days it is
    10-minute data that comes back looking exactly like a successful minute
    request with a tenth of the rows. So a 20-day warm must go out as several
    requests, every one at or under six days, and together they must cover the
    whole range — a chunker that stays under the cliff by dropping days is the
    same lie in a different place.
    """
    rec = _Recorder()
    start, end = datetime.date(2026, 7, 20), datetime.date(2026, 8, 8)
    WARM._warm_intraday(rec, ["RATES.BOND.US912810EX29.PRICE"], start=start, end=end)

    assert len(rec.windows) > 1, "a 20-day range must not go out as one request"
    for freq, w_start, w_end in rec.windows:
        assert freq == "MI01"
        assert w_end - w_start <= MAX_SPAN["MI01"], (
            f"{w_start}..{w_end} spans {w_end - w_start}, past the measured "
            f"{MAX_SPAN['MI01']} cliff — the add-in would serve 10-minute rows"
        )

    ordered = sorted(((s, e) for _, s, e in rec.windows))
    lo = datetime.datetime.combine(start, datetime.time(0, 0))
    hi = datetime.datetime.combine(end, datetime.time(23, 59))
    assert ordered[0][0] == lo
    assert ordered[-1][1] == hi
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:]):
        assert prev_end == next_start, "the windows leave a hole in the range"


@pytest.mark.parametrize("days,expected", [(5, 1), (6, 2)])
def test_the_split_happens_at_the_measured_boundary(days, expected):
    """Six days is the last span that serves minutes; seven is not.

    Parametrised across the boundary so a widened span is caught by a count, not
    only by the inequality above — the two fail for different reasons and a
    mutation that changes the constant should be visible in both.
    """
    rec = _Recorder()
    end = datetime.date(2026, 8, 8)
    WARM._warm_intraday(
        rec, ["RATES.BOND.US912810EX29.PRICE"],
        start=end - datetime.timedelta(days=days), end=end,
    )
    assert len(rec.windows) == expected
    assert all(span <= MAX_SPAN["MI01"] for span in _spans(rec))


# ══════════════════════════════════════════════════════════════════════════
# 5. RESUMABILITY
# ══════════════════════════════════════════════════════════════════════════


def _seed(manifest, mode, isins, key):
    manifest.write_text(
        json.dumps({mode: {isin: {"key": key, "tags": 2} for isin in isins}}),
        encoding="utf-8",
    )


def test_the_committed_catalog_still_holds_the_universe_this_job_sizes_itself_on():
    """At least 349 USA.USD.GOVT bonds, off disk, with no network and no Excel.

    Every cost in the script's header — 2,302 EOD tags, 698 intraday, ~170 MB —
    is stated per this number. It is also what makes the resume tests below
    meaningful rather than a test of a stub.

    ``>=`` and not ``==`` on purpose. The catalog is an ACCUMULATING UNION and is
    *supposed* to grow: Treasury auctions weekly, and the moment Citi picks up an
    issue it has been lagging (three were still absent eight days after issue on
    2026-08-08) a refresh adds it. An equality here would fail on correct
    behaviour, which is the worst kind of test. The tripwire that matters is the
    other direction — the universe must never SHRINK, because matured bonds are
    unrecoverable from ``CVCURVEBOND`` and dropping one silently loses history
    that cannot be re-fetched.
    """
    uni = WARM.universe()
    n = len(uni)
    assert n >= 349, (
        f"the USA.USD.GOVT universe shrank to {n}. It is a union that never removes, "
        "so a decrease means something deleted from the catalog — and a matured bond "
        "cannot be recovered from Citi once it is gone."
    )
    assert [r.isin for r in uni] == sorted(r.isin for r in uni), "the order must be stable"


def test_bonds_already_at_this_key_are_not_refetched(env, monkeypatch):
    """The whole point of the manifest: a lost session costs time, not data.

    Re-fetching what is already warm is not merely slow — it is ~1.7 MB of Excel
    per intraday tag against a ceiling only a human restart clears, so a resume
    that ignores the manifest cannot finish the universe at all.
    """
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    values = ("PRICE", "YIELD")
    uni = WARM.universe()
    already = [r.isin for r in uni[:8]]
    _seed(env.manifest, "eod", already, WARM._key("eod", start, end, values))

    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=start, end=end, values=values, batch=4, limit=8)

    requested = _isins_requested(quotes)
    assert not (requested & set(already)), (
        f"{sorted(requested & set(already))} were already warm at this key and went "
        f"out again"
    )
    assert requested == {r.isin for r in uni[8:16]}
    assert out["done"] == 8
    # The seeded entries are untouched — a resume must not rewrite what it skipped.
    book = _book(env.manifest, "eod")
    assert all("at" not in book[isin] for isin in already)


def test_force_rewarms_bonds_the_manifest_calls_done(env, monkeypatch):
    """The override that exists for a cache someone deleted by hand."""
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    values = ("PRICE", "YIELD")
    uni = WARM.universe()
    already = [r.isin for r in uni[:8]]
    _seed(env.manifest, "eod", already, WARM._key("eod", start, end, values))

    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=start, end=end, values=values, batch=4, limit=8, force=True)

    assert _isins_requested(quotes) == set(already)
    assert out["done"] == 8


@pytest.mark.parametrize(
    "label,seed_start,seed_end,run_start,run_end",
    [
        # `--years 10` after a `--years 5` run: the extra history was never fetched.
        ("a deeper history", datetime.date(2026, 8, 6), datetime.date(2026, 8, 8),
         datetime.date(2021, 8, 8), datetime.date(2026, 8, 8)),
        # The ordinary case: the same job, run again a day later. Nothing on disk
        # covers the new day, and there is no other field that says so.
        ("a later end", datetime.date(2021, 8, 8), datetime.date(2026, 8, 7),
         datetime.date(2021, 8, 8), datetime.date(2026, 8, 8)),
    ],
)
def test_a_moved_window_refetches_bonds_the_manifest_holds(
    env, monkeypatch, label, seed_start, seed_end, run_start, run_end
):
    """The resume key, at the level the resume actually happens.

    A manifest entry written for one window says nothing about a different one,
    in EITHER direction — deeper history at the front, or another day at the
    back. If it did, the run would report the universe fully warm with rows that
    were never fetched and no record that they are missing.
    """
    values = ("PRICE", "YIELD")
    uni = WARM.universe()
    already = [r.isin for r in uni[:8]]
    _seed(env.manifest, "eod", already, WARM._key("eod", seed_start, seed_end, values))

    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    WARM.warm("eod", start=run_start, end=run_end, values=values, batch=4, limit=8)
    assert _isins_requested(quotes) == set(already), (
        f"{label}: a moved window was served from a manifest entry written for a "
        f"different one"
    )


def test_an_added_value_refetches_bonds_the_manifest_holds(env, monkeypatch):
    """A bond warmed for ``PRICE`` is not warm for ``PRICE,YIELD``.

    Coverage is per value and the tags are separate cache keys, so adding
    ``--values`` to a job that already ran leaves the new value with no rows on
    disk. A manifest that answers for the bond rather than for the request would
    report the whole universe warm and skip every one of them.
    """
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    uni = WARM.universe()
    already = [r.isin for r in uni[:8]]
    _seed(env.manifest, "eod", already, WARM._key("eod", start, end, ("PRICE",)))

    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)
    WARM.warm("eod", start=start, end=end, values=("PRICE", "YIELD"), batch=4, limit=8)

    assert _isins_requested(quotes) == set(already)
    assert any(tag.endswith(".YIELD") for call in quotes.calls for tag in call.tags)


def test_a_fully_warm_window_does_no_work_at_all(env, monkeypatch):
    """The cheap resume: no fetcher is built, so no Excel is even a possibility."""
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    values = ("PRICE", "YIELD")
    uni = WARM.universe()
    _seed(env.manifest, "eod", [r.isin for r in uni], WARM._key("eod", start, end, values))

    quotes = FakeQuotes()
    made = _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=start, end=end, values=values, batch=8)

    assert out["done"] == 0 and out["stopped"] is False
    assert not quotes.calls
    assert not made, "a fetcher was constructed for a window with nothing to do"


# ══════════════════════════════════════════════════════════════════════════
# 6. THE MEMORY GATE
# ══════════════════════════════════════════════════════════════════════════


def test_the_run_refuses_to_start_above_the_ceiling(env, monkeypatch):
    """Gated BEFORE anything is constructed — a check after ``client()`` is not a check."""
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 3600.0)
    quotes = FakeQuotes()
    made = _install_fetcher(monkeypatch, quotes)

    with pytest.raises(MG.ExcelTooLargeError):
        WARM.warm(
            "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
            values=("PRICE",), batch=4, limit=8, ceiling_mb=3500.0,
        )
    assert not made and not quotes.calls


def test_the_run_stops_when_memory_reaches_the_ceiling_mid_warm(env, monkeypatch):
    """Excel's memory only ever grows, and it wedged at 5,249 MB on 2026-08-07.

    Stopping is the correct outcome, not an error to route around:
    ``recycle_workbook()`` was measured returning ``True`` while memory went UP
    7 MB, so there is nothing to do but stop and let a human restart. The batch
    already done must survive, which is what makes several sessions add up to one
    warm.
    """
    readings = iter([100.0, 3500.0])              # AT the ceiling on the second batch
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: next(readings))
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=16, ceiling_mb=3500.0,
    )

    assert out["stopped"] is True
    assert "ceiling" in out["reason"].lower(), out["reason"]
    assert out["done"] == 8, "the first batch's progress was lost"
    assert len(_book(env.manifest, "eod")) == 8


def test_an_unreadable_probe_stops_the_run_before_it_fetches_anything(env, monkeypatch):
    """FAIL CLOSED. "Could not tell" is not "nothing is running".

    A probe that timed out or was refused says nothing about what is live, and
    what might be live is the 13,884 MB process measured on 2026-08-08. Treating
    the unreadable answer as safe is what turns a gate into a formality.
    """
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: None)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=16, ceiling_mb=3500.0,
    )

    assert out["stopped"] is True
    assert "could not read" in out["reason"].lower(), out["reason"]
    assert out["done"] == 0
    assert not quotes.calls, "it fetched anyway after failing to read Excel's size"


def test_a_probe_that_raises_is_treated_as_unreadable(env, monkeypatch):
    """An exception out of the probe must gate the run, not crash it.

    ``excel_memory_mb`` already swallows its own failures, but this call site
    wraps it again: a probe that raised anyway would otherwise take down a run
    that has warmed batches on disk and no reason to abort them uncleanly.
    """
    def _boom(**k):
        raise OSError("powershell not found")

    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 100.0)
    monkeypatch.setattr(MG, "excel_memory_mb", _boom)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=16, ceiling_mb=3500.0,
    )
    assert out["stopped"] is True
    assert "could not read" in out["reason"].lower()
    assert not quotes.calls


def test_a_reading_just_under_the_ceiling_still_runs(env, monkeypatch):
    """The gate must not be so eager that the job can never make progress."""
    monkeypatch.setattr(MG, "assert_safe_to_connect", lambda limit, **k: 3499.0)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 3499.0)
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=8, ceiling_mb=3500.0,
    )
    assert out["stopped"] is False and out["done"] == 8


# ══════════════════════════════════════════════════════════════════════════
# 7. THE MANIFEST IS SAVED AFTER EVERY BATCH
# ══════════════════════════════════════════════════════════════════════════


def test_the_manifest_on_disk_is_current_at_the_start_of_every_batch(env, monkeypatch):
    """A stop must cost one batch, not the session.

    Observed from INSIDE the transport, because saving once in the ``finally``
    produces an identical end state and an identical return value — the only way
    to tell a per-batch save from a per-run one is to look at the file while the
    run is still going. When batch *k* goes out, batches 0..k-1 must already be
    on disk; otherwise a COM error, a closed Excel or a hit ceiling throws away
    every bond warmed since the process started.
    """
    quotes = FakeQuotes(watch_manifest=env.manifest)
    _install_fetcher(monkeypatch, quotes)

    WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=40,
    )

    assert quotes.manifest_seen == [0, 8, 16, 24, 32], (
        f"the manifest lagged the run: {quotes.manifest_seen}"
    )


def test_a_batch_that_fails_keeps_every_batch_before_it(env, monkeypatch):
    """One bad batch must not lose the rest — that is what makes the run resumable."""
    quotes = FakeQuotes(raise_on=4)               # the fourth batch's fetch blows up
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
        values=("PRICE",), batch=8, limit=40,
    )

    assert out["stopped"] is True
    assert "Excel went away" in out["reason"]
    assert out["done"] == 24
    assert len(_book(env.manifest, "eod")) == 24


def test_progress_survives_an_exception_raised_between_batches(env, monkeypatch):
    """The ``finally`` save, for the failures the inner handler does not catch.

    ``fetcher.plan`` runs outside the per-batch try, so a session dropped there
    propagates out of ``warm()``. The manifest must still hold what was warmed
    before it, or an unhandled error costs the whole run's Excel budget.
    """
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes, plan_raises_on=3)

    with pytest.raises(RuntimeError, match="dropped the session"):
        WARM.warm(
            "eod", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 8, 8),
            values=("PRICE",), batch=8, limit=40,
        )

    assert len(_book(env.manifest, "eod")) == 16


def test_the_saved_entries_carry_the_key_they_were_warmed_at(env, monkeypatch):
    """A manifest entry without the key it was written for cannot resume anything."""
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 8, 8)
    values = ("PRICE", "YIELD")
    quotes = FakeQuotes()
    _install_fetcher(monkeypatch, quotes)

    WARM.warm("eod", start=start, end=end, values=values, batch=4, limit=8)

    book = _book(env.manifest, "eod")
    assert {entry["key"] for entry in book.values()} == {WARM._key("eod", start, end, values)}


# ══════════════════════════════════════════════════════════════════════════
# 6. COVERAGE: A FILE THAT EXISTS IS NOT A WINDOW THAT IS COVERED
# ══════════════════════════════════════════════════════════════════════════
#
# ``cached_tags`` above answers "did the transport write anything at all". It
# cannot answer "is what it wrote current", and because the tag cache is
# CUMULATIVE the file is always there after the first ever run. Measured against
# the real cache on 2026-08-19 for the nightly window 2026-07-19..2026-08-18:
# 877/877 bonds stamped done, 522 of them holding DAILY data that ENDS BEFORE
# the window starts, 0 missing sidecars — and at tag level, 2,891 of the 8,510
# tags belonging to bonds that were ALIVE through that window hold no row in it.
#
# The predicate under test has to separate three things that all look like an
# empty window, and only one of them is a fault. Every number below is the
# measured one, not an illustration.


_WIN_START = datetime.date(2026, 7, 19)
_WIN_END = datetime.date(2026, 8, 18)

#: A real UST that is alive through the window: ``T 3.875 05/31/2030``.
_ALIVE = "US91282CNG23"
#: A second real UST alive through the window: ``T 5.5 08/15/2028``. Needed
#: because a chunk-wide failure only counts as an outage over at least two
#: alive bonds - one bond is what a per-column Excel error looks like.
_ALIVE_2 = "US912810FE39"

#: A real UST that redeemed four days before it: ``T 4.5 7/15/2026``. Its last
#: DAILY row in the real cache is 2026-07-14, one day before maturity.
_MATURED = "US91282CHM64"


def _plant(tag, freq, dates):
    """Write a real parquet AND sidecar through the real cache writer.

    Hand-built files would pin a layout nobody uses; this is the same
    ``CitiVeloTagCache.write`` the warm's own transport goes through, so the
    sidecar the predicate reads is the sidecar production writes.
    """
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    cache.write(tag, freq, pd.Series([1.0] * len(index), index=index))


def _run_of(last, n, step=1):
    """``n`` dates ending at ``last``, ``step`` days apart, ascending."""
    stop = pd.Timestamp(last)
    return [stop - pd.Timedelta(days=step * i) for i in range(n)][::-1]


def _resolutions(*isins):
    """Real :class:`BondResolution` objects for named ISINs, off the catalog.

    Real ones, because the maturity the exemption turns on comes from
    ``descriptor.maturity`` and a hand-made stub would let the test agree with
    whatever the code happens to read. It also lets a test name two bonds
    instead of walking 522 matured ISINs with ``limit`` to reach a live one.
    """
    by_isin = {r.isin: r for r in WARM.universe()}
    return [by_isin[i] for i in isins]


# ── the predicate on its own ─────────────────────────────────────────────


def test_a_tag_with_a_row_inside_the_window_is_covered(env):
    """The positive control: the bar must not refuse a tag that is up to date."""
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of("2026-08-18", 40))
    states = WARM.tag_states(
        "DAILY", {"PRICE": "RATES.BOND.X.PRICE"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["PRICE"] == (WARM.COVERED, datetime.date(2026, 8, 18))


def test_a_row_ON_the_window_start_counts_as_covered(env):
    """The window is CLOSED at both ends, and the boundary is a real day.

    The nightly window is the last 30 days and its first day is an ordinary
    business day with ordinary prints. A bar of ``last > start`` reads the same
    on almost every tag and silently reclassifies every tag whose only row in
    the window is on its first day — which for a monthly-cadence tag like
    ``ASW_4_CHF`` is the difference between "covered" and "quiet", and it is the
    boundary the whole predicate turns on.
    """
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of(_WIN_START, 40))
    states = WARM.tag_states(
        "DAILY", {"PRICE": "RATES.BOND.X.PRICE"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["PRICE"] == (WARM.COVERED, _WIN_START)


def test_a_row_inside_the_window_beats_maturity(env):
    """Six of the 877 bonds matured DURING the nightly window.

    Coverage is the stronger claim and has to be tested first, or a bond that
    redeemed on the 30th is filed under "nothing to see here" while it still
    holds exactly the rows the window asked for.
    """
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of("2026-07-28", 20))
    states = WARM.tag_states(
        "DAILY", {"PRICE": "RATES.BOND.X.PRICE"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2026, 7, 30),
    )
    assert states["PRICE"][0] == WARM.COVERED


@pytest.mark.parametrize(
    "offset_days,expected",
    [
        (-3000, "matured"),   # a 2018 vintage: the bulk of the catalog
        (-1, "matured"),      # redeemed the day before the window opened
        (0, "matured"),       # redeemed on the window's first day
        (4, "matured"),       # inside the measured 1-5 day quiet tail
        (5, "stalled"),       # past it: the silence is no longer explained
        (30, "stalled"),
    ],
)
def test_maturity_exempts_a_bond_only_within_the_measured_tail(env, offset_days, expected):
    """The grace is measured, and both of its edges matter.

    Over the 522 catalogued USTs that had already matured on 2026-08-19, the gap
    between the maturity date and the last DAILY row is 1 day for 127 bonds, 2
    for 202, 3 for 80, 4 for 95 and 5 for 18 — never 0, never above 5, and never
    negative. So a bond stops printing up to five days BEFORE it redeems, and an
    exemption pinned to the maturity date alone false-flags every maturing bond
    for the few nights the rolling window start sits inside that tail. Five days
    and no more: at six the silence is not explained by maturity any longer, and
    granting it anyway would rebuild the 522-bond blind spot in miniature.
    """
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of("2026-06-01", 60))
    states = WARM.tag_states(
        "DAILY", {"PRICE": "RATES.BOND.X.PRICE"},
        start=_WIN_START, end=_WIN_END,
        maturity=_WIN_START + datetime.timedelta(days=offset_days),
    )
    assert states["PRICE"][0] == expected


def test_a_sparse_tag_inside_its_own_envelope_is_not_stalled(env):
    """``ASW_4_CHF/EUR/GBP``, and the reason no calendar bar can do this.

    Measured over 60 bonds: median gap 1 day, WIDEST gap 76 days, trailing gap
    on 2026-08-19 of 48 days. The series went from daily to roughly monthly in
    October 2024 and is still printing. A fixed "no row in the last 30 days" bar
    calls 345 bonds × 3 currencies stale every month for ever, on data behaving
    exactly as it has for two years — and the reader stops looking.
    """
    dates = _run_of("2026-02-13", 400) + [
        pd.Timestamp(d) for d in ("2026-04-30", "2026-05-13", "2026-06-18", "2026-07-02")
    ]
    _plant("RATES.BOND.X.ASW_4_CHF", "DAILY", dates)
    states = WARM.tag_states(
        "DAILY", {"ASW_4_CHF": "RATES.BOND.X.ASW_4_CHF"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["ASW_4_CHF"] == (WARM.SPARSE, datetime.date(2026, 7, 2)), (
        "a 47-day silence on a tag whose own history holds a 76-day gap is not "
        "evidence of anything"
    )


def test_a_dense_tag_that_went_quiet_is_stalled(env):
    """``CAS``/``ZSPREAD``/``ASW``/``OISS``, which stop dead on 2025-10-03.

    Measured over 60 bonds: median gap 1 day, widest gap 4 days, trailing gap
    320 days — the same date on every bond that serves them. The four ``*_SOFR``
    spreads do the same on 2025-11-28 with a trailing 264. The same envelope
    that clears the sparse tag above convicts these, with nothing configured and
    no per-value list for anyone to keep up to date.
    """
    _plant("RATES.BOND.X.CAS", "DAILY", _run_of("2025-10-03", 90))
    states = WARM.tag_states(
        "DAILY", {"CAS": "RATES.BOND.X.CAS"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["CAS"] == (WARM.STALLED, datetime.date(2025, 10, 3))


def test_the_envelope_is_the_tag_own_history_and_not_a_constant(env):
    """The two cases above differ ONLY in the history, and that is the point.

    Same window, same maturity, same trailing silence to the day — one tag has
    seen a 76-day gap and the other has never seen more than four. Anything that
    reads the calendar instead of the history has to give these two the same
    answer, and both answers are wrong for one of them.
    """
    quiet_since = "2026-07-02"
    _plant("RATES.BOND.X.SPARSE", "DAILY",
           _run_of("2026-02-13", 400) + [pd.Timestamp(quiet_since)])
    _plant("RATES.BOND.X.DENSE", "DAILY", _run_of(quiet_since, 90))
    states = WARM.tag_states(
        "DAILY",
        {"SPARSE": "RATES.BOND.X.SPARSE", "DENSE": "RATES.BOND.X.DENSE"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["SPARSE"][1] == states["DENSE"][1] == datetime.date(2026, 7, 2)
    assert states["SPARSE"][0] == WARM.SPARSE
    assert states["DENSE"][0] == WARM.STALLED


def test_a_live_bond_with_no_file_at_all_is_absent(env):
    """Three USTs auctioned 2026-07-31 have never been warmed at ``MI01``.

    528 of the 877 bonds have no MI01 parquet and 525 of those matured. The
    other three are live on-the-run issues, and existence-counting reports them
    exactly as it reports the 525 — as nothing at all, silently.
    """
    states = WARM.tag_states(
        "MI01", {"PRICE": "RATES.BOND.US91282CRA17.PRICE"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2031, 7, 31),
    )
    assert states["PRICE"] == (WARM.ABSENT, None)
    assert WARM.ABSENT in WARM.ALARMING_STATES


def test_a_tag_too_short_to_calibrate_is_never_called_stalled(env):
    """Two rows give one gap, which is not an envelope.

    "I have never seen this tag print three times" is not evidence that it
    stopped, and a warm that alarms on it teaches its reader to ignore alarms.
    """
    _plant("RATES.BOND.X.DV01", "DAILY", ["2026-05-01", "2026-05-02"])
    states = WARM.tag_states(
        "DAILY", {"DV01": "RATES.BOND.X.DV01"},
        start=_WIN_START, end=_WIN_END, maturity=datetime.date(2030, 5, 31),
    )
    assert states["DV01"][0] == WARM.UNCALIBRATED
    assert WARM.UNCALIBRATED not in WARM.ALARMING_STATES


def test_an_unknown_maturity_is_treated_as_alive(env):
    """Fails towards visibility. Measured: no USA.USD.GOVT bond has one today.

    The exemption is the only thing keeping 522 bonds quiet, so handing it to an
    unknown maturity would be a silent hole that grows with the catalog.
    """
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of("2025-10-03", 90))
    states = WARM.tag_states(
        "DAILY", {"PRICE": "RATES.BOND.X.PRICE"},
        start=_WIN_START, end=_WIN_END, maturity=None,
    )
    assert states["PRICE"][0] == WARM.STALLED


def test_coverage_is_read_at_the_frequency_that_was_asked_for(env):
    """One minute and one day are different data and are never the same key.

    A DAILY-warm universe would otherwise mark every intraday tag covered off
    its own EOD parquets — the 349/349 lie moved one layer down.
    """
    _plant("RATES.BOND.X.PRICE", "DAILY", _run_of("2026-08-18", 40))
    tags = {"PRICE": "RATES.BOND.X.PRICE"}
    live = datetime.date(2030, 5, 31)
    assert WARM.tag_states("DAILY", tags, start=_WIN_START, end=_WIN_END,
                           maturity=live)["PRICE"][0] == WARM.COVERED
    assert WARM.tag_states("MI01", tags, start=_WIN_START, end=_WIN_END,
                           maturity=live)["PRICE"][0] == WARM.ABSENT


def test_the_record_names_the_quiet_values_and_counts_the_rest():
    """The manifest has to carry the OBSERVATION, not a boolean.

    "Done" used to mean "this batch did not abort", which is equally true of a
    night that fetched nothing new for two thirds of the universe. A record that
    cannot say WHICH value went quiet leaves its reader with a number that never
    moves and no way to ask why.
    """
    record = WARM.coverage_record({
        "PRICE": (WARM.COVERED, datetime.date(2026, 8, 18)),
        "YIELD": (WARM.COVERED, datetime.date(2026, 8, 18)),
        "CAS": (WARM.STALLED, datetime.date(2025, 10, 3)),
        "ASW_4_CHF": (WARM.SPARSE, datetime.date(2026, 7, 2)),
        "OAS": (WARM.MATURED, datetime.date(2016, 3, 31)),
        "DV01": (WARM.ABSENT, None),
    })
    assert record["covered"] == 2
    assert record["matured"] == 1
    assert record["stalled"] == ["CAS", "DV01"]
    assert record["quiet"] == {
        "ASW_4_CHF": "2026-07-02", "CAS": "2025-10-03", "DV01": "",
    }
    assert json.loads(json.dumps(record)) == record, "it lives in a JSON manifest"


# ── the predicate inside the warm ────────────────────────────────────────


def test_a_warm_over_a_stale_window_records_the_shortfall_instead_of_hiding_it(
    env, monkeypatch
):
    """The green-while-stale night, pinned.

    Every file here EXISTS, so ``cached_tags`` counts them all and the warm used
    to stamp both bonds done with nothing but a tag count — which is what 877/877
    said on every retained nightly run while 522 of them held nothing inside the
    window. The run must now come back saying what it measured: one value
    covered, one stalled, and the matured bond explained rather than flagged.
    """
    alive, matured = _resolutions(_ALIVE, _MATURED)
    monkeypatch.setattr(WARM, "universe", lambda: [alive, matured])

    _plant(f"RATES.BOND.{_ALIVE}.YIELD", "DAILY", _run_of("2026-08-18", 60))
    _plant(f"RATES.BOND.{_ALIVE}.PRICE", "DAILY", _run_of("2025-10-03", 90))
    for value in ("PRICE", "YIELD"):
        _plant(f"RATES.BOND.{_MATURED}.{value}", "DAILY", _run_of("2026-07-13", 60))

    quotes = FakeQuotes(writes_at=None, reports="empty")  # Velocity: nothing here
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        batch=8, do_refresh=False,
    )

    assert quotes.calls, "nothing was fetched; this is not exercising the warm"
    assert out["stopped"] is False, out.get("reason")
    assert out["coverage"] == {
        WARM.COVERED: 1, WARM.STALLED: 1, WARM.MATURED: 2,
    }, "the run has to report what the cache holds, not how many files exist"

    book = _book(env.manifest, "eod")
    assert book[_ALIVE]["covered"] == 1
    assert book[_ALIVE]["stalled"] == ["PRICE"]
    assert book[_ALIVE]["quiet"] == {"PRICE": "2025-10-03"}
    assert book[_MATURED]["matured"] == 2
    assert "stalled" not in book[_MATURED], (
        "528 of 877 bonds have matured — flagging them is the batch-0 abort that "
        "lost five of ten retained nightly runs"
    )


def test_a_matured_universe_is_never_a_shortfall(env, monkeypatch):
    """The control for the exemption, and the one that must never regress.

    ``universe()`` sorts by ISIN and the lowest ISINs are 2016 vintages, so with
    ``DEFAULT_BATCH = 8`` the first batch of the real run is all-dead by
    construction. A freshness check without the maturity exemption stops there
    every night having warmed nothing, which is precisely the failure that was
    just fixed.
    """
    matured, = _resolutions(_MATURED)
    monkeypatch.setattr(WARM, "universe", lambda: [matured])
    for value in ("PRICE", "YIELD"):
        _plant(f"RATES.BOND.{_MATURED}.{value}", "DAILY", _run_of("2026-07-13", 60))

    quotes = FakeQuotes(writes_at=None, reports="empty")
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "eod", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        batch=8, do_refresh=False,
    )

    assert out["stopped"] is False
    assert out["done"] == 1
    assert out["coverage"] == {WARM.MATURED: 2}
    assert out["regressed"] == {}


def test_only_a_NEW_silence_is_reported_as_a_regression(env, monkeypatch):
    """The standing level cannot drive an exit code; the change can.

    Ten value families have been silent since 2025-10-03 and 2025-11-28. A job
    that exits 1 for them every night is the always-1 exit code the parent
    warmer's own docstring says nobody reads — and an alarm nobody reads is how
    a real new outage arrives unnoticed among 2,891 standing ones.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    _plant(f"RATES.BOND.{_ALIVE}.PRICE", "DAILY", _run_of("2025-10-03", 90))
    _plant(f"RATES.BOND.{_ALIVE}.YIELD", "DAILY", _run_of("2026-08-18", 60))
    env.manifest.write_text(
        json.dumps({"eod": {_ALIVE: {"key": "an older window", "stalled": ["PRICE"]}}}),
        encoding="utf-8",
    )

    quotes = FakeQuotes(writes_at=None, reports="empty")
    _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
                    batch=8, do_refresh=False)

    assert out["coverage"] == {WARM.COVERED: 1, WARM.STALLED: 1}
    assert out["regressed"] == {}, (
        "PRICE was already recorded silent — re-alarming on it every night is how "
        "an alarm stops being read"
    )
    assert _book(env.manifest, "eod")[_ALIVE]["stalled"] == ["PRICE"]


def test_a_value_that_falls_silent_since_the_last_run_is_a_regression(env, monkeypatch):
    """The event nothing in this job could see before.

    A tag that was answering yesterday and is not today is the outage a warm
    exists to notice, and it is invisible to a file-existence check for ever:
    the parquet is still on disk and still counts.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    _plant(f"RATES.BOND.{_ALIVE}.PRICE", "DAILY", _run_of("2025-10-03", 90))
    _plant(f"RATES.BOND.{_ALIVE}.YIELD", "DAILY", _run_of("2026-08-18", 60))
    env.manifest.write_text(
        json.dumps({"eod": {_ALIVE: {"key": "an older window", "covered": 2}}}),
        encoding="utf-8",
    )

    quotes = FakeQuotes(writes_at=None, reports="empty")
    _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
                    batch=8, do_refresh=False)

    assert out["regressed"] == {_ALIVE: ["PRICE"]}


def test_a_shortfall_does_not_stop_the_run(env, monkeypatch):
    """Coverage is a report, never a brake.

    Stopping on a quiet tag would abort on the first batch that serves ``CAS`` —
    304 of the 355 live bonds do — which is the 0/877 abort in a new costume.
    The refetch already happens: ``missing_spans`` asks for the tail every night
    and 13,119 sidecars were rewritten on 2026-08-18. What was missing was the
    report, not the request.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive] * 3)
    _plant(f"RATES.BOND.{_ALIVE}.PRICE", "DAILY", _run_of("2025-10-03", 90))
    _plant(f"RATES.BOND.{_ALIVE}.YIELD", "DAILY", _run_of("2025-10-03", 90))

    quotes = FakeQuotes(writes_at=None, reports="empty")
    _install_fetcher(monkeypatch, quotes)
    out = WARM.warm("eod", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
                    batch=1, do_refresh=False)

    assert out["stopped"] is False, out.get("reason")
    assert out["done"] == 3, "every batch ran; a shortfall is not a fault"
    assert out["coverage"][WARM.STALLED] == 6


@pytest.mark.parametrize(
    "label,summary,expected",
    [
        ("everything warmed", {"stopped": False, "regressed": {}}, None),
        ("a standing shortfall is not a failure",
         {"stopped": False, "regressed": {},
          "coverage": {"covered": 5619, "stalled": 1854, "sparse": 1025}}, None),
        ("a NEW silence", {"stopped": False, "regressed": {"US91282CNG23": ["CAS"]}}, 1),
        ("stopped mid-run", {"stopped": True, "reason": "Excel reached the ceiling",
                             "regressed": {}}, 2),
        ("stopped wins over a regression",
         {"stopped": True, "reason": "ceiling", "regressed": {"US1": ["CAS"]}}, 2),
    ],
)
def test_the_exit_code_says_which_of_the_three_things_happened(
    monkeypatch, label, summary, expected
):
    """The exit code is the only thing the Windows scheduler records.

    Three codes, matching the parent warmer's own scheme: 0 completed, 1 a real
    defect to read the log about, 2 stopped part-way with progress kept. The
    STANDING shortfall deliberately does not reach here — 1,854 tags across ten
    value families have been silent since 2025-10-03 and 2025-11-28, and a job
    that exits 1 for them every night is the always-1 exit code the parent
    warmer's docstring says nobody reads. Only the CHANGE gets an exit code.
    """
    monkeypatch.setattr(sys, "argv", ["citivelo_ust_universe_warm.py", "eod"])
    monkeypatch.setattr(WARM, "warm", lambda *a, **k: dict(summary))
    if expected is None:
        WARM.main()
        return
    with pytest.raises(SystemExit) as exc:
        WARM.main()
    assert exc.value.code == expected, label


# ══════════════════════════════════════════════════════════════════════════
# 8. THE SPAN THAT REACHES THE WIRE
# ══════════════════════════════════════════════════════════════════════════
#
# Everything above bounds the span the warm ASKS for. Until 2026-08-20 nothing
# bounded the span that went OUT, because ``CitiVeloTagCache.missing_spans``
# re-derives its own from the cache: a partially cached tag is answered with
# ``(cov.last, want_end)``. Measured on the real MI01 bond cache, whose 698 tags
# all end 2026-08-07, a 2-day nightly request produced a 13 days 04:01 wire span
# for 400 of 400 sampled tags — against a 6-day cliff, so every row that came
# back would have been 10-minute data written into a 1-minute store, permanently,
# because ``missing_spans`` never re-asks a span it already covers.


class SpanQuotes:
    """A reader that records the span it was ASKED for and writes what it serves.

    It carries a REAL :class:`CitiVeloTagCache` on ``.cache``, which is the whole
    point: the cap under test works by consulting that cache, so a fake without
    one silently exercises the fallback path and proves nothing. ``floor`` is the
    oldest date it will serve, which is how a bond's start of life — or Citi's
    own retention — is expressed.
    """

    offline = True

    def __init__(self, *, cache, floor=None, reports=None, serve=True):
        self.cache = cache
        self.floor = floor
        self.reports = reports
        self.serve = serve
        self.calls = []

    def frame(self, tags, freq="DAILY", **kwargs):
        start = pd.Timestamp(kwargs.get("start"))
        end = pd.Timestamp(kwargs.get("end"))
        self.calls.append(
            SimpleNamespace(tags=[str(t) for t in tags], freq=freq, start=start,
                            end=end, span=end - start,
                            force_refresh=kwargs.get("force_refresh"))
        )
        days = [
            d for d in pd.date_range(start.normalize(), end.normalize(), freq="D")
            if d.weekday() < 5 and (self.floor is None or d.date() >= self.floor)
        ]
        failures = kwargs.get("failures")
        if not days or not self.serve:
            if failures is not None and self.reports is not None:
                for tag in tags:
                    failures[str(tag)] = self.reports
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        index = pd.DatetimeIndex(days)
        served = {str(t): pd.Series([1.0] * len(index), index=index) for t in tags}
        for tag, series in served.items():
            self.cache.write(tag, freq, series)
        frame = pd.concat(served, axis=1)
        frame.index.name = "Date"
        return frame.sort_index()

    def close(self):
        pass


def _spans_asked(quotes, freq="MI01"):
    return [c.span for c in quotes.calls if c.freq == freq]


class WireRecorder:
    """A CLIENT, not a reader — which is the whole point of it.

    The span that crosses the cliff is computed inside
    ``CitiVeloTagCache.missing_spans`` and handed to the FETCHER, three layers
    below ``frame``. A fake standing in for ``frame`` never reaches that code at
    all, so it records the span the warm ASKED for and would report a clean pass
    over the broken path. This sits where the wire sits, behind a real
    ``CitiVeloQuotes`` and a real ``CitiVeloTagCache``.
    """

    def __init__(self):
        self.spans = []

    def fetch_timeseries(self, tags, freq, *, period=None, start=None, end=None,
                         price_point="CLOSE"):
        self.spans.append(
            SimpleNamespace(freq=freq, start=pd.Timestamp(start), end=pd.Timestamp(end),
                            span=pd.Timestamp(end) - pd.Timestamp(start))
        )
        index = pd.DatetimeIndex(
            [d for d in pd.date_range(pd.Timestamp(start).normalize(),
                                      pd.Timestamp(end).normalize(), freq="D")
             if d.weekday() < 5]
        )
        if index.empty:
            return {}
        return {str(t): pd.Series([1.0] * len(index), index=index) for t in tags}

    def last_failures(self):
        return {}

    def close(self):
        pass


def test_a_partially_cached_tag_does_not_widen_the_wire_span_past_the_cliff(
    env, monkeypatch
):
    """The 13-day span, pinned at the layer that produced it.

    Measured on the real cache: every MI01 bond tag ends 2026-08-07, and a 2-day
    nightly request for 2026-08-20 came back as a **13 days 04:01** wire span for
    400 of 400 sampled tags. ``missing_spans`` answers a partially cached request
    with ``(cov.last, want_end)`` — a function of the CACHE, not of the window —
    so the chunking done one layer up is re-derived away and CVTSHIST silently
    serves 10-minute rows into a store whose contract is 1-minute. Nothing
    re-asks a covered span, so the resolution would be lost permanently.

    The assertion is on what the CLIENT received, because that is what CVTSHIST
    sees. Asserting on what ``frame`` was asked for would pass over the defect.
    """
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    stale = _run_of("2026-08-07", 4)
    for value in ("PRICE", "YIELD"):
        _plant(f"RATES.BOND.{_ALIVE}.{value}", "MI01", stale)

    wire = WireRecorder()
    quotes = CitiVeloQuotes(
        client=wire, cache=CitiVeloTagCache(base_dir=default_cache_dir())
    )
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday", start=datetime.date(2026, 8, 18), end=datetime.date(2026, 8, 20),
        values=("PRICE", "YIELD"), do_refresh=False,
    )

    assert wire.spans, "nothing reached the wire; this test is not exercising the cap"
    worst = max(s.span for s in wire.spans)
    assert worst <= MAX_SPAN["MI01"], (
        f"a {worst} span went to the wire against a {MAX_SPAN['MI01']} cliff — "
        f"CVTSHIST would have served 10-minute rows into the MI01 store and "
        f"missing_spans would never re-ask for them"
    )
    assert out["stopped"] is False, out.get("reason")


def test_a_window_already_banked_is_not_fetched_again(env, monkeypatch):
    """Idempotence, at the layer the cap is implemented in.

    Capping by re-asking for every window would hold the span under the cliff and
    re-pay for the whole history every night — which on a backwards backfill is
    the difference between accumulating and thrashing. The cap SKIPS what the
    cache already answers, so a window banked end to end costs one sidecar read
    and no ``CVTSHIST`` at all.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    start, end = datetime.date(2026, 8, 17), datetime.date(2026, 8, 20)
    # Banked to the exact bounds the warm asks for — 00:00 on the first day
    # through 23:59 on the last — because a tail the cache stops short of is a
    # REAL missing span and re-requesting it is correct, not a defect.
    banked = [pd.Timestamp(start) + pd.Timedelta(days=i) for i in range(4)]
    banked.append(pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59))
    for value in ("PRICE", "YIELD"):
        _plant(f"RATES.BOND.{_ALIVE}.{value}", "MI01", banked)

    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm("intraday", start=start, end=end, values=("PRICE", "YIELD"),
                    do_refresh=False)

    assert quotes.calls == [], (
        "a window already on disk end to end was re-fetched; the cap must skip "
        "covered tags, not re-ask for them"
    )
    assert out["stopped"] is False, out.get("reason")
    assert out["done"] == 1, "a fully cached bond was not recorded warm"


# ══════════════════════════════════════════════════════════════════════════
# 9. A MATURED BATCH CANNOT STOP THE RUN, WHATEVER THE WIRE CALLS IT
# ══════════════════════════════════════════════════════════════════════════
#
# ``universe()`` sorts by ISIN and the 22 lowest all matured between 2016 and
# 2025, so with ``DEFAULT_BATCH = 8`` batch 0 is all-dead by construction. The
# reason string that comes back for such a chunk cannot be established offline —
# ``parse_tshist_block`` maps a spill under two rows to ``"no block"`` for EVERY
# requested tag, the same string a real outage produces, and the benign
# ``"empty"`` is only reachable when some OTHER tag in the chunk returned rows,
# which an all-dead chunk cannot supply. So the guard is not allowed to depend on
# it. Maturity is catalog data and settles it without a wire.


def test_a_matured_batch_does_not_stop_the_run_on_a_non_benign_reason(
    env, monkeypatch
):
    """Batch 0, exactly: every bond redeemed, every tag ``no block``.

    Without the maturity gate this is the 0/877 abort that lost the intraday warm
    on every retained nightly run — and widening the benign-reason set to admit
    ``no block`` would fail open against the outage the set exists to catch.
    """
    matured, = _resolutions(_MATURED)
    monkeypatch.setattr(WARM, "universe", lambda: [matured])
    quotes = FakeQuotes(writes_at=None, reports="no block")
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    assert quotes.calls, "nothing was fetched; this is not exercising the guard"
    assert out["stopped"] is False, (
        f"a batch of bonds that had already redeemed stopped the run: "
        f"{out.get('reason')!r}. 528 of 877 catalogued USTs have matured — this "
        f"aborts every night at batch 0"
    )


def test_one_alive_bond_failing_is_not_an_outage_but_is_not_stamped_either(
    env, monkeypatch
):
    """A per-COLUMN Excel error is per tag, and must cost that bond only.

    ``block_parser``'s own module docstring says so: it writes an error NAME for
    one tag while every other tag in the same call returns normally. The version
    this replaces did ``if faults: break``, so with 110 batches a night one bad
    column ended the run. It must also NOT stamp the bond — stamping it makes a
    same-night re-run skip the one thing that did not warm.
    """
    alive, matured = _resolutions(_ALIVE, _MATURED)
    monkeypatch.setattr(WARM, "universe", lambda: [alive, matured])
    quotes = FakeQuotes(
        writes_at="same", reports="#N/A",
        reports_for=lambda tag: _ALIVE in tag and tag.endswith("PRICE"),
    )
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    assert out["stopped"] is False, out.get("reason")
    book = _book(env.manifest, "intraday")
    assert _MATURED in book, "the healthy bond in the same batch was not recorded"
    assert _ALIVE not in book, (
        "the bond whose tag the wire refused was stamped done — a same-night "
        "re-run would now skip exactly the bond that did not warm"
    )


def test_two_alive_bonds_failing_together_does_stop_the_run(env, monkeypatch):
    """The positive control. A guard that never fires is not a guard.

    Two independent bonds failing every tag in one call cannot be one bad column,
    which is the whole reason the threshold is two rather than one.
    """
    alive, = _resolutions(_ALIVE)
    other, = _resolutions(_ALIVE_2)
    monkeypatch.setattr(WARM, "universe", lambda: [alive, other])
    quotes = FakeQuotes(writes_at=None, reports="no block")
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    assert out["stopped"] is True, (
        "every tag of two alive bonds failed at once and the run carried on"
    )
    assert out["done"] == 0
    assert _book(env.manifest, "intraday") == {}


def test_a_silent_transport_that_persists_nothing_stops_the_intraday_warm(
    env, monkeypatch
):
    """Case (a) on the MI01 path — the fault that started all of this.

    The transport answers, writes nothing to the cache, and reports no reason.
    The guard this replaces asked ``landed == 0 and rows_served > 0``, and
    ``rows_served`` is ``len(frame)`` where ``frame`` is the cache's own re-read,
    so on the real transport it is 0 and the predicate was unreachable. The
    evidence has to be the sidecars, sampled either side of the fetch.

    The fake RETURNS AN EMPTY FRAME, and that is the load-bearing detail. A fake
    that returns the rows it pretended to serve makes the old predicate fire —
    ``landed == 0 and rows > 0`` — so a test written against one would pass on
    the broken code and prove nothing. The real reader cannot do that: ``frame``
    is built by re-reading the parquets, and a transport that wrote none has
    none to re-read. Verified by mutation: with the guard reverted, this test
    fails; with a rows-returning fake it does not.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache, serve=False)   # answers, persists nothing, says nothing
    _install_fetcher(monkeypatch, quotes)

    out = WARM.warm(
        "intraday", start=_WIN_START, end=_WIN_END, values=("PRICE", "YIELD"),
        do_refresh=False,
    )

    assert quotes.calls, "nothing was fetched; this is not exercising the guard"
    assert out["stopped"] is True, (
        "a transport that fetched and persisted nothing reported success"
    )
    assert "sidecar" in out["reason"], out["reason"]
    assert _book(env.manifest, "intraday") == {}


def test_the_warm_asks_for_a_universe_refresh_and_the_fixture_stops_it_connecting(
    env, monkeypatch
):
    """The fixture stub is load-bearing, so it is pinned rather than assumed.

    ``warm()`` defaults ``do_refresh=True`` and ``refresh()`` constructs a real
    ``CitiVeloQuotes`` and calls ``refresh_universe``, which reaches
    ``quotes.client()`` — a COM attach to whatever Excel is open. Seventeen of
    this file's ``warm()`` calls take that default. If the ``env`` fixture ever
    stops stubbing it, this test is what says so.
    """
    matured, = _resolutions(_MATURED)
    monkeypatch.setattr(WARM, "universe", lambda: [matured])
    quotes = FakeQuotes(writes_at=None, reports="empty")
    _install_fetcher(monkeypatch, quotes)

    WARM.warm("intraday", start=_WIN_START, end=_WIN_END,
              values=("PRICE", "YIELD"))          # do_refresh defaults to True

    assert env.refreshes, (
        "warm() no longer calls refresh(), or the fixture no longer intercepts "
        "it — either way a test in this file can now open Excel"
    )


# ══════════════════════════════════════════════════════════════════════════
# 10. DEPTH: THE BACKWARDS PASS
# ══════════════════════════════════════════════════════════════════════════
#
# A rolling window walks forward and only forward. The real cache is the proof:
# all 698 MI01 bond tags share first=2026-08-04 and last=2026-08-07, one window,
# never extended, because ``missing_spans``' backwards branch is
# ``want_start < cov.first`` and a nightly ``want_start`` only ever advances.


def _depth_book(manifest):
    path = pathlib.Path(manifest)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("depth", {})


def _weeks_asked(quotes):
    """The Mondays the depth pass actually requested, oldest first."""
    return sorted({c.start.date() for c in quotes.calls if c.freq == "MI01"})


def test_the_grid_is_a_monday_to_friday_week_under_the_cliff(env, monkeypatch):
    """Every backwards request is a stable, sub-cliff week.

    Stable matters as much as sub-cliff: a grid anchored on "today" moves every
    night, so the week banked on Tuesday is not the week Wednesday asks about and
    neither the coverage test nor the resume cursor would mean anything twice.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21,
                              budget_s=60.0)

    assert out["weeks"] > 0, "the pass banked nothing"
    for call in quotes.calls:
        assert call.start.weekday() == 0, f"a window started on {call.start:%A}"
        assert call.span <= MAX_SPAN["MI01"], call.span


def test_depth_walks_backwards_one_week_per_pass_until_the_target(env, monkeypatch):
    """The capability itself: history accumulates instead of tracking today."""
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21,
                              budget_s=60.0)

    weeks = _weeks_asked(quotes)
    assert weeks == [
        datetime.date(2026, 7, 27), datetime.date(2026, 8, 3),
        datetime.date(2026, 8, 10), datetime.date(2026, 8, 17),
    ], weeks
    assert out["deepest"] == datetime.date(2026, 7, 27)
    entry = _depth_book(env.manifest)[_ALIVE]
    assert entry.get("complete") is True, entry
    assert entry["weeks"] == 4


def test_depth_fills_an_interior_hole_the_forward_window_cannot_see(env, monkeypatch):
    """The 2026-08-08..08-17 stretch, in miniature.

    ``missing_spans`` inspects the head and the tail of the cached range and
    nothing in between, so a gap the nightly left inside it is invisible to the
    fetch path for ever. The cursor walks the GRID and tests each week against
    what the parquet holds, so the hole is filled the first time it passes over.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    # Weeks of 08-17 and 07-27 banked; the two weeks between them are the hole.
    banked = [datetime.date(2026, 8, 17) + datetime.timedelta(days=i) for i in range(5)]
    banked += [datetime.date(2026, 7, 27) + datetime.timedelta(days=i) for i in range(5)]
    for value in ("PRICE", "YIELD"):
        _plant(f"RATES.BOND.{_ALIVE}.{value}", "MI01", [pd.Timestamp(d) for d in banked])

    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21, budget_s=60.0)

    assert _weeks_asked(quotes) == [
        datetime.date(2026, 8, 3), datetime.date(2026, 8, 10),
    ], "the pass did not ask for exactly the two weeks that were missing"


def test_depth_never_chases_a_window_after_maturity_and_still_deepens_the_bond(
    env, monkeypatch
):
    """Matured bonds are the majority and this is the only path that warms them.

    They can hold no row after they redeemed, so the forward window finds nothing
    for 528 of the 877 for ever — while their history BEFORE maturity is exactly
    as real as anyone else's. Chasing weeks after the redemption is what makes
    two thirds of the universe look permanently un-warm.
    """
    matured, = _resolutions(_MATURED)
    maturity = matured.descriptor.maturity
    monkeypatch.setattr(WARM, "universe", lambda: [matured])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=60,
                              budget_s=60.0)

    weeks = _weeks_asked(quotes)
    assert weeks, "the matured bond was never deepened at all"
    assert max(weeks) <= maturity, (
        f"a window starting {max(weeks)} was requested for a bond that redeemed "
        f"{maturity}"
    )
    assert out["weeks"] > 0
    assert _depth_book(env.manifest)[_MATURED]["weeks"] > 0


def test_a_bond_below_citis_retention_floors_after_two_empty_weeks(env, monkeypatch):
    """Two strikes, not one, and the reason is measured.

    Citi's data legitimately stops 1-5 days before a bond redeems — 1 day for 127
    of 522 matured USTs, 5 for 18, never more — so the first backwards week is
    often the grace tail and holds nothing while every week below it is full.
    Flooring on one empty week strands exactly the bonds this pass recovers.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache, floor=datetime.date(2026, 8, 10),
                        reports="empty")
    _install_fetcher(monkeypatch, quotes)

    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=60,
                              budget_s=60.0)

    entry = _depth_book(env.manifest)[_ALIVE]
    assert entry.get("floor"), f"the bond never floored: {entry}"
    assert out["floored"] == [_ALIVE]
    weeks = _weeks_asked(quotes)
    # 08-17 and 08-10 serve; 08-03 and 07-27 are empty and are the two strikes.
    assert weeks == [
        datetime.date(2026, 7, 27), datetime.date(2026, 8, 3),
        datetime.date(2026, 8, 10), datetime.date(2026, 8, 17),
    ], weeks
    assert entry["floor"] == "2026-07-27"

    # And it stays floored: a second night asks the wire nothing.
    before = len(quotes.calls)
    WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=60, budget_s=60.0)
    assert len(quotes.calls) == before, "a floored bond was chased again"


def test_the_budget_stops_the_pass_cleanly_and_records_where_it_got_to(
    env, monkeypatch
):
    """Budget exhaustion is the DESIGNED outcome, not a partial failure.

    The pass is meant to run out of time every night until the target is reached.
    What it must never do is lose the weeks it banked or forget where it stopped.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    # A budget already spent when the first batch is considered.
    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=365,
                              budget_s=0.0)

    assert out["stopped"] is True
    assert "budget" in out["reason"], out["reason"]
    assert out["weeks"] == 0
    assert quotes.calls == [], "the budget was spent and the wire was still used"


def test_depth_resumes_from_the_cursor_after_a_stop(env, monkeypatch):
    """Resume across a simulated stop: no week is re-fetched, none is skipped.

    The manifest cursor is the whole resume contract. A run that stops must cost
    the batch in flight and nothing else, and the run after it must not re-pay
    for the weeks already banked.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    # Stop after the first pass by making the second one exceed the budget: a
    # tiny but non-zero budget admits exactly one batch.
    calls = {"n": 0}
    real_perf = WARM.time.perf_counter

    def _clock():
        calls["n"] += 1
        return real_perf() + (0.0 if calls["n"] <= 3 else 1000.0)

    monkeypatch.setattr(WARM.time, "perf_counter", _clock)
    first = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=365,
                                budget_s=10.0)
    monkeypatch.undo()
    monkeypatch.setattr(WARM, "MANIFEST", env.manifest)
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 100.0)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    _install_fetcher(monkeypatch, quotes)

    assert first["stopped"] is True and "budget" in first["reason"]
    banked = set(_weeks_asked(quotes))
    assert banked, "the first run banked nothing, so resume proves nothing"
    cursor = _depth_book(env.manifest)[_ALIVE]["cursor"]
    assert cursor == (min(banked) - datetime.timedelta(days=7)).isoformat()

    WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21, budget_s=60.0)
    later = [w for w in _weeks_asked(quotes) if w not in banked]
    assert later, "the resumed run asked for nothing new"
    assert all(w < min(banked) for w in later), (
        "the resumed run went forwards over weeks it had already banked"
    )


def test_a_second_run_over_a_finished_target_fetches_nothing(env, monkeypatch):
    """Idempotence end to end, which is what makes this safe to run nightly."""
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21, budget_s=60.0)
    before = len(quotes.calls)
    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=21,
                              budget_s=60.0)

    assert len(quotes.calls) == before, "a finished target was re-fetched"
    assert out["weeks"] == 0


def test_an_outage_during_the_depth_pass_floors_nobody(env, monkeypatch):
    """A dead wire must never be recorded as "Citi has nothing below here".

    The floor is permanent — a floored bond is not asked again — so writing one
    on a night the wire was down would lose that bond's history for good.
    """
    alive, = _resolutions(_ALIVE)
    other, = _resolutions(_ALIVE_2)
    monkeypatch.setattr(WARM, "universe", lambda: [alive, other])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache, serve=False, reports="no block")
    _install_fetcher(monkeypatch, quotes)

    out = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=365,
                              budget_s=60.0)

    assert out["stopped"] is True
    assert "alive" in out["reason"], out["reason"]
    assert out["floored"] == []
    for entry in _depth_book(env.manifest).values():
        assert not entry.get("floor"), entry


def test_the_ceiling_stops_the_depth_pass_and_an_unreadable_probe_does_too(
    env, monkeypatch
):
    """Same fail-closed contract as the forward warm, checked between batches.

    "Could not tell" and "nothing running" are different facts, and a wedged
    13 GB add-in is what the second one hides.
    """
    alive, = _resolutions(_ALIVE)
    monkeypatch.setattr(WARM, "universe", lambda: [alive])
    cache = CitiVeloTagCache(base_dir=default_cache_dir())
    quotes = SpanQuotes(cache=cache)
    _install_fetcher(monkeypatch, quotes)

    # The first reading is the one ``assert_safe_to_connect`` consumes at the
    # top of the pass; the ones after it are the between-batch checks.
    readings = iter([100.0])
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: next(readings, 9_000.0))
    over = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=365,
                               budget_s=60.0)
    assert over["stopped"] is True and "ceiling" in over["reason"], over["reason"]
    assert quotes.calls == [], "the wire was used after the ceiling was reached"

    unreadable_readings = iter([100.0])
    monkeypatch.setattr(
        MG, "excel_memory_mb", lambda **k: next(unreadable_readings, None)
    )
    unreadable = WARM.backfill_depth(end=datetime.date(2026, 8, 20), depth_days=365,
                                     budget_s=60.0)
    assert unreadable["stopped"] is True, (
        "an unreadable probe let the pass run — 'could not tell' and 'nothing "
        "running' are different facts and this one must fail closed"
    )
    assert "could not read" in unreadable["reason"], unreadable["reason"]
    assert quotes.calls == []


def test_no_test_in_this_repo_can_write_the_production_warm_manifest():
    """The rail that would have prevented the 2026-08-20 accident.

    ``MANIFEST`` is bound at import from ``_manifest_path()``, and every warm
    suite monkeypatches the module attribute per test. That is a convention, and
    a convention held right up to the moment the warm grew a second entry point:
    a test that stubbed ``warm`` and called the nightly job reached the backwards
    depth pass, which was not stubbed, and wrote a 397-bond ``depth`` book into
    the live manifest tonight's cron resumes from.

    ``tests/conftest.py`` now sets ``ARBS_UST_WARM_MANIFEST`` at CONFTEST IMPORT,
    which is before test modules are collected - so it catches the module that
    imports the warm script at collection time as well as the one that imports it
    lazily inside the call under test. A session-scoped fixture would be too late
    for the first of those.

    This test asserts the property directly rather than trusting the fixture:
    both the freshly computed path and the value this module bound at import must
    be somewhere other than the real cache directory.
    """
    from MDP.CitiVelocityExcel.cache import default_cache_dir

    production = default_cache_dir() / "ust_universe_warm_manifest.json"
    assert WARM._manifest_path() != production, (
        "the manifest override is not in effect; a test that forgets to "
        "monkeypatch MANIFEST would write the live resume state"
    )
    assert pathlib.Path(WARM.MANIFEST) != production, (
        "this module bound MANIFEST at import, before the override was set - "
        "the rail has to be armed at conftest import, not in a fixture"
    )
