import QuantLib as ql

from abc import ABC, abstractmethod
from enum import Enum
from typing import Type, TypeVar, Generic, Dict, Callable, Any

E = TypeVar("E", bound=Enum)
R = TypeVar("R")


class BaseValueFunctionMap(ABC, Generic[E, R]):

    def __init__(self, value_enum: Type[E], **common_kwargs: Any):
        self._value_enum = value_enum
        self.common_kwargs = common_kwargs
        self._map: Dict[E, Callable[..., R]] = self._create_map()

    @abstractmethod
    def _create_map(self) -> Dict[E, Callable[..., R]]: ...

    def apply(self, value: E, **extra_kwargs: Any) -> R:
        if value not in self._map:
            raise KeyError(f"Value '{value}' is not supported.")
        func = self._map[value]
        # Merge common and extra kwargs
        kwargs = {**self.common_kwargs, **extra_kwargs}
        return func(**kwargs)
