"""Query object for the paired exchange-vol vs OTC-vol structure.

One query = one *pair*: a futures-option leg on ``product`` and a swaption leg on ``tail``, struck
at a common signed yield offset from each leg's own forward, vega-matched, delta-hedged.

The structure is deliberately modelled as a single position rather than two. A
``ResolvedQueryPosition`` resolves one query through one adapter, so its package is homogeneous;
holding the pair as one position keeps the vega match, the strikes and the hedge state in one
place, which is where they have to be for the P&L to mean anything. The alternative -- two
positions bound by a shared tag -- is the framework's idiom for genuinely separable legs, and
these are not separable: the whole object is the spread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from Query.Base.BaseQuery import BaseQuery
from Query.BasisVsVol import adapter as _adapter  # noqa: F401  (registers product + handler)

PRODUCT = "BASISVSVOL"


@dataclass(frozen=True)
class BasisVsVolQuery(BaseQuery):
    ustf_product: str = "US"
    tail: str = "20Y"
    expiry_label: str = "3M"
    offset_bps: float = 0.0
    side: int = 1  # +1 = long swaption vol / short futures-option vol
    target_vega_usd: float = 100_000.0
    rehedge_days: int = 1
    hedge_cost_bp: float = 0.10
    cost_mult: float = 1.0
    max_gap_days: int = 5

    def __post_init__(self):
        object.__setattr__(self, "product", PRODUCT)
        object.__setattr__(self, "structure_id", "PAIR")
        req = dict(self.market_request or {})
        req.setdefault("product", self.ustf_product)
        req.setdefault("tail", self.tail)
        object.__setattr__(self, "market_request", req)

    # --- BaseQuery abstract surface -----------------------------------------
    def return_query(self) -> "BasisVsVolQuery":
        return self

    def col_name(self, cube_name: Optional[str] = None) -> str:
        return (f"BVV|{self.ustf_product}|{self.expiry_label}|{self.tail}"
                f"|off{self.offset_bps:+g}|side{self.side:+d}")

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return self.col_name(cube_name)
