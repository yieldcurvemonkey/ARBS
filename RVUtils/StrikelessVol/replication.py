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

    increments: list[tuple[float, float]] = []  # (delta_notional, rate_at_trade)
    last_hedge_rate_bp = ctx.rate(d0, "long") * 1e4
    inception = pd.Timestamp(d0)
    roll_days = int(round(cfg.roll_months * 21))

    n_long_base = n_long  # notional before any resize increments
    prev_pv = ctx.pv(d0, n_long, n_short)
    prev_base_pv = prev_pv
    prev_long_rate_bp = last_hedge_rate_bp
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

    days_held = 0
    for d in dates[1:]:
        days_held += 1
        long_rate_bp = ctx.rate(d, "long") * 1e4

        # what actually happened, on everything held
        total_pv_change = ctx.pv(d, n_long, n_short) - prev_pv

        # 1. carry: a day passing with the curve unchanged
        carry = float(ctx.theta(d, n_long, n_short))

        # 2. mtm: the curve move on the BASE notionals only, net of their carry
        base_pv = ctx.pv(d, n_long_base, n_short)
        base_carry = float(ctx.theta(d, n_long_base, n_short))
        mtm = (base_pv - prev_base_pv) - base_carry

        # 3. harvest: each increment marked from the rate it was traded at
        harvest = sum(
            dn * (long_rate_bp - prev_long_rate_bp) * dv01_long_unit
            for dn, _ in increments
        )

        # 4. cross: the plug. Second-order terms the three buckets above cannot
        #    hold -- chiefly the increments' own convexity within the day. It is
        #    computed, never assumed zero: defining mtm as the residual would
        #    force this to zero by construction and make reconciliation vacuous.
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
                increments.append((delta_n, long_rate_bp))
                n_long = target_long
                cost -= costs.cost_usd("hedge", abs(delta_n) * ctx.dv01(d, "long"))
                n_hedges = 1
            last_hedge_rate_bp = long_rate_bp

        if days_held >= roll_days:
            cost -= costs.cost_usd("roll", abs(cfg.package_dv01_usd))
            days_held = 0
            inception = pd.Timestamp(d)
            increments.clear()
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
        prev_long_rate_bp = long_rate_bp

    led = pd.DataFrame(rows).set_index("date")
    led["total"] = led[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    return led


def reconcile(ledger: pd.DataFrame) -> dict:
    """The plug must be small and trendless, not zero.

    Theta, base-notional MTM and increment MTM leave second-order cross terms.
    A growing plug means the attribution is wrong; a plug that quietly absorbs
    the harvest is how H10 would fake itself.
    """
    if ledger.empty:
        return {"max_abs_cross_frac": 0.0, "cross_trend_t": 0.0, "ok": True}
    total = ledger["total"].abs().sum()
    cross = ledger["cross"].abs().sum()
    frac = float(cross / total) if total else 0.0
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
        "max_abs_cross_frac": frac,
        "cross_trend_t": t,
        "ok": bool(frac < 0.01 and abs(t) < 3.0),
    }
