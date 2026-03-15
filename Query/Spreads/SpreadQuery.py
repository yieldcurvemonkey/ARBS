from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue
from Query.Spreads import adapter as _spread_adapter  # noqa: F401


@dataclass(frozen=True)
class SpreadQuery(BaseQuery):
    structure: SpreadStructure = SpreadStructure.OUTRIGHT
    value: Union[SpreadValue, List[SpreadValue]] = SpreadValue.SPREAD_BPS

    tenor: Optional[str] = None
    curve_a: Optional[str] = None
    curve_b: Optional[str] = None
    source_a: Optional[str] = None
    source_b: Optional[str] = None

    product_key: str = "IRSPREAD"

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="IRSPREAD")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", self.product_key)
        object.__setattr__(self, "structure_id", self.structure)

        # Auto-detect structure from tenor
        tenor_str = self.tenor or ""
        slash_count = tenor_str.count("/")
        if slash_count == 2:
            object.__setattr__(self, "structure", SpreadStructure.FLY)
            object.__setattr__(self, "structure_id", SpreadStructure.FLY)
        elif slash_count == 1:
            object.__setattr__(self, "structure", SpreadStructure.CURVE)
            object.__setattr__(self, "structure_id", SpreadStructure.CURVE)

        # Build structure_kwargs from tenor
        skw = dict(self.structure_kwargs or {})
        if skw.get("fixed_rate") is None and skw.get("coupon") is not None:
            skw["fixed_rate"] = skw["coupon"]
        if skw.get("front_fixed_rate") is None and skw.get("front_coupon") is not None:
            skw["front_fixed_rate"] = skw["front_coupon"]
        if skw.get("back_fixed_rate") is None and skw.get("back_coupon") is not None:
            skw["back_fixed_rate"] = skw["back_coupon"]
        if skw.get("mid_fixed_rate") is None:
            if skw.get("belly_coupon") is not None:
                skw["mid_fixed_rate"] = skw["belly_coupon"]
            elif skw.get("mid_coupon") is not None:
                skw["mid_fixed_rate"] = skw["mid_coupon"]
        if self.tenor and "tenor" not in skw:
            skw["tenor"] = self.tenor
        if self.structure == SpreadStructure.CURVE and "/" in (self.tenor or ""):
            parts = [t.strip() for t in self.tenor.split("/")]
            if len(parts) == 2:
                skw.setdefault("front_tenor", parts[0])
                skw.setdefault("back_tenor", parts[1])
        elif self.structure == SpreadStructure.FLY and "/" in (self.tenor or ""):
            parts = [t.strip() for t in self.tenor.split("/")]
            if len(parts) == 3:
                skw.setdefault("front_tenor", parts[0])
                skw.setdefault("belly_tenor", parts[1])
                skw.setdefault("back_tenor", parts[2])
        object.__setattr__(self, "structure_kwargs", skw)

        # Build market_request
        mr = dict(self.market_request or {})
        if self.curve_a and "curve_a" not in mr:
            mr["curve_a"] = self.curve_a
        if self.curve_b and "curve_b" not in mr:
            mr["curve_b"] = self.curve_b
        if self.source_a:
            mr["source_a"] = self.source_a
        if self.source_b:
            mr["source_b"] = self.source_b
        object.__setattr__(self, "market_request", mr)

        # Sync value_id / value_ids
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["SpreadQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        prefix = f"{self.curve_a or ''} vs {self.curve_b or ''} " if self.curve_a else ""
        tenor_str = self.tenor or ""
        val_name = self.value.name if isinstance(self.value, SpreadValue) else "MULTI"
        return re.sub(r"\s\s+", " ", f"{prefix}{tenor_str} {val_name}").strip()

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def default_mtm_value_id(self) -> Any:
        return SpreadValue.SPREAD_BPS
