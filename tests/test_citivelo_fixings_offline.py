r"""The published-fixings lookup must not be what drags a warm curve into Excel.

Nothing here touches Excel, COM, the network or the real cache root: every
:class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache` is rooted in ``tmp_path``,
the only transport is :class:`~MDP.CitiVelocityExcel.testing.FakeExcelApp`, and
the one place a real connection could be attempted -
:meth:`CitiVeloQuotes.client` - is replaced by a class that records the attempt.

The incident these pin
----------------------
A minute-resolution ``USD-SOFR-1D`` request on 2026-08-08 died with
``AddInNotSignedInError`` even though the curve's NODES came from the store and
the fixing tag was on disk complete - 5,427 rows, 2005-01-03..2026-06-25. The
cause was the shape of the request, not the state of the cache::

    missing_spans(start=2005-01-01, end=today)
      -> [(2005-01-01, 2005-01-03), (2026-06-25, 2026-08-08)]

An explicit ``start`` earlier than the cached first row is a missing head, and
``history_start`` - the sidecar that ends that - is consulted only on the
``start is None`` branch. An ``end`` past the cached last row is a missing tail,
and Citi's USD tail is frozen six weeks back, so it could never be filled. Two
fetches per call, forever, for a series nothing was missing from.

What is asserted here is therefore a COUNT of connection attempts, never a
duration, and every "no Excel" test is paired with its own teeth:

* :func:`test_the_old_bounded_request_is_what_went_to_excel` replays the previous
  bounds against the same warm cache and asserts it DOES connect - without it,
  "no COM was attempted" would pass just as well against a reader that never
  connects under any circumstances;
* :func:`test_the_tail_is_re_requested_once_the_staleness_window_lapses` ages the
  sidecar and asserts the fetch comes back, so the staleness gate is shown to be
  a gate and not a mute.

The degrade is guarded by the same reasoning: serving a cached series when Excel
refuses is safe ONLY because ``assert_covers`` and the callers' own gate already
refuse a series that does not reach the date being priced, and that is asserted
directly rather than assumed.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import AddInNotSignedInError
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.IRSwaps.CITIVELO_EXCEL import fixings as F

CURVE = "USD-SOFR-1D"
INDEX = "USD_SOFR"
TAG = F.MONEY_MARKET_ON_TAG[INDEX]

#: The tail Citi actually serves for USD, six weeks behind the date being priced.
#: Modelled rather than mocked away: a series that ran to today would hide the
#: bug, because the tail span would close on its own.
FIRST = pd.Timestamp("2026-01-02")
LAST = pd.Timestamp("2026-06-25")


# ------------------------------------------------------------------ #
#                              fixtures                              #
# ------------------------------------------------------------------ #


@pytest.fixture(autouse=True)
def _clean_module_state(cache, monkeypatch):
    """Process-wide state reset, and the real cache root put out of reach.

    ``_warn_once`` and the source memos are module globals; tests are not.

    The cache pin is the more important half. ``fixings_for(quotes=None)``
    constructs its own :class:`CitiVeloQuotes`, which defaults to the DEVELOPER'S
    cache root - so a test that seeds ``cache`` and then goes through
    ``fixings_for`` was reading a completely different store. That is not
    theoretical: once the real cache settled (``history_start`` recorded, a fresh
    ``fetched_at``), ``missing_spans`` returned ``[]``, nothing fetched, nothing
    warned, and ``test_the_degraded_series_is_still_refused_when_it_does_not_reach_the_date``
    failed for a reason with nothing to do with the behaviour it asserts. It had
    passed until then only because the real cache happened to be unsettled.

    Pinning here rather than per test because the omission is invisible: the test
    still seeds a cache, still calls the right function, and still passes on any
    machine whose cache has not settled yet.
    """
    F.reset_fixings_cache()
    F._WARNED.clear()
    monkeypatch.setattr(
        "MDP.CitiVelocityExcel.quotes.CitiVeloTagCache", lambda *a, **k: cache
    )
    yield
    F.reset_fixings_cache()
    F._WARNED.clear()


@pytest.fixture()
def on_series() -> pd.Series:
    index = pd.bdate_range(FIRST, LAST)
    return pd.Series(
        4.30 + 0.0001 * np.arange(len(index)), index=index, dtype="float64"
    )


@pytest.fixture()
def cache(tmp_path: pathlib.Path) -> CitiVeloTagCache:
    return CitiVeloTagCache(base_dir=tmp_path / "citivelo_excel")


@pytest.fixture()
def fake_client(on_series: pd.Series) -> CitiVelocityExcelClient:
    app = FakeExcelApp(FakeVelocityData(series={TAG: on_series}))
    return CitiVelocityExcelClient(app=app, drain_seconds=0.0)


def _exploding_client_class():
    """A client replacement that records - and refuses - every connect."""

    class _ExplodingClient:
        attempts: list = []

        @classmethod
        def connect(cls, **kwargs):
            cls.attempts.append(dict(kwargs))
            raise AddInNotSignedInError()

    _ExplodingClient.attempts = []
    return _ExplodingClient


def _age_sidecar(cache: CitiVeloTagCache, tag: str, *, hours: float) -> None:
    """Backdate ``fetched_at`` so the staleness gate sees a real elapsed window.

    ``fetched_at`` is written at one-second resolution, so a test that seeds the
    cache and then calls in the same second cannot tell "refreshed" from "not".
    """
    path = cache.meta_path(tag, "DAILY", "CLOSE")
    meta = json.loads(path.read_text(encoding="utf-8"))
    when = datetime.datetime.now() - datetime.timedelta(hours=hours)
    meta["fetched_at"] = when.isoformat(timespec="seconds")
    path.write_text(json.dumps(meta, indent=1), encoding="utf-8")


def _settled_cache(cache: CitiVeloTagCache, series: pd.Series) -> None:
    """The end state this change is trying to reach: head closed, tail fresh."""
    cache.write(TAG, "DAILY", series)
    cache.set_history_start(TAG, "DAILY", series.index.min(), price_point="CLOSE")


class _ConcurrentlyWrittenCache(CitiVeloTagCache):
    """A cache whose sidecar is touched by SOMEBODY ELSE during our read.

    One cache root is shared by the live curve daemon, the warmers and whatever
    notebook is open, so ``fetched_at`` having advanced is not by itself proof
    that OUR call fetched anything. This makes that race deterministic.
    """

    def get(self, *args, **kwargs):
        out = super().get(*args, **kwargs)
        _age_sidecar(self, TAG, hours=-1.0)
        return out


# ------------------------------------------------------------------ #
#                    the two spans that never filled                 #
# ------------------------------------------------------------------ #


def test_the_old_bounded_request_reopens_two_spans_that_can_never_fill(cache, on_series):
    """The measured defect, reproduced from the cache alone.

    This is the arithmetic behind the incident and it does not need Excel to
    show: the head reopens because an explicit ``start`` skips the
    ``history_start`` branch entirely, and the tail reopens because Citi's last
    published fixing is older than the ``end`` being asked for.
    """
    _settled_cache(cache, on_series)

    spans = cache.missing_spans(
        TAG,
        "DAILY",
        start=datetime.date(2005, 1, 1),
        end=datetime.date.today(),
        price_point="CLOSE",
        max_staleness=None,
    )
    assert len(spans) == 2, "the old bounds asked for a head AND a tail"
    assert spans[0][0] == pd.Timestamp("2005-01-01")
    assert spans[1][1] == pd.Timestamp(datetime.date.today())

    settled = cache.missing_spans(
        TAG,
        "DAILY",
        start=None,
        end=None,
        price_point="CLOSE",
        max_staleness=F._FIXINGS_MAX_STALENESS,
    )
    assert settled == [], (
        "unbounded, the same cache has nothing missing: the head closes through "
        "history_start and the tail through the staleness gate"
    )


# ------------------------------------------------------------------ #
#                     a warm cache stays off Excel                   #
# ------------------------------------------------------------------ #


def test_a_warm_fixing_cache_never_attaches_to_excel(cache, on_series, monkeypatch):
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _settled_cache(cache, on_series)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    got = F.citi_fixings(INDEX, quotes=quotes)

    assert exploding.attempts == [], "a complete cached series still went looking for Excel"
    assert len(got) == len(on_series)
    assert got.index.max() == LAST
    assert float(got.iloc[-1]) == pytest.approx(float(on_series.iloc[-1]))


def test_the_old_bounded_request_is_what_went_to_excel(cache, on_series, monkeypatch):
    """Teeth for the test above, through the reader rather than the cache."""
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _settled_cache(cache, on_series)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    with pytest.raises(AddInNotSignedInError):
        quotes.frame(
            [TAG], "DAILY", start=datetime.date(2005, 1, 1), end=datetime.date.today()
        )
    assert len(exploding.attempts) == 1


def test_the_tail_is_re_requested_once_the_staleness_window_lapses(
    cache, on_series, monkeypatch
):
    """Teeth for the staleness gate: it is a gate, not a mute."""
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _settled_cache(cache, on_series)
    _age_sidecar(cache, TAG, hours=F._FIXINGS_MAX_STALENESS.total_seconds() / 3600 + 1)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    with pytest.warns(UserWarning, match="would not serve"):
        F.citi_fixings(INDEX, quotes=quotes)

    assert len(exploding.attempts) == 1, "a lapsed tail must go and look"


# ------------------------------------------------------------------ #
#                          history_start                             #
# ------------------------------------------------------------------ #


def test_an_unbounded_fetch_records_the_history_start_it_learned(cache, fake_client):
    """One live call closes the head for every call after it."""
    quotes = CitiVeloQuotes(client=fake_client, cache=cache, offline=False)
    got = F.citi_fixings(INDEX, quotes=quotes)
    assert not got.empty

    cov = cache.coverage(TAG, "DAILY", "CLOSE")
    assert cov.history_start is not None, "the head would reopen on every later call"
    assert cov.history_start == FIRST
    assert cov.complete_back is True


def test_a_signed_out_excel_does_not_record_a_history_start(cache, on_series, monkeypatch):
    """A guess made from a fetch that never happened would truncate history.

    The cache here holds only the second half of the series, so stamping its
    first row as the tag's inception would permanently hide the first half.
    """
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    partial = on_series.iloc[len(on_series) // 2 :]
    cache.write(TAG, "DAILY", partial)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    with pytest.warns(UserWarning, match="would not serve"):
        F.citi_fixings(INDEX, quotes=quotes)

    cov = cache.coverage(TAG, "DAILY", "CLOSE")
    assert cov.history_start is None
    assert cov.complete_back is False


def test_an_offline_reader_does_not_record_a_history_start(tmp_path, on_series):
    """Offline asked the add-in nothing, so it learned nothing about inception.

    The cache used here has its sidecar written by another process mid-read, which
    is the only thing that makes this test discriminate: ``fetched_at`` advances,
    so the "was anything actually written" guard is satisfied, and ONLY the
    offline check stands between a read of half a series and a permanent claim
    that half is all there ever was.
    """
    cache = _ConcurrentlyWrittenCache(base_dir=tmp_path / "citivelo_excel")
    partial = on_series.iloc[len(on_series) // 2 :]
    cache.write(TAG, "DAILY", partial)

    quotes = CitiVeloQuotes(cache=cache, offline=True)
    got = F.citi_fixings(INDEX, quotes=quotes)

    assert len(got) == len(partial), "offline still serves what is on disk"
    assert cache.coverage(TAG, "DAILY", "CLOSE").history_start is None


def test_a_fetch_that_returned_nothing_records_no_history_start(cache, on_series):
    """An empty answer is not an answer, and must not be mistaken for the bottom.

    The add-in distinguishes "no such tag" from "no rows here" and both arrive as
    a normal return, not an exception. If that counted as "there is nothing
    older", one bad afternoon on the wire would stamp half a series as the whole
    of it - permanently, because ``history_start`` is never re-asked once set.
    """
    serves_nothing = CitiVelocityExcelClient(
        app=FakeExcelApp(FakeVelocityData(series={})), drain_seconds=0.0
    )
    partial = on_series.iloc[len(on_series) // 2 :]
    cache.write(TAG, "DAILY", partial)
    _age_sidecar(cache, TAG, hours=48)

    quotes = CitiVeloQuotes(client=serves_nothing, cache=cache, offline=False)
    got = F.citi_fixings(INDEX, quotes=quotes)

    assert len(got) == len(partial), "the cached rows are still served"
    cov = cache.coverage(TAG, "DAILY", "CLOSE")
    assert cov.first == partial.index.min(), "nothing was written"
    assert cov.history_start is None, "an empty wire answer is not evidence of inception"


def test_older_rows_arriving_defer_the_history_start(cache, on_series, fake_client):
    """The head fetch brought data older than the cache held: not the bottom yet."""
    cache.write(TAG, "DAILY", on_series.iloc[len(on_series) // 2 :])
    _age_sidecar(cache, TAG, hours=48)

    quotes = CitiVeloQuotes(client=fake_client, cache=cache, offline=False)
    F.citi_fixings(INDEX, quotes=quotes)

    cov = cache.coverage(TAG, "DAILY", "CLOSE")
    assert cov.first == FIRST, "the older rows were merged in"
    assert cov.history_start is None, "the call that learned them cannot also settle them"

    # ``fetched_at`` is second-resolution, and "did this call write anything" is
    # read off it. Two calls inside one second are indistinguishable, so the
    # second one is separated in time rather than left to the clock.
    _age_sidecar(cache, TAG, hours=48)
    F.citi_fixings(INDEX, quotes=quotes)  # the next one, which starts from the bottom
    assert cache.coverage(TAG, "DAILY", "CLOSE").history_start == FIRST


# ------------------------------------------------------------------ #
#                            the degrade                             #
# ------------------------------------------------------------------ #


def test_a_signed_out_excel_degrades_to_the_cached_series(cache, on_series, monkeypatch):
    """The whole point: an unreachable add-in must not be a hard failure here."""
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    cache.write(TAG, "DAILY", on_series)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    with pytest.warns(UserWarning, match="would not serve"):
        got = F.citi_fixings(INDEX, quotes=quotes)

    assert len(exploding.attempts) >= 1, "it did try, and the try failed"
    assert len(got) == len(on_series)
    pd.testing.assert_series_equal(
        got, on_series.astype("float64"), check_names=False, check_freq=False
    )


def test_the_degraded_series_is_still_refused_when_it_does_not_reach_the_date(
    cache, on_series, monkeypatch
):
    """Serving stale rows is safe only because the gate downstream still bites.

    Without this, the degrade would be a way to silently under-fix a float leg -
    which is the failure the whole module exists to prevent.
    """
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    monkeypatch.setattr(F, "official_fixings", lambda name: pd.Series(dtype="float64"))
    cache.write(TAG, "DAILY", on_series)

    needed = (LAST + pd.Timedelta(days=30)).date()
    with pytest.warns(UserWarning, match="would not serve"):
        result = F.fixings_for(CURVE, INDEX, reference_date=needed)

    assert not result.empty, "the cached rows were served"
    with pytest.raises(F.FixingsUnavailableError, match="fixings stop at"):
        result.assert_covers(needed)


def test_the_store_fixings_gate_survives_a_signed_out_excel(cache, on_series, monkeypatch):
    """The traceback from the incident, turned into an assertion.

    ``_citivelo_excel_store_fixings`` is the frame that raised. It must now return
    - empty when the tail is too old to trust, populated when it is not - so a
    curve whose nodes came from the store finishes building either way.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    monkeypatch.setattr(F, "official_fixings", lambda name: pd.Series(dtype="float64"))
    monkeypatch.setattr(
        "MDP.CitiVelocityExcel.quotes.CitiVeloTagCache", lambda *a, **k: cache
    )
    cache.write(TAG, "DAILY", on_series)

    mdp = IRSwapsMDP.__new__(IRSwapsMDP)  # no __init__: this method needs no state

    stale = mdp._citivelo_excel_store_fixings(
        curve_name=CURVE, citi_index=INDEX, reference_date=datetime.date(2026, 7, 31)
    )
    assert stale.empty, "six weeks behind is past the gate, so nothing is served"

    F.reset_fixings_cache()
    fresh = mdp._citivelo_excel_store_fixings(
        curve_name=CURVE,
        citi_index=INDEX,
        reference_date=(LAST + pd.Timedelta(days=1)).date(),
    )
    assert not fresh.empty, "inside the gate the cached fixings are served, no Excel"


# ------------------------------------------------------------------ #
#                              edges                                 #
# ------------------------------------------------------------------ #


def test_a_curve_with_no_fixing_tag_touches_nothing(cache, monkeypatch):
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    got = F.citi_fixings("NOK_NOWA", quotes=CitiVeloQuotes(client=None, cache=cache))
    assert got.empty
    assert exploding.attempts == []


def test_explicit_bounds_are_still_honoured(cache, on_series, monkeypatch):
    """The window arguments remain a window; only the default became unbounded."""
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _settled_cache(cache, on_series)

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    got = F.citi_fixings(
        INDEX,
        quotes=quotes,
        start=datetime.date(2026, 3, 2),
        end=datetime.date(2026, 3, 31),
    )
    assert got.index.min() >= pd.Timestamp("2026-03-02")
    assert got.index.max() <= pd.Timestamp("2026-03-31")
    assert exploding.attempts == [], "a window inside the cached span needs no fetch"
