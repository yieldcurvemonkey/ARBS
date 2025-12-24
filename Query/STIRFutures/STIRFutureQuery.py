# STIRFutures/STIRFutureQuery.py

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue


def _norm_curve_name(s: Optional[str]) -> str:
    return (s or "").strip()


def _split_curve_symbols(symbol: Optional[str]) -> Optional[Tuple[str, str]]:
    """
    Allow light ergonomics for curve inputs:
      - "H26 v M26"
      - "H26/M26"
      - "H26-M26"  (careful: we only accept one delimiter)
    """
    if symbol is None:
        return None
    t = symbol.strip()
    if not t:
        return None

    # prefer explicit "v" first
    m = re.split(r"\s+v\s+|\s+V\s+", t)
    if len(m) == 2:
        return m[0].strip(), m[1].strip()

    # then / or -
    for delim in ["/", "-"]:
        if delim in t and t.count(delim) == 1:
            a, b = t.split(delim)
            return a.strip(), b.strip()

    return None


@dataclass(frozen=True)
class STIRFutureQuery(BaseQuery):
    """
    STIR Future query entry point.

    User-facing args:
      - structure: OUTRIGHT / CURVE / BASIS (SPREAD supported as alias if your enum maps it)
      - value: STIRFutureValue or list[STIRFutureValue]
      - symbol OR (effective_date & maturity_date)
      - curve: (single-curve) curve name used by the MDP/pricer
      - structure_kwargs:
          OUTRIGHT:
            - notional / bpv (defaults notional=1_000_000 if both omitted)
          CURVE:
            - front_symbol/back_symbol (or symbols=[...], or symbol="H26/M26")
            - optional risk_weights (defaults [1.0, -1.0])
          BASIS:
            - symbol (or effective/maturity)
            - front_curve/back_curve (curve identifiers; mapped into market_request)
      - risk_weight: scalar used by eval_expression and arithmetic sugar
    """

    structure: STIRFutureStructure = STIRFutureStructure.OUTRIGHT
    value: Union[STIRFutureValue, List[STIRFutureValue]] = STIRFutureValue.PRICE

    symbol: Optional[str] = None
    effective_date: Optional[datetime.date] = None
    maturity_date: Optional[datetime.date] = None
    is_ser: bool = False

    # default single-curve request (OUTRIGHT / CURVE)
    curve: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="STIRFUTURE")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "STIRFUTURE")
        object.__setattr__(self, "structure_id", self.structure)

        skw: Dict[str, Any] = dict(self.structure_kwargs or {})

        # ---- normalize common identifiers into structure_kwargs ----
        if self.symbol is not None and "symbol" not in skw:
            skw["symbol"] = self.symbol
        if self.effective_date is not None and "effective_date" not in skw:
            skw["effective_date"] = self.effective_date
        if self.maturity_date is not None and "maturity_date" not in skw:
            skw["maturity_date"] = self.maturity_date
        if self.is_ser or "SER" in self.symbol:
            skw.setdefault("is_ser", True)
            # if "SERFF" in self.symbol or "SR1ZQ" in self.symbol:
            #     self.structure = STIRFutureStructure.BASIS

        # ---- structure-specific normalization + validation ----
        if self.structure == STIRFutureStructure.OUTRIGHT:
            assert skw.get("symbol") is not None or (
                skw.get("effective_date") is not None and skw.get("maturity_date") is not None
            ), "OUTRIGHT requires symbol OR (effective_date & maturity_date)"
            # if "notional" not in skw and "bpv" not in skw:
            #     skw.setdefault("notional", 1_000_000)
            # Only default notional if *no* sizing was provided.
            if skw.get("contracts") is None and "notional" not in skw and "bpv" not in skw:
                skw.setdefault("notional", 1_000_000)

        elif self.structure in {getattr(STIRFutureStructure, "CURVE", STIRFutureStructure.SPREAD), STIRFutureStructure.SPREAD}:
            # accept symbols=[...] as a convenience
            symbols = skw.get("symbols")
            if isinstance(symbols, (list, tuple)) and len(symbols) >= 2:
                skw.setdefault("front_symbol", symbols[0])
                skw.setdefault("back_symbol", symbols[-1])

            # accept symbol="H26/M26" style if user supplied `symbol`
            if skw.get("front_symbol") is None or skw.get("back_symbol") is None:
                maybe = _split_curve_symbols(skw.get("symbol"))
                if maybe is not None:
                    skw.setdefault("front_symbol", maybe[0])
                    skw.setdefault("back_symbol", maybe[1])

            assert (skw.get("front_symbol") is not None and skw.get("back_symbol") is not None) or (
                skw.get("front_effective_date") is not None
                and skw.get("front_maturity_date") is not None
                and skw.get("back_effective_date") is not None
                and skw.get("back_maturity_date") is not None
            ), "CURVE/SPREAD requires front/back symbols OR full front/back date pairs"

            # default risk weights if absent
            if skw.get("risk_weights") is None:
                skw["risk_weights"] = [1.0, -1.0]

        elif getattr(STIRFutureStructure, "BASIS", None) is not None and self.structure == STIRFutureStructure.BASIS:
            # BASIS: same symbol, different curves (MDP/pricer must support this request shape)
            assert skw.get("symbol") is not None or (
                skw.get("effective_date") is not None and skw.get("maturity_date") is not None
            ), "BASIS requires symbol OR (effective_date & maturity_date)"
            assert skw.get("front_curve") is not None and skw.get("back_curve") is not None, "BASIS requires structure_kwargs['front_curve'] and ['back_curve']"

        object.__setattr__(self, "structure_kwargs", skw)

        # ---- market_request normalization ----
        mr = dict(self.market_request or {})

        # default single-curve behavior
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve

        # basis-specific curve routing (keeps backward compat with single curve_name)
        if getattr(STIRFutureStructure, "BASIS", None) is not None and self.structure == STIRFutureStructure.BASIS:
            fc = _norm_curve_name(skw.get("front_curve"))
            bc = _norm_curve_name(skw.get("back_curve"))
            if fc and "front_curve_name" not in mr:
                mr["front_curve_name"] = fc
            if bc and "back_curve_name" not in mr:
                mr["back_curve_name"] = bc

        object.__setattr__(self, "market_request", mr)

        # ---- value_id/value_ids ----
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["STIRFutureQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        curve_label = (cube_name or self.curve or "").strip()

        struct = self.structure.name
        val = self.value.name if not isinstance(self.value, list) else "MULTI"

        skw = self.structure_kwargs or {}

        if getattr(STIRFutureStructure, "BASIS", None) is not None and self.structure == STIRFutureStructure.BASIS:
            fc = _norm_curve_name(skw.get("front_curve"))
            bc = _norm_curve_name(skw.get("back_curve"))
            ten = (skw.get("symbol") or "").strip()
            base = f"{ten} BASIS {fc}~{bc} {val}".strip()
            return re.sub(r"\s\s+", " ", base)

        if self.structure == STIRFutureStructure.OUTRIGHT:
            ten = (skw.get("symbol") or "").strip()
            base = f"{curve_label} {ten} {struct} {val}".strip()
            return re.sub(r"\s\s+", " ", base)

        # CURVE/SPREAD
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

        # Build symbols list from tenor and structure_kwargs
        symbols = []
        # if self.tenor:
        #     symbols.append(self.tenor)

        skw = self.structure_kwargs or {}
        for key in ("front_tenor", "back_tenor", "belly_tenor", "symbol", "symbols", "tickers"):
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
        # return STIRFutureValue.NPV
        return STIRFutureValue.PRICE
