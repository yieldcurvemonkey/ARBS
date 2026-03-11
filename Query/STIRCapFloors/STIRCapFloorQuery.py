from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.IRSwaptions.utils import normalize_tenor, parse_expiry_tail_shorthandle
from Query.STIRCapFloors import adapter as _stircapfloor_adapter  # noqa: F401
from Query.STIRCapFloors.STIRCapFloorStructure import STIRCapFloorStructure
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue


def _explicit_mode(skw: Dict[str, Any]) -> bool:
    return skw.get("swap_start") is not None or skw.get("swap_end") is not None


def _request_date(now: dt.date | dt.datetime) -> dt.date:
    return now.date() if isinstance(now, dt.datetime) else now


def _request_datetime(now: dt.date | dt.datetime) -> dt.datetime:
    return now if isinstance(now, dt.datetime) else dt.datetime.combine(now, dt.time())


def _quarter_multiple_label(token: str, *, label: str) -> str:
    norm = normalize_tenor(token)
    if norm.endswith("Y"):
        months = int(norm[:-1]) * 12
    elif norm.endswith("M"):
        months = int(norm[:-1])
    else:
        raise ValueError(f"{label} must be a multiple of 3M or a whole number of years, got {token!r}")
    if months % 3 != 0:
        raise ValueError(f"{label} must be a multiple of 3M, got {token!r}")
    return norm


@dataclass(frozen=True)
class STIRCapFloorQuery(BaseQuery):
    structure: STIRCapFloorStructure = STIRCapFloorStructure.CAP
    value: Union[STIRCapFloorValue, List[STIRCapFloorValue]] = STIRCapFloorValue.PRICE

    curve: str = "USD-SOFR-1D"
    shorthand: Optional[str] = None
    expiry: Optional[str] = None
    tail: Optional[str] = None
    swap_start: Optional[dt.date] = None
    swap_end: Optional[dt.date] = None
    weight_method: str = "equal"
    strike_convention: str = "atm_per_caplet"
    contracts: float = 1.0

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="STIRCAPFLOOR")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "STIRCAPFLOOR")
        object.__setattr__(self, "structure_id", self.structure)

        expiry = self.expiry
        tail = self.tail
        if self.shorthand is not None:
            parsed_expiry, parsed_tail = parse_expiry_tail_shorthandle(self.shorthand)
            expiry = expiry or parsed_expiry
            tail = tail or parsed_tail

        if expiry is not None:
            expiry = _quarter_multiple_label(expiry, label="expiry")
            object.__setattr__(self, "expiry", expiry)
        if tail is not None:
            tail = _quarter_multiple_label(tail, label="tail")
            object.__setattr__(self, "tail", tail)

        skw = dict(self.structure_kwargs or {})
        if self.swap_start is not None and "swap_start" not in skw:
            skw["swap_start"] = self.swap_start
        if self.swap_end is not None and "swap_end" not in skw:
            skw["swap_end"] = self.swap_end
        if expiry is not None and "expiry" not in skw:
            skw["expiry"] = expiry
        if tail is not None and "tail" not in skw:
            skw["tail"] = tail
        skw.setdefault("weight_method", self.weight_method)
        skw.setdefault("strike_convention", self.strike_convention)
        skw.setdefault("contracts", float(self.contracts))

        if _explicit_mode(skw):
            if skw.get("swap_start") is None or skw.get("swap_end") is None:
                raise ValueError("Explicit synthetic cap/floor mode requires both swap_start and swap_end.")
        elif skw.get("expiry") is None or skw.get("tail") is None:
            raise ValueError("Synthetic cap/floor requires shorthand, expiry+tail, or swap_start+swap_end.")

        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        mr.setdefault("endpoint", "synthetic_capfloor_snapshot")
        mr.setdefault("curve_name", self.curve)
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["STIRCapFloorQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def _tenor_label(self) -> str:
        skw = self.structure_kwargs or {}
        if skw.get("expiry") and skw.get("tail"):
            return f"{skw['expiry']}x{skw['tail']}"
        if skw.get("swap_start") and skw.get("swap_end"):
            return f"{skw['swap_start']}/{skw['swap_end']}"
        return "UNKNOWN"

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        value_label = self.value.name if not isinstance(self.value, list) else "MULTI"
        text = (
            f"{self.curve} {self._tenor_label()} {self.structure.name} "
            f"{self.weight_method.upper()} {self.strike_convention.upper()} {value_label}"
        )
        return str(self.name) if self.name else " ".join(text.split())

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def build_mdp_request(self, now: dt.date | dt.datetime) -> Dict[str, Any]:
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = _request_date(now)
        elif req[self.mdp_time_key] == "now":
            req[self.mdp_time_key] = _request_datetime(now)

        req["structure"] = self.structure.name
        skw = self.structure_kwargs or {}
        for key in ("swap_start", "swap_end", "expiry", "tail", "weight_method", "strike_convention", "contracts"):
            if skw.get(key) is not None:
                req[key] = skw[key]
        req.setdefault("endpoint", "synthetic_capfloor_snapshot")
        req.setdefault("curve_name", self.curve)
        return req

    def default_mtm_value_id(self):
        return STIRCapFloorValue.PRICE
