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

__all__ = ["PricingContext", "ReplicationConfig", "simulate", "reconcile"]


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
            target_long = cfg.sign * cfg.package_dv01_usd / ctx.dv01(d, "long")
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
