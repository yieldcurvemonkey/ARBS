"""Known-answer tests for the copula bounds on a sum of FOMC meeting outcomes.

Every expected number here is derived independently of the implementation -- by hand from
the definition of the coupling, or from a closed form the implementation does not use -- so
a bug in the module cannot also be a bug in its test.

The working marginals are the ZQ-implied hike probabilities measured on 2026-08-07:
Sep 0.420, Oct 0.250, Dec 0.431.
"""
import numpy as np
import pytest

from RVUtils.SR3ZQDistributionScreener._copula import (
    comonotone_sum_distribution,
    coupling_bounds,
    extremal_sum_distribution,
    independent_sum_distribution,
    lambda_from_statistic,
    mixture_sum_distribution,
    sum_variance,
    variance_bounds_violation,
    wing_mass,
)

P0807 = (0.420, 0.250, 0.431)
E_K = 1.101  # = 0.420 + 0.250 + 0.431, and identical under every coupling


# --------------------------------------------------------------------------------------
# comonotone: sort the marginals descending, take successive differences
# --------------------------------------------------------------------------------------

def test_comonotone_matches_hand_computed_atoms():
    # Survival levels are the sorted marginals: P(K>=1)=.431, P(K>=2)=.420, P(K>=3)=.250.
    expected = [1 - 0.431, 0.431 - 0.420, 0.420 - 0.250, 0.250]
    assert comonotone_sum_distribution(P0807) == pytest.approx(expected, abs=1e-12)
    assert expected == pytest.approx([0.569, 0.011, 0.170, 0.250], abs=1e-12)


def test_comonotone_is_order_invariant():
    a = comonotone_sum_distribution(P0807)
    b = comonotone_sum_distribution(tuple(reversed(P0807)))
    assert a == pytest.approx(b, abs=1e-12)


# --------------------------------------------------------------------------------------
# independent: the Bernoulli convolution, checked term by term
# --------------------------------------------------------------------------------------

def test_independent_matches_hand_computed_convolution():
    p1, p2, p3 = P0807
    q1, q2, q3 = 1 - p1, 1 - p2, 1 - p3
    expected = [
        q1 * q2 * q3,
        p1 * q2 * q3 + q1 * p2 * q3 + q1 * q2 * p3,
        p1 * p2 * q3 + p1 * q2 * p3 + q1 * p2 * p3,
        p1 * p2 * p3,
    ]
    assert independent_sum_distribution(P0807) == pytest.approx(expected, abs=1e-12)
    assert expected == pytest.approx([0.247515, 0.449225, 0.258005, 0.045255], abs=1e-9)


def test_independent_variance_equals_sum_of_bernoulli_variances():
    """A closed form the convolution code never touches: Var = sum p_i (1 - p_i)."""
    probs = independent_sum_distribution(P0807)
    expected = sum(p * (1 - p) for p in P0807)
    assert sum_variance(probs) == pytest.approx(expected, abs=1e-12)
    assert expected == pytest.approx(0.676339, abs=1e-9)


# --------------------------------------------------------------------------------------
# every coupling preserves E[K] -- that is the whole reason lambda is not an arbitrage
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "builder",
    [
        comonotone_sum_distribution,
        independent_sum_distribution,
        lambda p: extremal_sum_distribution(p, objective="min_variance").probs,
        lambda p: extremal_sum_distribution(p, objective="max_variance").probs,
    ],
)
def test_expected_k_is_copula_free(builder):
    probs = np.asarray(builder(P0807), dtype=float)
    mean = float(np.dot(np.arange(probs.size), probs))
    assert mean == pytest.approx(E_K, abs=1e-9)


@pytest.mark.parametrize("lam", [-1.0, -0.5, 0.0, 0.25, 0.54, 1.0])
def test_mixture_family_preserves_expected_k(lam):
    probs = mixture_sum_distribution(P0807, lam)
    mean = float(np.dot(np.arange(probs.size), probs))
    assert mean == pytest.approx(E_K, abs=1e-9)
    assert float(probs.sum()) == pytest.approx(1.0, abs=1e-12)
    assert np.all(probs >= -1e-12)


# --------------------------------------------------------------------------------------
# the LP, checked against answers it does not compute
# --------------------------------------------------------------------------------------

def test_lp_max_variance_reproduces_the_comonotone_coupling():
    """The maximum-variance coupling of Bernoullis is the upper Frechet bound. The LP is
    not told this, so agreement is a standing check on the LP formulation itself."""
    lp = extremal_sum_distribution(P0807, objective="max_variance")
    assert lp.feasible
    assert lp.probs == pytest.approx(comonotone_sum_distribution(P0807), abs=1e-9)


def test_lp_min_variance_matches_hand_constructed_joint():
    """A two-point law on {1, 2} with P(2) = 0.101 has mean 1.101, and it IS attainable:
    put 0.101/3 on each of the three two-hike cells and the remainder on the matching
    one-hike cells, which leaves every marginal exact and every mass non-negative."""
    lp = extremal_sum_distribution(P0807, objective="min_variance")
    assert lp.feasible and lp.status == "optimal"
    assert lp.probs == pytest.approx([0.0, 0.899, 0.101, 0.0], abs=1e-9)
    # Var = E[K^2] - mu^2 = (0.899 + 4*0.101) - 1.101^2
    assert lp.variance == pytest.approx(0.899 + 4 * 0.101 - E_K ** 2, abs=1e-9)
    assert lp.variance == pytest.approx(0.090799, abs=1e-9)


def test_lp_min_variance_orders_below_independent_below_comonotone():
    b = coupling_bounds(P0807)
    assert b.var_min_variance < b.var_independent < b.var_comonotone


def test_two_fair_coins_have_hand_checkable_extremes():
    p = (0.5, 0.5)
    assert comonotone_sum_distribution(p) == pytest.approx([0.5, 0.0, 0.5], abs=1e-12)
    assert independent_sum_distribution(p) == pytest.approx([0.25, 0.5, 0.25], abs=1e-12)
    lp = extremal_sum_distribution(p, objective="min_variance")
    # Exactly one of the two hikes happens: K is degenerate at 1.
    assert lp.probs == pytest.approx([0.0, 1.0, 0.0], abs=1e-9)
    assert lp.variance == pytest.approx(0.0, abs=1e-12)


def test_single_meeting_collapses_every_coupling():
    p = (0.37,)
    expected = [0.63, 0.37]
    assert comonotone_sum_distribution(p) == pytest.approx(expected, abs=1e-12)
    assert independent_sum_distribution(p) == pytest.approx(expected, abs=1e-12)
    assert extremal_sum_distribution(p, objective="min_variance").probs == pytest.approx(expected, abs=1e-12)


# --------------------------------------------------------------------------------------
# the lambda coordinate
# --------------------------------------------------------------------------------------

def test_measured_wing_masses_and_lambda_wing_reproduce_the_0807_reading():
    b = coupling_bounds(P0807)
    assert b.wing_comonotone == pytest.approx(0.819, abs=1e-9)
    assert b.wing_independent == pytest.approx(0.292770, abs=1e-9)
    assert b.wing_min_variance == pytest.approx(0.0, abs=1e-9)

    observed_rnd = [0.386, 0.179, 0.230, 0.191]
    observed_wing = wing_mass(observed_rnd)
    assert observed_wing == pytest.approx(0.577, abs=1e-12)
    assert b.lambda_wing(observed_wing) == pytest.approx(0.54, abs=5e-3)


def test_lambda_is_zero_at_independent_one_at_comonotone_minus_one_at_min_variance():
    b = coupling_bounds(P0807)
    assert b.lambda_wing(b.wing_independent) == pytest.approx(0.0, abs=1e-12)
    assert b.lambda_wing(b.wing_comonotone) == pytest.approx(1.0, abs=1e-12)
    assert b.lambda_wing(b.wing_min_variance) == pytest.approx(-1.0, abs=1e-9)
    assert b.lambda_var(b.var_independent) == pytest.approx(0.0, abs=1e-12)
    assert b.lambda_var(b.var_comonotone) == pytest.approx(1.0, abs=1e-12)
    assert b.lambda_var(b.var_min_variance) == pytest.approx(-1.0, abs=1e-9)


@pytest.mark.parametrize("lam", [-1.0, -0.6, -0.1, 0.0, 0.2, 0.54, 0.9, 1.0])
def test_wing_and_variance_lambdas_agree_inside_the_family(lam):
    """Both statistics are linear along the mixture family, so a law that lies IN the family
    recovers its own lambda from either one. This identity is what makes a DISAGREEMENT
    between lambda_wing and lambda_var informative rather than noise."""
    b = coupling_bounds(P0807)
    probs = mixture_sum_distribution(P0807, lam)
    assert b.lambda_wing(wing_mass(probs)) == pytest.approx(lam, abs=1e-9)
    assert b.lambda_var(sum_variance(probs)) == pytest.approx(lam, abs=1e-9)


def test_lambda_returns_nan_rather_than_a_fabricated_zero_on_a_degenerate_anchor():
    assert np.isnan(lambda_from_statistic(0.5, independent=0.3, comonotone=0.3))
    assert np.isnan(lambda_from_statistic(0.1, independent=0.3, comonotone=0.9))  # no min anchor
    assert np.isnan(lambda_from_statistic(float("nan"), independent=0.3, comonotone=0.9))


# --------------------------------------------------------------------------------------
# the HARD tier: a variance outside the bounds is a static arbitrage, not a view
# --------------------------------------------------------------------------------------

def test_variance_inside_the_bounds_is_not_a_violation():
    b = coupling_bounds(P0807)
    assert variance_bounds_violation(b.var_independent, b) == 0.0
    assert variance_bounds_violation(b.var_comonotone, b) == 0.0
    assert variance_bounds_violation(b.var_min_variance, b) == 0.0


def test_variance_outside_the_bounds_is_signed():
    b = coupling_bounds(P0807)
    assert variance_bounds_violation(b.var_comonotone + 0.05, b) == pytest.approx(0.05, abs=1e-9)
    assert variance_bounds_violation(b.var_min_variance - 0.02, b) == pytest.approx(-0.02, abs=1e-9)
    assert np.isnan(variance_bounds_violation(float("nan"), b))


# --------------------------------------------------------------------------------------
# input hygiene
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [(), (1.5,), (-0.1, 0.5), (float("nan"), 0.5)])
def test_invalid_marginals_raise(bad):
    with pytest.raises(ValueError):
        coupling_bounds(bad)


def test_too_many_meetings_raises_rather_than_hanging():
    with pytest.raises(ValueError, match="LP columns"):
        extremal_sum_distribution([0.3] * 17)
