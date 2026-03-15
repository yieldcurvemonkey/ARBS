from enum import Enum, auto
from functools import partial
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import datetime

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.FixedRateBonds._FixedRateBondGenericPricable import _FixedRateBondGenericPricable
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer


def linear_solve_for_risk_weighted_notionals(
    risk_weights: np.ndarray,
    bpvs: np.ndarray,
    constrained_leg_index: int,
    constrained_leg_contribution: float,
    contribution_is_bpv: Optional[bool] = False,
) -> np.ndarray:
    idx = constrained_leg_index
    constrained_leg_contribution = np.copysign(constrained_leg_contribution, risk_weights[idx])
    if contribution_is_bpv:
        notional_contrib = constrained_leg_contribution / bpvs[idx]
    else:
        notional_contrib = constrained_leg_contribution

    R = notional_contrib * bpvs[idx] / risk_weights[idx]
    notionals = (risk_weights * R) / bpvs
    return notionals


class FixedRateBondStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()


@dataclass(frozen=True)
class FixedRateBondPricableSpec:
    instrument: Any
    cusip: str
    issue_date: datetime.date
    maturity_date: datetime.date
    cpn: float
    notional: float


class FixedRateBondStructureFunctionMap(BaseStructureFunctionMap[FixedRateBondStructure, FixedRateBondPricableSpec]):
    def __init__(self, pricer: Dict[str, _FixedRateBondGenericPricer]):
        super().__init__(FixedRateBondStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[FixedRateBondStructure, Callable[..., List[FixedRateBondPricableSpec]]]:
        return {
            FixedRateBondStructure.OUTRIGHT: partial(self._build_outright),
            FixedRateBondStructure.CURVE: partial(self._build_curve),
            FixedRateBondStructure.FLY: partial(self._build_fly),
        }

    def _leg(
        self,
        cusip: str,
        issue_date: datetime.date,
        maturity_date: datetime.date,
        cpn: float,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
    ) -> FixedRateBondPricableSpec:
        current_pricer: _FixedRateBondGenericPricer = self.common_kwargs["pricer"][cusip]
        instrument = current_pricer.build_pricable(cusip=cusip, issue_date=issue_date, maturity_date=maturity_date, cpn=cpn, notional=notional, bpv=bpv)
        return FixedRateBondPricableSpec(
            instrument=instrument,
            cusip=str(cusip),
            issue_date=issue_date,
            maturity_date=maturity_date,
            cpn=float(cpn),
            notional=float(current_pricer.notional(instrument)),
        )

    def _leg_spec(self, *, cusip: str, prefix: str, **kwargs: Any) -> Dict[str, Any]:
        pricer: _FixedRateBondGenericPricer = self.common_kwargs["pricer"][cusip]
        return {
            "cusip": cusip,
            "issue_date": kwargs.get(f"{prefix}_issue_date") or kwargs.get("issue_date") or pricer.issue_date(),
            "maturity_date": kwargs.get(f"{prefix}_maturity_date") or kwargs.get("maturity_date") or pricer.maturity_date(),
            "cpn": kwargs.get(f"{prefix}_cpn") or kwargs.get(f"{prefix}_coupon") or kwargs.get("cpn") or kwargs.get("coupon") or pricer.coupon(),
        }

    def _build_spreadable(
        self,
        leg_specs: List[Dict[str, Any]],
        risk_weights: List[float],
        constrained_leg_index: int,
        constrained_notional: Optional[float] = None,
        constrained_bpv: Optional[float] = None,
    ) -> List[FixedRateBondPricableSpec]:
        n = len(leg_specs)
        rw = np.array(risk_weights or ([1.0, -1.0] + [0.0] * (n - 2))[:n], dtype=float)

        if sum(x is not None for x in (constrained_notional, constrained_bpv)) != 1:
            raise ValueError("Must specify exactly one of constrained_notional/bpv")

        bpvs = [self.common_kwargs["pricer"][spec["cusip"]].pv01(1) for spec in leg_specs]
        notionals = linear_solve_for_risk_weighted_notionals(
            risk_weights=rw,
            bpvs=bpvs,
            constrained_leg_index=constrained_leg_index,
            constrained_leg_contribution=constrained_notional if constrained_notional is not None else constrained_bpv,
            contribution_is_bpv=(constrained_bpv is not None),
        )

        return [self._leg(**spec, notional=float(n)) for spec, n in zip(leg_specs, notionals)]

    def _build_outright(self, notional: Optional[float] = None, bpv: Optional[float] = None, **_) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        if (notional is None and bpv is None) or (notional is not None and bpv is not None):
            raise ValueError("Must specify exactly one of `notional` or `bpv` for an outright bond.")

        cusip = next(iter(self.common_kwargs["pricer"]))
        pricer: _FixedRateBondGenericPricer = self.common_kwargs["pricer"][cusip]
        bond = self._leg(cusip=cusip, issue_date=_.get("issue_date") or pricer.issue_date(), maturity_date=_.get("maturity_date") or pricer.maturity_date(), cpn=_.get("cpn") or _.get("coupon") or pricer.coupon(), notional=notional, bpv=bpv)
        weight = 1.0 if bond.notional > 0 else -1.0
        return [bond], [weight]

    def _build_curve(
        self, front_notional: Optional[float] = None, back_notional: Optional[float] = None, bpv: Optional[float] = None, risk_weights: List[float] = [1.0, 1.0], **_
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        pricers: Dict[str, _FixedRateBondGenericPricable] = self.common_kwargs["pricer"]
        cusips = list(pricers.keys())
        assert len(cusips) == 2, "its a CURVE!"

        leg0 = self._leg_spec(cusip=cusips[0], prefix="front", **_)
        leg1 = self._leg_spec(cusip=cusips[1], prefix="back", **_)

        if front_notional is not None:
            idx, cn, cp = 0, front_notional, None
            risk_weights[0] = np.copysign(risk_weights[0], cn)
            risk_weights[1] = np.copysign(risk_weights[1], risk_weights[0] * -1)
        elif back_notional is not None:
            idx, cn, cp = 1, back_notional, None
            risk_weights[1] = np.copysign(risk_weights[1], cn)
            risk_weights[0] = np.copysign(risk_weights[0], risk_weights[1] * -1)
        else:
            idx, cn, cp = 1, None, bpv  # relative to the back leg e.g. rec 2s10s => rec 10s, pay2s flattener
            risk_weights[1] = np.copysign(risk_weights[1], cp)
            risk_weights[0] = np.copysign(risk_weights[0], risk_weights[1] * -1)

        return (
            self._build_spreadable(
                [leg0, leg1],
                risk_weights=risk_weights,
                constrained_leg_index=idx,
                constrained_notional=cn,
                constrained_bpv=cp,
            ),
            risk_weights,
        )

    def _build_fly(
        self,
        front_notional: Optional[float] = None,
        belly_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        bpv: Optional[float] = None,
        risk_weights: List[float] = [1.0, 2.0, 1.0],
        **_,
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        pricers: Dict[str, _FixedRateBondGenericPricable] = self.common_kwargs["pricer"]
        cusips = list(pricers.keys())
        assert len(cusips) == 3, "its a FLY!"

        if front_notional is not None:
            idx, cn, cp = 0, front_notional, None
        elif belly_notional is not None:
            idx, cn, cp = 1, belly_notional, None
        elif back_notional is not None:
            idx, cn, cp = 2, back_notional, None
        else:
            idx, cn, cp = 1, None, bpv

        risk_weights[idx] = np.copysign(risk_weights[idx], cn if cn is not None else cp)
        for i in range(3):
            if i != idx:
                risk_weights[i] = np.copysign(risk_weights[i], -risk_weights[idx])

        leg0 = self._leg_spec(cusip=cusips[0], prefix="front", **_)
        leg1 = self._leg_spec(cusip=cusips[1], prefix="belly", **_)
        leg2 = self._leg_spec(cusip=cusips[2], prefix="back", **_)

        return (
            self._build_spreadable(
                leg_specs=[leg0, leg1, leg2],
                risk_weights=risk_weights,
                constrained_leg_index=idx,
                constrained_notional=cn,
                constrained_bpv=cp,
            ),
            risk_weights,
        )
