from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.USTFutureOptions.USTFutureOptionStructure import USTFutureOptionStructureFunctionMap
from Query.USTFutureOptions.USTFutureOptionValue import USTFutureOptionValueFunctionMap
from Query.USTFutureOptions._USTFutureOptionGenericPricer import _USTFutureOptionGenericPricer


def _flatten_ust_option_pricers(pr: Any) -> Dict[str, _USTFutureOptionGenericPricer]:
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")

    out: "OrderedDict[str, _USTFutureOptionGenericPricer]" = OrderedDict()

    for k, v in pr.items():
        if isinstance(v, list):
            if len(v) == 1:
                p = v[0]
                if not isinstance(p, _USTFutureOptionGenericPricer):
                    raise TypeError(f"Expected _USTFutureOptionGenericPricer in list, got {type(p)} (key={k})")
                alias_key = str(k)
                if alias_key in out:
                    alias_key = p.id() if hasattr(p, "id") else f"{k}#0"
                out[alias_key] = p
            else:
                for i, p in enumerate(v):
                    if not isinstance(p, _USTFutureOptionGenericPricer):
                        raise TypeError(f"Expected _USTFutureOptionGenericPricer in list, got {type(p)} (key={k})")
                    leg_key = p.id() if hasattr(p, "id") else f"{k}#{i}"
                    if leg_key in out:
                        leg_key = f"{k}#{i}"
                    out[leg_key] = p
        else:
            if not isinstance(v, _USTFutureOptionGenericPricer):
                raise TypeError(f"Expected _USTFutureOptionGenericPricer, got {type(v)} (key={k})")
            out[str(k)] = v

    return out


class USTFutureOptionProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        pricer = _flatten_ust_option_pricers(pricer_or_curve)
        return USTFutureOptionStructureFunctionMap(pricer=pricer)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        pricer = _flatten_ust_option_pricers(pricer_or_curve)
        return USTFutureOptionValueFunctionMap(pricer=pricer, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q, pricer_or_curve):
        return q


register_product("USTFUTUREOPTION", USTFutureOptionProductAdapter)

from BT.position_handler import register_handler
from Query.USTFutureOptions.position_handler import USTFutureOptionHandler

register_handler("USTFUTUREOPTION", USTFutureOptionHandler)
