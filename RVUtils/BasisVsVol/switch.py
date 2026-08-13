"""The delivery (switch) option: crossover solver, CF-adjusted DV01 gap, two-bond valuation.

This is M2 of the plan -- the piece that makes the delivery option legible as a vanilla, and the
piece that says when that reduction is safe.

**The reduction.** Write the CF-adjusted forward price of deliverable ``j`` as
``a_j = P_j^fwd / CF_j``. Under a parallel shift ``s`` (bp) of the forward curve,

    a_j(s) = a_j(0) - (DV01_j / CF_j) * s

The current CTD ``c`` is the bond with the lowest ``a``. Its net basis at delivery is

    NB_c(T) = CF_c * max(0, a_c(s) - a_alt(s)) = CF_c * |m| * max(0, +/-(s - s*))

with ``m = DV01_c/CF_c - DV01_alt/CF_alt`` (the CF-adjusted DV01 gap, signed) and the crossover
``s* = (a_c(0) - a_alt(0)) / m``. So the CTD's net basis is exactly a **Bachelier option on the
parallel shift**, struck at ``s*``, with payoff slope ``CF_c * |m|`` per bp. If ``m < 0`` the
switch is triggered by a selloff (a call on the shift, payer-like); if ``m > 0`` by a rally.

**Validation.** Against the J.P. Morgan U.S. Futures and Options Package of 2026-08-12 this
two-bond reduction reproduces the Ultra Bond Sep26 delivery option value to within a tick
(1.05/32 computed vs 0-01 printed), and recovers a crossover of 24.6bp against JPM's printed
28.3bp -- the residual being their beta-adjusted yields and convexity, both of which this
linearisation drops.

**Where it fails, and why that matters.** For the classic Bond (ZB) Sep26 contract the same
calculation gives 1.39/32 against a printed 0-04. It misses 65% of the option value because ZB has
*seven* deliverables with delivery probability above 1% spanning 33 months of maturity, and a
two-bond model can only see one of the six available switches. That is the same conclusion the
CTD-probability sheets force, reached by an independent route, and it is why :func:`map_is_valid`
exists.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .bachelier import implied_normal_vol, normal_price, normal_vega

__all__ = [
    "Deliverable",
    "cf_adjusted_forward_price",
    "cf_adjusted_dv01",
    "dv01_gap",
    "crossover_shift",
    "delivery_option_two_bond",
    "implied_switch_vol",
    "map_is_valid",
    "ThirtySeconds",
]

ThirtySeconds = 32.0


@dataclass(frozen=True)
class Deliverable:
    """One basket member, at forward (delivery-date) values.

    ``price_fwd`` and ``dv01`` are per 100 face, in price points; ``dv01`` is points per bp
    (a JPM ``BPV`` column quoted per $1mm divides by 10,000 to get here).
    """

    label: str
    cf: float
    price_fwd: float
    dv01: float
    prob: float | None = None

    @property
    def a(self) -> float:
        return self.price_fwd / self.cf

    @property
    def a_dv01(self) -> float:
        return self.dv01 / self.cf


def cf_adjusted_forward_price(net_basis_32nds: float, cf: float, futures_price: float) -> float:
    """Recover a forward clean price from a published net basis: ``P_fwd = NB + CF*F``."""
    return net_basis_32nds / ThirtySeconds + cf * futures_price


def cf_adjusted_dv01(dv01: float, cf: float) -> float:
    return dv01 / cf


def dv01_gap(ctd: Deliverable, alt: Deliverable) -> float:
    """Signed CF-adjusted DV01 gap ``m``. Negative => the switch is triggered by a selloff."""
    return ctd.a_dv01 - alt.a_dv01


def crossover_shift(ctd: Deliverable, alt: Deliverable) -> float:
    """Parallel shift ``s*`` (bp) at which ``alt`` takes over as CTD. ``nan`` if the gap vanishes."""
    m = dv01_gap(ctd, alt)
    if abs(m) < 1e-12:
        return float("nan")
    return (ctd.a - alt.a) / m


def delivery_option_two_bond(ctd: Deliverable, alt: Deliverable, sigma_bp: float, tte: float,
                             in_32nds: bool = True) -> dict:
    """Value the CTD's net basis as a Bachelier option on the parallel shift.

    Returns the value, the crossover, the payoff slope and the vega. ``sigma_bp`` is the annualised
    normal vol of the forward yield in bp.
    """
    m = dv01_gap(ctd, alt)
    s_star = crossover_shift(ctd, alt)
    if not np.isfinite(s_star) or not np.isfinite(sigma_bp) or sigma_bp <= 0 or tte <= 0:
        return {"value": float("nan"), "s_star": s_star, "slope": float("nan"),
                "vega": float("nan"), "w": 0, "m": m}
    w = 1 if m < 0 else -1  # m<0: alt wins on a selloff -> payoff for s > s*
    slope = ctd.cf * abs(m)
    px_bp = float(normal_price(0.0, s_star, sigma_bp, tte, w=w))
    veg_bp = float(normal_vega(0.0, s_star, sigma_bp, tte))
    scale = ThirtySeconds if in_32nds else 1.0
    return {
        "value": slope * px_bp * scale,
        "vega": slope * veg_bp * scale,
        "s_star": s_star,
        "slope": slope,
        "w": w,
        "m": m,
    }


def implied_switch_vol(net_basis_32nds: float, ctd: Deliverable, alt: Deliverable,
                       tte: float) -> float:
    """Invert an observed CTD net basis for the normal vol of the forward yield (bp).

    Returns ``nan`` when the option carries no resolvable time value -- the same identification
    discipline as the Bachelier inverter. A served number where the basis cannot identify a vol is
    the failure mode gate G4 exists to prevent.
    """
    m = dv01_gap(ctd, alt)
    s_star = crossover_shift(ctd, alt)
    if not np.isfinite(s_star) or abs(m) < 1e-12 or tte <= 0:
        return float("nan")
    slope = ctd.cf * abs(m)
    if slope <= 0:
        return float("nan")
    px_bp = (net_basis_32nds / ThirtySeconds) / slope
    w = 1 if m < 0 else -1
    return implied_normal_vol(px_bp, 0.0, s_star, tte, w=w)


def map_is_valid(basket: list[Deliverable], prob_floor: float = 0.01,
                 max_span_months: float = 24.0, maturities_months: dict | None = None) -> dict:
    """Gate G7: is a single-swaption, parallel-shift map defensible for this basket?

    The two-bond reduction and the single-swaption mapping both assume the live switch is a
    contest between near-adjacent deliverables. When the set of bonds with non-trivial delivery
    probability spans a wide range of maturities, the switch is driven by curve shape as much as
    by level, and no single vanilla spans it.
    """
    live = [d for d in basket if (d.prob or 0.0) > prob_floor]
    out = {"n_live": len(live), "live_labels": [d.label for d in live]}
    if maturities_months and live:
        ms = [maturities_months[d.label] for d in live if d.label in maturities_months]
        span = (max(ms) - min(ms)) if ms else float("nan")
        out["span_months"] = span
        out["valid"] = bool(np.isfinite(span) and span <= max_span_months)
    else:
        out["span_months"] = float("nan")
        out["valid"] = len(live) <= 2
    out["reason"] = ("ok" if out.get("valid") else
                     f"live basket spans {out['span_months']:.0f}m across {len(live)} deliverables")
    return out
