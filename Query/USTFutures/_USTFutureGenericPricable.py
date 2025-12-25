import datetime
from abc import ABC, abstractmethod

from Query.Base._GenericPricable import _GenericPricable


class _USTFutureGenericPricable(_GenericPricable, ABC):

    @abstractmethod
    def contract_code(self) -> str: ...

    @abstractmethod
    def effective_date(self) -> datetime.date: ...

    @abstractmethod
    def maturity_date(self) -> datetime.date: ...

    @abstractmethod
    def price(self) -> float: ...

    @abstractmethod
    def contracts(self) -> int: ...

    @abstractmethod
    def notional(self) -> float: ...
