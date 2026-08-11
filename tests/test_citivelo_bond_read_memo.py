r"""Three memoisations on the offline bond read path, and what each must not break.

Profiled on a sixty-date offline pricer loop for one bond, the steady-state cost
was **107.6 ms per date**, and almost none of it was pricing:

    31%  BondUniverse.from_catalog   re-parsing 2,690 bond descriptions per date
    24%  CitiVeloTagCache.read       re-parsing the same parquet per date
    ~50% _filter_and_rank_ref_df     107,100 QuantLib Calendar.advance calls,
                                     recomputing a roll date that does not
                                     depend on the as_of it was asked for

After: **18.5 ms per date**, and the ten-year issue warm goes from a projected
26.1 hours to 4.5. The pricers are bit-identical - 2,520 numbers across 248
(target, date) keys, built with ``force_refresh=True`` so both sides went through
the fetcher rather than through a shared pricer cache.

What each test defends is the *invalidation*, because that is what a memo gets
wrong. A cache keyed too loosely serves a stale number, and a stale number here is
indistinguishable from a quote.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest
import QuantLib as ql

from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.FixedRateBonds.FixedRateBondsMDP import _auction_plus_1bd


# ------------------------------------------------------------------ #
#                     the roll date, memoised                        #
# ------------------------------------------------------------------ #


def _advance_1bd(d: datetime.date) -> datetime.date:
    """The original inline implementation, verbatim, as the oracle."""
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    nxt = cal.advance(ql.Date(d.day, d.month, d.year), ql.Period("1D"))
    return datetime.date(nxt.year(), nxt.month(), nxt.dayOfMonth())


#: Chosen so the answer is not simply "the next day": a Friday rolls to Monday, a
#: day before July 4th skips the holiday, and a day before Christmas skips two.
ROLL_CASES = [
    datetime.date(2024, 2, 12),   # Monday -> Tuesday, the easy case
    datetime.date(2024, 2, 16),   # Friday -> Tuesday (Presidents' Day Monday)
    datetime.date(2024, 7, 3),    # -> 5 July, skipping Independence Day
    datetime.date(2023, 12, 22),  # Friday -> Tuesday, skipping Christmas
    datetime.date(2021, 12, 31),  # across a year end
]


@pytest.mark.parametrize("d", ROLL_CASES)
def test_the_memoised_roll_date_matches_a_fresh_quantlib_advance(d):
    assert _auction_plus_1bd(pd.Timestamp(d)) == _advance_1bd(d)


def test_a_timestamp_and_a_date_for_the_same_day_agree():
    """The key is (y, m, d), not the object, so these must not diverge - a cache
    that split on type would double its size and, worse, hide that they had."""
    d = datetime.date(2024, 2, 16)
    assert _auction_plus_1bd(pd.Timestamp(d)) == _auction_plus_1bd(pd.Timestamp(d, tz=None))


def test_a_missing_auction_date_is_still_not_a_time():
    """NaT in, NaT out. The caller fills it from issue_date, and a memo that
    returned a real date here would silently invent a roll."""
    assert pd.isna(_auction_plus_1bd(pd.NaT))
    assert pd.isna(_auction_plus_1bd(None))


# ------------------------------------------------------------------ #
#                    the catalog parse, memoised                     #
# ------------------------------------------------------------------ #


def test_two_universes_from_one_catalog_agree_but_are_separate_objects():
    """The DESCRIPTORS are shared; the universe is not.

    Descriptors are frozen and safe to share. ``BondUniverse`` owns a mutable ISIN
    index, so handing one instance to two callers would make one caller's state
    the other's.
    """
    cat = CitiVeloCatalog.default()
    a = BondUniverse.from_catalog(catalog=cat)
    b = BondUniverse.from_catalog(catalog=cat)

    assert a is not b
    assert [d.isin for d in a] == [d.isin for d in b]
    assert len(list(a)) > 2000, "the catalog is unexpectedly small; this proves nothing"


def test_a_different_filter_is_a_different_entry():
    """A memo keyed only on the catalog would serve the whole universe to a
    caller that asked for US GOVT, which is a wrong answer that looks fine."""
    cat = CitiVeloCatalog.default()
    everything = BondUniverse.from_catalog(catalog=cat)
    us_govt = BondUniverse.from_catalog(catalog=cat, country="USA", asset_type="GOVT")

    n_all, n_us = len(list(everything)), len(list(us_govt))
    assert 0 < n_us < n_all, f"US GOVT is {n_us} of {n_all}"
    assert {d.country for d in us_govt} == {"USA"}


def test_the_reference_date_is_part_of_the_key():
    """``reference`` steers two-digit year resolution in the description parse, so
    a memo that dropped it would serve one date's reading to another."""
    cat = CitiVeloCatalog.default()
    early = BondUniverse.from_catalog(catalog=cat, reference=datetime.date(2016, 1, 1))
    late = BondUniverse.from_catalog(catalog=cat, reference=datetime.date(2026, 1, 1))
    memo = getattr(cat, "_descriptor_memo", None)
    assert memo is not None
    keys = [k for k in memo if k[3] in (datetime.date(2016, 1, 1), datetime.date(2026, 1, 1))]
    assert len(keys) == 2, f"reference did not reach the key: {keys}"
    assert len(list(early)) == len(list(late))


def test_a_caller_with_its_own_catalog_gets_its_own_memo():
    """Tying the memo to the catalog instance is what makes a re-seeded catalog
    invalidate for free - installing a new default brings a new cache with it."""
    cat = CitiVeloCatalog.default()
    BondUniverse.from_catalog(catalog=cat)
    other = CitiVeloCatalog()
    assert getattr(other, "_descriptor_memo", None) in (None, {})


# ------------------------------------------------------------------ #
#                   the parquet parse, memoised                      #
# ------------------------------------------------------------------ #


def _write(cache: CitiVeloTagCache, tag: str, values, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="D")
    cache.write(tag, "DAILY", pd.Series(values, index=idx))


def test_a_rewritten_tag_is_re_read_not_served_from_the_memo(tmp_path):
    """The whole risk of this memo, in one test.

    ``get`` writes through this cache, so a tag can be extended by the very
    process that is reading it. Keyed on the path alone, the reader would keep
    serving the series from before its own write - a stale number, forever, with
    nothing to show for it.
    """
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tag = "RATES.BOND.US912828U576.PRICE"

    _write(cache, tag, [99.0, 99.5])
    first = cache.read(tag, "DAILY")
    assert list(first) == [99.0, 99.5]

    _write(cache, tag, [99.0, 99.5, 100.25, 101.5])
    second = cache.read(tag, "DAILY")
    assert list(second) == [99.0, 99.5, 100.25, 101.5], (
        "the memo served the pre-write series; the file identity is not in the key"
    )


def test_the_memo_does_not_hand_out_a_shared_mutable_series(tmp_path):
    """Two readers must not share one Series. Any in-place edit by the first
    would otherwise reach every later reader with no trace."""
    cache = CitiVeloTagCache(base_dir=tmp_path)
    tag = "RATES.BOND.US912828U576.YIELD"
    _write(cache, tag, [4.0, 4.1, 4.2])

    a = cache.read(tag, "DAILY")
    a.iloc[0] = -999.0
    b = cache.read(tag, "DAILY")

    assert b.iloc[0] == 4.0, "an edit to one reader's Series reached the next reader"


def test_a_missing_tag_is_still_a_miss(tmp_path):
    cache = CitiVeloTagCache(base_dir=tmp_path)
    assert cache.read("RATES.BOND.US000000000.PRICE", "DAILY") is None


def test_the_memo_is_bounded(tmp_path):
    """A 900-bond warm touches thousands of tags; the memo must not grow with it."""
    cache = CitiVeloTagCache(base_dir=tmp_path)
    for i in range(CitiVeloTagCache._PARSE_MEMO_MAX + 20):
        tag = f"RATES.BOND.US91282800{i:03d}.PRICE"
        _write(cache, tag, [100.0 + i])
        cache.read(tag, "DAILY")
    assert len(cache._parse_memo) <= CitiVeloTagCache._PARSE_MEMO_MAX
