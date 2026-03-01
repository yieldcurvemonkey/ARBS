import datetime
from abc import ABC, abstractmethod

from Query.Base._GenericPricable import _GenericPricable


class _STIRFutureOptionGenericPricable(_GenericPricable, ABC):
    @abstractmethod
    def symbol(self) -> str: ...

    @abstractmethod
    def right(self) -> str: ...

    @abstractmethod
    def strike(self) -> float: ...

    @abstractmethod
    def expiry_date(self) -> datetime.date: ...

    @abstractmethod
    def quote_timestamp(self) -> datetime.datetime: ...

    @abstractmethod
    def quantity(self) -> float: ...
