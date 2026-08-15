"""The swaption warm chose smile richness over curve coverage, and lost COVID.

`citivelo_swaption_vol_warm.build` tried the full 13-offset grid first and took the first build that
succeeded -- whatever survived. That ranks a day by how much smile it has when what matters is which
part of the curve you can price at all.

Measured on the stored cube before the fix: **60 of 2,702 days degraded**, 59 of them contiguous
across 2020-01-24 to 2020-04-21. Two phases, because the rectangle search maximises area over a
sparse mask and the orientation flips:

    2020-01-24 .. 2020-03-24   expiries amputated -- 40 days with NO expiry shorter than 4Y
    2020-03-25 .. 2020-04-21   tenors amputated   -- 19 days down to 2-4 tenors
    2020-03-09                 the worst: 1 expiry x 5 tenors, minimum expiry 15Y
    2026-08-12                 a 1 x 2 rectangle kept over the full 17 x 9

The data was never missing. All 2,702 days, including all 60, hold a complete 17 x 9 ATM surface
upstream in the tag cache -- so the repair was an offline rebuild, no Excel and no Citi. After it:
**0 of 2,702 degraded**, and 1M x 10Y ATM vol exists right through the crisis (60.9bp on
2020-01-23, 168.2bp on 2020-03-09, 152.7bp on 2020-03-20, 83.4bp by 2020-04-22).

The cause is structural, not a run of bad days: the rectangle search requires EVERY offset present,
and a 1Y option has no -200bp strike when rates are ~1.5%, so one structurally unquotable wing
amputates a whole expiry row.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_WARM = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "citivelo_swaption_vol_warm.py"


def _warm_module():
    spec = importlib.util.spec_from_file_location("citivelo_swaption_vol_warm", _WARM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coverage_beats_smile():
    """2020-03-09 and 2026-08-12, in ATM cells: 1x5 and 1x2 against the full 17x9."""
    warm = _warm_module()
    assert warm.pick_widest_cube([(1 * 5, 12, "smile"), (17 * 9, 0, "atm")]) == "atm"
    assert warm.pick_widest_cube([(1 * 2, 12, "smile"), (17 * 9, 0, "atm")]) == "atm"


def test_a_full_smile_still_wins_when_it_costs_no_coverage():
    """The normal day: both candidates span the full 17 x 9, so the smile is free."""
    warm = _warm_module()
    assert warm.pick_widest_cube([(17 * 9, 12, "smile"), (17 * 9, 0, "atm")]) == "smile"


def test_smile_is_the_tie_break_not_the_ranking():
    """Equal coverage -> take the richer cube. Coverage is the primary key, not the only one."""
    warm = _warm_module()
    assert warm.pick_widest_cube([(17 * 9, 12, "smile"), (17 * 9, 0, "atm")]) == "smile"
    assert warm.pick_widest_cube([(17 * 9, 0, "atm"), (17 * 9, 12, "smile")]) == "smile"


def test_no_candidate_is_a_gap_not_a_crash():
    """A day with too few served nodes stays absent; the store keeps saying which days exist."""
    warm = _warm_module()
    assert warm.pick_widest_cube([]) is None


def test_the_choice_does_not_depend_on_the_order_candidates_were_built():
    """The old bug WAS the ordering. Ranking must be order-independent."""
    warm = _warm_module()
    forward = [(1 * 5, 12, "smile"), (17 * 9, 0, "atm")]
    assert warm.pick_widest_cube(forward) == warm.pick_widest_cube(list(reversed(forward)))


@pytest.mark.parametrize(
    "atm_cells_smile,atm_cells_only,expected",
    [
        (8 * 9, 17 * 9, "atm"),    # 2020-01-24 as stored: 8 expiries x 9 tenors, smile intact
        (7 * 9, 17 * 9, "atm"),    # the 819-row days
        (1 * 5, 17 * 9, "atm"),    # 2020-03-09, the worst
        (17 * 2, 17 * 9, "atm"),   # 2020-04-21, tenors amputated instead of expiries
        (17 * 9, 17 * 9, "smile"), # a healthy day: the smile costs no coverage
    ],
)
def test_the_rank_is_atm_axis_coverage_not_total_node_count(atm_cells_smile, atm_cells_only, expected):
    """The rank input is ``cube.atm.size`` -- expiries x tenors -- NOT the cube's total node count.

    The distinction decides every degraded day, so it is asserted rather than described. A stored
    2020-01-24 cube is 8 x 9 x 13 = 936 numbers against the ATM surface's 153, so ranking by TOTAL
    nodes would have kept the truncated expiry axis and changed nothing. Ranking by the ATM
    rectangle compares 72 cells against 153 and takes the full curve, which is what the offline
    rebuild actually produced.
    """
    warm = _warm_module()
    candidates = [(atm_cells_smile, 12, "smile"), (atm_cells_only, 0, "atm")]
    assert warm.pick_widest_cube(candidates) == expected
