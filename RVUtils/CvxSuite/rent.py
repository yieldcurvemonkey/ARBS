"""The rent line: repriced package gamma, daily theta, and breakeven vol.

One concern: given a resolved swap package on one day's pricer, produce the
four numbers the kink ledger row calls its rent block (kink_ledger.md section 6)::

    theta (USD/day) | Gamma (USD/bp^2) | sigma_BE = sqrt(2|theta|/Gamma) | status

Units (binding, DESIGN.md section 1)
------------------------------------
* ``gamma_usd_per_bp2`` — USD per bp^2 of parallel shift, for the WHOLE package
  at its traded size (not per unit DV01).
* ``theta_usd_day`` — USD per calendar-of-business day; negative = the package
  pays rent (long-gamma flattener), positive = it collects rent.
* ``carry_bp_day`` / ``sigma_be_bp_day`` — bp/day at the ledger boundary. The
  only bp/yr -> bp/day crossing is the named ``business_days`` divisor here.

How gamma is measured (and why the fit keeps the linear term)
-------------------------------------------------------------
Gamma is a least-squares quadratic ``a + b*s + c*s^2`` fitted to
``ConvexityRV.curve_ops.payoff_profile(pricer, package, shifts)`` — the
whole-package reprice on shifted curves — returning ``2c``. Repricing is the
package's own convention: ``IRSwapValue.GAMMA_01``/``DV01`` deliberately raise
on the rateslib backend (curve_ops module docstring), and the repriced second
difference is the number a risk system would show. Cross-validation on the
strat3 pairs: repriced gamma / theory ``2*(dM/1e4)*DV01`` has measured ratio
~1.00 (strat3_strikeless_vol tie-out (c), ``gamma_ratio``).

The linear term stays in the fit because packages are never perfectly
DV01-neutral: ``build_irswap(bpv=...)`` sizes off the analytic annuity while
neutrality is measured by repriced central difference, and the two diverge by
up to 10% on an inverted long end (strat3 ``leg_metrics`` docstring). On an
asymmetric shift grid an even-only fit aliases that residual delta into
curvature — measured here: planted ``(b=7, c=0.4)`` on the grid
``(-50,-25,-10,10,25,100)`` fits ``2c = 0.942`` without the linear term vs the
true ``0.800`` (18% bias); with the linear term the recovery is exact to
1.4e-16 relative.

The breakeven and its status taxonomy (strat1 semantics)
--------------------------------------------------------
``sigma_be_bp_day = sqrt(2|theta_daily| / |Gamma|)`` is the daily normal vol at
which the gamma P&L ``0.5*Gamma*sigma^2`` exactly offsets the rent — the
analytic form of strat3 ``screen_frame``'s ``be_daily_exact =
sqrt(2*|roll_1y/252|/gamma)``, with which it agrees identically when
``theta_usd_day = roll_1y_usd/252``.

The no-root cases follow ``strat1_curve_gamma.BreakevenResult`` — quoting its
docstring, a single NaN would cover "two OPPOSITE states":

* ``always_cheap`` — payoff positive at zero vol (the package carries
  positively, or theta>=0 with Gamma>=0): breakeven 0.0, cheap against any
  vol whatsoever. JPM's forward structure is "100% cheap curve gamma", i.e.
  exactly this branch; strat3's screen likewise prints ``be = 0`` whenever
  ``carry >= 0``.
* ``never_cheap`` — payoff negative at any vol (theta<=0 with Gamma<=0):
  breakeven +inf, rich against any vol whatsoever.
* ``undefined`` — non-finite inputs, or theta == Gamma == 0 identically.
* ``root`` — sign(theta) != sign(Gamma), both nonzero: the finite breakeven.
  This includes the SHORT-gamma side (Gamma<0, theta>0 — the harvest book,
  which receives the belly and collects rent): there sigma_BE is the realized
  vol ABOVE which the short-convexity position loses, and ``be_over_rv >= 1.17``
  (Citi's published curve-pair anchor) reads "the rent breakeven sits
  comfortably above realized".

Two documented deviations from strat1's numeric ``breakeven_vol``: (1) no
[1, 1000] bp/yr bracket — the closed form solves exactly, so a root strat1
would censor into always/never_cheap at the bracket edge is reported as
``root`` here; (2) ``|Gamma|`` in the denominator so the short-gamma root is
representable at all (strat1 only ever prices the long-gamma flattener).

What this is NOT
----------------
* NOT ``Curve.translate`` ageing. Measured wrong and refused upstream
  (``curve_ops.horizon_handle`` raises): 0.000 bp of carry on DV01-neutral
  forward packages, -531.94 bp on a 1y-aged 30Y payer. Carry enters the rent
  line as ``theta`` — a LEVEL — never via ``horizon_date``.
* NOT a carry source. ``carry_bp_yr`` is an input; it must come from the
  repriced-roll path (``CvxSuite.carry``, i.e. ``handle.roll`` /
  aged-rate identity — corr +0.991 with Citi's published carry), never from
  ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` for cross-sectional ranking
  (corr -0.136).
* NOT a vega model: vol prices rent here; it is never the hedge pair
  (DESIGN.md section 7; measured partial R^2 <= 0.044).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence, Tuple

import numpy as np

from RVUtils.ConvexityRV.curve_ops import payoff_profile
from RVUtils.ConvexityRV.payoff import BUSINESS_DAYS_PER_YEAR

__all__ = [
    "RentRow",
    "package_gamma_usd",
    "sigma_be_bp_day",
    "rent_row",
    "DEFAULT_SHIFTS_BP",
    "STATUSES",
]

#: Contract default shift grid, bp. Uneven on purpose (dense near the money,
#: 50/100 bp wings) and symmetric; the fit does not require symmetry.
DEFAULT_SHIFTS_BP: Tuple[float, ...] = (-100.0, -50.0, -25.0, -10.0, 10.0, 25.0, 50.0, 100.0)

#: The strat1 status taxonomy, verbatim.
STATUSES: Tuple[str, ...] = ("root", "always_cheap", "never_cheap", "undefined")


@dataclass(frozen=True)
class RentRow:
    """One package's rent block. Fields per DESIGN.md section 3; units above."""

    gamma_usd_per_bp2: float
    theta_usd_day: float
    carry_bp_day: float
    sigma_be_bp_day: float
    status: str  # root | always_cheap | never_cheap | undefined


def package_gamma_usd(
    pricer: Any,
    package: Sequence[Any],
    *,
    shifts: Sequence[float] = DEFAULT_SHIFTS_BP,
) -> float:
    """Repriced package gamma, USD per bp^2: ``2c`` of the quadratic fit.

    Fits ``payoff ~ a + b*s + c*s^2`` by least squares over the repriced
    profile ``curve_ops.payoff_profile(pricer, package, shifts)`` (currency,
    net of spot, ``carry_ccy=0.0`` — the profile here is the pure convexity
    SHAPE; carry enters the rent row as theta, never double-counted into the
    fit) and returns ``2c``.

    Error paths: a non-finite payoff anywhere on the grid returns NaN (never a
    silent zero); a degenerate grid (< 3 distinct finite shifts) or an empty
    package raises ``ValueError`` loudly.
    """
    s = np.asarray(list(shifts), dtype=float)
    if s.size < 3 or np.unique(s).size < 3:
        raise ValueError(
            f"package_gamma_usd needs >= 3 distinct shifts to identify a quadratic; got {list(s)}"
        )
    if not np.isfinite(s).all():
        raise ValueError(f"package_gamma_usd: non-finite shift in {list(s)}")
    if len(package) == 0:
        raise ValueError(
            "package_gamma_usd: empty package — an empty sum reprices to 0.0 "
            "everywhere and would report gamma 0.0 silently"
        )
    p = np.asarray(
        payoff_profile(pricer, package, s, net_of_spot=True, carry_ccy=0.0),
        dtype=float,
    )
    if not np.isfinite(p).all():
        return float("nan")
    coefs = np.polynomial.polynomial.polyfit(s, p, 2)  # ascending: [a, b, c]
    return float(2.0 * coefs[2])


def sigma_be_bp_day(theta_usd_day: float, gamma_usd_per_bp2: float) -> Tuple[float, str]:
    """``sqrt(2|theta|/|Gamma|)`` bp/day with the strat1 status taxonomy.

    The sign pair decides the branch (see the module docstring):

    ==========  ==========  =============  ==============================
    theta       Gamma       status         value (bp/day)
    ==========  ==========  =============  ==============================
    < 0         > 0         root           sqrt(2|theta|/Gamma)  (long gamma pays rent)
    > 0         < 0         root           sqrt(2 theta/|Gamma|) (short gamma collects rent)
    >= 0        >= 0        always_cheap   0.0   (never needs vol to break even)
    <= 0        <= 0        never_cheap    inf   (no vol level breaks even)
    == 0        == 0        undefined      NaN
    non-finite  any         undefined      NaN
    ==========  ==========  =============  ==============================

    ``always_cheap`` -> 0.0 and ``never_cheap`` -> inf follow
    ``strat1_curve_gamma.breakeven_vol`` exactly; collapsing both to NaN would
    hide OPPOSITE states (its docstring's own warning).
    """
    th = float(theta_usd_day)
    g = float(gamma_usd_per_bp2)
    if not (math.isfinite(th) and math.isfinite(g)):
        return (float("nan"), "undefined")
    if (th < 0.0 < g) or (g < 0.0 < th):
        return (math.sqrt(2.0 * abs(th) / abs(g)), "root")
    if th == 0.0 and g == 0.0:
        return (float("nan"), "undefined")
    if th >= 0.0 and g >= 0.0:
        return (0.0, "always_cheap")
    return (float("inf"), "never_cheap")


def rent_row(
    pricer: Any,
    package: Sequence[Any],
    *,
    dv01_usd: float,
    carry_bp_yr: float,
    shifts: Sequence[float] = DEFAULT_SHIFTS_BP,
    business_days: float = BUSINESS_DAYS_PER_YEAR,
) -> RentRow:
    """Compose the rent block for one package on one day.

    ``dv01_usd`` is the package's (positive) DV01 scale in USD/bp;
    ``carry_bp_yr`` is the signed repriced carry-and-roll in bp of that DV01
    per year (from ``CvxSuite.carry`` — the ``handle.roll`` / aged-rate
    identity path). Then::

        carry_bp_day  = carry_bp_yr / business_days
        theta_usd_day = carry_bp_day * dv01_usd        (== roll_1y_usd / 252)
        sigma_be, status = sigma_be_bp_day(theta_usd_day, package_gamma_usd(...))

    which reproduces strat3's ``be_daily_exact = sqrt(2*|roll_1y/252|/gamma)``
    identically. A NaN ``carry_bp_yr`` propagates to a NaN theta and an
    ``undefined`` status (refusal, not zero); a non-positive or non-finite
    ``dv01_usd`` raises ``ValueError``.
    """
    dv01 = float(dv01_usd)
    if not math.isfinite(dv01) or dv01 <= 0.0:
        raise ValueError(f"rent_row: dv01_usd must be a finite positive USD/bp scale, got {dv01_usd!r}")
    bdays = float(business_days)
    if not math.isfinite(bdays) or bdays <= 0.0:
        raise ValueError(f"rent_row: business_days must be finite and positive, got {business_days!r}")
    gamma = package_gamma_usd(pricer, package, shifts=shifts)
    carry_bp_day = float(carry_bp_yr) / bdays
    theta_usd_day = carry_bp_day * dv01
    be, status = sigma_be_bp_day(theta_usd_day, gamma)
    return RentRow(
        gamma_usd_per_bp2=gamma,
        theta_usd_day=theta_usd_day,
        carry_bp_day=carry_bp_day,
        sigma_be_bp_day=be,
        status=status,
    )
