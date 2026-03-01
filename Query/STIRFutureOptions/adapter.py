from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructureFunctionMap
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValueFunctionMap
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import _STIRFutureOptionGenericPricer


def _flatten_stir_option_pricers(pr: Any) -> Dict[str, _STIRFutureOptionGenericPricer]:
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")

    out: "OrderedDict[str, _STIRFutureOptionGenericPricer]" = OrderedDict()

    for k, v in pr.items():
        if isinstance(v, list):
            if len(v) == 1:
                p = v[0]
                if not isinstance(p, _STIRFutureOptionGenericPricer):
                    raise TypeError(f"Expected _STIRFutureOptionGenericPricer in list, got {type(p)} (key={k})")
                alias_key = str(k)
                if alias_key in out:
                    alias_key = p.id() if hasattr(p, "id") else f"{k}#0"
                out[alias_key] = p
            else:
                for i, p in enumerate(v):
                    if not isinstance(p, _STIRFutureOptionGenericPricer):
                        raise TypeError(f"Expected _STIRFutureOptionGenericPricer in list, got {type(p)} (key={k})")
                    leg_key = p.id() if hasattr(p, "id") else f"{k}#{i}"
                    if leg_key in out:
                        leg_key = f"{k}#{i}"
                    out[leg_key] = p
        else:
            if not isinstance(v, _STIRFutureOptionGenericPricer):
                raise TypeError(f"Expected _STIRFutureOptionGenericPricer, got {type(v)} (key={k})")
            out[str(k)] = v

    return out


class STIRFutureOptionProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        pricer = _flatten_stir_option_pricers(pricer_or_curve)
        return STIRFutureOptionStructureFunctionMap(pricer=pricer)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        pricer = _flatten_stir_option_pricers(pricer_or_curve)
        return STIRFutureOptionValueFunctionMap(pricer=pricer, package=package, risk_weights=risk_weights)

    def edit_query(self, *, q, pricer_or_curve):
        return q


register_product("STIRFUTUREOPTION", STIRFutureOptionProductAdapter)
