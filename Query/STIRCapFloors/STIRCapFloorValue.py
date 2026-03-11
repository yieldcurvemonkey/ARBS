from __future__ import annotations

import math
from enum import Enum, auto
from typing import Any, Callable, Dict, Iterable, Tuple

import QuantLib as ql

from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMarketContext
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.STIRCapFloors.pricer import STIRCapFloorLegPricable, build_leg_breakdown
from Query.STIRFutureOptions._risk import dollar_dv01, dollar_gamma_01, dollar_vega_01, resolve_pricer_for_leg


class STIRCapFloorValue(Enum):
    PRICE = auto()
    NPV = auto()
    BPVOL = auto()
    FLAT_BP_VOL = auto()
    DV01 = auto()
    DELTA = auto()
    GAMMA = auto()
    GAMMA_01 = auto()
    VEGA = auto()
    VEGA_01 = auto()
    THETA = auto()
    BREAKDOWN = auto()


class STIRCapFloorValueFunctionMap(BaseValueFunctionMap[STIRCapFloorValue, Any]):
    def __init__(
        self,
        *,
        context: STIRCapFloorMarketContext,
        package: list[STIRCapFloorLegPricable],
        risk_weights: list[float],
    ):
        super().__init__(STIRCapFloorValue, context=context, package=package, risk_weights=risk_weights)

    def _create_map(self) -> Dict[STIRCapFloorValue, Callable[..., Any]]:
        return {
            STIRCapFloorValue.PRICE: self._price,
            STIRCapFloorValue.NPV: self._npv,
            STIRCapFloorValue.BPVOL: self._bpvol,
            STIRCapFloorValue.FLAT_BP_VOL: self._flat_bp_vol,
            STIRCapFloorValue.DV01: self._dv01,
            STIRCapFloorValue.DELTA: self._delta,
            STIRCapFloorValue.GAMMA: self._gamma,
            STIRCapFloorValue.GAMMA_01: self._gamma_01,
            STIRCapFloorValue.VEGA: self._vega,
            STIRCapFloorValue.VEGA_01: self._vega_01,
            STIRCapFloorValue.THETA: self._theta,
            STIRCapFloorValue.BREAKDOWN: self._breakdown,
        }

    @staticmethod
    def _iter_components(
        *,
        context: STIRCapFloorMarketContext,
        package: list[STIRCapFloorLegPricable],
        risk_weights: list[float],
        **_: Any,
    ) -> Iterable[Tuple[int, float, Any, STIRCapFloorLegPricable, float]]:
        pricers = context.pricers
        for idx, (rw, leg) in enumerate(zip(risk_weights, package)):
            pricer = resolve_pricer_for_leg(pricers, leg, index=idx)
            qty = float(leg.quantity())
            yield idx, float(rw), pricer, leg, qty

    @staticmethod
    def _unit_weight_total(
        *,
        context: STIRCapFloorMarketContext,
        package: list[STIRCapFloorLegPricable],
        risk_weights: list[float],
        **_: Any,
    ) -> float:
        total = sum(abs(float(rw)) * abs(float(leg.unit_quantity())) for rw, leg in zip(risk_weights, package))
        return float(total if total > 0.0 else 1.0)

    def _strip_price_with_flat_sigma(self, sigma: float, **kwargs: Any) -> float:
        total = 0.0
        context = kwargs["context"]
        for _, rw, pricer, leg, _ in self._iter_components(**kwargs):
            tte = max((pricer.expiry_date() - context.as_of_date).days / 365.0, 1e-12)
            stddev = max(float(sigma), 0.0) * math.sqrt(float(tte))
            option_type = ql.Option.Call if str(pricer.right()).upper() == "C" else ql.Option.Put
            total += float(rw) * float(leg.unit_quantity()) * float(
                ql.bachelierBlackFormula(
                    option_type,
                    float(pricer.strike()),
                    float(pricer.forward()),
                    float(stddev),
                    float(pricer.discount()),
                )
            )
        return float(total)

    def _price(self, **kwargs: Any) -> float:
        return float(sum(rw * float(leg.unit_quantity()) * float(pricer.price()) for _, rw, pricer, leg, _ in self._iter_components(**kwargs)))

    def _npv(self, **kwargs: Any) -> float:
        return float(sum(rw * float(pricer.npv(leg)) for _, rw, pricer, leg, _ in self._iter_components(**kwargs)))

    def _bpvol(self, **kwargs: Any) -> float:
        denom = self._unit_weight_total(**kwargs)
        total = sum(
            abs(float(rw)) * abs(float(leg.unit_quantity())) * float(pricer.iv_normal_bps())
            for _, rw, pricer, leg, _ in self._iter_components(**kwargs)
        )
        return float(total / denom)

    def _flat_bp_vol(self, **kwargs: Any) -> float:
        target_price = float(self._price(**kwargs))
        if target_price <= 0.0:
            return 0.0

        lo = 1e-8
        hi = 1.0
        for _ in range(32):
            if self._strip_price_with_flat_sigma(hi, **kwargs) >= target_price:
                break
            hi *= 2.0
        else:
            raise ValueError("Could not bracket FLAT_BP_VOL for STIR cap/floor strip.")

        for _ in range(80):
            mid = 0.5 * (lo + hi)
            price_mid = self._strip_price_with_flat_sigma(mid, **kwargs)
            if price_mid < target_price:
                lo = mid
            else:
                hi = mid
        return float(0.5 * (lo + hi) * 100.0)

    def _dv01(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(dollar_dv01(pricer)) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _delta(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(pricer.delta()) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _gamma(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(pricer.gamma()) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _gamma_01(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(dollar_gamma_01(pricer)) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _vega(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(pricer.vega()) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _vega_01(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(dollar_vega_01(pricer)) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _theta(self, **kwargs: Any) -> float:
        return float(sum(rw * qty * float(pricer.theta()) for _, rw, pricer, _, qty in self._iter_components(**kwargs)))

    def _breakdown(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            build_leg_breakdown(leg, pricer, index=idx, risk_weight=rw)
            for idx, rw, pricer, leg, _ in self._iter_components(**kwargs)
        ]
