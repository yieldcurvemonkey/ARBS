"""Helpers for exposing package exports without eager imports."""

from __future__ import annotations

from importlib import import_module
import sys
from typing import Callable

ExportMap = dict[str, tuple[str, str | None]]


def attach_lazy_exports(
    package_name: str,
    export_map: ExportMap,
) -> tuple[list[str], Callable[[str], object], Callable[[], list[str]]]:
    """Create ``__all__``, ``__getattr__`` and ``__dir__`` for a package."""

    module = sys.modules[package_name]

    def __getattr__(name: str) -> object:
        if name not in export_map:
            raise AttributeError(f"module {package_name!r} has no attribute {name!r}")
        module_name, attribute_name = export_map[name]
        imported = import_module(module_name)
        value = imported if attribute_name is None else getattr(imported, attribute_name)
        setattr(module, name, value)
        return value

    def __dir__() -> list[str]:
        return sorted(set(module.__dict__) | set(export_map))

    return list(export_map), __getattr__, __dir__
