from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from Query.Base.BaseQuery import BaseQuery
from Query.Unified.UnifiedValueMap import UnifiedValueMap
from Query.Unified.registry import DESCRIPTOR_REGISTRY, UnifiedStructure, UnifiedValue


@dataclass(frozen=True)
class UnifiedQuery(BaseQuery):
    product: Optional[str] = None
    structure: Optional[UnifiedStructure | str | Any] = None
    value: Optional[UnifiedValue | Sequence[UnifiedValue] | str | Any] = None
    selector: Mapping[str, Any] = field(default_factory=dict)
    curve: Any = None
    tenor: Any = None

    structure_kwargs: Mapping[str, Any] = field(default_factory=dict)
    value_kwargs: Mapping[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        selector = dict(self.selector or {})
        for key, direct_value in (("curve", self.curve), ("tenor", self.tenor)):
            if direct_value is None:
                continue
            existing_value = selector.get(key)
            if existing_value is not None and existing_value != direct_value:
                raise ValueError(f"UnifiedQuery received conflicting {key!r}: selector={existing_value!r}, direct={direct_value!r}")
            selector.setdefault(key, direct_value)

        normalized_structure = DESCRIPTOR_REGISTRY.coerce_structure(self.structure, product=self.product)
        normalized_value = DESCRIPTOR_REGISTRY.coerce_values(self.value, product=self.product)
        inferred_product = DESCRIPTOR_REGISTRY.infer_query_product(
            product=self.product,
            structure=normalized_structure,
            value=normalized_value,
            selector=selector,
        )

        object.__setattr__(self, "product", inferred_product or str(self.product or ""))
        object.__setattr__(self, "structure", normalized_structure)
        object.__setattr__(self, "value", normalized_value)
        object.__setattr__(self, "selector", selector)
        object.__setattr__(self, "curve", selector.get("curve"))
        object.__setattr__(self, "tenor", selector.get("tenor"))
        object.__setattr__(self, "structure_kwargs", dict(self.structure_kwargs or {}))
        object.__setattr__(self, "value_kwargs", dict(self.value_kwargs or {}))
        object.__setattr__(self, "market_request", dict(self.market_request or {}))
        object.__setattr__(self, "meta", dict(self.meta or {}))
        object.__setattr__(self, "tags", tuple(self.tags or ()))
        object.__setattr__(self, "structure_id", normalized_structure)

        if isinstance(normalized_value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(normalized_value))
        else:
            object.__setattr__(self, "value_id", normalized_value)
            object.__setattr__(self, "value_ids", tuple())

    def _translated_legacy(self) -> tuple[Any, BaseQuery]:
        return DESCRIPTOR_REGISTRY.resolve(
            product=self.product or None,
            structure=self.structure,
            value=self.value,
            selector=self.selector,
            structure_kwargs=self.structure_kwargs,
            market_request=self.market_request,
            value_kwargs=self.value_kwargs,
            name=self.name,
            tags=self.tags,
            meta=self.meta,
            risk_weight=self.risk_weight,
        )

    def to_legacy(self) -> BaseQuery:
        _, legacy = self._translated_legacy()
        return legacy

    @classmethod
    def from_legacy(cls, query: BaseQuery) -> "UnifiedQuery":
        descriptor = DESCRIPTOR_REGISTRY.descriptor_for_legacy_query(query)
        selector: dict[str, Any] = {}

        for key in descriptor.ctor_selector_keys:
            if hasattr(query, key):
                value = getattr(query, key)
                if value is not None:
                    selector[key] = value

        structure_kwargs = dict(getattr(query, "structure_kwargs", {}) or {})
        for key in descriptor.structure_selector_keys:
            value = structure_kwargs.get(key)
            if value is not None:
                selector[key] = value

        local_value = getattr(query, "value", None)
        if isinstance(local_value, list):
            unified_value = [descriptor.to_unified_value(item) for item in local_value]
        else:
            unified_value = descriptor.to_unified_value(local_value) if local_value is not None else None

        local_structure = getattr(query, "structure", None)
        unified_structure = descriptor.to_unified_structure(local_structure) if local_structure is not None else None

        return cls(
            product=query.product,
            structure=unified_structure,
            value=unified_value,
            selector=selector,
            structure_kwargs=structure_kwargs,
            market_request=dict(query.market_request or {}),
            value_kwargs=dict(getattr(query, "value_kwargs", {}) or {}),
            risk_weight=getattr(query, "risk_weight", None),
            name=query.name,
            tags=query.tags,
            meta=dict(query.meta or {}),
        )

    def resolve_query(self, ref_dt, pricer_or_curve):
        _, legacy = self._translated_legacy()
        if hasattr(legacy, "resolve_query"):
            resolved = legacy.resolve_query(ref_dt, pricer_or_curve=pricer_or_curve)
            if not isinstance(resolved, BaseQuery):
                raise TypeError(f"{type(legacy).__name__}.resolve_query must return BaseQuery, got {type(resolved)}")
            return resolved
        return legacy

    def build_mdp_request(self, now) -> dict[str, Any]:
        legacy = self.to_legacy()
        req = dict(legacy.build_mdp_request(now))
        req.setdefault("product", legacy.product)
        return req

    def resolve_package(self, *, pricer_or_curve: Any, **hints: Any):
        legacy = self.to_legacy()
        return legacy.resolve_package(pricer_or_curve=pricer_or_curve, **hints)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: list[Any],
        risk_weights: list[float],
    ) -> UnifiedValueMap:
        descriptor, legacy = self._translated_legacy()
        legacy_value_map = legacy.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=package,
            risk_weights=risk_weights,
        )
        return UnifiedValueMap(descriptor=descriptor, legacy_value_map=legacy_value_map)

    def return_query(self) -> list["UnifiedQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=value_item) for value_item in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        legacy = self.to_legacy()
        return legacy.col_name(cube_name=cube_name)

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        legacy = self.to_legacy()
        return legacy.eval_expression(cube_name=cube_name)

    def default_mtm_value_id(self) -> Any:
        if self.value_id is not None:
            return self.value_id
        return self.value_ids[0] if self.value_ids else None
