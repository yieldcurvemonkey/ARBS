from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional

from Query.Base.BaseQuery import BaseQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue


@dataclass(frozen=True)
class STIRFutureQuery(BaseQuery):
    structure: STIRFutureStructure = STIRFutureStructure.OUTRIGHT
    value: Optional[STIRFutureValue] = STIRFutureValue.NPV

    tenor: Optional[str] = None
    effective_date: Optional[datetime.date] = None
    maturity_date: Optional[datetime.date] = None
    is_ser: bool = False

    curve: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="STIRFUTURE")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "STIRFUTURE")
        object.__setattr__(self, "structure_id", self.structure)

        skw = dict(self.structure_kwargs or {})
        if self.tenor is not None:
            skw.setdefault("tenor", self.tenor)
        if self.effective_date is not None:
            skw.setdefault("effective_date", self.effective_date)
        if self.maturity_date is not None:
            skw.setdefault("maturity_date", self.maturity_date)
        if self.is_ser:
            skw.setdefault("is_ser", True)

        if self.structure == STIRFutureStructure.OUTRIGHT and "notional" not in skw and "bpv" not in skw:
            skw.setdefault("notional", 1_000_000)

        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if self.value is not None:
            object.__setattr__(self, "value_id", self.value)
        object.__setattr__(self, "value_ids", tuple())

    def return_query(self):
        return self

    def col_name(self, cube_name: Optional[str] = None) -> str:
        return f"stirf_{self.tenor or self.structure.name.lower()}"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return col

    def __neg__(self):
        new_weight = -(self.risk_weight or 1.0)
        return replace(self, risk_weight=new_weight)

    def __mul__(self, scalar: object):
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        new_weight = (self.risk_weight or 1.0) * float(scalar)
        return replace(self, risk_weight=new_weight)

    def __rmul__(self, scalar: object):
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object):
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return self * (1.0 / scalar)

    def __rtruediv__(self, scalar: object):
        return NotImplemented
