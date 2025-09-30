import datetime
import math
from enum import Enum, auto
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

# helper for date stuff
import QuantLib as ql
from rateslib.scheduling import get_imm, next_imm

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve, _IRSwapGenericObject
from Query.IRSwaps.backends.quantlib.utils import ql_date_to_pydate


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


class IRSwapStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()
    SPREAD = auto()


class IRSwapStructureFunctionMap(BaseStructureFunctionMap[IRSwapStructure, _IRSwapGenericObject]):
    def __init__(
        self,
        curve: _IRSwapGenericCurve,
    ):
        super().__init__(
            IRSwapStructure,
            curve=curve,
        )

        self._map = self._create_map()

    def _create_map(self) -> Dict[IRSwapStructure, Callable[..., List[_IRSwapGenericObject]]]:
        return {
            IRSwapStructure.OUTRIGHT: partial(self._build_outright),
            IRSwapStructure.CURVE: partial(self._build_curve),
            IRSwapStructure.FLY: partial(self._build_fly),
            IRSwapStructure.SPREAD: partial(self._build_outright),
        }

    def _to_dt(self, d: Union[datetime.date, ql.Date, ql.Period, str], ref_date: Union[datetime.date, ql.Date]):

        if isinstance(d, ql.Period) or isinstance(d, str):
            if isinstance(d, str) and d.upper().startswith("IMM_"):
                if str(d.split("IMM_")[-1]).isnumeric():
                    offset = int(d.split("IMM_")[-1]) - 1
                    if isinstance(ref_date, ql.Date):
                        ref_date = ql_date_to_pydate(d)
                    imm = ref_date + datetime.timedelta(days=1)
                    for _ in range(offset + 1):
                        imm = next_imm(imm)
                    return imm
                return get_imm(code=d.split("IMM_")[-1])

            current_curve: _IRSwapGenericCurve = self.common_kwargs["curve"]
            d = current_curve.calendar_advance(ref_date, d)

        if isinstance(d, ql.Date):
            return ql_date_to_pydate(d)

        return d

    def _leg(
        self,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_for_timeseries: Optional[bool] = False,
    ) -> _IRSwapGenericObject:
        current_curve: _IRSwapGenericCurve = self.common_kwargs["curve"]

        if not is_for_timeseries:
            assert notional is not None or bpv is not None, "One of `notional` or `bpv` must be defined"

        if isinstance(tenor, str) and tenor.startswith("IMM_"):
            imm_date, mat_date = tenor.split("x")
            effective_date = self._to_dt(imm_date, current_curve.reference_date())
            maturity_date = self._to_dt(mat_date, effective_date)
            fwd, tenor = None, None
        elif isinstance(tenor, str) and tenor in _CENTRAL_BANK_DATES[current_curve.id()]:
            effective_date = _CENTRAL_BANK_DATES[current_curve.id()][tenor][0]
            maturity_date = _CENTRAL_BANK_DATES[current_curve.id()][tenor][1]
            fwd, tenor = None, None
        else:
            if tenor and "x" in tenor:
                fwd, tenor = tenor.split("x")
                fwd, tenor = fwd, tenor
            elif tenor:
                fwd, tenor = "0D", tenor if tenor else None
            elif effective_date and maturity_date:
                fwd, tenor = None, None
            else:
                print(effective_date, maturity_date)
                raise ValueError("Need to define tenor or dates")

        sw = current_curve.build_irswap(
            fwd=fwd,
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
        )
        return sw

    def _build_spreadable(
        self,
        leg_specs: List[Dict[str, Any]],
        risk_weights: Optional[List[float]] = None,
        constrained_leg_index: Optional[int] = None,
        constrained_notional: Optional[float] = None,
        constrained_bpv: Optional[float] = None,
    ) -> List[_IRSwapGenericObject]:
        current_curve: _IRSwapGenericCurve = self.common_kwargs["curve"]

        n = len(leg_specs)
        rw = np.array(risk_weights or ([1.0, -1.0] + [0.0] * (n - 2))[:n], dtype=float)

        if sum(x is not None for x in (constrained_notional, constrained_bpv)) != 1 or constrained_leg_index is None:
            raise ValueError("Must specify constrained_leg_index and exactly one of constrained_notional/bpv")

        unit_swaps = [self._leg(**spec, notional=1.0) for spec in leg_specs]
        bpvs = np.array([current_curve.pv01(s) for s in unit_swaps], dtype=float)

        contribution_is_bpv = False
        if constrained_notional is not None:
            contribution = constrained_notional
        else:
            contribution = constrained_bpv
            contribution_is_bpv = True

        notionals = linear_solve_for_risk_weighted_notionals(
            risk_weights=rw,
            bpvs=bpvs,
            constrained_leg_index=constrained_leg_index,
            constrained_leg_contribution=contribution,
            contribution_is_bpv=contribution_is_bpv,
        )
        result = []
        for spec, n in zip(leg_specs, notionals):
            result.append(self._leg(**spec, notional=float(n)))
        return result

    def _build_outright(
        self,
        *,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_for_timeseries: Optional[bool] = False,
        **_,
    ) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        if not is_for_timeseries:
            assert notional is not None or bpv is not None, "must pass in `notional` or `bpv` if not for timeseries buildig"

        if (notional is not None and notional > 0) or (bpv is not None and bpv > 0):
            rw = 1
        else:
            rw = -1

        return (
            [
                self._leg(
                    tenor=tenor,
                    effective_date=effective_date,
                    maturity_date=maturity_date,
                    fixed_rate=fixed_rate,
                    notional=notional,
                    bpv=bpv,
                    is_for_timeseries=is_for_timeseries,
                )
            ],
            [rw],
        )

    def _build_curve(
        self,
        *,
        front_tenor: Optional[str] = None,
        front_effective_date: Optional[datetime.date] = None,
        front_maturity_date: Optional[datetime.date] = None,
        back_tenor: Optional[str] = None,
        back_effective_date: Optional[datetime.date] = None,
        back_maturity_date: Optional[datetime.date] = None,
        front_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        bpv: Optional[float] = None,
        risk_weights: Optional[List[float]] = [1, 1],
        front_fixed_rate: Optional[float] = -0,
        back_fixed_rate: Optional[float] = -0,
        **_,
    ) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        assert sum(x is not None for x in (front_notional, back_notional, bpv)) == 1, "Exactly one of front_notional, back_notional or bpv must be provided"
        assert len(risk_weights) == 2, "CURVE 2 RISK WEIGHTS"

        # `_leg` specs
        leg0 = dict(tenor=front_tenor, effective_date=front_effective_date, maturity_date=front_maturity_date, fixed_rate=front_fixed_rate)
        leg1 = dict(tenor=back_tenor, effective_date=back_effective_date, maturity_date=back_maturity_date, fixed_rate=back_fixed_rate)

        # determine constraint
        if front_notional is not None:
            idx, cn, cp = 0, front_notional, None
            risk_weights[0] = math.copysign(risk_weights[0], cn)
            risk_weights[1] = math.copysign(risk_weights[1], risk_weights[0] * -1)
        elif back_notional is not None:
            idx, cn, cp = 1, back_notional, None
            risk_weights[1] = math.copysign(risk_weights[1], cn)
            risk_weights[0] = math.copysign(risk_weights[0], risk_weights[1] * -1)
        else:
            idx, cn, cp = 1, None, bpv  # relative to the back leg e.g. rec 2s10s => rec 10s, pay2s flattener
            risk_weights[1] = math.copysign(risk_weights[1], cp)
            risk_weights[0] = math.copysign(risk_weights[0], risk_weights[1] * -1)

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
        *,
        front_tenor: Optional[str] = None,
        front_effective_date: Optional[datetime.date] = None,
        front_maturity_date: Optional[datetime.date] = None,
        belly_tenor: Optional[str] = None,
        belly_effective_date: Optional[datetime.date] = None,
        belly_maturity_date: Optional[datetime.date] = None,
        back_tenor: Optional[str] = None,
        back_effective_date: Optional[datetime.date] = None,
        back_maturity_date: Optional[datetime.date] = None,
        front_fixed_rate: Optional[float] = -0.0,
        mid_fixed_rate: Optional[float] = -0.0,
        back_fixed_rate: Optional[float] = -0.0,
        front_notional: Optional[float] = None,
        belly_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        bpv: Optional[float] = None,
        risk_weights: Optional[List[float]] = [1.0, 2.0, 1.0],
        **_,
    ) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        assert (
            sum(x is not None for x in (front_notional, belly_notional, back_notional, bpv)) == 1
        ), "Exactly one of front_notional, belly_notional, back_notional or bpv must be provided"
        assert len(risk_weights) == 3, "FLY NEEDS 3 RISK WEIGHTS"

        if front_notional is not None:
            idx, cn, cp = 0, front_notional, None
        elif belly_notional is not None:
            idx, cn, cp = 1, belly_notional, None
        elif back_notional is not None:
            idx, cn, cp = 2, back_notional, None
        else:
            idx, cn, cp = 1, None, bpv

        risk_weights[idx] = math.copysign(risk_weights[idx], cn if cn is not None else cp)
        for i in range(3):
            if i != idx:
                risk_weights[i] = math.copysign(risk_weights[i], -risk_weights[idx])

        leg0 = dict(
            tenor=front_tenor,
            effective_date=front_effective_date,
            maturity_date=front_maturity_date,
            fixed_rate=front_fixed_rate,
        )
        leg1 = dict(
            tenor=belly_tenor,
            effective_date=belly_effective_date,
            maturity_date=belly_maturity_date,
            fixed_rate=mid_fixed_rate,
        )
        leg2 = dict(
            tenor=back_tenor,
            effective_date=back_effective_date,
            maturity_date=back_maturity_date,
            fixed_rate=back_fixed_rate,
        )

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
