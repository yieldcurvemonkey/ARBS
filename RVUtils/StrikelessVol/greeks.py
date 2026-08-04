"""Greeks by repricing. No assumed convexity constants, no quadratic toy.

The rateslib backend raises on ``dv01``/``gamma``/``dollar_carry`` because a
true DV01 needs a calibrated ``rl.Solver`` it does not carry. So this module
bumps the curve itself (``rl.Curve.shift``, in **bp**) and reprices, and takes
theta from ``rl.Curve.translate`` (advance the valuation date, hold the curve).
Nothing here calls the three raising methods.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

# rateslib's leg1 (fixed) notional sign for a PAYER swap. Pinned by
# test_payer_gains_when_rates_rise; flip this constant if that test fails,
# and nothing else in the package needs to change.
PAYER_NOTIONAL_SIGN: int = 1

__all__ = [
    "PAYER_NOTIONAL_SIGN",
    "Package",
    "analytic_leg_gamma",
    "build_leg",
    "build_package",
    "daily_dcf",
    "gamma_by_h",
    "package_dv01",
    "package_gamma",
    "package_npv",
]


@dataclass(frozen=True)
class Package:
    """A DV01-neutral two-leg forward slope position."""

    pair: ForwardPair
    short: Any  # rl.IRS, paid when sign == FLATTENER
    long: Any  # rl.IRS, received when sign == FLATTENER
    short_dv01: float
    long_dv01: float
    sign: int


def build_leg(curve, leg: ForwardLeg, *, dv01_usd: float, direction: int):
    """A forward-starting par swap sized to ``dv01_usd`` dollars per bp.

    ``direction`` is +1 to pay fixed, -1 to receive fixed.
    """
    unit = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=1.0)
    dv01_per_unit = float(curve.pv01(unit))
    if dv01_per_unit == 0.0:
        raise ValueError(f"zero analytic delta for {leg.label}")
    notional = direction * PAYER_NOTIONAL_SIGN * float(dv01_usd) / dv01_per_unit
    return curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=notional)


def build_package(
    curve,
    pair: ForwardPair,
    *,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
) -> Package:
    """DV01-neutral slope package. ``sign=+1`` is the flattener (long convexity)."""
    short = build_leg(curve, pair.short, dv01_usd=package_dv01_usd, direction=+sign)
    long_ = build_leg(curve, pair.long, dv01_usd=package_dv01_usd, direction=-sign)
    return Package(
        pair=pair,
        short=short,
        long=long_,
        short_dv01=float(curve.pv01(short)),
        long_dv01=float(curve.pv01(long_)),
        sign=int(sign),
    )


def package_npv(curve_handle, package: Package) -> float:
    """Package PV on an arbitrary curve handle (base, shifted or translated)."""
    return float(
        package.short.npv(curves=curve_handle).real
        + package.long.npv(curves=curve_handle).real
    )


def package_dv01(curve, package: Package, *, h_bp: float = 1.0) -> float:
    """Dollars per bp, central difference on a parallel reprice."""
    handle = curve.handle()
    up = package_npv(handle.shift(h_bp), package)
    dn = package_npv(handle.shift(-h_bp), package)
    return (up - dn) / (2.0 * h_bp)


def package_gamma(curve, package: Package, *, h_bp: float = 25.0) -> float:
    """Dollars per bp squared, second difference on parallel reprices."""
    handle = curve.handle()
    base = package_npv(handle, package)
    up = package_npv(handle.shift(h_bp), package)
    dn = package_npv(handle.shift(-h_bp), package)
    return (up + dn - 2.0 * base) / (h_bp ** 2)


def gamma_by_h(
    curve,
    package: Package,
    *,
    h_bps: Sequence[float] = (10.0, 25.0, 50.0),
) -> dict[float, float]:
    """Convexity at several move sizes. Reported, never averaged away."""
    return {float(h): package_gamma(curve, package, h_bp=float(h)) for h in h_bps}


def _as_dt(date: Any) -> datetime:
    """Normalise any rateslib/pandas date to a plain ``datetime``."""
    return pd.Timestamp(date).to_pydatetime()


def daily_dcf(handle) -> float:
    """The 1-day DCF implied by the curve's own day-count convention.

    ``rl.Curve.shift`` builds its shifted curve with terminal discount factor
    ``1 / (1 + d * shift / 10000) ** n`` over the curve's whole span, where
    ``n = (final - initial).days`` and ``d = dcf(span) / n``
    (``rateslib/curves/curves.py:955-960`` and ``curves/utils.py:609-615``).
    Log-linear interpolation then makes the time exponent the bump actually
    applies at date ``T`` equal to ``(T - initial).days * d`` -- so ``1/365``
    under *act365f* but ``1/360`` under *act360*.

    Hard-coding ``1/365`` understates ``t`` by ``360/365`` on an act360 curve,
    and gamma goes as ``t**2``, so the control would read ``(360/365)**2``
    low -- a deterministic 2.7% miss straight through the 2% band. The USD
    SOFR curves this repo builds are act360
    (``rl_curve_definitions_map.py``), so that is the normal case, not an
    edge case.

    Derived from ``handle.meta.convention``, never from ``shift`` itself: the
    control has to stay independent of the code it is checking.
    """
    meta = handle.meta
    nodes = handle.nodes
    span_days = (nodes.final - nodes.initial).days
    span_dcf = rl.dcf(nodes.initial, nodes.final, meta.convention, calendar=meta.calendar)
    return float(span_dcf) / span_days


def analytic_leg_gamma(curve, swap) -> float:
    """Closed-form d2PV/dShift2 for one leg, in dollars per bp squared.

    Independent of the bump code: takes discount factors and fixed-leg accruals
    straight off the curve and differentiates the single-curve replication

        PV(D) = N * [ D(T0) e^{-D t0} - D(TN) e^{-D tN}
                      - k * sum_i tau_i D(Ti) e^{-D ti} ]

    so d2PV/dD2 = N * [ t0^2 D(T0) - tN^2 D(TN) - k * sum_i tau_i ti^2 D(Ti) ],
    scaled by 1e-8 to convert per-decimal into per-bp-squared. ``t`` is measured
    with the curve's own daily DCF (see :func:`daily_dcf`), which is what the
    shift machinery uses.

    **The float leg's ``D(T0) - D(TN)`` telescoping assumes the leg's day-count
    convention matches the curve's.** rateslib compounds the RFR off the curve
    (curve convention) and then multiplies by the leg's own accrual fraction, so
    when the two disagree the float leg is scaled by ``tau_leg / tau_curve`` and
    the replication is off by exactly that ratio. A ``usd_irs`` swap (act360
    legs) on an act365f curve therefore misses by 365/360 = 1.39% on the float
    leg. Matched conventions -- the production case -- agree to ~0.05%.

    Residual against a repriced bump, on matched conventions, is second-order:
    the second difference's own truncation error, rateslib's discrete
    ``(1 + d*s)**n`` against this formula's ``e^{-Dt}`` (~0.01% on t), and
    payment lag (~0.0003%, measured -- the lagged-float replication and this
    one agree to 4 decimal places).
    """
    handle = curve.handle()
    ref = _as_dt(curve.reference_date())
    notional = float(curve.notional(swap))
    k = float(curve.fixed_rate(swap))  # decimal
    d = daily_dcf(handle)

    def _t(date: Any) -> float:
        return (_as_dt(date) - ref).days * d

    eff = _as_dt(curve.effective_date(swap))
    mat = _as_dt(curve.maturity_date(swap))
    t0, tN = _t(eff), _t(mat)
    d0, dN = float(handle[eff]), float(handle[mat])

    annuity_term = 0.0
    for _, row in swap.leg1.cashflows(handle).iterrows():
        pay = _as_dt(row["Payment"])
        tau = float(row["DCF"])
        ti = _t(pay)
        annuity_term += tau * ti * ti * float(handle[pay])

    second_derivative = notional * (t0 * t0 * d0 - tN * tN * dN - k * annuity_term)
    return second_derivative * 1e-8
