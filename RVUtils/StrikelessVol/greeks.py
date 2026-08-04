"""Greeks by repricing. No assumed convexity constants, no quadratic toy.

The rateslib backend raises on ``dv01``/``gamma``/``dollar_carry`` because a
true DV01 needs a calibrated ``rl.Solver`` it does not carry. So this module
bumps the curve itself (``rl.Curve.shift``, in **bp**) and reprices, and takes
theta from ``rl.Curve.translate`` (advance the valuation date, hold the curve).
Nothing here calls the three raising methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

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


def gamma_by_h(curve, package: Package, *, h_bps=(10.0, 25.0, 50.0)) -> dict:
    """Convexity at several move sizes. Reported, never averaged away."""
    return {float(h): package_gamma(curve, package, h_bp=float(h)) for h in h_bps}


def analytic_leg_gamma(curve, swap) -> float:
    """Closed-form d2PV/dShift2 for one leg, in dollars per bp squared.

    Independent of the bump code: takes discount factors and fixed-leg accruals
    straight off the curve and differentiates the single-curve replication

        PV(D) = N * [ D(T0) e^{-D t0} - D(TN) e^{-D tN}
                      - k * sum_i tau_i D(Ti) e^{-D ti} ]

    so d2PV/dD2 = N * [ t0^2 D(T0) - tN^2 D(TN) - k * sum_i tau_i ti^2 D(Ti) ],
    scaled by 1e-8 to convert per-decimal into per-bp-squared.
    """
    handle = curve.handle()
    ref = curve.reference_date()
    notional = float(curve.notional(swap))
    k = float(curve.fixed_rate(swap))  # decimal

    cf = swap.leg1.cashflows(handle)
    t0 = (pd.Timestamp(curve.effective_date(swap)) - pd.Timestamp(ref)).days / 365.0
    tN = (pd.Timestamp(curve.maturity_date(swap)) - pd.Timestamp(ref)).days / 365.0
    d0 = float(handle[curve.effective_date(swap)])
    dN = float(handle[curve.maturity_date(swap)])

    annuity_term = 0.0
    for _, row in cf.iterrows():
        pay = pd.Timestamp(row["Payment"])
        tau = float(row["DCF"])
        ti = (pay - pd.Timestamp(ref)).days / 365.0
        di = float(handle[pay.to_pydatetime()])
        annuity_term += tau * ti * ti * di

    second_derivative = notional * (t0 * t0 * d0 - tN * tN * dN - k * annuity_term)
    return second_derivative * 1e-8
