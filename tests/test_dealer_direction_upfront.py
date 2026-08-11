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
