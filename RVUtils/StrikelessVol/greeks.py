"""Greeks by repricing. No assumed convexity constants, no quadratic toy.

The rateslib backend raises on ``dv01``/``gamma``/``dollar_carry`` because a
true DV01 needs a calibrated ``rl.Solver`` it does not carry. So this module
bumps the curve itself (``rl.Curve.shift``, in **bp**) and reprices, and takes
theta/roll-down from ``rl.Curve.roll`` (slide the curve's shape forward in
time, holding a package's own cashflow dates fixed -- see
:func:`daily_roll_usd`). ``rl.Curve.translate`` was tried first and found to
give zero carry for any par-struck, not-yet-started forward package regardless
of curve shape (pinned by
``test_translate_yields_no_carry_for_a_par_struck_forward_package``), which is
why it is not used. Nothing here calls the three raising methods.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from utils.rl_compat import leg_cashflows

# rateslib's leg1 (fixed) notional sign for a PAYER swap. Pinned by
# test_payer_gains_when_rates_rise; flip this constant if that test fails,
# and nothing else in the package needs to change.
PAYER_NOTIONAL_SIGN: int = 1

__all__ = [
    "PAYER_NOTIONAL_SIGN",
    "Package",
    "PackageGreeks",
    "analytic_leg_gamma",
    "breakeven_bp_day",
    "build_leg",
    "build_package",
    "compute_greeks",
    "daily_dcf",
    "daily_roll_usd",
    "gamma_by_h",
    "greeks_panel",
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


def _reprice_dv01(curve, swap, *, h_bp: float = 1.0) -> float:
    """Dollars per bp for a single instrument: central difference on a
    +/-``h_bp`` parallel curve shift, repricing the instrument as-is (sign
    and magnitude both reflect the instrument's own current notional).

    This is the spec's DV01 measure -- the same bump-and-reprice used by
    ``package_dv01`` -- factored out so sizing (``build_leg``) and reporting
    (``Package.short_dv01``/``long_dv01``) both speak the one measure instead
    of one of them quietly using the analytic annuity (``curve.pv01``).
    """
    handle = curve.handle()
    up = swap.npv(curves=handle.shift(h_bp)).real
    dn = swap.npv(curves=handle.shift(-h_bp)).real
    return float((up - dn) / (2.0 * h_bp))


def build_leg(curve, leg: ForwardLeg, *, dv01_usd: float, direction: int, h_bp: float = 1.0):
    """A forward-starting par swap sized to ``dv01_usd`` dollars per bp.

    ``direction`` is +1 to pay fixed, -1 to receive fixed.

    Sized off the unit leg's own REPRICED DV01 (:func:`_reprice_dv01`) -- a
    central difference on a +/-``h_bp`` parallel curve shift -- not off
    ``curve.pv01`` (the analytic annuity/``analytic_delta``). The two
    measures diverge once the curve is not flat (on this module's own
    inverted fixture: reprice-DV01/PV01 ratio 1.018 for a 10-20y leg vs 0.904
    for a 20-30y leg), and the package's own neutrality is checked in the
    repriced measure (``package_dv01``), so sizing on the annuity while
    checking neutrality on the reprice would let a directional residual
    sneak into what is supposed to be a pure convexity package. ``curve.pv01``
    remains fine wherever an annuity is genuinely what is wanted; this is
    only about sizing.
    """
    unit = curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=1.0)
    dv01_per_unit = _reprice_dv01(curve, unit, h_bp=h_bp)
    if dv01_per_unit == 0.0:
        raise ValueError(f"zero repriced delta for {leg.label}")
    notional = direction * PAYER_NOTIONAL_SIGN * float(dv01_usd) / dv01_per_unit
    return curve.build_irswap(fwd=leg.fwd, tenor=leg.tail, notional=notional)


def build_package(
    curve,
    pair: ForwardPair,
    *,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
) -> Package:
    """DV01-neutral slope package. ``sign=+1`` is the flattener (long convexity).

    ``short_dv01``/``long_dv01`` are reported in the same repriced measure
    the legs are sized to (:func:`_reprice_dv01`), not ``curve.pv01`` --
    otherwise a reader comparing these fields to the sizing target would see
    a drift that isn't really there (the legs ARE dv01-neutral in the
    measure that matters; only the unrelated annuity isn't).
    """
    short = build_leg(curve, pair.short, dv01_usd=package_dv01_usd, direction=+sign)
    long_ = build_leg(curve, pair.long, dv01_usd=package_dv01_usd, direction=-sign)
    return Package(
        pair=pair,
        short=short,
        long=long_,
        short_dv01=_reprice_dv01(curve, short),
        long_dv01=_reprice_dv01(curve, long_),
        sign=int(sign),
    )


def package_npv(curve_handle, package: Package) -> float:
    """Package PV on an arbitrary curve handle (base, shifted, or rolled)."""
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

    **From rateslib 2.7.1 that caveat is unreachable, not merely unlikely**:
    forecasting an act360 RFR index off an act365f curve raises
    ``ValueError: A `rate_curve` and `rate_index` have been supplied with
    conflicting parameters`` before any number is produced. Kept because it
    explains what the assumption IS, and because it is the reason the
    telescoping is sound wherever this function can now be called at all. See
    ``test_a_curve_index_convention_mismatch_is_now_refused_outright``.

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
    for _, row in leg_cashflows(swap.leg1, handle).iterrows():
        pay = _as_dt(row["Payment"])
        tau = float(row["DCF"])
        ti = _t(pay)
        annuity_term += tau * ti * ti * float(handle[pay])

    second_derivative = notional * (t0 * t0 * d0 - tN * tN * dN - k * annuity_term)
    return second_derivative * 1e-8


def daily_roll_usd(curve, package: Package, *, next_date) -> float:
    """Carry+roll to ``next_date``, in dollars, package dates held fixed.

    ``next_date`` is caller-supplied (see :func:`compute_greeks`'s default,
    which uses exactly one CALENDAR day -- not one business day, since a
    weekend or holiday is not a market convention the curve's shape needs to
    respect, and letting the horizon vary with the calendar would silently
    change the "bp/day" unit ``breakeven_by_h`` is labelled in).

    ``rl.Curve.roll`` slides the curve's *shape* forward in time while holding
    the package's own cashflow dates fixed -- rateslib's own docs call this
    "the traditional direction for measuring roll down on a trade strategy".
    That is the roll-down assumption this module's economics rests on: the
    position's calendar dates stay put while the curve shape (a function of
    tenor-from-today) slides past them, so an inverted ultra-long curve makes
    the flattener bleed.

    This is NOT ``rl.Curve.translate``, which was tried first and found to be
    the wrong primitive: ``translate`` re-bases discounting to a new start
    date but keeps every discount factor's CALENDAR-DATE value identical (up
    to one constant rescale), so a package struck exactly at par -- true of
    every leg this module builds -- reprices to the same zero it started at,
    at ANY horizon before its first cashflow, regardless of curve shape. See
    ``test_translate_yields_no_carry_for_a_par_struck_forward_package`` for
    the pinned record of that finding, which is why the mechanic changed.

    Negative means the position bleeds -- the normal state of a flattener on
    an inverted ultra-long curve.
    """
    handle = curve.handle()
    base = package_npv(handle, package)
    rolled = package_npv(handle.roll(next_date), package)
    return rolled - base


def breakeven_bp_day(daily_roll: float, gamma: float) -> float:
    """The parallel move whose convexity gain pays one day of roll, in bp.

    ``sqrt(2 * |roll| / gamma)``. Undefined (NaN) when convexity is not positive:
    a non-convex package has no breakeven, and returning 0.0 there would read as
    "infinitely cheap".
    """
    if gamma is None or gamma <= 0.0:
        return float("nan")
    return math.sqrt(2.0 * abs(float(daily_roll)) / float(gamma))


@dataclass(frozen=True)
class PackageGreeks:
    date: Any
    pair_name: str
    short_rate: float
    long_rate: float
    spread_bp: float
    short_dv01: float
    long_dv01: float
    package_dv01: float
    gamma_by_h: dict
    daily_roll_usd: float
    breakeven_by_h: dict


def compute_greeks(
    curve,
    pair: ForwardPair,
    *,
    next_date=None,
    package_dv01_usd: float = 100_000.0,
    sign: int = FLATTENER,
    h_bps=(10.0, 25.0, 50.0),
) -> PackageGreeks:
    """Everything for one pair on one date, all of it repriced.

    ``next_date`` defaults to exactly one CALENDAR day forward, not one
    business day. ``roll_bps_running``/``calendar_advance``-style "1b" jumps
    3 calendar days over a weekend and 4 over a holiday-adjacent Friday, and
    with the roll spanning more calendar days the dollar roll and the
    breakeven it feeds both grow with the gap (a real panel showed Friday
    breakevens inflated ~sqrt(3) over midweek ones purely from the horizon,
    not from anything economic) -- while ``breakeven_by_h`` is labelled and
    consumed as bp/*day*. ``rl.Curve.roll`` slides the curve's shape forward
    in time; a weekend is not a market convention it needs to respect, so
    there is no reason to skip it. Pass an explicit ``next_date`` to measure
    a different horizon, but note the "bp/day" label then no longer applies
    literally -- divide the returned $ roll by the horizon's calendar-day
    count first if a genuine daily rate is needed.
    """
    from RVUtils.StrikelessVol.conventions import slope_bp

    pkg = build_package(curve, pair, package_dv01_usd=package_dv01_usd, sign=sign)
    short_rate = float(curve.fair_rate(curve.build_irswap(fwd=pair.short.fwd, tenor=pair.short.tail)))
    long_rate = float(curve.fair_rate(curve.build_irswap(fwd=pair.long.fwd, tenor=pair.long.tail)))

    if next_date is None:
        next_date = curve.reference_date() + timedelta(days=1)

    gammas = gamma_by_h(curve, pkg, h_bps=h_bps)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    return PackageGreeks(
        date=curve.reference_date(),
        pair_name=pair.name,
        short_rate=short_rate,
        long_rate=long_rate,
        spread_bp=slope_bp(short_rate=short_rate, long_rate=long_rate),
        short_dv01=pkg.short_dv01,
        long_dv01=pkg.long_dv01,
        package_dv01=package_dv01(curve, pkg),
        gamma_by_h=gammas,
        daily_roll_usd=roll,
        breakeven_by_h={h: breakeven_bp_day(roll, g) for h, g in gammas.items()},
    )


def greeks_panel(curve_map: dict, pair: ForwardPair, **kwargs) -> pd.DataFrame:
    """One row per date. Dates whose curve cannot price the pair are dropped.

    **What gets dropped is recorded, and dropping EVERY date raises.** The
    ``try`` wraps a whole ``compute_greeks`` -- two ``build_irswap``s, two
    ``fair_rate``s and nine repricings -- so a single date's genuine pricing
    failure and a systematic breakage look identical from outside: both are
    just missing rows. That is not hypothetical. When rateslib 2.7.1 started
    refusing this module's own test fixtures, every date failed, ``rows`` came
    back empty, and the error the caller finally saw was
    ``KeyError: "None of ['date'] are in the columns"`` from ``set_index`` --
    a message about a missing column, for a problem that was a convention
    conflict nine frames down.

    So: the surviving swallow is still per-date (a provider gap on one day
    should not lose the panel), but

    * ``attrs["dropped"]`` maps each dropped timestamp to its exception's
      ``repr``, and ``attrs["n_dropped"]`` counts them;
    * if there was at least one candidate date and NOT ONE of them priced,
      that is a systematic failure and it raises, carrying the first
      exception as its ``__cause__``.

    ``attrs["dates_in"]`` is the number of non-``None`` curves offered, so a
    caller can see the drop rate rather than infer it from a row count.
    """
    rows = []
    dropped: dict = {}
    first_error: Exception | None = None
    candidates = 0
    for ts in sorted(curve_map):
        curve = curve_map[ts]
        if curve is None:
            continue
        candidates += 1
        try:
            g = compute_greeks(curve, pair, **kwargs)
        except Exception as exc:  # per-date: one bad curve must not lose the panel
            dropped[pd.Timestamp(ts)] = repr(exc)
            if first_error is None:
                first_error = exc
            continue
        rec = {
            "date": pd.Timestamp(ts),
            "pair": g.pair_name,
            "short_rate": g.short_rate,
            "long_rate": g.long_rate,
            "spread_bp": g.spread_bp,
            "package_dv01": g.package_dv01,
            "daily_roll_usd": g.daily_roll_usd,
        }
        for h, val in g.gamma_by_h.items():
            rec[f"gamma_h{int(h)}"] = val
        for h, val in g.breakeven_by_h.items():
            rec[f"breakeven_h{int(h)}"] = val
        rows.append(rec)

    if candidates and not rows:
        raise ValueError(
            f"greeks_panel priced 0 of {candidates} dates for {pair.name}. "
            f"Every date raised, so this is a systematic failure, not a data "
            f"gap -- the first one is attached as __cause__. Distinct errors: "
            f"{sorted(set(dropped.values()))[:3]}"
        ) from first_error

    # No candidates at all: an empty panel, correctly shaped. Without this
    # `pd.DataFrame([])` has no "date" column and `set_index` raises the same
    # misleading KeyError the refusal above exists to replace.
    if not rows:
        panel = pd.DataFrame(columns=["date"]).set_index("date")
    else:
        panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.attrs.update({
        "dates_in": candidates,
        "n_dropped": len(dropped),
        "dropped": dropped,
    })
    return panel
