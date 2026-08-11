"""``RULE_PACKAGE_PRICE`` -- orienting a ``PKG-N`` from its one package price.

WHY THIS EXISTS
---------------

``EXCL_UNORIENTABLE_PKG`` is **39.97% of tape DV01** and the exclusion is not
random: the ``PKG-4+`` half of it is **97.9% D2C** against 82.1% for what is
kept, and carries **28.7% of its DV01 in block legs** against 11.1% -- the
largest, most customer-facing prints on the tape. It is also what produces the
**1.54x cross-bucket retention distortion** measured in
``docs/dealer_direction/2026-08-11-package-exclusion-skew.md``, which is what
makes a cross-sectional read of the ladder unsupportable.

``conventions.base_orientation`` refuses a ``PKG-N`` under
:data:`~.conventions.RULE_RATE`, and it is right to: there is no market quote
convention that says which legs of a seventeen-leg package the customer paid
fixed on, and inventing one manufactures a confident direction from nothing.
**That refusal stands.** This module does not relax it and ``conventions.py``
is untouched -- a test in this package's suite asserts it still raises.

What a ``PKG-N`` *does* have is **one price**. This module orients the package
from that price instead of from a quote convention.

THE IDENTIFICATION -- WHERE THE BIT ACTUALLY COMES FROM
-------------------------------------------------------

Write ``f_i`` for the leg's NPV to the fixed **payer** at the repriced mid,
``(M_i - R_i) * 100 * PV01_i``, and ``o_i in {+1,-1}`` for the base party's
``pay_signs`` (``conventions.py``'s polarity: ``+1`` = this party pays fixed).
The base party's position is worth

::

    V = sum(o_i * f_i)

and it hands over cash ``C``. A fair trade is ``C = V`` -- you pay what you get
-- so

::

    deviation = C - V > 0   =>   the base party overpaid
                            =>   the base party is the CUSTOMER
                            =>   the dealer holds  -o

which is exactly :func:`conventions.dealer_side`'s general rule with the
package's price in dollars rather than a structure's price in bp. Nothing new
is assumed. The whole problem is therefore ``o``, and ``o`` comes from the
cash, not from a guess:

* ``#58 Other payment amount`` is disseminated **unsigned** (spec: "any value
  greater than or equal to zero"), and ``#61 payer`` / ``#62 receiver`` are not
  disseminated at all. So a leg's fee says *how much* moved, never *which way*.
* The **package** price ``PTP`` is the net of those flows. So the per-leg cash
  signs ``s_i`` are pinned by ``sum(s_i * OPA_i) = PTP`` -- which is precisely
  the problem :mod:`SDRUtils.packages.opa_sign_solver` already solves, exactly
  for ``N <= 24`` (meet-in-the-middle) and greedily above.
* The physical constraint that closes it is the same one ``upfront.py`` is
  built on: **the cash flows from the party receiving value to the party giving
  it up.** So the party that pays leg ``i``'s fee is the one taking leg ``i``'s
  in-the-money side, and the ITM side of a swap is *pay fixed* exactly when
  ``f_i > 0``::

      o_i = s_i * sign(f_i)

**Two independent data sources, so this is not circular.** ``s`` is solved from
*reported* quantities only (the legs' fees against the package price); ``f``
comes from the repriced curve. The residual ``C - V`` is then a comparison
between the two, and its sign is not forced by either. The forbidden variant --
choosing ``o`` to make ``|V|`` match the fee and then reading ``sign(|V| - U)``
-- would drive the residual to zero by construction and is not implemented.

THE GLOBAL FLIP IS THE DEGREE OF FREEDOM, NOT A DEFECT
-------------------------------------------------------

``upfront.py``'s docstring records that the sign solver is "direction-blind *by
symmetry*": a sign vector and its complement score identically. That symmetry
is exactly what this rule consumes. Under ``s -> -s``: ``o -> -o``, ``V -> -V``,
``C -> -C``, so ``deviation -> -deviation`` and ``dealer_sign -> -dealer_sign``
-- and the only thing anyone downstream reads,

::

    received_signs = dealer_sign * o

is **unchanged**. Which branch the solver's tie-break returns therefore cannot
reach the ladder. A test negates the package price and asserts it.

The consequence for the API is worth stating plainly: for a package,
``dealer_sign`` **is not** "the dealer received fixed". It is the general
rule's bit relative to *this unit's* base orientation, and it is meaningless
without the ``base_orientation`` beside it. ``received_signs`` is the
orientation-free answer and is what a consumer should read.

|V| SURVIVES A PER-LEG SIGN ERROR; THE PER-LEG KRD DOES NOT
------------------------------------------------------------

Substituting ``o_i = s_i * sign(f_i)`` collapses the model price to

::

    V = sum(s_i * |f_i|)

so an error in ``sign(f_i)`` **cannot** move ``V`` -- the two sign factors
cancel. The direction call is therefore robust to legs sitting near mid. The
*key-rate profile* is not: that leg's own ``received_sign`` is
``dealer_sign * s_i * sign(f_i)`` and a near-mid ``sign(f_i)`` is a coin flip.
Legs inside :data:`LEG_SIGN_RESOLUTION_BPS` of mid are flagged
(:data:`FLAG_LEG_NEAR_MID`) and their PV01 is reported on the call
(``unresolved_pv01``) rather than being quietly signed; a leg exactly at mid is
refused outright, because there ``sign(f_i)`` is not merely noisy but undefined.

WHAT IS AND IS NOT RECOVERABLE
-------------------------------

Gated in this order, one named stratum each, so the coverage accounting adds up
the way ``types.py``'s vocabulary intends:

``NO_PACKAGE_PRICE``
    ``|PTP| <= PTP_USD_FLOOR``. **Measured, and it corrects the brief.** The
    claim that the ``PKG-4+`` package price is "verified non-degenerate,
    notation 1 or 3" is a *pooled* statistic. Split by notation, over all
    47,021 ``PKG-4+`` packages in the pinned window:

    ==========================  =======  ================  ==============
    ``ptp_price_notation``      n        median ``|PTP|``   ``|PTP|==10``
    ==========================  =======  ================  ==============
    1 (monetary)                 43,543        $291,737             0.0%
    3 (decimal)                   2,550          $10.00            86.5%
    (null)                          928        $2,556.00            0.0%
    ==========================  =======  ================  ==============

    97.6% of the notation-3 prices are at or below the floor and 86.5% are
    literally ``10.00`` -- the ``9.9999999999`` not-available sentinel. So
    notation 3 is **degenerate**, contributing 0.095% of ``PKG-4+`` DV01 to the
    recovery against 4.16% refused, while notation 1 supplies 68.3 of the 68.4
    points recovered. The frozen ``PTP_USD_FLOOR = 500`` removes the sentinel
    on its own, which is why this module reads **no notation column at all**
    (there is none on the legs table anyway -- it lives on the packages table
    as ``ptp_price_notation``): the floor plus the tie-out is an economic test,
    and a notation label is not.
``OPA_MISSING``
    Some leg carries no fee, so its cash sign is undetermined. Its ``|f_i|``
    still belongs in ``V``, so it cannot be dropped and the package is refused.
``TIEOUT_FAIL``
    No sign vector gets within :data:`TIEOUT_MAX_BPS` of the package price. The
    orientation would be a guess. This is the gate with teeth: on the measured
    tape 11.3% of ``PKG-4+`` packages have ``|PTP| > sum|OPA|``, which no signed
    sum of the fees can reach.
``LEG_AT_MID`` / ``PRICING_ERROR``
    ``f_i = 0`` exactly, or an unpriced leg / unusable DV01.

**Asset swaps are not recoverable this way and are not attempted.** The bond is
identified (``ust_cusip`` on 48%) but not priced on this tape, so no ``f_i``
exists for the leg that matters. ``EXCLUDED_TRADE_TYPES`` keeps them out ahead
of this gate, which is why :func:`tape_gate` never sees them.

THE KNOWN-ANSWER GATE -- MEASURED, NOT ASSERTED
------------------------------------------------

``conventions.base_orientation`` fixes the answer for a ``CURVE`` and a
``FLY``. Run this rule on real fee-bearing prints over 12 days spread across
the pinned window and ask whether the fee-derived ``o`` reproduces it:

===================================  ======  ==========  =========
population (12 days, real prints)    n       match       by chance
===================================  ======  ==========  =========
tape ``package_type = CURVE``           982      94.70%        50%
  ... worst leg >= 0.25 bp from mid     887      98.20%        50%
  ... worst leg >= 1.00 bp from mid     786      98.85%        50%
tape ``package_type = FLY``             437      91.08%        25%
  ... worst leg >= 0.25 bp from mid     362      97.51%        25%
  ... worst leg >= 1.00 bp from mid     303      99.01%        25%
===================================  ======  ==========  =========

**The conditioning on the tape's own ``package_type`` is the point, not a
filter chosen to flatter the number.** ``universe.unit_frame`` names a unit
``CURVE`` on **leg count alone**, and ``conventions.base_orientation`` then
asserts one payer and one receiver -- which is simply not true of a 2-leg
package that is a strip, a roll or a block split. Unconditionally the match is
86.09% (CURVE) and 69.86% (FLY); split by what the tape's DV01-neutrality
detector says, the genuine curves and flies come in at 94.7% / 91.1% and the
``PKG-2`` / ``PKG-3`` residue at 72.8% / 33.2% -- and 33.2% on a 3-leg unit is
*chance*, which is what "this convention does not apply here" looks like.

**The misses are the documented failure mode, not a second one.** Median
distance from mid of the worst leg is **0.085 bp on the misses against 3.465 bp
on the hits**: they are the near-mid legs where ``sign(f_i)`` is a coin flip,
exactly the population :data:`FLAG_LEG_NEAR_MID` marks. Restricting to units
whose worst leg is resolvable takes both structures to 98-99%.

A corollary worth keeping: ``opa_sign_solver``'s own absolute confidence tiers
are **anti**-informative here -- ``EXACT`` (residual < $100) matches 78.6% and
``LOOSE`` (< $50k) matches 98.2%, because a $100 residual means a small package
and a small package is a near-mid one. That is why :data:`TIEOUT_MAX_BPS` is in
bp.

AGREEING WITH THE RATE RULE IS NOT THE BAR -- 50% IS
------------------------------------------------------

On the same genuine CURVE/FLY population the per-leg ``received_signs`` agree
with :data:`~.conventions.RULE_RATE`'s answer **45.95%** of the time, flat
across the rate deviation (44.7% / 44.3% / 47.9% / 46.2% over |dev| bands from
0 to 50 bp). That is the expected number, and the derivation says so before the
measurement does: this rule's answer is ``sign(C - V)`` and the rate rule's is
``sign(-V)``, so the two agree **iff the cash under-compensates the off-market
value**. For an outright that is the frozen pair -- ``RULE_UPFRONT`` and
``RULE_RATE`` agree iff ``U < |f|`` -- and ``upfront.py`` measures ``U/|dev|``
at a median of **0.9996** on 2,025 fee-bearing flow outrights. The fee sits
*on* the value, so which side of it a print lands is near a coin flip and ~50%
is what two correct rules look like. **100% would mean the fee carried no
information at all**, and a sign bug would show a gradient with |dev| rather
than a flat line; there is none.

WIRING -- ONE LINE THIS MODULE CANNOT WRITE FOR ITSELF
--------------------------------------------------------

Routing recovered ``PKG-N`` units into the kept universe puts them in front of
:mod:`.krd`, which they never reached before. ``krd.received_hypothesis_signs``
dispatches on ``(kind, n_legs, rule)`` through ``conventions``, and for a
``PKG-N``:

* under ``RULE_RATE`` it raises ``UnorientableUnit`` -- loud, fine;
* under ``RULE_UPFRONT`` it returns ``(1,) * n``, **every leg the same sign**.

The second is the hazard: a recovered package has an upfront (its ``PTP``), so
a consumer routing on upfront presence lands there and gets a package's whole
key-rate profile pointed one way. It is not a new bug -- it is what
``RULE_UPFRONT`` has always done to a multi-leg unit -- but this module is the
first thing that knows better, so :func:`received_hypothesis_signs` here is the
per-unit replacement and a test pins the difference. Consumers must route a
unit carrying a :data:`RULE_PACKAGE_PRICE` call through *this* function.

THE BP DENOMINATOR IS A CHOICE, AND IT IS THE ONE ALREADY MADE
----------------------------------------------------------------

``deviation_bps = deviation_dollars / structure_dv01``, and for a ``PKG-N``
``midprice.structure_dv01`` is ``sum(|pv01|) / 2`` -- the midpoint of the range
the unknown internal orientation permits. Now that ``o`` is knowable,
``|sum(o_i * pv01_i)|`` is computable, and it is deliberately **not** used: a
curve-shaped package's net DV01 is near zero while its bid-offer is not, so
that denominator sends the deviation of exactly the most balanced packages to
infinity. The choice sets the scale of any ``tau`` fitted on these residuals,
so it must not be changed without refitting.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions
from SDRUtils.dealer_direction import types as dd_types
from SDRUtils.packages.opa_sign_solver import solve_opa_signs
from SDRUtils.stir_flow import config as stir_config

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

#: A third inference rule, beside :data:`conventions.RULE_RATE` and
#: :data:`conventions.RULE_UPFRONT`. Named here rather than in
#: ``conventions.py`` because that module is pinned and its two rules are
#: tie-out surface against the frozen predecessor.
RULE_PACKAGE_PRICE = "PACKAGE_PRICE_VS_MODEL"

#: Carried from the frozen ``stir_flow.config``, not re-declared. A package
#: price below this is a notation artefact rather than dollars -- it is what
#: keeps the ``9.9999999999`` sentinel out without reading a notation column.
PTP_USD_FLOOR = stir_config.PTP_USD_FLOOR

#: Also carried. When the package price and the summed ``UFRO`` legs are more
#: than this far apart, both cannot be the same fee; the call still comes out
#: (the frozen rule keeps the PTP) but it is flagged.
PTP_UFRO_DISAGREE_RATIO = stir_config.PTP_UFRO_DISAGREE_RATIO

#: How close ``sum(s_i * OPA_i)`` must get to the package price, in bp of the
#: package's own DV01, for the sign vector to be evidence rather than a fit.
#:
#: **In bp, not dollars, and that is the correction.** ``opa_sign_solver``'s own
#: tiers are absolute -- ``EXACT`` < $100, ``TIGHT`` < $1k, ``LOOSE`` < $50k --
#: and $50,000 is 5 bp on a $10k/bp package and 0.1 bp on a $500k/bp one. The
#: same label therefore means two entirely different qualities of evidence, and
#: measured on the real tape the absolute tiers are **anti**-informative:
#: ``EXACT`` matches the known orientation 78.6% of the time and ``LOOSE``
#: 98.2%. Rescaled to bp the gate says the unexplained cash is inside a
#: plausible package bid-offer.
#:
#: **Where 1.0 comes from.** Over all 47,021 ``PKG-4+`` packages in the pinned
#: window the residual distribution is p50 0.035, p75 0.199, p90 0.805,
#: p95 2.02, p99 16.8 bp, and the DV01 kept as the gate moves is::
#:
#:     0.05 bp -> 72.7%   0.25 -> 86.5%   0.50 -> 90.2%
#:     1.00 bp -> 92.5%   2.00 -> 94.4%   5.00 -> 96.2%
#:
#: -- a smooth region with no cliff, so the constant is not sitting on a
#: discontinuity and the cost of any other choice is on the record. It is set
#: at 1.0 rather than tighter because **tightening buys no accuracy**: the
#: orientation match rate by tie-out tier is 94.0 / 88.1 / 98.9 / 97.8 / 99.0%
#: going from an exact reconciliation out to 1 bp -- flat, and if anything
#: worst at the tightest end (small residual = small package = near-mid legs).
#: A tighter gate would only cost coverage, which is the thing this module
#: exists to buy.
TIEOUT_MAX_BPS = 1.0

#: Below this distance from mid a leg's ``sign(f_i)`` is inside the mid's own
#: measurement error. ``upfront.py`` measures the on-market control at robust
#: sigma 0.254 bp and fits ``s`` at 0.358 bp; 0.25 bp is that scale. It does not
#: exclude -- ``V`` is immune to the error (see the module docstring) -- it
#: flags, and reports the PV01 whose key-rate sign is unsupported.
LEG_SIGN_RESOLUTION_BPS = 0.25

#: Above this leg count ``opa_sign_solver`` drops from exact enumeration to a
#: greedy heuristic. Not a refusal -- the tie-out is the real gate and a greedy
#: solve that ties out is still a reconciliation -- but it is recorded.
EXACT_SOLVE_MAX_LEGS = 24

# --- strata ----------------------------------------------------------------
# Named refusals, so the DV01 given up is countable rather than assumed small.
EXCL_NO_PACKAGE_PRICE = "PKG_NO_PACKAGE_PRICE"
EXCL_OPA_MISSING = "PKG_OPA_MISSING"
EXCL_TIEOUT_FAIL = "PKG_TIEOUT_FAIL"
EXCL_LEG_AT_MID = "PKG_LEG_AT_MID"
EXCL_PRICING_ERROR = dd_types.EXCL_PRICING_ERROR

#: Every stratum this module can produce, in gate order. Iterating this rather
#: than a hand-written list in the report is what keeps the two in step.
STRATA = (EXCL_NO_PACKAGE_PRICE, EXCL_OPA_MISSING, EXCL_TIEOUT_FAIL,
          EXCL_LEG_AT_MID, EXCL_PRICING_ERROR)

FLAG_LEG_NEAR_MID = "PKG_LEG_NEAR_MID"
FLAG_GREEDY_SOLVE = "PKG_GREEDY_SIGN_SOLVE"
FLAG_PTP_UFRO_DISAGREE = "PTP_UFRO_DISAGREE"


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class CashSigns:
    """The per-leg cash directions that reconcile the fees with the price."""

    signs: tuple
    #: ``sum(s_i * OPA_i)`` -- the package price rebuilt from the legs. Its
    #: **sign** is what fixes the base party (the reported ``PTP``'s polarity is
    #: relative to an undisseminated reporting party, so it cannot); its
    #: magnitude is only the fit. ``residual`` is how far it lands from the
    #: reported price and is the gate.
    net: float
    residual: float
    exact: bool


@dataclasses.dataclass(frozen=True)
class PackagePriceCall:
    """The package-price rule's answer for one unit.

    Maps onto :class:`types.DirectionCall` with ``rule =
    :data:`RULE_PACKAGE_PRICE``` and ``deviation_bps = deviation_bps``.
    """

    rule: str = RULE_PACKAGE_PRICE
    #: ``pay_signs`` for the base party, ``+1`` = pays fixed. Arbitrary up to a
    #: global flip; see the module docstring. ``None`` on a refusal.
    base_orientation: tuple | None = None
    #: The fair cash the base party should pay, ``V = sum(s_i * |f_i|)``.
    model_price: float | None = None
    #: The cash it did pay: ``sign(sum(s_i * OPA_i)) * |PTP|``.
    reported_price: float | None = None
    deviation_dollars: float | None = None
    deviation_bps: float | None = None
    #: ``conventions.DEALER_RECEIVED`` / ``DEALER_PAID`` / ``0``, **relative to
    #: ``base_orientation``**. Not "the dealer received fixed".
    dealer_sign: int = 0
    #: ``dealer_sign * base_orientation``, ``+1`` = dealer received fixed on
    #: that leg. The orientation-free answer, and the only one to read. ``None``
    #: when no call was made.
    received_signs: tuple | None = None
    #: ``|sum(s*OPA) - PTP|`` in bp of the unit's DV01.
    tieout_bps: float | None = None
    #: Summed PV01 of legs whose ``sign(f_i)`` is inside the mid's own error.
    unresolved_pv01: float = 0.0
    flags: tuple = ()
    exclusion: str | None = None


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

def solve_cash_signs(opas, package_price: float) -> CashSigns:
    """Which way each leg's fee flowed, from the package price alone.

    Thin wrapper on :func:`SDRUtils.packages.opa_sign_solver.solve_opa_signs`
    so there is one implementation of the reconciliation, not two that drift.
    Reported quantities only -- no curve, no model -- which is what makes the
    later comparison against the repriced value independent evidence.
    """
    vals = [abs(float(v)) for v in opas]
    res = solve_opa_signs(vals, float(package_price))
    signs = tuple(int(s) for s in res["signs"])
    return CashSigns(signs=signs, net=float(sum(s * v for s, v in zip(signs, vals))),
                     residual=float(res["residual"]),
                     exact=len(vals) <= EXACT_SOLVE_MAX_LEGS)


def orientation_from_cash(signs, npv_pays) -> tuple:
    """``o_i = s_i * sign(f_i)`` -- the package's ``pay_signs``.

    The party paying leg ``i``'s fee takes leg ``i``'s in-the-money side, and
    that side is *pay fixed* exactly when the payer's NPV is positive.

    **``f_i == 0`` raises.** At exactly mid there is no in-the-money side, so
    the leg has no orientation -- and the two available spellings of the
    comparison (``> 0`` and ``>= 0``) disagree there and nowhere else, which
    makes a silent default an untestable coin flip on the leg's key-rate sign.
    :func:`classify` refuses the unit as :data:`EXCL_LEG_AT_MID` before ever
    getting here; this is the guard for a direct caller.
    """
    out = []
    for i, (s, f) in enumerate(zip(signs, npv_pays)):
        v = float(f)
        if v == 0.0:
            raise ValueError(
                f"leg {i} prices exactly at mid (npv_pay == 0), so it has no "
                "in-the-money side and no orientation; the caller must refuse "
                "the unit (EXCL_LEG_AT_MID) rather than take a default"
            )
        out.append(int(s) * (1 if v > 0 else -1))
    return tuple(out)


def package_value(orientation, npv_pays) -> float:
    """``V = sum(o_i * f_i)`` -- what the base party's position is worth."""
    return float(sum(int(o) * float(f) for o, f in zip(orientation, npv_pays)))


def classify(*, opas, package_price, npv_pays, pv01s, structure_dv01,
             is_lifecycle: bool = False, ufro_sum: float | None = None,
             leg_sign_resolution_bps: float = LEG_SIGN_RESOLUTION_BPS,
             tieout_max_bps: float = TIEOUT_MAX_BPS,
             flags=()) -> PackagePriceCall:
    """The package-price rule for one unit.

    ``npv_pays`` are per-leg NPVs **to the fixed payer** at the repriced mid,
    in dollars, in the unit's leg order -- i.e. ``midprice`` ``LegQuote.npv_pay``.
    ``opas`` are the legs' reported ``other payment amount``, unsigned.

    ``is_lifecycle`` negates ``received_signs``, matching ``upfront.classify``:
    on a tear-up the reported side is **the side the dealer held on the dying
    swap**, which is the negation of the risk it takes on the print. Same
    convention across the package or the two rules cannot be pooled.
    """
    flags = list(flags)
    n = len(npv_pays)

    def refuse(reason: str) -> PackagePriceCall:
        return PackagePriceCall(exclusion=reason, flags=tuple(flags))

    if n == 0 or len(opas) != n or len(pv01s) != n:
        raise ValueError(
            f"package_price.classify got {len(opas)} fees, {n} NPVs and "
            f"{len(pv01s)} PV01s; they are per-leg and must be in the unit's "
            "own leg order, so a length mismatch is a caller bug, not a row "
            "outcome"
        )

    dv01 = _num(structure_dv01)
    if dv01 is None or dv01 <= 0:
        return refuse(EXCL_PRICING_ERROR)
    if any(_num(f) is None for f in npv_pays) or any(_num(p) is None for p in pv01s):
        return refuse(EXCL_PRICING_ERROR)

    ptp = _num(package_price)
    if ptp is None or abs(ptp) <= PTP_USD_FLOOR:
        return refuse(EXCL_NO_PACKAGE_PRICE)

    if any(_num(o) is None for o in opas):
        return refuse(EXCL_OPA_MISSING)

    cash = solve_cash_signs(opas, ptp)
    tieout_bps = cash.residual / dv01
    if not cash.exact:
        flags.append(FLAG_GREEDY_SOLVE)
    # `net == 0` is the one place the global flip does NOT cancel: the base
    # party's cash would be zero under either branch while its position value
    # flips with it, so `deviation` would depend on the solver's tie-break.
    # Every sign vector netting to zero also means the fees carry no
    # orientation at all, which is a reconciliation failure whatever the
    # residual happens to be.
    if tieout_bps > float(tieout_max_bps) or cash.net == 0.0:
        return dataclasses.replace(refuse(EXCL_TIEOUT_FAIL),
                                   tieout_bps=tieout_bps)

    f = [float(v) for v in npv_pays]
    if any(v == 0.0 for v in f):
        return dataclasses.replace(refuse(EXCL_LEG_AT_MID), tieout_bps=tieout_bps)

    o = orientation_from_cash(cash.signs, f)
    model = package_value(o, f)
    # The cash the base party actually handed over: the REPORTED package price
    # for its magnitude -- that is the authoritative number and the legs' fees
    # are allocations of it -- carrying the base party's own polarity, which
    # only `sign(net)` can supply. Taking the magnitude from `net` instead
    # would throw the unallocated cash (`|PTP| - |net|`) away, and on a package
    # whose fees happen to equal their model values exactly that unallocated
    # cash IS the whole dealer charge.
    reported = math.copysign(abs(ptp), cash.net)
    deviation = reported - model
    dev_bps = deviation / dv01

    unresolved = 0.0
    for fi, pi in zip(f, pv01s):
        p = abs(float(pi))
        if p > 0 and abs(fi) / p < float(leg_sign_resolution_bps):
            unresolved += p
    if unresolved > 0:
        flags.append(FLAG_LEG_NEAR_MID)

    if ufro_sum is not None:
        u = _num(ufro_sum)
        if u is not None and u > 0:
            hi, lo = max(abs(ptp), u), min(abs(ptp), u)
            if lo > 0 and hi / lo > PTP_UFRO_DISAGREE_RATIO:
                flags.append(FLAG_PTP_UFRO_DISAGREE)

    dealer_sign = conventions.dealer_side(dev_bps)
    received = None
    if dealer_sign != 0:
        received = tuple(dealer_sign * oi for oi in o)
        if is_lifecycle:
            received = tuple(-r for r in received)

    return PackagePriceCall(
        base_orientation=o, model_price=model, reported_price=reported,
        deviation_dollars=deviation, deviation_bps=dev_bps,
        dealer_sign=dealer_sign, received_signs=received,
        tieout_bps=tieout_bps, unresolved_pv01=unresolved,
        flags=tuple(flags),
    )


def received_hypothesis_signs(call: PackagePriceCall) -> tuple:
    """Per-leg ``received_signs`` under the hypothesis that the dealer received.

    The analogue of :func:`krd.received_hypothesis_signs`, which reads
    ``conventions.dealer_received_signs(..., DEALER_RECEIVED)`` and so is
    ``+1 * base_orientation``. For this rule the base orientation is per-unit
    rather than per-structure, so it comes off the call.
    """
    if call.base_orientation is None:
        raise ValueError(
            f"unit was not oriented ({call.exclusion!r}); there is no "
            "hypothesis to sign"
        )
    return tuple(call.base_orientation)


# --------------------------------------------------------------------------
# the tape gate -- vectorised, no curve, for universe routing and reporting
# --------------------------------------------------------------------------

#: Columns :func:`tape_gate` reads. ``_unit_group`` and ``_dv01_proxy`` are
#: ``universe.annotate_legs``'s own; the other two are raw tape.
GATE_COLUMNS = ("_unit_group", "other_payment_amount",
                "package_transaction_price", "_dv01_proxy")


def tape_gate(legs: pd.DataFrame) -> pd.DataFrame:
    """Which packages this rule can orient, from the tape alone.

    One row per ``_unit_group``, indexed by it, with ``recoverable`` /
    ``stratum`` / ``tieout_bps``. Deliberately curve-free: the retention and
    skew accounting has to run over 610 days and 1.44M units, and a gate that
    needed a repriced mid could not. The repricing gates
    (:data:`EXCL_LEG_AT_MID`, :data:`EXCL_PRICING_ERROR`) are applied later by
    :func:`classify` and are counted as pricing failures there, exactly as they
    are for every other rule.

    The DV01 the tie-out is expressed in is ``sum(|dv01 proxy|) / 2``, which is
    ``midprice.structure_dv01``'s ``PKG-N`` convention evaluated on the
    coverage proxy -- so the gate and the classifier scale the same residual
    the same way.
    """
    cols = [c for c in GATE_COLUMNS if c not in legs.columns]
    if cols:
        raise KeyError(
            f"tape_gate needs {list(GATE_COLUMNS)}; missing {cols}. "
            "`_unit_group` and `_dv01_proxy` come from universe.annotate_legs"
        )
    dupes = [c for c in GATE_COLUMNS if (legs.columns == c).sum() > 1]
    if dupes:
        # `legs[c]` is then a DataFrame, not a Series, and every read of it
        # fails somewhere far from the cause. A duplicated `SELECT` column is
        # how it happens; naming it here is cheaper than the traceback.
        raise KeyError(
            f"tape_gate got duplicated column(s) {dupes}; a duplicate makes "
            "`legs[col]` a DataFrame and the failure surfaces far from here"
        )
    out = pd.DataFrame(columns=["recoverable", "stratum", "tieout_bps"])
    if legs.empty:
        return out

    opa = pd.to_numeric(legs["other_payment_amount"], errors="coerce")
    ptp = pd.to_numeric(legs["package_transaction_price"], errors="coerce")
    dv01 = pd.to_numeric(legs["_dv01_proxy"], errors="coerce").abs()
    work = pd.DataFrame({"g": legs["_unit_group"].to_numpy(),
                         "opa": opa.to_numpy(), "ptp": ptp.to_numpy(),
                         "dv01": dv01.to_numpy()})

    rows = {}
    for g, sub in work.groupby("g", sort=False):
        rows[g] = _gate_one(sub)
    out = pd.DataFrame.from_dict(rows, orient="index",
                                 columns=["recoverable", "stratum", "tieout_bps"])
    out["recoverable"] = out["recoverable"].astype(bool)
    return out


def _gate_one(sub: pd.DataFrame) -> tuple:
    ptp_vals = sub["ptp"].dropna()
    ptp = float(ptp_vals.iloc[0]) if len(ptp_vals) else float("nan")
    if not math.isfinite(ptp) or abs(ptp) <= PTP_USD_FLOOR:
        return (False, EXCL_NO_PACKAGE_PRICE, None)
    if sub["opa"].isna().any():
        return (False, EXCL_OPA_MISSING, None)
    dv01 = float(np.nansum(sub["dv01"].to_numpy())) / 2.0
    if not math.isfinite(dv01) or dv01 <= 0:
        return (False, EXCL_PRICING_ERROR, None)
    cash = solve_cash_signs(sub["opa"].tolist(), ptp)
    tie = cash.residual / dv01
    if tie > TIEOUT_MAX_BPS:
        return (False, EXCL_TIEOUT_FAIL, tie)
    return (True, None, tie)


# --------------------------------------------------------------------------

def _num(v):
    """``float(v)`` or ``None`` -- ``None``/``NaN``/``inf``/junk all refused."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


__all__ = [
    "RULE_PACKAGE_PRICE", "PTP_USD_FLOOR", "PTP_UFRO_DISAGREE_RATIO",
    "TIEOUT_MAX_BPS", "LEG_SIGN_RESOLUTION_BPS", "STRATA",
    "EXCL_NO_PACKAGE_PRICE", "EXCL_OPA_MISSING", "EXCL_TIEOUT_FAIL",
    "EXCL_LEG_AT_MID", "EXCL_PRICING_ERROR",
    "FLAG_LEG_NEAR_MID", "FLAG_GREEDY_SOLVE", "FLAG_PTP_UFRO_DISAGREE",
    "CashSigns", "PackagePriceCall", "solve_cash_signs",
    "orientation_from_cash", "package_value", "classify",
    "received_hypothesis_signs", "tape_gate", "GATE_COLUMNS",
]
