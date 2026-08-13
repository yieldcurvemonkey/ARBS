"""The upfront rule, pinned -- including the one place its sign inverts.

Three things are pinned here, in descending order of how badly a mistake would
hurt:

1. **The flow sign, against the frozen predecessor.** ``stir_flow/classifier.py``
   already implements the identified rule; the new module generalises it and
   must reproduce it on every case it covers.
2. **The termination inversion.** At inception the party *taking* the ITM side
   pays the fee; at tear-up the party *giving up* the ITM position receives it.
   So ``dealer holds ITM <=> U < |f|`` for flow and ``<=> U > |f|`` for a
   termination -- the same ``(U, f)`` gives opposite answers. A worked example
   is encoded rather than the algebra, because the algebra is what got this
   wrong in the brief.
3. **That a near-mid print with a large fee does not score as confident.** The
   rule's sign is carried by ``sign(mid - R)``, which is a coin flip inside the
   mid's own measurement error while ``|edge|`` is large -- exactly the shape of
   confident nonsense the dead-zone discussion exists to prevent.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import upfront as up
from SDRUtils.stir_flow import classifier as frozen
from SDRUtils.stir_flow import config as stir_config
from SDRUtils.stir_flow.pricing import LegPricing
from SDRUtils.stir_flow.trade_selection import Unit as FrozenUnit


PV01 = 10_000.0          # $/bp -- a ~$100mm 10y, so 1 bp of edge is $10k


def _frozen_call(npv_pay: float, upfront: float, pv01: float = PV01):
    """Run the frozen off-market branch of ``classifier.classify_unit``."""
    legs = pd.DataFrame([{
        "trade_id": "T1",
        "pkg_ptp": None,
        "other_payment_ufro": upfront,
        "fixed_rate": 0.03,
    }])
    unit = FrozenUnit("T1", "OUTRIGHT", legs, None, is_off_market=True)
    return frozen.classify_unit(
        unit, [LegPricing(mid_pct=3.0, npv_pay=npv_pay, pv01=pv01)],
    )


# --------------------------------------------------------------------------
# 1. The flow rule reproduces the frozen classifier.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("npv_pay", [-500_000.0, -60_000.0, -1_000.0,
                                     1_000.0, 60_000.0, 500_000.0])
@pytest.mark.parametrize("upfront", [1_500.0, 40_000.0, 400_000.0])  # never |npv|
def test_flow_sign_matches_frozen_classifier(npv_pay, upfront):
    """The generalisation must not move a single call on the frozen grid.

    `stir_flow/classifier.py:77-80` is the identified formulation
    (`dealer_bought = upfront < abs(npv_pay)`, ITM side = pay-fixed when
    `npv_pay > 0`). This package's job on flow prints is to put a probability
    on it, not to change it.
    """
    expected = {"RECEIVED": conv.DEALER_RECEIVED,
                "PAID": conv.DEALER_PAID}[_frozen_call(npv_pay, upfront).dealer_direction]

    call = up.classify(npv_pay=npv_pay, upfront=upfront, structure_dv01=PV01)

    assert call.dealer_sign == expected


@pytest.mark.parametrize("npv_pay", [-500_000.0, 60_000.0])
def test_residual_reproduces_the_frozen_dealer_charge(npv_pay):
    """``|residual_bps|`` is the frozen ``dealer_charge_bps``, to the float."""
    res = _frozen_call(npv_pay, upfront=40_000.0)

    call = up.classify(npv_pay=npv_pay, upfront=40_000.0, structure_dv01=PV01)

    assert abs(call.residual_bps) == pytest.approx(res.dealer_charge_bps)


def test_exact_tie_is_no_call_where_the_frozen_rule_picks_a_side():
    """The one deliberate deviation from the predecessor, same as `dealer_side`.

    `classifier.py` ends `dealer_direction = itm_side if dealer_bought else
    other` off a strict `<`, so ``U == |f|`` -- zero edge, no information --
    silently gets a side. `conventions.dealer_side` already established the
    zero branch; this rule inherits it.
    """
    res = _frozen_call(npv_pay=-40_000.0, upfront=40_000.0)
    assert res.dealer_direction in ("PAID", "RECEIVED")

    call = up.classify(npv_pay=-40_000.0, upfront=40_000.0, structure_dv01=PV01)

    assert call.dealer_sign == 0
    assert call.edge_bps == 0.0


def test_zero_npv_is_no_call_however_large_the_fee():
    """At `f == 0` the ITM side is undefined, so the fee cannot orient anything."""
    call = up.classify(npv_pay=0.0, upfront=250_000.0, structure_dv01=PV01)

    assert call.dealer_sign == 0


# --------------------------------------------------------------------------
# 2. The termination inversion.
# --------------------------------------------------------------------------

def test_termination_inverts_the_flow_sign_on_the_same_inputs():
    """Same `(U, f)`, opposite answer. This is the finding, in one assert."""
    for npv_pay in (-250_000.0, -10_000.0, 10_000.0, 250_000.0):
        for upfront in (5_000.0, 100_000.0):
            flow = up.classify(npv_pay=npv_pay, upfront=upfront,
                               structure_dv01=PV01)
            term = up.classify(npv_pay=npv_pay, upfront=upfront,
                               structure_dv01=PV01, is_lifecycle=True)
            assert term.dealer_sign == -flow.dealer_sign
            assert term.edge_bps == pytest.approx(-flow.edge_bps)


def test_worked_termination_example():
    """A customer unwinding an in-the-money payer, priced by hand.

    Customer paid fixed at 3.00% for 10y; mid is now 4.00%, so the customer's
    payer position is worth ``f = (mid - R)*A > 0`` and the dealer -- who
    received fixed at 3% -- is the out-of-the-money side. The dealer pays the
    customer to tear it up, and pays slightly *less* than the position is
    worth: ``U < |f|``. So ``U < |f|`` on a termination means the dealer held
    the side that was OUT of the money, which is the receive side here.

    Under the *flow* rule the same numbers would say the dealer held the ITM
    side and therefore PAID fixed -- the exact inversion.
    """
    f = 100.0 * PV01                       # 100 bp in the money to the payer
    u = f - 0.6 * PV01                     # dealer keeps 0.6 bp of the unwind

    term = up.classify(npv_pay=f, upfront=u, structure_dv01=PV01,
                       is_lifecycle=True)

    assert term.dealer_sign == conv.DEALER_RECEIVED
    assert term.edge_bps == pytest.approx(0.6)
    assert up.classify(npv_pay=f, upfront=u,
                       structure_dv01=PV01).dealer_sign == conv.DEALER_PAID


def test_lifecycle_sign_is_the_side_held_on_the_dying_swap():
    """Named, because it is a half-flip waiting to happen.

    ``dealer_sign`` on a lifecycle row is the side the dealer held on the swap
    being torn up -- NOT the risk direction of the tear-up, which is its
    negation (unwinding a received-fixed position sheds duration). The module
    must say so, and a consumer that wants flow must negate.
    """
    assert up.LIFECYCLE_SIGN_MEANS_SIDE_HELD is True
    assert "negate" in up.classify.__doc__.lower()


# --------------------------------------------------------------------------
# 3. Probability: the logistic, and the near-mid trap.
# --------------------------------------------------------------------------

def test_p_and_signed_weight_follow_the_edge():
    call = up.classify(npv_pay=-100_000.0, upfront=40_000.0,
                       structure_dv01=PV01, tau=up.TauUpfront(
                           tau_bps=0.5, bias_bps=0.0, half_spread_bps=1.0,
                           sigma_bps=1.0, n=100, bucket="TEST",
                           population=up.POPULATION_FLOW))

    assert call.edge_bps == pytest.approx(6.0)          # (10 - 4) bp
    assert call.p == pytest.approx(1.0 / (1.0 + math.exp(-12.0)))
    assert call.p > 0.5 and call.dealer_sign == conv.DEALER_RECEIVED
    assert call.signed_weight == pytest.approx(conv.signed_weight(call.p))


def test_near_mid_print_with_a_big_fee_is_not_confident():
    """The 275k-leg trap: the fee is large, so the *edge* is large, but the
    SIGN is carried by a 0.01 bp deviation inside a 0.2 bp measurement error.

    A bare logistic reports certainty. Marginalising over the mid error
    collapses it to a coin flip, which is what the print actually is.
    """
    tau = up.TauUpfront(tau_bps=0.5, bias_bps=0.0, half_spread_bps=1.0,
                        sigma_bps=1.0, n=100, bucket="TEST",
                        population=up.POPULATION_FLOW)
    # dev = +0.01 bp above mid, fee = 5 bp
    npv_pay = -0.01 * PV01

    naive = up.classify(npv_pay=npv_pay, upfront=5.0 * PV01,
                        structure_dv01=PV01, tau=tau)
    marginal = up.classify(npv_pay=npv_pay, upfront=5.0 * PV01,
                           structure_dv01=PV01, tau=tau, mid_sigma_bps=0.2)

    assert naive.p < 0.001                                   # confident nonsense
    assert marginal.p == pytest.approx(0.48, abs=0.03)       # a coin flip
    assert up.FLAG_SIGN_FRAGILE in marginal.flags
    assert up.FLAG_NO_MID_SIGMA in naive.flags


def test_marginalising_leaves_a_decisive_call_decisive():
    tau = up.TauUpfront(tau_bps=0.5, bias_bps=0.0, half_spread_bps=1.0,
                        sigma_bps=1.0, n=100, bucket="TEST",
                        population=up.POPULATION_FLOW)
    call = up.classify(npv_pay=-10.0 * PV01, upfront=2.0 * PV01,
                       structure_dv01=PV01, tau=tau, mid_sigma_bps=0.2)

    assert call.p > 0.999
    assert up.FLAG_SIGN_FRAGILE not in call.flags


def test_lifecycle_gets_no_probability_from_a_flow_tau():
    """A 20-year seasoned unwind is 100 bp from mid and would score as maximal
    confidence for the wrong reason, so the flow calibration must not reach it.
    """
    flow_tau = up.TauUpfront(tau_bps=0.5, bias_bps=0.0, half_spread_bps=1.0,
                             sigma_bps=1.0, n=100, bucket="TEST",
                             population=up.POPULATION_FLOW)

    with pytest.raises(ValueError, match="population"):
        up.classify(npv_pay=1e6, upfront=9e5, structure_dv01=PV01,
                    is_lifecycle=True, tau=flow_tau)

    call = up.classify(npv_pay=1e6, upfront=9e5, structure_dv01=PV01,
                       is_lifecycle=True)
    assert call.dealer_sign != 0
    assert call.p is None and call.signed_weight is None


# --------------------------------------------------------------------------
# 4. tau_upfront: fitted by probability.py's fitter, never a second copy.
# --------------------------------------------------------------------------

def test_tau_comes_from_the_injected_mixture_fitter():
    """`tau = s^2 / (2h)` -- DESIGN 1.1, and the fitter is imported not copied."""
    seen = {}

    def fake_fit(x):
        seen["n"] = len(x)
        return {"b0": 0.05, "h": 0.8, "s": 0.4}

    tau = up.fit_tau_upfront([0.1, -0.2, 0.3], population=up.POPULATION_FLOW,
                             bucket="2-5Y", mixture_fit=fake_fit)

    assert seen["n"] == 3
    assert tau.tau_bps == pytest.approx(0.4 ** 2 / (2 * 0.8))
    assert tau.bias_bps == pytest.approx(0.05)
    assert tau.population == up.POPULATION_FLOW
    assert tau.bucket == "2-5Y"


def test_the_default_fitter_is_the_one_probability_py_ships():
    """Coordination, pinned: one estimator in the package, two statistics.

    ``fit_mixture`` takes a keyword-only ``bucket``, which is why the call is
    routed by introspection -- and why this test calls the real thing rather
    than a stand-in.
    """
    from SDRUtils.dealer_direction import probability

    assert up._resolve_mixture_fit() is probability.fit_mixture

    rng = np.random.default_rng(3)
    z = 0.8 * rng.choice([-1.0, 1.0], 4000) + 0.4 * rng.standard_normal(4000)

    tau = up.fit_tau_upfront(z, population=up.POPULATION_FLOW, bucket="TEST")

    assert tau.n == 4000
    assert tau.half_spread_bps == pytest.approx(0.8, rel=0.15)
    assert tau.tau_bps == pytest.approx(0.4 ** 2 / (2 * 0.8), rel=0.3)


def test_tau_fitter_absence_is_loud():
    """No silent local fit. If `probability.py`'s fitter cannot be found the
    caller has to know, because a quietly-substituted tau is invisible.
    """
    with pytest.raises(up.MixtureFitUnavailable) as exc:
        up.fit_tau_upfront([0.1, 0.2], population=up.POPULATION_FLOW,
                           mixture_fit=object())

    assert "probability" in str(exc.value)


def test_the_fitted_residual_is_direction_blind():
    """What the mixture is fitted on must not know the answer.

    ``z = (|f| - U)/DV01`` is identical for a print and its mirror image, which
    is precisely why the fitter can be pointed at it: the +-h mixture comes from
    the unobserved side, not from anything we put in.
    """
    a = up.classify(npv_pay=+80_000.0, upfront=30_000.0, structure_dv01=PV01)
    b = up.classify(npv_pay=-80_000.0, upfront=30_000.0, structure_dv01=PV01)

    assert a.residual_bps == pytest.approx(b.residual_bps)
    assert a.dealer_sign == -b.dealer_sign


# --------------------------------------------------------------------------
# 5. Which fee, and the two thresholds carried forward from `stir_flow`.
# --------------------------------------------------------------------------

def test_termination_reads_uwin_which_the_frozen_rule_ignores():
    """`classifier.py:64` reads only `other_payment_ufro`, so a termination --
    whose settlement fee is UWIN -- currently has nothing to compare against.
    """
    flow = up.resolve_upfront(None, ufros=[12_000.0], uwins=[999_000.0])
    assert flow.amount == pytest.approx(12_000.0)
    assert flow.source == up.SRC_UFRO

    term = up.resolve_upfront(None, ufros=[12_000.0], uwins=[999_000.0],
                              is_lifecycle=True)
    assert term.amount == pytest.approx(999_000.0)
    assert term.source == up.SRC_UWIN


def test_termination_falls_back_to_ufro_when_uwin_is_absent():
    term = up.resolve_upfront(None, ufros=[7_000.0], uwins=[0.0],
                              is_lifecycle=True)

    assert term.amount == pytest.approx(7_000.0)
    assert term.source == up.SRC_UFRO
    assert up.FLAG_LIFECYCLE_FEE_FALLBACK in term.flags


def test_sub_floor_ptp_is_a_notation_artefact_not_a_fee():
    """`PTP_USD_FLOOR` carried forward, not re-derived."""
    below = stir_config.PTP_USD_FLOOR - 1.0

    got = up.resolve_upfront(below, ufros=[25_000.0])

    assert got.source == up.SRC_UFRO
    assert got.amount == pytest.approx(25_000.0)


def test_ptp_ufro_disagreement_is_flagged_and_ptp_still_wins():
    """`PTP_UFRO_DISAGREE_RATIO` carried forward, same precedence as frozen."""
    got = up.resolve_upfront(100_000.0, ufros=[10_000.0])

    assert got.source == up.SRC_PTP
    assert got.amount == pytest.approx(100_000.0)
    assert up.FLAG_PTP_UFRO_DISAGREE in got.flags

    agree = up.resolve_upfront(12_000.0, ufros=[10_000.0])
    assert up.FLAG_PTP_UFRO_DISAGREE not in agree.flags


def test_no_fee_at_all_is_not_an_upfront_unit():
    got = up.resolve_upfront(None, ufros=[0.0, 0.0])

    assert got.amount is None and got.source is None


def test_tiny_fee_is_flagged_because_the_rule_degenerates_to_the_rate_rule():
    call = up.classify(npv_pay=-100_000.0, upfront=1.0, structure_dv01=PV01)

    assert up.FLAG_TINY_UPFRONT in call.flags


# --------------------------------------------------------------------------
# 6. The capped-print guard.
# --------------------------------------------------------------------------

def test_capped_units_are_kept_because_58_is_scaled_with_the_notional():
    """Capping understates notional 1.6-4.0x, and if #58 were left unscaled
    ``|f|`` would shrink while ``U`` did not, flipping ``U < |f|``
    deterministically. Measured instead: median ``|NPV|/U`` 1.004 on 952 capped
    prints against 1.000 on 979 uncapped, and 0.984-1.017 paired within
    (tenor band x cap vintage). So the guard stays available and stays off.
    """
    assert up.CAPPED_UPFRONT_IS_UNSCALED is False

    kept = up.classify(npv_pay=-100_000.0, upfront=40_000.0,
                       structure_dv01=PV01, is_capped=True)
    assert kept.exclusion is None and kept.dealer_sign == conv.DEALER_RECEIVED

    guarded = up.classify(npv_pay=-100_000.0, upfront=40_000.0,
                          structure_dv01=PV01, is_capped=True,
                          exclude_capped=True)
    assert guarded.exclusion == up.EXCL_CAPPED_UPFRONT
    assert guarded.p is None and guarded.dealer_sign == 0


def test_robust_tau_is_used_where_the_mixture_refuses():
    """Every measured bucket of ``z`` is leptokurtic, so this is the live path.

    The mixture must refuse rather than return ``h = 0`` silently, and the
    fallback must be visibly a fallback -- with ``h`` NaN, not zero, so nothing
    downstream can multiply by it.
    """
    z = [0.0, 0.1, -0.1, 0.2, -0.2, 5.0, -6.0]        # spike plus fat tails

    with pytest.raises(ValueError, match="tau = s"):
        up.fit_tau_upfront(z, population=up.POPULATION_FLOW,
                           mixture_fit=lambda x: (0.0, 0.0, 1.0))

    tau = up.robust_tau_upfront(z, population=up.POPULATION_FLOW, bucket="5-10Y")

    assert tau.fallback == "LEPTOKURTIC"
    assert math.isnan(tau.half_spread_bps)
    assert tau.tau_bps == pytest.approx(1.4826 * 0.2)   # median |z - 0| = 0.2
    assert up.classify(npv_pay=-1.0 * PV01, upfront=0.0, structure_dv01=PV01,
                       tau=tau).p > 0.5


def test_a_unit_with_no_fee_cannot_be_classified_by_this_rule():
    call = up.classify(npv_pay=-100_000.0, upfront=None, structure_dv01=PV01)

    assert call.exclusion == up.EXCL_NO_UPFRONT
    assert call.dealer_sign == 0


def test_zero_dv01_refuses_rather_than_dividing():
    with pytest.raises(ValueError, match="structure_dv01"):
        up.classify(npv_pay=-1.0, upfront=1.0, structure_dv01=0.0)


# --------------------------------------------------------------------------
# 7. The mid bias moves the mid, so it must move the ORIENTATION too.
# --------------------------------------------------------------------------

def _flow_tau(tau_bps=0.5, bias_bps=0.0):
    return up.TauUpfront(tau_bps=tau_bps, bias_bps=bias_bps, half_spread_bps=1.0,
                         sigma_bps=1.0, n=100, bucket="TEST",
                         population=up.POPULATION_FLOW)


@pytest.mark.parametrize("mid_bias", [-0.8, -0.5, -0.05, 0.0, 0.05, 0.5, 0.8])
@pytest.mark.parametrize("npv_pay", [-4_000.0, -2_000.0, -300.0,
                                     300.0, 2_000.0, 4_000.0])
@pytest.mark.parametrize("upfront", [0.0, 1_234.0, 6_789.0])
def test_a_mid_bias_is_exactly_a_shifted_mid(mid_bias, npv_pay, upfront):
    """``mid_bias_bps`` shifts the mid, so every output must move with it.

    A bucket mid-bias of ``b`` says the mid we priced against is ``b`` bp away
    from the true one, which is arithmetically identical to having repriced
    against the true mid: ``npv_pay -> npv_pay + b * DV01``. So the two calls
    below are the same print described two ways and every field has to match --
    including ``dealer_sign``, which is the field that reads the *side of mid*
    the print is on.

    The failure this catches: the deviation was bias-corrected while the
    orientation was still taken from the raw ``npv_pay``, so whenever the bias
    moved a print across mid (``|raw dev| < |b|`` -- precisely the near-mid
    population this rule exists for) ``dealer_sign`` pointed one way and ``p``
    the other, on the same row.

    The fees are 1,234 and 6,789 rather than round numbers so that no cell
    lands on ``|dev| == U/DV01`` exactly: the two subtraction orders agree to
    1e-16 there but ``dealer_side`` is a discontinuous function of that, so an
    exact tie would compare one arm's ``+0.0`` against the other's ``-3e-17``
    and fail on float noise rather than on the invariant.
    """
    tau = _flow_tau()
    biased = up.classify(npv_pay=npv_pay, upfront=upfront, structure_dv01=PV01,
                         mid_bias_bps=mid_bias, tau=tau, mid_sigma_bps=0.05)
    repriced = up.classify(npv_pay=npv_pay + mid_bias * PV01, upfront=upfront,
                           structure_dv01=PV01, tau=tau, mid_sigma_bps=0.05)

    assert biased.dev_bps == pytest.approx(repriced.dev_bps, abs=1e-12)
    assert biased.residual_bps == pytest.approx(repriced.residual_bps, abs=1e-12)
    assert biased.edge_bps == pytest.approx(repriced.edge_bps, abs=1e-12)
    assert biased.dealer_sign == repriced.dealer_sign
    assert biased.p == pytest.approx(repriced.p, abs=1e-12)
    assert biased.signed_weight == pytest.approx(repriced.signed_weight, abs=1e-12)
    assert biased.flags == repriced.flags


def test_the_measured_cross_mid_case_agrees_with_itself():
    """The live measurement: a +0.20 bp print with a +0.5 bp bucket bias.

    The true deviation is -0.30 bp -- printed BELOW mid -- so with no fee the
    dealer holds the in-the-money PAY side and the call is ``DEALER_PAID``.
    ``dealer_sign``, ``p`` and ``signed_weight`` are three renderings of one
    answer and a consumer may build the ladder from any of them, so a row where
    they disagree is a ladder that points the opposite way depending on which
    column was read.
    """
    call = up.classify(npv_pay=-2_000.0, upfront=0.0, structure_dv01=PV01,
                       mid_bias_bps=0.5, tau=_flow_tau(), mid_sigma_bps=0.05)

    assert call.dev_bps == pytest.approx(-0.30)
    assert call.mid_bias_bps == 0.5          # the one input that was not recorded
    assert call.dealer_sign == conv.DEALER_PAID
    assert call.edge_bps == pytest.approx(-0.30)
    assert call.p < 0.5
    assert call.signed_weight < 0


# --------------------------------------------------------------------------
# 8. The marginalisation integrates the integrand it actually has.
# --------------------------------------------------------------------------

def _direct_integral(dev, u_bps, tau_bps, s, bias=0.0, is_lifecycle=False):
    """``p`` by brute force, with the grid SPLIT at the kink at ``d = 0``.

    The edge jumps by ``2(u + b0)`` there, so a single grid laid across it is
    itself wrong -- which is the finding. Two trapezoid grids, one per smooth
    branch, +-12 sigma (truncated mass 4e-33).
    """
    c = u_bps + bias
    lo, hi = dev - 12.0 * s, dev + 12.0 * s
    total = 0.0
    for a, b, branch in ((lo, min(hi, 0.0), +1.0), (max(lo, 0.0), hi, -1.0)):
        if b <= a:
            continue
        x = np.linspace(a, b, 40001)
        e = x + branch * c
        if is_lifecycle:
            e = -e
        w = np.exp(-0.5 * ((x - dev) / s) ** 2) / (s * math.sqrt(2.0 * math.pi))
        total += float(np.trapezoid(
            w / (1.0 + np.exp(-np.clip(e / tau_bps, -500.0, 500.0))), x))
    return total


@pytest.mark.parametrize("dev", [-1.0, -0.35, -0.18, -0.05, -0.004, 0.0,
                                 0.004, 0.05, 0.18, 0.35, 1.0, 8.0])
@pytest.mark.parametrize("u_bps,tau_bps,s", [(2.0, 3.816, 0.2543),
                                             (5.0, 3.816, 0.2543),
                                             (5.0, 0.5, 0.2),
                                             (0.4, 3.816, 0.2543),
                                             # s/tau = 10, so the logistic
                                             # saturates INSIDE the domain and
                                             # the closed-form wing carries real
                                             # mass. Nothing in the measured
                                             # regime (s/tau ~ 0.07) reaches
                                             # this, so nothing tested it.
                                             (2.0, 0.2, 2.0)])
def test_marginalised_p_ties_out_to_a_direct_integral(dev, u_bps, tau_bps, s):
    """Gauss-Hermite is polynomial-exact against a Gaussian weight; the
    integrand here has a jump discontinuity at ``d = 0``, so the rule does not
    converge on it and more nodes do not help. Measured against this reference
    on the real 2,025-print flow sample: max ``|p error|`` 0.030, and 27 rows
    (1.3%) came back with ``signed_weight`` of the WRONG SIGN.
    """
    got = up.p_marginalised(dev, u_bps, tau_bps, mid_sigma_bps=s)

    assert got == pytest.approx(_direct_integral(dev, u_bps, tau_bps, s),
                                abs=1e-6)


def test_a_hair_above_mid_with_a_fee_does_not_get_a_positive_weight():
    """The wrong-sign case, in one line.

    A print 0.01 bp above mid carrying a 2 bp fee is *just* on the pay-fixed
    side of a mid known to 0.25 bp, so the honest answer leans -- weakly --
    towards the dealer having PAID. Quadrature that straddles the kink returned
    0.5006 here, i.e. a positive ``signed_weight``, and the error is a
    deterministic function of ``|dev|/s`` so it does not average out of a
    ladder.
    """
    p = up.p_marginalised(0.01, 2.0, 3.816, mid_sigma_bps=0.2543)

    # 0.4966015 from `scipy.integrate.quad` run separately on each branch.
    assert p == pytest.approx(0.4966015, abs=1e-6)
    assert conv.signed_weight(p) < 0


def test_marginalised_p_has_no_quadrature_staircase():
    """``p`` was a step function of ``dev`` with the steps at the node
    positions -- flat for 0.045 bp and then jumping 0.19. On one smooth branch
    of the true integrand ``p`` is strictly monotone in ``dev``, so any flat
    run or reversal is quadrature, not the model.
    """
    devs = np.linspace(0.005, 0.5, 200)
    ps = np.array([up.p_marginalised(d, 5.0, 3.816, mid_sigma_bps=0.2543)
                   for d in devs])

    assert (np.diff(ps) < 0).all()
    assert ps[0] - ps[-1] > 0.2          # and it moves, so this is not a flat line


def test_marginalisation_folds_the_tau_bias_into_the_fee():
    """``b0`` is a systematic offset in ``z``, so it enters the edge exactly
    where the fee does -- ``edge = sign(d) * (|d| - u - b0)``. Pinned as an
    identity because dropping ``b0`` here would leave every other test green.
    """
    with_bias = up.p_marginalised(0.3, 2.0, 3.816, mid_sigma_bps=0.2543,
                                  bias_bps=0.4)
    folded = up.p_marginalised(0.3, 2.4, 3.816, mid_sigma_bps=0.2543)

    assert with_bias == pytest.approx(folded, abs=1e-12)
    assert with_bias != pytest.approx(
        up.p_marginalised(0.3, 2.0, 3.816, mid_sigma_bps=0.2543), abs=1e-6)


def test_marginalised_p_refuses_a_non_finite_input():
    """A NaN deviation used to make every branch test false and return 0.0 --
    a perfectly valid-looking probability, and the most confident one there is.
    """
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            up.p_marginalised(bad, 2.0, 3.8, mid_sigma_bps=0.25)
        with pytest.raises(ValueError):
            up.p_marginalised(0.1, bad, 3.8, mid_sigma_bps=0.25)
    with pytest.raises(ValueError, match="tau"):
        up.p_marginalised(0.1, 2.0, 0.0, mid_sigma_bps=0.25)


# --------------------------------------------------------------------------
# 9. FLAG_SIGN_FRAGILE has to test the quantity the sign actually turns on.
# --------------------------------------------------------------------------

def test_the_fragile_flag_fires_when_the_fee_matches_the_deviation():
    """``dealer_sign = sign(dev) * sign(z)``, so the sign flips at
    ``dev in {-c, 0, +c}`` with ``c = u + b0``: the distance to 0 is ``|dev|``
    and the distance to ``+-c`` is ``|z|``. The flag tested only ``|dev|``.

    Measured on the 2,025-print flow sample with sigma = 0.254 bp: the old
    condition fired on 12.4% while a further 46.0% were unflagged with
    ``|z|`` inside ONE sigma (median ``|z|`` 0.090 bp). Those rows have a
    coin-flip sign and said nothing about it.
    """
    sigma = 0.2543
    # 2 bp from mid -- nowhere near it -- but the fee matches to 0.05 bp.
    fragile = up.classify(npv_pay=-2.0 * PV01, upfront=2.05 * PV01,
                          structure_dv01=PV01, mid_sigma_bps=sigma)

    assert fragile.residual_bps == pytest.approx(-0.05)
    assert up.FLAG_SIGN_FRAGILE in fragile.flags

    # and the near-mid case the flag already caught must keep firing
    near_mid = up.classify(npv_pay=-0.01 * PV01, upfront=5.0 * PV01,
                           structure_dv01=PV01, mid_sigma_bps=0.2)
    assert up.FLAG_SIGN_FRAGILE in near_mid.flags

    # a print that is far from mid AND far from its fee is not fragile
    clear = up.classify(npv_pay=-10.0 * PV01, upfront=2.0 * PV01,
                        structure_dv01=PV01, mid_sigma_bps=0.2)
    assert up.FLAG_SIGN_FRAGILE not in clear.flags


@pytest.mark.parametrize("sigma", [0.05, 0.2543, 1.0])
@pytest.mark.parametrize("tau_bps", [0.5, 3.816, 11.0])
@pytest.mark.parametrize("is_lifecycle", [False, True])
def test_the_sign_and_the_weight_only_disagree_where_the_flag_fires(
        sigma, tau_bps, is_lifecycle):
    """``dealer_sign`` and ``signed_weight`` are different estimators -- the
    point call and the posterior over the mid error -- so they may disagree.
    The contract is that they only do so on rows the module has already called
    fragile, because a consumer may build the ladder from either column.

    This is the invariant the mid-bias defect broke wholesale: it read the
    magnitude off the corrected deviation and the sign off the raw NPV, so a
    print 0.3 bp from mid -- nowhere near a boundary, flag silent -- came back
    ``dealer_sign = +1`` with ``signed_weight = -0.29``.
    """
    tau = up.TauUpfront(tau_bps=tau_bps, bias_bps=0.0, half_spread_bps=1.0,
                        sigma_bps=1.0, n=100, bucket="TEST",
                        population=(up.POPULATION_LIFECYCLE if is_lifecycle
                                    else up.POPULATION_FLOW))
    seen_disagreement = False
    for dev in np.linspace(-6.0, 6.0, 241):
        for u_bps in (0.0, 0.05, 0.2, 1.0, 5.0, 20.0):
            call = up.classify(npv_pay=-dev * PV01, upfront=u_bps * PV01,
                               structure_dv01=PV01, is_lifecycle=is_lifecycle,
                               tau=tau, mid_sigma_bps=sigma)
            if call.dealer_sign == 0 or call.signed_weight == 0.0:
                continue
            if np.sign(call.signed_weight) != call.dealer_sign:
                seen_disagreement = True
                assert up.FLAG_SIGN_FRAGILE in call.flags, (dev, u_bps, call)
                # and it is genuinely on a boundary, with room to spare
                assert min(abs(call.dev_bps),
                           abs(call.residual_bps)) <= 1.5 * sigma
    assert seen_disagreement           # or the assertions above are vacuous


# --------------------------------------------------------------------------
# 10. Degenerate inputs are refused rather than priced.
# --------------------------------------------------------------------------

def test_a_non_finite_npv_is_a_pricing_error_not_a_zero_call():
    """The finiteness guard covered the fee and not the NPV, so a failed
    repricing returned ``dealer_sign = 0`` with ``exclusion = None`` -- which
    reads downstream as a successfully classified unit that happened to tie,
    and lands in the coverage numerator.
    """
    for bad in (float("nan"), float("inf"), float("-inf")):
        call = up.classify(npv_pay=bad, upfront=40_000.0, structure_dv01=PV01,
                           tau=_flow_tau())

        assert call.exclusion == up.EXCL_PRICING_ERROR
        assert call.dealer_sign == 0
        assert call.p is None and call.signed_weight is None
        assert call.dev_bps is None and call.edge_bps is None


def test_a_negative_fee_is_refused():
    """``#58`` is disseminated as "any value greater than or equal to zero"
    (spec p.31), and the rule's whole derivation assumes ``U >= 0``. A negative
    would make ``z = |dev| - U`` LARGER, i.e. turn corrupt data into a more
    confident call, which is the one direction an error must never go.
    """
    with pytest.raises(ValueError, match="negative"):
        up.classify(npv_pay=-100_000.0, upfront=-40_000.0, structure_dv01=PV01)


def test_a_nan_in_the_fee_list_does_not_erase_the_fee():
    """``trade_selection.resolve_upfront`` sums ``u for u in legs if u`` -- a
    NaN is truthy, so one NaN leg poisons the sum to NaN and ``ufro_sum > 0``
    goes False, reporting a fee-bearing unit as having no fee at all. Both
    frozen call sites pass ``.fillna(0.0)``; this one takes a caller's list, so
    it has to do the same coercion itself.
    """
    got = up.resolve_upfront(None, ufros=[25_000.0, float("nan")])

    assert got.amount == pytest.approx(25_000.0)
    assert got.source == up.SRC_UFRO

    term = up.resolve_upfront(None, ufros=[7_000.0],
                              uwins=[5_000.0, float("nan")], is_lifecycle=True)
    assert term.amount == pytest.approx(5_000.0)
    assert term.source == up.SRC_UWIN


# --------------------------------------------------------------------------
# 11. The pieces no test reached: the tau bias, and a LIFECYCLE tau.
# --------------------------------------------------------------------------

def test_the_tau_bias_shifts_the_residual_and_the_edge():
    """``b0`` is the fitted systematic offset in ``z`` and it is subtracted
    from every residual. Nothing else in the suite ever supplies a non-zero
    one, so dropping it entirely left the suite green.
    """
    call = up.classify(npv_pay=-100_000.0, upfront=40_000.0,
                       structure_dv01=PV01, tau=_flow_tau(bias_bps=0.3))

    assert call.residual_bps == pytest.approx(10.0 - 4.0 - 0.3)
    assert call.edge_bps == pytest.approx(5.7)
    assert call.bias_bps == pytest.approx(0.3)


def test_residual_bps_honours_its_bias_argument():
    assert up.residual_bps(-100_000.0, 40_000.0, PV01,
                           bias_bps=0.3) == pytest.approx(5.7)
    assert up.signed_edge_bps(-100_000.0, 40_000.0, PV01,
                              bias_bps=0.3) == pytest.approx(5.7)


@pytest.mark.parametrize("is_lifecycle", [False, True])
@pytest.mark.parametrize("npv_pay", [-500_000.0, -40_000.0, -1_000.0, 0.0,
                                     1_000.0, 40_000.0, 500_000.0])
@pytest.mark.parametrize("upfront", [0.0, 40_000.0, 400_000.0])
def test_classify_and_the_public_signed_edge_are_one_rule(npv_pay, upfront,
                                                          is_lifecycle):
    """``classify`` orients off its own bias-corrected deviation and
    :func:`signed_edge_bps` orients off the raw NPV through
    :func:`orientation`. With no mid bias those are the same quantity, so the
    two must return the same number -- otherwise the module has two rules for
    one thing and a consumer's answer depends on which entry point it used.

    Pinned here specifically because ``classify`` stopped calling
    ``orientation`` when the mid-bias defect was fixed, which left
    ``orientation``'s lifecycle negation and its ``f == 0`` branch reachable
    only through this helper -- and both were then deletable with the suite
    green.
    """
    call = up.classify(npv_pay=npv_pay, upfront=upfront, structure_dv01=PV01,
                       is_lifecycle=is_lifecycle)
    direct = up.signed_edge_bps(npv_pay, upfront, PV01,
                                is_lifecycle=is_lifecycle)

    assert call.edge_bps == pytest.approx(direct, abs=1e-12)
    assert call.dealer_sign == conv.dealer_side(direct)


def test_a_non_finite_calibration_input_is_refused():
    """Same failure as a NaN NPV, one argument along: a NaN bias or sigma makes
    every deviation NaN, and with no ``tau`` that comes back as
    ``dealer_sign = 0`` with no exclusion -- an exact tie, apparently. These
    are calibration inputs rather than per-row data, so a non-finite one is a
    programming error and is raised rather than given an exclusion name.
    """
    with pytest.raises(ValueError, match="mid_bias_bps"):
        up.classify(npv_pay=-100_000.0, upfront=40_000.0, structure_dv01=PV01,
                    mid_bias_bps=float("nan"))

    with pytest.raises(ValueError, match="mid_sigma_bps"):
        up.classify(npv_pay=-100_000.0, upfront=40_000.0, structure_dv01=PV01,
                    mid_sigma_bps=float("nan"))


@pytest.mark.parametrize("mid_sigma", [None, 0.0, 0.2543])
def test_a_lifecycle_tau_mirrors_the_flow_probability(mid_sigma):
    """The termination inversion has to survive into ``p``, on all three
    probability paths -- the bare logistic, the ``s <= 0`` shortcut inside the
    marginalisation, and the marginalisation proper. No test built a
    ``POPULATION_LIFECYCLE`` tau at all, so both lifecycle negations in the
    probability path were deletable with the suite green.
    """
    flow_tau = _flow_tau(tau_bps=3.816, bias_bps=0.13)
    life_tau = dataclasses.replace(flow_tau, population=up.POPULATION_LIFECYCLE)

    flow = up.classify(npv_pay=-120_000.0, upfront=40_000.0,
                       structure_dv01=PV01, tau=flow_tau, mid_sigma_bps=mid_sigma)
    life = up.classify(npv_pay=-120_000.0, upfront=40_000.0,
                       structure_dv01=PV01, is_lifecycle=True, tau=life_tau,
                       mid_sigma_bps=mid_sigma)

    assert life.dealer_sign == -flow.dealer_sign != 0
    assert life.p == pytest.approx(1.0 - flow.p, abs=1e-12)
    assert life.signed_weight == pytest.approx(-flow.signed_weight, abs=1e-12)
    assert flow.p != pytest.approx(0.5, abs=1e-3)      # or the mirror is trivial


def test_a_lifecycle_marginalisation_is_the_flow_one_reflected():
    p_flow = up.p_marginalised(0.3, 2.0, 3.816, mid_sigma_bps=0.2543,
                               bias_bps=0.4)
    p_life = up.p_marginalised(0.3, 2.0, 3.816, mid_sigma_bps=0.2543,
                               bias_bps=0.4, is_lifecycle=True)

    assert p_life == pytest.approx(1.0 - p_flow, abs=1e-12)
    assert p_flow == pytest.approx(
        _direct_integral(0.3, 2.0, 3.816, 0.2543, bias=0.4), abs=1e-6)


def test_the_fitters_own_tau_wins_over_recomputing_it():
    """``probability.MixtureFit.tau`` floors ``h`` at ``MIN_SEPARATION * s``,
    which caps tau at the no-information limit. Recomputing ``s^2/(2h)`` here
    throws that floor away: on the measured flow bucket it is the difference
    between 3.8 bp and a tau fifteen times sharper, i.e. between ``p = 0.512``
    and a confident call on the same print.
    """
    class _Fit:
        b0, h, s, tau, flags = 0.0, 0.01, 0.4, 3.816, ()

    tau = up.fit_tau_upfront([0.1, -0.2, 0.3], population=up.POPULATION_FLOW,
                             mixture_fit=lambda x: _Fit())

    assert tau.tau_bps == pytest.approx(3.816)
    assert 0.4 ** 2 / (2 * 0.01) == pytest.approx(8.0)      # what it is NOT
