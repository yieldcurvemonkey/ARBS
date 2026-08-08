"""Transaction costs for forward-slope packages.

Priors from the research brief, at $100k DV01 clips: 0.75-1.0bp to initiate,
0.3-0.4bp per hedge or roll, one way. Defaults are the midpoints. Every result
in this study is reported at multiplier 0, 1 and 2 -- capacity is a first-order
constraint here, so the conclusion is stated in clips, not in ratios.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["CostSchedule", "FREE", "MAKER", "TAKER", "charge_usd"]


@dataclass(frozen=True)
class CostSchedule:
    initiate_bp: float = 0.875
    hedge_bp: float = 0.35
    roll_bp: float = 0.35
    clip_dv01_usd: float = 100_000.0
    clip_exponent: float = 0.0
    multiplier: float = 1.0

    def cost_usd(self, kind: str, dv01_traded_usd: float) -> float:
        """Dollars charged for trading ``dv01_traded_usd`` of risk.

        Returns a non-negative magnitude regardless of the sign of ``dv01_traded_usd``.
        Callers subtract this from signed P&L to account for transaction costs.
        """
        rate_bp = {
            "initiate": self.initiate_bp,
            "hedge": self.hedge_bp,
            "roll": self.roll_bp,
        }[kind]
        dv01 = abs(float(dv01_traded_usd))
        if dv01 == 0.0:
            return 0.0
        size_factor = (
            (dv01 / self.clip_dv01_usd) ** self.clip_exponent
            if self.clip_exponent
            else 1.0
        )
        return self.multiplier * rate_bp * dv01 * size_factor


def charge_usd(
    volumes,
    schedule: CostSchedule,
    *,
    multiplier: float | None = None,
    roll_charged: bool = True,
):
    """Fee, in dollars, for a frame of traded-risk volumes. Non-negative.

    ``volumes`` is a DataFrame carrying ``replication.TRADED_DV01_COLS`` -- the
    RISK traded per day, which ``simulate`` records separately from the fee
    precisely so the same path can be repriced. Two knobs matter and both are
    reported as their own dimension in :func:`report.cost_table`:

    * ``multiplier`` -- costs are first-order here (41% of gross at 1x on the
      static long, 83% at 2x), so no number is quoted at one multiplier only.
    * ``roll_charged`` -- whether the annual roll is charged at all. That
      single convention was measured at **67.5% of the static book's
      headline**, which makes it a result in its own right rather than a
      modelling detail to bury inside a total.
    """
    import pandas as pd

    from RVUtils.StrikelessVol.replication import COST_KIND_BY_VOLUME_COL

    sched = schedule if multiplier is None else replace(schedule, multiplier=float(multiplier))
    out = pd.Series(0.0, index=volumes.index)
    for col, kind in COST_KIND_BY_VOLUME_COL.items():
        if col not in volumes.columns:
            continue
        if kind == "roll" and not roll_charged:
            continue
        vol = volumes[col].astype(float).fillna(0.0)
        if sched.clip_exponent:
            out = out + vol.map(lambda v: sched.cost_usd(kind, v))
        else:
            # exactly linear in the volume when there is no size penalty
            rate = {"initiate": sched.initiate_bp, "hedge": sched.hedge_bp,
                    "roll": sched.roll_bp}[kind]
            out = out + sched.multiplier * rate * vol.abs()
    return out


FREE = CostSchedule(multiplier=0.0)
MAKER = CostSchedule(initiate_bp=0.75, hedge_bp=0.30, roll_bp=0.30)
TAKER = CostSchedule(initiate_bp=1.00, hedge_bp=0.40, roll_bp=0.40)
