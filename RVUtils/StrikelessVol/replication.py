"""Path-wise replication of the delta-hedged straddle.

The rebalancing rule IS the option replication: unhedged, a forward flattener is
a curve position with a story. Resizing the longer leg back to DV01 neutral at
fixed move triggers is grid gamma-scalping, and it applies on both sides -- a
steepener runs the short-straddle ledger (carry collected, convexity paid).

The simulator talks to a ``PricingContext``, so it is fully testable against a
closed-form synthetic world with no market data anywhere near it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import CostSchedule

__all__ = ["CurvePricer", "PricingContext", "ReplicationConfig", "simulate", "reconcile"]


class PricingContext(Protocol):
    def rate(self, date, leg: str) -> float: ...
    def dv01(self, date, leg: str) -> float: ...
    def pv(self, date, notional_long: float, notional_short: float) -> float: ...
    def theta(self, date, notional_long: float, notional_short: float) -> float: ...


@dataclass(frozen=True)
class ReplicationConfig:
    trigger_bp: float = 25.0
    roll_months: int = 12
    package_dv01_usd: float = 100_000.0
    sign: int = FLATTENER
    hedge_instrument: str = "long_leg"  # or "spot_atm"


def simulate(
    ctx: PricingContext,
    dates: Sequence,
    cfg: ReplicationConfig,
    costs: CostSchedule,
) -> pd.DataFrame:
    """Run the rule down a path and keep the five ledgers separately."""
    dates = list(dates)
    if not dates:
        return pd.DataFrame()

    d0 = dates[0]
    dv01_long_unit = ctx.dv01(d0, "long")
    dv01_short_unit = ctx.dv01(d0, "short")

    n_long = cfg.sign * cfg.package_dv01_usd / dv01_long_unit
    n_short = -cfg.sign * cfg.package_dv01_usd / dv01_short_unit

    last_hedge_rate_bp = ctx.rate(d0, "long") * 1e4
    inception = pd.Timestamp(d0)
    # Date-based, not row-counted: ``dates`` may be a business-day index (as
    # in the synthetic tests), a calendar-day index, or a real dated curve
    # (Task 13). Counting elapsed rows and assuming ~21/month drifts against
    # any of those -- ~11.6 months on a business-day index, ~8.3 on a
    # calendar-day one, per the actual number of rows a "month" contains.
    # DateOffset tracks the calendar directly, so the roll fires at the same
    # elapsed wall-clock time regardless of what ``dates`` is sampled on.
    roll_due = inception + pd.DateOffset(months=cfg.roll_months)

    n_long_base = n_long  # notional before any resize increments
    prev_pv = ctx.pv(d0, n_long, n_short)
    prev_base_pv = prev_pv
    rows = [
        {
            "date": pd.Timestamp(d0),
            "carry": 0.0,
            "harvest": 0.0,
            "mtm": 0.0,
            "cross": 0.0,
            "cost": -costs.cost_usd("initiate", abs(cfg.package_dv01_usd)),
            "n_hedges": 0,
            "long_notional": n_long,
            "short_notional": n_short,
            "position_age_years": 0.0,
        }
    ]

    for d in dates[1:]:
        long_rate_bp = ctx.rate(d, "long") * 1e4

        # what actually happened, on everything held
        full_pv_today = ctx.pv(d, n_long, n_short)
        total_pv_change = full_pv_today - prev_pv

        # 1. carry: a day passing with the curve unchanged
        carry = float(ctx.theta(d, n_long, n_short))

        # 2. mtm: the curve move on the BASE notionals only, net of their carry
        base_pv = ctx.pv(d, n_long_base, n_short)
        base_carry = float(ctx.theta(d, n_long_base, n_short))
        mtm = (base_pv - prev_base_pv) - base_carry

        # 3. harvest: the FULL repriced P&L of the resize increments, net of
        #    their own carry -- not a linear mark from the trade rate. Defined
        #    as (full position PV - base position PV) today, minus the same
        #    difference yesterday, minus the increments' own carry (theta of
        #    the full position minus theta of the base position). This is the
        #    literal difference between the position actually held and the
        #    position that would have been held without ever resizing, so it
        #    is exact -- convexity included -- with no separate formula for
        #    the increments' own gamma to get wrong or leave out. carry, mtm
        #    and harvest now partition total_pv_change as a property of this
        #    definition (each is pv(full)-pv(base) or pv(base) alone, net of
        #    its own carry), not because harvest is written as a residual.
        increment_pv_today = full_pv_today - base_pv
        increment_pv_yesterday = prev_pv - prev_base_pv
        increment_carry = carry - base_carry
        harvest = (increment_pv_today - increment_pv_yesterday) - increment_carry

        # 4. cross: retained as a completeness check on the ARITHMETIC only --
        #    that the four terms above were summed and subtracted correctly,
        #    nothing more. It is NOT a check on the VALUES of carry/mtm/
        #    harvest: expand the definitions and every one of C, Cb, B, Q, A,
        #    P cancels algebraically, so cross == 0 for any six input values,
        #    not just correct ones (carry+mtm+harvest = C+(B-Q-Cb)+((A-B)-
        #    (P-Q)-(C-Cb)) = A-P = total_pv_change, identically). A bug that
        #    corrupts a variable shared symmetrically by two buckets (e.g. a
        #    stale prev_base_pv feeding both mtm and harvest) cancels in this
        #    sum exactly as cleanly as a correct run does -- verified: it
        #    corrupts harvest by 6 orders of magnitude with mtm absorbing the
        #    mirror image, and cross stays at float noise throughout. Do not
        #    read a passing cross as evidence any individual bucket is
        #    right -- use the closed-form value tests below for that.
        cross = total_pv_change - (carry + mtm + harvest)

        cost = 0.0
        n_hedges = 0

        # Tolerance against float round-trip noise: rate() returns a decimal
        # that gets re-expanded to bp here, and a genuine trigger_bp move can
        # land a few ULPs under the threshold (e.g. 24.999999999999943) purely
        # from that round trip. 1e-6 bp is far below anything financially
        # meaningful and only closes that gap.
        if abs(long_rate_bp - last_hedge_rate_bp) >= cfg.trigger_bp - 1e-6:
            # Resize the longer leg back to DV01 NEUTRAL against the shorter
            # leg as actually held -- not to a fixed dollar target. The two
            # rules coincide in the synthetic world (SyntheticCtx's short leg
            # has unit dv01 identically 1.0 and a notional fixed at
            # -sign*package_dv01, so -n_short*1/dv01_long IS
            # sign*package_dv01/dv01_long, and every Task 12 test is
            # unaffected), and they coincide at inception on real curves
            # because both legs start sized to package_dv01_usd. They diverge
            # once the position ages: the shorter leg is never resized, so ITS
            # repriced dv01 drifts too, and hedging the longer leg back to a
            # fixed $100k left the package with a measured residual delta of
            # ~$4.6k/bp after two months on real USD-OIS curves -- a naked
            # directional position on a package whose entire premise is that
            # it has none, and one that grows with the roll period. Targeting
            # neutrality removes it by construction.
            target_long = -n_short * ctx.dv01(d, "short") / ctx.dv01(d, "long")
            delta_n = target_long - n_long
            if delta_n != 0.0:
                n_long = target_long
                cost -= costs.cost_usd("hedge", abs(delta_n) * ctx.dv01(d, "long"))
                n_hedges = 1
            last_hedge_rate_bp = long_rate_bp

        if pd.Timestamp(d) >= roll_due:
            cost -= costs.cost_usd("roll", abs(cfg.package_dv01_usd))
            inception = pd.Timestamp(d)
            roll_due = inception + pd.DateOffset(months=cfg.roll_months)
            n_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "long")
            n_short = -cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "short")
            n_long_base = n_long
            last_hedge_rate_bp = long_rate_bp

        rows.append(
            {
                "date": pd.Timestamp(d),
                "carry": carry,
                "harvest": harvest,
                "mtm": mtm,
                "cross": cross,
                "cost": cost,
                "n_hedges": n_hedges,
                "long_notional": n_long,
                "short_notional": n_short,
                "position_age_years": (pd.Timestamp(d) - inception).days / 365.0,
            }
        )
        prev_pv = ctx.pv(d, n_long, n_short)
        prev_base_pv = ctx.pv(d, n_long_base, n_short)

    led = pd.DataFrame(rows).set_index("date")
    led["total"] = led[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    return led


class CurvePricer:
    """A ``PricingContext`` backed by real repriced curves.

    Holds ONE aged package: the legs are built on the inception curve and keep
    their dates, so a 10y10y bought today is priced as a 9y10y a year later.
    Panels elsewhere in this package are constant-maturity (see
    ``panels.py``'s module docstring); mixing the two is the vintage trap, so
    the aging lives here and only here. Rebuilding constant-maturity legs each
    day would destroy the position's convexity -- every day would start at par
    with zero accumulated gamma P&L -- and produce exactly the zero-gamma,
    wrong-skew result the Task 13 gate exists to detect.

    **This class does not roll.** It ages one package for as long as it is
    given dates. A strategy that rolls annually is run as one ``CurvePricer``
    (and one ``simulate`` call) per roll period, with the periods sharing
    their boundary date -- see ``scripts/sv_static_long_control.py``. That
    keeps the roll where it belongs (a genuinely new package, built on the
    roll date's curve) instead of inside a pricer whose whole contract is
    "these legs, aged".

    Every quantity the simulator asks for is exactly linear in the notionals,
    which is what lets ``simulate`` decompose the day into base and increment
    slices without any of them being an approximation:

    * ``pv(date, nl, ns) = nl*L(date) + ns*S(date)`` -- rateslib's swap NPV is
      proportional to notional, so the per-unit values ``L``/``S`` are cached
      once per date and every notional slice is one multiply.
    * ``theta(date, nl, ns) = nl*theta_L(date) + ns*theta_S(date)`` -- the
      curve roll is a curve operation, so the package roll is the sum of the
      leg rolls and each leg's roll scales with its own notional. (Scaling the
      whole package roll by the LONG leg's notional ratio, as an earlier draft
      did, silently misprices the short leg's carry by the amount the long leg
      has been resized.)
    """

    def __init__(
        self,
        curve_map: dict,
        pair,
        *,
        package_dv01_usd: float = 100_000.0,
        sign: int = FLATTENER,
    ):
        from RVUtils.StrikelessVol.greeks import build_package

        self._curves = {pd.Timestamp(k): v for k, v in curve_map.items()
                        if v is not None and k != "live"}
        self._dates = sorted(self._curves)
        if not self._dates:
            raise ValueError("CurvePricer needs at least one non-None curve")
        self._pair = pair
        inception_curve = self._curves[self._dates[0]]
        self._pkg = build_package(
            inception_curve, pair, package_dv01_usd=package_dv01_usd, sign=sign,
        )
        # The notionals the legs were BUILT with. Everything below is reported
        # per unit of these, so the simulator's own notionals scale it.
        self._built_notional = {
            "long": float(inception_curve.notional(self._pkg.long)),
            "short": float(inception_curve.notional(self._pkg.short)),
        }
        # date -> the path date before it, so carry can be measured over the
        # interval it was actually earned over rather than the next one.
        self._prev_date = dict(zip(self._dates[1:], self._dates[:-1]))
        self._pv_cache: dict = {}
        self._roll_cache: dict = {}
        self._dv01_cache: dict = {}
        self._rate_cache: dict = {}

    # ---------------------------------------------------------------- access

    @property
    def package(self):
        """The aged package. Exposed so tests can check it never changes."""
        return self._pkg

    def dates(self) -> list:
        return list(self._dates)

    def _curve(self, date):
        return self._curves[pd.Timestamp(date)]

    def _leg(self, leg: str):
        return self._pkg.long if leg == "long" else self._pkg.short

    # ------------------------------------------------------------- pricing

    def rate(self, date, leg: str) -> float:
        """The pair's CONSTANT-MATURITY forward par rate -- the trigger's ruler.

        Deliberately not the aged leg's own fair rate: the rebalancing trigger
        is "the 20y10y has moved 25bp", a statement about the market, and a
        rate that drifts because the position got a month older would fire
        (or fail to fire) the hedge for a reason that has nothing to do with a
        market move. The POSITION ages; the ruler does not.
        """
        key = (pd.Timestamp(date), leg)
        out = self._rate_cache.get(key)
        if out is None:
            curve = self._curve(date)
            spec = self._pair.long if leg == "long" else self._pair.short
            out = float(curve.fair_rate(curve.build_irswap(fwd=spec.fwd, tenor=spec.tail)))
            self._rate_cache[key] = out
        return out

    def dv01(self, date, leg: str) -> float:
        """Repriced dollars per bp of ONE UNIT of that leg's notional, negated.

        Two things are load-bearing here.

        *Repriced, on ``date``'s curve, for the AGED leg.* Freezing this at its
        inception value (as an earlier draft did) makes the resize target
        constant, so ``delta_n`` is identically zero, no hedge ever fires and
        the harvest ledger is dead. The drift in this number IS the gamma the
        strategy scalps, and on real USD-OIS curves it is not small: the 20y10y
        leg's unit dv01 moved 10.3% over two months in 2026.

        *Negated.* ``simulate`` sizes with ``n = sign * package_dv01 / dv01``,
        and a flattener (``sign = +1``) must RECEIVE the longer leg, i.e. hold
        a negative rateslib notional on it (``PAYER_NOTIONAL_SIGN``). A unit-
        notional payer swap has a positive repriced dv01, so returning it
        unnegated would hand ``simulate`` a payer on the longer leg and a
        receiver on the shorter -- a steepener, short convexity, the exact
        sign error the gate's skew test is built to catch. The negation makes
        the notionals reproduce ``greeks.build_leg``'s own direction
        convention identically for both legs and both signs, which is pinned
        by ``test_pricer_notionals_reproduce_build_package``.
        """
        key = (pd.Timestamp(date), leg)
        out = self._dv01_cache.get(key)
        if out is None:
            from RVUtils.StrikelessVol.greeks import _reprice_dv01

            swap = self._leg(leg)
            out = -_reprice_dv01(self._curve(date), swap) / self._built_notional[leg]
            self._dv01_cache[key] = out
        return out

    def _unit_pv(self, date) -> tuple:
        """(long, short) NPV per unit of built notional on ``date``'s curve."""
        ts = pd.Timestamp(date)
        out = self._pv_cache.get(ts)
        if out is None:
            handle = self._curve(ts).handle()
            out = (
                float(self._pkg.long.npv(curves=handle).real) / self._built_notional["long"],
                float(self._pkg.short.npv(curves=handle).real) / self._built_notional["short"],
            )
            self._pv_cache[ts] = out
        return out

    def _unit_roll(self, date) -> tuple:
        """(long, short) carry+roll per unit of built notional INTO ``date``.

        Measured on the PREVIOUS path date's curve, rolled forward to ``date``
        with the package's own dates held fixed (``rl.Curve.roll``, the
        mechanic :func:`greeks.daily_roll_usd` settled on real curves in
        Task 9). Backward-looking on purpose: ``simulate`` uses ``theta(d)`` as
        the carry earned between ``d-1`` and ``d``, so the horizon that belongs
        there is the one that actually elapsed -- which is 3 calendar days into
        a Monday and 1 into a Tuesday. Taking the roll forward from ``d``
        instead (the obvious reading of "one day of carry") attributes
        Monday's three days to Friday and would put a weekend-shaped sawtooth
        into the carry ledger. It cannot change the strategy's total P&L
        either way -- ``mtm`` is defined net of ``theta`` and absorbs any
        redefinition exactly -- but it is the difference between a carry ledger
        that means something and one that does not.

        On the inception date there is no prior curve, so the horizon is one
        calendar day forward; ``simulate`` never asks for carry on that row.
        """
        ts = pd.Timestamp(date)
        out = self._roll_cache.get(ts)
        if out is None:
            prev = self._prev_date.get(ts)
            if prev is None:
                base, horizon = self._curve(ts), ts + pd.Timedelta(days=1)
            else:
                base, horizon = self._curve(prev), ts
            handle = base.handle()
            rolled = handle.roll(horizon.to_pydatetime())
            out = (
                (float(self._pkg.long.npv(curves=rolled).real)
                 - float(self._pkg.long.npv(curves=handle).real)) / self._built_notional["long"],
                (float(self._pkg.short.npv(curves=rolled).real)
                 - float(self._pkg.short.npv(curves=handle).real)) / self._built_notional["short"],
            )
            self._roll_cache[ts] = out
        return out

    def pv(self, date, notional_long: float, notional_short: float) -> float:
        """Reprice the AGED legs on ``date``'s curve at the requested notionals."""
        unit_long, unit_short = self._unit_pv(date)
        return notional_long * unit_long + notional_short * unit_short

    def theta(self, date, notional_long: float, notional_short: float) -> float:
        """One interval of repriced carry, scaled to the notionals held."""
        roll_long, roll_short = self._unit_roll(date)
        return notional_long * roll_long + notional_short * roll_short


CROSS_ABS_TOL_USD: float = 1e-3


def reconcile(ledger: pd.DataFrame) -> dict:
    """Check that the ledger's daily arithmetic sums correctly. Nothing more.

    carry, mtm and harvest are each written as differences of PV/theta calls
    on specific notional slices, and ``cross := total_pv_change - (carry +
    mtm + harvest)``. Expand those definitions with carry=C, mtm=(B-Q-Cb),
    harvest=((A-B)-(P-Q)-(C-Cb)): every symbol cancels, leaving
    ``carry+mtm+harvest = A-P = total_pv_change`` for ANY six input values,
    correct or not. So ``cross`` is an identity of how the code is written,
    not a property that requires carry/mtm/harvest to hold correct values --
    a bug that corrupts a variable shared symmetrically by two buckets (e.g.
    a stale ``prev_base_pv`` feeding both ``mtm`` and ``harvest``) cancels in
    this sum exactly as cleanly as a correct run does. Verified directly:
    that specific mutant corrupts ``harvest`` by six orders of magnitude with
    ``mtm`` absorbing the mirror-image error, and ``cross`` stays at float
    noise (~1e-10) throughout, ``ok`` reporting True.

    What this function actually checks, then, is only that the day's five
    numbers were added up without a transcription slip in the summation
    itself (e.g. a sign flip in the ``cross`` line, or ``total`` summing the
    wrong columns) -- a real but narrow guarantee. It says NOTHING about
    whether carry, mtm or harvest individually hold the right value, and
    should not be read that way. For that, see the closed-form value tests
    in ``tests/test_strikeless_vol_replication.py`` (harvest and carry each
    checked against an independent closed-form expectation derived from the
    synthetic world's own PV formula) -- those are what catch a bug like the
    one above; this function cannot.

    ``max_abs_cross`` and ``max_abs_cross_frac`` (the former as a fraction of
    the path's total absolute P&L) are the numbers the pass/fail bound below
    is built from, both returned so a caller can reproduce or log the gate.
    ``cross_trend_t`` is returned too but is not part of the gate and is not
    a reliable discriminator at this scale -- against the same mutant it sat
    in the same range (tens) as a fully healthy run, because a linear-trend
    fit against a residual already at the float-noise floor is dominated by
    rounding structure, not by whatever produced the residual.
    """
    if ledger.empty:
        return {
            "max_abs_cross": 0.0,
            "max_abs_cross_frac": 0.0,
            "cross_trend_t": 0.0,
            "ok": True,
        }
    total = ledger["total"].abs().sum()
    cross_abs = ledger["cross"].abs()
    max_abs_cross = float(cross_abs.max())
    frac = float(max_abs_cross / total) if total else 0.0
    cum = ledger["cross"].cumsum().to_numpy()
    x = np.arange(len(cum), dtype=float)
    if len(cum) > 2 and np.std(cum) > 0:
        slope, intercept = np.polyfit(x, cum, 1)
        resid = cum - (slope * x + intercept)
        se = np.std(resid, ddof=2) / (np.std(x) * np.sqrt(len(x))) if np.std(x) else np.nan
        t = float(slope / se) if se and np.isfinite(se) else 0.0
    else:
        t = 0.0
    return {
        "max_abs_cross": max_abs_cross,
        "max_abs_cross_frac": frac,
        "cross_trend_t": t,
        "ok": bool(max_abs_cross < CROSS_ABS_TOL_USD),
    }
