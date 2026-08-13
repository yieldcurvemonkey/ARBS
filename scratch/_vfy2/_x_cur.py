"""The upfront rule: a repriced NPV against the reported fee, made probabilistic.

WHAT MAKES THE RULE IDENTIFIED
------------------------------

The brief's statement -- "if the NPV is higher than the reported other-payment
amount, the dealer received fixed" -- is not decidable as written. ``#58 Other
payment amount`` is disseminated as "any value greater than or equal to zero"
while ``#61 payer`` and ``#62 receiver`` are not disseminated at all (spec
p.31-32, visually verified: F-13). An unsigned amount cannot be compared to a
signed NPV. Naive edge-capture is not identified either -- with the fee sign
free, *both* direction hypotheses can be made to imply a non-negative dealer
edge.

The missing constraint is physical: **the fee flows from the party receiving
value to the party giving it up.** With ``f = (mid - R) * A`` the NPV to the
fixed payer and ``U >= 0`` the observed fee, the dealer's edge under a
hypothesis is ``sign(V) * (|f| - U)`` where ``V`` is the value of the side the
hypothesis gives the dealer. The two hypotheses give exactly opposite edges, so
one and only one is non-negative, and that closes the system::

    dealer holds the ITM side   <=>   U < |f|          (a NEW trade)
    ITM side is PAY fixed       <=>   f > 0  (R < mid)

which is exactly what ``stir_flow/classifier.py:77-80`` already implements. This
module is a *generalisation of that rule*, not a second solver. In particular it
is not ``SDRUtils/packages/opa_sign_solver.py``, which is an adjacent problem:
that solver minimises ``min(|sum(s*OPA) - PTP|, |sum(s*OPA) + PTP|)``, so a sign
vector and its global complement score identically -- it is direction-blind *by
symmetry* -- and its ``dealer_spread_est`` is literally the dollar residual,
non-negative on all 351,510 populated rows and flat across ``sign(net)``.

AND THE SIGN INVERTS ON A TERMINATION
-------------------------------------

At inception the party *taking* the in-the-money side receives value and
therefore pays the fee, so a dealer holding the ITM side is out of pocket ``U``
and its edge is ``|f| - U >= 0``. At a tear-up the party *giving up* the
in-the-money position is the one handing over value, so it *receives* the fee,
and the same dealer's edge is ``U - |f| >= 0``. Same physical principle, opposite
comparison::

    NEW TRADE    dealer holds the ITM side  <=>  U < |f|
    TERMINATION  dealer holds the ITM side  <=>  U > |f|

Worked: a customer paid fixed at 3.00% and mid is now 4.00%. The customer's payer
position is in the money (``f > 0``); the dealer received fixed at 3% and is the
out-of-the-money side. To tear it up the dealer pays the customer slightly *less*
than the position is worth, so ``U < |f|`` while the dealer held the OTM side --
the exact inverse of the new-trade reading. ``LEDGER D8`` records "the sign is
right" for terminations; that was established from the fact that repricing
against the fee *is* the inference, and never derived the direction of the
comparison. It is derived here, and pinned by test.

``dealer_sign`` on a lifecycle row is **the side the dealer held on the dying
swap**, not the risk direction of the tear-up -- those are negations of each
other, since unwinding a received-fixed position sheds duration.

WHY A SEPARATE tau
------------------

``p = sigma(edge / tau)`` with ``tau = s^2 / (2h)`` (DESIGN 1.1). ``tau_upfront``
is fitted separately from the rate rule's because the noise is different in
kind: NPV error grows with duration, and the fee carries its own rounding and
notation hazards. It is fitted on ``z = (|f| - U) / DV01``, which is observable
without knowing the direction and is, under the model, exactly the symmetric
``+-h`` mixture the rate rule's fitter already estimates -- so
``probability.py``'s fitter applies to it unchanged. That is the coordination:
one fitter, pointed at a second statistic. Flow and lifecycle are never pooled,
and a ``TauUpfront`` carries the population it was fitted on so it cannot be
applied to the other one.

WHAT THE CALIBRATION ACTUALLY MEASURED -- READ THIS BEFORE TRUSTING A p
-----------------------------------------------------------------------

The sign is derived and pinned. The *confidence* is not there, and the reason is
worth stating in one place rather than being rediscovered from a ladder that
does not move.

On 2,025 fee-bearing flow outrights over 609 days, the fee tracks the repriced
NPV extraordinarily closely: median ``U/|dev|`` is **0.9996**, and 52% of prints
sit within 10% of a perfect match. The residual after the fee is
``median |z| = 0.178 bp``, ``MAD-sigma 0.261 bp``. That is bid-offer scale, and
it is also -- to within a rounding error -- **the size of our own mid error**:
the on-market control (507 prints, no fee) has robust sigma 0.254 bp and fitted
``s`` 0.358 bp against the upfront population's fitted ``s`` 0.382 bp.

So ``probability.fit_mixture`` cannot separate ``h`` from ``s`` on ``z``: every
bucket comes back ``LEPTOKURTIC_MOMENT_CHECK_FAILED`` +
``SEPARATION_BELOW_FLOOR``, ``h`` floored, ``tau_upfront`` capped at the
no-information limit of 2.9-11.0 bp by tenor band. A median edge of 0.18 bp
against ``tau`` of 3.8 bp is ``p = 0.512`` and ``signed_weight = 0.024``. That is
the honest answer, not a defect: the dealer's edge on an off-market print is
smaller than our ability to price the print. ``tau = s^2/(2h)`` is quadratic in
mid quality (DESIGN 1.1), so this is a mid-precision problem and halving ``s``
quarters ``tau``.

THE NEAR-MID TRAP
-----------------

``edge = sign(R - mid) * (|f| - U - b0)``, i.e. ``sign(dev)`` times the residual
-- the magnitude comes from the fee, the *sign* comes from which side of mid the
print is on. For the 275,540 flow legs that carry a fee while not being rate
outliers, that deviation can be inside the mid's own measurement error while
``|edge|`` is several basis points -- a bare logistic then mass-produces
confident coin flips. Passing ``mid_sigma_bps`` marginalises the deviation over
its measurement error, which sends ``p -> 0.5`` exactly where the sign is
unidentified. Without it the call still comes out, flagged
:data:`FLAG_NO_MID_SIGMA`.

Every quantity in that expression is read off the **bias-corrected** deviation,
including the sign. ``mid_bias_bps`` moves the mid, so it moves which side of it
a print is on; taking the magnitude from the corrected deviation and the sign
from the raw NPV produced rows where ``dealer_sign`` and ``p`` pointed opposite
ways, and the trigger was ``|raw dev| < |bias|`` -- the near-mid population this
rule exists for.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from SDRUtils.dealer_direction import conventions
from SDRUtils.dealer_direction import types as dd_types
from SDRUtils.stir_flow import config as stir_config
from SDRUtils.stir_flow.trade_selection import resolve_upfront as _frozen_resolve

# --- populations. Never pooled: see D8 and the tau docstring above. --------
POPULATION_FLOW = "FLOW"
POPULATION_LIFECYCLE = "LIFECYCLE"

# --- where the fee came from ----------------------------------------------
SRC_PTP = "PTP"
SRC_UFRO = "UFRO_SUM"
SRC_UWIN = "UWIN_SUM"

# --- flags. Diagnostics, not exclusions, unless stated. -------------------
#: Both a package price and a leg fee are present and they are more than
#: ``PTP_UFRO_DISAGREE_RATIO`` apart. The frozen rule keeps the PTP; so do we.
FLAG_PTP_UFRO_DISAGREE = "PTP_UFRO_DISAGREE"
#: A lifecycle row with no UWIN, classified off its UFRO instead.
FLAG_LIFECYCLE_FEE_FALLBACK = "LIFECYCLE_FEE_FALLBACK"
#: The fee is below ``PTP_USD_FLOOR``, so the rule has degenerated into the rate
#: rule with extra steps -- ``U ~ 0`` makes ``U < |f|`` true for anything.
FLAG_TINY_UPFRONT = "TINY_UPFRONT"
#: The deviation carrying the sign is inside the mid's measurement error while
#: the fee is larger than it. The magnitude is real; the sign is a coin flip.
FLAG_SIGN_FRAGILE = "SIGN_FRAGILE"
#: No ``mid_sigma_bps`` was supplied, so :data:`FLAG_SIGN_FRAGILE` could not be
#: evaluated and ``p`` is the bare logistic. Absence of evidence, flagged.
FLAG_NO_MID_SIGMA = "NO_MID_SIGMA"

# --- exclusions -----------------------------------------------------------
#: A capped print carrying a fee. `types.py` owns the ``EXCL_*`` vocabulary and
#: is not this module's to edit, so this constant lives here and should be
#: adopted there; the coverage accounting needs it to be one name.
EXCL_CAPPED_UPFRONT = "CAPPED_UPFRONT"
EXCL_NO_UPFRONT = "NO_UPFRONT"
#: The repriced NPV is not a finite number, so there is nothing to compare the
#: fee against. Re-exported from ``types`` rather than given a second name --
#: this is the ordinary pricing failure and it already has one.
EXCL_PRICING_ERROR = dd_types.EXCL_PRICING_ERROR

#: Whether ``#58`` is left at its unscaled value on a capped print. The spec
#: requires the SDR to "proportionally scale other applicable fields" but does
#: not enumerate them, delegating to the SDR's own procedures -- so it is a
#: measurement, not a reading, and the measurement says **scaled**.
#:
#: ``|NPV|/U`` is scale-free in notional (both sides are linear in it), so if
#: ``#58`` were left unscaled while the notional was capped 1.6-4.0x low, capped
#: prints would show a ratio 1.6-4.0x *below* the uncapped control -- a
#: deterministic inversion of ``U < |f|``, not noise. Measured on 952 capped and
#: 979 uncapped fee-bearing outrights: median ``|NPV|/U`` **1.004 capped vs
#: 1.000 uncapped**, and paired within (tenor band x cap vintage) the
#: capped/uncapped ratio of medians runs **0.984-1.017** across seven cells.
#: There is no inversion, so the guard is off by default and ``exclude_capped``
#: exists only so the decision can be revisited on a future tape generation.
#: The residual asymmetry is real but small -- capped ``frac(|NPV| > U)`` 0.563
#: against 0.490 uncapped, and a wider IQR -- which is a confidence question,
#: not a sign one.
CAPPED_UPFRONT_IS_UNSCALED = False

#: ``min(|dev|, |z|) <= this * s`` is where the sign stops being identified.
#:
#: ``dealer_sign = sign(dev) * sign(z)``, and as a function of the true
#: deviation the edge is ``dev - sign(dev) * c`` with ``c = U/DV01 + b0``, so it
#: changes sign at ``dev in {-c, 0, +c}``. The distance to 0 is ``|dev|`` and the
#: distance to ``+-c`` is ``|z|``; the sign is a coin flip within the mid error
#: of **either**. Testing ``|dev|`` alone missed the ``|z|`` boundary, which on
#: this tape is the common one: median ``U/|dev|`` is 0.9996, so most fees land
#: almost exactly on the deviation.
#:
#: Measured on the 2,025-print flow sample at sigma = 0.254 bp: the ``|dev|``-only
#: condition fired on 12.4% while a further 46.0% sat inside ONE sigma of the
#: ``|z|`` boundary (median ``|z|`` 0.090 bp) and said nothing. The corrected
#: condition is a strict superset -- it drops no row that used to fire -- and
#: takes the flagged share to 72% at two sigma, 57% at one. That rate is the
#: finding, not a reason to move the threshold: it restates the calibration
#: section above, where the residual after the fee (median ``|z|`` 0.178 bp) is
#: the same size as our own mid error (0.254 bp). Two sigma is kept.
FRAGILE_SIGMA_MULT = 2.0

#: Named so a consumer cannot mistake which of the two lifecycle polarities this
#: module reports. See the module docstring.
LIFECYCLE_SIGN_MEANS_SIDE_HELD = True

#: The fitter is looked up by name in ``probability.py``. First match wins.
_MIXTURE_FIT_NAMES = ("fit_mixture", "fit_symmetric_mixture",
                      "fit_two_component_mixture", "mixture_fit")

# Quadrature for `p_marginalised`. Gauss-Legendre, panelled, with the panels
# laid out so the integrand's jump at `d = 0` always falls on a panel EDGE --
# see that function for why a Gaussian-weighted rule cannot be used across it.
# 16 nodes on panels one sigma wide; measured max error 1.8e-14 against an
# independent per-branch `scipy.integrate.quad` over a 1,560-point grid of
# (dev, U, tau, s, b0), and the accuracy is flat from 8 to 16 nodes and from
# 0.75 to 1.5 sigma panels, so this sits well inside the plateau rather than on
# its edge. Computed once.
_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(16)
_PANEL_SIGMAS = 1.0
#: Standard-normal units at which the Gaussian is truncated. Dropped mass
#: ``2*Phi(-9) = 2.3e-19``, i.e. below the last bit of a double on a probability.
_TAIL_SIGMAS = 9.0
#: ``|x|`` beyond which ``sigma(x)`` is within 4.2e-18 of 0 or 1. The saturated
#: wings are then integrated in closed form off the normal CDF instead of
#: spending nodes on a constant.
_LOGISTIC_SATURATION = 40.0
_SQRT2 = math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


class MixtureFitUnavailable(RuntimeError):
    """``probability.py``'s mixture fitter could not be resolved.

    Raised rather than falling back to a local fit. A quietly substituted
    ``tau`` is invisible -- every ``p`` in the run would be wrong by a scale
    factor and nothing would look broken.
    """


@dataclasses.dataclass(frozen=True)
class ResolvedUpfront:
    """Which fee this unit is classified against, and what was odd about it."""

    amount: float | None
    source: str | None
    flags: tuple = ()


@dataclasses.dataclass(frozen=True)
class TauUpfront:
    """A fitted calibration for one population and one bucket.

    Carries ``population`` so a flow calibration cannot be applied to a
    termination: a 20-year seasoned unwind is 100 bp from mid and would score as
    maximal confidence under the flow ``tau``, for entirely the wrong reason.
    """

    tau_bps: float
    bias_bps: float                 # b0 -- the systematic offset in z
    half_spread_bps: float          # h
    sigma_bps: float                # s -- the measurement noise in z
    n: int
    population: str
    bucket: str = "ALL"
    #: ``None`` when the mixture fitted. Otherwise the reason it could not, so
    #: the fallback is visible in provenance rather than inferred from a number.
    fallback: str | None = None


@dataclasses.dataclass(frozen=True)
class UpfrontCall:
    """The upfront rule's answer for one unit.

    Maps onto :class:`types.DirectionCall` with ``rule =
    conventions.RULE_UPFRONT``, ``deviation_bps = edge_bps``, and this module's
    ``flags`` folded into provenance.
    """

    #: Printed price minus mid, bp. Exactly ``-npv_pay / structure_dv01``,
    #: because ``npv_pay = (mid - R) * A`` and ``pv01 = A * 1e-4``. For an
    #: OUTRIGHT this is the leg's rate deviation; for a package it is the net
    #: NPV expressed in bp of the unit's own DV01.
    dev_bps: float | None
    #: ``U / structure_dv01``.
    upfront_bps: float | None
    #: ``z = |dev| - u - b0``. Direction-blind, and what ``tau`` is fitted on.
    residual_bps: float | None
    #: ``z`` signed towards "dealer received fixed". This is the signed edge.
    edge_bps: float | None
    dealer_sign: int
    p: float | None = None
    signed_weight: float | None = None
    population: str = POPULATION_FLOW
    upfront_source: str | None = None
    tau_bps: float | None = None
    tau_bucket: str | None = None
    bias_bps: float = 0.0
    #: The bucket mid-bias that was subtracted from ``dev_bps``. Recorded
    #: because it is the one input that changes the ANSWER -- it can move a
    #: print across mid and so flip ``dealer_sign`` -- and a call that does not
    #: carry it cannot be reconciled against the raw NPV it came from.
    mid_bias_bps: float = 0.0
    flags: tuple = ()
    exclusion: str | None = None


def resolve_upfront(pkg_ptp, ufros=None, uwins=None, *,
                    is_lifecycle: bool = False) -> ResolvedUpfront:
    """Which reported amount is this unit's fee.

    Delegates the PTP-vs-fee precedence and both thresholds to the frozen
    ``trade_selection.resolve_upfront`` -- ``PTP_USD_FLOOR`` (sub-floor package
    prices are notation artefacts rather than dollars) and
    ``PTP_UFRO_DISAGREE_RATIO`` -- so there is one implementation of that rule,
    not two that drift.

    The extension is **UWIN**, the unwind settlement fee, which
    ``classifier.py:64`` does not read. But the premise that terminations
    therefore have nothing to compare against turns out to be false on this
    tape, and the measurement inverts which branch matters:
    ``other_payment_uwin > 0`` on **15 rows out of 2,326,781** (one of them a
    TERMINATION), while **11,583 of 50,752 ECONOMIC_FLOW terminations carry
    ``other_payment_ufro``**. The SDR is stamping ``#57 Other payment type`` as
    UFRO on unwind settlements, so the UWIN column is very nearly empty and the
    UFRO fallback below is the *main path* for lifecycle rows, not a corner
    case. UWIN is still preferred where present, because when it is populated it
    is unambiguous.
    """
    # `_num` before the frozen resolver, not after: it sums
    # `u for u in leg_ufros if u`, and a NaN is truthy, so ONE NaN leg poisons
    # the sum and `ufro_sum > 0` goes False -- reporting a fee-bearing unit as
    # having no fee at all. Both frozen call sites hand it `.fillna(0.0)` /
    # `or 0.0`; this one takes a caller's list, so it does the coercion itself.
    ufros = [_num(u) for u in (ufros or [])]
    uwins = [_num(u) for u in (uwins or [])]
    flags: list = []

    if is_lifecycle:
        primary, primary_src = uwins, SRC_UWIN
        if not any(_num(u) > 0 for u in uwins):
            primary, primary_src = ufros, SRC_UFRO
            if any(_num(u) > 0 for u in ufros):
                flags.append(FLAG_LIFECYCLE_FEE_FALLBACK)
    else:
        primary, primary_src = ufros, SRC_UFRO

    amount, source, disagree = _frozen_resolve(pkg_ptp, primary)
    if disagree:
        flags.append(FLAG_PTP_UFRO_DISAGREE)
    if source == "UFRO_SUM":
        source = primary_src
    return ResolvedUpfront(amount, source, tuple(flags))


def orientation(npv_pay: float, *, is_lifecycle: bool = False) -> int:
    """``+1`` when a positive residual means the dealer RECEIVED fixed.

    ``sign(-f)`` on a new trade -- the dealer holding the ITM side means the
    dealer received when the receive side is the ITM one, i.e. when ``f < 0``.
    Negated on a lifecycle row, where holding the ITM side means ``U > |f|``.
    Returns ``0`` at ``f == 0``, where the ITM side is undefined and no fee,
    however large, can orient anything.

    This reads the **raw** NPV, so it is only the orientation when the mid it
    was priced against is the one you believe. :func:`classify` orients off its
    bias-corrected deviation instead -- identical whenever ``mid_bias_bps`` is
    zero, and deliberately different when it is not.
    """
    s = (1 if npv_pay < 0 else -1 if npv_pay > 0 else 0)
    return -s if is_lifecycle else s


def residual_bps(npv_pay: float, upfront: float, structure_dv01: float, *,
                 bias_bps: float = 0.0) -> float:
    """``z = (|f| - U) / DV01 - b0``, in bp. Direction-blind, by construction.

    This is the statistic the mixture is fitted on, and it must not know the
    answer: it is identical for a print and its mirror image. The ``+-h``
    separation in its distribution comes from the unobserved side, which is what
    makes the fit meaningful rather than circular.
    """
    dv01 = _positive_dv01(structure_dv01)
    return (abs(float(npv_pay)) - float(upfront)) / dv01 - float(bias_bps)


def signed_edge_bps(npv_pay: float, upfront: float, structure_dv01: float, *,
                    is_lifecycle: bool = False, bias_bps: float = 0.0) -> float:
    """The dealer's edge in bp, signed towards ``p(dealer received fixed)``."""
    return orientation(npv_pay, is_lifecycle=is_lifecycle) * residual_bps(
        npv_pay, upfront, structure_dv01, bias_bps=bias_bps,
    )


def p_from_edge(edge_bps: float, tau_bps: float) -> float:
    """``sigma(edge / tau)`` -- the same logistic form as the rate rule.

    Only ``tau`` differs, and only because it is fitted on a different
    statistic; the functional form is the same Bayes posterior under a symmetric
    two-component model, so the two rules produce comparable probabilities.
    """
    if tau_bps is None or tau_bps <= 0:
        raise ValueError(f"tau must be positive, got {tau_bps!r}")
    z = float(edge_bps) / float(tau_bps)
    if z >= 0:                       # overflow-safe both ways
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def p_marginalised(dev_bps: float, upfront_bps: float, tau_bps: float, *,
                   mid_sigma_bps: float, bias_bps: float = 0.0,
                   is_lifecycle: bool = False) -> float:
    """``p`` integrated over the mid's own measurement error.

    The edge is ``x(d) = d - sign(d) * (u + b0)`` in the true deviation ``d``,
    which is **discontinuous at ``d = 0``** -- it jumps by ``2(u + b0)``. That
    discontinuity is the rule, not an artefact: a print one hundredth of a basis
    point either side of mid gets opposite answers with the fee's full
    confidence. Since ``d`` is only known to within ``s``, the honest answer is
    the average over ``d ~ N(dev_bps, s^2)``, which collapses to 0.5 exactly
    where the two branches are equally likely. ``dev_bps`` is the deviation the
    caller believes -- :func:`classify` has already taken its ``mid_bias_bps``
    off it, so the mean of that Gaussian is the corrected deviation and the
    branch the print falls in is decided on the corrected one too.

    **The integral is split at the jump, and it has to be.** Gauss-Hermite is
    polynomial-exact against a Gaussian weight, so it converges on smooth
    integrands and does not converge on a discontinuous one -- raising the node
    count moves the nodes, it does not fix the rule. Laid across this kink,
    40-node Gauss-Hermite made ``p`` a *staircase* in ``dev``, flat between node
    positions and then jumping 0.19; on the real 2,025-print flow sample the
    error reached 0.030 in ``p`` and **27 prints (1.3%) came back with
    ``signed_weight`` of the wrong sign**. The error is a deterministic function
    of ``|dev|/s``, so it does not average out of a ladder, and it grows as
    ``tau`` shrinks -- the direction this calibration is trying to go.

    Each branch on its own *is* smooth, so the fix is to integrate them
    separately: ``d < 0`` with ``edge = d + c`` and ``d >= 0`` with
    ``edge = d - c``, ``c = u + b0``. Neither branch has an elementary closed
    form -- a logistic against a Gaussian is the standard non-elementary
    integral -- so each is done by panelled Gauss-Legendre with the kink on a
    panel edge, which ties out to 1.8e-14 (see :data:`_GL_NODES`). Still
    deterministic, which is what matters when the output gets differenced; about
    100 us a call against the old 20, and wrong 1.3% of the time was not worth
    80 us.
    """
    tau = float(tau_bps)
    if not tau > 0:
        raise ValueError(f"tau must be positive, got {tau_bps!r}")
    dev = float(dev_bps)
    c = float(upfront_bps) + float(bias_bps)
    s = float(mid_sigma_bps)
    if not (math.isfinite(dev) and math.isfinite(c) and math.isfinite(s)):
        raise ValueError(
            f"p_marginalised(dev={dev_bps!r}, upfront={upfront_bps!r}, "
            f"bias={bias_bps!r}, mid_sigma={mid_sigma_bps!r}): a non-finite "
            "input leaves every branch test false and returns 0.0, which is a "
            "perfectly valid-looking probability and the most confident one "
            "there is"
        )
    if s <= 0:
        return p_from_edge(
            _edge_from_dev(dev, upfront_bps, bias_bps, is_lifecycle), tau,
        )

    beta = s / tau                     # logistic steepness in sigma units
    t_kink = -dev / s                  # where d = 0 lands in sigma units
    p = 0.0
    if t_kink > -_TAIL_SIGMAS:         # the d < 0 branch: edge = d + c
        p += _logistic_normal_segment(
            -_TAIL_SIGMAS, min(t_kink, _TAIL_SIGMAS), beta, (-c - dev) / s)
    if t_kink < _TAIL_SIGMAS:          # the d >= 0 branch: edge = d - c
        p += _logistic_normal_segment(
            max(t_kink, -_TAIL_SIGMAS), _TAIL_SIGMAS, beta, (c - dev) / s)
    return 1.0 - p if is_lifecycle else p


def fit_tau_upfront(residuals, *, population: str, bucket: str = "ALL",
                    mixture_fit=None) -> TauUpfront:
    """Fit ``tau_upfront`` on a sample of ``z`` values, using probability.py.

    ``mixture_fit`` is the dependency, injected: a callable taking the sample
    and returning ``(b0, h, s)`` -- as a triple, a mapping, or an object with
    those attributes. Left ``None`` it resolves ``probability.fit_mixture``,
    which is where the rate rule's fitter lives. Nothing is fitted locally: the
    whole point of ``tau = s^2/(2h)`` is that the two rules share an estimator
    and differ only in what it is pointed at.

    Whatever the fitter reports about the *quality* of its fit -- ``flags`` in
    ``probability.MixtureFit``, e.g. ``LEPTOKURTIC_MOMENT_CHECK_FAILED`` or
    ``N_BELOW_MINIMUM`` -- lands on :attr:`TauUpfront.fallback` verbatim rather
    than being re-invented here, so one vocabulary describes both rules'
    calibrations. That matters on ``z``: every bucket measured so far is
    leptokurtic, so the flag is the normal case, not an alarm.
    """
    x = np.asarray([float(v) for v in residuals], dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2:
        raise ValueError(f"a mixture needs a sample, got {x.size} usable values")

    fitter = mixture_fit if mixture_fit is not None else _resolve_mixture_fit()
    if not callable(fitter):
        raise MixtureFitUnavailable(
            f"mixture_fit={fitter!r} is not callable. It must be "
            "dealer_direction.probability's symmetric two-component fitter, or "
            "anything with its contract: sample -> (b0, h, s)."
        )
    # `probability.fit_mixture` requires a keyword-only `bucket`. Decided by
    # introspection, not by catching TypeError: a TypeError raised *inside* a
    # fitter that happens to take a bucket would then be silently retried
    # without one, which is how a fallback path starts serving the main case.
    fit = (fitter(x, bucket=bucket) if _accepts_kwarg(fitter, "bucket")
           else fitter(x))
    b0, h, s = _unpack_mixture(fit)
    tau_reported = getattr(fit, "tau", None)
    flags = tuple(getattr(fit, "flags", ()) or ())
    if not (h > 0 and s > 0):
        raise ValueError(
            f"the mixture fit returned h={h!r}, s={s!r}; tau = s^2/(2h) is "
            "undefined and a degenerate fit must not be turned into a "
            "confident probability"
        )
    # The fitter's own `tau` when it has one: `probability.MixtureFit.tau`
    # floors `h` at `MIN_SEPARATION * s`, which caps tau at the no-information
    # limit instead of letting it run to infinity. Recomputing s^2/(2h) here
    # would discard that floor and hand back a wilder number than the estimator
    # itself is willing to stand behind.
    tau_bps = float(tau_reported) if tau_reported is not None else s * s / (2.0 * h)
    return TauUpfront(
        tau_bps=tau_bps, bias_bps=b0, half_spread_bps=h,
        sigma_bps=s, n=int(x.size), population=population, bucket=bucket,
        fallback=(",".join(flags) if flags and tuple(flags) != ("OK",) else None),
    )


def robust_tau_upfront(residuals, *, population: str, bucket: str = "ALL",
                       reason: str = "LEPTOKURTIC") -> TauUpfront:
    """A ``tau`` from the robust scale of ``z``, for when there is no fitter.

    **Not the default, and deliberately so.** ``probability.fit_mixture`` has
    its own robust fallback and floors ``h``, which caps ``tau`` at the
    no-information limit -- 3.8 bp on the measured flow population. The MAD
    scale is 0.26 bp there, i.e. **fifteen times more confident**, so reaching
    for this function is a decision to claim precision the mixture fit declined
    to claim. It exists for the case where the fitter is unavailable or raises,
    and it records itself in :attr:`TauUpfront.fallback` so the choice is
    visible in provenance rather than inferred from a suspiciously sharp ``p``.

    Every bucket of ``z`` measured is leptokurtic (excess kurtosis +3.4 to +34),
    so the moment closed form ``s^2 = m2 - sqrt(m2^2 - (m4 - m2^2)/2)`` has no
    real solution: ``z`` is a spike at zero with heavy tails, not two separated
    components. ``half_spread_bps`` is left NaN rather than zero so that nothing
    downstream can multiply by it and get an answer.
    """
    x = np.asarray([float(v) for v in residuals], dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2:
        raise ValueError(f"a scale needs a sample, got {x.size} usable values")
    med = float(np.median(x))
    scale = 1.4826 * float(np.median(np.abs(x - med)))
    if not scale > 0:
        raise ValueError(
            f"the robust scale of this bucket is {scale!r}; a zero-width "
            "residual means every call would be certain"
        )
    return TauUpfront(tau_bps=scale, bias_bps=med, half_spread_bps=float("nan"),
                      sigma_bps=scale, n=int(x.size), population=population,
                      bucket=bucket, fallback=reason)


def classify(*, npv_pay, upfront, structure_dv01, upfront_source: str | None = None,
             is_lifecycle: bool = False, is_capped: bool = False,
             tau: TauUpfront | None = None, mid_sigma_bps: float | None = None,
             mid_bias_bps: float = 0.0, flags=(),
             exclude_capped: bool | None = None) -> UpfrontCall:
    """The upfront rule for one unit.

    ``dealer_sign`` is :data:`conventions.DEALER_RECEIVED` /
    ``DEALER_PAID`` / ``0``, and on a lifecycle row it is **the side the dealer
    held on the swap being torn up**. A consumer that wants the risk *flow* of
    the unwind must negate it, because unwinding a received-fixed position sheds
    duration.

    ``p`` is only produced when a ``tau`` for this unit's population is given.
    That is deliberate for lifecycle rows: the confidence model does not
    transfer, so the default is a sign with no probability rather than a
    probability that is wrong by a factor.

    **``dealer_sign`` and ``signed_weight`` are two different estimators and
    they are allowed to disagree -- but only inside the flagged set.**
    ``dealer_sign`` is the point call, the frozen classifier's answer, which
    takes the mid at face value. ``signed_weight`` comes from ``p``, which
    (given ``mid_sigma_bps``) averages over the mid's error and so discounts the
    fee's contribution by how sure we are which side of mid the print is on.
    Where the two conclusions differ the print is within the mid error of a
    boundary, so :data:`FLAG_SIGN_FRAGILE` fires. Measured: on 282,240 grid
    points spanning sigma 0.05-1.0 bp, tau 0.5-11 bp and both populations, every
    one of the 15,032 disagreements is flagged and the worst sits at 0.997 sigma
    from the ``z`` boundary against a flag that fires at 2. On the real 2,025
    print flow sample they disagree on 140 rows carrying 0.17% of the total
    absolute weight (max ``|signed_weight|`` 0.011).

    That is *not* the failure this docstring's predecessor had, where the two
    read different deviations -- one bias-corrected, one raw -- and could
    disagree with ``|signed_weight| = 0.29`` on a print 0.3 bp from mid with the
    flag silent.
    """
    flags = list(flags)
    dv01 = _positive_dv01(structure_dv01)
    population = POPULATION_LIFECYCLE if is_lifecycle else POPULATION_FLOW

    if tau is not None and tau.population != population:
        raise ValueError(
            f"tau was fitted on population {tau.population!r} and this unit is "
            f"{population!r}. Flow and lifecycle prints are separated because "
            "a seasoned unwind is a hundred basis points from mid and would "
            "score as maximal confidence under the flow calibration."
        )

    # The mid calibration is not per-row data, so a non-finite value here is a
    # programming error rather than an outcome the coverage accounting has a
    # name for -- refused, not excluded. Left through, a NaN bias makes every
    # deviation NaN and (with no tau) returns `dealer_sign = 0, exclusion =
    # None`, which is indistinguishable from an exact tie; a NaN sigma makes
    # FLAG_SIGN_FRAGILE unable to fire at all.
    if not np.isfinite(float(mid_bias_bps)):
        raise ValueError(
            f"mid_bias_bps={mid_bias_bps!r} is not finite; every deviation "
            "would be NaN and, with no tau, would come back as an exact tie"
        )
    if mid_sigma_bps is not None and not np.isfinite(float(mid_sigma_bps)):
        raise ValueError(
            f"mid_sigma_bps={mid_sigma_bps!r} is not finite; the comparison "
            "against it is false for every input, so FLAG_SIGN_FRAGILE could "
            "never fire and its absence would read as a solid sign"
        )

    if upfront is None or not np.isfinite(float(upfront)):
        return UpfrontCall(None, None, None, None, 0, population=population,
                           mid_bias_bps=float(mid_bias_bps),
                           flags=tuple(flags), exclusion=EXCL_NO_UPFRONT)

    # The same gate on the other side of the comparison. Without it a failed
    # repricing came back `dealer_sign = 0, exclusion = None`, which reads
    # downstream as a unit that WAS classified and happened to tie -- so it
    # lands in the coverage numerator instead of the failure column.
    if npv_pay is None or not np.isfinite(float(npv_pay)):
        return UpfrontCall(None, None, None, None, 0, population=population,
                           upfront_source=upfront_source,
                           mid_bias_bps=float(mid_bias_bps),
                           flags=tuple(flags), exclusion=EXCL_PRICING_ERROR)

    upfront = float(upfront)
    if upfront < 0.0:
        raise ValueError(
            f"upfront={upfront!r}. `#58 Other payment amount` is disseminated "
            "as any value greater than or equal to zero, and the rule is "
            "derived from U >= 0; a negative makes z = |dev| - U bigger, so a "
            "corrupt fee would come back as a MORE confident call"
        )
    if upfront < stir_config.PTP_USD_FLOOR:
        flags.append(FLAG_TINY_UPFRONT)

    if exclude_capped is None:
        exclude_capped = CAPPED_UPFRONT_IS_UNSCALED
    if is_capped and exclude_capped:
        return UpfrontCall(None, None, None, None, 0, population=population,
                           upfront_source=upfront_source,
                           mid_bias_bps=float(mid_bias_bps),
                           flags=tuple(flags), exclusion=EXCL_CAPPED_UPFRONT)

    bias = tau.bias_bps if tau is not None else 0.0
    dev = -float(npv_pay) / dv01 - float(mid_bias_bps)
    u_bps = upfront / dv01
    z = abs(dev) - u_bps - bias
    # Orientation off the bias-corrected `dev`, NOT off the raw npv_pay: a mid
    # bias moves the mid, so it moves which side of it the print is on. Reading
    # the magnitude from `dev` and the sign from `npv_pay` disagreed with `p`
    # on every row where the bias crossed mid. Identical when the bias is zero.
    edge = _edge_from_dev(dev, u_bps, bias, is_lifecycle)

    if mid_sigma_bps is None:
        flags.append(FLAG_NO_MID_SIGMA)
    elif min(abs(dev), abs(z)) <= FRAGILE_SIGMA_MULT * float(mid_sigma_bps):
        # BOTH boundaries: sign(edge) turns over at dev in {-c, 0, +c}, so the
        # sign is a coin flip within the mid error of `dev` OR of `z`.
        flags.append(FLAG_SIGN_FRAGILE)

    p = sw = None
    if tau is not None:
        if mid_sigma_bps is None:
            p = p_from_edge(edge, tau.tau_bps)
        else:
            p = p_marginalised(dev, u_bps, tau.tau_bps,
                               mid_sigma_bps=mid_sigma_bps, bias_bps=bias,
                               is_lifecycle=is_lifecycle)
        sw = conventions.signed_weight(p)

    return UpfrontCall(
        dev_bps=dev, upfront_bps=u_bps, residual_bps=z, edge_bps=edge,
        dealer_sign=conventions.dealer_side(edge), p=p, signed_weight=sw,
        population=population, upfront_source=upfront_source,
        tau_bps=(tau.tau_bps if tau is not None else None),
        tau_bucket=(tau.bucket if tau is not None else None),
        bias_bps=bias, mid_bias_bps=float(mid_bias_bps), flags=tuple(flags),
    )


# --- internals ------------------------------------------------------------

def _num(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f != f else f


def _positive_dv01(structure_dv01) -> float:
    dv01 = abs(float(structure_dv01))
    if not dv01 > 0:
        raise ValueError(
            f"structure_dv01={structure_dv01!r}; an edge in bp is a dollar "
            "amount divided by a DV01, and a zero DV01 unit has no bp scale"
        )
    return dv01


def _normal_mass(lo: float, hi: float) -> float:
    """``Phi(hi) - Phi(lo)``, arranged so neither end cancels.

    Taking the difference of two CDFs that are both within 1e-19 of 1 loses
    every significant digit, and this is used precisely on the saturated tail
    where that happens.
    """
    if hi <= lo:
        return 0.0
    if hi <= 0.0:
        return 0.5 * (math.erfc(-hi / _SQRT2) - math.erfc(-lo / _SQRT2))
    if lo >= 0.0:
        return 0.5 * (math.erfc(lo / _SQRT2) - math.erfc(hi / _SQRT2))
    return 1.0 - 0.5 * (math.erfc(-lo / _SQRT2) + math.erfc(hi / _SQRT2))


def _logistic_normal_segment(lo: float, hi: float, beta: float,
                             a: float) -> float:
    """``int_lo^hi sigma(beta * (t - a)) phi(t) dt``, ``t`` in sigma units.

    One smooth branch of :func:`p_marginalised`'s integrand. Panelled
    Gauss-Legendre, one sigma per panel or one logistic width if that is
    narrower, so the number of nodes is bounded whatever ``beta`` is: the
    transition occupies ``80/beta`` and the panels are ``1/beta``, so it is at
    most 80 panels when the logistic is the sharp factor and at most 18 when the
    Gaussian is.
    """
    if hi <= lo:
        return 0.0
    reach = _LOGISTIC_SATURATION / beta
    lo_sat = min(max(lo, a - reach), hi)     # below this the logistic is 0
    hi_sat = max(min(hi, a + reach), lo)     # above this the logistic is 1
    total = _normal_mass(hi_sat, hi)
    if hi_sat > lo_sat:
        width = min(_PANEL_SIGMAS, 1.0 / beta)
        n = max(1, int(math.ceil((hi_sat - lo_sat) / width)))
        edges = np.linspace(lo_sat, hi_sat, n + 1)
        centre = (0.5 * (edges[:-1] + edges[1:]))[:, None]
        radius = (0.5 * (edges[1:] - edges[:-1]))[:, None]
        t = centre + radius * _GL_NODES[None, :]
        f = (_INV_SQRT_2PI * np.exp(-0.5 * t * t)
             / (1.0 + np.exp(-np.clip(beta * (t - a), -500.0, 500.0))))
        total += float((f * (_GL_WEIGHTS[None, :] * radius)).sum())
    return total


def _edge_from_dev(dev_bps, upfront_bps, bias_bps, is_lifecycle) -> float:
    s = (1 if dev_bps > 0 else -1 if dev_bps < 0 else 0)
    e = s * (abs(float(dev_bps)) - float(upfront_bps) - float(bias_bps))
    return -e if is_lifecycle else e


def _accepts_kwarg(fn, name: str) -> bool:
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    for p in sig.parameters.values():
        if p.name == name or p.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return False


def _resolve_mixture_fit():
    try:
        from SDRUtils.dealer_direction import probability
    except ImportError as exc:                 # pragma: no cover - build order
        raise MixtureFitUnavailable(
            "dealer_direction.probability is not importable, so tau_upfront "
            "cannot be fitted with the same estimator as the rate rule. Pass "
            "mixture_fit=<callable: sample -> (b0, h, s)> explicitly, or "
            f"install the module. ({exc})"
        ) from exc
    for name in _MIXTURE_FIT_NAMES:
        fn = getattr(probability, name, None)
        if callable(fn):
            return fn
    raise MixtureFitUnavailable(
        "found dealer_direction.probability but none of "
        f"{_MIXTURE_FIT_NAMES} on it. tau_upfront must be fitted by the rate "
        "rule's own symmetric two-component fitter -- sample -> (b0, h, s) -- "
        "not by a second copy of it. Pass mixture_fit= explicitly if the "
        "fitter is spelled differently."
    )


def _unpack_mixture(fit):
    """Accept the fitter's result as a triple, a mapping, or an object."""
    if isinstance(fit, dict):
        return float(fit["b0"]), float(fit["h"]), float(fit["s"])
    if all(hasattr(fit, a) for a in ("b0", "h", "s")):
        return float(fit.b0), float(fit.h), float(fit.s)
    try:
        b0, h, s = fit
    except (TypeError, ValueError) as exc:
        raise MixtureFitUnavailable(
            f"the mixture fitter returned {fit!r}, which is not (b0, h, s), a "
            "mapping with those keys, or an object with those attributes"
        ) from exc
    return float(b0), float(h), float(s)


__all__ = [
    "CAPPED_UPFRONT_IS_UNSCALED", "EXCL_CAPPED_UPFRONT", "EXCL_NO_UPFRONT",
    "EXCL_PRICING_ERROR", "FRAGILE_SIGMA_MULT",
    "FLAG_LIFECYCLE_FEE_FALLBACK", "FLAG_NO_MID_SIGMA",
    "FLAG_PTP_UFRO_DISAGREE", "FLAG_SIGN_FRAGILE", "FLAG_TINY_UPFRONT",
    "LIFECYCLE_SIGN_MEANS_SIDE_HELD", "MixtureFitUnavailable",
    "POPULATION_FLOW", "POPULATION_LIFECYCLE", "ResolvedUpfront", "SRC_PTP",
    "SRC_UFRO", "SRC_UWIN", "TauUpfront", "UpfrontCall", "classify",
    "fit_tau_upfront", "orientation", "p_from_edge", "p_marginalised",
    "residual_bps", "resolve_upfront", "robust_tau_upfront", "signed_edge_bps",
]
