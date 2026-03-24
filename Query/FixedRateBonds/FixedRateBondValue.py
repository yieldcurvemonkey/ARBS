from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondPricableSpec
from Query.FixedRateBonds._FixedRateBondGenericPricer import _FixedRateBondGenericPricer
from Query.FixedRateBonds._FixedRateBondGenericPricable import _FixedRateBondGenericPricable
from Query.FixedRateBonds.carry_roll import (
    compute_carry_roll_frame,
    expand_pricer_universe_for_carry_roll,
    frame_supports_roll,
    normalize_horizon_spec,
    safe_float,
)


class FixedRateBondValue(Enum):
    YTM = auto()
    CLEAN_PRICE = auto()
    DIRTY_PRICE = auto()
    NPV = auto()
    PV01 = auto()
    DV01 = auto()
    MOD_DURATION = auto()
    CONVEXITY = auto()
    CARRY_BPS_RUNNING = auto()
    ROLL_BPS_RUNNING = auto()
    CARRY_AND_ROLL_BPS_RUNNING = auto()


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
    return sum(risk_weights[i] * abs(_rebuild_pricer(_resolve_leg_pricer(pricer, leg), leg).ytm()) for i, leg in enumerate(package))


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


def _resolve_leg_pricer(
    pricers: Dict[str, _FixedRateBondGenericPricer],
    leg: FixedRateBondPricableSpec,
) -> _FixedRateBondGenericPricer:
    leg_key = str(leg.cusip)
    pr = pricers.get(leg_key)
    if pr is not None:
        return pr

    for key, candidate in pricers.items():
        try:
            meta = candidate.meta() or {}
        except Exception:
            meta = {}
        if str(meta.get("cusip") or key) == leg_key:
            return candidate

    raise KeyError(f"Missing FRB pricer for leg cusip={leg_key!r}. available={list(pricers.keys())}")


class FixedRateBondValueFunctionMap(BaseValueFunctionMap[FixedRateBondValue, float]):
    def __init__(
        self,
        pricer: Dict[str, _FixedRateBondGenericPricer],
        package: List[FixedRateBondPricableSpec],
        risk_weights: List[float],
    ):
        super().__init__(FixedRateBondValue, package=package, risk_weights=risk_weights, pricer=pricer)
        self._carry_roll_lookup_cache: Optional[pd.DataFrame] = None

    def _create_map(self) -> Dict[FixedRateBondValue, Callable[..., float]]:
        return {
            FixedRateBondValue.YTM: self._ytm,
            FixedRateBondValue.CLEAN_PRICE: self._clean_price,
            FixedRateBondValue.DIRTY_PRICE: self._dirty_price,
            FixedRateBondValue.NPV: self._npv,
            FixedRateBondValue.PV01: self._pv01,
            FixedRateBondValue.DV01: self._dv01,
            FixedRateBondValue.MOD_DURATION: self._mod_duration,
            FixedRateBondValue.CARRY_BPS_RUNNING: self._carry_bps_running,
            FixedRateBondValue.ROLL_BPS_RUNNING: self._roll_bps_running,
            FixedRateBondValue.CARRY_AND_ROLL_BPS_RUNNING: self._carry_and_roll_bps_running,
            # FixedRateBondValue.CONVEXITY: self._convexity,
        }

    def _frame_covers_package(self, frame: pd.DataFrame) -> bool:
        if frame.empty or "cusip" not in frame.columns:
            return False
        available = set(frame["cusip"].astype(str))
        for leg in self.common_kwargs["package"]:
            candidate_keys = {str(leg.cusip)}
            try:
                leg_pricer = _resolve_leg_pricer(self.common_kwargs["pricer"], leg)
                meta = leg_pricer.meta() or {}
            except Exception:
                meta = {}
            candidate_keys.add(str(meta.get("cusip") or leg.cusip))
            if available.isdisjoint(candidate_keys):
                return False
        return True

    def _carry_roll_lookup(self) -> pd.DataFrame:
        if self._carry_roll_lookup_cache is None:
            pricers = self.common_kwargs["pricer"]
            if not pricers:
                self._carry_roll_lookup_cache = pd.DataFrame()
            else:
                first_pricer = next(iter(pricers.values()))
                as_of_date = first_pricer.reference_date()
                frame = compute_carry_roll_frame(pricers=pricers, as_of_date=as_of_date)
                if not self._frame_covers_package(frame) or not frame_supports_roll(frame, as_of_date=as_of_date):
                    expanded_pricers = expand_pricer_universe_for_carry_roll(
                        pricers=pricers,
                        as_of_date=as_of_date,
                        min_ttm=1.0,
                    )
                    frame = compute_carry_roll_frame(pricers=expanded_pricers, as_of_date=as_of_date)
                if frame.empty or "cusip" not in frame.columns:
                    self._carry_roll_lookup_cache = pd.DataFrame()
                else:
                    self._carry_roll_lookup_cache = frame.drop_duplicates(subset=["cusip"], keep="last").set_index("cusip", drop=False)
        return self._carry_roll_lookup_cache

    def _metric_for_leg(self, *, leg: FixedRateBondPricableSpec, column: str) -> float:
        lookup = self._carry_roll_lookup()
        if lookup.empty or column not in lookup.columns:
            return float("nan")

        leg_key = str(leg.cusip)
        if leg_key not in lookup.index:
            pr = self.common_kwargs["pricer"].get(leg_key)
            if pr is not None:
                try:
                    meta = pr.meta() or {}
                except Exception:
                    meta = {}
                leg_key = str(meta.get("cusip") or leg_key)

        if leg_key not in lookup.index:
            return float("nan")

        val = safe_float(lookup.at[leg_key, column])
        return float("nan") if val is None else float(val)

    def _carry_roll_metric(self, *, column: str, **kwargs: Any) -> float:
        total = 0.0
        for i, leg in enumerate(kwargs["package"]):
            val = self._metric_for_leg(leg=leg, column=column)
            if pd.isna(val):
                return float("nan")
            total += kwargs["risk_weights"][i] * float(val)
        return float(total)

    def _ytm(self, **kwargs: Any) -> float:
        return calc_spread_rate(kwargs["pricer"], kwargs["package"], kwargs["risk_weights"]) * _frb_structure_legs_mapper[len(kwargs["package"])][1]

    def _clean_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).clean_price() for leg in kwargs["package"])

    def _dirty_price(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).dirty_price(notional=leg.notional) for leg in kwargs["package"])

    def _npv(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).npv(notional=leg.notional) for leg in kwargs["package"])

    def _pv01(self, **kwargs: Any) -> float:
        return sum(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).pv01(notional=leg.notional) for leg in kwargs["package"])

    def _dv01(self, **kwargs: Any) -> float:
        return self._pv01(**kwargs)

    def _mod_duration(self, **kwargs: Any) -> float:
        return sum(
            kwargs["risk_weights"][i] * abs(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).mod_duration())
            for i, leg in enumerate(kwargs["package"])
        )

    def _carry_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"carry_{label}_bps", **kwargs)

    def _roll_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"roll_{label}_bps", **kwargs)

    def _carry_and_roll_bps_running(self, **kwargs: Any) -> float:
        label, _, _ = normalize_horizon_spec(kwargs.get("horizon"))
        return self._carry_roll_metric(column=f"carry_and_roll_{label}_bps", **kwargs)

    def _convexity(self, **kwargs: Any) -> float:
        return sum(
            kwargs["risk_weights"][i] * abs(_rebuild_pricer(_resolve_leg_pricer(kwargs["pricer"], leg), leg).convexity())
            for i, leg in enumerate(kwargs["package"])
        )
