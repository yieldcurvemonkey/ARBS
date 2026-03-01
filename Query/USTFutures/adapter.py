from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.USTFutures.USTFutureStructure import USTFutureStructureFunctionMap
from Query.USTFutures.USTFutureValue import USTFutureValueFunctionMap
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer


def _flatten_ust_pricers(pr: Any) -> Dict[str, _USTFutureGenericPricer]:
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")

    out: "OrderedDict[str, _USTFutureGenericPricer]" = OrderedDict()

    for k, v in pr.items():
        if isinstance(v, list):
            for i, p in enumerate(v):
                if not isinstance(p, _USTFutureGenericPricer):
                    raise TypeError(f"Expected _USTFutureGenericPricer in list, got {type(p)} (key={k})")
                leg_key = p.id() if hasattr(p, "id") else f"{k}#{i}"
                if leg_key in out:
                    leg_key = f"{leg_key}#{i}"
                out[leg_key] = p
        else:
            if not isinstance(v, _USTFutureGenericPricer):
                raise TypeError(f"Expected _USTFutureGenericPricer, got {type(v)} (key={k})")
            out[k] = v

    return out


class USTFutureProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        pricer = _flatten_ust_pricers(pricer_or_curve)
        return USTFutureStructureFunctionMap(pricer=pricer)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        pricer = _flatten_ust_pricers(pricer_or_curve)
        return USTFutureValueFunctionMap(pricer=pricer, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q, pricer_or_curve):
        return q


register_product("USTFUTURE", USTFutureProductAdapter)

from BT.position_handler import register_handler
from Query.USTFutures.position_handler import USTFutureHandler
register_handler("USTFUTURE", USTFutureHandler)
