from abc import ABC, abstractmethod
from dataclasses import replace
from typing import List, Optional, Union, Any


class BaseQuery(ABC):
    value: Any
    structure: Any

    name: Optional[str] = None
    risk_weight: Optional[float] = None

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
