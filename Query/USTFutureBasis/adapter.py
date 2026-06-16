from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Mapping

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import ProductAdapter, register_product
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer
from Query.USTFutureBasis.USTFutureBasisStructure import USTFutureBasisStructureFunctionMap
from Query.USTFutureBasis.USTFutureBasisValue import USTFutureBasisValueFunctionMap


def _wrap_as_basis(pr: Any) -> Dict[str, RLUSTFutureBasisPricer]:
    """Wrap the MDP's UST-future pricers into basis pricers (CTD-default)."""
    if not isinstance(pr, Mapping):
        raise TypeError(f"Expected pricer mapping, got {type(pr)}")
    out: "OrderedDict[str, RLUSTFutureBasisPricer]" = OrderedDict()
    for k, v in pr.items():
        if isinstance(v, RLUSTFutureBasisPricer):
            out[k] = v
            continue
        if isinstance(v, list):
            for i, p in enumerate(v):
                out[f"{k}#{i}" if k in out else k] = RLUSTFutureBasisPricer(p)
            continue
        if not isinstance(v, _USTFutureGenericPricer):
            raise TypeError(f"Expected UST future pricer, got {type(v)} (key={k})")
        out[k] = RLUSTFutureBasisPricer(v)
    return out


class USTFutureBasisProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        return USTFutureBasisStructureFunctionMap(pricer=_wrap_as_basis(pricer_or_curve))

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return USTFutureBasisValueFunctionMap(
            pricer=_wrap_as_basis(pricer_or_curve),
            package=package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q: Any, pricer_or_curve: Any) -> Any:
        return q


register_product("USTFUTUREBASIS", USTFutureBasisProductAdapter)

# Register the PnL position handler with the backtest engine.
from BT.position_handler import register_handler
from Query.USTFutureBasis.position_handler import USTFutureBasisHandler

register_handler("USTFUTUREBASIS", USTFutureBasisHandler)
