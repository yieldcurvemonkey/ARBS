"""``RULE_PACKAGE_PRICE`` -- orienting a ``PKG-N`` from its one package price.

The module under test recovers the 39.97% of tape DV01 currently thrown away as
``EXCL_UNORIENTABLE``. Everything it produces rests on one claim:

    the per-leg cash signs that reconcile the legs' ``other payment amount``
    with the package's ``package_transaction_price`` are the package's
    orientation, up to a global flip that the price-vs-model comparison then
    resolves.

That claim is testable on the cases where the answer is *already known* --
``CURVE`` and ``FLY``, whose base orientation ``conventions.base_orientation``
fixes by market convention, and ``OUTRIGHT``, which ``upfront.classify``
already answers. **Those known-answer tests are the point of this file**; if
they fail the ``PKG-N`` numbers mean nothing, and the task says to stop.

The three layers pinned here, in descending order of how badly a mistake hurts:

1. **Orientation** (``§2``). On a synthetic ``CURVE``/``FLY`` built from a
   worked example, the fee-derived orientation must equal
   ``conventions.base_orientation(kind, n, RULE_RATE)`` up to a global sign.
2. **Direction** (``§3``). With a cash term smaller than the package's own
   off-market value, the per-leg ``received_signs`` must equal what
   ``conventions.structure_price`` + ``conventions.dealer_side`` +
   ``conventions.dealer_received_signs`` give for the same unit -- exactly, on
   every case where both rules apply.
3. **Global-flip invariance** (``§4``). The answer must not depend on which of
   the two symmetric branches the sign solver happened to return. The solver is
   direction-blind *by symmetry* (``upfront.py`` says so in its docstring); that
   symmetry is the degree of freedom the price comparison consumes, so any
   dependence on it is a bug that would show up as a randomly inverted ladder.

Three sign factors multiply in ``received_signs = dealer_sign * s * sign(f)``.
``conventions.py``'s own docstring records that two of them cancelling is the
trap that inverted its first draft, so ``§7`` mutates each factor and asserts
the tests go red.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import package_price as pp
from SDRUtils.dealer_direction import upfront as up
from SDRUtils.stir_flow import config as stir_config


# --------------------------------------------------------------------------
# helpers -- a package expressed the way the tape expresses one
# --------------------------------------------------------------------------

def npv_pay(mid_pct: float, rate_pct: float, pv01: float) -> float:
    """``f`` -- the NPV to the fixed PAYER, in dollars.

    ``(mid - R) * 100 * PV01``: percent in, and the ``100`` is the same
    percent->bp boundary ``conventions.structure_price`` crosses.
    """
    return (float(mid_pct) - float(rate_pct)) * 100.0 * float(pv01)


def build(kind: str, mids, rates, pv01s, *, charge: float = 0.0,
          charge_leg: int = 0):
    """A synthetic package, oriented by market convention, with a dealer charge.

    Returns ``(opas, ptp, npvs, pv01s, orientation)``. The fees are constructed
    from the *physics* the module claims -- each leg's cash is the value that
    leg transfers, and it flows from the party receiving that value -- so the
    test does not merely re-run the module's own arithmetic.

    ``charge`` is added to the leg the base party pays cash on, so the base
    party ends up over-paying by exactly ``charge`` dollars and is therefore
    the customer.
    """
    n = len(mids)
    o = conv.base_orientation(kind, n, conv.RULE_RATE)
    f = [npv_pay(m, r, p) for m, r, p in zip(mids, rates, pv01s)]
    # a_i = +1 when the base party RECEIVES value on leg i and therefore pays
    # that leg's cash. This is the physical rule, written out rather than
    # imported from the module under test.
    a = [1 if o_i * f_i > 0 else -1 for o_i, f_i in zip(o, f)]
    opas = [abs(o_i * f_i) for o_i, f_i in zip(o, f)]
    paid = [i for i, ai in enumerate(a) if ai > 0]
    j = paid[charge_leg % len(paid)] if paid else 0
    opas[j] += float(charge)
    ptp = float(sum(ai * u for ai, u in zip(a, opas)))
    return opas, ptp, f, list(pv01s), o


CURVE_MIDS = (4.00, 4.20)
CURVE_RATES = (4.01, 4.215)
CURVE_PV01 = (10_000.0, 10_000.0)

FLY_MIDS = (4.00, 4.20, 4.30)
# The wings are 5 bp off mid, not 0.5 bp, and the reason is §9: a wing fee of
# 0.25 bp of the belly's DV01 makes the whole package UNIDENTIFIED -- flipping
# that wing's cash direction moves the reconciliation by 0.5 bp, which is
# inside the 1 bp of unexplained cash `TIEOUT_MAX_BPS` declares acceptable, so
# two orientations fit the price equally well and the module now refuses it.
# All three legs are struck BELOW mid so the fly still prices UP against mid
# (`-r0 + 2 r1 - r2` rises by 0.08), which is what keeps §3's agreement with
# the rate rule a live test rather than a sign coincidence.
FLY_RATES = (3.95, 4.19, 4.25)
FLY_PV01 = (5_000.0, 10_000.0, 5_000.0)


def _dv01(kind, pv01s):
    from SDRUtils.dealer_direction import midprice
    return midprice.structure_dv01(kind, pv01s)


def in_known_frame(call, known):
    """The call re-expressed against ``known`` rather than its own orientation.

    ``model_price``, ``reported_price``, ``deviation_*`` and ``dealer_sign``
    are all defined **relative to ``call.base_orientation``**, and that
    orientation is only fixed up to a global flip -- which branch comes back is
    ``opa_sign_solver``'s tie-break, a module this one does not own. Asserting
    those quantities' absolute signs would therefore pin an implementation
    detail of somebody else's tie-break, and a mutation that took the other
    branch would (and did) show up as a failure when the answer had not
    changed at all.

    So the tests state their expectations in the known market frame and this
    maps into it. ``received_signs`` is deliberately NOT touched: it is the
    orientation-free answer and must already be identical in both branches.
    """
    g = 1 if tuple(call.base_orientation) == tuple(known) else -1
    return dataclasses.replace(
        call,
        base_orientation=tuple(g * x for x in call.base_orientation),
        model_price=g * call.model_price,
        reported_price=g * call.reported_price,
        deviation_dollars=g * call.deviation_dollars,
        deviation_bps=g * call.deviation_bps,
        dealer_sign=g * call.dealer_sign,
    )


CURVE_FRAME = conv.base_orientation(conv.CURVE, 2, conv.RULE_RATE)


# --------------------------------------------------------------------------
# 1. the worked example itself -- pinned before anything reads it
# --------------------------------------------------------------------------

def test_worked_curve_example_is_what_the_docstring_says():
    """The fixture must be a real over-pay, or §2/§3 pin nothing."""
    opas, ptp, f, pv01s, o = build(conv.CURVE, CURVE_MIDS, CURVE_RATES,
                                   CURVE_PV01, charge=1_000.0)
    assert o == (-1, 1)
    assert f == pytest.approx([-10_000.0, -15_000.0])
    # base receives value on the front leg (it receives fixed above mid), so it
    # pays that cash; it gives up value on the back leg, so it receives cash.
    assert opas == pytest.approx([11_000.0, 15_000.0])
    assert ptp == pytest.approx(-4_000.0)


def test_worked_fly_example_is_what_the_docstring_says():
    opas, ptp, f, pv01s, o = build(conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01,
                                   charge=500.0)
    assert o == (-1, 1, -1)
    assert f == pytest.approx([25_000.0, 10_000.0, 25_000.0])
    # base receives fixed on the wings and pays on the belly; struck below mid
    # the wings are out of the money to it, so it RECEIVES their cash and pays
    # the belly's -- and the charge lands on the belly, the leg it pays.
    assert opas == pytest.approx([25_000.0, 10_500.0, 25_000.0])
    assert ptp == pytest.approx(-39_500.0)


# --------------------------------------------------------------------------
# 2. KNOWN ANSWER (i): the fee-derived orientation IS the market convention
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind,mids,rates,pv01s", [
    (conv.CURVE, CURVE_MIDS, CURVE_RATES, CURVE_PV01),
    (conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01),
])
def test_orientation_reproduces_market_convention(kind, mids, rates, pv01s):
    opas, ptp, f, pv01s, o = build(kind, mids, rates, pv01s, charge=1_000.0)
    call = pp.classify(opas=opas, package_price=ptp, npv_pays=f, pv01s=pv01s,
                       structure_dv01=_dv01(kind, pv01s))
    assert call.exclusion is None
    got = call.base_orientation
    assert got == o or got == tuple(-x for x in o), (
        f"fee-derived orientation {got} is neither {o} nor its complement; "
        "the package-price rule disagrees with the known quote convention"
    )


@pytest.mark.parametrize("kind,mids,rates,pv01s", [
    (conv.CURVE, CURVE_MIDS, CURVE_RATES, CURVE_PV01),
    (conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01),
])
def test_model_price_is_the_structure_price_deviation_in_dollars(
        kind, mids, rates, pv01s):
    """``reported - model`` with no charge is the rate rule's own deviation.

    ``-V = sum(o_i (R_i - M_i) * 100 * PV01_i)``, which for a package balanced
    in the quote ratio is ``(P_traded - P_mid)`` times the structure's price
    DV01. This is the identity that makes "the package price" the same object
    the rate rule compares, and it is checked in dollars because the bp
    denominator is a separate choice (``structure_dv01`` calls a fly's risk its
    belly, which is 2x the fly spread's own $/bp).
    """
    opas, ptp, f, pv01s, o = build(kind, mids, rates, pv01s, charge=0.0)
    call = in_known_frame(
        pp.classify(opas=opas, package_price=ptp, npv_pays=f, pv01s=pv01s,
                    structure_dv01=_dv01(kind, pv01s)), o)
    dev_bp = (conv.structure_price(rates, kind, len(rates), conv.RULE_RATE)
              - conv.structure_price(mids, kind, len(mids), conv.RULE_RATE))
    q = conv.quote_weights(kind, len(pv01s), conv.RULE_RATE)
    price_dv01 = sum(abs(w) * p for w, p in zip(q, pv01s)) / sum(w * w for w in q)
    # the base party's fair cash is the value of what it takes on
    assert -call.model_price == pytest.approx(dev_bp * price_dv01, rel=1e-9,
                                              abs=1e-6)


# --------------------------------------------------------------------------
# 3. KNOWN ANSWER (ii): the direction reproduces the rate rule
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind,mids,rates,pv01s", [
    (conv.CURVE, CURVE_MIDS, CURVE_RATES, CURVE_PV01),
    (conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01),
])
@pytest.mark.parametrize("charge", [1.0, 500.0, 1_000.0])
def test_received_signs_reproduce_the_rate_rule(kind, mids, rates, pv01s,
                                                charge):
    """Both rules apply; they must agree, per leg, exactly."""
    opas, ptp, f, pv01s_l, o = build(kind, mids, rates, pv01s, charge=charge)
    call = pp.classify(opas=opas, package_price=ptp, npv_pays=f,
                       pv01s=pv01s_l, structure_dv01=_dv01(kind, pv01s))
    dev_bp = (conv.structure_price(rates, kind, len(rates), conv.RULE_RATE)
              - conv.structure_price(mids, kind, len(mids), conv.RULE_RATE))
    want = conv.dealer_received_signs(kind, len(mids), conv.RULE_RATE,
                                      conv.dealer_side(dev_bp))
    assert call.received_signs == want


def test_the_two_rules_disagree_when_the_cash_dominates_and_that_is_correct():
    """A charge larger than the off-market value flips the answer, on purpose.

    The rate rule sees only ``P_traded - P_mid``; this rule sees that *plus*
    the cash. When the cash is the bigger term it is the cash that says who
    paid, and a test that demanded agreement everywhere would be pinning the
    rate rule's blind spot rather than this rule's correctness.
    """
    # rates struck BELOW mid so the base party is up on the swaps, then a cash
    # term big enough to more than take it back.
    mids, rates = (4.00, 4.20), (3.99, 4.185)
    opas, ptp, f, pv01s, o = build(conv.CURVE, mids, rates, CURVE_PV01,
                                   charge=50_000.0)
    call = in_known_frame(
        pp.classify(opas=opas, package_price=ptp, npv_pays=f, pv01s=pv01s,
                    structure_dv01=_dv01(conv.CURVE, CURVE_PV01)), o)
    dev_bp = (conv.structure_price(rates, conv.CURVE, 2, conv.RULE_RATE)
              - conv.structure_price(mids, conv.CURVE, 2, conv.RULE_RATE))
    rate_answer = conv.dealer_received_signs(conv.CURVE, 2, conv.RULE_RATE,
                                             conv.dealer_side(dev_bp))
    assert call.received_signs == tuple(-x for x in rate_answer)
    assert call.deviation_dollars == pytest.approx(50_000.0)


# --------------------------------------------------------------------------
# 4. KNOWN ANSWER (iii): the outright reproduces the frozen upfront rule
# --------------------------------------------------------------------------

@pytest.mark.parametrize("f", [-500_000.0, -60_000.0, -1_000.0,
                               1_000.0, 60_000.0, 500_000.0])
@pytest.mark.parametrize("u", [1_500.0, 40_000.0, 400_000.0])
@pytest.mark.parametrize("ptp_sign", [1.0, -1.0])
def test_outright_reproduces_upfront_rule(f, u, ptp_sign):
    """One leg, one fee -- the case ``upfront.classify`` already answers.

    ``dealer_sign`` is NOT compared: it is orientation-relative and the two
    rules use different base orientations (``upfront`` works in the all-pay
    frame, this rule in the fee-derived one). ``received_signs`` is the
    orientation-free answer and it must be identical.
    """
    pv01 = 10_000.0
    got = pp.classify(opas=[u], package_price=ptp_sign * u, npv_pays=[f],
                      pv01s=[pv01], structure_dv01=pv01)
    want = up.classify(npv_pay=f, upfront=u, structure_dv01=pv01)
    assert got.received_signs == (want.dealer_sign,)


@pytest.mark.parametrize("f,u", [(-60_000.0, 40_000.0), (60_000.0, 40_000.0),
                                 (-60_000.0, 90_000.0), (60_000.0, 90_000.0)])
def test_outright_lifecycle_inverts_with_the_upfront_rule(f, u):
    pv01 = 10_000.0
    got = pp.classify(opas=[u], package_price=u, npv_pays=[f], pv01s=[pv01],
                      structure_dv01=pv01, is_lifecycle=True)
    want = up.classify(npv_pay=f, upfront=u, structure_dv01=pv01,
                       is_lifecycle=True)
    assert got.received_signs == (want.dealer_sign,)


# --------------------------------------------------------------------------
# 4b. the THREE fields have to compose, and the lifecycle negation has to sit
#     in the same one `upfront.py` puts it in
# --------------------------------------------------------------------------
#
# `received_signs = dealer_sign * base_orientation` is what the dataclass says
# and what a consumer following the `krd` pattern computes for itself
# (`dealer_sign * received_hypothesis_signs(...)`). Comparing only
# `received_signs` against `upfront` -- which is all
# `test_outright_lifecycle_inverts_with_the_upfront_rule` above does -- cannot
# see the two fields disagreeing, and they did: the negation was applied to
# `received_signs` while `dealer_sign` was left alone, so every lifecycle
# package's key-rate profile came out inverted for anyone who composed it.

# A PKG-4 that is BOTH a real call (not an exact tie, so `dealer_sign != 0`)
# and identified (one sign class inside the tie-out gate, so §9's margin gate
# keeps it). The fees are spread so the runner-up sign class is 10 bp of the
# unit's DV01 away; `test_the_pkg4_fixture_is_a_real_call_and_identified` pins
# both properties so a later change to the numbers cannot quietly turn this
# into a fixture that passes for the wrong reason.
PKG4_OPAS = (10_000.0, 21_000.0, 43_000.0, 87_000.0)
PKG4_PTP = -55_000.0
PKG4_NPVS = (-1_000.0, -1_500.0, 600.0, 400.0)
PKG4_PV01 = (1_000.0, 1_000.0, 1_000.0, 1_000.0)
PKG4_DV01 = 2_000.0


def _pkg4(**kw):
    args = dict(opas=list(PKG4_OPAS), package_price=PKG4_PTP,
                npv_pays=list(PKG4_NPVS), pv01s=list(PKG4_PV01),
                structure_dv01=PKG4_DV01)
    args.update(kw)
    return pp.classify(**args)


@pytest.mark.parametrize("is_lifecycle", [False, True])
@pytest.mark.parametrize("kind,mids,rates,pv01s", [
    (conv.CURVE, CURVE_MIDS, CURVE_RATES, CURVE_PV01),
    (conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01),
])
def test_received_signs_is_the_composition_of_the_two_fields_it_claims(
        kind, mids, rates, pv01s, is_lifecycle):
    """The pinned identity, on the composition rather than on either field.

    A consumer of a ``RULE_PACKAGE_PRICE`` call is told to read
    ``package_price.received_hypothesis_signs`` and multiply by the call's
    ``dealer_sign`` -- that is the ``krd`` seam's shape. So THAT product is what
    has to equal ``received_signs``, whichever field the lifecycle negation
    lands in.
    """
    opas, ptp, f, pv01s_l, _ = build(kind, mids, rates, pv01s, charge=1_000.0)
    call = pp.classify(opas=opas, package_price=ptp, npv_pays=f,
                       pv01s=pv01s_l, structure_dv01=_dv01(kind, pv01s),
                       is_lifecycle=is_lifecycle)
    assert call.exclusion is None and call.dealer_sign != 0
    composed = tuple(call.dealer_sign * s
                     for s in pp.received_hypothesis_signs(call))
    assert call.received_signs == composed, (
        f"received_signs {call.received_signs} is not dealer_sign "
        f"{call.dealer_sign} times the hypothesis signs "
        f"{pp.received_hypothesis_signs(call)}; a consumer composing them "
        "gets the whole package's key-rate profile the wrong way round")


@pytest.mark.parametrize("is_lifecycle", [False, True])
def test_the_composition_holds_on_a_pkg4_too(is_lifecycle):
    call = _pkg4(is_lifecycle=is_lifecycle)
    assert call.exclusion is None and call.dealer_sign != 0
    assert call.received_signs == tuple(
        call.dealer_sign * s for s in pp.received_hypothesis_signs(call))


@pytest.mark.parametrize("f,u", [(-60_000.0, 40_000.0), (60_000.0, 40_000.0),
                                 (-60_000.0, 90_000.0), (60_000.0, 90_000.0)])
def test_the_lifecycle_negation_sits_in_dealer_sign_like_the_upfront_rule(f, u):
    """``upfront.py`` negates ``edge`` before ``dealer_side``, so its
    ``dealer_sign`` flips on a lifecycle row. Both rules feed one pooled
    population, so the negation cannot sit in a different field here --
    ``base_orientation`` is a property of the package, not of the print, and it
    must NOT move.
    """
    pv01 = 10_000.0
    flow = pp.classify(opas=[u], package_price=u, npv_pays=[f], pv01s=[pv01],
                       structure_dv01=pv01)
    life = pp.classify(opas=[u], package_price=u, npv_pays=[f], pv01s=[pv01],
                       structure_dv01=pv01, is_lifecycle=True)
    up_flow = up.classify(npv_pay=f, upfront=u, structure_dv01=pv01)
    up_life = up.classify(npv_pay=f, upfront=u, structure_dv01=pv01,
                          is_lifecycle=True)
    assert up_life.dealer_sign == -up_flow.dealer_sign     # the frozen rule
    assert life.base_orientation == flow.base_orientation
    assert life.dealer_sign == -flow.dealer_sign
    assert life.received_signs == tuple(-r for r in flow.received_signs)


# --------------------------------------------------------------------------
# 5. the global flip must not reach the answer
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind,mids,rates,pv01s", [
    (conv.CURVE, CURVE_MIDS, CURVE_RATES, CURVE_PV01),
    (conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01),
])
def test_negating_the_package_price_leaves_the_answer_unchanged(
        kind, mids, rates, pv01s):
    """``s -> -s`` flips the orientation AND the deviation; the product is fixed.

    The solver scores a sign vector and its complement identically, so which
    one comes back is a tie-break detail. If that detail reached
    ``received_signs`` the ladder would invert at random.
    """
    opas, ptp, f, pv01s_l, _ = build(kind, mids, rates, pv01s, charge=1_000.0)
    a = pp.classify(opas=opas, package_price=ptp, npv_pays=f, pv01s=pv01s_l,
                    structure_dv01=_dv01(kind, pv01s))
    b = pp.classify(opas=opas, package_price=-ptp, npv_pays=f, pv01s=pv01s_l,
                    structure_dv01=_dv01(kind, pv01s))
    assert a.received_signs == b.received_signs
    assert a.base_orientation == tuple(-x for x in b.base_orientation)
    assert a.deviation_dollars == pytest.approx(-b.deviation_dollars)


def test_a_leg_permutation_permutes_the_answer_and_nothing_else():
    opas, ptp, f, pv01s, o = build(conv.FLY, FLY_MIDS, FLY_RATES, FLY_PV01,
                                   charge=800.0)
    perm = [2, 0, 1]
    a = pp.classify(opas=opas, package_price=ptp, npv_pays=f, pv01s=pv01s,
                    structure_dv01=_dv01(conv.FLY, FLY_PV01))
    b = pp.classify(opas=[opas[i] for i in perm], package_price=ptp,
                    npv_pays=[f[i] for i in perm],
                    pv01s=[pv01s[i] for i in perm],
                    structure_dv01=_dv01(conv.FLY, FLY_PV01))
    assert b.received_signs == tuple(a.received_signs[i] for i in perm)
    assert b.deviation_dollars == pytest.approx(a.deviation_dollars)


# --------------------------------------------------------------------------
# 6. the gates -- every refusal has a name, and the constants are carried
# --------------------------------------------------------------------------

def test_floor_and_disagree_ratio_come_from_the_frozen_config():
    assert pp.PTP_USD_FLOOR == stir_config.PTP_USD_FLOOR == 500.0
    assert (pp.PTP_UFRO_DISAGREE_RATIO
            == stir_config.PTP_UFRO_DISAGREE_RATIO == 2.0)


@pytest.mark.parametrize("ptp", [None, float("nan"), 0.0, 499.0, -499.0])
def test_sub_floor_package_price_is_refused_by_name(ptp):
    """A sub-floor PTP is a notation artefact, not dollars. Named, not guessed."""
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=ptp,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_NO_PACKAGE_PRICE
    assert call.received_signs is None


def test_the_notation_3_sentinel_is_below_the_floor():
    """``9.9999999999`` with notation 3 is the spec's not-available sentinel.

    It is the modal ``package_transaction_price`` on notation-3 ``PKG-4+``
    packages, and the floor is what keeps it out -- no notation column is read.
    """
    call = pp.classify(opas=[10_000.0], package_price=9.9999999999,
                       npv_pays=[-10_000.0], pv01s=[10_000.0],
                       structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_NO_PACKAGE_PRICE


def test_a_leg_with_no_reported_cash_is_refused_by_name():
    call = pp.classify(opas=[10_000.0, None], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_OPA_MISSING


def test_a_package_whose_cash_does_not_reconcile_is_refused_by_name():
    """No sign vector gets near the price -> the orientation is a guess."""
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=9_000_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_TIEOUT_FAIL
    assert call.tieout_bps is not None and call.tieout_bps > pp.TIEOUT_MAX_BPS


def test_a_reconciling_package_is_not_refused():
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion is None
    assert call.tieout_bps == pytest.approx(0.1)   # $1,000 on $10,000/bp


@pytest.mark.parametrize("npvs", [[0.0, -15_000.0], [-10_000.0, 0.0]])
def test_a_leg_exactly_at_mid_cannot_be_oriented_and_says_so(npvs):
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=npvs, pv01s=[10_000.0, 10_000.0],
                       structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_LEG_AT_MID


def test_a_leg_inside_the_mid_resolution_is_flagged_not_refused():
    """Near-mid is a confidence problem, not an eligibility one.

    The two legs carry DIFFERENT PV01 on purpose: with equal PV01 the reported
    ``unresolved_pv01`` is the same number whichever leg was flagged, so the
    test cannot tell the comparison from its inverse. (It could not, until a
    mutation that flipped ``<`` to ``>`` survived.)

    The near-mid leg's **fee** is large ($40k) while its **NPV** is $10. Those
    are two different quantities and only the second one is what "near mid"
    means; a fixture that made both small would be refused by §9's
    identification gate and would stop testing this at all.
    """
    # leg 0 is 0.001 bp from mid: |f| = 0.001 * 10_000 = $10
    call = pp.classify(opas=[40_000.0, 60_000.0], package_price=-20_000.0,
                       npv_pays=[-10.0, -15_000.0],
                       pv01s=[10_000.0, 20_000.0], structure_dv01=15_000.0,
                       leg_sign_resolution_bps=0.25)
    assert call.exclusion is None
    assert pp.FLAG_LEG_NEAR_MID in call.flags
    assert call.unresolved_pv01 == pytest.approx(10_000.0)   # leg 0, not leg 1


def test_a_package_with_no_near_mid_leg_carries_no_flag_and_no_unresolved_pv01():
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 20_000.0], structure_dv01=15_000.0,
                       leg_sign_resolution_bps=0.25)
    assert pp.FLAG_LEG_NEAR_MID not in call.flags
    assert call.unresolved_pv01 == 0.0


def test_orientation_from_cash_refuses_a_leg_exactly_at_mid():
    """``> 0`` and ``>= 0`` differ at exactly one input; neither is right."""
    assert pp.orientation_from_cash((1, -1), (5.0, -5.0)) == (1, 1)
    with pytest.raises(ValueError, match="exactly at mid"):
        pp.orientation_from_cash((1, -1), (0.0, -5.0))


def test_ptp_ufro_disagreement_is_flagged_and_carries_the_frozen_ratio():
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0,
                       ufro_sum=100.0)
    assert pp.FLAG_PTP_UFRO_DISAGREE in call.flags
    call2 = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                        npv_pays=[-10_000.0, -15_000.0],
                        pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0,
                        ufro_sum=3_000.0)
    assert pp.FLAG_PTP_UFRO_DISAGREE not in call2.flags


def test_an_unpriced_leg_is_a_pricing_error_not_a_silent_zero():
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, None],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_PRICING_ERROR
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, float("nan")],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_PRICING_ERROR


def test_an_exact_tie_is_no_call_not_a_side():
    """``conventions.dealer_side`` has a zero branch; this rule must use it."""
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-5_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.deviation_dollars == pytest.approx(0.0)
    assert call.dealer_sign == 0
    assert call.received_signs is None


def test_unallocated_cash_is_signal_not_noise():
    """The fees equal their model values exactly; the whole charge is the gap
    between their signed sum and the reported package price.

    Taking ``reported_price`` from ``sum(s_i * OPA_i)`` instead of from the
    package price would make this print an exact tie and throw the charge away
    -- and it is the case the tape produces whenever the venue allocates the
    fees at fair value and prices the package a tick away.
    """
    call = in_known_frame(
        pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                    npv_pays=[-10_000.0, -15_000.0],
                    pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0),
        CURVE_FRAME)
    assert call.reported_price == pytest.approx(-4_000.0)
    assert call.model_price == pytest.approx(-5_000.0)
    assert call.deviation_dollars == pytest.approx(1_000.0)
    assert call.dealer_sign == conv.DEALER_RECEIVED


def test_all_zero_fees_against_a_real_price_is_refused():
    """No sign vector orients anything, and the global flip stops cancelling."""
    call = pp.classify(opas=[0.0, 0.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=1e9)
    assert call.exclusion == pp.EXCL_TIEOUT_FAIL


def test_bp_denominator_is_the_structure_dv01_and_a_bad_one_is_refused():
    call = in_known_frame(
        pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                    npv_pays=[-10_000.0, -15_000.0],
                    pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0),
        CURVE_FRAME)
    assert call.deviation_bps == pytest.approx(1_000.0 / 10_000.0)
    for bad in (0.0, -1.0, None, float("nan")):
        assert pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                           npv_pays=[-10_000.0, -15_000.0],
                           pv01s=[10_000.0, 10_000.0],
                           structure_dv01=bad).exclusion == pp.EXCL_PRICING_ERROR


def test_rule_constant_is_its_own_and_not_one_of_the_pinned_two():
    assert pp.RULE_PACKAGE_PRICE not in (conv.RULE_RATE, conv.RULE_UPFRONT)


def test_conventions_still_refuses_to_orient_a_pkg_n():
    """``conventions.py`` is pinned; this module must not have relaxed it."""
    with pytest.raises(conv.UnorientableUnit):
        conv.base_orientation(conv.PKG, 4, conv.RULE_RATE)


# --------------------------------------------------------------------------
# 7. the vectorised tape gate agrees with the scalar path
# --------------------------------------------------------------------------

def _legs(pkg: str, opas, ptp, dv01s):
    return pd.DataFrame([
        {"_unit_group": pkg, "other_payment_amount": o,
         "package_transaction_price": ptp, "_dv01_proxy": d}
        for o, d in zip(opas, dv01s)
    ])


def test_tape_gate_matches_the_scalar_rule_on_every_named_refusal():
    frames = [
        _legs("OK", [10_000.0, 15_000.0], -4_000.0, [10_000.0, 10_000.0]),
        _legs("NOPRICE", [10_000.0, 15_000.0], 100.0, [10_000.0, 10_000.0]),
        _legs("MISSING", [10_000.0, np.nan], -4_000.0, [10_000.0, 10_000.0]),
        _legs("TIEOUT", [10_000.0, 15_000.0], 9e6, [10_000.0, 10_000.0]),
    ]
    df = pd.concat(frames, ignore_index=True)
    got = pp.tape_gate(df)
    assert list(got.loc[["OK", "NOPRICE", "MISSING", "TIEOUT"], "recoverable"]) \
        == [True, False, False, False]
    assert list(got.loc[["NOPRICE", "MISSING", "TIEOUT"], "stratum"]) == [
        pp.EXCL_NO_PACKAGE_PRICE, pp.EXCL_OPA_MISSING, pp.EXCL_TIEOUT_FAIL]


def test_tape_gate_is_empty_safe():
    got = pp.tape_gate(_legs("X", [1.0], None, [1.0]).iloc[:0])
    assert list(got.columns) == ["recoverable", "stratum", "tieout_bps",
                                 "margin_bps"]
    assert len(got) == 0


def test_tape_gate_refuses_a_frame_it_cannot_read_rather_than_returning_empty():
    """A missing column must raise. Silently returning "nothing recoverable"
    would read downstream as a measurement, not as a wiring bug."""
    with pytest.raises(KeyError):
        pp.tape_gate(pd.DataFrame({"_unit_group": ["A"]}))


def test_tape_gate_names_a_duplicated_column():
    """A ``SELECT`` that lists a column twice makes ``legs[col]`` a DataFrame.

    Not hypothetical: routing this gate into ``universe`` did exactly that, and
    the symptom was a ``to_numeric`` TypeError four frames away.
    """
    df = _legs("A", [1.0, 2.0], 5_000.0, [10.0, 10.0])
    df = pd.concat([df, df[["other_payment_amount"]]], axis=1)
    with pytest.raises(KeyError, match="duplicated"):
        pp.tape_gate(df)


def test_leg_columns_has_no_duplicates():
    from SDRUtils.dealer_direction import universe
    cols = list(universe.LEG_COLUMNS)
    assert len(cols) == len(set(cols)), \
        [c for c in set(cols) if cols.count(c) > 1]


# --------------------------------------------------------------------------
# 8. universe routing -- the recovered units leave EXCL_UNORIENTABLE
# --------------------------------------------------------------------------

def test_universe_routes_a_recoverable_pkg4_out_of_unorientable():
    from SDRUtils.dealer_direction import types as T
    from SDRUtils.dealer_direction import universe

    import tests.test_dealer_direction_universe as tu

    # Four 100mm 10y legs is ~$85k/bp each, so the unit's DV01 proxy is ~$170k
    # and one bp of it is $170k. The fees have to be spread by more than that
    # for the reconciliation to pick one sign vector out; the original fixture
    # here ([10k, 15k, 6k, 3k]) had a runner-up sign class $2,000 away --
    # 0.012 bp -- so it was routed into the kept universe on an orientation the
    # solver's lowest-mask tie-break chose. See §9.
    legs = tu._frame(*[
        tu._leg(trade_id=f"T{i}", package_id="P1",
                other_payment_amount=amt,
                package_transaction_price=-3_000_000.0,
                notional=100_000_000.0, tenor_years=10.0)
        for i, amt in enumerate([500_000.0, 1_100_000.0, 2_300_000.0,
                                 4_700_000.0])
    ])
    # the un-gated PTP makes it recoverable; a package with no price does not
    u = universe.unit_frame(legs)
    assert list(u["exclusion"]) == [None]

    legs2 = tu._frame(*[
        tu._leg(trade_id=f"T{i}", package_id="P2", other_payment_amount=amt,
                package_transaction_price=None,
                notional=100_000_000.0, tenor_years=10.0)
        for i, amt in enumerate([500_000.0, 1_100_000.0, 2_300_000.0,
                                 4_700_000.0])
    ])
    u2 = universe.unit_frame(legs2)
    assert list(u2["exclusion"]) == [T.EXCL_UNORIENTABLE]


def test_krd_seam_still_gives_a_package_one_sign_and_this_module_does_not():
    """The one hazard routing recovered PKG-N units into the ladder creates.

    ``krd.received_hypothesis_signs`` dispatches through ``conventions``: for a
    PKG-N it RAISES under the rate rule (loud, fine) and returns ``(1,)*n``
    under the upfront rule -- every leg the same sign. A recovered package has
    an upfront (its PTP), so a consumer routing on upfront presence lands in
    the second branch and points a whole package's key-rate profile one way.

    Pinned here so the difference is visible rather than discovered from a
    ladder that does not move: consumers of a RULE_PACKAGE_PRICE call must read
    ``package_price.received_hypothesis_signs`` instead.
    """
    from SDRUtils.dealer_direction import krd

    with pytest.raises(conv.UnorientableUnit):
        krd.received_hypothesis_signs(conv.PKG, 4, conv.RULE_RATE)
    assert krd.received_hypothesis_signs(conv.PKG, 4, conv.RULE_UPFRONT) \
        == (1, 1, 1, 1)

    call = _pkg4()
    assert call.exclusion is None
    got = pp.received_hypothesis_signs(call)
    assert len(set(got)) > 1, (
        "the whole point is that the package's legs are NOT all one way")
    assert got == tuple(call.base_orientation)


def test_received_hypothesis_signs_refuses_an_unoriented_call():
    call = pp.classify(opas=[1.0, 2.0], package_price=None,
                       npv_pays=[-1.0, -2.0], pv01s=[1e4, 1e4],
                       structure_dv01=1e4)
    assert call.exclusion == pp.EXCL_NO_PACKAGE_PRICE
    with pytest.raises(ValueError, match="not oriented"):
        pp.received_hypothesis_signs(call)


def test_universe_still_excludes_an_asset_swap_package():
    from SDRUtils.dealer_direction import types as T
    from SDRUtils.dealer_direction import universe

    import tests.test_dealer_direction_universe as tu

    legs = tu._frame(*[
        tu._leg(trade_id=f"T{i}", package_id="P3", other_payment_amount=amt,
                package_transaction_price=-3_000_000.0,
                trade_type="SPREADOVER",
                notional=100_000_000.0, tenor_years=10.0)
        for i, amt in enumerate([500_000.0, 1_100_000.0, 2_300_000.0,
                                 4_700_000.0])
    ])
    u = universe.unit_frame(legs)
    assert list(u["exclusion"]) == [T.EXCL_UNORIENTABLE]


# --------------------------------------------------------------------------
# 9. IDENTIFICATION -- is the winning sign vector the only one that fits?
# --------------------------------------------------------------------------
#
# Passing the tie-out gate says the winning sign vector reconciles the fees
# with the price. It does NOT say it is the only one that does, and on a
# PKG-4+ it usually is not: measured on the tape (see
# ``scratch/ppfix_measure.py``), the median accepted PKG-4+ unit has several
# mutually inconsistent orientations inside ``TIEOUT_MAX_BPS``, each implying
# a different per-leg key-rate profile, with the winner chosen by
# ``opa_sign_solver``'s lowest-mask tie-break -- a convention, not economics.
#
# ``margin_bps`` is the identification statistic: the distance from the
# winning sign class to the next DISTINCT one, in bp of the unit's own DV01,
# where a "class" is a sign vector together with its global complement (the
# degree of freedom the price comparison consumes, so the two are the same
# answer). A unit is identified when the runner-up class sits OUTSIDE the same
# gate the winner had to sit inside: if 1 bp of unexplained cash is acceptable
# noise, then every class within 1 bp is equally consistent with the data.


def test_the_pkg4_fixture_is_a_real_call_and_identified():
    """The fixture 4b leans on, pinned so it cannot rot into passing for the
    wrong reason (an exact tie would make ``dealer_sign`` 0, and an ambiguous
    package would be refused)."""
    call = _pkg4()
    assert call.exclusion is None
    assert call.dealer_sign != 0
    assert call.margin_bps == pytest.approx(10.0)      # $20,000 on $2,000/bp


@pytest.mark.parametrize("opas,ptp,want", [
    # one leg -> one sign class; a vector and its complement are the same
    # answer, so there is no runner-up and the unit is identified by default.
    ([40_000.0], 40_000.0, float("inf")),
    # two legs, two classes: {+,+} nets 20,000 and {+,-} nets 0. Against a
    # price of 600 the residuals are 19,400 and 600 -> margin 18,800.
    ([10_000.0, 10_000.0], 600.0, 18_800.0),
    # the worked CURVE example: {+,+} nets 26,000, {+,-} nets -4,000.
    ([11_000.0, 15_000.0], -4_000.0, 22_000.0),
    # duplicated fees make DISTINCT sign vectors net the same, so two classes
    # tie exactly and the winner is the tie-break's. Margin must be 0.
    ([10_000.0, 10_000.0, 5_000.0, 5_000.0], 10_000.0, 0.0),
    # the 4b PKG-4: residuals 86k/22k/0/64k/44k/20k/42k/106k -> runner-up 20k
    (list(PKG4_OPAS), PKG4_PTP, 20_000.0),
])
def test_sign_class_margin_reproduces_hand_computed_answers(opas, ptp, want):
    """The identification statistic, checked against inputs whose answer is
    known by enumeration on paper -- not against the module's own arithmetic.
    """
    got = pp.sign_class_margin(opas, ptp)
    if math.isinf(want):
        assert math.isinf(got) and got > 0
    else:
        assert got == pytest.approx(want)


def _all_classes(n):
    for m in range(1 << (n - 1)):
        yield [1] + [1 if (m >> i) & 1 else -1 for i in range(n - 1)]


def test_sign_class_margin_agrees_with_the_solver_on_the_best_residual():
    """The margin enumeration and ``opa_sign_solver`` must be measuring the
    same landscape, or the margin is the distance between two different
    problems."""
    rng = np.random.default_rng(20260811)
    seen = 0
    for _ in range(200):
        n = int(rng.integers(2, 9))
        opas = np.round(rng.uniform(1_000, 500_000, size=n), 2).tolist()
        ptp = float(np.round(rng.uniform(-2e6, 2e6), 2))
        if abs(ptp) <= pp.PTP_USD_FLOOR:
            continue
        seen += 1
        cash = pp.solve_cash_signs(opas, ptp)
        best = min(abs(abs(sum(s * v for s, v in zip(sv, opas))) - abs(ptp))
                   for sv in _all_classes(n))
        assert cash.residual == pytest.approx(best, abs=1e-6)
        assert cash.margin >= -1e-9
    assert seen > 150


def test_margin_is_not_enumerated_above_the_leg_cap_and_that_is_ambiguous():
    """Above ``MARGIN_MAX_LEGS`` the runner-up cannot be enumerated, so the
    unit cannot be certified identified. It must be refused, not waved through
    on a silently missing statistic."""
    n = pp.MARGIN_MAX_LEGS + 1
    opas = [float(1_000 * (i + 1)) for i in range(n)]
    ptp = float(sum(opas[:3]) - sum(opas[3:]))
    assert math.isnan(pp.sign_class_margin(opas, ptp))
    call = pp.classify(opas=opas, package_price=ptp,
                       npv_pays=[float(-100 * (i + 1)) for i in range(n)],
                       pv01s=[10_000.0] * n, structure_dv01=1e5)
    assert call.exclusion == pp.EXCL_SIGNS_AMBIGUOUS
    assert call.margin_bps is None or math.isnan(call.margin_bps)


def test_an_ambiguous_package_is_refused_by_name_not_oriented_on_a_tie_break():
    """The original FLY fixture, kept here as the regression it is.

    Wings 0.5 bp off mid put $2,500 of fee on a $10,000/bp belly, so flipping
    a wing's cash direction moves the reconciliation 0.5 bp -- half the
    residual the gate already tolerates. Two orientations fit; the module used
    to return whichever the solver's lowest-mask tie-break produced, and every
    leg's key-rate sign came from that.
    """
    opas, ptp = [3_500.0, 10_000.0, 2_500.0], -4_000.0
    call = pp.classify(opas=opas, package_price=ptp,
                       npv_pays=[-2_500.0, -10_000.0, -2_500.0],
                       pv01s=[5_000.0, 10_000.0, 5_000.0],
                       structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_SIGNS_AMBIGUOUS
    assert call.base_orientation is None and call.received_signs is None
    # the refusal is countable: both statistics survive it
    assert call.tieout_bps == pytest.approx(0.0)
    assert call.margin_bps == pytest.approx(0.5)


def test_the_identification_gate_is_the_tieout_gate_not_a_new_constant():
    """A unit is identified iff the runner-up class is outside
    ``tieout_max_bps`` -- the same number, applied to the second-best fit
    instead of the best. No second threshold is introduced, and moving the
    tie-out moves both.
    """
    opas, ptp, pv01s = [3_500.0, 10_000.0, 2_500.0], -4_000.0, [5e3, 1e4, 5e3]
    npvs = [-2_500.0, -10_000.0, -2_500.0]
    tight = pp.classify(opas=opas, package_price=ptp, npv_pays=npvs,
                        pv01s=pv01s, structure_dv01=10_000.0,
                        tieout_max_bps=0.25)
    assert tight.exclusion is None            # runner-up 0.5 bp > 0.25 bp
    loose = pp.classify(opas=opas, package_price=ptp, npv_pays=npvs,
                        pv01s=pv01s, structure_dv01=10_000.0,
                        tieout_max_bps=1.0)
    assert loose.exclusion == pp.EXCL_SIGNS_AMBIGUOUS


def test_margin_is_reported_on_a_call_that_is_accepted():
    call = pp.classify(opas=[10_000.0, 15_000.0], package_price=-4_000.0,
                       npv_pays=[-10_000.0, -15_000.0],
                       pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
    assert call.exclusion is None
    assert call.margin_bps == pytest.approx(2.0)      # $20,000 on $10,000/bp


def test_the_tape_gate_reports_the_margin_and_refuses_an_ambiguous_package():
    df = pd.concat([
        _legs("IDENT", [10_000.0, 15_000.0], -4_000.0, [10_000.0, 10_000.0]),
        _legs("AMBIG", [3_500.0, 10_000.0, 2_500.0], -4_000.0,
              [10_000.0, 5_000.0, 5_000.0]),
    ], ignore_index=True)
    got = pp.tape_gate(df)
    assert list(got.loc[["IDENT", "AMBIG"], "recoverable"]) == [True, False]
    assert got.loc["AMBIG", "stratum"] == pp.EXCL_SIGNS_AMBIGUOUS
    assert got.loc["IDENT", "margin_bps"] == pytest.approx(2.0)
    assert got.loc["AMBIG", "margin_bps"] == pytest.approx(0.5)


def test_ambiguous_is_in_the_strata_vocabulary():
    """The report iterates ``STRATA``; a stratum missing from it is DV01 that
    vanishes from the coverage accounting rather than being given up by name.
    """
    assert pp.EXCL_SIGNS_AMBIGUOUS in pp.STRATA


# --------------------------------------------------------------------------
# 10. the gate and the classifier are ONE rule -- they must not disagree
# --------------------------------------------------------------------------

def _gate_stratum(opas, ptp, dv01_legs):
    got = pp.tape_gate(_legs("U", opas, ptp, dv01_legs))
    return got.loc["U", "stratum"], bool(got.loc["U", "recoverable"])


def test_a_package_whose_fees_net_to_zero_is_refused_by_BOTH_paths():
    """Equal fee allocations. ``classify`` calls this ``TIEOUT_FAIL`` (the
    base party's cash is zero under either branch, so the deviation would
    depend on the solver's tie-break) -- and the gate used to call it
    recoverable, which is the word ``universe.unit_frame`` routes on. The
    coverage table and the classifier then disagreed about the same package.
    """
    opas, ptp, dv01_legs = [10_000.0, 10_000.0], 600.0, [10_000.0, 10_000.0]
    stratum, recoverable = _gate_stratum(opas, ptp, dv01_legs)
    call = pp.classify(opas=opas, package_price=ptp,
                       npv_pays=[-10_000.0, -15_000.0], pv01s=dv01_legs,
                       structure_dv01=10_000.0)
    assert call.exclusion == pp.EXCL_TIEOUT_FAIL
    assert (stratum, recoverable) == (pp.EXCL_TIEOUT_FAIL, False)


def test_a_non_finite_fee_names_one_stratum_instead_of_killing_the_day():
    """``classify``'s ``_num`` refuses ``inf``; the gate's
    ``to_numeric().isna()`` let it through and the solver died inside
    ``_select_best`` with "zero-size array to reduction operation minimum",
    taking the whole day's ``unit_frame`` with it. One corrupt leg must cost
    one package, not one day.
    """
    for bad in (float("inf"), float("-inf")):
        stratum, recoverable = _gate_stratum([10_000.0, bad], -4_000.0,
                                             [10_000.0, 10_000.0])
        call = pp.classify(opas=[10_000.0, bad], package_price=-4_000.0,
                           npv_pays=[-10_000.0, -15_000.0],
                           pv01s=[10_000.0, 10_000.0], structure_dv01=10_000.0)
        assert call.exclusion == pp.EXCL_OPA_MISSING
        assert (stratum, recoverable) == (pp.EXCL_OPA_MISSING, False)


def test_a_non_finite_fee_does_not_take_the_rest_of_the_frame_with_it():
    df = pd.concat([
        _legs("GOOD", [10_000.0, 15_000.0], -4_000.0, [10_000.0, 10_000.0]),
        _legs("BAD", [10_000.0, float("inf")], -4_000.0, [1e4, 1e4]),
    ], ignore_index=True)
    got = pp.tape_gate(df)
    assert list(got.loc[["GOOD", "BAD"], "recoverable"]) == [True, False]


#: (opas, ptp, per-leg dv01) -> the two paths must name the same stratum.
#: The dv01 the classifier is given is the gate's own ``sum(|dv01|)/2`` so the
#: only thing under test is the ORDER and the PREDICATES, not the denominator.
_PRECEDENCE_GRID = [
    ([10_000.0, 15_000.0], -4_000.0, [10_000.0, 10_000.0]),      # clean
    ([10_000.0, 15_000.0], None, [10_000.0, 10_000.0]),          # no price
    ([10_000.0, 15_000.0], 100.0, [10_000.0, 10_000.0]),         # sub-floor
    ([10_000.0, 15_000.0], float("nan"), [1e4, 1e4]),            # nan price
    ([10_000.0, 15_000.0], float("inf"), [1e4, 1e4]),            # inf price
    ([10_000.0, None], -4_000.0, [1e4, 1e4]),                    # missing fee
    ([10_000.0, float("nan")], -4_000.0, [1e4, 1e4]),            # nan fee
    ([10_000.0, float("inf")], -4_000.0, [1e4, 1e4]),            # inf fee
    ([10_000.0, 15_000.0], -4_000.0, [0.0, 0.0]),                # no dv01
    ([10_000.0, 15_000.0], -4_000.0, [float("inf"), 1e4]),       # inf dv01
    ([10_000.0, 15_000.0], 9e6, [1e4, 1e4]),                     # tie-out fail
    ([10_000.0, 10_000.0], 600.0, [1e4, 1e4]),                   # net == 0
    ([0.0, 0.0], -4_000.0, [1e9, 1e9]),                          # zero fees
    ([3_500.0, 10_000.0, 2_500.0], -4_000.0, [1e4, 5e3, 5e3]),   # ambiguous
    ([10_000.0, 15_000.0], None, [0.0, 0.0]),             # no price + no dv01
    ([10_000.0, None], 100.0, [1e4, 1e4]),           # sub-floor + missing fee
    ([10_000.0, float("inf")], -4_000.0, [0.0, 0.0]),     # inf fee + no dv01
]


@pytest.mark.parametrize("opas,ptp,dv01_legs", _PRECEDENCE_GRID)
def test_the_gate_and_the_classifier_name_the_same_stratum(opas, ptp,
                                                           dv01_legs):
    """One rule, two implementations, and ``universe.unit_frame`` routes on
    the gate's word while the report reads the classifier's. Where both can
    see a stratum they must agree -- including which one wins when two apply.
    """
    stratum, recoverable = _gate_stratum(opas, ptp, dv01_legs)
    dv01 = float(np.nansum([abs(d) for d in dv01_legs])) / 2.0
    call = pp.classify(opas=opas, package_price=ptp,
                       npv_pays=[-10_000.0 * (i + 1) for i in range(len(opas))],
                       pv01s=[abs(d) for d in dv01_legs], structure_dv01=dv01)
    assert call.exclusion == stratum, (
        f"gate says {stratum!r}, classify says {call.exclusion!r}")
    assert recoverable is (stratum is None)


def test_the_shared_strata_are_evaluated_in_the_declared_order():
    """``STRATA`` is the order, and it is the order both paths walk. A stratum
    that is not in it, or is in it in the wrong place, makes the two disagree
    on any row where more than one applies."""
    assert pp.STRATA == (
        pp.EXCL_NO_PACKAGE_PRICE, pp.EXCL_OPA_MISSING, pp.EXCL_PRICING_ERROR,
        pp.EXCL_TIEOUT_FAIL, pp.EXCL_SIGNS_AMBIGUOUS, pp.EXCL_LEG_AT_MID)


def test_the_gate_and_the_classifier_scale_the_same_residual_the_same_way():
    """M16: deleting the ``/ 2.0`` from the gate's DV01 left the whole suite
    green. The two paths take DIFFERENT dv01 INPUTS -- the gate a notional x
    tenor proxy, the classifier repriced PV01s -- but they must apply the same
    ``PKG-N`` convention, ``sum(|dv01|) / 2``, to whatever they are given.

    Pinned on a residual that lands between the gate and twice the gate, so
    dropping the halving flips the verdict rather than moving a number nobody
    reads: best net is 25,000 against a price of 36,000 -> $11,000 residual,
    which is 1.1 bp on $10,000/bp and 0.55 bp on $20,000/bp.
    """
    opas, ptp, dv01_legs = [10_000.0, 15_000.0], 36_000.0, [10_000.0, 10_000.0]
    stratum, recoverable = _gate_stratum(opas, ptp, dv01_legs)
    assert (stratum, recoverable) == (pp.EXCL_TIEOUT_FAIL, False)
    got = pp.tape_gate(_legs("U", opas, ptp, dv01_legs))
    assert got.loc["U", "tieout_bps"] == pytest.approx(1.1)
    call = pp.classify(opas=opas, package_price=ptp,
                       npv_pays=[-10_000.0, -15_000.0], pv01s=dv01_legs,
                       structure_dv01=sum(dv01_legs) / 2.0)
    assert call.exclusion == pp.EXCL_TIEOUT_FAIL
    assert call.tieout_bps == pytest.approx(got.loc["U", "tieout_bps"])


# --------------------------------------------------------------------------
# 11. the greedy solve is recorded, and the leg cap is not a hand-copy
# --------------------------------------------------------------------------

def test_above_the_solver_exact_limit_the_solve_is_greedy_and_says_so():
    """M19/M20: ``FLAG_GREEDY_SOLVE`` fired in no test and ``CashSigns.exact``
    could be hardcoded ``True``. Both survived because nothing exercised more
    legs than ``opa_sign_solver`` enumerates."""
    n = pp.EXACT_SOLVE_MAX_LEGS + 2
    opas = [float(1_000 * (i + 1)) for i in range(n)]
    cash = pp.solve_cash_signs(opas, 5_000.0)
    assert cash.exact is False
    small = pp.solve_cash_signs([10_000.0, 15_000.0], -4_000.0)
    assert small.exact is True
    call = pp.classify(opas=opas, package_price=5_000.0,
                       npv_pays=[float(-100 * (i + 1)) for i in range(n)],
                       pv01s=[10_000.0] * n, structure_dv01=130_000.0)
    assert pp.FLAG_GREEDY_SOLVE in call.flags


def test_the_exact_solve_cap_is_taken_from_the_solver_not_copied():
    """A hand-copied 24 lies silently the day ``opa_sign_solver`` moves its
    own limit: ``exact`` would keep saying ``True`` for a greedy solve."""
    from SDRUtils.packages import opa_sign_solver

    assert pp.EXACT_SOLVE_MAX_LEGS == opa_sign_solver._MAX_BRUTE_N
    assert pp.MARGIN_MAX_LEGS <= pp.EXACT_SOLVE_MAX_LEGS
