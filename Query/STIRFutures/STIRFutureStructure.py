from __future__ import annotations

import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


class STIRFutureStructure(Enum):
    OUTRIGHT = auto()
    SPREAD = auto()


class STIRFutureStructureFunctionMap(BaseStructureFunctionMap[STIRFutureStructure, Any]):
    def __init__(self, curve: _IRSwapGenericCurve):
        super().__init__(STIRFutureStructure, curve=curve)
        self._map = self._create_map()

    def _create_map(self) -> Dict[STIRFutureStructure, Callable[..., Tuple[List[Any], List[float]]]]:
        return {
            STIRFutureStructure.OUTRIGHT: self._build_outright,
            STIRFutureStructure.SPREAD: self._build_spread,
        }

    def _leg(
        self,
        curve: _IRSwapGenericCurve,
        *,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = None,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
    ) -> Any:
        return curve.build_stirf(
            fwd=None,
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
            is_ser=is_ser,
        )

    def _build_outright(
        self,
        curve: _IRSwapGenericCurve,
        *,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = None,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
        risk_weights: Optional[List[float]] = None,
        **_,
    ) -> Tuple[List[Any], List[float]]:
        leg = self._leg(
            curve,
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
            is_ser=is_ser,
        )
        rw = risk_weights[0] if risk_weights else 1.0
        if notional is not None and notional < 0:
            rw = -abs(rw)
        return [leg], [rw]

    def _build_spread(
        self,
        curve: _IRSwapGenericCurve,
        *,
        front_tenor: Optional[str] = None,
        back_tenor: Optional[str] = None,
        front_effective_date: Optional[datetime.date] = None,
        back_effective_date: Optional[datetime.date] = None,
        front_maturity_date: Optional[datetime.date] = None,
        back_maturity_date: Optional[datetime.date] = None,
        front_fixed_rate: Optional[float] = None,
        back_fixed_rate: Optional[float] = None,
        front_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        front_bpv: Optional[float] = None,
        back_bpv: Optional[float] = None,
        risk_weights: Optional[List[float]] = None,
        is_ser: Optional[bool] = False,
        **_,
    ) -> Tuple[List[Any], List[float]]:
        front = self._leg(
            curve,
            tenor=front_tenor,
            effective_date=front_effective_date,
            maturity_date=front_maturity_date,
            fixed_rate=front_fixed_rate,
            notional=front_notional,
            bpv=front_bpv,
            is_ser=is_ser,
        )
        back = self._leg(
            curve,
            tenor=back_tenor,
            effective_date=back_effective_date,
            maturity_date=back_maturity_date,
            fixed_rate=back_fixed_rate,
            notional=back_notional,
            bpv=back_bpv,
            is_ser=is_ser,
        )

        if risk_weights is None:
            risk_weights = [1.0, -1.0]

        return [front, back], risk_weights
