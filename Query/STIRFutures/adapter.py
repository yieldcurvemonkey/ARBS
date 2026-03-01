from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructureFunctionMap
from Query.STIRFutures.STIRFutureValue import STIRFutureValueFunctionMap
from Query.STIRFutures._STIRFutureGenericPricer import _STIRFutureGenericPricer


def _flatten_stir_pricers(pr: Any) -> Dict[str, _STIRFutureGenericPricer]:
    """
    Normalizes STIR MDP output into Dict[key, _STIRFutureGenericPricer].

    Accepts:
      - Dict[str, _STIRFutureGenericPricer]
      - Dict[str, List[_STIRFutureGenericPricer]]  (e.g. {"whites": [p1,p2,p3,p4]})
    """
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")

    out: "OrderedDict[str, _STIRFutureGenericPricer]" = OrderedDict()

    for k, v in pr.items():
        if isinstance(v, list):
            for i, p in enumerate(v):
                if not isinstance(p, _STIRFutureGenericPricer):
                    raise TypeError(f"Expected _STIRFutureGenericPricer in list, got {type(p)} (key={k})")
                # prefer stable instrument id as key if available
                leg_key = p.id() if hasattr(p, "id") else f"{k}#{i}"
                # avoid accidental collisions
                if leg_key in out:
                    leg_key = f"{leg_key}#{i}"
                out[leg_key] = p
        else:
            if not isinstance(v, _STIRFutureGenericPricer):
                raise TypeError(f"Expected _STIRFutureGenericPricer, got {type(v)} (key={k})")
            out[k] = v

    return out


class STIRFutureProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        pricer = _flatten_stir_pricers(pricer_or_curve)
        return STIRFutureStructureFunctionMap(pricer=pricer)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        pricer = _flatten_stir_pricers(pricer_or_curve)
        return STIRFutureValueFunctionMap(pricer=pricer, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q, pricer_or_curve):
        return q


register_product("STIRFUTURE", STIRFutureProductAdapter)

from BT.position_handler import register_handler
from Query.STIRFutures.position_handler import STIRFutureHandler
register_handler("STIRFUTURE", STIRFutureHandler)
