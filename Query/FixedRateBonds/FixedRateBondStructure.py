from enum import Enum, auto
from functools import partial
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


class FixedRateBondStructureFunctionMap(BaseStructureFunctionMap[FixedRateBondStructure, _FixedRateBondGenericPricable]):
    def __init__(self, pricer: Dict[str, _FixedRateBondGenericPricer]):
        super().__init__(FixedRateBondStructure, pricer=pricer)
        self._map = self._create_map()

    def _create_map(self) -> Dict[FixedRateBondStructure, Callable[..., List[_FixedRateBondGenericPricable]]]:
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
    ) -> _FixedRateBondGenericPricable:
        current_pricer: _FixedRateBondGenericPricer = self.common_kwargs["pricer"][cusip]
        return current_pricer.build_pricable(cusip=cusip, issue_date=issue_date, maturity_date=maturity_date, cpn=cpn, notional=notional, bpv=bpv)

    def _build_spreadable(
        self,
        leg_specs: List[Dict[str, Any]],
        risk_weights: List[float],
        constrained_leg_index: int,
        constrained_notional: Optional[float] = None,
        constrained_bpv: Optional[float] = None,
    ) -> List[_FixedRateBondGenericPricable]:
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
        bond = self._leg(cusip=cusip, issue_date=pricer.issue_date(), maturity_date=pricer.maturity_date(), cpn=pricer.coupon(), notional=notional, bpv=bpv)
        weight = 1.0 if pricer.notional(bond) > 0 else -1.0
        return [bond], [weight]

    def _build_curve(
        self, front_notional: Optional[float] = None, back_notional: Optional[float] = None, bpv: Optional[float] = None, risk_weights: List[float] = [1.0, 1.0], **_
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        pricers: Dict[str, _FixedRateBondGenericPricable] = self.common_kwargs["pricer"] 
        cusips = list(pricers.keys())
        assert len(cusips) == 2, "its a CURVE!"

        leg0 = {
            "cusip": cusips[0],
            "issue_date": pricers[cusips[0]].issue_date(),
            "maturity_date": pricers[cusips[0]].maturity_date(),
            "cpn": pricers[cusips[0]].coupon(),
        }
        leg1 = {
            "cusip": cusips[1],
            "issue_date": pricers[cusips[1]].issue_date(),
            "maturity_date": pricers[cusips[1]].maturity_date(),
            "cpn": pricers[cusips[1]].coupon(),
        }

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
        self, front_cusip: str, belly_cusip: str, back_cusip: str, bpv: float, risk_weights: List[float] = [1.0, -2.0, 1.0], **_
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:

        raise NotImplementedError()
        # leg0 = {"cusip": front_cusip}
        # leg1 = {"cusip": belly_cusip}
        # leg2 = {"cusip": back_cusip}

        # return (
        #     self._build_spreadable(
        #         [leg0, leg1, leg2],
        #         risk_weights=risk_weights,
        #         constrained_leg_index=1,  # Constrain the belly leg
        #         constrained_bpv=bpv,
        #     ),
        #     risk_weights,
        # )
