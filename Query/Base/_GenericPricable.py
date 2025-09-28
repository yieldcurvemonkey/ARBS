from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Any


class _GenericPricable(ABC):
    pass


_GP = TypeVar("_GP", bound=_GenericPricable)
