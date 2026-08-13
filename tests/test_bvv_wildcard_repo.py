"""Wildcard-option and repo-store tests.

The wildcard cases are pinned to values J.P. Morgan published, so the model is checked against a
framework it does not share. The repo cases pin the *degeneracy* of Citi's tenor axis, because the
whole point of that dataset was a term repo curve and it does not contain one.
"""

from __future__ import annotations

import math
import pathlib

import pytest

from RVUtils.BasisVsVol.wildcard import tail_multiplier, wildcard_value


# --------------------------------------------------------------------------- wildcard mechanics
def test_tail_multiplier_is_the_delivery_tail():
    """Per contract the short holds 1/CF face and delivers 1; the excess is the option."""
    assert tail_multiplier(0.5) == pytest.approx(1.0)
    assert tail_multiplier(0.8) == pytest.approx(0.25)
    assert tail_multiplier(1.0) == pytest.approx(0.0)


def test_no_tail_means_no_wildcard():
    """CF = 1 leaves nothing to sell after delivery, so there is no option at any vol."""
    r = wildcard_value(1.0, 0.13, 0.002, 15, sigma_yield_bp=2.0)
    assert math.isnan(r.value_ticks) or r.value_ticks == pytest.approx(0.0, abs=1e-9)


def test_value_rises_with_vol_and_with_the_tail():
    lo = wildcard_value(0.75, 0.13, 0.002, 15, sigma_yield_bp=0.5).value_ticks
    hi = wildcard_value(0.75, 0.13, 0.002, 15, sigma_yield_bp=2.0).value_ticks
    assert hi > lo > 0
    small_tail = wildcard_value(0.95, 0.13, 0.002, 15, sigma_yield_bp=1.0).value_ticks
    big_tail = wildcard_value(0.60, 0.13, 0.002, 15, sigma_yield_bp=1.0).value_ticks
    assert big_tail > small_tail > 0


def test_positive_carry_suppresses_the_option():
    """Waiting earns carry, which raises the exercise threshold. This is the 2026 regime."""
    neg = wildcard_value(0.6141, 0.21, -0.002, 15).value_ticks
    zero = wildcard_value(0.6141, 0.21, 0.0, 15).value_ticks
    pos = wildcard_value(0.6141, 0.21, 0.010, 15).value_ticks
    assert neg > zero > pos > 0


def test_more_delivery_days_is_worth_more():
    short = wildcard_value(0.7, 0.13, 0.002, 5).value_ticks
    long = wildcard_value(0.7, 0.13, 0.002, 20).value_ticks
    assert long > short


def test_fomc_day_adds_value_wherever_it_lands():
    base = wildcard_value(0.7, 0.13, 0.002, 15).value_ticks
    early = wildcard_value(0.7, 0.13, 0.002, 15, fomc_days=(2,)).value_ticks
    late = wildcard_value(0.7, 0.13, 0.002, 15, fomc_days=(14,)).value_ticks
    assert early > base and late > base


def test_whether_a_late_fomc_beats_an_early_one_depends_on_carry():
    """J.P. Morgan: "FOMC meetings timed towards the end of the delivery month can likewise boost
    its value substantially". That is true, but only in the positive-carry regime they were
    describing -- and the condition is worth stating because it is the 2026 regime too.

    Carry sets the exercise threshold. With little or no carry the threshold is low (~1.5bp), the
    option is very likely exercised in the first few days, and a meeting late in the window is
    rarely reached -- so an early meeting is worth more. With strong positive carry the threshold
    rises (~5.8bp), the option survives, and the late meeting dominates.
    """
    def pair(g):
        e = wildcard_value(0.7, 0.13, g, 15, fomc_days=(2,)).value_ticks
        l = wildcard_value(0.7, 0.13, g, 15, fomc_days=(14,)).value_ticks
        return e, l

    e0, l0 = pair(0.0)     # no carry: exercised early, late meeting seldom reached
    e2, l2 = pair(0.020)   # strong positive carry: option survives to the late meeting
    assert l0 < e0
    assert l2 > e2
    # and the threshold is the mechanism
    thr_lo = wildcard_value(0.7, 0.13, 0.0, 15).exercise_thresholds_bp[0]
    thr_hi = wildcard_value(0.7, 0.13, 0.020, 15).exercise_thresholds_bp[0]
    assert thr_hi > 2 * thr_lo


# --------------------------------------------------------------------------- published anchors
def test_reproduces_jpm_fvm8_wildcard():
    """J.P. Morgan, *Good things come to those who wait* (18 May 2018): FVM8 ~0.5-1.0 ticks
    at 1bp/2hr post-close vol with the FOMC day doubled."""
    r = wildcard_value(0.80, 0.045, 0.0, 21, sigma_yield_bp=1.0, fomc_days=(10,))
    assert 0.4 <= r.value_ticks <= 1.1, r.value_ticks


def test_reproduces_jpm_tum8_only_with_the_negative_basis_they_describe():
    """TUM8 is ~0.75 ticks in the same note -- but only because its gross basis was negative.

    At zero carry the same contract prices at ~0.1 ticks. The paper's whole subject is that TU and
    FV had negative gross bases that spring, and the negative carry is what drags the exercise
    threshold down and makes the option valuable. Getting their number without their carry would
    mean the model was right for the wrong reason.
    """
    flat = wildcard_value(0.91, 0.019, 0.0, 21, sigma_yield_bp=1.0, fomc_days=(10,)).value_ticks
    negative = wildcard_value(0.91, 0.019, -0.001, 21, sigma_yield_bp=1.0, fomc_days=(10,)).value_ticks
    assert flat < 0.25
    assert 0.5 <= negative <= 1.1, negative


def test_conversion_factor_ordering_matches_jpm_exhibit_6():
    """Low CF stays optimal to deliver late even at a substantially negative basis; high CF does not."""
    vals = [wildcard_value(cf, 0.13, 0.002, 15).value_ticks for cf in (0.60, 0.70, 0.80, 0.90, 0.95)]
    assert vals == sorted(vals, reverse=True)
    assert vals[0] > 10 * vals[-1]


# --------------------------------------------------------------------------- repo store
STORE = (pathlib.Path(__file__).resolve().parents[1]
         / "notebooks" / "backtests" / "basis_vs_vol" / "_data" / "usd_repo_history.parquet")
repo_only = pytest.mark.skipif(not STORE.exists(), reason="repo store not seeded")


@repo_only
def test_citi_repo_tenor_axis_is_degenerate():
    """The measured fact this module is built around: there is no term repo curve in here.

    If this ever fails, Citi has started serving a real term structure and every consumer that
    treats the overnight rate as "the term repo to delivery" must be revisited.
    """
    from MDP.CitiVelocityExcel.repo import store as R

    df = R.load(STORE)
    diag = R.assert_tenor_axis_is_degenerate(df)
    assert set(diag) == set(R.REPO_COLLATERAL)
    for coll, d in diag.items():
        assert d["max_tenor_spread_bp"] == pytest.approx(0.0, abs=1e-9), (coll, d)
        assert d["pct_days_dispersed"] == 0.0, (coll, d)


@repo_only
def test_gc_rate_ties_out_to_the_vendor_package():
    """Citi GC on 2026-08-12 against the 3.69% term repo J.P. Morgan used for Sep26 delivery."""
    from MDP.CitiVelocityExcel.repo import store as R

    df = R.load(STORE)
    assert R.gc_rate(df, "2026-08-12") == pytest.approx(3.69, abs=0.01)


@repo_only
def test_term_sofr_is_a_real_term_structure():
    """Unlike the repo tags, the SOFR tags do carry a genuine term axis."""
    from MDP.CitiVelocityExcel.repo import store as R

    df = R.load(STORE)
    vals = [R.term_sofr(df, "2026-08-12", t) for t in ("1M", "3M", "6M", "1Y")]
    assert all(math.isfinite(v) for v in vals)
    assert vals == sorted(vals), vals            # upward sloping on this date
    assert vals[-1] - vals[0] > 0.2              # and materially so, unlike the repo tags


@repo_only
def test_specialness_is_negative_or_zero_and_otr_only():
    from MDP.CitiVelocityExcel.repo import store as R

    df = R.load(STORE)
    g = R.repo_tag("USTREASGC", "ON")
    for coll in ("USD5YOTR", "USD10YOTR", "USD30YOTR"):
        s = (df[R.repo_tag(coll, "ON")] - df[g]).dropna() * 100.0
        assert len(s) > 500
        assert s.median() <= 0.0
        assert s.min() < -5.0          # specialness episodes are real and large
        assert s.quantile(0.95) <= 1.0  # and essentially one-sided
