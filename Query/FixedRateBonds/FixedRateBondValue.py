from enum import Enum, auto
from typing import Any, Callable, Dict, List

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondPricableSpec
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds._FixedRateBondGenericPricable import _FixedRateBondGenericPricable


class FixedRateBondValue(Enum):
    YTM = auto()
    CLEAN_PRICE = auto()
    DIRTY_PRICE = auto()
    NPV = auto()
    PV01 = auto()
    DV01 = auto()
    MOD_DURATION = auto()
    CONVEXITY = auto()


# _frb_structure_sign_mapper = {
#     FixedRateBondStructure.OUTRIGHT: lambda rws: [abs(rws[0])],
#     FixedRateBondStructure.CURVE: lambda rws: [-1 * abs(rws[0]), abs(rws[1])],
#     FixedRateBondStructure.FLY: lambda rws: [-1 * abs(rws[0]), abs(rws[1]), -1 * abs(rws[2])],
# }
_frb_structure_sign_mapper = {
    FixedRateBondStructure.OUTRIGHT: lambda rws: rws,
    FixedRateBondStructure.CURVE: lambda rws: rws,
    FixedRateBondStructure.FLY: lambda rws: rws,
}
_frb_structure_legs_mapper = {
    1: (FixedRateBondStructure.OUTRIGHT, 1),
    2: (FixedRateBondStructure.CURVE, 100),
    3: (FixedRateBondStructure.FLY, 100),
}


def calc_spread_rate(
    pricer: Dict[str, _FixedRateBondGenericPricer],
    package: List[FixedRateBondPricableSpec],
    risk_weights: List[float],
) -> float:
    risk_weights = _frb_structure_sign_mapper[_frb_structure_legs_mapper[len(package)][0]](risk_weights)
    return sum([risk_weights[i] * abs(_rebuild_pricer(pr, leg).ytm()) for i, (pr, leg) in enumerate(zip(pricer.values(), package))])


def _quote_kwargs(pr: _FixedRateBondGenericPricer) -> Dict[str, Any]:
    clean_price = getattr(pr, "_clean_price", None)
    ytm = getattr(pr, "_ytm", None)
    if clean_price is not None:
        return {"clean_price": clean_price}
    if ytm is not None:
        return {"ytm": ytm}
    return {"clean_price": pr.clean_price()}


def _rebuild_pricer(pr: _FixedRateBondGenericPricer, leg: FixedRateBondPricableSpec) -> _FixedRateBondGenericPricer:
    init_kwargs = {
        "reference_date": pr.reference_date(),
        "issue_date": leg.issue_date,
        "maturity_date": leg.maturity_date,
        "cpn": leg.cpn,
        "notional": leg.notional,
        "meta_data": pr.meta(),
        **_quote_kwargs(pr),
    }
    if hasattr(pr, "_ql_frb_id"):
        init_kwargs["ql_frb_id"] = pr.id()
    else:
        init_kwargs["rl_frb_id"] = pr.id()
    return type(pr)(**init_kwargs)


class FixedRateBondValueFunctionMap(BaseValueFunctionMap[FixedRateBondValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _FixedRateBondGenericPricer],
        package: List[FixedRateBondPricableSpec],
        risk_weights: List[float],
    ):
        super().__init__(FixedRateBondValue, package=package, risk_weights=risk_weights, pricer=pricer)

    def _create_map(self) -> Dict[FixedRateBondValue, Callable[..., float]]:
        return {
            FixedRateBondValue.YTM: self._ytm,
            FixedRateBondValue.CLEAN_PRICE: self._clean_price,
            FixedRateBondValue.DIRTY_PRICE: self._dirty_price,
            FixedRateBondValue.NPV: self._npv,
            FixedRateBondValue.PV01: self._pv01,
            FixedRateBondValue.DV01: self._dv01,
            FixedRateBondValue.MOD_DURATION: self._mod_duration,
            # FixedRateBondValue.CONVEXITY: self._convexity,
        }

    def _ytm(self, **kwargs: Any) -> float:
        return calc_spread_rate(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _frb_structure_legs_mapper[len(kwargs["package"])][1]

    def _clean_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(pr, leg).clean_price() for pr, leg in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dirty_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(pr, leg).dirty_price(notional=leg.notional) for pr, leg in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _npv(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(pr, leg).npv(notional=leg.notional) for pr, leg in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _pv01(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(pr, leg).pv01(notional=leg.notional) for pr, leg in zip(kwargs["pricer"].values(), kwargs["package"]))

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)

    def _mod_duration(self, **kwargs: Any) -> float:
        return sum([kwargs["risk_weights"][i] * abs(_rebuild_pricer(pr, leg).mod_duration()) for i, (pr, leg) in enumerate(zip(kwargs["pricer"].values(), kwargs["package"]))])

    def _convexity(self, **kwargs: Any) -> float:
        return sum([kwargs["risk_weights"][i] * abs(_rebuild_pricer(pr, leg).convexity()) for i, (pr, leg) in enumerate(zip(kwargs["pricer"].values(), kwargs["package"]))])
