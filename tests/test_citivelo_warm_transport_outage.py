r"""A total Velocity outage must STOP the universe warm, not report success.

``scripts/citivelo_ust_universe_warm.warm`` has to separate two observations
that arrive looking identical, and getting the separation wrong has now cost the
nightly run in both directions:

**Treating "no rows" as a fault** aborted the 877-bond intraday warm at 0/877 on
five of ten retained nightly runs, in 2.9-4.4 s each. ``universe()`` sorts by
ISIN, the 22 lowest ISINs in the catalog all matured between 2016 and 2025, and
``DEFAULT_BATCH`` is 8 - so batch 0 is all-dead BY CONSTRUCTION, and a matured
bond asked for a window after it redeemed correctly holds nothing.

**Treating a fault as "no rows"** is the opposite failure and is worse, because
it is silent. ``CitiVeloQuotes.frame`` returns an EMPTY FRAME AND RAISES NOTHING
when every tag in the request fails: ``series()`` returns only the tags that came
back, and ``frame()`` builds an empty DataFrame from an empty dict. Its own
docstring says a failed tag "is simply an absent COLUMN here, which is
indistinguishable from a tag that returned no rows unless the reasons are asked
for". Measured on the real 877-bond catalog against a dead transport, the warm
stamped 877 bonds done, warmed 0, returned ``stopped=False`` - so the job wrapper
did not raise, the job reported OK and the warmer exited 0 - and the stamped
manifest then blocked the same-day re-run that would have recovered the day.

The discriminator is the REASON, which is why ``failures=`` is now threaded
through. A live add-in answers per column: ``"empty"``, ``"bad tag"``,
``"no column"``. A wire that produced no readable block at all writes
``failures[tag] = excel_error_name(value) or "no block"`` for every tag in the
chunk (``com_client.py:968-971``). The first set continues; the second stops.

Hermetic: the real catalog and the real ``CitiVeloBondFetcher.plan`` (pure, and
what decides which tags exist at all), a local fake for the wire, the tag cache
redirected into ``tmp_path``, the manifest redirected into ``tmp_path``, and the
memory probe stubbed - it shells out to PowerShell against the live EXCEL.EXE
otherwise. No Excel, no COM, no network.
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

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "citivelo_ust_universe_warm.py"

#: The catalog as it stands. Asserted rather than assumed by
#: :func:`test_the_outage_is_measured_against_the_whole_catalog`, because the
#: whole point of this file is that it runs against the real universe the
#: nightly job runs against, not against a hand-picked handful.
_CATALOG_AT_LEAST = 877

_END = datetime.date(2026, 8, 18)
_START = _END - datetime.timedelta(days=30)


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


# ── the fakes ────────────────────────────────────────────────────────────


class _Wire:
    """A ``CitiVeloQuotes``-shaped reader that models what the WIRE reports.

    ``reason`` is the whole point. ``CitiVeloQuotes.frame`` hands a caller's
    ``failures`` mapping down to ``series`` -> the cache fetcher closure ->
    ``client.last_failures()``, so a fake that returns an empty frame WITHOUT
    filling ``failures`` models a case that cannot occur on a live fetch and
    quietly makes an outage untestable. Both empty-frame cases here therefore
    fill it, with the reason ``block_parser``/``com_client`` would really write:

    ``"no block"``   the chunk came back with no readable block. What a dead
                     wire produces, for EVERY tag (``com_client.py:968-971``).
    ``"empty"``      the column came back with no rows in this window. What a
                     matured bond produces (``block_parser.py:385``).

    ``rows`` is the healthy case: it writes through the REAL
    :class:`CitiVeloTagCache`, so a positive test also proves the cache layout
    and ``cached_tags`` still agree about where a warmed tag lives.
    """

    offline = True

    def __init__(self, *, reason=None, rows=False):
        self.reason = reason
        self.rows = rows
        self.calls = 0
        self.tags_seen = []
        self.closed = False

    def frame(self, tags, freq="DAILY", **kwargs):
        wanted = [str(t) for t in tags]
        self.calls += 1
        self.tags_seen.append(wanted)
        failures = kwargs.get("failures")
        if not self.rows:
            if failures is not None:
                for tag in wanted:
                    failures[tag] = self.reason
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))

        index = pd.date_range("2026-08-17", periods=2, freq="D")
        served = {t: pd.Series([1.0, 2.0], index=index) for t in wanted}
        cache = CitiVeloTagCache(base_dir=default_cache_dir())
        for tag, series in served.items():
            cache.write(tag, freq, series)
        frame = pd.concat(served, axis=1)
        frame.index.name = "Date"
        return frame.sort_index()

    def close(self):
        self.closed = True


#: Bound ONCE, at import. Reading ``BF.CitiVeloBondFetcher`` inside the installer
#: instead would capture whatever the PREVIOUS ``_install_fetcher`` call left
#: there, so a test that installs a second transport would silently keep talking
#: to the first one - which is exactly the shape of the re-run test below, and it
#: reported a false pass for the fixed code before this line existed.
_REAL_FETCHER = BF.CitiVeloBondFetcher


def _install_fetcher(monkeypatch, quotes):
    """The REAL fetcher wrapped around ``quotes``. Only the wire is faked.

    ``plan`` is kept because it is pure and is what decides which tags exist at
    all - it reads the committed coverage harvest and builds no tag for a value
    a bond is known not to serve. ``close()`` on a fetcher with an injected
    reader is a no-op by design, so nothing here can close a live client that
    was never opened.
    """
    real_cls = _REAL_FETCHER

    class _Wrapper:
        def __init__(self):
            self._inner = real_cls(quotes=quotes)

        def quotes(self):
            return self._inner.quotes()

        def plan(self, resolutions, *, values=None):
            return self._inner.plan(resolutions, values=values)

        def close(self):
            self._inner.close()

    monkeypatch.setattr(BF, "CitiVeloBondFetcher", lambda *a, **k: _Wrapper())


def _stamped(manifest, mode):
    if not pathlib.Path(manifest).exists():
        return {}
    book = json.loads(pathlib.Path(manifest).read_text(encoding="utf-8")).get(mode, {})
    return {k: v for k, v in book.items() if v.get("key")}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Cache, manifest and memory probe all redirected away from the real ones."""
    monkeypatch.setenv("CITIVELO_EXCEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(WARM, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(MG, "excel_memory_mb", lambda **k: 100.0)
    return SimpleNamespace(tmp=tmp_path, manifest=tmp_path / "manifest.json")


# ══════════════════════════════════════════════════════════════════════════
# 1. THE OUTAGE MUST STOP THE RUN
# ══════════════════════════════════════════════════════════════════════════


def test_the_outage_is_measured_against_the_whole_catalog():
    """The fidelity these tests are worth anything for.

    The defect was invisible on a handful of live bonds and obvious on the real
    universe, because the real universe is majority-matured: 528 of 877 have
    redeemed. A test built on eight hand-picked live ISINs would have agreed with
    the broken code.
    """
    uni = WARM.universe()
    assert len(uni) >= _CATALOG_AT_LEAST, (
        f"the USA.USD.GOVT universe is {len(uni)}, below the {_CATALOG_AT_LEAST} "
        "these measurements were taken on. It is a union that never removes, so a "
        "decrease means something was deleted from the catalog."
    )


def test_a_dead_transport_stops_the_warm_instead_of_reporting_success(env, monkeypatch):
    """Every tag fails, nothing raises - the run must still stop.

    On the code this replaces, this exact stimulus stamped all 877 bonds done at
    today's key, returned ``stopped=False``, and the warmer exited 0.
    """
    wire = _Wire(reason="no block")
    _install_fetcher(monkeypatch, wire)

    out = WARM.warm("eod", start=_START, end=_END, do_refresh=False)

    assert wire.calls, "nothing was fetched; this test is not exercising the guard"
    assert out["stopped"] is True, (
        "a total Velocity outage was reported as a completed warm - the wrapper "
        "does not raise on that, so the job reports OK and the warmer exits 0"
    )
    assert out["done"] == 0
    assert "no block" in out["reason"], (
        f"the stop must carry the transport's own reasons, got {out['reason']!r}"
    )


def test_a_dead_transport_stamps_no_bond_done(env, monkeypatch):
    """The manifest side-effect, which is what kills the same-day retry.

    Measured on the broken code: 877 bonds stamped at today's key after a run
    that warmed nothing.
    """
    wire = _Wire(reason="no block")
    _install_fetcher(monkeypatch, wire)

    WARM.warm("eod", start=_START, end=_END, do_refresh=False)

    assert _stamped(env.manifest, "eod") == {}, (
        "bonds were stamped done by a run in which Velocity answered nothing at "
        "all - and the stamp is what blocks the re-run that recovers the day"
    )


def test_the_same_day_rerun_after_an_outage_actually_retries(env, monkeypatch):
    """The recovery path, end to end: outage, then Velocity comes back.

    On the broken code the re-run made ZERO transport calls, because the first
    run's stamps said the whole universe was already warm at this key. The
    manifest is the resume key, so an outage that stamps is an outage that
    cannot be retried until the window moves - i.e. not today.
    """
    dead = _Wire(reason="no block")
    _install_fetcher(monkeypatch, dead)
    WARM.warm("eod", start=_START, end=_END, do_refresh=False)

    healthy = _Wire(rows=True)
    _install_fetcher(monkeypatch, healthy)
    out = WARM.warm("eod", start=_START, end=_END, limit=8, do_refresh=False)

    assert healthy.calls > 0, (
        "the re-run asked Velocity for nothing at all - the outage's manifest "
        "stamps blocked the retry that would have recovered the day"
    )
    assert out["stopped"] is False and out["done"] == 8
    assert len(_stamped(env.manifest, "eod")) == 8


def test_the_job_wrapper_raises_so_the_warmer_cannot_exit_zero(env, monkeypatch):
    """The other half of the silence: ``stopped`` is the only thing that raises.

    ``daily_cache_warmer.warm_citivelo_ust_universe_eod`` returns ``None`` unless
    ``out["stopped"]``, and a job that returns cleanly is reported OK. So a
    ``stopped=False`` outage is not merely mislabelled inside the script - it
    reaches the scheduler as ``rc=0``.
    """
    import scripts.daily_cache_warmer as DCW

    wire = _Wire(reason="no block")
    _install_fetcher(monkeypatch, wire)
    monkeypatch.setattr("scripts.citivelo_ust_universe_warm.warm", WARM.warm)
    monkeypatch.setenv("CITIVELO_UST_EOD_DAYS", "30")

    with pytest.raises(RuntimeError, match="stopped"):
        DCW.warm_citivelo_ust_universe_eod(_END, _END)


@pytest.mark.parametrize("reason", ["no block", "no header row", "#N/A", "#VALUE!"])
def test_every_reason_that_is_not_a_per_column_answer_stops_the_run(env, monkeypatch, reason):
    """Fail CLOSED on the reasons nobody has catalogued.

    ``"no block"`` is the measured outage; the others are what
    ``fetch_timeseries`` writes when the add-in returns an Excel error value for
    a whole chunk. A reason nobody has seen before is not evidence that the wire
    is healthy, which is exactly the assumption the previous version made.
    """
    wire = _Wire(reason=reason)
    _install_fetcher(monkeypatch, wire)

    out = WARM.warm("eod", start=_START, end=_END, do_refresh=False)

    assert out["stopped"] is True, f"{reason!r} was treated as a bond with no rows"
    assert _stamped(env.manifest, "eod") == {}


# ══════════════════════════════════════════════════════════════════════════
# 2. AND THE MATURED-BOND CASE MUST STILL NOT STOP IT
# ══════════════════════════════════════════════════════════════════════════
#
# This is the half that the fix being tested above must not take back with it.
# The `rows_served > 0` condition was added because the guard it replaced
# aborted the whole 877-bond warm at batch 0 every night; a fix for the outage
# that stops on a matured bond has simply reinstated that.


@pytest.mark.parametrize("reason", ["empty", "bad tag", "no column"])
def test_a_per_column_answer_is_recorded_and_the_warm_continues(env, monkeypatch, reason):
    """A live add-in answering "there is nothing here" is not an outage.

    ``"empty"`` is what a matured bond returns for a window after it redeemed.
    ``"bad tag"`` and ``"no column"`` are the add-in rejecting or omitting one
    symbol - all three are a working wire, per column, and none of them is a
    reason to abandon the other 869 bonds.
    """
    wire = _Wire(reason=reason)
    _install_fetcher(monkeypatch, wire)

    out = WARM.warm("eod", start=_START, end=_END, limit=8, do_refresh=False)

    assert out["stopped"] is False, (
        f"{reason!r} is a per-column answer from a live add-in and stopped the "
        f"warm: {out.get('reason')!r}"
    )
    book = json.loads(env.manifest.read_text(encoding="utf-8"))["eod"]
    assert len(book) == 8, "a bond with nothing to warm must still be recorded"
    for entry in book.values():
        assert entry["tags"] == 0 and entry["note"], entry
        assert reason in entry.get("why", ""), (
            f"the record must say WHY there were no rows, got {entry!r}"
        )


def test_nothing_reported_at_all_is_still_treated_as_no_rows(env, monkeypatch):
    """A read served entirely from cache reports no reasons, and that is fine.

    ``series`` writes nothing into ``failures`` when no fetch happened, because
    the client's record would belong to some earlier request. An empty mapping
    must therefore keep meaning "no rows", or a fully-cached batch would stop the
    run.
    """
    wire = _Wire(reason=None)
    monkeypatch.setattr(
        _Wire, "frame",
        lambda self, tags, freq="DAILY", **kw: (
            self.tags_seen.append(list(tags)),
            pd.DataFrame(index=pd.DatetimeIndex([], name="Date")),
        )[1],
    )
    _install_fetcher(monkeypatch, wire)

    out = WARM.warm("eod", start=_START, end=_END, limit=8, do_refresh=False)

    assert out["stopped"] is False, out.get("reason")
    assert len(json.loads(env.manifest.read_text(encoding="utf-8"))["eod"]) == 8


def test_the_intraday_path_asks_for_the_reasons_too(env, monkeypatch):
    """``_warm_intraday`` passed ``failures=None`` and discarded them.

    The intraday warm is the one that runs against MI01 windows, where the
    majority-matured catalog makes an empty answer the NORMAL one - so it is the
    path where an outage hides best. ``warm_windows`` already merged the reasons
    across every window it issued; nothing asked it for them.
    """
    seen = {}

    class _Recorder:
        offline = True

        def frame(self, tags, freq="DAILY", **kwargs):
            failures = kwargs.get("failures")
            assert failures is not None, (
                "_warm_intraday did not ask warm_windows for the reasons, so an "
                "MI01 outage is indistinguishable from a matured bond"
            )
            for tag in tags:
                failures[str(tag)] = "no block"
            seen["asked"] = True
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))

    out = {}
    rows = WARM._warm_intraday(
        _Recorder(), ["RATES.BOND.US912810EX29.PRICE"],
        start=_END - datetime.timedelta(days=2), end=_END, failures=out,
    )

    assert seen.get("asked")
    assert rows == 0
    assert out == {"RATES.BOND.US912810EX29.PRICE": "no block"}, (
        "the reasons reached warm_windows but were not handed back to the caller"
    )


def test_an_intraday_outage_stops_the_warm(env, monkeypatch):
    """The same discrimination, on the path the nightly intraday job takes."""
    wire = _Wire(reason="no block")
    _install_fetcher(monkeypatch, wire)

    out = WARM.warm(
        "intraday",
        start=_END - datetime.timedelta(days=2), end=_END,
        do_refresh=False,
    )

    assert out["stopped"] is True, out
    assert "no block" in out["reason"]
    assert _stamped(env.manifest, "intraday") == {}
