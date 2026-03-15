from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.FXForwards._FXForwardGenericPricer import _FXForwardGenericPricer
from Query.FXForwards.FXForwardStructure import FXForwardStructureFunctionMap
from Query.FXForwards.FXForwardValue import FXForwardValueFunctionMap


def _flatten_fx_forward_pricers(pr: Any) -> Dict[str, _FXForwardGenericPricer]:
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")

    out: "OrderedDict[str, _FXForwardGenericPricer]" = OrderedDict()
    for key, value in pr.items():
        if isinstance(value, list):
            if len(value) != 1 or not isinstance(value[0], _FXForwardGenericPricer):
                raise TypeError(f"Expected singleton FX forward pricer list for key={key!r}")
            out[str(key)] = value[0]
        else:
            if not isinstance(value, _FXForwardGenericPricer):
                raise TypeError(f"Expected FX forward pricer for key={key!r}, got {type(value)}")
            out[str(key)] = value
    return out


class FXForwardProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return FXForwardStructureFunctionMap(pricer=_flatten_fx_forward_pricers(pricer_or_curve))

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return FXForwardValueFunctionMap(
            pricer=_flatten_fx_forward_pricers(pricer_or_curve),
            package=package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q, pricer_or_curve):
        _ = pricer_or_curve
        return q


register_product("FXFORWARD", FXForwardProductAdapter)
