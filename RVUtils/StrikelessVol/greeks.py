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

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

# rateslib's leg1 (fixed) notional sign for a PAYER swap. Pinned by
# test_payer_gains_when_rates_rise; flip this constant if that test fails,
# and nothing else in the package needs to change.
PAYER_NOTIONAL_SIGN: int = 1

__all__ = ["PAYER_NOTIONAL_SIGN", "Package", "build_leg", "build_package", "package_npv"]


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
