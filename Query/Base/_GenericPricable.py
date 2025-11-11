# ABOUTME: Generic marker interface for pricable instruments
# ABOUTME: Used for type constraints in product adapters and pricers
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Any


class _GenericPricable(ABC):
    pass


_GP = TypeVar("_GP", bound=_GenericPricable)
