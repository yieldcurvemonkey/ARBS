import datetime

from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

_structure_kwargs_formatters: Dict[IRSwapStructure, Callable[[Optional[Dict]], str]] = {
    IRSwapStructure.OUTRIGHT: lambda kw: _format_struct_kwargs(IRSwapStructure.OUTRIGHT, kw),
    IRSwapStructure.CURVE: lambda kw: _format_struct_kwargs(IRSwapStructure.CURVE, kw),
    IRSwapStructure.FLY: lambda kw: _format_struct_kwargs(IRSwapStructure.FLY, kw),
}


def _format_struct_kwargs(ss: IRSwapStructure, kw: Dict):
    def _format_notional(value, dec_places=1, base=1_000_000, tag="mm"):
        if not value:
            return None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        short = num / base
        if short.is_integer():
            return f"{int(short)}{tag}"
        else:
            return f"{short:.{dec_places}f}{tag}"

    try:
        if ss == IRSwapStructure.OUTRIGHT:
            if "bpv" in kw:
                is_rec = "REC" if kw["bpv"] > 0 else "PAY"
                size = kw["bpv"]
                base, tag = 1000, "k/bp"
            elif "notional" in kw:
                is_rec = "REC" if kw["notional"] > 0 else "PAY"
                size = kw["notional"]
                base, tag = 1_000_000, "mm"

            if "fixed_rate" in kw and size and is_rec:
                return f"{is_rec} {_format_notional(size, base=base, tag=tag)} @ {kw["fixed_rate"] * 100:.3f}%"
            elif size and is_rec:
                return f"{is_rec} {_format_notional(size, base=base, tag=tag)}"

            raise ValueError(f"IRSwapStructure.OUTRIGHT kwargs incorrectly passed")

        # TODO format bpv and notional for structures
        tenor_delimiter = "x"
        if ss == IRSwapStructure.CURVE:
            if tenor_delimiter in kw["front_tenor"] and tenor_delimiter in kw["back_tenor"]:
                front_fwd, front_tenor = kw["front_tenor"].split(tenor_delimiter)
                back_fwd, back_tenor = kw["back_tenor"].split(tenor_delimiter)
                assert front_fwd == back_fwd, "MUST BE IN SAME FWD DIM"
                return f"{front_fwd}x{front_tenor}-{back_tenor}"

            return f"{kw["front_tenor"]}-{kw["back_tenor"]}"

        if ss == IRSwapStructure.FLY:
            if tenor_delimiter in kw["front_tenor"] and tenor_delimiter in kw["back_tenor"]:
                front_fwd, front_tenor = kw["front_tenor"].split(tenor_delimiter)
                belly_fwd, belly_tenor = kw["belly_tenor"].split("x")
                back_fwd, back_tenor = kw["back_tenor"].split(tenor_delimiter)
                assert front_fwd == belly_fwd == back_fwd, "MUST BE IN SAME FWD DIM"
                return f"{front_fwd}x{front_tenor}-{belly_tenor}-{back_tenor}"

            return f"{kw["front_tenor"]}-{kw["belly_tenor"]}-{kw["back_tenor"]}"

    except Exception as e:
        return ""


@dataclass
class IRSwapQuery(BaseQuery):
    tenor: Optional[str] = None
    effective_date: Optional[datetime.date] = None
    maturity_date: Optional[datetime.date] = None

    is_mms: Optional[bool] = False

    # trade_date: Optional[datetime] = None
    curve: Optional[str] = None
    # curve_handle: Optional[datetime] = None

    value: Union[IRSwapValue, List[IRSwapValue]] = IRSwapValue.RATE
    structure: IRSwapStructure = IRSwapStructure.OUTRIGHT
    structure_kwargs: Optional[Dict] = field(default_factory=dict)

    name: Optional[str] = None
    risk_weight: Optional[float] = None

    _curve_name: Optional[str] = None

    def __post_init__(self):
        if self.structure == IRSwapStructure.OUTRIGHT:
            assert (
                self.tenor or (self.effective_date and self.maturity_date) or self.is_mms
            ), "IRSwapQuery OUTRIGHT requires either tenor OR (effective_date AND maturity_date) OR Matched-Maturity (is_mss)"
        elif self.structure == IRSwapStructure.CURVE:
            assert ("front_tenor" in self.structure_kwargs and "back_tenor" in self.structure_kwargs) or (
                "front_effective_date" in self.structure_kwargs
                and "back_effective_date" in self.structure_kwargs
                and "front_maturity_date" in self.structure_kwargs
                and "back_maturity_date" in self.structure_kwargs
            ), "IRSwapQuery CURVE requires either both leg tenors OR both leg (effective_date AND maturity_date)s"

        # if self.trade_date:
        #     assert self.tenor, "'tenor' expected for 'trade_date'"
        #     assert self.curve and self.curve_handle, "'curve' and 'curve_handle' expected for 'trade_date'"
        #     assert self.structure == IRSwapStructure.OUTRIGHT, "'trade_date' supports only 'OUTRIGHT's"
        #     pkg, _ = IRSwapStructureFunctionMap(curve=self.curve, curve_handle=self.curve_handle).apply(
        #         structure=self.structure, tenor=self.tenor, **self.structure_kwargs
        #     )
        #     pkg: ql.FixedVsFloatingSwap = pkg[0]

        #     self.tenor = None
        #     self.trade_date = None
        #     self.curve = None
        #     self.curve_handle = None

        #     self.effective_date = ql_date_to_datetime(pkg.startDate())
        #     self.maturity_date = ql_date_to_datetime(pkg.maturityDate())
        #     if "fixed_rate" not in self.structure_kwargs:
        #         self.structure_kwargs = self.structure_kwargs | {"fixed_rate": pkg.fairRate() * 100}

    def return_query(self) -> List["IRSwapQuery"]:
        if isinstance(self.value, list):
            out: List[IRSwapQuery] = []
            for v in self.value:
                out.append(
                    IRSwapQuery(
                        tenor=self.tenor,
                        effective_date=self.effective_date,
                        maturity_date=self.maturity_date,
                        value=v,
                        structure=self.structure,
                        structure_kwargs=self.structure_kwargs,
                        name=self.name,
                        risk_weight=self.risk_weight,
                    )
                )
            return out
        return [self]

    def col_name(self, curve_name: Optional[str] = None) -> str:
        if curve_name:
            self._curve_name = curve_name

        if self._curve_name is None:
            self._curve_name = self.curve

        if self.tenor:
            swap_name = str(self.tenor)
        elif self.effective_date and self.maturity_date:
            swap_name = f"{self.effective_date.date()}/{self.maturity_date.date()}"
        elif self.is_mms and self.maturity_date:
            swap_name = f"MMS {self.maturity_date.date()}"
        else:
            swap_name = None

        fmt = _structure_kwargs_formatters[self.structure](self.structure_kwargs)

        if self.name:
            return self.name
        prefix = f"{curve_name} " if curve_name else f"{self._curve_name} " if self._curve_name else ""
        if fmt:
            return f"{prefix}{swap_name} {fmt} {self.structure.name} {self.value.name}" if swap_name else f"{prefix} {fmt} {self.structure.name} {self.value.name}"
        return f"{prefix}{swap_name} {self.structure.name} {self.value.name}" if swap_name else f"{prefix} {self.structure.name} {self.value.name}"

    def eval_expression(self, curve_name: Optional[str] = None, ignore_risk_weight: bool = False) -> str:
        col = self.col_name(curve_name=curve_name)
        if self.risk_weight is not None and not ignore_risk_weight:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def __pos__(self) -> "IRSwapQuery":
        assert not isinstance(self.value, list)
        return self

    def __neg__(self) -> "IRSwapQuery":
        assert not isinstance(self.value, list)
        new_weight = -(self.risk_weight or 1.0)
        return replace(self, risk_weight=new_weight)

    def __add__(self, other: object) -> List["IRSwapQuery"]:
        # self + other
        if isinstance(other, IRSwapQuery):
            return [self * 1, other * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [self * 1] + [q * 1 for q in other]
        return NotImplemented

    def __radd__(self, other: object) -> List["IRSwapQuery"]:
        # other + self
        if isinstance(other, IRSwapQuery):
            return [other * 1, self * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [q * 1 for q in other] + [self * 1]
        return NotImplemented

    def __sub__(self, other: object) -> List["IRSwapQuery"]:
        # self - other
        if isinstance(other, IRSwapQuery):
            return [self * 1, other * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [self * 1] + [q * -1 for q in other]
        return NotImplemented

    def __rsub__(self, other: object) -> List["IRSwapQuery"]:
        # other - self
        if isinstance(other, IRSwapQuery):
            return [other * 1, self * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwapQuery) for q in other):
            return [q * 1 for q in other] + [self * -1]
        return NotImplemented

    def __mul__(self, scalar: object) -> "IRSwapQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        new_weight = (self.risk_weight or 1.0) * scalar
        return replace(self, risk_weight=new_weight)

    def __rmul__(self, scalar: object) -> "IRSwapQuery":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> "IRSwapQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return self * (1.0 / scalar)

    def __rtruediv__(self, scalar: object) -> List["IRSwapQuery"]:
        return NotImplemented


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
