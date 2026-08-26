"""The Hull-White SOFR convexity model, checked four independent ways.

The model is closed-form algebra, and closed-form algebra is exactly the kind
of code that runs, returns a plausible number, and is wrong. So nothing here
compares the module against itself:

1. **Quadrature.** Every integral is re-integrated numerically from its
   defining integrand, written out in this file. That catches an algebra slip
   in the closed form.
2. **Monte Carlo.** ``E[exp(int x ds)] = exp(v/2)`` is simulated from an exactly
   stepped Ornstein-Uhlenbeck path. That is what settles the sign question the
   published formula leaves open (arXiv:2304.13402 eq (17) prints a minus).
3. **QuantLib.** ``ql.HullWhite.convexityBias`` is an independent C++
   implementation of the term/ED payoff. Its exact relationship to this module
   is pinned below -- and it is pinned against a KNOWN answer first, because a
   miscalibrated oracle is worse than none.
4. **The a -> 0 limits**, each written from the paper rather than from the code.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import QuantLib as ql
from scipy.integrate import quad

from RVUtils.ConvexityRV import hw1f_sofr as H
from RVUtils.ConvexityRV.holee import pack_ca_bp as holee_pack_ca_bp

SIGMA = 0.01           # 100bp/yr, decimal
GRID_A = (0.0, 1e-9, 1e-4, 1e-3, 0.01, 0.03, 0.05, 0.10, 0.25)
#: Quadrature grid. It stops at 1e-4 rather than 1e-9 because the REFERENCE
#: goes bad first: the naive ``(1 - exp(-a t))/a`` written below loses nine
#: digits at ``a = 1e-9``, so a disagreement there would be the oracle's, not
#: the module's. ``a = 0`` and the analytic limits cover the bottom end.
GRID_A_QUAD = (0.0, 1e-4, 1e-3, 0.01, 0.03, 0.05, 0.10, 0.25)
GRID_T1 = (0.05, 0.25, 1.0, 3.5, 6.0)
GRID_TAU = (0.2493, 0.25, 0.2548)


def _B(a: float, t: float) -> float:
    """Textbook ``B``, written out here so the module cannot define its own."""
    return t if a == 0.0 else (1.0 - math.exp(-a * t)) / a


# ---------------------------------------------------------------------------
# 1. the integrals, against quadrature
# ---------------------------------------------------------------------------
def test_b_factor_is_the_duration_factor_and_its_limit():
    assert H.b_factor(0.0, 3.5) == 3.5
    assert H.b_factor(0.03, 1.0) == pytest.approx((1 - math.exp(-0.03)) / 0.03)
    # expm1, not 1-exp: at a*t = 1e-12 the naive form has lost every digit
    assert H.b_factor(1e-12, 4.0) == pytest.approx(4.0, rel=1e-11)


@pytest.mark.parametrize("a", GRID_A_QUAD)
@pytest.mark.parametrize("tau", GRID_TAU)
def test_j1_and_j2_reproduce_their_own_integrands(a, tau):
    j1, _ = quad(lambda w: _B(a, w), 0.0, tau, epsabs=1e-16, epsrel=1e-13)
    j2, _ = quad(lambda w: _B(a, w) ** 2, 0.0, tau, epsabs=1e-18, epsrel=1e-13)
    assert H._j1(a, tau) == pytest.approx(j1, rel=1e-10)
    assert H._j2(a, tau) == pytest.approx(j2, rel=1e-10)


def test_the_series_and_the_closed_form_agree_across_the_crossover(monkeypatch):
    """The threshold is a real seam: prove it is not a step.

    Both branches are evaluated at the SAME ``a``, by moving the threshold --
    comparing one branch either side of it measures the function's own slope
    (6.7e-7 across a 0.2% move in ``a``) and would pass a broken series.
    """
    tau = 0.25
    a = H._SERIES_ATAU / tau                    # exactly on the seam
    for f in (H._j1, H._j2):
        monkeypatch.setattr(H, "_SERIES_ATAU", 1e-30)     # force closed form
        closed = f(a, tau)
        monkeypatch.setattr(H, "_SERIES_ATAU", 1e30)      # force the series
        series = f(a, tau)
        assert closed == pytest.approx(series, rel=1e-9),             f"{f.__name__}: series and closed form disagree ON the seam"


@pytest.mark.parametrize("a", GRID_A_QUAD)
@pytest.mark.parametrize("t1", GRID_T1)
def test_drift_term_is_the_integral_of_the_hull_white_alpha(a, t1):
    t2 = t1 + 0.25
    want, _ = quad(lambda s: 0.5 * SIGMA ** 2 * _B(a, s) ** 2, t1, t2,
                   epsabs=1e-20, epsrel=1e-13)
    assert H.drift_term(SIGMA, a, t1, t2) == pytest.approx(want, rel=1e-9)


@pytest.mark.parametrize("a", GRID_A_QUAD)
@pytest.mark.parametrize("t1", GRID_T1)
def test_compounding_var_is_the_variance_of_the_accrued_state(a, t1):
    """``Var(int_{T1}^{T2} x ds) = sigma^2 int_0^{T2} h(u)^2 du``.

    ``h(u)`` is written out from the stochastic integral, not taken from the
    module: ``x_s = sigma int_0^s e^{-a(s-u)} dW_u`` so the ``dW_u`` weight is
    ``int_{max(u,T1)}^{T2} e^{-a(s-u)} ds``.
    """
    t2 = t1 + 0.25

    def h(u: float) -> float:
        lo = max(u, t1)
        return quad(lambda s: math.exp(-a * (s - u)), lo, t2,
                    epsabs=1e-18, epsrel=1e-13)[0]

    want, _ = quad(lambda u: SIGMA ** 2 * h(u) ** 2, 0.0, t2,
                   points=[t1], epsabs=1e-22, epsrel=1e-11, limit=200)
    assert H.compounding_var(SIGMA, a, t1, t2) == pytest.approx(want, rel=1e-7)


# ---------------------------------------------------------------------------
# 2. Monte Carlo -- the sign of the Jensen term
# ---------------------------------------------------------------------------
def _ou_paths(a: float, sigma: float, t1: float, t2: float, *,
              n: int, steps: int, seed: int):
    """Exactly stepped OU, returning ``int_{T1}^{T2} x_s ds`` per path.

    Exact per-step transition -- ``(x_{t+h}, int_t^{t+h} x ds)`` is bivariate
    normal with textbook moments, written out here -- so there is NO
    discretisation bias to confuse with an algebra error. Antithetic pairs,
    because the quantity under test is ``E[exp(I)] - 1 ~ 1e-5`` and a raw mean
    would need ~1e10 paths to see it.
    """
    rng = np.random.default_rng(seed)
    grid = np.concatenate([np.linspace(0.0, t1, steps + 1)[:-1],
                           np.linspace(t1, t2, steps + 1)])
    x_pos = np.zeros(n)
    x_neg = np.zeros(n)
    acc_pos = np.zeros(n)
    acc_neg = np.zeros(n)
    for lo, hi in zip(grid[:-1], grid[1:]):
        h = hi - lo
        if a == 0.0:
            var_x = sigma ** 2 * h
            var_i = sigma ** 2 * h ** 3 / 3.0
            cov = sigma ** 2 * h ** 2 / 2.0
            decay, b_h = 1.0, h
        else:
            var_x = sigma ** 2 * (1.0 - math.exp(-2 * a * h)) / (2 * a)
            b_h = (1.0 - math.exp(-a * h)) / a
            var_i = (sigma ** 2 / a ** 2) * (
                h - 2 * b_h + (1.0 - math.exp(-2 * a * h)) / (2 * a))
            cov = (sigma ** 2 / (2 * a ** 2)) * (1.0 - math.exp(-a * h)) ** 2
            decay = math.exp(-a * h)
        z1 = rng.standard_normal(n)
        z2 = rng.standard_normal(n)
        sd_x = math.sqrt(var_x)
        beta = cov / var_x
        sd_i = math.sqrt(max(var_i - beta * cov, 0.0))
        dx_pos, dx_neg = sd_x * z1, -sd_x * z1
        di_pos = beta * dx_pos + sd_i * z2
        di_neg = beta * dx_neg - sd_i * z2
        i_pos = x_pos * b_h + di_pos
        i_neg = x_neg * b_h + di_neg
        if hi > t1 + 1e-15:
            acc_pos += i_pos
            acc_neg += i_neg
        x_pos = x_pos * decay + dx_pos
        x_neg = x_neg * decay + dx_neg
    return acc_pos, acc_neg


@pytest.mark.parametrize("a", (0.0, 0.03))
def test_monte_carlo_settles_the_sign_of_the_jensen_term(a):
    """``E[exp(I)] = exp(+v/2)``, not ``exp(-v/2)``.

    arXiv:2304.13402 eq (17) prints ``exp(-1/2 int Gamma^2)``. Inverting their
    own eq (17) into their eq (18) only reproduces (18) if (17) carries a plus,
    and this is the measurement that decides it. A big volatility is used so
    the two candidates are many Monte-Carlo standard errors apart.
    """
    sigma, t1, t2 = 0.05, 3.5, 3.75
    v = H.compounding_var(sigma, a, t1, t2)
    pos, neg = _ou_paths(a, sigma, t1, t2, n=60_000, steps=64, seed=20260825)
    i_all = np.concatenate([pos, neg])

    assert float(np.var(i_all, ddof=1)) == pytest.approx(v, rel=0.03)

    got = float(np.mean(np.exp(i_all)))
    plus, minus = math.exp(v / 2), math.exp(-v / 2)
    assert abs(got - plus) < abs(got - minus)
    assert got == pytest.approx(plus, rel=2e-4)
    assert got > 1.0


def test_monte_carlo_prices_the_whole_compounded_adjustment():
    """The futures rate itself, on a flat curve, against :func:`futures_ca`."""
    sigma, a, t1, t2 = 0.05, 0.03, 3.5, 3.75
    tau = t2 - t1
    mu = H.drift_term(sigma, a, t1, t2)
    pos, neg = _ou_paths(a, sigma, t1, t2, n=60_000, steps=64, seed=7)
    i_all = np.concatenate([pos, neg])
    # flat curve r=0 => -log D = 0, so the futures rate is (E[e^{mu + I}]-1)/tau
    mc = float(np.mean(np.exp(mu + i_all)) - 1.0) / tau
    model = H.futures_ca(sigma, t1, t2, a)
    assert mc == pytest.approx(model, rel=2e-3)
    # ...and it is nowhere near the minus-sign variant, which sits 14% away --
    # the tolerance above is Monte-Carlo noise on a difference of exponentials,
    # not slack that could hide the wrong sign.
    wrong = math.expm1(mu - 0.5 * H.compounding_var(sigma, a, t1, t2)) / tau
    assert abs(mc - model) < 0.05 * abs(mc - wrong)


# ---------------------------------------------------------------------------
# 3. QuantLib, calibrated on a known answer before it is used as an oracle
# ---------------------------------------------------------------------------
def _ql_lambda(sigma: float, a: float, t1: float, tau: float) -> float:
    """QuantLib's bias, inverted for its internal ``lambda``.

    Its output form is ``(1 - e^{-lam}) (F + 1/tau)`` with ``F = (100-px)/100``,
    which the price sensitivity confirms; passing ``px=100`` sets ``F = 0``.
    """
    return -math.log1p(-ql.HullWhite.convexityBias(100.0, t1, t1 + tau, sigma, a) * tau)


def test_the_quantlib_oracle_is_calibrated_before_it_is_trusted():
    """What does QuantLib actually price? Answer it on a known case first.

    At ``a -> 0`` QuantLib is NOT Hull's ``1/2 sigma^2 T1 T2``: it is that plus
    ``1/2 sigma^2 tau^2 T1``, i.e. the term adjustment plus half the pre-``T1``
    compounding variance. Pinning this is what makes the next test an oracle
    rather than a coincidence.
    """
    t1, tau = 3.5, 0.25
    lam = _ql_lambda(SIGMA, 1e-9, t1, tau)
    hull = 0.5 * SIGMA ** 2 * t1 * (t1 + tau) * tau
    v_pre_over_2 = 0.5 * SIGMA ** 2 * tau ** 2 * t1
    assert lam == pytest.approx(hull + v_pre_over_2, rel=1e-5)
    assert lam > hull                      # and it is NOT the textbook number


@pytest.mark.parametrize("a", (1e-4, 0.001, 0.01, 0.03, 0.10, 0.25))
@pytest.mark.parametrize("t1", (0.25, 1.0, 3.5, 6.0))
def test_quantlib_equals_the_term_branch_plus_half_the_pre_t1_variance(a, t1):
    """An independent C++ implementation, matched to 1e-9.

    ``lam_QL = tau * CA_term + v_pre / 2`` where ``v_pre`` is the first term of
    :func:`compounding_var` -- diffusion accumulated before the accrual starts.
    This pins ``B``, ``B(0,T1)``, the term formula and the pre-``T1`` variance
    against code this repository did not write.
    """
    tau = 0.25
    t2 = t1 + tau
    v_pre = H.compounding_var(SIGMA, a, t1, t2) - SIGMA ** 2 * H._j2(a, tau)
    mine = tau * H.futures_ca(SIGMA, t1, t2, a, payoff="term") + 0.5 * v_pre
    assert mine == pytest.approx(_ql_lambda(SIGMA, a, t1, tau), rel=1e-9)


# ---------------------------------------------------------------------------
# 4. the a -> 0 limits, written from the papers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("t1", GRID_T1)
def test_term_payoff_reduces_to_hulls_textbook_number(t1):
    t2 = t1 + 0.25
    hull = 0.5 * SIGMA ** 2 * t1 * t2
    assert H.futures_ca(SIGMA, t1, t2, 0.0, payoff="term") == pytest.approx(hull, rel=1e-13)
    assert H.futures_ca(SIGMA, t1, t2, 1e-12, payoff="term") == pytest.approx(hull, rel=1e-9)


@pytest.mark.parametrize("t1", GRID_T1)
def test_average_payoff_reduces_to_T1_T2_plus_a_third_of_tau_squared(t1):
    t2 = t1 + 0.25
    want = 0.5 * SIGMA ** 2 * (t1 * t2 + 0.25 ** 2 / 3.0)
    assert H.futures_ca(SIGMA, t1, t2, 0.0, payoff="average") == pytest.approx(want, rel=1e-13)


@pytest.mark.parametrize("t1", GRID_T1)
def test_compounded_payoff_reduces_to_T2_squared_not_T1_squared(t1):
    """The headline: SR3 settles on the compounded rate, and its weight is T2^2.

    Exact at ``a = 0``, including the ``exp`` curvature -- the linear limit is
    ``mu + v/2`` and the branch returns ``expm1`` of it, so the identity is
    ``expm1(lin * tau) / tau`` and holds to machine precision, not to a
    tolerance that could hide a wrong term.
    """
    t2 = t1 + 0.25
    lin = H.holee_limit_ca(SIGMA, t1, t2)
    assert lin == pytest.approx(0.5 * SIGMA ** 2 * (t2 ** 2 - 0.25 ** 2 / 3.0), rel=1e-15)
    got = H.futures_ca(SIGMA, t1, t2, 0.0)
    assert got == pytest.approx(math.expm1(lin * 0.25) / 0.25, rel=1e-14)
    assert got == pytest.approx(lin, rel=1e-3)          # curvature is 1 + z/2


def test_the_three_payoffs_are_ordered_and_materially_apart():
    """compounded > average > term, and the spread is ~15% at the Blues point."""
    t1, t2 = 3.5, 3.75
    c = H.futures_ca_bp(100.0, t1, t2, 0.0)
    m = H.futures_ca_bp(100.0, t1, t2, 0.0, payoff="average")
    t = H.futures_ca_bp(100.0, t1, t2, 0.0, payoff="term")
    citi = holee_pack_ca_bp(100.0, [t1], convention="citi")
    assert c > m > t > citi
    assert (c - citi) / citi == pytest.approx(0.146, abs=0.01)
    assert c == pytest.approx(7.02, abs=0.01)
    assert t == pytest.approx(6.5625, abs=0.001)
    assert citi == pytest.approx(6.125, abs=0.001)


# ---------------------------------------------------------------------------
# 5. behaviour: mean reversion, volatility, packs, refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payoff", H.PAYOFFS)
def test_mean_reversion_damps_the_adjustment(payoff):
    t1, t2 = 3.5, 3.75
    vals = [H.futures_ca(SIGMA, t1, t2, a, payoff=payoff)
            for a in (0.0, 0.01, 0.03, 0.10, 0.30)]
    assert all(x > y for x, y in zip(vals, vals[1:])), vals
    assert vals[-1] < 0.6 * vals[0]        # and it is not a rounding-level effect


def test_the_adjustment_is_quadratic_in_volatility():
    t1, t2, a = 3.5, 3.75, 0.03
    one = H.futures_ca(SIGMA, t1, t2, a, payoff="term")
    two = H.futures_ca(2 * SIGMA, t1, t2, a, payoff="term")
    assert two == pytest.approx(4.0 * one, rel=1e-12)


def test_the_vol_mapping_is_the_identity_at_zero_mean_reversion():
    assert H.sigma_from_normal_vol(0.0095, 0.0, 3.5, 1.0) == 0.0095
    assert H.sigma_from_normal_vol_bp(95.0, 0.0, 3.5, 1.0) == pytest.approx(95.0)


@pytest.mark.parametrize("a", (0.001, 0.03, 0.15))
@pytest.mark.parametrize("tail", (0.25, 1.0, 5.0))
def test_the_vol_mapping_round_trips(a, tail):
    s = H.sigma_from_normal_vol(0.0095, a, 3.5, tail)
    assert H.normal_vol_from_sigma(s, a, 3.5, tail) == pytest.approx(0.0095, rel=1e-13)


def test_a_longer_tail_implies_a_LARGER_short_rate_vol():
    """``B(a, tail)/tail`` is the point of the mapping.

    A 5Y-tail swap rate moves less per unit of short-rate vol than a 3M one
    does, so reproducing the SAME quoted normal vol needs a larger sigma. The
    first version of this test asserted the opposite and passed against a
    mapping that was missing its ``/tail``.
    """
    a = 0.05
    s3m = H.sigma_from_normal_vol(0.0095, a, 3.5, 0.25)
    s1y = H.sigma_from_normal_vol(0.0095, a, 3.5, 1.0)
    s5y = H.sigma_from_normal_vol(0.0095, a, 3.5, 5.0)
    assert s5y > s1y > s3m > 0.0095


@pytest.mark.parametrize("tail", (0.25, 0.5, 1.0, 2.0, 5.0, 10.0))
def test_the_mapping_is_continuous_into_zero_mean_reversion_at_every_tail(tail):
    """The regression test for a mapping that is the identity ONLY at tail=1.

    Dropping the ``/tail`` leaves ``a = 0`` returning the quote and ``a = 1e-12``
    returning ``quote/tail`` -- a 4x step in sigma and 16x in the adjustment at
    a 3M tail, invisible to every 1Y-tail test. Continuity in ``a`` at a
    non-unit tail is the property that catches it.
    """
    at_zero = H.sigma_from_normal_vol(0.0095, 0.0, 3.5, tail)
    just_above = H.sigma_from_normal_vol(0.0095, 1e-12, 3.5, tail)
    assert at_zero == pytest.approx(0.0095, rel=1e-15)
    assert just_above == pytest.approx(at_zero, rel=1e-9)


def test_mean_reversion_nearly_cancels_once_the_vol_is_recalibrated():
    """Second order, and the sign flips -- worth pinning because it is a trap.

    At a FIXED short-rate vol, mean reversion damps the adjustment hard (-13%
    at ``a = 3%`` on a 4.6y contract). Recalibrated to the same ATM quote it
    raises sigma by nearly as much, and the net is +2.5%. So ``a`` is not the
    dial that explains a rich/cheap signal; the payoff convention (15%) is.
    """
    t1, t2, tail, quote = 4.6, 4.85, 1.0, 95.0
    fixed = [H.futures_ca_bp(quote, t1, t2, a) for a in (0.0, 0.03)]
    assert fixed[1] / fixed[0] == pytest.approx(0.869, abs=0.01)
    recal = [H.futures_ca_bp(H.sigma_from_normal_vol_bp(quote, a, t1, tail),
                             t1, t2, a) for a in (0.0, 0.03)]
    assert recal[1] / recal[0] == pytest.approx(1.025, abs=0.01)


def test_pack_is_the_mean_of_its_contracts_and_broadcasts_the_vol():
    t1s = [3.25, 3.5, 3.75, 4.0]
    t2s = [t + 0.25 for t in t1s]
    a = 0.03
    each = [H.futures_ca_bp(95.0, t1, t2, a) for t1, t2 in zip(t1s, t2s)]
    assert H.pack_ca_bp(95.0, t1s, t2s, a) == pytest.approx(float(np.mean(each)))
    per = [95.0, 96.0, 97.0, 98.0]
    each2 = [H.futures_ca_bp(s, t1, t2, a) for s, t1, t2 in zip(per, t1s, t2s)]
    assert H.pack_ca_bp(per, t1s, t2s, a) == pytest.approx(float(np.mean(each2)))
    assert H.pack_ca_bp(per, t1s, t2s, a) != pytest.approx(H.pack_ca_bp(95.0, t1s, t2s, a))


def test_the_forward_discount_factor_scales_the_compounded_branch():
    t1, t2, a = 3.5, 3.75, 0.03
    plain = H.futures_ca(SIGMA, t1, t2, a)
    d = math.exp(-0.04 * 0.25)
    assert H.futures_ca(SIGMA, t1, t2, a, fwd_discount=d) == pytest.approx(plain / d)
    assert H.futures_ca(SIGMA, t1, t2, a, fwd_discount=d) > plain      # 1/D > 1


def test_bad_inputs_raise_rather_than_returning_a_plausible_number():
    with pytest.raises(ValueError, match="payoff"):
        H.futures_ca(SIGMA, 3.5, 3.75, 0.03, payoff="libor")
    with pytest.raises(ValueError, match="t2 must exceed t1"):
        H.futures_ca(SIGMA, 3.75, 3.75, 0.03)
    with pytest.raises(ValueError, match="mean reversion"):
        H.futures_ca(SIGMA, 3.5, 3.75, -0.01)
    with pytest.raises(ValueError, match="t1 must be non-negative"):
        H.futures_ca(SIGMA, -0.1, 0.15, 0.03)
    with pytest.raises(ValueError, match="expiry must be positive"):
        H.sigma_from_normal_vol(0.0095, 0.03, 0.0, 1.0)
    with pytest.raises(ValueError, match="no contracts"):
        H.pack_ca_bp(95.0, [], [], 0.03)
    with pytest.raises(ValueError, match="length mismatch"):
        H.pack_ca_bp(95.0, [3.5, 3.75], [3.75], 0.03)


def test_the_accrual_is_not_hard_coded_at_a_quarter():
    """IMM-to-IMM runs 0.244-0.255 ACT/365 and the weight is quadratic in it."""
    a = 0.03
    short = H.futures_ca_bp(95.0, 3.5, 3.5 + 0.2493, a)
    long_ = H.futures_ca_bp(95.0, 3.5, 3.5 + 0.2548, a)
    assert long_ > short
    # 0.28%: the weight is quadratic in T2, so a 2.2% spread in the accrual is
    # 2 * 0.0055 / 3.75 on the level -- small, but larger than the 1e-4 bp the
    # cache round-trips to.
    assert (long_ - short) / short == pytest.approx(0.0028, abs=0.0005)
