r"""Hermetic tests for the Citi Velocity cache, quote reader and MDP source.

Nothing here touches Excel, COM, the network, a database or the real cache root:
every :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache` is built with
``base_dir=tmp_path``, and the only "transport" is an underscore-prefixed
recording fetcher that replays canned pandas series and remembers exactly which
spans it was asked for. The one place a COM connection could plausibly be
attempted - :meth:`CitiVeloQuotes.client` - is monkeypatched to a class that
raises if anyone calls it, so "the cache served this without Excel" is asserted
rather than assumed.

Three tests are paired with a MUTATION CHECK: the same input is also run through
a deliberately-wrong variant of the thing under test, and the test asserts the
wrong variant produces a different, wrong answer. Without that pairing "the
merge produced 25 rows" passes just as happily against a merge that keeps the
stale print, and "MI01 and DAILY are separate" passes against a cache that never
looked at the frequency at all.

The properties that carry the most weight, and why:

* **Incoming wins a merge collision.** A re-fetch of an overlapping span is how a
  revised print reaches us; keeping the existing value pins the stale one forever.
* **``history_start`` is what terminates a "full history" request.** Without the
  ``CVMETADATA`` sidecar, ``start=None`` re-requests the whole span on every call
  for the life of the cache.
* **Intraday and daily are different data.** A one-minute series and a daily
  series of the same tag share a tag but not a meaning; collapsing them picks an
  arbitrary minute per day.
* **``asof`` is backward-only.** ``nearest`` is direction-unbounded and is shown
  here answering with a row from the FUTURE, which is exactly why it is not the
  default.
"""

from __future__ import annotations

import datetime
import logging
import pathlib
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pytest

from MDP.CitiVelocityExcel.cache import _MAX_STEM, CitiVeloTagCache, sanitise_tag
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes, snapshot_from_frame
from MDP.CitiVelocityExcel.source import CitiVelocityExcelSource

TAG_10Y = "RATES.OIS.USD_SOFR.PAR.10Y"
TAG_2Y = "RATES.OIS.USD_SOFR.PAR.2Y"

#: The OIS par axis is 44 tenors wide, which is the batching case that matters:
#: a cold grid must cost one ``CVTSHIST``, not 44.
GRID_TENORS: Tuple[str, ...] = (
    "1W", "2W", "3W",
    "1M", "2M", "3M", "4M", "5M", "6M", "7M", "8M", "9M", "10M", "11M",
    "1Y", "15M", "18M", "21M",
    "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "11Y", "12Y",
    "13Y", "14Y", "15Y", "16Y", "17Y", "18Y", "19Y", "20Y", "21Y", "25Y",
    "30Y", "35Y", "40Y", "45Y", "50Y",
)
GRID_TAGS: List[str] = [f"RATES.OIS.USD_SOFR.PAR.{t}" for t in GRID_TENORS]

CACHE_LOGGER = "MDP.CitiVelocityExcel.cache"


# ------------------------------------------------------------------ #
#                        fixtures and fake data                      #
# ------------------------------------------------------------------ #


@pytest.fixture()
def cache(tmp_path: pathlib.Path) -> CitiVeloTagCache:
    """A cache rooted in ``tmp_path`` - never the developer's real cache root."""
    return CitiVeloTagCache(base_dir=tmp_path / "citivelo_excel")


@pytest.fixture()
def daily_index() -> pd.DatetimeIndex:
    return pd.bdate_range("2026-07-01", "2026-08-04")


def _daily(index: pd.DatetimeIndex, base: float = 4.20, step: float = 0.001) -> pd.Series:
    return pd.Series(base + step * np.arange(len(index)), index=index)


def _grid_data(index: pd.DatetimeIndex) -> Dict[str, pd.Series]:
    return {tag: _daily(index, base=4.0 + 0.01 * i) for i, tag in enumerate(GRID_TAGS)}


@dataclass(frozen=True)
class _FetchCall:
    tags: Tuple[str, ...]
    freq: str
    start: Optional[datetime.datetime]
    end: Optional[datetime.datetime]
    price_point: str


class _RecordingFetcher:
    """A stand-in for the client's timeseries fetcher that records every call.

    Matches the ``Fetcher`` protocol in :mod:`MDP.CitiVelocityExcel.cache`
    (``(tags, freq, start, end, price_point) -> {tag: Series}``) and slices its
    canned series to the requested span, so a test can distinguish "asked for the
    whole history" from "asked only for the tail".
    """

    def __init__(self, data: Mapping[str, pd.Series]):
        self._data = {k: v for k, v in data.items()}
        self.calls: List[_FetchCall] = []

    def __call__(self, tags, freq, start, end, price_point):  # noqa: D102 - protocol
        self.calls.append(_FetchCall(tuple(tags), freq, start, end, price_point))
        out: Dict[str, pd.Series] = {}
        for tag in tags:
            series = self._data.get(tag)
            if series is None:
                continue
            sub = series
            if start is not None:
                sub = sub[sub.index >= pd.Timestamp(start)]
            if end is not None:
                sub = sub[sub.index <= pd.Timestamp(end)]
            if not sub.empty:
                out[tag] = sub
        return out

    @property
    def n_calls(self) -> int:
        return len(self.calls)


def _exploding_client_class():
    """A ``CitiVelocityExcelClient`` replacement that fails if anyone connects.

    Returned fresh per test so the attempt counter cannot leak between tests.
    """

    class _ExplodingClient:
        attempts: List[dict] = []

        @classmethod
        def connect(cls, **kwargs):
            cls.attempts.append(dict(kwargs))
            raise AssertionError(
                "CitiVeloQuotes tried to attach to Excel; the cache should have served this."
            )

    _ExplodingClient.attempts = []
    return _ExplodingClient


def _warm_cache(cache: CitiVeloTagCache, index: pd.DatetimeIndex, tags: Sequence[str]) -> None:
    for i, tag in enumerate(tags):
        cache.write(tag, "DAILY", _daily(index, base=4.0 + 0.01 * i))


# ------------------------------------------------------------------ #
#                     write / read round trip                        #
# ------------------------------------------------------------------ #


def test_write_read_round_trip_normalises_dtype_and_index(cache, daily_index):
    """A round trip must return float64 values on an ascending named DatetimeIndex.

    The input is deliberately integer-valued and shuffled: parquet would happily
    round-trip an int column and an arbitrary row order, and every downstream
    consumer (curve solves, snapshots, ``asof``) assumes neither.
    """
    shuffled = pd.Series(
        np.arange(len(daily_index), dtype="int64"),
        index=daily_index[::-1],
    )
    cache.write(TAG_10Y, "DAILY", shuffled)

    out = cache.read(TAG_10Y, "DAILY")
    assert out is not None
    assert out.dtype == np.dtype("float64")
    assert isinstance(out.index, pd.DatetimeIndex)
    assert out.index.is_monotonic_increasing
    assert out.index.name == "Date"
    assert out.name == TAG_10Y
    assert len(out) == len(daily_index)
    assert out.loc[daily_index[0]] == pytest.approx(float(len(daily_index) - 1))


def test_read_of_an_absent_key_is_none_not_an_error(cache):
    assert cache.read(TAG_10Y, "DAILY") is None
    assert cache.coverage(TAG_10Y, "DAILY") is None
    assert cache.keys() == []


def test_coverage_reports_bounds_row_count_and_history_start(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index), history_start="2018-01-02")
    cov = cache.coverage(TAG_10Y, "DAILY")
    assert cov is not None
    assert cov.first == daily_index.min()
    assert cov.last == daily_index.max()
    assert cov.n_rows == len(daily_index)
    assert cov.history_start == pd.Timestamp("2018-01-02")
    assert cov.fetched_at is not None
    assert cov.complete_back is False  # the cache starts in 2026, history in 2018


# ------------------------------------------------------------------ #
#                        merge, and who wins                         #
# ------------------------------------------------------------------ #


def test_merge_is_the_union_and_incoming_wins_a_collision():
    existing = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03"]))
    incoming = pd.Series([2.5, 4.0], index=pd.to_datetime(["2026-08-02", "2026-08-04"]))

    merged = CitiVeloTagCache.merge(existing, incoming)

    assert list(merged.index) == list(pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]))
    assert merged.loc[pd.Timestamp("2026-08-02")] == pytest.approx(2.5)  # the revision
    assert merged.loc[pd.Timestamp("2026-08-04")] == pytest.approx(4.0)
    assert merged.dtype == np.dtype("float64")
    assert merged.index.is_monotonic_increasing


def test_merge_keeping_the_existing_value_pins_a_stale_print():
    """MUTATION CHECK for the collision rule.

    A re-fetch of an overlapping span is the ONLY way a revised print reaches
    this cache. A merge that resolves a timestamp collision in favour of what is
    already on disk therefore pins the first value ever seen, and no amount of
    re-fetching will ever dislodge it. This test runs the same pair through that
    wrong rule and asserts it answers with the stale number.
    """
    stamp = pd.Timestamp("2026-08-02")
    existing = pd.Series([2.0], index=[stamp])
    incoming = pd.Series([2.5], index=[stamp])  # the exchange revised the print

    def _merge_keeping_existing(a: pd.Series, b: pd.Series) -> pd.Series:
        combined = pd.concat([a, b])
        return combined[~combined.index.duplicated(keep="first")].sort_index()

    good = CitiVeloTagCache.merge(existing, incoming)
    bad = _merge_keeping_existing(existing, incoming)

    assert good.loc[stamp] == pytest.approx(2.5)
    assert bad.loc[stamp] == pytest.approx(2.0)
    assert good.loc[stamp] != bad.loc[stamp]


def test_write_merges_into_what_is_already_cached(cache):
    first = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-08-01", "2026-08-02"]))
    revision = pd.Series([2.5, 3.0], index=pd.to_datetime(["2026-08-02", "2026-08-03"]))

    cache.write(TAG_10Y, "DAILY", first)
    returned = cache.write(TAG_10Y, "DAILY", revision)

    on_disk = cache.read(TAG_10Y, "DAILY")
    assert len(on_disk) == 3
    assert on_disk.loc[pd.Timestamp("2026-08-02")] == pytest.approx(2.5)
    pd.testing.assert_series_equal(returned, on_disk, check_names=False)


def test_duplicate_timestamps_within_one_incoming_series_keep_the_last(cache):
    """The add-in can repeat a timestamp inside one block; the later row wins."""
    stamp = pd.Timestamp("2026-08-02")
    duped = pd.Series([1.0, 9.0], index=[stamp, stamp])
    cache.write(TAG_10Y, "DAILY", duped)
    out = cache.read(TAG_10Y, "DAILY")
    assert len(out) == 1
    assert out.loc[stamp] == pytest.approx(9.0)


# ------------------------------------------------------------------ #
#                          missing_spans                             #
# ------------------------------------------------------------------ #


def test_cold_cache_needs_exactly_one_full_span(cache):
    spans = cache.missing_spans(TAG_10Y, "DAILY", start="2026-01-01", end="2026-06-30")
    assert spans == [(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-30"))]


def test_a_cached_middle_leaves_a_head_and_a_tail(cache):
    cached = pd.bdate_range("2026-07-10", "2026-07-20")
    cache.write(TAG_10Y, "DAILY", _daily(cached))

    spans = cache.missing_spans(TAG_10Y, "DAILY", start="2026-07-01", end="2026-07-31")

    assert len(spans) == 2
    head, tail = spans
    assert head == (pd.Timestamp("2026-07-01"), cached.min())
    assert tail == (cached.max(), pd.Timestamp("2026-07-31"))


def test_a_fully_covered_window_needs_nothing(cache):
    cached = pd.bdate_range("2026-07-01", "2026-07-31")
    cache.write(TAG_10Y, "DAILY", _daily(cached))
    assert cache.missing_spans(TAG_10Y, "DAILY", start="2026-07-06", end="2026-07-24") == []


def test_history_start_is_what_ends_a_full_history_request(cache):
    """``start=None`` stops asking for the head once the sidecar says it is complete.

    This is the entire point of recording ``CVMETADATA``'s history start: without
    it there is no way to distinguish "the cache holds everything the add-in has"
    from "the cache happens to start in 2018", so every ``start=None`` call would
    re-request the full span forever. All three states are pinned here.
    """
    index = pd.bdate_range("2018-01-02", "2018-06-29")
    series = _daily(index)

    # (a) history start recorded AND reached -> no head span.
    cache.write("TAG.REACHED", "DAILY", series, history_start="2018-01-02")
    assert cache.missing_spans("TAG.REACHED", "DAILY", start=None, end="2018-06-29") == []

    # (b) history start recorded but NOT reached -> the head is still missing.
    cache.write("TAG.SHORT", "DAILY", series, history_start="2010-01-04")
    assert cache.missing_spans("TAG.SHORT", "DAILY", start=None, end="2018-06-29") == [
        (None, index.min())
    ]

    # (c) no sidecar at all -> the head can never be known to be complete.
    cache.write("TAG.NOMETA", "DAILY", series)
    assert cache.missing_spans("TAG.NOMETA", "DAILY", start=None, end="2018-06-29") == [
        (None, index.min())
    ]


def test_history_start_can_be_recorded_without_any_rows(cache):
    """``set_history_start`` writes the sidecar alone; the key stays a full miss."""
    cache.set_history_start(TAG_10Y, "DAILY", "2018-01-02")
    cov = cache.coverage(TAG_10Y, "DAILY")
    assert cov is not None and cov.n_rows == 0
    assert cov.history_start == pd.Timestamp("2018-01-02")
    assert cache.missing_spans(TAG_10Y, "DAILY", start="2026-01-01", end="2026-06-30") == [
        (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-30"))
    ]


def test_open_ended_tail_is_refetched_unless_max_staleness_says_otherwise(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))

    stale = cache.missing_spans(TAG_10Y, "DAILY", start="2026-07-01", end=None)
    assert stale == [(daily_index.max(), None)]

    fresh = cache.missing_spans(
        TAG_10Y,
        "DAILY",
        start="2026-07-01",
        end=None,
        max_staleness=datetime.timedelta(hours=1),
    )
    assert fresh == []

    expired = cache.missing_spans(
        TAG_10Y,
        "DAILY",
        start="2026-07-01",
        end=None,
        max_staleness=datetime.timedelta(seconds=-1),
    )
    assert expired == [(daily_index.max(), None)]


# ------------------------------------------------------------------ #
#                     get(): one call, many tags                     #
# ------------------------------------------------------------------ #


def test_a_cold_44_tag_grid_costs_one_fetch(cache, daily_index):
    """Tags whose missing spans coincide must be fetched together.

    A cold 44-tenor par grid is the case this exists for: 44 separate
    ``CVTSHIST`` calls against a live add-in is minutes of wall clock and 44
    chances to trip the async timeout, and the whole grid shares one span.
    """
    fetcher = _RecordingFetcher(_grid_data(daily_index))

    out = cache.get(
        GRID_TAGS,
        "DAILY",
        start="2026-07-01",
        end="2026-08-04",
        fetcher=fetcher,
    )

    assert len(GRID_TAGS) == 44
    assert fetcher.n_calls == 1
    assert set(fetcher.calls[0].tags) == set(GRID_TAGS)  # one call, not one tag
    assert fetcher.calls[0].freq == "DAILY"
    assert fetcher.calls[0].price_point == "CLOSE"
    assert set(out) == set(GRID_TAGS)
    assert all(len(s) == len(daily_index) for s in out.values())


def test_a_second_read_of_the_same_window_fetches_nothing(cache, daily_index):
    fetcher = _RecordingFetcher(_grid_data(daily_index))
    kwargs = dict(start="2026-07-01", end="2026-08-04", fetcher=fetcher)

    cache.get(GRID_TAGS, "DAILY", **kwargs)
    assert fetcher.n_calls == 1

    again = cache.get(GRID_TAGS, "DAILY", **kwargs)
    assert fetcher.n_calls == 1, "a warm cache re-fetched"
    assert set(again) == set(GRID_TAGS)


def test_extending_the_window_fetches_only_the_tail_once_for_every_tag(cache):
    early = pd.bdate_range("2026-07-01", "2026-07-17")
    full = pd.bdate_range("2026-07-01", "2026-08-04")
    fetcher = _RecordingFetcher(_grid_data(full))

    cache.get(GRID_TAGS, "DAILY", start="2026-07-01", end=str(early.max().date()), fetcher=fetcher)
    cache.get(GRID_TAGS, "DAILY", start="2026-07-01", end="2026-08-04", fetcher=fetcher)

    assert fetcher.n_calls == 2
    tail = fetcher.calls[1]
    assert set(tail.tags) == set(GRID_TAGS), "the tail was not batched across tags"
    assert pd.Timestamp(tail.start) == early.max(), "the tail refetched history it already had"
    assert pd.Timestamp(tail.end) == pd.Timestamp("2026-08-04")


def test_tags_needing_different_spans_are_grouped_not_merged(cache, daily_index):
    """Two spans means two calls - grouping must not flatten to one wrong window."""
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))  # warm
    fetcher = _RecordingFetcher({TAG_10Y: _daily(daily_index), TAG_2Y: _daily(daily_index)})

    cache.get([TAG_10Y, TAG_2Y], "DAILY", start="2026-07-01", end="2026-08-04", fetcher=fetcher)

    assert fetcher.n_calls == 1
    assert fetcher.calls[0].tags == (TAG_2Y,), "the already-cached tag was refetched"


def test_get_without_a_fetcher_serves_only_what_is_on_disk(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))
    out = cache.get([TAG_10Y, TAG_2Y], "DAILY", start="2026-07-01", end="2026-08-04")
    assert set(out) == {TAG_10Y}  # the uncached tag is ABSENT, not NaN-filled


def test_get_clips_the_returned_series_to_the_requested_window(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))
    out = cache.get([TAG_10Y], "DAILY", start="2026-07-20", end="2026-07-24")
    assert out[TAG_10Y].index.min() >= pd.Timestamp("2026-07-20")
    assert out[TAG_10Y].index.max() <= pd.Timestamp("2026-07-24")


def test_max_staleness_suppresses_the_open_ended_refetch(cache, daily_index):
    fetcher = _RecordingFetcher({TAG_10Y: _daily(daily_index)})
    cache.get([TAG_10Y], "DAILY", start="2026-07-01", end=None, fetcher=fetcher)
    assert fetcher.n_calls == 1

    cache.get(
        [TAG_10Y],
        "DAILY",
        start="2026-07-01",
        end=None,
        fetcher=fetcher,
        max_staleness=datetime.timedelta(hours=1),
    )
    assert fetcher.n_calls == 1, "a fresh open-ended tail was refetched anyway"


def test_force_refresh_refetches_a_warm_key_and_the_revision_wins(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index, base=4.20))
    revised = _daily(daily_index, base=9.99)
    fetcher = _RecordingFetcher({TAG_10Y: revised})

    out = cache.get(
        [TAG_10Y], "DAILY", start="2026-07-01", end="2026-08-04", fetcher=fetcher, force_refresh=True
    )

    assert fetcher.n_calls == 1
    assert out[TAG_10Y].iloc[0] == pytest.approx(9.99)


# ------------------------------------------------------------------ #
#              intraday and daily are different data                 #
# ------------------------------------------------------------------ #


def _minute_series(day: str = "2026-08-04", periods: int = 30) -> pd.Series:
    idx = pd.date_range(f"{day} 09:00", periods=periods, freq="min")
    return pd.Series(4.30 + 0.0001 * np.arange(periods), index=idx)


def test_intraday_and_daily_land_in_different_files_and_never_mix(cache, daily_index):
    """One tag, two frequencies, two keys - and a read of one never sees the other."""
    minutes = _minute_series()
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))
    cache.write(TAG_10Y, "MI01", minutes)

    daily_path = cache.path(TAG_10Y, "DAILY")
    intraday_path = cache.path(TAG_10Y, "MI01")
    assert daily_path != intraday_path
    assert daily_path.parent.parent.name == "DAILY"
    assert intraday_path.parent.parent.name == "MI01"
    assert daily_path.is_file() and intraday_path.is_file()

    read_daily = cache.read(TAG_10Y, "DAILY")
    read_intraday = cache.read(TAG_10Y, "MI01")
    assert len(read_daily) == len(daily_index)
    assert len(read_intraday) == len(minutes)
    assert set(read_daily.index).isdisjoint(read_intraday.index)
    # Every daily stamp is midnight; no minute bar leaked in.
    assert not any(ts.hour or ts.minute for ts in read_daily.index)
    assert all(ts.hour == 9 for ts in read_intraday.index)

    assert sorted(k[0] for k in cache.keys()) == ["DAILY", "MI01"]


def test_a_frequency_blind_key_would_collapse_the_two_series(cache, daily_index):
    """MUTATION CHECK for the frequency dimension of the cache key.

    A cache keyed on the tag alone gives both frequencies the same path, and the
    merge then produces a series that is neither: for 2026-08-04 it holds one
    midnight close AND thirty 09:00-09:29 bars, so "the last value of the day"
    becomes an arbitrary minute. This runs both keying rules over the same pair
    and asserts the naive one collides.
    """
    minutes = _minute_series()
    daily = _daily(daily_index)

    keyed = {cache.path(TAG_10Y, "DAILY"), cache.path(TAG_10Y, "MI01")}
    naive = {cache.base_dir / f"{sanitise_tag(TAG_10Y)}.parquet"} | {
        cache.base_dir / f"{sanitise_tag(TAG_10Y)}.parquet"
    }
    assert len(keyed) == 2
    assert len(naive) == 1, "the naive key does not distinguish the two frequencies"

    collapsed = CitiVeloTagCache.merge(daily, minutes)
    assert len(collapsed) == len(daily) + len(minutes)
    # The damage, concretely: the last row of the series is a 09:29 minute bar,
    # not the 2026-08-04 close a daily consumer asked for.
    assert collapsed.index.max() == pd.Timestamp("2026-08-04 09:29")
    assert cache.read(TAG_10Y, "DAILY") is None  # nothing above touched the cache


def test_price_points_are_separate_keys_too(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index, base=4.20), price_point="CLOSE")
    cache.write(TAG_10Y, "DAILY", _daily(daily_index, base=4.30), price_point="OPEN")
    assert cache.read(TAG_10Y, "DAILY", "CLOSE").iloc[0] == pytest.approx(4.20)
    assert cache.read(TAG_10Y, "DAILY", "OPEN").iloc[0] == pytest.approx(4.30)
    assert sorted(k[1] for k in cache.keys()) == ["CLOSE", "OPEN"]


# ------------------------------------------------------------------ #
#                            sanitise_tag                            #
# ------------------------------------------------------------------ #


def test_sanitise_tag_is_stable_and_leaves_ordinary_tags_alone():
    assert sanitise_tag(TAG_10Y) == TAG_10Y
    assert sanitise_tag(TAG_10Y) == sanitise_tag(TAG_10Y)  # stable across calls
    assert sanitise_tag("  " + TAG_10Y + "  ") == TAG_10Y  # whitespace is stripped
    assert sanitise_tag("RATES/VOL:USD ATM") == "RATES_VOL_USD_ATM"
    assert sanitise_tag(TAG_10Y) != sanitise_tag(TAG_2Y)


def test_an_over_long_tag_falls_back_to_a_hashed_stem():
    """Past ``_MAX_STEM`` the stem is truncated and a digest appended.

    The cap exists because a deep cache root plus a seven-segment
    ``XCCY_OIS_SWAP`` tag approaches Windows' 260-character path limit. Note the
    fallback lands one character OVER ``_MAX_STEM`` (107 + ``__`` + 12 = 121);
    that off-by-one is reported rather than fixed, because changing the stem
    changes the on-disk key and would orphan anything already cached under it.
    """
    long_tag = "RATES.XCCY_OIS_SWAP." + ("SEGMENT_" * 20) + "10Y"
    sibling = "RATES.XCCY_OIS_SWAP." + ("SEGMENT_" * 20) + "20Y"
    assert len(long_tag) > _MAX_STEM

    stem = sanitise_tag(long_tag)
    assert stem == sanitise_tag(long_tag)  # deterministic
    assert stem != sanitise_tag(sibling)  # the digest keeps siblings apart
    assert stem.startswith(long_tag[:40])
    assert "__" in stem[-15:]
    assert len(stem) <= _MAX_STEM + 1


def test_the_hashed_stem_is_a_usable_cache_key(cache, daily_index):
    long_tag = "RATES.XCCY_OIS_SWAP." + ("SEGMENT_" * 20) + "10Y"
    cache.write(long_tag, "DAILY", _daily(daily_index))
    out = cache.read(long_tag, "DAILY")
    assert out is not None and len(out) == len(daily_index)
    assert cache.path(long_tag, "DAILY").is_file()


# ------------------------------------------------------------------ #
#                     corruption is loud, not silent                 #
# ------------------------------------------------------------------ #


def test_a_corrupt_parquet_warns_and_refetches(cache, daily_index, caplog):
    """A corrupt file must degrade to a REFETCH with a warning, not a silent miss.

    Silently returning ``None`` looks identical to a cold key, so a permanently
    unreadable file would be re-fetched and re-written on every call for the life
    of the cache with nothing in the log to say why.
    """
    cache.write(TAG_10Y, "DAILY", _daily(daily_index))
    path = cache.path(TAG_10Y, "DAILY")
    path.write_bytes(b"this is not a parquet file")

    fetcher = _RecordingFetcher({TAG_10Y: _daily(daily_index, base=7.77)})
    caplog.set_level(logging.WARNING, logger=CACHE_LOGGER)

    out = cache.get([TAG_10Y], "DAILY", start="2026-07-01", end="2026-08-04", fetcher=fetcher)

    warnings = [r for r in caplog.records if r.name == CACHE_LOGGER and r.levelno >= logging.WARNING]
    assert warnings, "a corrupt cache file was swallowed silently"
    assert "unreadable" in warnings[0].getMessage()
    assert str(path) in warnings[0].getMessage()

    assert fetcher.n_calls == 1
    assert out[TAG_10Y].iloc[0] == pytest.approx(7.77)
    # ... and the file is healthy again afterwards.
    caplog.clear()
    assert cache.read(TAG_10Y, "DAILY") is not None
    assert not [r for r in caplog.records if r.name == CACHE_LOGGER]


def test_a_corrupt_sidecar_is_treated_as_absent(cache, daily_index):
    cache.write(TAG_10Y, "DAILY", _daily(daily_index), history_start="2018-01-02")
    cache.meta_path(TAG_10Y, "DAILY").write_text("{not json", encoding="utf-8")
    cov = cache.coverage(TAG_10Y, "DAILY")
    assert cov is not None
    assert cov.history_start is None
    assert cov.n_rows == len(daily_index)  # the data itself is untouched


# ------------------------------------------------------------------ #
#                          CitiVeloQuotes                            #
# ------------------------------------------------------------------ #


def test_a_fully_cached_read_never_attaches_to_excel(cache, daily_index, monkeypatch):
    """``client=None`` plus ``offline=False`` and a warm cache must stay off COM.

    A notebook re-running a backtest over a warm cache should neither open a
    workbook nor require the user to be signed in, so the client is constructed
    lazily on the first request that actually needs live data. The exploding
    stand-in turns "constructed it anyway" into a failure.
    """
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _warm_cache(cache, daily_index, [TAG_10Y, TAG_2Y])

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    frame = quotes.frame([TAG_10Y, TAG_2Y], "DAILY", start="2026-07-06", end="2026-07-31")

    assert exploding.attempts == []
    assert list(frame.columns) == [TAG_10Y, TAG_2Y]
    assert frame.index.name == "Date"
    assert not frame.empty


def test_an_uncached_span_DOES_reach_for_the_client(cache, daily_index, monkeypatch):
    """Teeth for the test above: the same object connects when it must.

    Without this, "no COM was attempted" would pass equally well against a
    :class:`CitiVeloQuotes` that never connects under any circumstances.
    """
    exploding = _exploding_client_class()
    monkeypatch.setattr("MDP.CitiVelocityExcel.quotes.CitiVelocityExcelClient", exploding)
    _warm_cache(cache, daily_index, [TAG_10Y])

    quotes = CitiVeloQuotes(client=None, cache=cache, offline=False)
    with pytest.raises(AssertionError, match="tried to attach to Excel"):
        quotes.frame([TAG_10Y], "DAILY", start="2020-01-01", end="2020-06-30")
    assert len(exploding.attempts) == 1


def test_offline_refuses_to_connect_and_names_the_cache_root(cache):
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    with pytest.raises(CitiVelocityError) as excinfo:
        quotes.client()
    message = str(excinfo.value)
    assert "offline" in message.lower()
    assert str(cache.base_dir) in message, "the message must name the cache root"
    assert "offline=False" in message  # and say what to do about it


def test_offline_serves_the_cache_and_omits_what_is_missing(cache, daily_index):
    """Offline is a read of the cache, not an error: absent tags are simply absent."""
    _warm_cache(cache, daily_index, [TAG_10Y])
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    series = quotes.series([TAG_10Y, TAG_2Y], "DAILY", start="2026-07-01", end="2026-08-04")
    assert set(series) == {TAG_10Y}


def test_frame_orders_columns_by_request_not_by_name(cache, daily_index):
    _warm_cache(cache, daily_index, [TAG_10Y, TAG_2Y])
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    frame = quotes.frame([TAG_2Y, TAG_10Y], "DAILY", start="2026-07-01", end="2026-08-04")
    assert list(frame.columns) == [TAG_2Y, TAG_10Y]
    assert frame.index.is_monotonic_increasing


def test_frame_of_nothing_is_an_empty_frame_not_a_raise(cache):
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    frame = quotes.frame([TAG_10Y], "DAILY", start="2026-07-01", end="2026-08-04")
    assert isinstance(frame, pd.DataFrame)
    assert frame.empty
    assert frame.index.name == "Date"


def test_quotes_snapshot_resolves_one_instant_from_the_cache(cache, daily_index):
    _warm_cache(cache, daily_index, [TAG_10Y, TAG_2Y])
    quotes = CitiVeloQuotes(cache=cache, offline=True)
    snap = quotes.snapshot([TAG_10Y, TAG_2Y], "2026-07-15", "DAILY")
    assert set(snap) == {TAG_10Y, TAG_2Y}
    assert all(isinstance(v, float) for v in snap.values())
    expected = _daily(daily_index, base=4.0).loc[pd.Timestamp("2026-07-15")]
    assert snap[TAG_10Y] == pytest.approx(float(expected))


# ------------------------------------------------------------------ #
#                     CitiVelocityExcelSource                        #
# ------------------------------------------------------------------ #


@pytest.fixture()
def source(cache, daily_index) -> CitiVelocityExcelSource:
    """A source over a warm, offline cache - no Excel, no network, no DB."""
    _warm_cache(cache, daily_index, [TAG_10Y, TAG_2Y])
    return CitiVelocityExcelSource(cache=cache, offline=True)


def test_get_data_returns_a_wide_frame(source, daily_index):
    frame = source.get_data(
        {"tags": [TAG_10Y, TAG_2Y], "freq": "DAILY", "start": "2026-07-01", "end": "2026-08-04"}
    )
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == [TAG_10Y, TAG_2Y]
    assert len(frame) == len(daily_index)
    assert frame.index.name == "Date"
    assert frame.index.is_monotonic_increasing


def test_get_data_accepts_the_singular_tag_key(source):
    frame = source.get_data({"tag": TAG_10Y, "start": "2026-07-01", "end": "2026-08-04"})
    assert list(frame.columns) == [TAG_10Y]


def test_get_data_without_tags_is_a_clear_error(source):
    with pytest.raises(ValueError, match="'tags'"):
        source.get_data({"freq": "DAILY"})


def test_get_data_with_a_timestamp_returns_one_mapping(source):
    out = source.get_data({"tags": [TAG_10Y, TAG_2Y], "timestamp": "2026-07-15"})
    assert isinstance(out, dict)
    assert set(out) == {TAG_10Y, TAG_2Y}
    assert all(isinstance(v, float) for v in out.values())


def test_get_data_timestamp_is_backward_only_by_default(source, daily_index):
    """2026-07-04 is a business day but 2026-07-18 is the row we want for a Saturday."""
    saturday = source.get_data({"tags": [TAG_10Y], "timestamp": "2026-07-18 12:00"})
    friday = source.get_data({"tags": [TAG_10Y], "timestamp": "2026-07-17"})
    assert saturday[TAG_10Y] == pytest.approx(friday[TAG_10Y])


def test_get_data_live_returns_the_last_row(source, daily_index):
    out = source.get_data({"tags": [TAG_10Y], "timestamp": "live", "start": "2026-07-01", "end": "2026-08-04"})
    expected = _daily(daily_index, base=4.0).iloc[-1]
    assert out[TAG_10Y] == pytest.approx(float(expected))


def test_get_pricer_is_get_data(source):
    a = source.get_pricer({"tags": [TAG_10Y], "start": "2026-07-01", "end": "2026-08-04"})
    b = source.get_data({"tags": [TAG_10Y], "start": "2026-07-01", "end": "2026-08-04"})
    pd.testing.assert_frame_equal(a, b)


def test_bulk_get_data_keys_by_timestamp_and_omits_the_unreachable(source):
    """Points with no row at or before them are ABSENT, not present-and-empty.

    ``TB.BaseTimeseriesTB._bulk_fetch`` distinguishes the two, and an empty dict
    for a date the source simply does not cover would be read as "the market was
    blank that day".
    """
    too_early = pd.Timestamp("2026-06-15")
    stamps = [too_early, pd.Timestamp("2026-07-15"), pd.Timestamp("2026-08-03")]

    out = source.bulk_get_data({"tags": [TAG_10Y, TAG_2Y], "timestamps": stamps})

    assert set(out) == {pd.Timestamp("2026-07-15"), pd.Timestamp("2026-08-03")}
    assert too_early not in out
    for values in out.values():
        assert set(values) == {TAG_10Y, TAG_2Y}
        assert all(isinstance(v, float) for v in values.values())
    assert out[pd.Timestamp("2026-07-15")][TAG_10Y] != out[pd.Timestamp("2026-08-03")][TAG_10Y]


def test_bulk_get_data_requires_timestamps(source):
    with pytest.raises(ValueError, match="timestamps"):
        source.bulk_get_data({"tags": [TAG_10Y]})


def test_bulk_get_data_is_one_pass_over_the_window(cache, daily_index, monkeypatch):
    """N reference points cost ONE cache read, not N.

    The counter is on :meth:`CitiVeloQuotes.frame`, which is the call that would
    become a per-timestamp ``CVTSHIST`` against a live add-in.
    """
    _warm_cache(cache, daily_index, [TAG_10Y])
    src = CitiVelocityExcelSource(cache=cache, offline=True)

    calls: List[int] = []
    real_frame = src.quotes.frame

    def _counting_frame(*args, **kwargs):
        calls.append(1)
        return real_frame(*args, **kwargs)

    monkeypatch.setattr(src.quotes, "frame", _counting_frame)
    stamps = [pd.Timestamp(d) for d in ("2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27")]
    out = src.bulk_get_data({"tags": [TAG_10Y], "timestamps": stamps})

    assert len(out) == 4
    assert sum(calls) == 1


def test_bulk_get_data_handles_the_live_token(source, daily_index):
    out = source.bulk_get_data(
        {"tags": [TAG_10Y], "timestamps": [pd.Timestamp("2026-07-15"), "live"]}
    )
    assert "live" in out
    expected = _daily(daily_index, base=4.0).iloc[-1]
    assert out["live"][TAG_10Y] == pytest.approx(float(expected))


# ------------------------------------------------------------------ #
#                        snapshot_from_frame                         #
# ------------------------------------------------------------------ #


@pytest.fixture()
def hourly_frame() -> pd.DataFrame:
    idx = pd.date_range("2026-07-27 09:00", periods=6, freq="h")
    return pd.DataFrame(
        {TAG_10Y: 4.20 + 0.01 * np.arange(6), TAG_2Y: 4.05 + 0.02 * np.arange(6)}, index=idx
    )


def test_asof_never_looks_forward(hourly_frame):
    row = snapshot_from_frame(hourly_frame, "2026-07-27 11:40", method="asof")
    assert row.name == pd.Timestamp("2026-07-27 11:00")


def test_nearest_can_answer_with_a_row_from_the_future(hourly_frame):
    """MUTATION CHECK for the default resolution rule.

    ``nearest`` is direction-unbounded, and this is the concrete demonstration:
    asked for 11:40 it returns the 12:00 row - twenty minutes of data that did
    not exist yet. On the sibling ``citivelo`` source this was measured answering
    a 00:05 ET request with a snapshot 55 minutes in the future. Backtests read
    these snapshots, so ``asof`` is the default and ``nearest`` must be chosen
    knowingly. 11:40 rather than 11:30 because 11:30 is an exact tie and would
    prove nothing.
    """
    asof = snapshot_from_frame(hourly_frame, "2026-07-27 11:40", method="asof")
    nearest = snapshot_from_frame(hourly_frame, "2026-07-27 11:40", method="nearest")

    target = pd.Timestamp("2026-07-27 11:40")
    assert asof.name < target < nearest.name
    assert nearest.name == pd.Timestamp("2026-07-27 12:00")
    assert asof[TAG_10Y] != nearest[TAG_10Y]


def test_exact_returns_the_row_and_raises_when_it_is_absent(hourly_frame):
    exact = snapshot_from_frame(hourly_frame, "2026-07-27 11:00", method="exact")
    assert exact.name == pd.Timestamp("2026-07-27 11:00")
    with pytest.raises(ValueError, match="exactly"):
        snapshot_from_frame(hourly_frame, "2026-07-27 11:30", method="exact")


def test_asof_before_the_first_row_raises_with_the_earliest_stamp(hourly_frame):
    with pytest.raises(ValueError) as excinfo:
        snapshot_from_frame(hourly_frame, "2026-07-27 08:00", method="asof")
    assert "2026-07-27 09:00" in str(excinfo.value)


def test_no_timestamp_means_the_last_row(hourly_frame):
    assert snapshot_from_frame(hourly_frame, None).name == pd.Timestamp("2026-07-27 14:00")


def test_an_empty_frame_and_an_unknown_method_both_raise(hourly_frame):
    with pytest.raises(ValueError, match="empty"):
        snapshot_from_frame(pd.DataFrame(index=pd.DatetimeIndex([])), "2026-07-27 11:00")
    with pytest.raises(ValueError, match="Unknown method"):
        snapshot_from_frame(hourly_frame, "2026-07-27 11:00", method="interpolate")
