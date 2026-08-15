"""Ho-Lee convexity adjustment for STIR futures, and its inversion to implied vol.

Citi's STIR convexity screen defines the adjustment for a 1y pack as::

    "Convexity adjustments for 1y SFR packs are computed as the spread between
     the pack's rate (the average of 4 ED rates in the pack) and matched
     maturity forward 1y swap rate. The model for convexity adjustment is the
     Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by
     matching the model to the observed convexity adjustment. Realized vol is
     3m realized vol of the corresponding pack."

Under Ho-Lee (constant absolute/normal volatility, no mean reversion) the
futures rate exceeds the matched forward rate by a ``1/2 * sigma^2 * (time)^2``
term. **Two conventions for that time factor are supported, and they are not
interchangeable:**

``convention="citi"`` (default) -- ``1/2 * sigma^2 * T1^2``
    What Citi's published tables actually use. Recovered empirically by solving
    for sigma against the printed "Implied Vol" column of eight published
    screens (seven ED, one SOFR): the ratio ``sigma_fit / sigma_reported`` has
    median 0.9998-1.0004 on every table, i.e. flat to within a few basis points
    of a percent.

``convention="hull"`` -- ``1/2 * sigma^2 * T1 * T2``
    The textbook Ho-Lee/Hull result, with ``T2 = T1 + 0.25`` for a 3M contract.
    Correct as theory, but it does **not** reproduce Citi's tables: across the
    12-Jan-2017 screen the fitted ratio drifts monotonically 0.933 -> 0.975, a
    clear maturity-dependent bias. Kept because it is the standard result and
    Hull's worked example pins the arithmetic.

``T1`` is the ACT/365 year fraction from the as-of date to the contract's IMM
date (3rd Wednesday of the delivery month).

A **pack** is four consecutive quarterly contracts. Its rate is the simple
average of the four contract rates, so its model adjustment is the simple
average of the four contract adjustments::

    CA_pack = 1/2 * sigma^2 * mean_i(w_i)      w_i = T1_i^2   or   T1_i * T2_i

which inverts in closed form -- the model is quadratic in sigma, so no root
find is needed::

    sigma = sqrt( 2 * CA_pack / mean_i(w_i) )

Everything here is in **decimal rate units** internally (0.0001 = 1bp) with
explicit ``_bp`` helpers at the boundary, because mixing the two is the classic
way to get a 100x error in a convexity number and not notice.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

__all__ = [
    "ho_lee_ca",
    "ho_lee_ca_bp",
    "pack_time_weight",
    "pack_ca",
    "pack_ca_bp",
    "implied_vol_from_ca",
    "implied_vol_from_ca_bp",
    "ACCRUAL_3M",
]

#: Accrual length of a 3M SOFR (SFR/SR3) or Eurodollar (ED) contract, in years.
ACCRUAL_3M = 0.25


def ho_lee_ca(sigma: float, t1: float, t2: float) -> float:
    """Ho-Lee convexity adjustment, decimal rate units.

    ``sigma`` is the absolute (normal) short-rate vol in decimal per sqrt-year,
    e.g. ``0.012`` for 120bp/yr. ``t1``/``t2`` in years.
    """
    return 0.5 * float(sigma) ** 2 * float(t1) * float(t2)


def ho_lee_ca_bp(sigma_bp: float, t1: float, t2: float) -> float:
    """Ho-Lee convexity adjustment in **bp**, from a vol quoted in **bp/yr**."""
    return ho_lee_ca(float(sigma_bp) / 1e4, t1, t2) * 1e4


#: Citi's published screens use T1^2; the textbook Ho-Lee/Hull form uses T1*T2.
CITI = "citi"
HULL = "hull"
DEFAULT_CONVENTION = CITI


def pack_time_weight(
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
    convention: str = DEFAULT_CONVENTION,
) -> float:
    """``mean_i(w_i)`` for a pack whose contracts expire at *t1s*.

    ``w_i = T1_i^2`` under ``convention="citi"``, ``T1_i * (T1_i + accrual)``
    under ``"hull"``.
    """
    t1 = np.asarray(list(t1s), dtype=float)
    if t1.size == 0:
        return float("nan")
    conv = str(convention).lower()
    if conv == CITI:
        return float(np.mean(t1 * t1))
    if conv == HULL:
        return float(np.mean(t1 * (t1 + float(accrual))))
    raise ValueError(f"unknown convention {convention!r}; expected 'citi' or 'hull'")


def pack_ca(
    sigma: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
    convention: str = DEFAULT_CONVENTION,
) -> float:
    """Model convexity adjustment of a pack, decimal rate units."""
    return 0.5 * float(sigma) ** 2 * pack_time_weight(t1s, accrual, convention)


def pack_ca_bp(
    sigma_bp: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
    convention: str = DEFAULT_CONVENTION,
) -> float:
    """Model convexity adjustment of a pack in **bp**, vol in **bp/yr**."""
    return pack_ca(float(sigma_bp) / 1e4, t1s, accrual, convention) * 1e4


def implied_vol_from_ca(
    ca: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
    convention: str = DEFAULT_CONVENTION,
) -> float:
    """Invert the pack adjustment for the Ho-Lee vol. Decimal in, decimal out.

    Returns NaN for a non-positive observed adjustment: a negative CA is not
    representable under Ho-Lee (the adjustment is a variance and cannot be
    negative), and in practice signals either a data problem or a genuinely
    inverted futures/forward basis that this model has nothing to say about.
    Citi's own screens print ``n/a`` in exactly that case (e.g. the 16-Jan-2020
    table, which carries a negative CA and two ``n/a`` implied vols).
    """
    w = pack_time_weight(t1s, accrual, convention)
    if not np.isfinite(w) or w <= 0:
        return float("nan")
    if not np.isfinite(ca) or ca <= 0:
        return float("nan")
    return float(np.sqrt(2.0 * float(ca) / w))


def implied_vol_from_ca_bp(
    ca_bp: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
    convention: str = DEFAULT_CONVENTION,
) -> float:
    """Implied Ho-Lee vol in **bp/yr** from an adjustment quoted in **bp**."""
    sigma = implied_vol_from_ca(float(ca_bp) / 1e4, t1s, accrual, convention)
    return float(sigma * 1e4) if np.isfinite(sigma) else float("nan")
