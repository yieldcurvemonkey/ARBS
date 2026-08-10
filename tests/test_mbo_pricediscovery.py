"""Tests for the Hasbrouck and Gonzalo-Granger price-discovery shares.

Three of these carry the weight.

The first is a **known-answer test against the literature**: Baillie, Booth, Tse
and Zabotina publish the true information-share bounds and component share for two
analytic bivariate systems, and the two data-generating processes here are those
systems.  Case B (one market does not adjust, innovations uncorrelated) must give
bounds of 1.00/1.00 and a component share of 1.00; Case A (equal adjustment
speeds, innovation correlation 0.9) must give bounds of 0.95/0.05 and a component
share of exactly 0.50.  A statistic that agrees with a published table on data
built to match it is being checked against something other than itself.

The second is an **exact identity test**.  The simulated fits above are
statistical and can only be asserted to a tolerance, which would leave the
Cholesky and permutation plumbing free to be subtly wrong.  So the shares the
module reports are also compared, to 1e-12, against the closed-form bivariate
Hasbrouck expressions evaluated at the module's OWN fitted weights and covariance.
Those expressions are re-derived here rather than copied: the printed factor in
the secondary literature carries a ``(1 - rho)^(1/2)`` where ``F F' = Sigma``
requires ``(1 - rho^2)^(1/2)``, and a test that copied the typo would certify it.

The third is the **guard**: two random walks are not cointegrated and have no
common efficient price, yet every step of both statistics computes happily on them
and returns two numbers that sum to one.  The seed is pinned after checking the
unit-root test really does fail to reject on it -- under the null the p-value is
uniform, so an unpinned seed would flip this test's meaning about one run in
twenty.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.pricediscovery import (
    UNINFORMATIVE_BOUND_WIDTH,
    _common_factor,
    _orderings,
    _shares_for_order,
    component_share,
    information_share,
    vecm_fit,
)


def _index(n):
    return pd.date_range("2026-08-03 14:00", periods=n, freq="1s", tz="UTC")


# --------------------------------------------------------------------------- #
# the two Baillie et al. systems, and a pair with nothing in common
# --------------------------------------------------------------------------- #

def _leader_follower(n=20_000, a2=0.05, seed=101, rho=0.0):
    """Baillie et al. Case B: ``fast`` never adjusts, ``slow`` comes to it.

    ``d fast = e1``; ``d slow = a2 (fast - slow)_{t-1} + e2``, innovations
    uncorrelated.  The efficient price is ``fast`` by construction, so the true
    information share is 1.00 at BOTH bounds and the component share is 1.00.
    """
    rng = np.random.default_rng(seed)
    e = rng.multivariate_normal(np.zeros(2),
                                np.array([[1.0, rho], [rho, 1.0]]), size=n)
    x = np.zeros((n, 2))
    for t in range(1, n):
        z = x[t - 1, 0] - x[t - 1, 1]
        x[t, 0] = x[t - 1, 0] + e[t, 0]
        x[t, 1] = x[t - 1, 1] + a2 * z + e[t, 1]
    return pd.DataFrame(x, columns=["fast", "slow"], index=_index(n))


def _equal_speeds(n=20_000, a=0.05, rho=0.9, seed=202):
    """Baillie et al. Case A with rho = 0.9: bounds [0.05, 0.95], CS exactly 0.50.

    Both markets adjust at the same speed, so neither leads; all that differs
    between the Cholesky orderings is which one is credited with the shared 0.9 of
    innovation correlation.  This is the case that makes the point of reporting an
    interval at all.
    """
    rng = np.random.default_rng(seed)
    e = rng.multivariate_normal(np.zeros(2),
                                np.array([[1.0, rho], [rho, 1.0]]), size=n)
    x = np.zeros((n, 2))
    for t in range(1, n):
        z = x[t - 1, 0] - x[t - 1, 1]
        x[t, 0] = x[t - 1, 0] - a * z + e[t, 0]
        x[t, 1] = x[t - 1, 1] + a * z + e[t, 1]
    return pd.DataFrame(x, columns=["a", "b"], index=_index(n))


def _unrelated(n=4000, seed=303):
    """Two independent random walks: no common efficient price to share out.

    Seed pinned deliberately.  Under the unit-root null the ADF p-value is
    uniform, so an arbitrary seed lands below 0.05 about one time in twenty and
    this fixture would silently start testing the opposite of what it says.  On
    seed 303 the p-value is 0.73.
    """
    rng = np.random.default_rng(seed)
    return pd.DataFrame(np.cumsum(rng.normal(size=(n, 2)), axis=0),
                        columns=["p", "q"], index=_index(n))


def _three_venues(n=30_000, seed=77):
    """One leader and two followers adjusting at different speeds."""
    rng = np.random.default_rng(seed)
    e = rng.normal(size=(n, 3))
    x = np.zeros((n, 3))
    for t in range(1, n):
        x[t, 0] = x[t - 1, 0] + e[t, 0]
        x[t, 1] = x[t - 1, 1] + 0.05 * (x[t - 1, 0] - x[t - 1, 1]) + e[t, 1]
        x[t, 2] = x[t - 1, 2] + 0.10 * (x[t - 1, 0] - x[t - 1, 2]) + e[t, 2]
    return pd.DataFrame(x, columns=["lead", "mid", "lag"], index=_index(n))


@pytest.fixture(scope="module")
def leader():
    return _leader_follower()


@pytest.fixture(scope="module")
def equal():
    return _equal_speeds()


@pytest.fixture(scope="module")
def three():
    return _three_venues()


# --------------------------------------------------------------------------- #
# the published known answers
# --------------------------------------------------------------------------- #

def test_the_market_that_never_adjusts_takes_the_whole_information_share(leader):
    """Baillie et al. Case B, rho = 0: true bounds 1.00 / 1.00, CS 1.00."""
    got = information_share(leader, lags=2)
    assert list(got.index) == ["fast", "slow"]
    assert got.loc["fast", "is_lower"] > 0.99
    assert got.loc["fast", "is_upper"] > 0.99
    assert got.loc["slow", "is_upper"] < 0.01
    assert not got["bounds_uninformative"].any()


def test_the_leader_also_takes_the_whole_component_share(leader):
    cs = component_share(leader, lags=2)
    assert cs.loc["fast", "cs"] == pytest.approx(1.0, abs=0.05)
    assert cs.loc["slow", "cs"] == pytest.approx(0.0, abs=0.05)
    assert cs["cs"].sum() == pytest.approx(1.0, abs=1e-12)


def test_equal_adjustment_speeds_and_correlated_innovations_give_wide_bounds(equal):
    """Baillie et al. Case A, rho = 0.9: the bounds run 0.05 to 0.95.

    This is the number that makes the interval non-negotiable. The same fit
    supports "market a made the price" and "market a made none of it", and which
    one you report is decided by the order you typed the column names in.
    """
    got = information_share(equal, lags=2)
    for series in ("a", "b"):
        assert got.loc[series, "is_lower"] < 0.10
        assert got.loc[series, "is_upper"] > 0.90
        assert got.loc[series, "bound_width"] > 0.80
        assert got.loc[series, "bounds_uninformative"]


def test_the_bound_width_is_the_innovation_correlation(equal):
    """In this symmetric system the interval width IS rho, and nothing else.

    Worth asserting because it names the mechanism: the bounds are wide precisely
    to the extent that the two markets' innovations arrive together, which is a
    property of the sampling interval, not of who is informed.
    """
    fit = vecm_fit(equal, lags=2)
    s = fit["sigma"]
    rho_hat = s[0, 1] / np.sqrt(s[0, 0] * s[1, 1])
    width = information_share(equal, lags=2).loc["a", "bound_width"]
    assert width == pytest.approx(rho_hat, abs=0.01)


def test_component_share_is_pinned_at_a_half_where_hasbrouck_spans_everything(equal):
    """The disagreement is the point: CS 0.50 against IS bounds [0.05, 0.95].

    Gonzalo-Granger never looks at the innovation covariance, so the correlation
    that opens the Hasbrouck interval to nine tenths of the unit interval moves
    the component share not at all.
    """
    cs = component_share(equal, lags=2)
    assert cs.loc["a", "cs"] == pytest.approx(0.5, abs=0.05)
    assert cs.loc["b", "cs"] == pytest.approx(0.5, abs=0.05)
    assert not cs["cs_out_of_range"].any()
    assert information_share(equal, lags=2).loc["a", "bound_width"] > 0.80


# --------------------------------------------------------------------------- #
# the exact identity: no tolerance, no simulation noise
# --------------------------------------------------------------------------- #

def _closed_form_bivariate(psi, sigma):
    """Hasbrouck's bivariate shares, re-derived rather than copied.

    Ordering (1, 2) has ``F = [[s1, 0], [rho s2, s2 sqrt(1 - rho^2)]]``. The
    printed version in the secondary literature has ``sqrt(1 - rho)`` in the
    corner, which does not satisfy ``F F' = Sigma``; deriving it here is what
    keeps this test independent of the module and of that paper.
    """
    s1, s2 = np.sqrt(sigma[0, 0]), np.sqrt(sigma[1, 1])
    rho = sigma[0, 1] / (s1 * s2)
    d = float(psi @ sigma @ psi)
    p1, p2 = psi
    first = np.array([(p1 * s1 + p2 * rho * s2) ** 2,
                      p2 ** 2 * s2 ** 2 * (1 - rho ** 2)])
    second = np.array([p1 ** 2 * s1 ** 2 * (1 - rho ** 2),
                       (p2 * s2 + p1 * rho * s1) ** 2])
    return first / d, second / d


def test_the_shares_equal_the_closed_form_at_the_fitted_parameters(equal):
    fit = vecm_fit(equal, lags=2)
    order_12, order_21 = _closed_form_bivariate(fit["psi"], fit["sigma"])
    got = information_share(equal, lags=2)

    assert got["is_lower"].to_numpy() == pytest.approx(
        np.minimum(order_12, order_21), abs=1e-12)
    assert got["is_upper"].to_numpy() == pytest.approx(
        np.maximum(order_12, order_21), abs=1e-12)
    assert got["is_mid"].to_numpy() == pytest.approx(
        0.5 * (np.minimum(order_12, order_21) + np.maximum(order_12, order_21)),
        abs=1e-12)


def test_a_pinned_ordering_reproduces_that_orderings_closed_form(equal):
    fit = vecm_fit(equal, lags=2)
    order_12, order_21 = _closed_form_bivariate(fit["psi"], fit["sigma"])

    ab = information_share(equal, order=["a", "b"], lags=2)
    ba = information_share(equal, order=["b", "a"], lags=2)
    assert ab["is_ordered"].to_numpy() == pytest.approx(order_12, abs=1e-12)
    assert ba["is_ordered"].to_numpy() == pytest.approx(order_21, abs=1e-12)
    assert list(ab["order_position"]) == [0, 1]
    assert list(ba["order_position"]) == [1, 0]


def test_order_position_is_where_each_series_sits_not_what_sits_where(three):
    """The two readings coincide for two series and part company at three.

    ``order_position`` is indexed BY series and holds a position, i.e. the inverse
    of the permutation handed in. For ``["mid", "lag", "lead"]`` against columns
    ``(lead, mid, lag)`` the permutation is (1, 2, 0) and the answer is (2, 0, 1);
    a two-series test cannot tell them apart because every permutation of two
    elements is its own inverse.
    """
    got = information_share(three, order=["mid", "lag", "lead"], lags=1)
    assert list(got.index) == ["lead", "mid", "lag"]
    assert list(got["order_position"]) == [2, 0, 1]


def test_shares_under_one_ordering_sum_to_one_exactly(three):
    for order in itertools.permutations(["lead", "mid", "lag"]):
        got = information_share(three, order=list(order), lags=1)
        assert got["is_ordered"].sum() == pytest.approx(1.0, abs=1e-12)


def test_a_pinned_result_cannot_be_mistaken_for_a_bound(equal):
    """Different column names on purpose: a single ordering is not an interval."""
    pinned = information_share(equal, order=["a", "b"], lags=2)
    assert list(pinned.columns) == ["is_ordered", "order_position"]
    assert "is_lower" not in pinned.columns
    assert "is_mid" not in pinned.columns


# --------------------------------------------------------------------------- #
# the guard that stops both statistics being computed on nonsense
# --------------------------------------------------------------------------- #

def test_two_random_walks_raise_instead_of_reporting_a_share():
    panel = _unrelated()
    with pytest.raises(ValueError, match="not cointegrated"):
        information_share(panel, lags=2)
    with pytest.raises(ValueError, match="not cointegrated"):
        component_share(panel, lags=2)
    with pytest.raises(ValueError, match="not cointegrated"):
        vecm_fit(panel, lags=2)


def test_the_unrelated_fixture_really_does_fail_the_unit_root_test():
    """Verify the check against an input whose answer is known.

    A cointegration guard that raised for the wrong reason -- too few rows, a NaN,
    an unrelated validation error -- would pass the test above and hide the very
    failure it exists to catch.
    """
    from statsmodels.tsa.stattools import adfuller

    panel = _unrelated()
    spread = panel["p"].to_numpy() - panel["q"].to_numpy()
    assert adfuller(spread, maxlag=2, regression="c", autolag=None)[1] > 0.3


def test_a_cointegrated_pair_passes_the_same_guard(leader):
    """The other half: the guard must not reject everything put in front of it."""
    fit = vecm_fit(leader, lags=2)
    assert fit["coint_pvalues"]["fast-slow"] < 0.01


def test_the_guard_can_be_relaxed_but_must_be_relaxed_on_purpose():
    panel = _unrelated()
    got = information_share(panel, lags=2, coint_pvalue=1.0)
    assert len(got) == 2                       # computes, and means nothing


# --------------------------------------------------------------------------- #
# degenerate covariance
# --------------------------------------------------------------------------- #

def test_perfectly_correlated_innovations_are_refused_not_bounded():
    """One shared innovation makes the covariance singular and the share undefined.

    Not the same case as wide bounds. As the innovation correlation approaches one
    the interval approaches [0, 1] and the statistic stops discriminating; AT one
    there is no Cholesky factor at all, and reporting [0, 1] would suggest a
    computation had taken place.
    """
    n = 6000
    rng = np.random.default_rng(404)
    e = rng.normal(size=n)
    x = np.zeros((n, 2))
    for t in range(1, n):
        # 'two' carries HALF of 'one''s innovation and nothing of its own, so the
        # spread is still a genuine stationary AR(1) -- the pair passes the
        # cointegration guard -- while the residual covariance is exactly rank one.
        x[t, 0] = x[t - 1, 0] + e[t]
        x[t, 1] = x[t - 1, 1] + 0.08 * (x[t - 1, 0] - x[t - 1, 1]) + 0.5 * e[t]
    panel = pd.DataFrame(x, columns=["one", "two"], index=_index(n))
    assert vecm_fit(panel, lags=0)["coint_pvalues"]["one-two"] < 0.01
    with pytest.raises(ValueError, match="singular"):
        information_share(panel, lags=0)


def test_the_singular_covariance_guard_does_not_wait_for_lapack_to_raise():
    """A covariance LAPACK is happy to factor, and the guard must refuse anyway.

    This is the case that makes the guard worth having. At correlation 1 - 1e-9
    the final Cholesky pivot is about 2e-9: positive, so numpy returns a factor,
    whose last column is entirely round-off. Shares computed from it are finite,
    sum to one and mean nothing. A guard written as ``try: cholesky`` would let
    this straight through, so the test asserts LAPACK's acceptance first -- it
    cannot be satisfied by the exception path.
    """
    from RVUtils.MBO.analytics.pricediscovery import _check_cholesky

    sigma = np.array([[1.0, 1.0 - 1e-9], [1.0 - 1e-9, 1.0]])
    np.linalg.cholesky(sigma)                        # numpy does NOT object
    with pytest.raises(ValueError, match="singular"):
        _check_cholesky(sigma, ("one", "two"))

    # exactly rank one, where numpy does object: must give the same verdict
    with pytest.raises(ValueError, match="singular"):
        _check_cholesky(np.array([[4.0, 2.0], [2.0, 1.0]]), ("one", "two"))

    # strongly but not perfectly correlated still factors, and must NOT be refused
    _check_cholesky(np.array([[1.0, 0.9999], [0.9999, 1.0]]), ("one", "two"))


def test_a_series_with_no_innovation_of_its_own_is_refused():
    """``echo`` is a deterministic function of ``real``, not a second quote of it.

    Its residual variance comes back as about 1e-30 rather than zero, because an
    exactly-explained series still leaves rounding dust. Every share computed from
    that is finite and sums to one; the module must refuse it rather than report
    that ``echo`` contributed 4e-32 of the price discovery.
    """
    n = 6000
    rng = np.random.default_rng(606)
    e = rng.normal(size=n)
    x = np.zeros((n, 2))
    for t in range(1, n):
        x[t, 0] = x[t - 1, 0] + e[t]
        x[t, 1] = x[t - 1, 1] + 0.08 * (x[t - 1, 0] - x[t - 1, 1])
    panel = pd.DataFrame(x, columns=["real", "echo"], index=_index(n))

    variances = np.diag(vecm_fit(panel, lags=0)["sigma"])
    assert variances[1] > 0.0                        # positive, just meaningless
    with pytest.raises(ValueError, match="no innovation of their own"):
        information_share(panel, lags=0)


def test_the_same_series_under_two_names_is_refused():
    """A constant offset does not subtract to a constant in floating point.

    ``walk - (walk + 0.25)`` leaves a few units in the last place of the price, so
    a spread-variance test written against exact zero passes this straight through
    to a unit-root test run on rounding noise.
    """
    n = 3000
    rng = np.random.default_rng(505)
    walk = np.cumsum(rng.normal(size=n))
    panel = pd.DataFrame({"zn": walk, "zn_copy": walk + 0.25}, index=_index(n))
    assert np.std(panel["zn"].to_numpy() - panel["zn_copy"].to_numpy()) > 0.0
    with pytest.raises(ValueError, match="constant at every observation"):
        vecm_fit(panel, lags=2)


def test_an_exactly_duplicated_column_is_refused_too():
    n = 3000
    rng = np.random.default_rng(506)
    walk = np.cumsum(rng.normal(size=n))
    panel = pd.DataFrame({"zn": walk, "zn_again": walk.copy()}, index=_index(n))
    with pytest.raises(ValueError, match="constant at every observation"):
        vecm_fit(panel, lags=2)


def test_an_unidentified_common_trend_is_refused():
    """No market adjusts, so there is no common trend to take a share of.

    Reached through the private helper on purpose: for two series this state also
    fails the cointegration test, which fires first, so the guard is unreachable
    from the public path and would otherwise never be exercised at all.
    """
    with pytest.raises(ValueError, match="rank 0, not 1"):
        _common_factor(np.zeros((2, 1)), np.eye(2))


# --------------------------------------------------------------------------- #
# the ordering enumeration -- the load-bearing correctness claim
# --------------------------------------------------------------------------- #

def test_the_reduced_enumeration_reaches_the_same_extremes_as_every_permutation():
    """Above four series only ``n 2^(n-1)`` orderings are fitted, not ``n!``.

    That is sound because a series' share depends on the SET ordered ahead of it
    and not on the order within that set. This asserts it at n = 5, where the full
    120 permutations are still cheap enough to brute-force.
    """
    rng = np.random.default_rng(5)
    for _ in range(20):
        root = rng.normal(size=(5, 5))
        sigma = root @ root.T + 0.05 * np.eye(5)
        psi = rng.normal(size=5)
        full = np.vstack([_shares_for_order(psi, sigma, p)
                          for p in itertools.permutations(range(5))])
        reduced = np.vstack([_shares_for_order(psi, sigma, p) for p in _orderings(5)])
        assert reduced.min(axis=0) == pytest.approx(full.min(axis=0), abs=1e-12)
        assert reduced.max(axis=0) == pytest.approx(full.max(axis=0), abs=1e-12)
        assert len(_orderings(5)) < 120


def test_first_and_last_placement_do_not_generally_give_the_bounds():
    """The shortcut the literature uses, shown failing -- which is why we enumerate.

    Taking the upper bound from the series placed first and the lower from the
    series placed last is exact for two series and wrong in general. If this test
    ever stops finding a counterexample, the enumeration has quietly been replaced
    by the shortcut.
    """
    rng = np.random.default_rng(909)
    counterexamples = 0
    for _ in range(50):
        root = rng.normal(size=(3, 3))
        sigma = root @ root.T + 0.05 * np.eye(3)
        psi = rng.normal(size=3)
        full = np.vstack([_shares_for_order(psi, sigma, p)
                          for p in itertools.permutations(range(3))])
        for i in range(3):
            others = [j for j in range(3) if j != i]
            first = _shares_for_order(psi, sigma, tuple([i] + others))[i]
            if first < full[:, i].max() - 1e-12:
                counterexamples += 1
    assert counterexamples > 0


def test_all_permutations_are_used_up_to_four_series():
    assert _orderings(2) == [(0, 1), (1, 0)]
    assert len(_orderings(3)) == 6
    assert len(_orderings(4)) == 24


def test_too_many_series_is_refused_rather_than_approximated():
    with pytest.raises(ValueError, match="Cholesky orderings"):
        _orderings(13)


# --------------------------------------------------------------------------- #
# invariances that must hold, and one that must not be assumed
# --------------------------------------------------------------------------- #

def test_the_answer_does_not_depend_on_the_panels_column_order(three):
    """The Hasbrouck basis names column 0 as the reference spread leg.

    That choice must not reach the answer: the cointegrating SPACE it spans is the
    set of contrasts summing to zero either way. If reordering the panel moved a
    share, the reference leg would be a free parameter nobody documented.
    """
    a = information_share(three, lags=1)
    b = information_share(three[["lag", "lead", "mid"]], lags=1)
    for series in ("lead", "mid", "lag"):
        assert b.loc[series, "is_lower"] == pytest.approx(
            a.loc[series, "is_lower"], abs=1e-8)
        assert b.loc[series, "is_upper"] == pytest.approx(
            a.loc[series, "is_upper"], abs=1e-8)
    cs_a = component_share(three, lags=1)
    cs_b = component_share(three[["lag", "lead", "mid"]], lags=1)
    for series in ("lead", "mid", "lag"):
        assert cs_b.loc[series, "cs"] == pytest.approx(
            cs_a.loc[series, "cs"], abs=1e-8)


def test_the_three_venue_ranking_matches_the_construction(three):
    """``lead`` never adjusts; ``lag`` adjusts twice as fast as ``mid``."""
    got = information_share(three, lags=1)
    assert got.loc["lead", "is_lower"] > 0.99
    cs = component_share(three, lags=1)
    assert cs.loc["lead", "cs"] > 0.95
    assert cs["cs"].sum() == pytest.approx(1.0, abs=1e-12)


def test_a_negative_component_share_is_reported_not_clipped(three):
    """A market estimated to move away from the spread is a finding, not a bug."""
    cs = component_share(three, lags=1)
    assert list(cs.columns) == ["cs", "alpha_perp", "cs_out_of_range"]
    assert cs["cs_out_of_range"].dtype == np.dtype("bool")
    assert bool(cs["cs_out_of_range"].any()) == bool(
        ((cs["cs"] < 0.0) | (cs["cs"] > 1.0)).any())


# --------------------------------------------------------------------------- #
# the fit itself
# --------------------------------------------------------------------------- #

def test_the_fit_recovers_the_adjustment_speeds_it_was_built_from(leader):
    """d slow = 0.05 (fast - slow); d fast has no error-correction term at all."""
    fit = vecm_fit(leader, lags=2)
    assert fit["alpha"].shape == (2, 1)
    assert fit["alpha"][0, 0] == pytest.approx(0.0, abs=0.01)     # fast: none
    assert fit["alpha"][1, 0] == pytest.approx(0.05, abs=0.01)    # slow: 0.05


def test_the_imposed_cointegrating_basis_is_hasbroucks(three):
    fit = vecm_fit(three, lags=1)
    assert fit["beta"].shape == (3, 2)
    np.testing.assert_allclose(fit["beta"].T,
                               np.array([[1.0, -1.0, 0.0], [1.0, 0.0, -1.0]]))
    np.testing.assert_allclose(fit["beta"].T @ fit["beta_perp"], np.zeros(2),
                               atol=1e-12)


def test_the_long_run_vector_annihilates_the_cointegrating_space(three):
    """``theta' Psi(1) = 0`` is what makes the long-run impact matrix rank one.

    Psi(1) is ``1_n psi'`` here, so the check is that the cointegrating basis
    annihilates the vector of ones -- if it did not, there would be more than one
    common trend and no single share to report.
    """
    fit = vecm_fit(three, lags=1)
    psi_1 = np.outer(fit["beta_perp"], fit["psi"])
    np.testing.assert_allclose(fit["beta"].T @ psi_1, np.zeros((2, 3)), atol=1e-10)
    assert np.linalg.matrix_rank(psi_1, tol=1e-10) == 1


def test_the_component_share_is_the_normalised_long_run_vector(three):
    """CS and Hasbrouck's psi differ only by the scalar Gamma(1) normalisation.

    Worth pinning: it is what guarantees both statistics describe one fit rather
    than two, so a disagreement between them is about the innovation covariance
    and nothing else.
    """
    fit = vecm_fit(three, lags=1)
    cs = component_share(three, lags=1)["cs"].to_numpy()
    assert cs == pytest.approx(fit["psi"] / fit["psi"].sum(), abs=1e-10)


def test_the_shares_ignore_the_scale_of_the_long_run_vector(equal):
    """Both statistics are ratios homogeneous of degree zero in psi.

    So the Gamma(1) normalisation cannot change an answer, which is why it is
    reported rather than relied on.
    """
    fit = vecm_fit(equal, lags=2)
    base = _shares_for_order(fit["psi"], fit["sigma"], (0, 1))
    for scale in (-7.5, 1e-4, 3.0):
        assert _shares_for_order(fit["psi"] * scale, fit["sigma"], (0, 1)) == \
            pytest.approx(base, abs=1e-12)


def test_a_pure_error_correction_model_is_allowed(leader):
    fit = vecm_fit(leader, lags=0)
    assert fit["gamma"].shape == (0, 2, 2)
    np.testing.assert_allclose(fit["gamma_1"], np.eye(2))
    assert fit["alpha"][1, 0] == pytest.approx(0.05, abs=0.01)


def test_the_lag_order_reaches_the_fit(leader):
    a = vecm_fit(leader, lags=1)
    b = vecm_fit(leader, lags=6)
    assert a["gamma"].shape == (1, 2, 2)
    assert b["gamma"].shape == (6, 2, 2)
    assert a["nobs"] != b["nobs"]


def test_the_residual_covariance_matches_the_innovations_it_was_built_from(equal):
    """The DGP draws innovations with unit variance and correlation 0.9."""
    sigma = vecm_fit(equal, lags=2)["sigma"]
    assert sigma[0, 0] == pytest.approx(1.0, abs=0.05)
    assert sigma[1, 1] == pytest.approx(1.0, abs=0.05)
    assert sigma[0, 1] / np.sqrt(sigma[0, 0] * sigma[1, 1]) == \
        pytest.approx(0.9, abs=0.02)


# --------------------------------------------------------------------------- #
# input handling
# --------------------------------------------------------------------------- #

def test_an_empty_panel_gives_an_empty_typed_frame():
    empty = pd.DataFrame()
    got = information_share(empty)
    assert got.empty
    assert list(got.columns) == ["is_lower", "is_upper", "is_mid", "bound_width",
                                 "bounds_uninformative"]
    assert got["is_lower"].dtype == np.dtype("float64")
    assert got["bounds_uninformative"].dtype == np.dtype("bool")
    assert got.index.name == "series"

    ordered = information_share(empty, order=["a", "b"])
    assert list(ordered.columns) == ["is_ordered", "order_position"]
    assert ordered["order_position"].dtype == np.dtype("int64")

    cs = component_share(empty)
    assert cs.empty
    assert list(cs.columns) == ["cs", "alpha_perp", "cs_out_of_range"]


def test_a_panel_with_rows_but_no_columns_is_also_empty():
    got = information_share(pd.DataFrame(index=_index(10)))
    assert got.empty


def test_an_empty_panel_cannot_be_fitted():
    """There is no empty model, so vecm_fit raises where the frames do not."""
    with pytest.raises(ValueError, match="empty panel"):
        vecm_fit(pd.DataFrame())


def test_something_that_is_not_a_frame_says_so():
    with pytest.raises(TypeError, match="must be a DataFrame"):
        information_share(np.zeros((100, 2)))


def test_a_single_field_multiindex_panel_is_accepted(leader):
    wide = pd.concat({"mid": leader}, axis=1)
    wide.columns.names = ["field", "symbol"]
    got = information_share(wide, lags=2)
    assert list(got.index) == ["fast", "slow"]
    assert got.loc["fast", "is_lower"] > 0.99


def test_two_fields_are_refused_rather_than_flattened(leader):
    wide = pd.concat({"bid": leader, "ask": leader + 0.01}, axis=1)
    wide.columns.names = ["field", "symbol"]
    with pytest.raises(ValueError, match="carries 2 fields"):
        information_share(wide, lags=2)


def test_one_series_cannot_lead_itself():
    with pytest.raises(ValueError, match="at least two series"):
        information_share(pd.DataFrame({"only": np.arange(500.0)}))


def test_duplicate_column_names_are_refused():
    n = 500
    panel = pd.DataFrame(np.zeros((n, 2)), columns=["zn", "zn"], index=_index(n))
    with pytest.raises(ValueError, match="duplicate series names"):
        information_share(panel)


def test_leading_nans_are_dropped_but_interior_gaps_raise(leader):
    """A hole would be read as one sampling interval and shrink the adjustment.

    Leading NaNs are the normal shape of a panel -- an instrument had not started
    quoting -- so those are dropped. An interior hole is a different animal and
    cannot be silently closed up.
    """
    lead_nan = leader.copy()
    lead_nan.iloc[:20, 1] = np.nan
    got = information_share(lead_nan, lags=2)
    assert got.loc["fast", "is_lower"] > 0.99

    hole = leader.copy()
    hole.iloc[5000:5010, 0] = np.nan
    with pytest.raises(ValueError, match="interior rows with a missing price"):
        information_share(hole, lags=2)


def test_a_panel_that_never_has_every_price_at_once():
    n = 400
    panel = pd.DataFrame({"a": np.arange(float(n)), "b": np.arange(float(n))},
                         index=_index(n))
    panel.loc[panel.index[:200], "a"] = np.nan
    panel.loc[panel.index[200:], "b"] = np.nan
    with pytest.raises(ValueError, match="no row of the panel"):
        information_share(panel)


def test_a_non_numeric_panel_says_so():
    n = 400
    panel = pd.DataFrame({"a": ["x"] * n, "b": np.arange(float(n))},
                         index=_index(n))
    with pytest.raises(ValueError, match="numeric prices"):
        information_share(panel)


def test_an_order_that_is_not_a_permutation_is_refused(equal):
    with pytest.raises(ValueError, match="not a permutation"):
        information_share(equal, order=["a", "a"], lags=2)
    with pytest.raises(ValueError, match="not a permutation"):
        information_share(equal, order=["a"], lags=2)
    with pytest.raises(ValueError, match="not a permutation"):
        information_share(equal, order=["a", "b", "c"], lags=2)


def test_a_bad_lag_order_is_refused(leader):
    for bad in (-1, 2.5, "5", True):
        with pytest.raises(ValueError, match="non-negative integer"):
            vecm_fit(leader, lags=bad)


def test_too_short_a_sample_for_the_lag_order_is_refused(leader):
    with pytest.raises(ValueError, match="usable observations"):
        vecm_fit(leader.iloc[:40], lags=10)
