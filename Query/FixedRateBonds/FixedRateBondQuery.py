import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue


@dataclass(frozen=True)
class FixedRateBondQuery(BaseQuery):
    structure: FixedRateBondStructure = FixedRateBondStructure.OUTRIGHT
    value: Union[FixedRateBondValue, List[FixedRateBondValue]] = FixedRateBondValue.YTM

    cusip: Optional[str] = None
    curve: Optional[str] = None  # Maps to the MDP source

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="FRB")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        skw = dict(self.structure_kwargs or {})
        if self.cusip is not None and "cusip" not in skw:
            skw["cusip"] = self.cusip

        object.__setattr__(self, "product", "FRB")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["FixedRateBondQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        curve_label = cube_name or self.curve or ""
        struct_name = self.structure.name
        val_name = self.value.name
        rws = "/".join([str(rw) for rw in self.structure_kwargs.get("risk_weights", [])])

        cusip_str = self.structure_kwargs.get("cusip", "")
        if self.structure == FixedRateBondStructure.CURVE and self.structure_kwargs.get("front_cusip") is not None:
            cusip_str = f"{self.structure_kwargs.get('front_cusip')}v{self.structure_kwargs.get('back_cusip')}"
        elif self.structure == FixedRateBondStructure.FLY and self.structure_kwargs.get("front_cusip") is not None:
            cusip_str = f"{self.structure_kwargs.get('front_cusip')}v{self.structure_kwargs.get('belly_cusip')}v{self.structure_kwargs.get('back_cusip')}"

        if cusip_str.count("/") == 1:
            struct_name = FixedRateBondStructure.CURVE.name
        elif cusip_str.count("/") == 2:
            struct_name = FixedRateBondStructure.FLY.name

        if curve_label.strip() == cusip_str.strip():
            return re.sub(r'\s\s+', " ", f"{cusip_str} {struct_name} {val_name}".strip())

        if rws not in ["1/-1", "0.5/-0.5", "0.50/-0.50", "-1/2/-1", "-0.50/1.00/-0.50", "-0.5/1/-0.5"]:
            return re.sub(r'\s\s+', " ", f"{curve_label} {cusip_str} {rws} {struct_name} {val_name}".strip())

        return re.sub(r'\s\s+', " ", f"{curve_label} {cusip_str} {struct_name} {val_name}".strip())

    def eval_expression(self, cube_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None and not ignore_risk_weight:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    # --- Arithmetic ---
    def __pos__(self) -> "FixedRateBondQuery":
        return self

    def __neg__(self) -> "FixedRateBondQuery":
        return replace(self, risk_weight=-(self.risk_weight or 1.0))

    def __mul__(self, scalar: object) -> "FixedRateBondQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return replace(self, risk_weight=(self.risk_weight or 1.0) * float(scalar))

    def __rmul__(self, scalar: object) -> "FixedRateBondQuery":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> "FixedRateBondQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return self * (1.0 / float(scalar))

    def build_mdp_request(self, now) -> Dict[str, Any]:
        """
        Build the request dict for MDP.get_pricer(request) at time 'now'.
        Policy:
          - If mdp_time_key missing -> inject 'now.date()'
          - If mdp_time_key == "live" or already set -> pass through unchanged
          - If mdp_time_key == "now" -> inject full datetime
        """
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = now
            # "live" or concrete value: leave as-is
        
        req["cusips"] = [self.cusip]
        return req
    
    def default_mtm_value_id(self) -> Any:
        return FixedRateBondValue.NPV