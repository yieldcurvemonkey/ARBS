from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.FXForwards import adapter as _fxfwd_adapter  # noqa: F401
from Query.FXForwards.FXForwardStructure import FXForwardStructure
from Query.FXForwards.FXForwardValue import FXForwardValue


def _symbol_from_pair_tenor(pair: Optional[str], tenor: Optional[str]) -> Optional[str]:
    if pair is None:
        return None
    token = str(pair).strip().upper().replace("/", "")
    if tenor is None:
        return token
    return f"{token}:{str(tenor).strip().upper()}"


@dataclass(frozen=True)
class FXForwardQuery(BaseQuery):
    structure: FXForwardStructure = FXForwardStructure.OUTRIGHT
    value: Union[FXForwardValue, List[FXForwardValue]] = FXForwardValue.FORWARD_RATE

    pair: Optional[str] = None
    tenor: Optional[str] = None
    symbol: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="FXFORWARD")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "FXFORWARD")
        object.__setattr__(self, "structure_id", self.structure)

        skw = dict(self.structure_kwargs or {})
        if self.pair is not None and "pair" not in skw:
            skw["pair"] = str(self.pair).strip().upper().replace("/", "")
        if self.tenor is not None and "tenor" not in skw:
            skw["tenor"] = str(self.tenor).strip().upper()
        derived_symbol = self.symbol or _symbol_from_pair_tenor(self.pair, self.tenor)
        if derived_symbol is not None and "symbol" not in skw:
            skw["symbol"] = derived_symbol

        object.__setattr__(self, "structure_kwargs", skw)
        object.__setattr__(self, "market_request", dict(self.market_request or {}))

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["FXForwardQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        label = self.structure_kwargs.get("symbol") or self.symbol or _symbol_from_pair_tenor(self.pair, self.tenor) or "FXFWD"
        value_label = self.value.name if not isinstance(self.value, list) else "MULTI"
        return f"{label} {self.structure.name} {value_label}".strip()

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def build_mdp_request(self, now: datetime.datetime) -> Dict[str, Any]:
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        elif req[self.mdp_time_key] == "now":
            req[self.mdp_time_key] = now

        symbol = self.structure_kwargs.get("symbol")
        if symbol is None:
            raise ValueError("FXForwardQuery requires symbol or pair/tenor.")
        req["symbols"] = [str(symbol)]
        return req

    def default_mtm_value_id(self) -> Any:
        return FXForwardValue.FORWARD_RATE
