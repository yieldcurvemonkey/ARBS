from __future__ import annotations

from typing import Any

from Query.Unified.registry import ProductDescriptor, UnifiedValue


class UnifiedValueMap:
    def __init__(self, *, descriptor: ProductDescriptor, legacy_value_map: Any):
        self._descriptor = descriptor
        self._legacy_value_map = legacy_value_map

    @property
    def descriptor(self) -> ProductDescriptor:
        return self._descriptor

    @property
    def legacy_value_map(self) -> Any:
        return self._legacy_value_map

    def apply(self, value: UnifiedValue | Any, **kwargs: Any) -> Any:
        if isinstance(value, UnifiedValue):
            local_value = self._descriptor.to_local_value(value)
        else:
            local_value = value
        return self._legacy_value_map.apply(value=local_value, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._legacy_value_map, name)
