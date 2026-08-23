r"""Inclusive date-interval algebra for resume ledgers.

Its own file because the algebra is what the resume CORRECTNESS rests on: if
:func:`subtract` ever returns less than it should, a warm skips work it never
did and reports the universe warm over rows that do not exist. That is the one
failure mode a resume must not have, and it is cheap to test exhaustively here
and expensive to test through a warm.

The interior-hole cases are the point. A single first/last coverage interval
cannot express a gap in the middle, and a gap in the middle does not raise -
the as-of search serves the previous print and a whole session silently
inherits the day before.
"""

from __future__ import annotations

import datetime

import pytest

from utils import window_ledger as WL

D = datetime.date


def days(*pairs):
    return [(D(*a), D(*b)) for a, b in pairs]


# ------------------------------------------------------------------ #
#                             normalize                              #
# ------------------------------------------------------------------ #


def test_touching_intervals_merge_because_a_day_is_the_unit():
    """[1..3] and [4..6] have no gap between them: they are one window."""
    assert WL.normalize(days(((2026, 8, 1), (2026, 8, 3)),
                             ((2026, 8, 4), (2026, 8, 6)))) == days(
        ((2026, 8, 1), (2026, 8, 6)))


def test_a_one_day_gap_does_NOT_merge():
    """[1..3] and [5..6] leave the 4th unfetched, and it must stay visible."""
    got = WL.normalize(days(((2026, 8, 1), (2026, 8, 3)),
                            ((2026, 8, 5), (2026, 8, 6))))
    assert got == days(((2026, 8, 1), (2026, 8, 3)), ((2026, 8, 5), (2026, 8, 6)))


def test_overlapping_and_nested_intervals_collapse():
    assert WL.normalize(days(((2026, 8, 1), (2026, 8, 20)),
                             ((2026, 8, 5), (2026, 8, 9)),
                             ((2026, 8, 18), (2026, 8, 25)))) == days(
        ((2026, 8, 1), (2026, 8, 25)))


def test_input_order_does_not_matter():
    a = WL.normalize(days(((2026, 8, 5), (2026, 8, 9)), ((2026, 8, 1), (2026, 8, 3))))
    b = WL.normalize(days(((2026, 8, 1), (2026, 8, 3)), ((2026, 8, 5), (2026, 8, 9))))
    assert a == b


def test_iso_strings_are_accepted_because_that_is_how_a_manifest_stores_them():
    assert WL.normalize([["2026-08-01", "2026-08-03"]]) == days(
        ((2026, 8, 1), (2026, 8, 3)))


@pytest.mark.parametrize("junk", [
    [None], [[]], [["not-a-date", "2026-08-01"]], [[1, 2, 3]], [{"a": 1}],
])
def test_a_torn_or_hand_edited_entry_is_ignored_not_fatal(junk):
    """Failing OPEN here costs a re-fetch. Raising costs the whole warm."""
    assert WL.normalize(junk) == []


def test_a_reversed_interval_is_repaired_rather_than_dropped():
    assert WL.normalize([("2026-08-09", "2026-08-01")]) == days(
        ((2026, 8, 1), (2026, 8, 9)))


# ------------------------------------------------------------------ #
#                             subtract                               #
# ------------------------------------------------------------------ #


def test_nothing_banked_means_everything_is_owed():
    assert WL.subtract(D(2026, 8, 1), D(2026, 8, 5), []) == days(
        ((2026, 8, 1), (2026, 8, 5)))


def test_a_fully_banked_window_is_owed_nothing():
    assert WL.subtract(D(2026, 8, 1), D(2026, 8, 5),
                       days(((2026, 7, 1), (2026, 9, 1)))) == []


def test_THE_NIGHTLY_CASE_a_moved_end_owes_only_the_tail():
    """The whole reason this module exists.

    A window ending at the last settled session moves every night. Under the old
    ``start|end|values`` key that changed the key and re-entered all 877 bonds;
    here it costs one day.
    """
    assert WL.subtract(D(2026, 7, 9), D(2026, 8, 8),
                       days(((2026, 7, 8), (2026, 8, 7)))) == days(
        ((2026, 8, 8), (2026, 8, 8)))


def test_a_deeper_history_owes_only_the_front():
    assert WL.subtract(D(2021, 8, 8), D(2026, 8, 8),
                       days(((2026, 8, 6), (2026, 8, 8)))) == days(
        ((2021, 8, 8), (2026, 8, 5)))


def test_AN_INTERIOR_HOLE_IS_OWED():
    """The case a first/last coverage interval cannot see.

    Banked [1..3] and [7..9]; asked [1..9]. Days 4-6 were never fetched, and a
    ledger that reported this window covered would leave a hole that does not
    raise.
    """
    assert WL.subtract(D(2026, 8, 1), D(2026, 8, 9),
                       days(((2026, 8, 1), (2026, 8, 3)),
                            ((2026, 8, 7), (2026, 8, 9)))) == days(
        ((2026, 8, 4), (2026, 8, 6)))


def test_several_interior_holes_are_all_owed():
    assert WL.subtract(D(2026, 8, 1), D(2026, 8, 20),
                       days(((2026, 8, 3), (2026, 8, 5)),
                            ((2026, 8, 9), (2026, 8, 11)),
                            ((2026, 8, 17), (2026, 8, 18)))) == days(
        ((2026, 8, 1), (2026, 8, 2)),
        ((2026, 8, 6), (2026, 8, 8)),
        ((2026, 8, 12), (2026, 8, 16)),
        ((2026, 8, 19), (2026, 8, 20)),
    )


def test_banked_windows_entirely_outside_the_request_change_nothing():
    assert WL.subtract(D(2026, 8, 10), D(2026, 8, 12),
                       days(((2020, 1, 1), (2020, 2, 1)),
                            ((2030, 1, 1), (2030, 2, 1)))) == days(
        ((2026, 8, 10), (2026, 8, 12)))


def test_a_single_day_request():
    assert WL.subtract(D(2026, 8, 8), D(2026, 8, 8), []) == days(
        ((2026, 8, 8), (2026, 8, 8)))
    assert WL.subtract(D(2026, 8, 8), D(2026, 8, 8),
                       days(((2026, 8, 8), (2026, 8, 8)))) == []


def test_an_inverted_request_owes_nothing():
    assert WL.subtract(D(2026, 8, 9), D(2026, 8, 1), []) == []


def test_subtract_never_returns_a_day_outside_the_request():
    """The property that matters most: a residual must never widen the ask."""
    lo, hi = D(2026, 8, 5), D(2026, 8, 15)
    banked = days(((2026, 8, 1), (2026, 8, 7)), ((2026, 8, 10), (2026, 8, 20)))
    for g_lo, g_hi in WL.subtract(lo, hi, banked):
        assert lo <= g_lo <= g_hi <= hi


# ------------------------------------------------------------------ #
#                        add / covers / span                         #
# ------------------------------------------------------------------ #


def test_adding_the_owed_window_makes_the_request_covered():
    """The round trip a warm performs: owe it, fetch it, bank it, owe nothing."""
    banked = days(((2026, 7, 8), (2026, 8, 7)))
    lo, hi = D(2026, 7, 9), D(2026, 8, 8)
    for g_lo, g_hi in WL.subtract(lo, hi, banked):
        banked = WL.add(banked, g_lo, g_hi)
    assert WL.covers(lo, hi, banked)
    assert banked == days(((2026, 7, 8), (2026, 8, 8))), "and it merged into one"


def test_span_encloses_separated_gaps_because_a_fetch_takes_one_window():
    """Over-fetching the covered middle is fine; under-fetching is not."""
    assert WL.span(days(((2026, 8, 1), (2026, 8, 2)),
                        ((2026, 8, 19), (2026, 8, 20)))) == (D(2026, 8, 1), D(2026, 8, 20))


def test_span_of_nothing_is_None():
    assert WL.span([]) is None


def test_to_json_is_stable_and_sorted():
    once = WL.to_json(days(((2026, 8, 5), (2026, 8, 9)), ((2026, 8, 1), (2026, 8, 3))))
    assert once == [["2026-08-01", "2026-08-03"], ["2026-08-05", "2026-08-09"]]
    assert WL.to_json(once) == once, "a re-read must not change the file"


def test_total_days_counts_inclusively():
    assert WL.total_days(days(((2026, 8, 1), (2026, 8, 1)))) == 1
    assert WL.total_days(days(((2026, 8, 1), (2026, 8, 3)),
                              ((2026, 8, 5), (2026, 8, 6)))) == 5
