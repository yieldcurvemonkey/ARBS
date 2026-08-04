"""Synthetic, no-network tests for the adjacent-expiry (vol-vs-vol) leg.

Planted throughout: the nesting relation the whole construction rests on, the
two mirroring conventions, the least-squares ratio and the degeneracy it refuses
to fit, what the hedge leaves behind, and the causal trailing ratio's refusal to
see the future.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeetingProb.atoms import (
    AtomEngine, ContractMeetings, ResolvedMeeting)
from RVUtils.OutcomeMap import (
    MIN_SHARED_MEETINGS, adjacent, align_exposure, empirical_ratio, fly_legs,
    mirror_package, package_contracts, package_hedge_ratios,
    residual_exposure, tree_ratio,
)


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------

def _expiries():
    return {
        "SFRU26": datetime.date(2026, 9, 11),
        "SFRZ26": datetime.date(2026, 12, 11),
        "SFRH27": datetime.date(2027, 3, 12),
        "SFRM27": datetime.date(2027, 6, 11),
        "SFRM25": datetime.date(2025, 6, 13),      # already expired
    }


def test_adjacent_walks_the_listed_expiry_order():
    d = datetime.date(2026, 8, 1)
    assert adjacent(_expiries(), d, "SFRZ26") == ("SFRU26", "SFRH27")
    assert adjacent(_expiries(), d, "SFRU26") == (None, "SFRZ26")
    assert adjacent(_expiries(), d, "SFRM27") == ("SFRH27", None)


def test_adjacent_ignores_contracts_that_have_expired():
    d = datetime.date(2026, 8, 1)
    prev, nxt = adjacent(_expiries(), d, "SFRU26")
    assert prev is None                       # SFRM25 is dead, not the neighbour
    assert nxt == "SFRZ26"


# ---------------------------------------------------------------------------
# mirroring
# ---------------------------------------------------------------------------

def test_mirror_at_absolute_strikes_reproduces_the_package():
    strikes = [95.00 + 0.0625 * i for i in range(40)]
    legs = mirror_package([96.00, 96.50], [1.0, -1.0], strikes)
    assert legs == fly_legs(96.00, weight=1.0) + fly_legs(96.50, weight=-1.0)
    assert package_contracts(legs) == pytest.approx(6.0)   # telescoped


def test_moneyness_convention_shifts_by_the_forward_difference():
    strikes = [95.00 + 0.0625 * i for i in range(40)]
    f1, f2 = 3.60, 3.85                       # far forward 25bp higher in rate
    legs = mirror_package([96.00], [1.0], strikes, shift=f1 - f2)
    centres = sorted({k for _, k, _ in legs})
    assert centres[1] == pytest.approx(96.25)  # ...so 25bp lower in price terms


def test_mirror_returns_none_when_a_cell_cannot_be_built():
    strikes = [96.00, 96.25]                  # no wings for a 0.25 fly at 96.00
    assert mirror_package([96.00], [1.0], strikes) is None


def test_mirror_keeps_the_package_a_set_of_valid_flies():
    """Every mirrored cell must contribute 1/-2/1 at its own centre."""
    strikes = [95.00 + 0.0625 * i for i in range(40)]
    legs = mirror_package([96.00, 96.25], [2.0, -0.5], strikes)
    by_k = {}
    for right, k, w in legs:
        by_k[k] = by_k.get(k, 0.0) + w
    assert by_k[95.75] == pytest.approx(2.0)
    assert by_k[96.00] == pytest.approx(-4.0 - 0.5)
    assert by_k[96.25] == pytest.approx(2.0 + 1.0)
    assert by_k[96.50] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# the nesting relation and the ratio
# ---------------------------------------------------------------------------

def _cm(effectives, expiry, window):
    return ContractMeetings(
        symbol="X", as_of=datetime.date(2026, 8, 1), window=window,
        expiry=expiry,
        resolved=tuple(
            ResolvedMeeting(effective=e, decision=e - datetime.timedelta(days=1),
                            weight=1.0, support=(0, 1), q_zq=0.5, jump_bp=12.5,
                            stale=False) for e in effectives),
        unresolved_var_bp2=0.0, any_stale=False)


def test_align_exposure_splits_shared_from_extra():
    e = [datetime.date(2026, 9, 17), datetime.date(2026, 11, 5),
         datetime.date(2026, 12, 17), datetime.date(2027, 1, 28)]
    cm1 = _cm(e[:2], datetime.date(2026, 12, 11),
              (datetime.date(2026, 12, 16), datetime.date(2027, 3, 17)))
    cm2 = _cm(e, datetime.date(2027, 3, 12),
              (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16)))
    v1, v2, shared, extra = align_exposure(cm1, [0.4, 0.6], cm2,
                                           [0.2, 0.3, 0.1, 0.05])
    assert shared == e[:2] and extra == e[2:]
    assert list(v1) == [0.4, 0.6]
    assert list(v2) == [0.2, 0.3]              # aligned BY DATE, not position


def test_align_is_by_date_not_position():
    """A far contract that dropped an early meeting must still line up."""
    a = datetime.date(2026, 9, 17)
    b = datetime.date(2026, 11, 5)
    cm1 = _cm([a, b], datetime.date(2026, 12, 11),
              (datetime.date(2026, 12, 16), datetime.date(2027, 3, 17)))
    cm2 = _cm([b], datetime.date(2027, 3, 12),
              (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16)))
    v1, v2, shared, extra = align_exposure(cm1, [0.4, 0.6], cm2, [0.9])
    assert shared == [b] and list(v1) == [0.6] and list(v2) == [0.9]


def test_tree_ratio_is_least_squares_over_shared_meetings():
    v1 = np.array([0.4, 0.6])
    v2 = np.array([0.2, 0.3])
    assert tree_ratio(v1, v2) == pytest.approx(2.0)     # v1 = 2 * v2 exactly
    assert residual_exposure(v1, v2, 2.0) == pytest.approx(0.0)


def test_tree_ratio_refuses_an_under_determined_fit():
    """One shared meeting solves exactly and says nothing — do not fit it."""
    assert MIN_SHARED_MEETINGS == 2
    assert np.isnan(tree_ratio(np.array([0.5]), np.array([0.08])))
    assert np.isnan(tree_ratio(np.array([0.4, 0.6]), np.array([0.0, 0.0])))


def test_residual_exposure_reports_what_the_hedge_leaves():
    v1 = np.array([1.0, 0.0])
    v2 = np.array([0.5, 0.5])
    lam = tree_ratio(v1, v2)
    assert lam == pytest.approx(1.0)                    # 0.5 / 0.5
    # hedged: (1 - 0.5, 0 - 0.5) -> |0.5| + |0.5| = 1.0 against a base of 1.0
    assert residual_exposure(v1, v2, lam) == pytest.approx(1.0)


def test_a_perfect_hedge_and_a_useless_one_are_distinguishable():
    v1 = np.array([0.4, 0.6])
    good = np.array([0.2, 0.3])
    bad = np.array([0.6, -0.4])
    assert residual_exposure(v1, good, tree_ratio(v1, good)) < 1e-9
    assert residual_exposure(v1, bad, tree_ratio(v1, bad)) > 0.9


# ---------------------------------------------------------------------------
# the ratio against a real two-expiry lattice
# ---------------------------------------------------------------------------

def test_nested_lattices_give_a_finite_well_posed_ratio():
    e = [datetime.date(2026, 9, 17), datetime.date(2026, 11, 5),
         datetime.date(2026, 12, 17)]
    cm1 = _cm(e[:2], datetime.date(2026, 12, 11),
              (datetime.date(2026, 12, 16), datetime.date(2027, 3, 17)))
    cm2 = _cm(e, datetime.date(2027, 3, 12),
              (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16)))
    fwd = 4.00
    r1, _ = AtomEngine(cm1).rates_probs(fwd)
    legs1 = fly_legs(round(100.0 - float(np.max(r1)), 6))
    legs2 = fly_legs(round(100.0 - float(np.max(r1)), 6))   # same absolute rate
    h1 = package_hedge_ratios(cm1, fwd, legs1, 0.0)
    h2 = package_hedge_ratios(cm2, fwd, legs2, 0.0)
    v1, v2, shared, extra = align_exposure(cm1, h1, cm2, h2)
    assert len(shared) == 2 and len(extra) == 1
    lam = tree_ratio(v1, v2)
    assert np.isfinite(lam)
    # the extra meeting is exposure the calendar hedge can never remove
    m2 = {r.effective: h2[i] for i, r in enumerate(cm2.resolved)}
    assert abs(m2[extra[0]]) > 0.0


# ---------------------------------------------------------------------------
# the causal empirical ratio
# ---------------------------------------------------------------------------

def test_empirical_ratio_recovers_a_planted_relationship():
    idx = pd.bdate_range("2026-01-05", periods=60)
    rng = np.random.default_rng(0)
    b = pd.Series(rng.normal(size=len(idx)).cumsum(), index=idx)
    a = 1.7 * b
    assert empirical_ratio(a, b) == pytest.approx(1.7, abs=1e-9)


def test_empirical_ratio_cannot_see_the_future():
    """Only the trailing window feeds the ratio; later data must not move it."""
    idx = pd.bdate_range("2026-01-05", periods=60)
    rng = np.random.default_rng(1)
    b = pd.Series(rng.normal(size=len(idx)).cumsum(), index=idx)
    a = 1.2 * b
    hist = slice(0, 45)
    base = empirical_ratio(a.iloc[hist], b.iloc[hist])
    a2 = a.copy()
    a2.iloc[45:] = a2.iloc[45:] * 10.0            # blow up the FUTURE only
    assert empirical_ratio(a2.iloc[hist], b.iloc[hist]) == pytest.approx(base)


def test_empirical_ratio_is_nan_without_enough_history():
    idx = pd.bdate_range("2026-01-05", periods=8)
    s = pd.Series(np.arange(8.0), index=idx)
    assert np.isnan(empirical_ratio(s, s))


def test_empirical_ratio_uses_only_the_trailing_window():
    """Built from DIFFS so an old regime cannot cancel itself out of the fit."""
    idx = pd.bdate_range("2026-01-05", periods=120)
    db = np.ones(119)
    da = np.concatenate([np.full(79, 5.0), np.full(40, 1.0)])
    b = pd.Series(np.concatenate([[0.0], db.cumsum()]), index=idx)
    a = pd.Series(np.concatenate([[0.0], da.cumsum()]), index=idx)
    assert empirical_ratio(a, b, window=40) == pytest.approx(1.0)
    # the whole history would average the dead regime back in
    assert empirical_ratio(a, b, window=10_000) == pytest.approx(
        float(da.sum() / 119.0))
