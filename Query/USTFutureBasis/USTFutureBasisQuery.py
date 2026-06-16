from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.USTFutureBasis import adapter as _ustfb_adapter  # noqa: F401  (registers product + handler)
from Query.USTFutureBasis.USTFutureBasisStructure import USTFutureBasisStructure
from Query.USTFutureBasis.USTFutureBasisValue import USTFutureBasisValue


@dataclass(frozen=True)
class USTFutureBasisQuery(BaseQuery):
    """A Treasury-futures basis position: a cash bond (CTD by default) vs CF-weighted futures.

    direction = +1 -> LONG the basis  (buy cash / sell futures = cash-and-carry)
    direction = -1 -> SHORT the basis (sell cash / buy futures)
    """

    structure: USTFutureBasisStructure = USTFutureBasisStructure.BASIS
    value: Union[USTFutureBasisValue, List[USTFutureBasisValue]] = USTFutureBasisValue.NET_BASIS

    symbol: Optional[str] = None        # future symbol, e.g. "TYZ5"
    bond_cusip: Optional[str] = None    # explicit cash leg; None -> CTD
    direction: int = 1
    repo_rate: Optional[float] = None   # percent; None -> SOFR/GC fixing
    bond_notional: Optional[float] = None  # cash face; futures CF-weighted to it
    contracts: Optional[int] = None
    curve: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="USTFUTUREBASIS")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "product", "USTFUTUREBASIS")
        object.__setattr__(self, "structure_id", self.structure)

        skw: Dict[str, Any] = dict(self.structure_kwargs or {})
        if self.symbol is not None:
            skw.setdefault("symbol", self.symbol)
        if self.bond_cusip is not None:
            skw.setdefault("bond_cusip", self.bond_cusip)
        skw.setdefault("direction", int(self.direction))
        if self.repo_rate is not None:
            skw.setdefault("repo_rate", self.repo_rate)
        if self.bond_notional is not None:
            skw.setdefault("bond_notional", self.bond_notional)
        if self.contracts is not None:
            skw.setdefault("contracts", self.contracts)
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        mr["include_basket"] = True
        if self.curve is not None and "curve_id" not in mr:
            mr["curve_id"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def build_mdp_request(self, now: Any) -> Dict[str, Any]:
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date() if isinstance(now, datetime.datetime) else now
        req["include_basket"] = True
        sym = self.structure_kwargs.get("symbol") or self.symbol
        if sym:
            req["symbols"] = [sym]
        return req

    def return_query(self) -> List["USTFutureBasisQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        sym = self.structure_kwargs.get("symbol", self.symbol or "")
        bond = self.structure_kwargs.get("bond_cusip", "CTD")
        side = "LONG" if int(self.direction) >= 0 else "SHORT"
        val = self.value.name if not isinstance(self.value, list) else "MULTI"
        base = f"{sym} {bond} {side}_BASIS {val}".strip()
        return re.sub(r"\s\s+", " ", base)

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def default_mtm_value_id(self) -> Any:
        if isinstance(self.value, list):
            return self.value[0]
        return self.value

    def __neg__(self) -> "USTFutureBasisQuery":
        new_weight = -(self.risk_weight or 1.0)
        return replace(self, risk_weight=new_weight)

    def __mul__(self, scalar: object) -> "USTFutureBasisQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        new_weight = (self.risk_weight or 1.0) * float(scalar)
        return replace(self, risk_weight=new_weight)

    def __rmul__(self, scalar: object) -> "USTFutureBasisQuery":
        return self.__mul__(scalar)
