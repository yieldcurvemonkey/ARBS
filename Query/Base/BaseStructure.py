from abc import ABC, abstractmethod
from enum import Enum
from typing import Type, TypeVar, Generic, Dict, Callable, List, Any, Tuple

E = TypeVar("E", bound=Enum)
T = TypeVar("T")


class BaseStructureFunctionMap(ABC, Generic[E, T]):

    def __init__(self, structure_enum: Type[E], **common_kwargs: Any):
        self._structure_enum = structure_enum
        self.common_kwargs = common_kwargs
        self._map: Dict[E, Callable[..., List[T]]] = self._create_map()

    @abstractmethod
    def _create_map(self) -> Dict[E, Callable[..., List[T]]]: ...

    def apply(self, structure: E, **builder_kwargs: Any) -> Tuple[List[T], List[float]]:
        if not self._map:
            self._map = self._create_map()
        if structure not in self._map:
            self._map = self._create_map()
            raise KeyError(f"Structure '{structure}' is not supported.")
        builder = self._map[structure]
        kwargs = {**self.common_kwargs, **builder_kwargs}
        return builder(**kwargs)
