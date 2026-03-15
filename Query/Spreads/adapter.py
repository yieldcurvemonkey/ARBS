from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Tuple

from Query.Base.product_adapter import ProductAdapter, register_product
from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue


@dataclass
class SpreadLegPair:
    """A pair of instruments (one from each leg) at a given tenor."""
    inst_a: Any
    inst_b: Any
    tenor: str = ""


class SpreadStructureFunctionMap(BaseStructureFunctionMap[SpreadStructure, SpreadLegPair]):
    def __init__(self, pricer_a: Any, pricer_b: Any, **common_kwargs: Any):
        self._pricer_a = pricer_a
        self._pricer_b = pricer_b
        super().__init__(SpreadStructure, pricer_a=pricer_a, pricer_b=pricer_b, **common_kwargs)

    def _create_map(self) -> Dict[SpreadStructure, Callable[..., Tuple[List[SpreadLegPair], List[float]]]]:
        return {
            SpreadStructure.OUTRIGHT: self._build_outright,
            SpreadStructure.CURVE: self._build_curve,
            SpreadStructure.FLY: self._build_fly,
        }

    def _filter_build_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only the kwargs relevant for build_irswap (bpv, notional)."""
        out = {}
        if "bpv" in kwargs:
            out["bpv"] = kwargs["bpv"]
        elif "notional" in kwargs:
            out["notional"] = kwargs["notional"]
        return out

    def _build_leg_pair(self, tenor: str, build_kwargs: Dict[str, Any]) -> SpreadLegPair:
        build_kw = {"tenor": tenor, **build_kwargs}
        inst_a = self._pricer_a.build_irswap(**build_kw)
        inst_b = self._pricer_b.build_irswap(**build_kw)
        return SpreadLegPair(inst_a=inst_a, inst_b=inst_b, tenor=tenor)

    def _build_outright(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        tenor = kwargs.get("tenor", "5Y")
        bkw = self._filter_build_kwargs(kwargs)
        pair = self._build_leg_pair(tenor, bkw)
        return [pair], [1.0]

    def _build_curve(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        ft = kwargs["front_tenor"]
        bt = kwargs["back_tenor"]
        bkw = self._filter_build_kwargs(kwargs)
        front_pair = self._build_leg_pair(ft, bkw)
        back_pair = self._build_leg_pair(bt, bkw)
        return [front_pair, back_pair], [-1.0, 1.0]

    def _build_fly(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        ft = kwargs["front_tenor"]
        belly = kwargs["belly_tenor"]
        bt = kwargs["back_tenor"]
        bkw = self._filter_build_kwargs(kwargs)
        return (
            [self._build_leg_pair(ft, bkw), self._build_leg_pair(belly, bkw), self._build_leg_pair(bt, bkw)],
            [-0.5, 1.0, -0.5],
        )


class SpreadValueFunctionMap(BaseValueFunctionMap[SpreadValue, float]):
    def __init__(
        self,
        pricer_a: Any,
        pricer_b: Any,
        package: List[SpreadLegPair],
        risk_weights: List[float],
    ):
        self._pricer_a = pricer_a
        self._pricer_b = pricer_b
        super().__init__(
            SpreadValue,
            pricer_a=pricer_a,
            pricer_b=pricer_b,
            package=package,
            risk_weights=risk_weights,
        )

    def _create_map(self) -> Dict[SpreadValue, Callable[..., float]]:
        return {
            SpreadValue.SPREAD_RATE: self._spread_rate,
            SpreadValue.SPREAD_BPS: self._spread_bps,
            SpreadValue.LEG_A_RATE: self._leg_a_rate,
            SpreadValue.LEG_B_RATE: self._leg_b_rate,
            SpreadValue.PV01: self._pv01,
            SpreadValue.NPV: self._npv,
            SpreadValue.CVX_ADJ_EMPIRICAL: self._spread_bps,
            SpreadValue.CVX_ADJ_HW1F: self._cvx_adj_hw1f,
        }

    def _spread_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(
            rws[i] * (pa.fair_rate(pair.inst_a) - pb.fair_rate(pair.inst_b))
            for i, pair in enumerate(package)
        )

    def _spread_bps(self, **kw) -> float:
        return self._spread_rate(**kw) * 10_000

    def _leg_a_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pa = kw["pricer_a"]
        total = sum(rws[i] * pa.fair_rate(pair.inst_a) for i, pair in enumerate(package))
        n_legs = len(package)
        scale = 1.0 if n_legs == 1 else 10_000
        return total * scale

    def _leg_b_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pb = kw["pricer_b"]
        total = sum(rws[i] * pb.fair_rate(pair.inst_b) for i, pair in enumerate(package))
        n_legs = len(package)
        scale = 1.0 if n_legs == 1 else 10_000
        return total * scale

    def _pv01(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(pa.pv01(p.inst_a) + pb.pv01(p.inst_b) for p in package)

    def _npv(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(pa.npv(p.inst_a) - pb.npv(p.inst_b) for p in package)

    def _cvx_adj_hw1f(self, **kw) -> float:
        raise NotImplementedError("HW1F convexity adjustment requires hw1f_model — see STIRConvexityAdjustmentMDP")


class SpreadProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> SpreadStructureFunctionMap:
        return SpreadStructureFunctionMap(
            pricer_a=pricer_or_curve.pricer_a,
            pricer_b=pricer_or_curve.pricer_b,
        )

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[Any],
        risk_weights: List[float],
    ) -> SpreadValueFunctionMap:
        return SpreadValueFunctionMap(
            pricer_a=pricer_or_curve.pricer_a,
            pricer_b=pricer_or_curve.pricer_b,
            package=package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


register_product("IRSPREAD", SpreadProductAdapter)
register_product("IRBASIS", SpreadProductAdapter)
register_product("IRCHBASIS", SpreadProductAdapter)
register_product("STIRCVX", SpreadProductAdapter)
