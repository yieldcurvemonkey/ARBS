from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.IRSwaptions import adapter as _irswp_adapter  # noqa: F401
from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from Query.IRSwaptions.pricer import IRSwaptionPricable, leg_forward_rate, leg_model_vol, leg_tte_years
from Query.IRSwaptions.utils import (
    infer_option_type_from_strike_spec,
    normalize_tenor,
    parse_expiry_tail_shorthandle,
    parse_midcurve_tail,
    resolve_strike_spec,
    to_date,
)


def _is_explicit_date_mode(skw: Dict[str, Any]) -> bool:
    return all(
        skw.get(k) is not None
        for k in ("exercise_date", "underlying_effective_date", "underlying_maturity_date")
    )


def _normalize_tail_label(tail: str) -> str:
    fwd, tenor = parse_midcurve_tail(tail)
    if fwd is None:
        return tenor
    return f"{fwd}x{tenor}"


def _infer_outright_structure(
    structure: IRSwaptionStructure,
    strike_spec: float | str | None,
) -> IRSwaptionStructure:
    if structure not in {IRSwaptionStructure.RECEIVER, IRSwaptionStructure.PAYER}:
        return structure
    inferred_option_type = infer_option_type_from_strike_spec(strike_spec)
    if inferred_option_type == "payer":
        return IRSwaptionStructure.PAYER
    if inferred_option_type == "receiver":
        return IRSwaptionStructure.RECEIVER
    return structure


@dataclass(frozen=True)
class IRSwaptionQuery(BaseQuery):
    structure: IRSwaptionStructure = IRSwaptionStructure.RECEIVER
    value: Union[IRSwaptionValue, List[IRSwaptionValue]] = IRSwaptionValue.NVOL

    curve: Optional[str] = None
    shorthand: Optional[str] = None
    expiry: Optional[str] = None
    tail: Optional[str] = None
    exercise_date: Optional[dt.date] = None
    underlying_effective_date: Optional[dt.date] = None
    underlying_maturity_date: Optional[dt.date] = None
    strike: Union[float, str, None] = "ATMF"
    side: str = "buy"
    trade_date: Optional[dt.date] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None
    _curve_name: Optional[str] = None

    product: str = field(init=False, default="IRSWAPTION")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "IRSWAPTION")

        expiry = self.expiry
        tail = self.tail
        if self.shorthand is not None:
            parsed_expiry, parsed_tail = parse_expiry_tail_shorthandle(self.shorthand)
            if expiry is not None and normalize_tenor(expiry) != parsed_expiry:
                raise ValueError(
                    f"shorthand '{self.shorthand}' expiry '{parsed_expiry}' conflicts with explicit expiry '{expiry}'."
                )
            if tail is not None and _normalize_tail_label(tail) != parsed_tail:
                raise ValueError(
                    f"shorthand '{self.shorthand}' tail '{parsed_tail}' conflicts with explicit tail '{tail}'."
                )
            expiry = expiry or parsed_expiry
            tail = tail or parsed_tail

        if expiry is not None:
            expiry = normalize_tenor(expiry)
            object.__setattr__(self, "expiry", expiry)
        if tail is not None:
            tail = _normalize_tail_label(tail)
            object.__setattr__(self, "tail", tail)

        skw = dict(self.structure_kwargs or {})
        if expiry is not None and "expiry" not in skw:
            skw["expiry"] = expiry
        if tail is not None and "tail" not in skw:
            skw["tail"] = tail
        if self.exercise_date is not None and "exercise_date" not in skw:
            skw["exercise_date"] = self.exercise_date
        if self.underlying_effective_date is not None and "underlying_effective_date" not in skw:
            skw["underlying_effective_date"] = self.underlying_effective_date
        if self.underlying_maturity_date is not None and "underlying_maturity_date" not in skw:
            skw["underlying_maturity_date"] = self.underlying_maturity_date
        if self.strike is not None and "strike" not in skw:
            skw["strike"] = self.strike
        if "side" not in skw:
            skw["side"] = self.side

        inferred_structure = _infer_outright_structure(self.structure, skw.get("strike", self.strike))
        object.__setattr__(self, "structure", inferred_structure)
        object.__setattr__(self, "structure_id", inferred_structure)

        if not _is_explicit_date_mode(skw):
            if skw.get("expiry") is None or skw.get("tail") is None:
                raise ValueError(
                    "IRSwaptionQuery requires either explicit dates "
                    "(exercise_date, underlying_effective_date, underlying_maturity_date) "
                    "or tenor mode (expiry, tail)."
                )

        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        mr.setdefault("endpoint", "swaption_snapshot")
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["IRSwaptionQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]

    def _tenor_label(self) -> str:
        skw = self.structure_kwargs or {}
        if skw.get("expiry") and skw.get("tail"):
            return f"{skw['expiry']}x{skw['tail']}"
        if _is_explicit_date_mode(skw):
            return f"{skw['exercise_date']}/{skw['underlying_maturity_date']}"
        return "UNKNOWN"

    def col_name(self, cube_name: Optional[str] = None) -> str:
        if cube_name:
            object.__setattr__(self, "_curve_name", cube_name)
        curve_lbl = self._curve_name if self._curve_name is not None else self.curve
        val_lbl = self.value.name if not isinstance(self.value, list) else "MULTI"
        side_lbl = str((self.structure_kwargs or {}).get("side", self.side)).upper()
        strike_lbl = str((self.structure_kwargs or {}).get("strike", self.strike))
        text = f"{curve_lbl or ''} {self._tenor_label()} {self.structure.name} {side_lbl} {strike_lbl} {val_lbl}".strip()
        if self.name:
            return str(self.name)
        return " ".join(text.split())

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def resolve_query(self, ref_dt, pricer_or_curve):
        skw = dict(self.structure_kwargs or {})
        if self.trade_date is None:
            return self

        if _is_explicit_date_mode(skw):
            return self

        if self.structure not in {IRSwaptionStructure.RECEIVER, IRSwaptionStructure.PAYER, IRSwaptionStructure.STRADDLE}:
            raise ValueError("trade_date mode only supports RECEIVER, PAYER, or STRADDLE structures.")

        tail = str(skw.get("tail") or "")
        if "x" in tail.lower():
            raise ValueError("trade_date mode does not support midcurve tails containing 'x'.")

        expiry = skw.get("expiry")
        if not expiry or not tail:
            return self

        context = pricer_or_curve
        if not hasattr(context, "curve"):
            raise TypeError("trade_date resolution expects IRSwaptionMarketContext with a .curve attribute.")

        curve = context.curve
        td = to_date(self.trade_date)
        ex_dt = to_date(curve.calendar_advance(td, str(expiry)))
        _mid, tenor = parse_midcurve_tail(str(tail))
        eff_dt = ex_dt
        mat_dt = to_date(curve.calendar_advance(eff_dt, str(tenor)))

        par_swap = curve.build_irswap(
            effective_date=eff_dt,
            maturity_date=mat_dt,
            fixed_rate=-0.0,
            notional=1.0,
        )
        atmf = abs(float(curve.fair_rate(par_swap)))

        option_type = "payer" if self.structure == IRSwaptionStructure.PAYER else "receiver"
        temp_leg = IRSwaptionPricable(
            option_type=option_type,
            exercise_date=ex_dt,
            underlying_effective_date=eff_dt,
            underlying_maturity_date=mat_dt,
            strike=atmf,
            notional=1.0,
        )
        vol = float(leg_model_vol(context, temp_leg, strike=atmf))
        tte = float(leg_tte_years(context, temp_leg))
        fwd = float(leg_forward_rate(context, temp_leg))

        strike_resolved = resolve_strike_spec(
            skw.get("strike", self.strike),
            atmf=atmf,
            atms=atmf,
            option_type=option_type,
            vol_normal=vol,
            tte=tte,
            forward=fwd,
        )

        skw["exercise_date"] = ex_dt
        skw["underlying_effective_date"] = eff_dt
        skw["underlying_maturity_date"] = mat_dt
        skw["strike"] = strike_resolved

        q2 = replace(
            self,
            exercise_date=ex_dt,
            underlying_effective_date=eff_dt,
            underlying_maturity_date=mat_dt,
            strike=strike_resolved,
            structure_kwargs=skw,
        )
        return q2

    def __pos__(self) -> "IRSwaptionQuery":
        assert not isinstance(self.value, list)
        return self

    def __neg__(self) -> "IRSwaptionQuery":
        assert not isinstance(self.value, list)
        return replace(self, risk_weight=-(self.risk_weight or 1.0))

    def __add__(self, other: object) -> List["IRSwaptionQuery"]:
        if isinstance(other, IRSwaptionQuery):
            return [self * 1, other * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwaptionQuery) for q in other):
            return [self * 1] + [q * 1 for q in other]
        return NotImplemented  # type: ignore[return-value]

    def __radd__(self, other: object) -> List["IRSwaptionQuery"]:
        if isinstance(other, IRSwaptionQuery):
            return [other * 1, self * 1]
        if isinstance(other, list) and all(isinstance(q, IRSwaptionQuery) for q in other):
            return [q * 1 for q in other] + [self * 1]
        return NotImplemented  # type: ignore[return-value]

    def __sub__(self, other: object) -> List["IRSwaptionQuery"]:
        if isinstance(other, IRSwaptionQuery):
            return [self * 1, other * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwaptionQuery) for q in other):
            return [self * 1] + [q * -1 for q in other]
        return NotImplemented  # type: ignore[return-value]

    def __rsub__(self, other: object) -> List["IRSwaptionQuery"]:
        if isinstance(other, IRSwaptionQuery):
            return [other * 1, self * -1]
        if isinstance(other, list) and all(isinstance(q, IRSwaptionQuery) for q in other):
            return [q * 1 for q in other] + [self * -1]
        return NotImplemented  # type: ignore[return-value]

    def __mul__(self, scalar: object) -> "IRSwaptionQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented  # type: ignore[return-value]
        return replace(self, risk_weight=(self.risk_weight or 1.0) * float(scalar))

    def __rmul__(self, scalar: object) -> "IRSwaptionQuery":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> "IRSwaptionQuery":
        if not isinstance(scalar, (int, float)):
            return NotImplemented  # type: ignore[return-value]
        return self * (1.0 / float(scalar))

    def default_mtm_value_id(self) -> Any:
        return IRSwaptionValue.SPOT_NPV


@dataclass
class IRSwaptionQueryWrapper:
    queries: List[IRSwaptionQuery]
    name: str

    def __init__(self, queries: Union[IRSwaptionQuery, List[IRSwaptionQuery]], name: str):
        self.queries = [queries] if isinstance(queries, IRSwaptionQuery) else list(queries)
        self.name = str(name)

    def return_query(self) -> List[IRSwaptionQuery]:
        return list(self.queries)

    def col_name(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        return self.name

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        _ = cube_name
        parts = []
        for q in self.queries:
            rw = q.risk_weight if q.risk_weight is not None else 1.0
            parts.append(f"{rw} * `{q.col_name()}`")
        return " + ".join(parts)
