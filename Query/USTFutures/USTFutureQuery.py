from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from definitions.USTFutures import normalize_root
from Query.Base.BaseQuery import BaseQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue


def _norm_curve_name(s: Optional[str]) -> str:
    return (s or "").strip()


def _split_curve_symbols(symbol: Optional[str]) -> Optional[Tuple[str, str]]:
    if symbol is None:
        return None
    t = symbol.strip()
    if not t:
        return None
    m = re.split(r"\s+v\s+|\s+V\s+", t)
    if len(m) == 2:
        return m[0].strip(), m[1].strip()
    for delim in ["/", "-"]:
        if delim in t and t.count(delim) == 1:
            a, b = t.split(delim)
            return a.strip(), b.strip()
    return None


def _resolve_symbol_from_tenor_contract(tenor: Optional[str], contract: Optional[str]) -> Optional[str]:
    if tenor is None or contract is None:
        return None
    root = normalize_root(tenor)
    return f"{root}{contract.strip().upper()}"


@dataclass(frozen=True)
class USTFutureQuery(BaseQuery):
    structure: USTFutureStructure = USTFutureStructure.OUTRIGHT
    value: Union[USTFutureValue, List[USTFutureValue]] = USTFutureValue.PRICE

    tenor: Optional[str] = None
    contract: Optional[str] = None
    symbol: Optional[str] = None

    curve: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="USTFUTURE")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "USTFUTURE")
        object.__setattr__(self, "structure_id", self.structure)

        skw: Dict[str, Any] = dict(self.structure_kwargs or {})

        inferred_symbol = _resolve_symbol_from_tenor_contract(self.tenor, self.contract)
        if inferred_symbol is not None and "symbol" not in skw and self.symbol is None:
            skw["symbol"] = inferred_symbol

        if self.symbol is not None and "symbol" not in skw:
            skw["symbol"] = self.symbol

        if self.structure == USTFutureStructure.OUTRIGHT and "/" not in (skw.get("symbol") or ""):
            assert skw.get("symbol") is not None, "OUTRIGHT requires symbol"
            if skw.get("contracts") is None and "notional" not in skw:
                skw.setdefault("contracts", 1)

        elif "/" in (skw.get("symbol") or "") or self.structure in {USTFutureStructure.CURVE, USTFutureStructure.SPREAD}:
            symbols = skw.get("symbols")
            if isinstance(symbols, (list, tuple)) and len(symbols) >= 2:
                skw.setdefault("front_symbol", symbols[0])
                skw.setdefault("back_symbol", symbols[-1])

            if skw.get("front_symbol") is None or skw.get("back_symbol") is None:
                maybe = _split_curve_symbols(skw.get("symbol"))
                if maybe is not None:
                    skw.setdefault("front_symbol", maybe[0])
                    skw.setdefault("back_symbol", maybe[1])

            assert skw.get("front_symbol") is not None and skw.get("back_symbol") is not None, "CURVE/SPREAD requires front/back symbols"
            if skw.get("risk_weights") is None:
                skw["risk_weights"] = [1.0, -1.0]

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

        symbol_str = self.structure_kwargs.get("symbol") or self.symbol or ""
        slash_count = symbol_str.count("/")
        if slash_count == 1:
            object.__setattr__(self, "structure", USTFutureStructure.CURVE)
            object.__setattr__(self, "structure_id", USTFutureStructure.CURVE)
        elif slash_count == 2:
            object.__setattr__(self, "structure", USTFutureStructure.FLY)
            object.__setattr__(self, "structure_id", USTFutureStructure.FLY)

    def return_query(self) -> List["USTFutureQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        curve_label = (cube_name or self.curve or "").strip()
        struct = self.structure.name
        val = self.value.name if not isinstance(self.value, list) else "MULTI"
        skw = self.structure_kwargs or {}

        if self.structure == USTFutureStructure.OUTRIGHT:
            sym = (skw.get("symbol") or "").strip()
            base = f"{curve_label} {sym} {struct} {val}".strip()
            return re.sub(r"\s\s+", " ", base)

        ft = (skw.get("front_symbol") or "").strip()
        bt = (skw.get("back_symbol") or "").strip()
        rws = skw.get("risk_weights") or []
        rw_str = "/".join(str(x) for x in rws) if rws else ""
        base = f"{curve_label} {ft}v{bt} {struct} {val} {rw_str}".strip()
        return re.sub(r"\s\s+", " ", base)

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

    def build_mdp_request(self, now: datetime.datetime) -> Dict[str, Any]:
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = now

        symbols = []
        skw = self.structure_kwargs or {}
        for key in ("front_symbol", "back_symbol", "belly_symbol", "symbol", "symbols", "tickers"):
            val = skw.get(key)
            if val:
                if isinstance(val, (list, tuple)):
                    symbols.extend(val)
                else:
                    symbols.append(val)
        if symbols:
            req["symbols"] = symbols
        return req

    def default_mtm_value_id(self):
        return USTFutureValue.PRICE
