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


# --------------------------------------------------------------------------------------
# categorical marginals: the 50bp-contamination machinery
# --------------------------------------------------------------------------------------

from RVUtils.SR3ZQDistributionScreener._copula import (  # noqa: E402
    categorical_comonotone_sum,
    categorical_independent_sum,
    categorical_min_variance_sum,
    fold_to_binary_support,
    three_point_marginal,
)


def test_categorical_comonotone_matches_hand_walked_uniform_partition():
    """Two Bernoullis, worked by hand over the CDF breakpoints {0, .25, .5, 1}."""
    got = categorical_comonotone_sum([[0.5, 0.5], [0.25, 0.75]])
    assert got == pytest.approx([0.25, 0.25, 0.50], abs=1e-12)


def test_categorical_comonotone_handles_a_genuine_three_point_marginal():
    """A on {0,1,2} with pmf (.2,.5,.3), B on {0,1} with pmf (.6,.4). Breakpoints
    {0,.2,.6,.7,1} give sums 0,1,2,3 with widths .2,.4,.1,.3."""
    got = categorical_comonotone_sum([[0.2, 0.5, 0.3], [0.6, 0.4]])
    assert got == pytest.approx([0.2, 0.4, 0.1, 0.3], abs=1e-12)
    assert float(np.dot(np.arange(4), got)) == pytest.approx(1.5, abs=1e-12)


def test_categorical_collapses_to_the_bernoulli_case():
    binary = [[1 - p, p] for p in P0807]
    assert categorical_comonotone_sum(binary) == pytest.approx(
        comonotone_sum_distribution(P0807), abs=1e-12
    )
    assert categorical_independent_sum(binary) == pytest.approx(
        independent_sum_distribution(P0807), abs=1e-12
    )
    lp = categorical_min_variance_sum(binary)
    assert lp.feasible
    assert lp.probs == pytest.approx(
        extremal_sum_distribution(P0807, objective="min_variance").probs, abs=1e-8
    )


@pytest.mark.parametrize("mix", [0.0, 0.2, 0.5])
def test_three_point_marginal_keeps_the_mean_zq_pins(mix):
    for e in (0.420, 0.250, 0.431):
        pmf = three_point_marginal(e, mix)
        assert float(pmf.sum()) == pytest.approx(1.0, abs=1e-12)
        assert float(np.dot(np.arange(3), pmf)) == pytest.approx(e, abs=1e-12)
    assert three_point_marginal(0.42, 0.0) == pytest.approx([0.58, 0.42, 0.0], abs=1e-12)


def test_three_point_marginal_refuses_an_impossible_mix():
    # 37.5bp expected with no 50s at all needs P(one 25bp step) = 1.5.
    with pytest.raises(ValueError, match="negative probability"):
        three_point_marginal(1.5, 0.0)
    # 62.5bp expected delivered entirely as 50s needs P(one 50bp step) = 1.25.
    with pytest.raises(ValueError, match="negative probability"):
        three_point_marginal(2.5, 1.0)
    with pytest.raises(ValueError, match="size_mix"):
        three_point_marginal(0.42, 1.5)


def test_an_all_50s_mix_is_legal_when_the_mean_is_small_enough():
    """s = 1 with a 22.5bp expected move is a coin flip between nothing and a 50: it meets
    ZQ's mean exactly and is a perfectly good marginal. The framework must not reject it."""
    pmf = three_point_marginal(0.9, 1.0)
    assert pmf == pytest.approx([0.55, 0.0, 0.45], abs=1e-12)
    assert float(np.dot(np.arange(3), pmf)) == pytest.approx(0.9, abs=1e-12)


@pytest.mark.parametrize("mix", [0.0, 0.25, 0.5])
def test_categorical_couplings_all_preserve_the_mean(mix):
    pmfs = [three_point_marginal(e, mix) for e in P0807]
    want = sum(P0807)
    for probs in (
        categorical_comonotone_sum(pmfs),
        categorical_independent_sum(pmfs),
        categorical_min_variance_sum(pmfs).probs,
    ):
        assert float(np.dot(np.arange(len(probs)), probs)) == pytest.approx(want, abs=1e-8)


def test_categorical_variances_stay_ordered():
    pmfs = [three_point_marginal(e, 0.4) for e in P0807]
    v_min = categorical_min_variance_sum(pmfs).variance
    v_ind = sum_variance(categorical_independent_sum(pmfs))
    v_com = sum_variance(categorical_comonotone_sum(pmfs))
    assert v_min < v_ind < v_com


def test_allowing_50bp_moves_raises_the_wing_mass_at_fixed_marginal_means():
    """The contamination direction, measured rather than asserted: size uncertainty adds
    dispersion to the sum, and on the binary support that dispersion lands in the wings."""
    n = len(P0807)
    binary = fold_to_binary_support(categorical_independent_sum(
        [three_point_marginal(e, 0.0) for e in P0807]), n)
    mixed = fold_to_binary_support(categorical_independent_sum(
        [three_point_marginal(e, 0.4) for e in P0807]), n)
    assert wing_mass(mixed) > wing_mass(binary)


def test_fold_to_binary_support_absorbs_the_top_and_pads_the_short_case():
    assert fold_to_binary_support([0.1, 0.2, 0.3, 0.25, 0.15], 3) == pytest.approx(
        [0.1, 0.2, 0.3, 0.40], abs=1e-12
    )
    assert fold_to_binary_support([0.4, 0.6], 3) == pytest.approx([0.4, 0.6, 0.0, 0.0], abs=1e-12)


# --------------------------------------------------------------------------------------
# the lambda_dependence signal
# --------------------------------------------------------------------------------------

from RVUtils.SR3ZQDistributionScreener._signals import (  # noqa: E402
    compute_signals,
    signal_lambda_dependence,
)
from RVUtils.SR3ZQDistributionScreener._types import RegimeBucket, TradeFlagKind  # noqa: E402


def _sig(**kw):
    base = dict(lambda_wing=0.5, lambda_prior=0.5, lambda_z=0.0, hard_violation_bp2=0.0,
                lambda_atom_spread=0.1)
    base.update(kw)
    return signal_lambda_dependence(**base)


def test_lambda_signal_is_silent_inside_the_z_band():
    assert _sig(lambda_z=0.9) is None
    assert _sig(lambda_z=-0.9) is None


def test_low_lambda_buys_the_wings_and_high_lambda_sells_them():
    """Low lambda means the market prices a fat middle, so the wings are the cheap side."""
    lo = _sig(lambda_wing=0.1, lambda_z=-2.0)
    hi = _sig(lambda_wing=0.9, lambda_z=+2.0)
    assert lo.kind is TradeFlagKind.LAMBDA_DEPENDENCE and lo.direction == "buy_wings"
    assert hi.kind is TradeFlagKind.LAMBDA_DEPENDENCE and hi.direction == "sell_wings"
    assert hi.severity_decile > _sig(lambda_wing=0.7, lambda_z=+1.1).severity_decile


def test_a_variance_outside_every_coupling_outranks_the_view():
    """The hard tier is a static arbitrage and must not be reported as a view trade, even
    when the z-score would not have fired at all."""
    flag = _sig(lambda_z=0.0, hard_violation_bp2=-250.0)
    assert flag.kind is TradeFlagKind.LAMBDA_ARBITRAGE
    assert flag.direction == "buy_wings"
    assert flag.severity_decile == 10
    assert _sig(lambda_z=0.0, hard_violation_bp2=+250.0).direction == "sell_wings"


def test_a_wide_cross_strike_spread_suppresses_the_signal():
    """If the atoms disagree about lambda the RND has left the one-parameter family, so a
    single headline lambda is an average of contradictory readings."""
    assert _sig(lambda_z=-2.5, lambda_atom_spread=0.9) is None
    assert _sig(lambda_z=-2.5, lambda_atom_spread=0.2) is not None


def test_lambda_signal_is_a_no_op_for_callers_that_do_not_pass_it():
    """Existing callers of compute_signals must be untouched."""
    flags = compute_signals(
        residual_ratio=100.0, skew=0.0,
        tail_upper_50bp=0.1, tail_lower_50bp=0.1,
        tail_upper_100bp=0.02, tail_lower_100bp=0.02,
        regime=RegimeBucket.CALM,
    )
    assert all(f.kind not in {TradeFlagKind.LAMBDA_DEPENDENCE, TradeFlagKind.LAMBDA_ARBITRAGE}
               for f in flags)

    with_lambda = compute_signals(
        residual_ratio=100.0, skew=0.0,
        tail_upper_50bp=0.1, tail_lower_50bp=0.1,
        tail_upper_100bp=0.02, tail_lower_100bp=0.02,
        regime=RegimeBucket.CALM,
        lambda_wing=0.1, lambda_prior=0.5, lambda_z=-2.2, lambda_atom_spread=0.1,
    )
    assert any(f.kind is TradeFlagKind.LAMBDA_DEPENDENCE for f in with_lambda)


# --------------------------------------------------------------------------------------
# cross-check against the repo's own day-weighted meeting variance
# --------------------------------------------------------------------------------------

def test_independent_coupling_reproduces_the_repo_day_weighted_variance():
    """``day_weighted_meeting_variance_bp2`` sums ``w_i^2 * 625 * p(1-p)`` with no
    cross-covariance term, so it IS the independent-coupling point of the interval -- and it
    gets there through completely different code. Agreement is a check on both.
    """
    import datetime

    from RVUtils.SR3ZQDistributionScreener._types import MeetingNode
    from RVUtils.SR3ZQDistributionScreener._variance import day_weighted_meeting_variance_bp2

    ref_start = datetime.date(2026, 12, 16)
    ref_end = datetime.date(2027, 3, 17)
    # Unit day-weight: every meeting effective on or before the window start.
    nodes = [
        MeetingNode(
            label=f"m{i}", date=ref_start, prior_effr=0.0, next_effr=0.0,
            expected_change_bp=25.0 * p, char_25bp=0, mantissa=p,
            p_lower=1.0 - p, p_upper=p, variance_bp2=625.0 * p * (1.0 - p),
        )
        for i, p in enumerate(P0807)
    ]
    repo_var, _ = day_weighted_meeting_variance_bp2(nodes, ref_start=ref_start, ref_end=ref_end)

    mine = 625.0 * sum_variance(independent_sum_distribution(P0807))
    assert repo_var == pytest.approx(mine, rel=1e-9)
    assert mine == pytest.approx(422.71, abs=0.02)


def test_the_repo_variance_sits_strictly_inside_the_copula_interval():
    """The screener's existing variance number is one point of a whole interval. Stating the
    interval is the contribution: the same marginals admit anything from the LP minimum to
    the comonotone maximum, and only the middle of that range was ever being reported."""
    b = coupling_bounds(P0807)
    assert b.var_min_variance * 625.0 == pytest.approx(56.75, abs=0.05)
    assert b.var_independent * 625.0 == pytest.approx(422.71, abs=0.02)
    assert b.var_comonotone * 625.0 == pytest.approx(1080.50, abs=0.05)


# --------------------------------------------------------------------------------------
# the screener adapter path
# --------------------------------------------------------------------------------------

def test_screener_adapter_places_a_synthetic_rnd_record_on_the_coordinate():
    """The screener's RND names its arrays density_pdf / density_cdf; everything in the
    measurement was written against a BreedenLitzenbergerResult. Exercise the adapter so a
    rename on either side fails here rather than silently in a daily screen."""
    import datetime
    import types

    import pandas as pd

    from RVUtils.SR3ZQDistributionScreener._lambda_signal import measure_lambda_from_rnd_record

    as_of = datetime.date(2026, 8, 7)
    expiry = datetime.date(2026, 12, 11)

    # A three-atom mixture on the SFRZ26 lattice, wide enough to be admissible.
    grid = np.linspace(2.5, 5.5, 4001)
    pins = [3.687, 3.937, 4.187, 4.437]
    weights = [0.37, 0.21, 0.22, 0.20]
    pdf = np.zeros_like(grid)
    for mu, w in zip(pins, weights):
        pdf += w * np.exp(-0.5 * ((grid - mu) / 0.055) ** 2)
    pdf /= np.trapezoid(pdf, grid)
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[1:] + pdf[:-1]) * np.diff(grid))])
    cdf /= cdf[-1]
    mean = float(np.trapezoid(grid * pdf, grid))

    record = types.SimpleNamespace(
        strike_grid_rate=grid, density_pdf=pdf, density_cdf=cdf,
        std_rate=float(np.sqrt(np.trapezoid((grid - mean) ** 2 * pdf, grid))),
        mean_rate=mean, forward_rate=mean, forward_price=100.0 - mean,
        n_strikes_observed=54, prices_source="market_listed",
    )

    zq = {"ZQQ26": 96.3675, "ZQU26": 96.3150, "ZQV26": 96.2550, "ZQX26": 96.2000,
          "ZQZ26": 96.1200, "ZQF27": 96.0850, "ZQG27": 96.0500, "ZQH27": 96.0200}
    fomc = pd.DataFrame({
        "meeting_label": ["sep26", "oct26", "dec26", "jan27", "mar27"],
        "effective_date": pd.to_datetime(
            ["2026-09-16", "2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17"]
        ),
    })

    m = measure_lambda_from_rnd_record(
        record=record, as_of=as_of, symbol="SFRZ26",
        zq_prices=zq, fomc_schedule=fomc, expiry=expiry,
    )
    assert m.ok, m.reason
    assert m.marginals == pytest.approx((0.420, 0.250, 0.4313), abs=2e-3)
    assert -1.0 <= m.lambda_wing <= 1.5
    assert len(m.observed_atoms) == 4
    assert float(sum(m.observed_atoms)) == pytest.approx(1.0, abs=1e-9)
