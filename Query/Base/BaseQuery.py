from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

from typing import List, Optional, Union, Any, Dict, Tuple

import datetime

from Query.Base._GenericPricable import _GenericPricable
from Query.Base.product_adapter import get_adapter


@dataclass(frozen=True)
class BaseQuery(ABC):
    """
    Product-agnostic entry point for the backtester.

    You hand this object to the engine. At each timestep:
      1) The engine calls build_mdp_request(now) -> dict to fetch a pricer/curve from the MDP
      2) Using the product adapter, the engine resolves (package, risk_weights) = StructureMap.apply(...)
      3) Using the product adapter, the engine values via ValueMap.apply(...)

    Fields:
      product:          logical product name used to select an adapter (e.g., "IRS", "Swaption")
      structure_id:     product-specific identifier (enum or str) for outright/curve/fly/etc.
      structure_kwargs: dict of product-specific build params (tenor, dates, notional/bpv, side, strikes, …)
      value_id:         (optional) default value metric (enum/str) for quick one-off valuation
      value_ids:        (optional) additional metrics to compute/record
      market_request:   dict template consumed by your MarketDataProvider.get_pricer(request)
                        e.g., {"curve_name": "USD-SOFR-1D", "timestamp": "live"}
      mdp_time_key:     which key within market_request should receive the per-timestep time (default "timestamp")
      name/tags/meta:   display and audit helpers
    """

    product: str = field(init=False, default="")
    structure_id: Any = field(init=False, default=None)
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_id: Optional[Any] = None
    value_ids: Tuple[Any, ...] = tuple()
    market_request: Dict[str, Any] = field(default_factory=dict)
    mdp_time_key: str = "timestamp"
    name: Optional[str] = None
    tags: Tuple[str, ...] = tuple()
    meta: Dict[str, Any] = field(default_factory=dict)

    def build_mdp_request(self, now: datetime.datetime) -> Dict[str, Any]:
        """
        Build the request dict for MDP.get_pricer(request) at time 'now'.
        Policy:
          - If mdp_time_key missing -> inject 'now.date()'
          - If mdp_time_key == "live" or already set -> pass through unchanged
          - If mdp_time_key == "now" -> inject full datetime
        """
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = now
            # "live" or concrete value: leave as-is
        return req

    def _edited(self, pricer_or_curve: Any) -> "BaseQuery":
        """
        Run this query through the product adapter's edit pass.
        Adapters that don't override edit_query will noop.
        """
        adapter_cls = get_adapter(self.product)
        adapter = adapter_cls()
        return adapter.edit_query(q=self, pricer_or_curve=pricer_or_curve)

    def resolve_package(
        self,
        *,
        pricer_or_curve: Any,
        **hints: Any,
    ) -> Tuple[List[_GenericPricable], List[float]]:
        """
        Resolve this query into a concrete package of priceables + weights using the product adapter.
        """
        adapter_cls = get_adapter(self.product)
        adapter = adapter_cls()
        struct_map = adapter.build_structure_map(pricer_or_curve=pricer_or_curve)

        kwargs = {k: v for k, v in (self.structure_kwargs or {}).items() if v is not None}
        for k, v in (hints or {}).items():
            kwargs[k] = v

        package, weights = struct_map.apply(self.structure_id, **kwargs)
        return package, weights

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        """
        Get the value map bound to (pricer/curve, package, weights) via the product adapter.
        """
        adapter_cls = get_adapter(self.product)
        adapter = adapter_cls()
        return adapter.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=package,
            risk_weights=risk_weights,
        )

    # -------- MTM metric selection (product-agnostic) --------
    def default_mtm_value_id(self) -> Any:
        if getattr(self, "value_id", None) is not None:
            return self.value_id
        vids = getattr(self, "value_ids", ()) or ()
        return vids[0] if len(vids) > 0 else None

    # -------- Convenience & identity --------

    def signature(self) -> str:
        """
        Stable identifier for logging/portfolio keys (if you choose to store queries).
        """
        parts: List[str] = [f"product={self.product}", f"struct={self._coerce(self.structure_id)}"]
        for k, v in sorted((self.structure_kwargs or {}).items()):
            parts.append(f"{k}={self._coerce(v)}")
        if self.value_id is not None:
            parts.append(f"value={self._coerce(self.value_id)}")
        if self.tags:
            parts.append("tags=" + ",".join(map(str, self.tags)))
        if self.name:
            parts.append(f"name={self.name}")
        return "|".join(parts)

    def _coerce(self, v: Any) -> str:
        try:
            return f"{v:.10g}" if isinstance(v, float) else str(v)
        except Exception:
            return repr(v)

    @abstractmethod
    def return_query(self) -> Union["BaseQuery", List["BaseQuery"]]: ...

    @abstractmethod
    def col_name(self, cube_name: Optional[str] = None) -> str: ...

    @abstractmethod
    def eval_expression(self, cube_name: Optional[str] = None) -> str: ...

    def __pos__(self) -> "BaseQuery":
        return self

    def __neg__(self) -> "BaseQuery":
        new_weight = -(self.risk_weight or 1)
        return replace(self, risk_weight=new_weight)

    def __add__(self, other: object) -> List["BaseQuery"]:
        if not isinstance(other, BaseQuery):
            return NotImplemented
        return [self * 1, other * 1]

    def __radd__(self, other: object) -> List["BaseQuery"]:
        return self.__add__(other)

    def __sub__(self, other: object) -> List["BaseQuery"]:
        if not isinstance(other, BaseQuery):
            return NotImplemented
        return [self * 1, other * -1]

    def __rsub__(self, other: object) -> List["BaseQuery"]:
        if not isinstance(other, BaseQuery):
            return NotImplemented
        return [other * 1, self * -1]

    def __mul__(self, scalar: object) -> List["BaseQuery"]:
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        new_weight = (self.risk_weight or 1) * scalar
        return replace(self, risk_weight=new_weight)

    def __rmul__(self, scalar: object) -> List["BaseQuery"]:
        return self.__mul__(scalar)

    def __truediv__(self, scalar: object) -> List["BaseQuery"]:
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return self * (1.0 / scalar)

    def __rtruediv__(self, scalar: object) -> List["BaseQuery"]:
        return NotImplemented
