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
    """

    offline = True

    def __init__(self, *, writes_at="same", raise_on=None, watch_manifest=None):
        self.writes_at = writes_at
        self.raise_on = raise_on
        self.watch_manifest = watch_manifest
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
            )
        )
        if self.watch_manifest is not None:
            self.manifest_seen.append(len(_book(self.watch_manifest, "eod")))
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise RuntimeError("Excel went away mid-batch")
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
    """
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(WARM, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 100.0)
    return SimpleNamespace(mod=WARM, tmp=tmp_path, manifest=tmp_path / "manifest.json")


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
