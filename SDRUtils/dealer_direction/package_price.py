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

**How much that buys, up front, because it is much less than the exclusion is
worth.** One price against ``n`` unsigned fees usually does not pin ``n`` signs,
and measured over the whole window it pins them on **12.48% of ``PKG-4+``
packages carrying 4.14% of their DV01**. Retention goes 56.96% -> **57.89%**, not
to the 72.40% the tie-out alone would claim: the difference is packages where
several orientations fit the price equally well and the answer would be the
sign solver's tie-break. On the population where the answer is knowable those
tie-break orientations are right 66-84% of the time, and at zero margin they
are right at chance. See "PASSING THE TIE-OUT IS NOT IDENTIFICATION" below --
it is the section that matters most, and the one to read before quoting a
recovery number from this module.

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

That identity is exact and it is the **composition** that is pinned, not
either field: ``received_signs == dealer_sign * received_hypothesis_signs()``,
including on a lifecycle row, where the negation sits in ``dealer_sign``
because that is the field ``upfront.py`` puts it in. It had sat in
``received_signs`` instead, which agreed with ``upfront`` on the only field the
test compared while leaving ``dealer_sign * base_orientation`` inverted on
every lifecycle package -- the failure a consumer following the ``krd`` seam
would have taken silently.

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

**EVERY NUMBER BELOW IS COMPUTED BY A SCRIPT IN THE TREE, ON NAMED DAYS.**
``scratch/ppfix_measure.py`` (curve-free, all 610 days of the pinned window
``2024-03-01 .. 2026-08-07``, 1,437,838 units, 47,021 ``PKG-4+`` packages) and
``scratch/ppfix_known_answer.py`` (the repricing gate, on the ten days its own
day-selection *rule* picks: the first tape day on or after the 15th of every
third month -- 2024-03-15, 2024-06-17, 2024-09-16, 2024-12-16, 2025-03-17,
2025-06-16, 2025-09-15, 2025-12-15, 2026-03-16, 2026-06-15). The rule is in the
script and is evaluated there, so the population cannot be shopped after the
fact. Their combined output is committed at ``scratch/ppfix_results.txt``.
**A figure here that those two do not print has nothing behind it**, which was
the state of every number in this docstring before 2026-08-11: none of them was
computed anywhere in the tree and the days were not named.

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

    97.6% of the notation-3 prices are at or below the floor and 86.55% are
    literally ``10.00`` -- the ``9.9999999999`` not-available sentinel. So
    notation 3 is **degenerate**: it contributes 0.002 + 0.093 = **0.095**
    points of ``PKG-4+`` DV01 to the recovery against **4.182** refused, while
    notation 1 supplies **4.136 of the 4.138 points identified** (and 68.26 of
    the 68.36 the tie-out alone would have taken, before the identification
    gate below cut it down). ``ppfix_measure.py report`` section 8 prints that
    split; it is the claim the floor rests on, because a notation can be 5% of
    the packages and 0% of the answer. The frozen
    ``PTP_USD_FLOOR = 500`` removes the sentinel
    on its own, which is why this module reads **no notation column at all**
    (there is none on the legs table anyway -- it lives on the packages table
    as ``ptp_price_notation``): the floor plus the tie-out is an economic test,
    and a notation label is not.
``OPA_MISSING``
    Some leg carries no fee, so its cash sign is undetermined. Its ``|f_i|``
    still belongs in ``V``, so it cannot be dropped and the package is refused.
``TIEOUT_FAIL``
    No sign vector gets within :data:`TIEOUT_MAX_BPS` of the package price, or
    every one that does nets to zero cash. The orientation would be a guess.
    **7.7%** of the ``PKG-4+`` packages that reach this gate (a price above the
    floor and a fee on every leg) have ``|PTP| > sum|OPA|``, which no signed sum
    of the fees can reach -- 6.7% of their DV01. (Counted against *all*
    ``PKG-4+`` it reads 16.2%, but that number is inflated: a missing fee drops
    out of ``sum|OPA|`` rather than making it unknown, so the package looks
    unreachable when it is really unmeasured. The brief's 11.3% reproduces
    under no denominator this module uses.)
``SIGNS_AMBIGUOUS``
    More than one sign class fits the price inside the same gate, so the
    orientation is the solver's tie-break rather than the data's. **This is the
    biggest stratum by a distance -- 64.2% of ``PKG-4+`` DV01** -- and the
    section below is about why it has to be a refusal.
``LEG_AT_MID`` / ``PRICING_ERROR``
    ``f_i = 0`` exactly, or an unpriced leg / unusable DV01.

**Asset swaps are not recoverable this way and are not attempted.** The bond is
identified (``ust_cusip`` on 48%) but not priced on this tape, so no ``f_i``
exists for the leg that matters. ``EXCLUDED_TRADE_TYPES`` keeps them out ahead
of this gate, which is why :func:`tape_gate` never sees them.

THE KNOWN-ANSWER GATE -- MEASURED, NOT ASSERTED
------------------------------------------------

``conventions.base_orientation`` fixes the answer for a ``CURVE`` and a
``FLY``. Run this rule on real fee-bearing prints over the ten named days and
ask whether the fee-derived ``o`` reproduces it (1,821 fee-bearing CURVE/FLY
units with a usable package price, 1,803 priced, 18 refused for no curve):

===================================  ======  ==========  =========
population (10 named days)           n       match       by chance
===================================  ======  ==========  =========
tape ``package_type = CURVE``           753      94.82%        50%
  ... worst leg >= 0.25 bp from mid     699      98.14%        50%
  ... worst leg >= 1.00 bp from mid     644      98.45%        50%
tape ``package_type = FLY``             325      93.85%        25%
  ... worst leg >= 0.25 bp from mid     292      95.89%        25%
  ... worst leg >= 1.00 bp from mid     236      96.61%        25%
===================================  ======  ==========  =========

**The conditioning on the tape's own ``package_type`` is the point, not a
filter chosen to flatter the number.** ``universe.unit_frame`` names a unit
``CURVE`` on **leg count alone**, and ``conventions.base_orientation`` then
asserts one payer and one receiver -- which is simply not true of a 2-leg
package that is a strip, a roll or a block split. Unconditionally the match is
86.10% (CURVE, n=1,259) and 67.10% (FLY, n=544); split by what the tape's
DV01-neutrality detector says, the genuine curves and flies come in at 94.8% /
93.9% and the ``PKG-2`` / ``PKG-3`` residue at 73.12% (n=506) / **27.40%**
(n=219) -- and 27.40% on a 3-leg unit is *chance*, which is what "this
convention does not apply here" looks like.

**The misses are the documented failure mode, not a second one.** Median
distance from mid of the worst leg is **0.152 bp on the 59 misses against
7.401 bp on the 1,019 hits**: they are the near-mid legs where ``sign(f_i)``
is a coin flip, exactly the population :data:`FLAG_LEG_NEAR_MID` marks.

A corollary worth keeping: ``opa_sign_solver``'s own absolute confidence tiers
are **anti**-informative here -- ``EXACT`` (residual < $100) matches 87.88%
and ``LOOSE`` (< $50k) matches 96.80%, because a $100 residual means a small
package and a small package is a near-mid one. That is why
:data:`TIEOUT_MAX_BPS` is in bp.

PASSING THE TIE-OUT IS NOT IDENTIFICATION, AND THAT IS MOST OF THE STORY
--------------------------------------------------------------------------

Everything above says the winning sign vector *fits*. **It does not say it is
the only one that does**, and the difference is the whole recovery.

Write ``margin_bps`` for the distance from the winning sign class to the next
distinct one, in bp of the unit's own DV01, where a *class* is a sign vector
together with its global complement (the two are the same answer -- see above
-- so counting them separately would report a spurious zero on every unit). A
unit is **identified** when the runner-up sits OUTSIDE the same gate the winner
had to sit inside. No second constant: if 1 bp of unexplained cash is
acceptable noise, every class inside 1 bp is equally consistent with the price,
and the choice between them is ``opa_sign_solver._select_best``'s lowest-mask
tie-break applied to every leg's key-rate sign.

**On the known-answer population this is not a theoretical worry, it is the
dominant term.** Same ten days, tape-named CURVE/FLY, tie-out passed:

===============================  ======  ==========
population                       n       match
===============================  ======  ==========
CURVE, identified                   603      98.34%
CURVE, ambiguous                     77      66.23%
FLY, identified                     205     100.00%
FLY, ambiguous                      117      83.76%
-------------------------------  ------  ----------
margin in [0, 0.05) bp               33      45.45%
margin in [0.05, 0.25) bp            66      68.18%
margin in [0.25, 1.0) bp            106      93.40%
margin in [1.0, 5.0) bp             191      97.91%
margin in [5.0, inf) bp             606      99.17%
===============================  ======  ==========

**A 2-leg unit whose runner-up is within 0.05 bp reproduces the known
orientation 45.45% of the time. That is chance.** The margin is not a proxy for
confidence, it *is* the identification, and it is monotone in exactly the way a
statistic has to be to be gated on. By contrast the tie-out residual itself
buys nothing once it is inside the gate: match by tie-out band is 95.7 / 88.5 /
97.8 / 96.9 / 98.0% going from an exact reconciliation out to 1 bp -- flat, and
worst at the tightest end.

WHAT THIS COSTS, STATED PLAINLY
---------------------------------

The identification requirement is brutal on ``PKG-4+`` and it is brutal for a
structural reason, not a tuning one. Flipping one leg's cash direction moves
the reconciliation by ``2 * OPA_i``, so a unit is identified only if **every**
fee exceeds about half a bp of the package's DV01 -- and a package's DV01 grows
with its leg count while its individual fees do not. Measured over the whole
window (``scratch/ppfix_measure.py report``, section 5):

(shares rounded to 2 dp from ``ppfix_measure.py report`` section 5, which
prints them to 4: 61.4535 / 70.8075 / 87.0968 / 90.9040 / 97.2520)

====================  =======  =============  ==================
legs                  n        median margin  share ambiguous
====================  =======  =============  ==================
4                       9,866       0.4387 bp            61.45%
5                       3,542       0.2563 bp            70.81%
6                       4,681       0.0927 bp            87.10%
7                       1,803       0.0800 bp            90.90%
8+                      9,716       0.0054 bp            97.25%
====================  =======  =============  ==================

So the honest recovery is:

=========================================  =================  ============
DV01 (proxy), whole pinned window          $                  % of tape
=========================================  =================  ============
kept with no ``PKG-4+`` recovery at all      45,941,783,080        56.96%
+ recovered **and identified**                  754,307,566    **57.89%**
+ recovered but **ambiguous**                11,705,194,189        72.40%
=========================================  =================  ============

**The headline is 57.89%, not 72.40%.** The 14.5 points in the third row are
packages whose orientation is a tie-break, and on the only population where the
answer is knowable, tie-break orientations are right 66-84% of the time and at
zero margin are right at chance. Buying 14.5 points of DV01 by pointing
key-rate profiles the wrong way on a third of them is not a recovery; it is a
larger, more confident version of the exclusion skew this module exists to fix.
The 12.48% of ``PKG-4+`` units that survive are still worth having: they are
99.8% D2C and 32.5% block by DV01, the same customer-facing population the
exclusion was stripping, and their orientation is now evidence rather than a
convention.

Two smaller honesty notes on the same number. **0.94% of the units that clear
the tie-out are exact ties** (margin identically zero, distinct sign vectors
netting to the same number, which duplicated fee allocations guarantee); they
are inside ``SIGNS_AMBIGUOUS`` and are refused, not silently decided. And
**31.16% of ``PKG-4+`` DV01 sits above** :data:`MARGIN_MAX_LEGS`, where the
runner-up is not enumerated at all and the unit is refused for that reason; on
a sample of eight days, all 11 such units that clear the tie-out and can be
enumerated exactly out to 24 legs have a margin of at most 0.00001 bp, i.e.
**none of them would have been identified anyway** -- so the cap is a cost of
almost nothing, but it is a cost taken on measurement rather than on faith.

AGREEING WITH THE RATE RULE IS NOT THE BAR -- 50% IS
------------------------------------------------------

On the same genuine CURVE/FLY population the per-leg ``received_signs`` agree
with :data:`~.conventions.RULE_RATE`'s answer **49.50%** of the time (n=808),
roughly flat across the rate deviation (60.5% / 53.7% / 43.2% / 46.3% over
|dev| bands 0-1, 1-5, 5-20 and 20+ bp). That is the expected number, and the
derivation says so before the
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
# `_MAX_BRUTE_N` is imported rather than copied on purpose: it is the leg count
# above which the solver stops enumerating, and `CashSigns.exact` is a claim
# about exactly that. A hand-written 24 goes on saying `True` the day the
# solver's own limit moves, which is a silent lie about the evidence; an import
# of a renamed private name is a loud one.
from SDRUtils.packages.opa_sign_solver import _MAX_BRUTE_N, solve_opa_signs
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
#: ``EXACT`` matches the known orientation 87.9% of the time and ``LOOSE``
#: 96.8%. Rescaled to bp the gate says the unexplained cash is inside a
#: plausible package bid-offer.
#:
#: **Where 1.0 comes from** (``scratch/ppfix_measure.py report``, section 6).
#: Over all 47,021 ``PKG-4+`` packages in the pinned window the residual
#: distribution is p50 0.035, p75 0.199, p90 0.805, p95 2.024, p99 16.831 bp,
#: and the share of *eligible* DV01 kept as the gate moves -- eligible meaning
#: a price above the floor and a fee on every leg, 73.9% of ``PKG-4+`` DV01,
#: which is the only population the gate can be applied to -- is::
#:
#:     0.05 bp -> 72.7%   0.25 -> 86.5%   0.50 -> 90.2%
#:     1.00 bp -> 92.5%   2.00 -> 94.4%   5.00 -> 96.2%
#:
#: -- a smooth region with no cliff, so the constant is not sitting on a
#: discontinuity and the cost of any other choice is on the record. It is set
#: at 1.0 rather than tighter because **tightening buys no accuracy**: the
#: orientation match rate by tie-out band (``ppfix_known_answer.py report``,
#: section B, the control table) is 95.65 / 88.54 / 97.75 / 96.92 / 98.02%
#: going from an exact reconciliation out to 1 bp -- flat, and if anything
#: worst at the tightest end (small residual = small package = near-mid legs).
#:
#: **It is also the identification gate**, and there the direction of the
#: trade-off reverses, which is worth knowing before anyone moves it: the same
#: eligible DV01 surviving BOTH the tie-out and the requirement that the
#: runner-up sign class fall outside it is 9.9 / 9.5 / 7.9 / **5.6** / 3.7 /
#: 1.8% over the same ladder. A looser gate admits more fits and fewer
#: identifications. 1.0 is kept because it is the number the frozen
#: distribution was characterised on, not because it maximises either column.
TIEOUT_MAX_BPS = 1.0

#: Below this distance from mid a leg's ``sign(f_i)`` is inside the mid's own
#: measurement error. ``upfront.py`` measures the on-market control at robust
#: sigma 0.254 bp and fits ``s`` at 0.358 bp; 0.25 bp is that scale. It does not
#: exclude -- ``V`` is immune to the error (see the module docstring) -- it
#: flags, and reports the PV01 whose key-rate sign is unsupported.
LEG_SIGN_RESOLUTION_BPS = 0.25

#: Above this leg count ``opa_sign_solver`` drops from exact enumeration to a
#: greedy heuristic. Not a refusal -- the tie-out is the real gate and a greedy
#: solve that ties out is still a reconciliation -- but it is recorded. Taken
#: from the solver, never copied.
EXACT_SOLVE_MAX_LEGS = _MAX_BRUTE_N

#: Above this leg count :func:`sign_class_margin` stops enumerating, because
#: the runner-up sign class costs ``2**(n-1)`` work to find and the gate runs
#: over every ``PKG-4+`` group in the window (47,021 of them; ``universe``
#: restricts it to those, not to all 1.44M units). A unit past the cap is
#: **refused** as :data:`EXCL_SIGNS_AMBIGUOUS` rather than accepted on a
#: missing statistic. That is 3,798 of the 47,021 packages -- 8.1% of units but
#: **31.16% of ``PKG-4+`` DV01** -- so it is not a rounding decision, and it is
#: taken on a
#: measurement: enumerated exactly out to 24 legs on eight sampled days
#: (``scratch/ppfix_measure.py bigleg``), all 11 such units that clear the
#: tie-out have a margin of at most 0.00001 bp and **none would have been
#: identified**. A 24-leg package has 8.4M sign classes to fit one number; the
#: lattice is dense and the runner-up is always adjacent.
MARGIN_MAX_LEGS = 20

# --- strata ----------------------------------------------------------------
# Named refusals, so the DV01 given up is countable rather than assumed small.
EXCL_NO_PACKAGE_PRICE = "PKG_NO_PACKAGE_PRICE"
EXCL_OPA_MISSING = "PKG_OPA_MISSING"
EXCL_TIEOUT_FAIL = "PKG_TIEOUT_FAIL"
EXCL_SIGNS_AMBIGUOUS = "PKG_SIGNS_AMBIGUOUS"
EXCL_LEG_AT_MID = "PKG_LEG_AT_MID"
EXCL_PRICING_ERROR = dd_types.EXCL_PRICING_ERROR

#: Every stratum this module can produce, **in the order both paths evaluate
#: them**. :func:`classify` and :func:`tape_gate` are one rule with two
#: implementations -- ``universe.unit_frame`` routes on the gate's word while
#: the coverage report reads the classifier's -- so a difference in precedence
#: is a difference in what the two say about the same package. The gate stops
#: after :data:`EXCL_SIGNS_AMBIGUOUS`; the two strata that need a repriced mid
#: (:data:`EXCL_LEG_AT_MID`, and the per-leg half of
#: :data:`EXCL_PRICING_ERROR`) are the classifier's alone, and a test walks the
#: whole grid asserting they agree wherever both can see.
STRATA = (EXCL_NO_PACKAGE_PRICE, EXCL_OPA_MISSING, EXCL_PRICING_ERROR,
          EXCL_TIEOUT_FAIL, EXCL_SIGNS_AMBIGUOUS, EXCL_LEG_AT_MID)

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
    #: Dollars from this sign class's residual to the **next distinct class's**
    #: -- the identification statistic. ``inf`` for a one-leg unit (a vector and
    #: its complement are one class, so there is no runner-up) and ``nan`` above
    #: :data:`MARGIN_MAX_LEGS`, where it is not enumerated. See
    #: :func:`sign_class_margin`.
    margin: float = float("nan")


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
    #: ``base_orientation``**. Not "the dealer received fixed". Carries the
    #: lifecycle negation, exactly as ``upfront.UpfrontCall.dealer_sign`` does,
    #: so the two rules' columns mean the same thing in a pooled population.
    dealer_sign: int = 0
    #: ``dealer_sign * base_orientation``, ``+1`` = dealer received fixed on
    #: that leg. The orientation-free answer, and the only one to read. ``None``
    #: when no call was made. The identity is exact -- it is
    #: ``dealer_sign * received_hypothesis_signs(call)`` -- and a test pins the
    #: composition rather than either field, because a negation applied to one
    #: field and not the other is invisible to a test that reads only this one.
    received_signs: tuple | None = None
    #: ``|sum(s*OPA) - PTP|`` in bp of the unit's DV01.
    tieout_bps: float | None = None
    #: Distance from the winning sign class to the next distinct one, in bp of
    #: the unit's DV01 -- **the identification statistic**. ``tieout_bps`` says
    #: the winner fits; this says whether anything else fits as well. ``inf``
    #: when there is only one class, ``nan`` when it was not enumerable.
    margin_bps: float | None = None
    #: Summed PV01 of legs whose ``sign(f_i)`` is inside the mid's own error.
    unresolved_pv01: float = 0.0
    flags: tuple = ()
    exclusion: str | None = None


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

def sign_class_margin(opas, package_price: float) -> float:
    """Dollars from the best sign class's residual to the runner-up class's.

    **The identification statistic.** ``residual`` says the winning sign vector
    reconciles the fees with the price; this says whether anything else does
    too. A *class* is a sign vector together with its global complement, which
    is the degree of freedom the price-vs-model comparison consumes (see the
    module docstring) -- the two members are the same answer, so counting them
    twice would report a spurious zero margin on every unit.

    Enumerated by fixing leg 0's sign to ``+1``, which picks exactly one
    representative of each class, so the ``2**(n-1)`` nets are the classes.
    A class's residual is ``| |net| - |PTP| |``, which is
    ``min(|net - PTP|, |net + PTP|)`` -- the solver's own objective.

    ``inf`` when there is only one class (a one-leg unit), ``nan`` above
    :data:`MARGIN_MAX_LEGS` or on a non-finite input. Two *distinct* sign
    vectors that happen to net to the same number -- which duplicated fees
    guarantee -- are two classes at zero margin, and that is correct: the
    winner between them is :func:`opa_sign_solver._select_best`'s lowest-mask
    tie-break, which is a convention and not economics.
    """
    vals = np.abs(np.asarray([float(v) for v in opas], dtype=float))
    n = int(vals.size)
    ptp = abs(float(package_price))
    if n == 0 or not np.isfinite(vals).all() or not math.isfinite(ptp):
        return float("nan")
    if n == 1:
        return float("inf")
    if n > MARGIN_MAX_LEGS:
        return float("nan")
    nets = np.array([vals[0]], dtype=float)
    for v in vals[1:]:
        nets = np.concatenate([nets - v, nets + v])
    resid = np.abs(np.abs(nets) - ptp)
    two = np.partition(resid, 1)[:2]
    return float(max(two.max() - two.min(), 0.0))


def solve_cash_signs(opas, package_price: float) -> CashSigns:
    """Which way each leg's fee flowed, from the package price alone.

    Thin wrapper on :func:`SDRUtils.packages.opa_sign_solver.solve_opa_signs`
    so there is one implementation of the reconciliation, not two that drift.
    Reported quantities only -- no curve, no model -- which is what makes the
    later comparison against the repriced value independent evidence.

    ``margin`` comes back beside the residual because the two are read
    together: a residual inside the gate with a runner-up also inside it is a
    fit, not an identification.
    """
    vals = [abs(float(v)) for v in opas]
    res = solve_opa_signs(vals, float(package_price))
    signs = tuple(int(s) for s in res["signs"])
    return CashSigns(signs=signs, net=float(sum(s * v for s, v in zip(signs, vals))),
                     residual=float(res["residual"]),
                     exact=len(vals) <= EXACT_SOLVE_MAX_LEGS,
                     margin=sign_class_margin(vals, package_price))


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

    ``is_lifecycle`` negates ``dealer_sign`` -- **the same field**
    ``upfront.classify`` negates, which puts it inside ``_edge_from_dev`` --
    and ``received_signs`` follows because it is the product. On a tear-up the
    reported side is **the side the dealer held on the dying swap**, which is
    the negation of the risk it takes on the print. Same convention *and the
    same field* across the two rules, or their ``dealer_sign`` columns cannot
    be pooled and a consumer that composes the fields gets the package's
    key-rate profile inverted on every lifecycle row.
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

    # The gates run in `STRATA` order, which is also `tape_gate`'s order. Both
    # are one rule and a package must not be given up for one reason here and a
    # different one there -- `universe.unit_frame` routes on the gate while the
    # coverage report reads this, so a precedence difference is two documents
    # disagreeing about the same package.
    ptp = _num(package_price)
    if ptp is None or abs(ptp) <= PTP_USD_FLOOR:
        return refuse(EXCL_NO_PACKAGE_PRICE)

    if any(_num(o) is None for o in opas):
        return refuse(EXCL_OPA_MISSING)

    dv01 = _num(structure_dv01)
    if dv01 is None or dv01 <= 0:
        return refuse(EXCL_PRICING_ERROR)
    if any(_num(f) is None for f in npv_pays) or any(_num(p) is None for p in pv01s):
        return refuse(EXCL_PRICING_ERROR)

    cash = solve_cash_signs(opas, ptp)
    tieout_bps = cash.residual / dv01
    margin_bps = cash.margin / dv01
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
                                   tieout_bps=tieout_bps,
                                   margin_bps=margin_bps)

    # IDENTIFICATION. Clearing the tie-out says this sign vector fits; it does
    # not say it is the only one that does, and on a PKG-4+ it usually is not.
    # The rule needs no new constant: the winner had to land inside
    # `tieout_max_bps`, so any other class inside it fits the price equally
    # well and the choice between them is `opa_sign_solver`'s lowest-mask
    # tie-break -- a convention, applied to every leg's key-rate sign. `nan`
    # (not enumerable) fails this comparison, which is the intended direction.
    if not (tieout_bps + margin_bps > float(tieout_max_bps)):
        return dataclasses.replace(refuse(EXCL_SIGNS_AMBIGUOUS),
                                   tieout_bps=tieout_bps,
                                   margin_bps=margin_bps)

    f = [float(v) for v in npv_pays]
    if any(v == 0.0 for v in f):
        return dataclasses.replace(refuse(EXCL_LEG_AT_MID),
                                   tieout_bps=tieout_bps,
                                   margin_bps=margin_bps)

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

    # The lifecycle negation goes HERE, inside `dealer_sign`, and not on
    # `received_signs` afterwards. `upfront.classify` negates its `edge` before
    # `dealer_side` sees it (`upfront._edge_from_dev`), so its `dealer_sign` is
    # already the side the dealer takes on the print; putting the negation in a
    # different field here would make the two rules' `dealer_sign` columns mean
    # different things in one pooled population, and would break the identity
    # `received_signs == dealer_sign * base_orientation` that this dataclass
    # states and that a consumer following the `krd` seam computes for itself.
    # `base_orientation` is a property of the package and must NOT move: it is
    # which legs are paid fixed, which a tear-up does not change.
    dealer_sign = conventions.dealer_side(dev_bps)
    if is_lifecycle:
        dealer_sign = -dealer_sign
    received = None
    if dealer_sign != 0:
        received = tuple(dealer_sign * oi for oi in o)

    return PackagePriceCall(
        base_orientation=o, model_price=model, reported_price=reported,
        deviation_dollars=deviation, deviation_bps=dev_bps,
        dealer_sign=dealer_sign, received_signs=received,
        tieout_bps=tieout_bps, margin_bps=margin_bps,
        unresolved_pv01=unresolved, flags=tuple(flags),
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
    ``midprice.structure_dv01``'s ``PKG-N`` convention evaluated on the coverage
    proxy. **Same convention, different input**, and the distinction is worth
    stating because the older phrasing ("the gate and the classifier scale the
    same residual the same way") was half false and nothing tested it: this
    divides ``sanity.expected_dv01``, a notional x tenor proxy that is forced to
    ``0.0`` on the 55 sentinel legs, while :func:`classify` divides repriced
    PV01s. The two therefore disagree in *level* on any unit whose proxy is off,
    and only the ``/ 2`` convention is shared. What IS pinned -- by
    ``test_the_gate_and_the_classifier_scale_the_same_residual_the_same_way``,
    on a residual that lands between the gate and twice it -- is that the
    halving is applied in both, because deleting it here left the whole suite
    green and doubles every tie-out the coverage table routes on.
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
    cols_out = ["recoverable", "stratum", "tieout_bps", "margin_bps"]
    out = pd.DataFrame(columns=cols_out)
    if legs.empty:
        return out

    # `to_numeric` leaves `inf` alone and `.isna()` does not see it, so an
    # `inf` fee used to reach `solve_opa_signs`, where every residual is `nan`,
    # `_select_best`'s candidate array comes back empty and the reduction
    # raises `zero-size array` -- killing the whole day's `unit_frame` instead
    # of naming one package. `classify`'s `_num` refuses non-finite; this makes
    # the gate refuse it the same way and under the same name.
    opa = _finite_or_nan(legs["other_payment_amount"])
    ptp = _finite_or_nan(legs["package_transaction_price"])
    dv01 = _finite_or_nan(legs["_dv01_proxy"], keep_non_finite=True).abs()
    work = pd.DataFrame({"g": legs["_unit_group"].to_numpy(),
                         "opa": opa.to_numpy(), "ptp": ptp.to_numpy(),
                         "dv01": dv01.to_numpy()})

    rows = {}
    for g, sub in work.groupby("g", sort=False):
        rows[g] = _gate_one(sub)
    out = pd.DataFrame.from_dict(rows, orient="index", columns=cols_out)
    out["recoverable"] = out["recoverable"].astype(bool)
    return out


def _finite_or_nan(col: pd.Series, keep_non_finite: bool = False) -> pd.Series:
    """``to_numeric`` with ``inf`` treated as missing, like ``_num`` does.

    ``keep_non_finite`` is for the DV01 proxy, where an ``inf`` must survive to
    the ``math.isfinite(dv01)`` check so the unit is named a pricing error
    rather than silently dropped out of the sum by ``nansum``.
    """
    v = pd.to_numeric(col, errors="coerce")
    if keep_non_finite:
        return v
    return v.where(np.isfinite(v.to_numpy(dtype=float)))


def _gate_one(sub: pd.DataFrame) -> tuple:
    ptp_vals = sub["ptp"].dropna()
    ptp = float(ptp_vals.iloc[0]) if len(ptp_vals) else float("nan")
    if not math.isfinite(ptp) or abs(ptp) <= PTP_USD_FLOOR:
        return (False, EXCL_NO_PACKAGE_PRICE, None, None)
    if sub["opa"].isna().any():
        return (False, EXCL_OPA_MISSING, None, None)
    dv01 = float(np.nansum(sub["dv01"].to_numpy())) / 2.0
    if not math.isfinite(dv01) or dv01 <= 0:
        return (False, EXCL_PRICING_ERROR, None, None)
    cash = solve_cash_signs(sub["opa"].tolist(), ptp)
    tie = cash.residual / dv01
    margin = cash.margin / dv01
    if tie > TIEOUT_MAX_BPS or cash.net == 0.0:
        # `net == 0` is `classify`'s refusal too, and it was missing here: the
        # gate called it recoverable, `universe` routed it into the kept
        # universe on that word, and `classify` then refused the same package.
        # Equal fee allocations produce exactly this shape.
        return (False, EXCL_TIEOUT_FAIL, tie, margin)
    if not (tie + margin > TIEOUT_MAX_BPS):
        return (False, EXCL_SIGNS_AMBIGUOUS, tie, margin)
    return (True, None, tie, margin)


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
    "EXACT_SOLVE_MAX_LEGS", "MARGIN_MAX_LEGS",
    "EXCL_NO_PACKAGE_PRICE", "EXCL_OPA_MISSING", "EXCL_TIEOUT_FAIL",
    "EXCL_SIGNS_AMBIGUOUS", "EXCL_LEG_AT_MID", "EXCL_PRICING_ERROR",
    "FLAG_LEG_NEAR_MID", "FLAG_GREEDY_SOLVE", "FLAG_PTP_UFRO_DISAGREE",
    "CashSigns", "PackagePriceCall", "solve_cash_signs", "sign_class_margin",
    "orientation_from_cash", "package_value", "classify",
    "received_hypothesis_signs", "tape_gate", "GATE_COLUMNS",
]
