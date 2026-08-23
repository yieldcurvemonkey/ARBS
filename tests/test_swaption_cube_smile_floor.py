"""Coverage beats smile — but only when coverage is actually at stake.

`pick_widest_cube` chose the candidate with the largest ATM rectangle, full
stop. That correction was right and is kept: ranking by smile richness had cost
the short end of the curve for 59 consecutive days across COVID, preferring a
1-expiry x 5-tenor cube (65 nodes, minimum expiry 15Y) over the full 17 x 9 ATM
surface.

What it lacked was proportion. Measured 2026-08-17..08-21: the full-offset grid
drops tenors 4Y and 12Y for incomplete quotes, giving 136 ATM cells against the
ATM-only build's 153. So `153 > 136` and ATM-only won every day — trading 17
extra ATM cells for 1,632 smile quotes (136 x 12 offsets), and leaving
`citivelo_swaption_eod_warm` with nothing to price, because its manifest is
mostly ATMF+/-25 payers, receivers, strangles, risk reversals, 1x2s and ladders.
All of those need the wings.

The floor separates the two cases by a wide margin: 89% keeps the smile, 42%
and 1% do not.
"""

import pytest

from scripts.citivelo_swaption_vol_warm import (
    SMILE_COVERAGE_FLOOR,
    pick_widest_cube,
)


def _cand(atm_cells, n_offsets, name):
    return (atm_cells, n_offsets, name)


def test_no_candidates_is_none():
    assert pick_widest_cube([]) is None


def test_a_single_candidate_wins_by_default():
    assert pick_widest_cube([_cand(153, 0, "atm")]) == "atm"


def test_the_measured_2026_08_case_keeps_the_smile():
    """136/153 = 89%, comfortably over the floor."""
    chosen = pick_widest_cube([_cand(153, 0, "atm"), _cand(136, 12, "smile")])
    assert chosen == "smile"


def test_the_covid_case_still_keeps_coverage():
    """65/153 = 42%. Losing the short end is what the original fix was for."""
    chosen = pick_widest_cube([_cand(153, 0, "atm"), _cand(65, 12, "smile")])
    assert chosen == "atm"


def test_the_2026_08_12_case_still_keeps_coverage():
    """2/153 = 1%."""
    chosen = pick_widest_cube([_cand(153, 0, "atm"), _cand(2, 12, "smile")])
    assert chosen == "atm"


def test_a_smile_that_is_also_the_widest_wins_outright():
    chosen = pick_widest_cube([_cand(120, 0, "atm"), _cand(153, 12, "smile")])
    assert chosen == "smile"


def test_the_floor_is_inclusive():
    atm = 100
    smile = int(atm * SMILE_COVERAGE_FLOOR)
    chosen = pick_widest_cube([_cand(atm, 0, "atm"), _cand(smile, 12, "smile")])
    assert chosen == "smile", f"{smile}/{atm} is exactly the floor and should qualify"


def test_just_under_the_floor_keeps_coverage():
    atm = 100
    smile = int(atm * SMILE_COVERAGE_FLOOR) - 1
    assert pick_widest_cube([_cand(atm, 0, "atm"), _cand(smile, 12, "smile")]) == "atm"


def test_an_empty_widest_surface_does_not_divide_by_zero():
    assert pick_widest_cube([_cand(0, 0, "atm"), _cand(0, 12, "smile")]) is not None


def test_the_floor_sits_between_the_measured_cases():
    """A guard on the constant itself: the three measured shares are 89/42/1%."""
    assert 0.42 < SMILE_COVERAGE_FLOOR <= 0.89
