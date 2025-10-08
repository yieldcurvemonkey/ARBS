# Query/IRSwaps/IRSwapQuery.py
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from Query.Base.BaseQuery import BaseQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

from utils.misc import human_format


def _format_struct_kwargs(ss: IRSwapStructure, kw: Dict[str, Any]) -> str:
    def _format_size(value: Any, *, base: float, tag: str, dec_places: int = 1) -> Optional[str]:
        if value is None:
            return None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        short = num / base
        if float(short).is_integer():
            return f"{int(short)}{tag}"
        return f"{short:.{dec_places}f}{tag}"

    try:
        if ss == IRSwapStructure.OUTRIGHT:
            side = None
            size_str = None

            if "bpv" in kw and kw["bpv"] is not None:
                side = "REC" if float(kw["bpv"]) > 0 else "PAY"
                size_str = _format_size(kw["bpv"], base=1_000.0, tag="k/bp", dec_places=1)
            elif "notional" in kw and kw["notional"] is not None:
                side = "REC" if float(kw["notional"]) > 0 else "PAY"
                size_str = _format_size(kw["notional"], base=1_000_000.0, tag="mm", dec_places=1)

            rate_str = None
            if "fixed_rate" in kw and kw["fixed_rate"] is not None:
                try:
                    rate_str = f"@ {float(kw['fixed_rate']) * 100.0:.3f}%"
                except Exception:
                    rate_str = f"@ {kw['fixed_rate']}"

            if side and size_str and rate_str:
                return f"{side} {size_str} {rate_str}"
            if side and size_str:
                return f"{side} {size_str}"
            return ""  # outright but no size/rate formatting fields

        # CURVE/FLY: prefer concise tenor strings, support fwdxTenor like "3x10Y"
        tenor_delim = "x"

        if ss == IRSwapStructure.CURVE:
            ft = kw.get("front_tenor")
            bt = kw.get("back_tenor")
            if ft is None or bt is None:
                return ""
            if tenor_delim in str(ft) and tenor_delim in str(bt):
                f_fwd, f_tenor = str(ft).split(tenor_delim)
                b_fwd, b_tenor = str(bt).split(tenor_delim)
                if f_fwd == b_fwd:
                    return f"{f_fwd}x{f_tenor}-{b_tenor}"
            return f"{ft}-{bt}"

        if ss == IRSwapStructure.FLY:
            lt = kw.get("front_tenor")
            ct = kw.get("belly_tenor")
            rt = kw.get("back_tenor")
            if lt is None or ct is None or rt is None:
                return ""
            if tenor_delim in str(lt) and tenor_delim in str(ct) and tenor_delim in str(rt):
                l_fwd, l_tenor = str(lt).split(tenor_delim)
                c_fwd, c_tenor = str(ct).split(tenor_delim)
                r_fwd, r_tenor = str(rt).split(tenor_delim)
                if l_fwd == c_fwd == r_fwd:
                    return f"{l_fwd}x{l_tenor}-{c_tenor}-{r_tenor}"
            return f"{lt}-{ct}-{rt}"

    except Exception:
        return ""

    return ""


_structure_kwargs_formatters: Dict[IRSwapStructure, Callable[[Dict[str, Any]], str]] = {
    IRSwapStructure.OUTRIGHT: lambda kw: _format_struct_kwargs(IRSwapStructure.OUTRIGHT, kw),
    IRSwapStructure.CURVE: lambda kw: _format_struct_kwargs(IRSwapStructure.CURVE, kw),
    IRSwapStructure.FLY: lambda kw: _format_struct_kwargs(IRSwapStructure.FLY, kw),
}


# -------------------------------- IRSwapQuery --------------------------------


@dataclass(frozen=True)
class IRSwapQuery(BaseQuery):
    """
    IRS-specific Query entry point.

    User-facing args:
      - structure: outright/curve/fly
      - value:     report label helper (RATE, NPV, PV01, DV01, NOTIONAL, etc.)
      - tenor OR (effective_date & maturity_date) OR is_mms=True
      - curve:     the curve name (used to build market_request for the MDP)
      - structure_kwargs: product params (bpv / notional / pay_fixed / fixed_rate / leg tenors, etc.)
      - risk_weight: scalar for convenience when combining queries arithmetically

    This subclass auto-fills BaseQuery fields:
      product="IRS"
      structure_id = structure
      structure_kwargs = normalized union of user kwargs + tenor/dates flags
      market_request = {'curve_name': curve, ...}
      value_id / value_ids derived from `value` if you use those downstream
    """

    # ---- IRS-specific, user-facing fields ----
    structure: IRSwapStructure = IRSwapStructure.OUTRIGHT
    value: Union[IRSwapValue, List[IRSwapValue]] = IRSwapValue.RATE

    tenor: Optional[str] = None
    effective_date: Optional[datetime.date] = None
    maturity_date: Optional[datetime.date] = None
    is_mms: bool = False

    curve: Optional[str] = None  # becomes market_request['curve_name']

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None
    _curve_name: Optional[str] = None

    product: str = field(init=False, default="IRS")
    structure_id: Any = field(init=False, default=None)

    # ---- initialization: normalize and populate BaseQuery fields ----
    def __post_init__(self):
        object.__setattr__(self, "product", "IRS")
        object.__setattr__(self, "structure_id", self.structure)

        # Basic validation by structure
        if self.structure == IRSwapStructure.OUTRIGHT:
            assert (
                self.tenor or (self.effective_date and self.maturity_date) or self.is_mms
            ), "OUTRIGHT requires tenor OR (effective_date & maturity_date) OR is_mms=True"
        elif self.structure == IRSwapStructure.CURVE:
            assert ("front_tenor" in self.structure_kwargs and "back_tenor" in self.structure_kwargs) or (
                "front_effective_date" in self.structure_kwargs
                and "front_maturity_date" in self.structure_kwargs
                and "back_effective_date" in self.structure_kwargs
                and "back_maturity_date" in self.structure_kwargs
            ), "CURVE requires both leg tenors OR both leg (effective_date & maturity_date)"
        elif self.structure == IRSwapStructure.FLY:
            assert ("front_tenor" in self.structure_kwargs and "belly_tenor" in self.structure_kwargs and "back_tenor" in self.structure_kwargs) or (
                "front_effective_date" in self.structure_kwargs
                and "front_maturity_date" in self.structure_kwargs
                and "belly_effective_date" in self.structure_kwargs
                and "belly_maturity_date" in self.structure_kwargs
                and "back_effective_date" in self.structure_kwargs
                and "back_maturity_date" in self.structure_kwargs
            ), "FLY requires all three leg tenors OR (effective_date & maturity_date) for each leg"

        # Build normalized structure kwargs (merge tenor/dates/is_mms flags)
        skw: Dict[str, Any] = dict(self.structure_kwargs or {})
        if self.tenor is not None and "tenor" not in skw:
            skw["tenor"] = self.tenor
        if self.effective_date is not None and "effective_date" not in skw:
            skw["effective_date"] = self.effective_date
        if self.maturity_date is not None and "maturity_date" not in skw:
            skw["maturity_date"] = self.maturity_date
        if self.is_mms and "is_mms" not in skw:
            skw["is_mms"] = True

        # Auto-populate BaseQuery fields (frozen dataclass -> use object.__setattr__)
        object.__setattr__(self, "product", "IRS")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)

        # Build default market_request from curve if not supplied at construction
        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        # Keep BaseQuery's value_id/value_ids in sync (optional, for downstream)
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

        if self.tenor is not None and type(self.tenor) == str:
            if "ct" in self.tenor or "9128" in self.tenor:
                skw["is_mms"] = True

    # ---- BaseQuery abstract hooks adapted to IRS ----

    def return_query(self) -> List["IRSwapQuery"]:
        """Expand a list-valued `value` into separate queries; otherwise, return [self]."""
        if isinstance(self.value, list):
            out: List[IRSwapQuery] = []
            for v in self.value:
                # Rebuild a new query so __post_init__ syncs BaseQuery fields
                q = IRSwapQuery(
                    structure=self.structure,
                    value=v,
                    tenor=self.tenor,
                    effective_date=self.effective_date,
                    maturity_date=self.maturity_date,
                    is_mms=self.is_mms,
                    curve=self.curve,
                    structure_kwargs=self.structure_kwargs,
                    risk_weight=self.risk_weight,
                    name=self.name,  # inherited from BaseQuery
                    tags=self.tags,  # inherited from BaseQuery
                    meta=self.meta,  # inherited from BaseQuery
                    market_request=self.market_request,
                    mdp_time_key=self.mdp_time_key,
                )
                out.append(q)
            return out
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        """Human-friendly label for dataframes/plots."""
        if cube_name:
            object.__setattr__(self, "_curve_name", cube_name)

        curve_label = self._curve_name if self._curve_name is not None else self.curve
        if self.tenor:
            swap_name = str(self.tenor)
        elif self.effective_date and self.maturity_date:
            swap_name = f"{self.effective_date}/{self.maturity_date}"
        elif self.is_mms and self.maturity_date:
            swap_name = f"MMS {self.maturity_date}"
        else:
            swap_name = None

        fmt = _structure_kwargs_formatters[self.structure](self.structure_kwargs or {})

        prefix = f"{curve_label} " if curve_label else ""
        suffix = f"{self.structure.name} {self.value.name if isinstance(self.value, IRSwapValue) else 'MULTI'}"
        to_return = f"{prefix}{suffix}"

        if self.name:
            to_return = self.name
        if fmt and swap_name:
            to_return = f"{prefix}{swap_name} {fmt} {suffix}"
        if fmt:
            to_return = f"{prefix}{fmt} {suffix}"
        if swap_name:
            to_return = f"{prefix}{swap_name} {suffix}"
        if "bpv" in self.structure_kwargs and self.structure_kwargs["bpv"] > 1:
            human_format_risk = human_format(abs(self.structure_kwargs["bpv"]))
            verb = f"Paid {human_format_risk}" if self.structure_kwargs["bpv"] < 0 else f"Rec {human_format_risk}"
            to_return = f"{verb} {prefix}{suffix}"

        return to_return

    def eval_expression(self, cube_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        col = self.col_name(cube_name=cube_name)
        if (self.risk_weight is not None) and (not ignore_risk_weight):
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    # ---- arithmetic sugar (keeps IRSwapQuery type) ----

    def __pos__(self) -> "IRSwapQuery":
        assert not isinstance(self.value, list)
        return self

    def __neg__(self) -> "IRSwapQuery":
        assert not isinstance(self.value, list)
        new_weight = -(self.risk_weight or 1.0)
        return replace(self, risk_weight=new_weight)

    def __add__(self, other: object) -> List["IRSwapQuery"]:
        if isinstance(other, IRSwapQuery):
            return [self * 1, other * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [self * 1] + [q * 1 for q in other]
        return NotImplemented  # type: ignore[return-value]

    def __radd__(self, other: object) -> List["IRSwapQuery"]:
        if isinstance(other, IRSwapQuery):
            return [other * 1, self * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [q * 1 for q in other] + [self * 1]
        return NotImplemented  # type: ignore[return-value]

    def __sub__(self, other: object) -> List["IRSwapQuery"]:
        if isinstance(other, IRSwapQuery):
            return [self * 1, other * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [self * 1] + [q * -1 for q in other]
        return NotImplemented  # type: ignore[return-value]

    def __rsub__(self, other: object) -> List["IRSwapQuery"]:
        if isinstance(other, IRSwapQuery):
            return [other * 1, self * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [q * 1 for q in other] + [self * -1]
        return NotImplemented  # type: ignore[return-value]

    def __mul__(self, scalar: object) -> "IRSwapQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented  # type: ignore[return-value]
        new_weight = (self.risk_weight or 1.0) * float(scalar)
        return replace(self, risk_weight=new_weight)

    def __rmul__(self, scalar: object) -> "IRSwapQuery":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> "IRSwapQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented  # type: ignore[return-value]
        return self * (1.0 / float(scalar))

    def __rtruediv__(self, scalar: object) -> List["IRSwapQuery"]:
        return NotImplemented  # type: ignore[return-value]


@dataclass
class IRSwapQueryWrapper:
    queries: List[IRSwapQuery]
    name: str
    ignore_risk_weights: bool = True

    def __init__(self, queries: Union[IRSwapQuery, List[IRSwapQuery]], name: str):
        self.queries = [queries] if isinstance(queries, IRSwapQuery) else queries
        self.name = name

    def return_query(self) -> List[IRSwapQuery]:
        return self.queries

    def col_name(self, curve_name: Optional[str] = None) -> str:
        return self.name

    def eval_expression(self, curve_name: Optional[str] = None) -> str:
        parts = []
        for q in self.queries:
            rw = q.risk_weight or 1.0
            parts.append(f"{rw} * `{q.col_name(curve_name)}`")
        return " + ".join(parts)
