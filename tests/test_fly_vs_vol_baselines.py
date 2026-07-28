"""Tests for RVUtils.FlyVsVol.baselines — the FedWatch-style independence null.

Fixture: CME's published Sep-2022 worked example (and the GCUMF_Valuation_Framework
workbook that reproduces it): ZQU2 97.4475, ZQV2 96.94 (Oct, no FOMC), ZQX2 96.43;
Sept meeting splits the month 21/9 days, Nov meeting 2/28. Expected outputs:
Sept jump 0.7250 -> P(2 moves)=10%, P(3)=90%; Nov jump 0.546429 -> 81.43/18.57;
cumulative {4: 8.14%, 5: 75.14%, 6: 16.71%}.
"""
import datetime

import pytest

from RVUtils.FlyVsVol.baselines import (
    conditional_tree,
    independent_move_table,
    mantissa_probs,
    solve_meeting_month,
)

# ---- CME Sep-2022 fixture ---------------------------------------------------

OCT_AVG = 100 - 96.94  # 3.06, anchor month (no FOMC)


def test_fixture_sept_bootstrap():
    # Sept: avg known (2.5525), END known from Oct anchor -> solve start
    start, end, jump = solve_meeting_month(
        avg=100 - 97.4475, days_before=21, days_after=9, known_end=OCT_AVG
    )
    assert start == pytest.approx(2.3350, abs=1e-4)
    assert end == pytest.approx(3.06, abs=1e-9)
    assert jump == pytest.approx(0.7250, abs=1e-4)
    assert mantissa_probs(jump * 100) == pytest.approx({2: 0.10, 3: 0.90}, abs=1e-6)


def test_fixture_nov_bootstrap():
    # Nov: avg known (3.57), START known from Oct anchor -> solve end
    start, end, jump = solve_meeting_month(
        avg=100 - 96.43, days_before=2, days_after=28, known_start=OCT_AVG
    )
    assert end == pytest.approx(3.606429, abs=1e-5)
    assert jump == pytest.approx(0.546429, abs=1e-5)
    probs = mantissa_probs(jump * 100)
    assert probs == pytest.approx({2: 0.814286, 3: 0.185714}, abs=1e-5)


def test_fixture_conditional_tree():
    sept = mantissa_probs(72.50)
    nov = mantissa_probs(54.6429)
    cum = conditional_tree([sept, nov])
    assert cum[4] == pytest.approx(0.081429, abs=1e-4)
    assert cum[5] == pytest.approx(0.751429, abs=1e-4)
    assert cum[6] == pytest.approx(0.167143, abs=1e-4)
    assert sum(cum.values()) == pytest.approx(1.0, abs=1e-12)


# ---- mantissa edge cases ----------------------------------------------------

def test_mantissa_cuts_and_small_moves():
    assert mantissa_probs(-54.6429) == pytest.approx({-2: 0.814286, -3: 0.185714}, abs=1e-5)
    assert mantissa_probs(10.0) == pytest.approx({0: 0.6, 1: 0.4}, abs=1e-9)
    assert mantissa_probs(-10.0) == pytest.approx({0: 0.6, -1: 0.4}, abs=1e-9)
    assert mantissa_probs(50.0) == pytest.approx({2: 1.0}, abs=1e-9)
    assert mantissa_probs(0.0) == pytest.approx({0: 1.0}, abs=1e-9)


# ---- independence null for the fly windows ----------------------------------

W_U26 = (datetime.date(2026, 9, 16), datetime.date(2026, 12, 16))
W_Z26 = (datetime.date(2026, 12, 16), datetime.date(2027, 3, 17))
W_H27 = (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16))


def test_independent_move_table_zero_jumps():
    meetings = [(datetime.date(2026, 10, 28), {0: 1.0}),
                (datetime.date(2027, 4, 28), {0: 1.0})]
    res = independent_move_table(meetings, W_U26, W_Z26, W_H27)
    assert res["dn_table"] == pytest.approx({0: 1.0})
    assert res["prob_delta"] == pytest.approx(0.0)


def test_independent_move_table_dec_hike():
    # a certain Dec-9 hike lands almost fully between the U26 and Z26 windows
    meetings = [(datetime.date(2026, 12, 9), {1: 1.0})]
    res = independent_move_table(meetings, W_U26, W_Z26, W_H27)
    assert res["dn_table"] == pytest.approx({1: 1.0})  # N1=1 (d1~+23bp), N2=0
    assert res["prob_delta"] == pytest.approx(1.0)


def test_independent_move_table_bernoulli_sum():
    # 50/50 hike at Dec (window 1) and 50/50 hike at Apr-27 (window 2), independent
    meetings = [(datetime.date(2026, 12, 9), {0: 0.5, 1: 0.5}),
                (datetime.date(2027, 4, 28), {0: 0.5, 1: 0.5})]
    res = independent_move_table(meetings, W_U26, W_Z26, W_H27)
    t = res["dn_table"]
    # dec hike -> N1 += 1; apr hike -> N2 += 1 (d2 +13.2bp rounds to 1)... apr eff
    # 4/29 covers 48/91 of H27 -> d2 = +13.2bp -> rounds to 1 move.
    assert t.get(1, 0) == pytest.approx(0.25, abs=1e-9)   # dec only
    assert t.get(-1, 0) == pytest.approx(0.25, abs=1e-9)  # apr only
    assert t.get(0, 0) == pytest.approx(0.50, abs=1e-9)   # neither or both
    assert sum(t.values()) == pytest.approx(1.0, abs=1e-12)


def test_independent_move_table_sums_and_expectation():
    meetings = [
        (datetime.date(2026, 10, 28), {0: 0.6, 1: 0.4}),
        (datetime.date(2026, 12, 9), {0: 0.3, 1: 0.7}),
        (datetime.date(2027, 3, 17), {0: 0.8, 1: 0.2}),
    ]
    res = independent_move_table(meetings, W_U26, W_Z26, W_H27)
    assert sum(res["dn_table"].values()) == pytest.approx(1.0, abs=1e-12)
    e_dn = sum(j * p for j, p in res["dn_table"].items())
    assert e_dn == pytest.approx(res["e_n1"] - res["e_n2"], abs=1e-9)
    assert 0 <= res["p_dn_zero"] <= 1
