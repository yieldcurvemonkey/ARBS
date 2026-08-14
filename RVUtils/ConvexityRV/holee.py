"""Ho-Lee convexity adjustment for STIR futures, and its inversion to implied vol.

Citi's STIR convexity screen defines the adjustment for a 1y pack as::

    "Convexity adjustments for 1y SFR packs are computed as the spread between
     the pack's rate (the average of 4 ED rates in the pack) and matched
     maturity forward 1y swap rate. The model for convexity adjustment is the
     Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by
     matching the model to the observed convexity adjustment. Realized vol is
     3m realized vol of the corresponding pack."

Under Ho-Lee (constant absolute/normal volatility, no mean reversion) the
futures rate exceeds the matched forward rate by

    CA  =  1/2 * sigma^2 * T1 * T2

with ``T1`` the time to the futures expiry and ``T2`` the time to the end of the
rate's accrual period (``T1 + 0.25`` for a 3M contract). This is the standard
Hull result; it is exact for Ho-Lee, and Ho-Lee is the zero-mean-reversion limit
of Hull-White, so it is the conservative (largest) adjustment of that family.

A **pack** is four consecutive quarterly contracts. Its rate is the simple
average of the four contract rates, so its model adjustment is the simple
average of the four contract adjustments::

    CA_pack = 1/2 * sigma^2 * mean_i(T1_i * T2_i)

which inverts in closed form to the implied vol

    sigma = sqrt( 2 * CA_pack / mean_i(T1_i * T2_i) )

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


def pack_time_weight(t1s: Sequence[float], accrual: float = ACCRUAL_3M) -> float:
    """``mean_i(T1_i * T2_i)`` for a pack whose contracts expire at *t1s*."""
    t1 = np.asarray(list(t1s), dtype=float)
    if t1.size == 0:
        return float("nan")
    return float(np.mean(t1 * (t1 + float(accrual))))


def pack_ca(sigma: float, t1s: Sequence[float], accrual: float = ACCRUAL_3M) -> float:
    """Model convexity adjustment of a pack, decimal rate units."""
    return 0.5 * float(sigma) ** 2 * pack_time_weight(t1s, accrual)


def pack_ca_bp(sigma_bp: float, t1s: Sequence[float], accrual: float = ACCRUAL_3M) -> float:
    """Model convexity adjustment of a pack in **bp**, vol in **bp/yr**."""
    return pack_ca(float(sigma_bp) / 1e4, t1s, accrual) * 1e4


def implied_vol_from_ca(
    ca: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
) -> float:
    """Invert the pack adjustment for the Ho-Lee vol. Decimal in, decimal out.

    Returns NaN for a non-positive observed adjustment: a negative CA is not
    representable under Ho-Lee (the adjustment is a variance and cannot be
    negative), and in practice signals either a data problem or a genuinely
    inverted futures/forward basis that this model has nothing to say about.
    """
    w = pack_time_weight(t1s, accrual)
    if not np.isfinite(w) or w <= 0:
        return float("nan")
    if not np.isfinite(ca) or ca <= 0:
        return float("nan")
    return float(np.sqrt(2.0 * float(ca) / w))


def implied_vol_from_ca_bp(
    ca_bp: float,
    t1s: Sequence[float],
    accrual: float = ACCRUAL_3M,
) -> float:
    """Implied Ho-Lee vol in **bp/yr** from an adjustment quoted in **bp**."""
    sigma = implied_vol_from_ca(float(ca_bp) / 1e4, t1s, accrual)
    return float(sigma * 1e4) if np.isfinite(sigma) else float("nan")
