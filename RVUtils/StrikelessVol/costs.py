"""Transaction costs for forward-slope packages.

Priors from the research brief, at $100k DV01 clips: 0.75-1.0bp to initiate,
0.3-0.4bp per hedge or roll, one way. Defaults are the midpoints. Every result
in this study is reported at multiplier 0, 1 and 2 -- capacity is a first-order
constraint here, so the conclusion is stated in clips, not in ratios.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CostSchedule", "FREE", "MAKER", "TAKER"]


@dataclass(frozen=True)
class CostSchedule:
    initiate_bp: float = 0.875
    hedge_bp: float = 0.35
    roll_bp: float = 0.35
    clip_dv01_usd: float = 100_000.0
    clip_exponent: float = 0.0
    multiplier: float = 1.0

    def cost_usd(self, kind: str, dv01_traded_usd: float) -> float:
        """Dollars charged for trading ``dv01_traded_usd`` of risk."""
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


FREE = CostSchedule(multiplier=0.0)
MAKER = CostSchedule(initiate_bp=0.75, hedge_bp=0.30, roll_bp=0.30)
TAKER = CostSchedule(initiate_bp=1.00, hedge_bp=0.40, roll_bp=0.40)
