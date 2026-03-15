from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union
from Query.Base.BaseQuery import BaseQuery
from Query.EventContracts.EventContractStructure import EventContractStructure
from Query.EventContracts.EventContractValue import EventContractValue
from Query.EventContracts import adapter as _ec_adapter  # noqa: F401


@dataclass(frozen=True)
class EventContractQuery(BaseQuery):
    structure: EventContractStructure = EventContractStructure.OUTRIGHT
    value: Union[EventContractValue, List[EventContractValue]] = EventContractValue.PRICE
    ticker: Optional[str] = None
    market_id: Optional[str] = None
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None
    product: str = field(init=False, default="EVENT")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "EVENT")
        object.__setattr__(self, "structure_id", self.structure)
        mr = dict(self.market_request or {})
        if self.ticker and "ticker" not in mr:
            mr["ticker"] = self.ticker
        if self.market_id and "market_id" not in mr:
            mr["market_id"] = self.market_id
        object.__setattr__(self, "market_request", mr)
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["EventContractQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        label = self.ticker or self.market_id or "EVENT"
        val_name = self.value.name if isinstance(self.value, EventContractValue) else "MULTI"
        return f"{label} {val_name}"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def default_mtm_value_id(self) -> Any:
        return EventContractValue.PRICE
