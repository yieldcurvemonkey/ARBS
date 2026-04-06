import datetime
from abc import ABC, abstractmethod

from Query.Base._GenericPricable import _GenericPricable


class _FixedRateBondGenericPricable(_GenericPricable, ABC):

    @abstractmethod
    def effective_date(self) -> datetime.date: ...

    @abstractmethod
    def maturity_date(self) -> datetime.date: ...

    @abstractmethod
    def coupon(self) -> float: ...

    @abstractmethod
    def nominal(self) -> float: ...

    @abstractmethod
    def ytm(self) -> float: ...

    @abstractmethod
    def dirty_price(self) -> float: ...

    @abstractmethod
    def clean_price(self) -> float: ...

    @abstractmethod
    def npv(self) -> float: ...

    @abstractmethod
    def accured(self) -> float: ...

    @abstractmethod
    def pv01(self) -> float: ...

    @abstractmethod
    def mod_duration(self) -> float: ...

    @abstractmethod
    def convexity(self) -> float: ...

    # TODO carry, roll
